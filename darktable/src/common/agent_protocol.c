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

#include "common/agent_catalog.h"

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

static gboolean _require_uint_member(JsonObject *object,
                                     const char *member,
                                     guint *out,
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
     || !g_type_is_a(json_node_get_value_type(node), G_TYPE_INT64))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be an integer", member);
    return FALSE;
  }

  const gint64 value = json_node_get_int(node);
  if(value < 0)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be >= 0", member);
    return FALSE;
  }

  *out = (guint)value;
  return TRUE;
}

static gboolean _require_boolean_member(JsonObject *object,
                                        const char *member,
                                        gboolean *out,
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
     || !g_type_is_a(json_node_get_value_type(node), G_TYPE_BOOLEAN))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be a boolean", member);
    return FALSE;
  }

  *out = json_node_get_boolean(node);
  return TRUE;
}

static gboolean _parse_optional_string_member(JsonObject *object,
                                              const char *member,
                                              char **out,
                                              GError **error)
{
  if(!json_object_has_member(object, member))
  {
    *out = NULL;
    return TRUE;
  }

  JsonNode *node = json_object_get_member(object, member);
  if(JSON_NODE_HOLDS_NULL(node))
  {
    *out = NULL;
    return TRUE;
  }

  if(!JSON_NODE_HOLDS_VALUE(node)
     || !g_type_is_a(json_node_get_value_type(node), G_TYPE_STRING))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member '%s' must be a string or null", member);
    return FALSE;
  }

  const char *value = json_node_get_string(node);
  *out = value ? g_strdup(value) : NULL;
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

static gboolean _parse_refinement(JsonObject *object,
                                  const char *member,
                                  dt_agent_refinement_mode_t *mode,
                                  gboolean *enabled,
                                  guint *pass_index,
                                  guint *max_passes,
                                  gboolean *continue_refining,
                                  gchar **stop_reason,
                                  const gboolean require_continue_member,
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

  JsonObject *refinement = json_node_get_object(node);
  gchar *mode_name = NULL;
  gboolean parsed_enabled = FALSE;
  gboolean parsed_continue = FALSE;
  gboolean ok = _require_string_member(refinement, "mode", &mode_name, error)
             && _require_boolean_member(refinement, "enabled", &parsed_enabled, error)
             && _require_uint_member(refinement, "passIndex", pass_index, error)
             && _require_uint_member(refinement, "maxPasses", max_passes, error);

  if(ok && require_continue_member)
    ok = _require_boolean_member(refinement, "continueRefining", &parsed_continue, error);

  if(ok)
    ok = _parse_optional_string_member(refinement, "stopReason", stop_reason, error);

  if(ok)
  {
    *mode = dt_agent_refinement_mode_from_string(mode_name);
    if(*mode == DT_AGENT_REFINEMENT_MODE_UNKNOWN)
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "unsupported refinement mode '%s'",
                  mode_name ? mode_name : "");
      ok = FALSE;
    }
    else if(*pass_index == 0 || *max_passes == 0 || *pass_index > *max_passes)
    {
      g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                  "refinement passIndex/maxPasses must satisfy 1 <= passIndex <= maxPasses");
      ok = FALSE;
    }
    else if(require_continue_member)
    {
      *continue_refining = parsed_continue;
    }

    *enabled = parsed_enabled;
  }

  g_free(mode_name);
  return ok;
}

static void _serialize_choice_options(JsonBuilder *builder, const GPtrArray *choices)
{
  if(!choices)
  {
    json_builder_add_null_value(builder);
    return;
  }

  json_builder_begin_array(builder);
  for(guint i = 0; i < choices->len; i++)
  {
    const dt_agent_choice_option_t *option = g_ptr_array_index((GPtrArray *)choices, i);
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "choiceValue");
    json_builder_add_int_value(builder, option->choice_value);
    json_builder_set_member_name(builder, "choiceId");
    json_builder_add_string_value(builder, option->choice_id);
    json_builder_set_member_name(builder, "label");
    json_builder_add_string_value(builder, option->label);
    json_builder_end_object(builder);
  }
  json_builder_end_array(builder);
}

static void _serialize_capabilities(JsonBuilder *builder, const GPtrArray *capabilities)
{
  json_builder_begin_array(builder);

  if(capabilities)
  {
    for(guint i = 0; i < capabilities->len; i++)
    {
      const dt_agent_capability_t *capability = g_ptr_array_index((GPtrArray *)capabilities, i);
      json_builder_begin_object(builder);

      json_builder_set_member_name(builder, "moduleId");
      json_builder_add_string_value(builder, capability->module_id);
      json_builder_set_member_name(builder, "moduleLabel");
      json_builder_add_string_value(builder, capability->module_label);
      json_builder_set_member_name(builder, "capabilityId");
      json_builder_add_string_value(builder, capability->capability_id);
      json_builder_set_member_name(builder, "label");
      json_builder_add_string_value(builder, capability->label);
      json_builder_set_member_name(builder, "kind");
      json_builder_add_string_value(builder, capability->kind);
      json_builder_set_member_name(builder, "targetType");
      json_builder_add_string_value(builder, capability->target_type);
      json_builder_set_member_name(builder, "actionPath");
      json_builder_add_string_value(builder, capability->action_path);

      json_builder_set_member_name(builder, "supportedModes");
      json_builder_begin_array(builder);
      if((capability->supported_modes & DT_AGENT_VALUE_MODE_FLAG_SET) != 0)
        json_builder_add_string_value(builder, "set");
      if((capability->supported_modes & DT_AGENT_VALUE_MODE_FLAG_DELTA) != 0)
        json_builder_add_string_value(builder, "delta");
      json_builder_end_array(builder);

      if(g_strcmp0(capability->kind, "set-float") == 0)
      {
        json_builder_set_member_name(builder, "minNumber");
        json_builder_add_double_value(builder, capability->min_number);
        json_builder_set_member_name(builder, "maxNumber");
        json_builder_add_double_value(builder, capability->max_number);
        json_builder_set_member_name(builder, "defaultNumber");
        json_builder_add_double_value(builder, capability->default_number);
        json_builder_set_member_name(builder, "stepNumber");
        json_builder_add_double_value(builder, capability->step_number);
      }
      else
      {
        json_builder_set_member_name(builder, "minNumber");
        json_builder_add_null_value(builder);
        json_builder_set_member_name(builder, "maxNumber");
        json_builder_add_null_value(builder);
        json_builder_set_member_name(builder, "defaultNumber");
        json_builder_add_null_value(builder);
        json_builder_set_member_name(builder, "stepNumber");
        json_builder_add_null_value(builder);
      }

      json_builder_set_member_name(builder, "choices");
      _serialize_choice_options(builder, capability->choices);

      json_builder_set_member_name(builder, "defaultChoiceValue");
      if(capability->has_default_choice_value)
        json_builder_add_int_value(builder, capability->default_choice_value);
      else
        json_builder_add_null_value(builder);

      json_builder_set_member_name(builder, "defaultBool");
      if(capability->has_default_bool)
        json_builder_add_boolean_value(builder, capability->default_bool);
      else
        json_builder_add_null_value(builder);

      json_builder_end_object(builder);
    }
  }

  json_builder_end_array(builder);
}

static gchar *_build_image_revision_id(const dt_agent_chat_request_t *request)
{
  if(request && request->image_revision_id && request->image_revision_id[0])
    return g_strdup(request->image_revision_id);

  if(request && request->ui_context.has_image_id)
    return g_strdup_printf("image-%" G_GINT64_FORMAT "-history-%d-%d",
                           request->ui_context.image_id,
                           request->image_state.history_position,
                           request->image_state.history_count);

  return g_strdup("image-unknown");
}

static void _serialize_image_snapshot(JsonBuilder *builder,
                                      const dt_agent_chat_request_t *request)
{
  const dt_agent_image_state_t *state = &request->image_state;

  json_builder_set_member_name(builder, "imageSnapshot");
  json_builder_begin_object(builder);

  g_autofree gchar *image_revision_id = _build_image_revision_id(request);
  json_builder_set_member_name(builder, "imageRevisionId");
  json_builder_add_string_value(builder, image_revision_id);

  json_builder_set_member_name(builder, "historyPosition");
  json_builder_add_int_value(builder, state->history_position);

  json_builder_set_member_name(builder, "historyCount");
  json_builder_add_int_value(builder, state->history_count);

  json_builder_set_member_name(builder, "metadata");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "imageId");
  if(state->metadata.has_image_id)
    json_builder_add_int_value(builder, state->metadata.image_id);
  else
    json_builder_add_null_value(builder);
  json_builder_set_member_name(builder, "imageName");
  if(state->metadata.image_name)
    json_builder_add_string_value(builder, state->metadata.image_name);
  else
    json_builder_add_null_value(builder);
  json_builder_set_member_name(builder, "cameraMaker");
  if(state->metadata.camera_maker)
    json_builder_add_string_value(builder, state->metadata.camera_maker);
  else
    json_builder_add_null_value(builder);
  json_builder_set_member_name(builder, "cameraModel");
  if(state->metadata.camera_model)
    json_builder_add_string_value(builder, state->metadata.camera_model);
  else
    json_builder_add_null_value(builder);
  json_builder_set_member_name(builder, "width");
  json_builder_add_int_value(builder, state->metadata.width);
  json_builder_set_member_name(builder, "height");
  json_builder_add_int_value(builder, state->metadata.height);
  json_builder_set_member_name(builder, "exifExposureSeconds");
  json_builder_add_double_value(builder, state->metadata.exif_exposure_seconds);
  json_builder_set_member_name(builder, "exifAperture");
  json_builder_add_double_value(builder, state->metadata.exif_aperture);
  json_builder_set_member_name(builder, "exifIso");
  json_builder_add_double_value(builder, state->metadata.exif_iso);
  json_builder_set_member_name(builder, "exifFocalLength");
  json_builder_add_double_value(builder, state->metadata.exif_focal_length);
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "editableSettings");
  json_builder_begin_array(builder);
  for(guint i = 0; i < state->controls->len; i++)
  {
    const dt_agent_image_control_t *control = g_ptr_array_index(state->controls, i);

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "moduleId");
    json_builder_add_string_value(builder, control->module_id);
    json_builder_set_member_name(builder, "moduleLabel");
    json_builder_add_string_value(builder, control->module_label);
    json_builder_set_member_name(builder, "settingId");
    if(control->setting_id)
      json_builder_add_string_value(builder, control->setting_id);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "capabilityId");
    json_builder_add_string_value(builder, control->capability_id);
    json_builder_set_member_name(builder, "label");
    json_builder_add_string_value(builder, control->label);
    json_builder_set_member_name(builder, "kind");
    json_builder_add_string_value(builder, control->kind);
    json_builder_set_member_name(builder, "actionPath");
    json_builder_add_string_value(builder, control->action_path);

    json_builder_set_member_name(builder, "supportedModes");
    json_builder_begin_array(builder);
    if(control->supported_modes & DT_AGENT_VALUE_MODE_FLAG_SET)
      json_builder_add_string_value(builder, "set");
    if(control->supported_modes & DT_AGENT_VALUE_MODE_FLAG_DELTA)
      json_builder_add_string_value(builder, "delta");
    json_builder_end_array(builder);

    json_builder_set_member_name(builder, "minNumber");
    if(g_strcmp0(control->kind, "set-float") == 0)
      json_builder_add_double_value(builder, control->min_number);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "maxNumber");
    if(g_strcmp0(control->kind, "set-float") == 0)
      json_builder_add_double_value(builder, control->max_number);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "defaultNumber");
    if(g_strcmp0(control->kind, "set-float") == 0)
      json_builder_add_double_value(builder, control->default_number);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "stepNumber");
    if(g_strcmp0(control->kind, "set-float") == 0)
      json_builder_add_double_value(builder, control->step_number);
    else
      json_builder_add_null_value(builder);

    json_builder_set_member_name(builder, "currentNumber");
    if(control->has_current_number)
      json_builder_add_double_value(builder, control->current_number);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "choices");
    _serialize_choice_options(builder, control->choices);
    json_builder_set_member_name(builder, "defaultChoiceValue");
    if(control->has_default_choice_value)
      json_builder_add_int_value(builder, control->default_choice_value);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "currentChoiceValue");
    if(control->has_current_choice_value)
      json_builder_add_int_value(builder, control->current_choice_value);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "currentChoiceId");
    if(control->current_choice_id)
      json_builder_add_string_value(builder, control->current_choice_id);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "defaultBool");
    if(control->has_default_bool)
      json_builder_add_boolean_value(builder, control->default_bool);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "currentBool");
    if(control->has_current_bool)
      json_builder_add_boolean_value(builder, control->current_bool);
    else
      json_builder_add_null_value(builder);
    json_builder_end_object(builder);
  }
  json_builder_end_array(builder);

  json_builder_set_member_name(builder, "history");
  json_builder_begin_array(builder);
  for(guint i = 0; i < state->history->len; i++)
  {
    const dt_agent_history_item_t *item = g_ptr_array_index(state->history, i);
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "num");
    json_builder_add_int_value(builder, item->num);
    json_builder_set_member_name(builder, "module");
    if(item->module)
      json_builder_add_string_value(builder, item->module);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "enabled");
    json_builder_add_boolean_value(builder, item->enabled);
    json_builder_set_member_name(builder, "multiPriority");
    json_builder_add_int_value(builder, item->multi_priority);
    json_builder_set_member_name(builder, "instanceName");
    if(item->instance_name)
      json_builder_add_string_value(builder, item->instance_name);
    else
      json_builder_add_null_value(builder);
    json_builder_set_member_name(builder, "iopOrder");
    json_builder_add_int_value(builder, item->iop_order);
    json_builder_end_object(builder);
  }
  json_builder_end_array(builder);

  json_builder_set_member_name(builder, "preview");
  if(state->preview.available)
  {
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "previewId");
    json_builder_add_string_value(builder, state->preview.preview_id);
    json_builder_set_member_name(builder, "mimeType");
    json_builder_add_string_value(builder, state->preview.mime_type);
    json_builder_set_member_name(builder, "width");
    json_builder_add_int_value(builder, state->preview.width);
    json_builder_set_member_name(builder, "height");
    json_builder_add_int_value(builder, state->preview.height);
    json_builder_set_member_name(builder, "base64Data");
    json_builder_add_string_value(builder, state->preview.base64_data);
    json_builder_end_object(builder);
  }
  else
    json_builder_add_null_value(builder);

  json_builder_set_member_name(builder, "histogram");
  if(state->histogram.available)
  {
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "binCount");
    json_builder_add_int_value(builder, state->histogram.bin_count);
    json_builder_set_member_name(builder, "channels");
    json_builder_begin_object(builder);
    const struct
    {
      const char *name;
      const guint32 *bins;
    } channels[] = {
      { "red", state->histogram.red },
      { "green", state->histogram.green },
      { "blue", state->histogram.blue },
      { "luma", state->histogram.luma },
    };
    for(guint channel_index = 0; channel_index < G_N_ELEMENTS(channels); channel_index++)
    {
      json_builder_set_member_name(builder, channels[channel_index].name);
      json_builder_begin_object(builder);
      json_builder_set_member_name(builder, "bins");
      json_builder_begin_array(builder);
      for(gint bin_index = 0; bin_index < state->histogram.bin_count; bin_index++)
        json_builder_add_int_value(builder, channels[channel_index].bins[bin_index]);
      json_builder_end_array(builder);
      json_builder_end_object(builder);
    }
    json_builder_end_object(builder);
    json_builder_end_object(builder);
  }
  else
    json_builder_add_null_value(builder);

  json_builder_end_object(builder);
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
  dt_agent_chat_operation_t *operation = g_new0(dt_agent_chat_operation_t, 1);

  if(!_require_string_member(object, "operationId", &operation->operation_id, error)
     || !_require_string_member(object, "kind", &operation->kind_name, error))
  {
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  operation->status = g_strdup("planned");

  operation->kind = dt_agent_operation_kind_from_string(operation->kind_name);
  if(operation->kind == DT_AGENT_OPERATION_UNKNOWN)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported operation kind '%s'",
                operation->kind_name ? operation->kind_name : "");
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
  if(!_require_string_member(target, "settingId", &operation->setting_id, error))
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
  if(!_require_string_member(value, "mode", &value_mode_name, error))
  {
    g_free(value_mode_name);
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  operation->value_mode = dt_agent_value_mode_from_string(value_mode_name);
  g_free(value_mode_name);

  if(json_object_has_member(object, "sequence"))
  {
    JsonNode *sequence_node = json_object_get_member(object, "sequence");
    if(JSON_NODE_HOLDS_VALUE(sequence_node)
       && g_type_is_a(json_node_get_value_type(sequence_node), G_TYPE_INT64))
      operation->sequence = json_node_get_int(sequence_node);
  }

  if(operation->value_mode == DT_AGENT_VALUE_MODE_UNKNOWN)
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "unsupported value mode");
    dt_agent_chat_operation_free(operation);
    return FALSE;
  }

  switch(operation->kind)
  {
    case DT_AGENT_OPERATION_SET_FLOAT:
      if(!_require_number_member(value, "number", &operation->number, error))
      {
        dt_agent_chat_operation_free(operation);
        return FALSE;
      }
      break;
    case DT_AGENT_OPERATION_SET_CHOICE:
      {
        JsonNode *choice_value_node = json_object_get_member(value, "choiceValue");
        if(!choice_value_node || !JSON_NODE_HOLDS_VALUE(choice_value_node)
           || !g_type_is_a(json_node_get_value_type(choice_value_node), G_TYPE_INT64))
        {
          g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                      "choice operations require integer choiceValue");
          dt_agent_chat_operation_free(operation);
          return FALSE;
        }
        operation->has_choice_value = TRUE;
        operation->choice_value = json_node_get_int(choice_value_node);
        if(json_object_has_member(value, "choiceId"))
        {
          JsonNode *choice_id_node = json_object_get_member(value, "choiceId");
          if(JSON_NODE_HOLDS_VALUE(choice_id_node)
             && g_type_is_a(json_node_get_value_type(choice_id_node), G_TYPE_STRING))
          {
            const char *choice_id = json_node_get_string(choice_id_node);
            if(choice_id && choice_id[0])
              operation->choice_id = g_strdup(choice_id);
          }
        }
      }
      break;
    case DT_AGENT_OPERATION_SET_BOOL:
      {
        JsonNode *bool_value_node = json_object_get_member(value, "boolValue");
        if(!bool_value_node || !JSON_NODE_HOLDS_VALUE(bool_value_node)
           || !g_type_is_a(json_node_get_value_type(bool_value_node), G_TYPE_BOOLEAN))
        {
          g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                      "bool operations require boolean boolValue");
          dt_agent_chat_operation_free(operation);
          return FALSE;
        }
        operation->has_bool_value = TRUE;
        operation->bool_value = json_node_get_boolean(bool_value_node);
      }
      break;
    case DT_AGENT_OPERATION_UNKNOWN:
    default:
      break;
  }

  *out = operation;
  return TRUE;
}

static gboolean _parse_session(JsonObject *object,
                               char **app_session_id,
                               char **image_session_id,
                               char **conversation_id,
                               char **turn_id,
                               GError **error)
{
  if(!json_object_has_member(object, "session"))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "missing required member 'session'");
    return FALSE;
  }

  JsonNode *node = json_object_get_member(object, "session");
  if(!JSON_NODE_HOLDS_OBJECT(node))
  {
    g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                "member 'session' must be an object");
    return FALSE;
  }

  JsonObject *session = json_node_get_object(node);
  return _require_string_member(session, "appSessionId", app_session_id, error)
      && _require_string_member(session, "imageSessionId", image_session_id, error)
      && _require_string_member(session, "conversationId", conversation_id, error)
      && _require_string_member(session, "turnId", turn_id, error);
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
  request->refinement_mode = DT_AGENT_REFINEMENT_MODE_SINGLE;
  request->refinement_enabled = FALSE;
  request->refinement_pass_index = 1;
  request->refinement_max_passes = 1;
  request->refinement_fast_mode = FALSE;
  request->refinement_automatic_continuation = FALSE;
  request->capabilities = g_ptr_array_new_with_free_func(dt_agent_capability_free);
}

void dt_agent_chat_request_clear(dt_agent_chat_request_t *request)
{
  if(!request)
    return;

  g_free(request->schema_version);
  g_free(request->request_id);
  g_free(request->app_session_id);
  g_free(request->image_session_id);
  g_free(request->conversation_id);
  g_free(request->turn_id);
  g_free(request->image_revision_id);
  g_free(request->message_text);
  g_free(request->refinement_goal_text);
  dt_agent_ui_context_clear(&request->ui_context);
  if(request->capabilities)
    g_ptr_array_unref(request->capabilities);
  dt_agent_image_state_clear(&request->image_state);
  memset(request, 0, sizeof(*request));
}

void dt_agent_chat_request_copy(dt_agent_chat_request_t *dest,
                                const dt_agent_chat_request_t *src)
{
  dt_agent_chat_request_init(dest);
  g_free(dest->schema_version);
  dest->schema_version = g_strdup(src->schema_version);
  dest->request_id = g_strdup(src->request_id);
  dest->app_session_id = g_strdup(src->app_session_id);
  dest->image_session_id = g_strdup(src->image_session_id);
  dest->conversation_id = g_strdup(src->conversation_id);
  dest->turn_id = g_strdup(src->turn_id);
  dest->image_revision_id = g_strdup(src->image_revision_id);
  dest->message_text = g_strdup(src->message_text);
  dest->refinement_mode = src->refinement_mode;
  dest->refinement_enabled = src->refinement_enabled;
  dest->refinement_pass_index = src->refinement_pass_index;
  dest->refinement_max_passes = src->refinement_max_passes;
  dest->refinement_fast_mode = src->refinement_fast_mode;
  dest->refinement_automatic_continuation = src->refinement_automatic_continuation;
  dest->refinement_goal_text = g_strdup(src->refinement_goal_text);
  dest->ui_context.view = g_strdup(src->ui_context.view);
  dest->ui_context.has_image_id = src->ui_context.has_image_id;
  dest->ui_context.image_id = src->ui_context.image_id;
  dest->ui_context.image_name = g_strdup(src->ui_context.image_name);
  for(guint i = 0; src->capabilities && i < src->capabilities->len; i++)
  {
    const dt_agent_capability_t *capability = g_ptr_array_index(src->capabilities, i);
    g_ptr_array_add(dest->capabilities, dt_agent_capability_copy(capability));
  }
  dt_agent_image_state_copy(&dest->image_state, &src->image_state);
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
  g_free(operation->setting_id);
  g_free(operation->choice_id);
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
  g_free(response->app_session_id);
  g_free(response->image_session_id);
  g_free(response->conversation_id);
  g_free(response->turn_id);
  g_free(response->plan_id);
  g_free(response->base_image_revision_id);
  g_free(response->status);
  g_free(response->message_role);
  g_free(response->message_text);
  if(response->operations)
    g_ptr_array_unref(response->operations);
  g_free(response->refinement_stop_reason);
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
    case DT_AGENT_OPERATION_SET_CHOICE:
      return "set-choice";
    case DT_AGENT_OPERATION_SET_BOOL:
      return "set-bool";
    case DT_AGENT_OPERATION_UNKNOWN:
    default:
      return "unknown";
  }
}

dt_agent_operation_kind_t dt_agent_operation_kind_from_string(const char *kind_name)
{
  if(g_strcmp0(kind_name, "set-float") == 0)
    return DT_AGENT_OPERATION_SET_FLOAT;
  if(g_strcmp0(kind_name, "set-choice") == 0)
    return DT_AGENT_OPERATION_SET_CHOICE;
  if(g_strcmp0(kind_name, "set-bool") == 0)
    return DT_AGENT_OPERATION_SET_BOOL;

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

const char *dt_agent_refinement_mode_to_string(dt_agent_refinement_mode_t mode)
{
  switch(mode)
  {
    case DT_AGENT_REFINEMENT_MODE_SINGLE:
      return "single-turn";
    case DT_AGENT_REFINEMENT_MODE_MULTI:
      return "multi-turn";
    case DT_AGENT_REFINEMENT_MODE_UNKNOWN:
    default:
      return "unknown";
  }
}

dt_agent_refinement_mode_t dt_agent_refinement_mode_from_string(const char *mode_name)
{
  if(g_strcmp0(mode_name, "single-turn") == 0)
    return DT_AGENT_REFINEMENT_MODE_SINGLE;
  if(g_strcmp0(mode_name, "multi-turn") == 0)
    return DT_AGENT_REFINEMENT_MODE_MULTI;

  return DT_AGENT_REFINEMENT_MODE_UNKNOWN;
}

gchar *dt_agent_chat_request_serialize(const dt_agent_chat_request_t *request,
                                       GError **error)
{
  if(!request || !request->request_id || !request->app_session_id
     || !request->image_session_id || !request->conversation_id || !request->turn_id
     || !request->message_text || !request->ui_context.view
     || !request->capabilities || request->capabilities->len == 0
     || request->refinement_mode == DT_AGENT_REFINEMENT_MODE_UNKNOWN
     || !request->refinement_goal_text || !request->refinement_goal_text[0]
     || request->refinement_enabled != (request->refinement_mode == DT_AGENT_REFINEMENT_MODE_MULTI)
     || request->refinement_pass_index == 0
     || request->refinement_max_passes == 0
     || request->refinement_pass_index > request->refinement_max_passes
     || (!request->refinement_enabled
         && (request->refinement_pass_index != 1
             || request->refinement_max_passes != 1
             || request->refinement_automatic_continuation)))
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

  json_builder_set_member_name(builder, "session");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "appSessionId");
  json_builder_add_string_value(builder, request->app_session_id);
  json_builder_set_member_name(builder, "imageSessionId");
  json_builder_add_string_value(builder, request->image_session_id);
  json_builder_set_member_name(builder, "conversationId");
  json_builder_add_string_value(builder, request->conversation_id);
  json_builder_set_member_name(builder, "turnId");
  json_builder_add_string_value(builder, request->turn_id);
  json_builder_end_object(builder);

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

  json_builder_set_member_name(builder, "refinement");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "mode");
  json_builder_add_string_value(builder,
                                dt_agent_refinement_mode_to_string(request->refinement_mode));
  json_builder_set_member_name(builder, "enabled");
  json_builder_add_boolean_value(builder, request->refinement_enabled);
  json_builder_set_member_name(builder, "passIndex");
  json_builder_add_int_value(builder, MAX(1, (gint)request->refinement_pass_index));
  json_builder_set_member_name(builder, "maxPasses");
  json_builder_add_int_value(builder, MAX(1, (gint)request->refinement_max_passes));
  json_builder_set_member_name(builder, "fastMode");
  json_builder_add_boolean_value(builder, request->refinement_fast_mode);
  json_builder_set_member_name(builder, "automaticContinuation");
  json_builder_add_boolean_value(builder, request->refinement_automatic_continuation);
  json_builder_set_member_name(builder, "goalText");
  json_builder_add_string_value(builder, request->refinement_goal_text);
  json_builder_end_object(builder);

  json_builder_set_member_name(builder, "capabilityManifest");
  json_builder_begin_object(builder);
  json_builder_set_member_name(builder, "manifestVersion");
  json_builder_add_string_value(builder, "darktable-agent-live");
  json_builder_set_member_name(builder, "targets");
  _serialize_capabilities(builder, request->capabilities);
  json_builder_end_object(builder);
  _serialize_image_snapshot(builder, request);

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
             && _parse_session(object,
                               &response->app_session_id,
                               &response->image_session_id,
                               &response->conversation_id,
                               &response->turn_id,
                               error)
             && _require_string_member(object, "status", &response->status, error)
             && _parse_message(object, "assistantMessage",
                               &response->message_role, &response->message_text, error)
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

    if(ok)
    {
      ok = _parse_refinement(object, "refinement",
                             &response->refinement_mode,
                             &response->refinement_enabled,
                             &response->refinement_pass_index,
                             &response->refinement_max_passes,
                             &response->refinement_continue,
                             &response->refinement_stop_reason,
                             g_strcmp0(response->status, "ok") == 0,
                             error);
    }

    if(!ok)
      goto cleanup;

    if(g_strcmp0(response->status, "ok") == 0)
    {
      if(!json_object_has_member(object, "plan"))
      {
        g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                    "missing required member 'plan'");
        ok = FALSE;
      }
      else
      {
        JsonNode *plan_node = json_object_get_member(object, "plan");
        if(!JSON_NODE_HOLDS_OBJECT(plan_node))
        {
          g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                      "member 'plan' must be an object");
          ok = FALSE;
        }
        else
        {
          JsonObject *plan = json_node_get_object(plan_node);
          ok = _require_string_member(plan, "planId", &response->plan_id, error)
             && _require_string_member(plan, "baseImageRevisionId",
                                       &response->base_image_revision_id, error);

          if(!ok)
            goto cleanup;

          if(!json_object_has_member(plan, "operations"))
          {
            g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                        "plan must include operations");
            ok = FALSE;
          }
          else
          {
            JsonNode *operations_node = json_object_get_member(plan, "operations");
            if(!JSON_NODE_HOLDS_ARRAY(operations_node))
            {
              g_set_error(error, _agent_protocol_error_quark(), DT_AGENT_PROTOCOL_ERROR_INVALID,
                          "plan operations must be an array");
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
