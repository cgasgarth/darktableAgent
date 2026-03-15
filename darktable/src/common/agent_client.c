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
  dt_agent_client_progress_callback_t progress_callback;
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

typedef struct dt_agent_client_stream_progress_delivery_t
{
  dt_agent_client_progress_callback_t callback;
  gpointer user_data;
  dt_agent_client_progress_t progress;
} dt_agent_client_stream_progress_delivery_t;

typedef struct dt_agent_client_sse_parser_t
{
  dt_agent_client_job_t *job_data;
  dt_agent_client_delivery_t *final_delivery;
  GString *line_buffer;
  GString *data_buffer;
  gchar *event_name;
} dt_agent_client_sse_parser_t;

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

static gboolean _parse_progress_payload(const dt_agent_client_request_t *request,
                                        const gchar *data,
                                        gssize length,
                                        dt_agent_client_progress_t *progress,
                                        GError **error);

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

static gchar *_stream_endpoint_from_chat_endpoint(const gchar *endpoint)
{
  if(!endpoint || !endpoint[0])
    return g_strdup("http://127.0.0.1:8001/v1/chat/stream");

  return g_str_has_suffix(endpoint, "/")
           ? g_strconcat(endpoint, "stream", NULL)
           : g_strconcat(endpoint, "/stream", NULL);
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

static void _stream_progress_delivery_clear(dt_agent_client_stream_progress_delivery_t *delivery)
{
  if(!delivery)
    return;

  dt_agent_client_progress_clear(&delivery->progress);
  g_free(delivery);
}

static gboolean _deliver_stream_progress(gpointer user_data)
{
  dt_agent_client_stream_progress_delivery_t *delivery = user_data;
  if(delivery->callback)
    delivery->callback(&delivery->progress, delivery->user_data);
  _stream_progress_delivery_clear(delivery);
  return G_SOURCE_REMOVE;
}

static void _sse_parser_reset_event(dt_agent_client_sse_parser_t *parser)
{
  g_clear_pointer(&parser->event_name, g_free);
  g_string_set_size(parser->data_buffer, 0);
}

static void _sse_dispatch_current_event(dt_agent_client_sse_parser_t *parser)
{
  if(!parser || parser->data_buffer->len == 0)
    return;

  g_autofree gchar *event_name = g_strdup(parser->event_name ? parser->event_name : "message");
  g_autofree gchar *payload = g_strdup(parser->data_buffer->str);
  g_strchomp(payload);

  if(g_strcmp0(event_name, "progress") == 0)
  {
    if(!parser->job_data->progress_callback)
      return;

    dt_agent_client_stream_progress_delivery_t *delivery
      = g_new0(dt_agent_client_stream_progress_delivery_t, 1);
    delivery->callback = parser->job_data->progress_callback;
    delivery->user_data = parser->job_data->user_data;
    delivery->progress.endpoint
      = _stream_endpoint_from_chat_endpoint(parser->job_data->handle
                                              ? parser->job_data->handle->endpoint
                                              : NULL);
    g_autoptr(GError) parse_error = NULL;
    if(!_parse_progress_payload(parser->job_data->handle,
                                payload,
                                -1,
                                &delivery->progress,
                                &parse_error))
    {
      delivery->progress.transport_error
        = g_strdup(parse_error && parse_error->message ? parse_error->message
                                                       : _("failed to parse stream progress event"));
    }

    g_main_context_invoke(NULL, _deliver_stream_progress, delivery);
    return;
  }

  if(g_strcmp0(event_name, "final") == 0 || g_strcmp0(event_name, "error") == 0)
  {
    if(parser->final_delivery->result.has_response)
      return;

    g_autoptr(GError) parse_error = NULL;
    parser->final_delivery->result.has_response
      = dt_agent_chat_response_parse_data(payload, -1,
                                          &parser->final_delivery->result.response,
                                          &parse_error);
    if(!parser->final_delivery->result.has_response
       && !parser->final_delivery->result.transport_error)
    {
      parser->final_delivery->result.transport_error
        = g_strdup(parse_error && parse_error->message ? parse_error->message
                                                       : _("failed to parse streamed final response"));
    }
    return;
  }
}

static size_t _write_sse_response(void *ptr, size_t size, size_t nmemb, void *userdata)
{
  dt_agent_client_sse_parser_t *parser = userdata;
  const size_t bytes = size * nmemb;
  if(!parser || !ptr || bytes == 0)
    return bytes;

  g_string_append_len(parser->line_buffer, (const gchar *)ptr, bytes);

  while(TRUE)
  {
    gchar *newline = strchr(parser->line_buffer->str, '\n');
    if(!newline)
      break;

    const gsize line_len = (gsize)(newline - parser->line_buffer->str);
    g_autofree gchar *line = g_strndup(parser->line_buffer->str, line_len);
    g_string_erase(parser->line_buffer, 0, line_len + 1);

    g_strchomp(line);
    if(line[0] == '\0')
    {
      _sse_dispatch_current_event(parser);
      _sse_parser_reset_event(parser);
      continue;
    }

    if(g_str_has_prefix(line, ":"))
      continue;

    if(g_str_has_prefix(line, "event:"))
    {
      g_free(parser->event_name);
      parser->event_name = g_strstrip(g_strdup(line + 6));
      continue;
    }

    if(g_str_has_prefix(line, "data:"))
    {
      const gchar *content = g_strstrip(line + 5);
      if(parser->data_buffer->len > 0)
        g_string_append_c(parser->data_buffer, '\n');
      g_string_append(parser->data_buffer, content);
      continue;
    }
  }

  return bytes;
}

static void _sse_parser_clear(dt_agent_client_sse_parser_t *parser)
{
  if(!parser)
    return;
  if(parser->line_buffer)
    g_string_free(parser->line_buffer, TRUE);
  parser->line_buffer = NULL;
  if(parser->data_buffer)
    g_string_free(parser->data_buffer, TRUE);
  parser->data_buffer = NULL;
  g_clear_pointer(&parser->event_name, g_free);
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

void dt_agent_client_progress_clear(dt_agent_client_progress_t *progress)
{
  if(!progress)
    return;

  g_free(progress->endpoint);
  g_free(progress->transport_error);
  g_free(progress->status);
  g_free(progress->message);
  if(progress->has_response)
    dt_agent_chat_response_clear(&progress->response);
  memset(progress, 0, sizeof(*progress));
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

static gchar *_build_progress_response_json(const dt_agent_client_request_t *request,
                                            JsonNode *operations_node,
                                            GError **error)
{
  JsonBuilder *builder = json_builder_new();
  json_builder_begin_object(builder);

  json_builder_set_member_name(builder, "schemaVersion");
  json_builder_add_string_value(builder, DT_AGENT_CHAT_SCHEMA_VERSION);
  json_builder_set_member_name(builder, "requestId");
  json_builder_add_string_value(builder, request->request_id ? request->request_id : "progress");

  json_builder_set_member_name(builder, "session");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "appSessionId");
  json_builder_add_string_value(builder, request->app_session_id ? request->app_session_id : "app");
  json_builder_set_member_name(builder, "imageSessionId");
  json_builder_add_string_value(builder, request->image_session_id ? request->image_session_id : "image");
  json_builder_set_member_name(builder, "conversationId");
  json_builder_add_string_value(builder, request->conversation_id ? request->conversation_id : "conversation");
  json_builder_set_member_name(builder, "turnId");
  json_builder_add_string_value(builder, request->turn_id ? request->turn_id : "turn");
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "status");
  json_builder_add_string_value(builder, "ok");
  json_builder_set_member_name(builder, "assistantMessage");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "role");
  json_builder_add_string_value(builder, "assistant");
  json_builder_set_member_name(builder, "text");
  json_builder_add_string_value(builder, "");
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "refinement");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "mode");
  json_builder_add_string_value(builder, "multi-turn");
  json_builder_set_member_name(builder, "enabled");
  json_builder_add_boolean_value(builder, TRUE);
  json_builder_set_member_name(builder, "passIndex");
  json_builder_add_int_value(builder, 1);
  json_builder_set_member_name(builder, "maxPasses");
  json_builder_add_int_value(builder, 1);
  json_builder_set_member_name(builder, "continueRefining");
  json_builder_add_boolean_value(builder, FALSE);
  json_builder_set_member_name(builder, "stopReason");
  json_builder_add_string_value(builder, "continue");
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "plan");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "planId");
  json_builder_add_string_value(builder, "live-progress");
  json_builder_set_member_name(builder, "baseImageRevisionId");
  json_builder_add_string_value(builder, "live-progress");
  json_builder_set_member_name(builder, "operations");
  if(operations_node && JSON_NODE_HOLDS_ARRAY(operations_node))
    json_builder_add_value(builder, json_node_copy(operations_node));
  else
  {
    json_builder_begin_array(builder);
    json_builder_end_array(builder);
  }
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "operationResults");
  json_builder_begin_array(builder);
  json_builder_end_array(builder);

  json_builder_set_member_name(builder, "error");
  json_builder_add_null_value(builder);

  json_builder_end_object(builder);

  JsonGenerator *generator = json_generator_new();
  JsonNode *root = json_builder_get_root(builder);
  json_generator_set_root(generator, root);
  gchar *data = json_generator_to_data(generator, NULL);
  if(!data)
    g_set_error(error, _agent_client_error_quark(), DT_AGENT_CLIENT_ERROR_INVALID,
                "%s", _("failed to build progress response payload"));
  json_node_free(root);
  g_object_unref(generator);
  g_object_unref(builder);
  return data;
}

static gboolean _parse_progress_payload(const dt_agent_client_request_t *request,
                                        const gchar *data,
                                        gssize length,
                                        dt_agent_client_progress_t *progress,
                                        GError **error)
{
  JsonParser *parser = json_parser_new();
  if(!json_parser_load_from_data(parser, data, length, error))
  {
    g_object_unref(parser);
    return FALSE;
  }

  JsonNode *root = json_parser_get_root(parser);
  if(!root || !JSON_NODE_HOLDS_OBJECT(root))
  {
    g_set_error(error, _agent_client_error_quark(), DT_AGENT_CLIENT_ERROR_INVALID,
                "%s", _("progress response root must be an object"));
    g_object_unref(parser);
    return FALSE;
  }

  JsonObject *object = json_node_get_object(root);
  JsonNode *found_node = json_object_get_member(object, "found");
  if(found_node && JSON_NODE_HOLDS_VALUE(found_node)
     && g_type_is_a(json_node_get_value_type(found_node), G_TYPE_BOOLEAN))
    progress->found = json_node_get_boolean(found_node);

  JsonNode *status_node = json_object_get_member(object, "status");
  if(status_node && JSON_NODE_HOLDS_VALUE(status_node)
     && g_type_is_a(json_node_get_value_type(status_node), G_TYPE_STRING))
    progress->status = g_strdup(json_node_get_string(status_node));

  JsonNode *message_node = json_object_get_member(object, "message");
  if(message_node && JSON_NODE_HOLDS_VALUE(message_node)
     && g_type_is_a(json_node_get_value_type(message_node), G_TYPE_STRING))
    progress->message = g_strdup(json_node_get_string(message_node));

  JsonNode *tool_used_node = json_object_get_member(object, "toolCallsUsed");
  if(tool_used_node && JSON_NODE_HOLDS_VALUE(tool_used_node)
     && g_type_is_a(json_node_get_value_type(tool_used_node), G_TYPE_INT64))
    progress->tool_calls_used = (guint)MAX(0, json_node_get_int(tool_used_node));

  JsonNode *tool_max_node = json_object_get_member(object, "maxToolCalls");
  if(tool_max_node && JSON_NODE_HOLDS_VALUE(tool_max_node)
     && g_type_is_a(json_node_get_value_type(tool_max_node), G_TYPE_INT64))
    progress->tool_calls_max = (guint)MAX(0, json_node_get_int(tool_max_node));

  JsonNode *applied_count_node = json_object_get_member(object, "appliedOperationCount");
  if(applied_count_node && JSON_NODE_HOLDS_VALUE(applied_count_node)
     && g_type_is_a(json_node_get_value_type(applied_count_node), G_TYPE_INT64))
    progress->applied_operation_count = (guint)MAX(0, json_node_get_int(applied_count_node));

  JsonNode *operations_node = json_object_get_member(object, "operations");
  if(operations_node && !JSON_NODE_HOLDS_ARRAY(operations_node))
  {
    g_set_error(error, _agent_client_error_quark(), DT_AGENT_CLIENT_ERROR_INVALID,
                "%s", _("progress response operations must be an array"));
    g_object_unref(parser);
    return FALSE;
  }

  if(progress->found)
  {
    g_autofree gchar *response_json = _build_progress_response_json(request,
                                                                    operations_node,
                                                                    error);
    if(!response_json)
    {
      g_object_unref(parser);
      return FALSE;
    }
    progress->has_response = dt_agent_chat_response_parse_data(response_json, -1,
                                                               &progress->response, error);
    if(!progress->has_response)
    {
      g_object_unref(parser);
      return FALSE;
    }
    if(progress->applied_operation_count == 0 && progress->response.operations)
      progress->applied_operation_count = progress->response.operations->len;
  }

  if(g_strcmp0(progress->status, "cancelled") == 0)
    progress->cancelled = TRUE;

  g_object_unref(parser);
  return TRUE;
}

static int32_t _chat_job_run(dt_job_t *job)
{
  dt_agent_client_job_t *job_data = dt_control_job_get_params(job);
  dt_agent_client_delivery_t *delivery = g_new0(dt_agent_client_delivery_t, 1);
  delivery->callback = job_data->callback;
  delivery->user_data = job_data->user_data;
  delivery->destroy = job_data->destroy;
  delivery->result.endpoint = _stream_endpoint_from_chat_endpoint(
    job_data->handle ? job_data->handle->endpoint : NULL);

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

  dt_agent_client_sse_parser_t parser = {
    .job_data = job_data,
    .final_delivery = delivery,
    .line_buffer = g_string_new(NULL),
    .data_buffer = g_string_new(NULL),
    .event_name = NULL,
  };
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
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _write_sse_response);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &parser);
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
    if(parser.data_buffer->len > 0)
      _sse_dispatch_current_event(&parser);

    if(!delivery->result.has_response && !delivery->result.transport_error)
    {
      delivery->result.transport_error
        = g_strdup(_("chat stream ended without a final response"));
    }

    dt_print(DT_DEBUG_CONTROL,
             "[agent_client] request complete: http=%d endpoint=%s parsed=%s",
             delivery->result.http_status,
             delivery->result.endpoint ? delivery->result.endpoint : "",
             delivery->result.has_response ? "yes" : "no");
  }

  _sse_parser_clear(&parser);
  curl_slist_free_all(headers);
  curl_easy_cleanup(curl);
  g_free(payload);

  g_main_context_invoke(NULL, _deliver_result, delivery);
  return 0;
}

dt_agent_client_request_t *dt_agent_client_chat_async(const dt_agent_chat_request_t *request,
                                                      dt_agent_client_callback_t callback,
                                                      dt_agent_client_progress_callback_t progress_callback,
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
  job_data->progress_callback = progress_callback;
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
