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
#include "common/darktable.h"
#include "control/conf.h"
#include "control/jobs.h"

#include <curl/curl.h>
#include <glib/gi18n.h>
#include <string.h>

typedef struct dt_agent_client_job_t
{
  dt_agent_chat_request_t request;
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

static size_t _write_response(void *ptr, size_t size, size_t nmemb, void *userdata)
{
  GString *buffer = userdata;
  const size_t bytes = size * nmemb;

  if(buffer->len + bytes > 1024 * 1024)
    return 0;

  g_string_append_len(buffer, ptr, bytes);
  return bytes;
}

static void _job_destroy(gpointer data)
{
  dt_agent_client_job_t *job_data = data;

  if(!job_data)
    return;

  dt_agent_chat_request_clear(&job_data->request);
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

  delivery->result.endpoint = dt_agent_client_dup_endpoint();

  GError *error = NULL;
  gchar *payload = dt_agent_chat_request_serialize(&job_data->request, &error);
  if(!payload)
  {
    delivery->result.transport_error
      = g_strdup(error && error->message ? error->message : _("failed to serialize chat request"));
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

  const long timeout_seconds = MAX(1, dt_conf_get_int(DT_AGENT_CHAT_TIMEOUT_SECONDS_CONF));

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

  const CURLcode curl_result = curl_easy_perform(curl);
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &delivery->result.http_status);

  if(curl_result != CURLE_OK)
  {
    delivery->result.transport_error = g_strdup_printf(_("chat request failed: %s"),
                                                       curl_easy_strerror(curl_result));
    dt_print(DT_DEBUG_AI, "[agent_client] request failed: curl=%d endpoint=%s",
             curl_result, delivery->result.endpoint);
  }
  else
  {
    delivery->result.has_response
      = dt_agent_chat_response_parse_data(response->str, response->len,
                                          &delivery->result.response, &error);
    if(!delivery->result.has_response)
    {
      delivery->result.transport_error
        = g_strdup(error && error->message ? error->message : _("failed to parse chat response"));
      g_clear_error(&error);
    }

    dt_print(DT_DEBUG_AI,
             "[agent_client] request complete: http=%d endpoint=%s parsed=%s",
             delivery->result.http_status,
             delivery->result.endpoint,
             delivery->result.has_response ? "yes" : "no");
  }

  curl_slist_free_all(headers);
  g_string_free(response, TRUE);
  curl_easy_cleanup(curl);
  g_free(payload);

  g_main_context_invoke(NULL, _deliver_result, delivery);
  return 0;
}

dt_job_t *dt_agent_client_chat_async(const dt_agent_chat_request_t *request,
                                     dt_agent_client_callback_t callback,
                                     gpointer user_data,
                                     GDestroyNotify destroy)
{
  if(!request)
  {
    if(destroy)
      destroy(user_data);
    return NULL;
  }

  dt_agent_client_job_t *job_data = g_new0(dt_agent_client_job_t, 1);
  dt_agent_chat_request_copy(&job_data->request, request);
  job_data->callback = callback;
  job_data->user_data = user_data;
  job_data->destroy = destroy;

  dt_job_t *job = dt_control_job_create(_chat_job_run, "%s", N_("AI chat request"));
  dt_control_job_set_params(job, job_data, _job_destroy);

  if(!dt_control_add_job(DT_JOB_QUEUE_USER_BG, job))
  {
    dt_control_job_dispose(job);
    return NULL;
  }

  return job;
}
