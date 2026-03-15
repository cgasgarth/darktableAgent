/*
    This file is part of darktable,
    Copyright (C) 2026 darktable developers.

    darktable is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    darktable is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with darktable.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "common/agent_client.h"

#include "common/curl_tools.h"
#include "control/conf.h"
#include "control/jobs.h"

#include <curl/curl.h>
#include <glib/gi18n.h>
#include <json-glib/json-glib.h>
#include <string.h>

struct dt_agent_client_request_t
{
  volatile gint refcount;
  volatile gint cancel_requested;
  volatile gint cancel_notified;
  gchar *request_id;
  gchar *app_session_id;
  gchar *image_session_id;
  gchar *conversation_id;
  gchar *turn_id;
  gchar *endpoint;
};

typedef struct dt_agent_client_job_t
{
  dt_agent_chat_request_t request;
  dt_agent_client_request_t *handle;
  dt_agent_client_callback_t callback;
  gpointer user_data;
  GDestroyNotify destroy;
} dt_agent_client_job_t;

typedef struct dt_agent_client_delivery_t
{
  dt_agent_client_callback_t callback;
  gpointer user_data;
  GDestroyNotify destroy;
  dt_agent_client_result_t result;
} dt_agent_client_delivery_t;

typedef struct dt_agent_client_cancel_delivery_t
{
  gchar *request_id;
  gchar *app_session_id;
  gchar *image_session_id;
  gchar *conversation_id;
  gchar *turn_id;
  gchar *endpoint;
} dt_agent_client_cancel_delivery_t;

typedef enum dt_agent_client_error_t
{
  DT_AGENT_CLIENT_ERROR_INVALID = 1,
  DT_AGENT_CLIENT_ERROR_QUEUE_UNAVAILABLE,
} dt_agent_client_error_t;

#define DT_AGENT_CLIENT_DEFAULT_TIMEOUT_SECONDS 600L

static GQuark _agent_client_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-client-error");
}

static dt_agent_client_request_t *_request_ref(dt_agent_client_request_t *request)
{
  if(request)
    g_atomic_int_inc(&request->refcount);
  return request;
}

void dt_agent_client_request_unref(dt_agent_client_request_t *request)
{
  if(!request || !g_atomic_int_dec_and_test(&request->refcount))
    return;

  g_free(request->request_id);
  g_free(request->app_session_id);
  g_free(request->image_session_id);
  g_free(request->conversation_id);
  g_free(request->turn_id);
  g_free(request->endpoint);
  g_free(request);
}

static size_t _write_response(void *ptr, size_t size, size_t nmemb, void *userdata)
{
  GString *buffer = userdata;
  const size_t bytes = size * nmemb;

  if(buffer->len + bytes > 1024 * 1024)
    return 0;

  g_string_append_len(buffer, ptr, ptr ? bytes : 0);
  return bytes;
}

static gboolean _request_cancelled(const dt_agent_client_request_t *request)
{
  return request && g_atomic_int_get(&request->cancel_requested) != 0;
}

static int _progress_callback(void *clientp,
                              curl_off_t dltotal,
                              curl_off_t dlnow,
                              curl_off_t ultotal,
                              curl_off_t ulnow)
{
  (void)dltotal;
  (void)dlnow;
  (void)ultotal;
  (void)ulnow;
  return _request_cancelled(clientp) ? 1 : 0;
}

static gchar *_cancel_endpoint_from_chat_endpoint(const gchar *endpoint)
{
  if(!endpoint || !endpoint[0])
    return g_strdup("http://127.0.0.1:8001/v1/chat/cancel");

  return g_str_has_suffix(endpoint, "/")
           ? g_strconcat(endpoint, "cancel", NULL)
           : g_strconcat(endpoint, "/cancel", NULL);
}

static gchar *_serialize_cancel_payload(const dt_agent_client_cancel_delivery_t *delivery,
                                        GError **error)
{
  JsonBuilder *builder = json_builder_new();
  json_builder_begin_object(builder);

  json_builder_set_member_name(builder, "requestId");
  json_builder_add_string_value(builder, delivery->request_id ? delivery->request_id : "");

  json_builder_set_member_name(builder, "session");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "appSessionId");
  json_builder_add_string_value(builder, delivery->app_session_id ? delivery->app_session_id : "");
  json_builder_set_member_name(builder, "imageSessionId");
  json_builder_add_string_value(builder, delivery->image_session_id ? delivery->image_session_id : "");
  json_builder_set_member_name(builder, "conversationId");
  json_builder_add_string_value(builder, delivery->conversation_id ? delivery->conversation_id : "");
  json_builder_set_member_name(builder, "turnId");
  json_builder_add_string_value(builder, delivery->turn_id ? delivery->turn_id : "");
  json_builder_end_object(builder);

  json_builder_end_object(builder);

  JsonGenerator *generator = json_generator_new();
  JsonNode *root = json_builder_get_root(builder);
  json_generator_set_root(generator, root);
  gchar *payload = json_generator_to_data(generator, NULL);

  if(!payload)
    g_set_error(error, g_quark_from_static_string("dt-agent-client-cancel"), 1,
                "%s", _("failed to serialize cancel request"));

  json_node_free(root);
  g_object_unref(generator);
  g_object_unref(builder);
  return payload;
}

static void _cancel_delivery_free(dt_agent_client_cancel_delivery_t *delivery)
{
  if(!delivery)
    return;

  g_free(delivery->request_id);
  g_free(delivery->app_session_id);
  g_free(delivery->image_session_id);
  g_free(delivery->conversation_id);
  g_free(delivery->turn_id);
  g_free(delivery->endpoint);
  g_free(delivery);
}

static gpointer _cancel_request_thread(gpointer user_data)
{
  dt_agent_client_cancel_delivery_t *delivery = user_data;
  g_autofree gchar *cancel_endpoint = _cancel_endpoint_from_chat_endpoint(delivery->endpoint);
  g_autoptr(GError) error = NULL;
  g_autofree gchar *payload = _serialize_cancel_payload(delivery, &error);

  if(!payload)
  {
    dt_print(DT_DEBUG_CONTROL, "[agent_client] failed to serialize cancel payload: %s",
             error && error->message ? error->message : "");
    _cancel_delivery_free(delivery);
    return NULL;
  }

  CURL *curl = curl_easy_init();
  if(!curl)
  {
    dt_print(DT_DEBUG_CONTROL, "[agent_client] failed to initialize cancel request client");
    _cancel_delivery_free(delivery);
    return NULL;
  }

  struct curl_slist *headers = NULL;
  headers = curl_slist_append(headers, "Accept: application/json");
  headers = curl_slist_append(headers, "Content-Type: application/json");

  dt_curl_init(curl, FALSE);
  curl_easy_setopt(curl, CURLOPT_URL, cancel_endpoint);
  curl_easy_setopt(curl, CURLOPT_POST, 1L);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(payload));
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 5L);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);

  const CURLcode curl_result = curl_easy_perform(curl);
  long http_status = 0;
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_status);
  if(curl_result != CURLE_OK)
  {
    dt_print(DT_DEBUG_CONTROL, "[agent_client] cancel request failed: curl=%d endpoint=%s",
             curl_result,
             cancel_endpoint ? cancel_endpoint : "");
  }
  else
  {
    dt_print(DT_DEBUG_CONTROL, "[agent_client] cancel request complete: http=%ld endpoint=%s",
             http_status,
             cancel_endpoint ? cancel_endpoint : "");
  }

  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);
  _cancel_delivery_free(delivery);
  return NULL;
}

void dt_agent_client_request_cancel(dt_agent_client_request_t *request)
{
  if(!request)
    return;

  g_atomic_int_set(&request->cancel_requested, 1);

  if(g_atomic_int_compare_and_exchange(&request->cancel_notified, 0, 1))
  {
    dt_agent_client_cancel_delivery_t *delivery = g_new0(dt_agent_client_cancel_delivery_t, 1);
    delivery->request_id = g_strdup(request->request_id);
    delivery->app_session_id = g_strdup(request->app_session_id);
    delivery->image_session_id = g_strdup(request->image_session_id);
    delivery->conversation_id = g_strdup(request->conversation_id);
    delivery->turn_id = g_strdup(request->turn_id);
    delivery->endpoint = g_strdup(request->endpoint);
    g_thread_unref(g_thread_new("agent-chat-cancel", _cancel_request_thread, delivery));
  }
}

static void _job_destroy(gpointer data)
{
  dt_agent_client_job_t *job_data = data;

  if(!job_data)
    return;

  dt_agent_chat_request_clear(&job_data->request);
  dt_agent_client_request_unref(job_data->handle);
  g_free(job_data);
}

static void _delivery_clear(dt_agent_client_delivery_t *delivery)
{
  if(!delivery)
    return;

  dt_agent_client_result_clear(&delivery->result);
  if(delivery->destroy)
    delivery->destroy(delivery->user_data);
  g_free(delivery);
}

static gboolean _deliver_result(gpointer user_data)
{
  dt_agent_client_delivery_t *delivery = user_data;

  if(delivery->callback)
    delivery->callback(&delivery->result, delivery->user_data);

  _delivery_clear(delivery);
  return G_SOURCE_REMOVE;
}

void dt_agent_client_result_clear(dt_agent_client_result_t *result)
{
  if(!result)
    return;

  g_free(result->endpoint);
  g_free(result->transport_error);
  if(result->has_response)
    dt_agent_chat_response_clear(&result->response);
  memset(result, 0, sizeof(*result));
}

char *dt_agent_client_dup_endpoint(void)
{
  const char *env_endpoint = g_getenv("DARKTABLE_AGENT_SERVER_URL");
  if(env_endpoint && *env_endpoint)
    return g_strdup(env_endpoint);

  const char *configured = dt_conf_get_string_const(DT_AGENT_CHAT_SERVER_URL_CONF);
  if(configured && *configured)
    return g_strdup(configured);

  return g_strdup(DT_AGENT_CHAT_DEFAULT_ENDPOINT);
}

static int32_t _chat_job_run(dt_job_t *job)
{
  dt_agent_client_job_t *job_data = dt_control_job_get_params(job);
  dt_agent_client_delivery_t *delivery = g_new0(dt_agent_client_delivery_t, 1);
  delivery->callback = job_data->callback;
  delivery->user_data = job_data->user_data;
  delivery->destroy = job_data->destroy;
  delivery->result.endpoint = g_strdup(job_data->handle ? job_data->handle->endpoint : NULL);

  if(_request_cancelled(job_data->handle))
  {
    delivery->result.cancelled = TRUE;
    delivery->result.transport_error = g_strdup(_("chat request canceled"));
    g_main_context_invoke(NULL, _deliver_result, delivery);
    return 0;
  }

  GError *error = NULL;
  gchar *payload = dt_agent_chat_request_serialize(&job_data->request, &error);
  if(!payload)
  {
    delivery->result.transport_error
      = g_strdup(error && error->message ? error->message
                                         : _("failed to serialize chat request"));
    g_clear_error(&error);
    g_main_context_invoke(NULL, _deliver_result, delivery);
    return 0;
  }

  CURL *curl = curl_easy_init();
  if(!curl)
  {
    delivery->result.transport_error = g_strdup(_("failed to initialize network client"));
    g_free(payload);
    g_main_context_invoke(NULL, _deliver_result, delivery);
    return 0;
  }

  const char *env_timeout = g_getenv("DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS");
  const long configured_timeout = env_timeout && *env_timeout ? g_ascii_strtoll(env_timeout, NULL, 10)
                                                              : dt_conf_get_int(DT_AGENT_CHAT_TIMEOUT_SECONDS_CONF);
  const long timeout_seconds = configured_timeout > 0
                                 ? configured_timeout
                                 : DT_AGENT_CLIENT_DEFAULT_TIMEOUT_SECONDS;

  GString *response = g_string_new(NULL);
  struct curl_slist *headers = NULL;
  headers = curl_slist_append(headers, "Accept: application/json");
  headers = curl_slist_append(headers, "Content-Type: application/json");

  dt_curl_init(curl, FALSE);
  curl_easy_setopt(curl, CURLOPT_URL, delivery->result.endpoint);
  curl_easy_setopt(curl, CURLOPT_POST, 1L);
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload);
  curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(payload));
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, timeout_seconds);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout_seconds);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _write_response);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, response);
  curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
  curl_easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, _progress_callback);
  curl_easy_setopt(curl, CURLOPT_XFERINFODATA, job_data->handle);

  const CURLcode curl_result = curl_easy_perform(curl);
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &delivery->result.http_status);

  if(curl_result != CURLE_OK)
  {
    if(curl_result == CURLE_ABORTED_BY_CALLBACK && _request_cancelled(job_data->handle))
    {
      delivery->result.cancelled = TRUE;
      delivery->result.transport_error = g_strdup(_("chat request canceled"));
      dt_print(DT_DEBUG_CONTROL, "[agent_client] request canceled endpoint=%s",
               delivery->result.endpoint ? delivery->result.endpoint : "");
    }
    else
    {
      delivery->result.transport_error = g_strdup_printf(_("chat request failed: %s"),
                                                         curl_easy_strerror(curl_result));
      dt_print(DT_DEBUG_CONTROL, "[agent_client] request failed: curl=%d endpoint=%s",
               curl_result,
               delivery->result.endpoint ? delivery->result.endpoint : "");
    }
  }
  else
  {
    delivery->result.has_response
      = dt_agent_chat_response_parse_data(response->str, response->len,
                                          &delivery->result.response, &error);
    if(!delivery->result.has_response)
    {
      delivery->result.transport_error
        = g_strdup(error && error->message ? error->message
                                           : _("failed to parse chat response"));
      g_clear_error(&error);
    }

    dt_print(DT_DEBUG_CONTROL,
             "[agent_client] request complete: http=%d endpoint=%s parsed=%s",
             delivery->result.http_status,
             delivery->result.endpoint ? delivery->result.endpoint : "",
             delivery->result.has_response ? "yes" : "no");
  }

  curl_slist_free_all(headers);
  g_string_free(response, TRUE);
  curl_easy_cleanup(curl);
  g_free(payload);

  g_main_context_invoke(NULL, _deliver_result, delivery);
  return 0;
}

dt_agent_client_request_t *dt_agent_client_chat_async(const dt_agent_chat_request_t *request,
                                                      dt_agent_client_callback_t callback,
                                                      gpointer user_data,
                                                      GDestroyNotify destroy,
                                                      GError **error)
{
  if(!request)
  {
    g_set_error(error, _agent_client_error_quark(), DT_AGENT_CLIENT_ERROR_INVALID,
                "%s", _("missing agent chat request"));
    if(destroy)
      destroy(user_data);
    return NULL;
  }

  dt_agent_client_request_t *handle = g_new0(dt_agent_client_request_t, 1);
  handle->refcount = 1;
  handle->request_id = g_strdup(request->request_id);
  handle->app_session_id = g_strdup(request->app_session_id);
  handle->image_session_id = g_strdup(request->image_session_id);
  handle->conversation_id = g_strdup(request->conversation_id);
  handle->turn_id = g_strdup(request->turn_id);
  handle->endpoint = dt_agent_client_dup_endpoint();

  dt_agent_client_job_t *job_data = g_new0(dt_agent_client_job_t, 1);
  dt_agent_chat_request_copy(&job_data->request, request);
  job_data->handle = _request_ref(handle);
  job_data->callback = callback;
  job_data->user_data = user_data;
  job_data->destroy = destroy;

  dt_job_t *job = dt_control_job_create(_chat_job_run, "%s", N_("agent chat request"));
  if(!job)
  {
    g_set_error(error, _agent_client_error_quark(), DT_AGENT_CLIENT_ERROR_QUEUE_UNAVAILABLE,
                "%s", _("darktable background jobs are not ready yet"));
    _job_destroy(job_data);
    dt_agent_client_request_unref(handle);
    dt_print(DT_DEBUG_CONTROL,
             "[agent_client] failed to create request job: control_running=%s",
             dt_control_running() ? "yes" : "no");
    return NULL;
  }

  dt_control_job_set_params(job, job_data, _job_destroy);
  dt_control_add_job(DT_JOB_QUEUE_USER_BG, job);
  dt_print(DT_DEBUG_CONTROL, "[agent_client] queued request job");

  return handle;
}
