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

#include "common/agent_protocol.h"

#include <json-glib/json-glib.h>
#include <string.h>

typedef enum dt_agent_protocol_error_t
{
  DT_AGENT_PROTOCOL_ERROR_INVALID = 1,
} dt_agent_protocol_error_t;

static GQuark _agent_protocol_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-protocol-error");
}

static gboolean _string_in_list(const char *value, const char *const *choices)
{
  if(!value)
    return FALSE;

  for(const char *const *choice = choices; *choice; choice++)
    if(g_strcmp0(value, *choice) == 0)
      return TRUE;

  return FALSE;
}

static gboolean _require_string_member(JsonObject *object,
                                       const char *member,
                                       char **out,
                                       GError **error)
{
  if(!json_object_has_member(object, member))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "missing required member '%s'", member);
    return FALSE;
  }

  JsonNode *node = json_object_get_member(object, member);
  if(!JSON_NODE_HOLDS_VALUE(node)
     || !g_type_is_a(json_node_get_value_type(node), G_TYPE_STRING))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be a string", member);
    return FALSE;
  }

  const char *value = json_node_get_string(node);
  if(!value || !value[0])
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must not be empty", member);
    return FALSE;
  }

  *out = g_strdup(value);
  return TRUE;
}

static gboolean _require_number_member(JsonObject *object,
                                       const char *member,
                                       double *out,
                                       GError **error)
{
  if(!json_object_has_member(object, member))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "missing required member '%s'", member);
    return FALSE;
  }

  JsonNode *node = json_object_get_member(object, member);
  if(!JSON_NODE_HOLDS_VALUE(node)
     || !g_type_is_a(json_node_get_value_type(node), G_TYPE_DOUBLE))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be numeric", member);
    return FALSE;
  }

  *out = json_node_get_double(node);
  return TRUE;
}

static gboolean _parse_message(JsonObject *object,
                               const char *member,
                               char **role,
                               char **text,
                               GError **error)
{
  if(!json_object_has_member(object, member))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "missing required member '%s'", member);
    return FALSE;
  }

  JsonNode *node = json_object_get_member(object, member);
  if(!JSON_NODE_HOLDS_OBJECT(node))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be an object", member);
    return FALSE;
  }

  JsonObject *message = json_node_get_object(node);
  return _require_string_member(message, "role", role, error)
      && _require_string_member(message, "text", text, error);
}

static gboolean _parse_error(JsonObject *object,
                             char **error_code,
                             char **error_message,
                             GError **error)
{
  if(!json_object_has_member(object, "error"))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "missing required member 'error'");
    return FALSE;
  }

  JsonNode *node = json_object_get_member(object, "error");
  if(JSON_NODE_HOLDS_NULL(node))
    return TRUE;

  if(!JSON_NODE_HOLDS_OBJECT(node))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member 'error' must be an object or null");
    return FALSE;
  }

  JsonObject *error_object = json_node_get_object(node);
  return _require_string_member(error_object, "code", error_code, error)
      && _require_string_member(error_object, "message", error_message, error);
}

static gboolean _parse_operation(JsonObject *object,
                                 dt_agent_chat_operation_t **out,
                                 GError **error)
{
  static const char *const valid_statuses[] = {
    "planned",
    "applied",
    "blocked",
    "failed",
    NULL,
  };

  dt_agent_chat_operation_t *operation = g_new0(dt_agent_chat_operation_t, 1);

  if(!_require_string_member(object, "operationId", &operation->operation_id, error)
     || !_require_string_member(object, "kind", &operation->kind_name, error)
     || !_require_string_member(object, "status", &operation->status, error))
  {
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  operation->kind = dt_agent_operation_kind_from_string(operation->kind_name);
  if(operation->kind == DT_AGENT_OPERATION_UNKNOWN)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported operation kind '%s'",
                operation->kind_name ? operation->kind_name : "");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  if(!_string_in_list(operation->status, valid_statuses))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported operation status '%s'",
                operation->status ? operation->status : "");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  if(!json_object_has_member(object, "target")
     || !json_object_has_member(object, "value"))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "operation must include target and value objects");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  JsonNode *target_node = json_object_get_member(object, "target");
  JsonNode *value_node = json_object_get_member(object, "value");
  if(!JSON_NODE_HOLDS_OBJECT(target_node) || !JSON_NODE_HOLDS_OBJECT(value_node))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "operation target and value must be objects");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  JsonObject *target = json_node_get_object(target_node);
  JsonObject *value = json_node_get_object(value_node);

  if(!_require_string_member(target, "type", &operation->target_type, error)
     || !_require_string_member(target, "actionPath", &operation->action_path, error))
  {
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  if(g_strcmp0(operation->target_type, "darktable-action") != 0)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported target type '%s'",
                operation->target_type ? operation->target_type : "");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  char *value_mode_name = NULL;
  if(!_require_string_member(value, "mode", &value_mode_name, error)
     || !_require_number_member(value, "number", &operation->number, error))
  {
    g_free(value_mode_name);
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  operation->value_mode = dt_agent_value_mode_from_string(value_mode_name);
  g_free(value_mode_name);

  if(operation->value_mode == DT_AGENT_VALUE_MODE_UNKNOWN)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported value mode");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  *out = operation;
  return TRUE;
}

void dt_agent_ui_context_clear(dt_agent_ui_context_t *ui_context)
{
  if(!ui_context)
    return;

  g_free(ui_context->view);
  g_free(ui_context->image_name);
  *ui_context = (dt_agent_ui_context_t){ 0 };
}

void dt_agent_chat_request_init(dt_agent_chat_request_t *request)
{
  if(!request)
    return;

  memset(request, 0, sizeof(*request));
  request->schema_version = g_strdup(DT_AGENT_CHAT_SCHEMA_VERSION);
}

void dt_agent_chat_request_clear(dt_agent_chat_request_t *request)
{
  if(!request)
    return;

  g_free(request->schema_version);
  g_free(request->request_id);
  g_free(request->conversation_id);
  g_free(request->message_text);
  dt_agent_ui_context_clear(&request->ui_context);
  g_free(request->mock_response_id);
  memset(request, 0, sizeof(*request));
}

void dt_agent_chat_request_copy(dt_agent_chat_request_t *dest,
                                const dt_agent_chat_request_t *src)
{
  dt_agent_chat_request_init(dest);
  g_free(dest->schema_version);
  dest->schema_version = g_strdup(src->schema_version);
  dest->request_id = g_strdup(src->request_id);
  dest->conversation_id = g_strdup(src->conversation_id);
  dest->message_text = g_strdup(src->message_text);
  dest->ui_context.view = g_strdup(src->ui_context.view);
  dest->ui_context.has_image_id = src->ui_context.has_image_id;
  dest->ui_context.image_id = src->ui_context.image_id;
  dest->ui_context.image_name = g_strdup(src->ui_context.image_name);
  dest->mock_response_id = g_strdup(src->mock_response_id);
}

void dt_agent_chat_operation_free(gpointer data)
{
  dt_agent_chat_operation_t *operation = data;

  if(!operation)
    return;

  g_free(operation->operation_id);
  g_free(operation->kind_name);
  g_free(operation->status);
  g_free(operation->target_type);
  g_free(operation->action_path);
  g_free(operation);
}

void dt_agent_chat_response_init(dt_agent_chat_response_t *response)
{
  if(!response)
    return;

  memset(response, 0, sizeof(*response));
  response->operations = g_ptr_array_new_with_free_func(dt_agent_chat_operation_free);
}

void dt_agent_chat_response_clear(dt_agent_chat_response_t *response)
{
  if(!response)
    return;

  g_free(response->schema_version);
  g_free(response->request_id);
  g_free(response->conversation_id);
  g_free(response->status);
  g_free(response->message_role);
  g_free(response->message_text);
  if(response->operations)
    g_ptr_array_unref(response->operations);
  g_free(response->error_code);
  g_free(response->error_message);
  memset(response, 0, sizeof(*response));
}

const char *dt_agent_operation_kind_to_string(dt_agent_operation_kind_t kind)
{
  switch(kind)
  {
    case DT_AGENT_OPERATION_SET_FLOAT:
      return "set-float";
    case DT_AGENT_OPERATION_UNKNOWN:
    default:
      return "unknown";
  }
}

dt_agent_operation_kind_t dt_agent_operation_kind_from_string(const char *kind_name)
{
  if(g_strcmp0(kind_name, "set-float") == 0)
    return DT_AGENT_OPERATION_SET_FLOAT;

  return DT_AGENT_OPERATION_UNKNOWN;
}

const char *dt_agent_value_mode_to_string(dt_agent_value_mode_t mode)
{
  switch(mode)
  {
    case DT_AGENT_VALUE_MODE_SET:
      return "set";
    case DT_AGENT_VALUE_MODE_DELTA:
      return "delta";
    case DT_AGENT_VALUE_MODE_UNKNOWN:
    default:
      return "unknown";
  }
}

dt_agent_value_mode_t dt_agent_value_mode_from_string(const char *mode_name)
{
  if(g_strcmp0(mode_name, "set") == 0)
    return DT_AGENT_VALUE_MODE_SET;
  if(g_strcmp0(mode_name, "delta") == 0)
    return DT_AGENT_VALUE_MODE_DELTA;

  return DT_AGENT_VALUE_MODE_UNKNOWN;
}

gchar *dt_agent_chat_request_serialize(const dt_agent_chat_request_t *request,
                                       GError **error)
{
  if(!request || !request->request_id || !request->conversation_id
     || !request->message_text || !request->ui_context.view)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "request is incomplete");
    return NULL;
  }

  JsonBuilder *builder = json_builder_new();
  json_builder_begin_object(builder);

  json_builder_set_member_name(builder, "schemaVersion");
  json_builder_add_string_value(builder,
                                request->schema_version ? request->schema_version
                                                        : DT_AGENT_CHAT_SCHEMA_VERSION);

  json_builder_set_member_name(builder, "requestId");
  json_builder_add_string_value(builder, request->request_id);

  json_builder_set_member_name(builder, "conversationId");
  json_builder_add_string_value(builder, request->conversation_id);

  json_builder_set_member_name(builder, "message");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "role");
  json_builder_add_string_value(builder, "user");
  json_builder_set_member_name(builder, "text");
  json_builder_add_string_value(builder, request->message_text);
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "uiContext");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "view");
  json_builder_add_string_value(builder, request->ui_context.view);
  json_builder_set_member_name(builder, "imageId");
  if(request->ui_context.has_image_id)
    json_builder_add_int_value(builder, request->ui_context.image_id);
  else
    json_builder_add_null_value(builder);
  json_builder_set_member_name(builder, "imageName");
  if(request->ui_context.image_name)
    json_builder_add_string_value(builder, request->ui_context.image_name);
  else
    json_builder_add_null_value(builder);
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "mockResponseId");
  if(request->mock_response_id)
    json_builder_add_string_value(builder, request->mock_response_id);
  else
    json_builder_add_null_value(builder);

  json_builder_end_object(builder);

  JsonGenerator *generator = json_generator_new();
  JsonNode *root = json_builder_get_root(builder);
  json_generator_set_root(generator, root);
  gchar *serialized = json_generator_to_data(generator, NULL);

  json_node_free(root);
  g_object_unref(generator);
  g_object_unref(builder);
  return serialized;
}

gboolean dt_agent_chat_response_parse_data(const gchar *data,
                                           gssize length,
                                           dt_agent_chat_response_t *response,
                                           GError **error)
{
  static const char *const valid_response_statuses[] = { "ok", "error", NULL };

  if(!data || !response)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "response buffer is invalid");
    return FALSE;
  }

  JsonParser *parser = json_parser_new();
  if(!json_parser_load_from_data(parser, data, length, error))
  {
    g_object_unref(parser);
    return FALSE;
  }

  JsonNode *root = json_parser_get_root(parser);
  if(!root || !JSON_NODE_HOLDS_OBJECT(root))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "response root must be an object");
    g_object_unref(parser);
    return FALSE;
  }

  dt_agent_chat_response_init(response);
  JsonObject *object = json_node_get_object(root);

  gboolean ok = _require_string_member(object, "schemaVersion", &response->schema_version, error)
             && _require_string_member(object, "requestId", &response->request_id, error)
             && _require_string_member(object, "conversationId", &response->conversation_id, error)
             && _require_string_member(object, "status", &response->status, error)
             && _parse_message(object, "message", &response->message_role, &response->message_text, error)
             && _parse_error(object, &response->error_code, &response->error_message, error);

  if(ok)
  {
    if(g_strcmp0(response->schema_version, DT_AGENT_CHAT_SCHEMA_VERSION) != 0)
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "unsupported schemaVersion '%s'",
                  response->schema_version ? response->schema_version : "");
      ok = FALSE;
    }
    else if(!_string_in_list(response->status, valid_response_statuses))
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "unsupported response status '%s'",
                  response->status ? response->status : "");
      ok = FALSE;
    }
    else if(g_strcmp0(response->message_role, "assistant") != 0)
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "response message role must be 'assistant'");
      ok = FALSE;
    }
    else if(g_strcmp0(response->status, "error") == 0
            && (!response->error_code || !response->error_message))
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "error responses require error details");
      ok = FALSE;
    }
    else if(g_strcmp0(response->status, "ok") == 0
            && (response->error_code || response->error_message))
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "ok responses must not include error details");
      ok = FALSE;
    }

    if(!ok)
      goto cleanup;

    if(!json_object_has_member(object, "operations"))
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "missing required member 'operations'");
      ok = FALSE;
    }
    else
    {
      JsonNode *operations_node = json_object_get_member(object, "operations");
      if(!JSON_NODE_HOLDS_ARRAY(operations_node))
      {
        g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                    "member 'operations' must be an array");
        ok = FALSE;
      }
      else
      {
        JsonArray *operations = json_node_get_array(operations_node);
        const guint count = json_array_get_length(operations);
        for(guint i = 0; ok && i < count; i++)
        {
          JsonNode *operation_node = json_array_get_element(operations, i);
          if(!JSON_NODE_HOLDS_OBJECT(operation_node))
          {
            g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                        "operation %u must be an object", i);
            ok = FALSE;
            break;
          }

          dt_agent_chat_operation_t *operation = NULL;
          ok = _parse_operation(json_node_get_object(operation_node), &operation, error);
          if(ok)
            g_ptr_array_add(response->operations, operation);
        }
      }
    }
  }

cleanup:

  g_object_unref(parser);

  if(!ok)
  {
    dt_agent_chat_response_clear(response);
    return FALSE;
  }

  return TRUE;
}
