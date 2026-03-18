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

#include "common/agent_catalog.h"

#include "bauhaus/bauhaus.h"
#include "common/darktable.h"
#include "common/introspection.h"
#include "develop/develop.h"
#include "develop/imageop.h"
#include "gui/accelerators.h"
#include "gui/draw.h"

#include <glib/gi18n.h>
#include <float.h>
#include <math.h>
#include <string.h>

typedef enum dt_agent_catalog_error_t
{
  DT_AGENT_CATALOG_ERROR_INVALID = 1,
} dt_agent_catalog_error_t;

typedef struct dt_agent_colorzones_node_t
{
  float x;
  float y;
} dt_agent_colorzones_node_t;

enum
{
  DT_AGENT_RGBLEVELS_CHANNELS = 3,
  DT_AGENT_RGBLEVELS_HANDLES = 3,
  DT_AGENT_COLORZONES_CHANNELS = 3,
  DT_AGENT_COLORZONES_BANDS = 8,
};

static const char *const _rgblevels_channel_ids[DT_AGENT_RGBLEVELS_CHANNELS]
  = { "red", "green", "blue" };
static const char *const _rgblevels_channel_labels[DT_AGENT_RGBLEVELS_CHANNELS]
  = { "R", "G", "B" };
static const char *const _rgblevels_handle_ids[DT_AGENT_RGBLEVELS_HANDLES]
  = { "black", "gray", "white" };
static const char *const _rgblevels_handle_labels[DT_AGENT_RGBLEVELS_HANDLES]
  = { "black", "gray", "white" };

static const char *const _colorzones_channel_ids[DT_AGENT_COLORZONES_CHANNELS]
  = { "lightness", "chroma", "hue" };
static const char *const _colorzones_channel_labels[DT_AGENT_COLORZONES_CHANNELS]
  = { "lightness", "chroma", "hue" };
static const char *const _colorzones_band_ids[DT_AGENT_COLORZONES_BANDS]
  = { "red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta" };
static const char *const _colorzones_band_labels[DT_AGENT_COLORZONES_BANDS]
  = { "red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta" };

static GQuark _agent_catalog_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-catalog-error");
}

gboolean dt_agent_catalog_is_action_path_allowed(const char *action_path)
{
  return action_path && action_path[0];
}

static gchar *_action_full_id(dt_action_t *action)
{
  gchar *full_label = NULL;
  size_t owner_len = 0;
  size_t max_len = 2 * strlen(action->id) + 2;
  if(action->owner)
  {
    full_label = _action_full_id(action->owner);
    owner_len = strlen(full_label);
  }
  full_label = g_realloc(full_label, owner_len + max_len);
  gchar *d = full_label + owner_len;
  if(owner_len)
    *d++ = '/';
  for(const gchar *c = action->id; *c; c++)
  {
    if(strchr("@;/\\", *c))
    {
      *d++ = '@';
      *d++ = *c == ';' ? ':' : *c == '/' ? '<' : *c == '\\' ? '>' : '@';
    }
    else
      *d++ = *c;
  }
  *d = 0;
  return full_label;
}

static gchar *_sanitize_id_segment(const char *value)
{
  if(!value || !value[0])
    return g_strdup("unknown");

  gchar *sanitized = g_strdup(value);
  for(char *c = sanitized; *c; c++)
  {
    if((*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z') || (*c >= '0' && *c <= '9'))
      continue;
    *c = '.';
  }
  return sanitized;
}

static gchar *_build_setting_id(const char *action_path, const dt_iop_module_t *module)
{
  g_autofree gchar *sanitized = _sanitize_id_segment(action_path);
  return g_strdup_printf("setting.%s.instance.%d", sanitized, module ? module->multi_priority : 0);
}

static gchar *_build_setting_id_with_suffix(const char *action_path,
                                            const dt_iop_module_t *module,
                                            const char *suffix)
{
  g_autofree gchar *setting_id = _build_setting_id(action_path, module);
  if(!suffix || !suffix[0])
    return g_steal_pointer(&setting_id);

  g_autofree gchar *sanitized = _sanitize_id_segment(suffix);
  return g_strdup_printf("%s.%s", setting_id, sanitized);
}

static gchar *_build_capability_id(const char *setting_id)
{
  g_autofree gchar *sanitized = _sanitize_id_segment(setting_id);
  return g_strdup_printf("capability.%s", sanitized);
}

static gchar *_build_module_id(const dt_iop_module_t *module)
{
  return g_strdup((module && module->op[0]) ? module->op : "unknown");
}

static gchar *_build_module_label(const dt_iop_module_t *module)
{
  if(module && module->name)
  {
    const char *label = module->name();
    if(label && label[0])
      return g_strdup(label);
  }

  return g_strdup((module && module->op[0]) ? module->op : "unknown");
}

static dt_introspection_field_t *_find_field_by_name(const dt_iop_module_t *module,
                                                     const char *field_name)
{
  if(!module || !field_name || !field_name[0] || !module->have_introspection || !module->so
     || !module->so->get_introspection_linear)
    return NULL;

  for(dt_introspection_field_t *iter = module->so->get_introspection_linear();
      iter && iter->header.type != DT_INTROSPECTION_TYPE_NONE;
      iter++)
  {
    if(g_strcmp0(iter->header.field_name, field_name) == 0)
      return iter;
  }

  return NULL;
}

static gpointer _field_data(const dt_iop_module_t *module,
                            const dt_introspection_field_t *field,
                            const gboolean use_defaults)
{
  if(!module || !field)
    return NULL;

  guint8 *base = use_defaults ? (guint8 *)module->default_params : (guint8 *)module->params;
  if(!base)
    return NULL;

  return base + field->header.offset;
}

static dt_introspection_field_t *_find_field_for_widget(const dt_iop_module_t *module,
                                                        GtkWidget *widget,
                                                        const dt_action_target_t *referral)
{
  if(!module || !widget || !module->have_introspection || !module->so
     || !module->so->get_introspection_linear)
    return NULL;

  gpointer field = dt_bauhaus_widget_get_field(widget);
  if(field && module->params)
  {
    const ptrdiff_t offset = (const guint8 *)field - (const guint8 *)module->params;
    if(offset >= 0 && offset < module->params_size)
    {
      for(dt_introspection_field_t *iter = module->so->get_introspection_linear();
          iter && iter->header.type != DT_INTROSPECTION_TYPE_NONE;
          iter++)
      {
        if((ptrdiff_t)iter->header.offset == offset)
          return iter;
      }
    }
  }

  (void)referral;
  return NULL;
}

static gboolean _is_numeric_field(const dt_introspection_field_t *field)
{
  if(!field)
    return FALSE;

  switch(field->header.type)
  {
    case DT_INTROSPECTION_TYPE_FLOAT:
    case DT_INTROSPECTION_TYPE_DOUBLE:
    case DT_INTROSPECTION_TYPE_INT:
    case DT_INTROSPECTION_TYPE_UINT:
    case DT_INTROSPECTION_TYPE_SHORT:
    case DT_INTROSPECTION_TYPE_USHORT:
    case DT_INTROSPECTION_TYPE_INT8:
    case DT_INTROSPECTION_TYPE_UINT8:
    case DT_INTROSPECTION_TYPE_CHAR:
      return TRUE;
    default:
      return FALSE;
  }
}

static void _populate_choice_options(dt_agent_action_descriptor_t *descriptor,
                                     GtkWidget *widget,
                                     dt_action_t *action,
                                     const dt_introspection_field_t *field)
{
  descriptor->choices = g_ptr_array_new_with_free_func(dt_agent_choice_option_free);

  if(field && field->header.type == DT_INTROSPECTION_TYPE_ENUM && field->Enum.values)
  {
    for(dt_introspection_type_enum_tuple_t *value = field->Enum.values; value->name; value++)
    {
      dt_agent_choice_option_t *option = g_new0(dt_agent_choice_option_t, 1);
      option->choice_value = value->value;
      option->choice_id = g_strdup(value->name);
      option->label = g_strdup(value->description && value->description[0]
                                 ? value->description
                                 : value->name);
      g_ptr_array_add(descriptor->choices, option);
    }
    descriptor->has_default_choice_value = TRUE;
    descriptor->default_choice_value = field->Enum.Default;
    return;
  }

  const int current_index = dt_bauhaus_combobox_get(widget);
  for(int pos = 0;; pos++)
  {
    const char *entry = dt_bauhaus_combobox_get_entry(widget, pos);
    if(!entry)
      break;

    dt_agent_choice_option_t *option = g_new0(dt_agent_choice_option_t, 1);
    option->choice_value = pos;
    option->choice_id = g_strdup_printf("choice.%d", pos);
    option->label = g_strdup(entry);
    g_ptr_array_add(descriptor->choices, option);
  }

  if(current_index >= 0)
  {
    descriptor->has_default_choice_value = TRUE;
    descriptor->default_choice_value = dt_bauhaus_combobox_get_default(widget);
  }

  (void)action;
}

static gboolean _initialize_float_descriptor(dt_agent_action_descriptor_t *descriptor,
                                             GtkWidget *widget)
{
  if(!descriptor || !widget)
    return FALSE;

  double min_number = dt_bauhaus_slider_get_hard_min(widget);
  double max_number = dt_bauhaus_slider_get_hard_max(widget);
  double default_number = dt_bauhaus_slider_get_default(widget);
  double current_number = dt_bauhaus_slider_get(widget);
  double step_number = dt_bauhaus_slider_get_step(widget);

  if(!isfinite(current_number))
    return FALSE;

  if(!isfinite(min_number))
    min_number = current_number;
  if(!isfinite(max_number))
    max_number = current_number;

  if(min_number > max_number)
  {
    const double tmp = min_number;
    min_number = max_number;
    max_number = tmp;
  }

  if(!isfinite(default_number))
    default_number = current_number;
  default_number = CLAMP(default_number, min_number, max_number);

  if(!isfinite(step_number) || step_number <= 0.0)
  {
    const double range = fabs(max_number - min_number);
    step_number = range > 0.0 ? MAX(range / 1000.0, 0.0001) : 0.0001;
  }

  descriptor->supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET | DT_AGENT_VALUE_MODE_FLAG_DELTA;
  descriptor->has_number_range = TRUE;
  descriptor->min_number = min_number;
  descriptor->max_number = max_number;
  descriptor->default_number = default_number;
  descriptor->step_number = step_number;
  return TRUE;
}

static dt_agent_action_descriptor_t *_new_float_descriptor(dt_iop_module_t *module,
                                                           GtkWidget *widget,
                                                           const char *action_path,
                                                           const char *setting_suffix,
                                                           const char *label,
                                                           const double min_number,
                                                           const double max_number,
                                                           const double default_number,
                                                           const double step_number)
{
  dt_agent_action_descriptor_t *descriptor = g_new0(dt_agent_action_descriptor_t, 1);
  descriptor->module_id = _build_module_id(module);
  descriptor->module_label = _build_module_label(module);
  descriptor->setting_id = _build_setting_id_with_suffix(action_path, module, setting_suffix);
  descriptor->capability_id = _build_capability_id(descriptor->setting_id);
  descriptor->label = g_strdup(label);
  descriptor->kind_name = g_strdup(dt_agent_operation_kind_to_string(DT_AGENT_OPERATION_SET_FLOAT));
  descriptor->target_type = g_strdup("darktable-action");
  descriptor->action_path = g_strdup(action_path);
  descriptor->operation_kind = DT_AGENT_OPERATION_SET_FLOAT;
  descriptor->supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET | DT_AGENT_VALUE_MODE_FLAG_DELTA;
  descriptor->binding = DT_AGENT_DESCRIPTOR_BINDING_WIDGET;
  descriptor->module = module;
  descriptor->widget = widget;
  descriptor->has_number_range = TRUE;
  descriptor->min_number = min_number;
  descriptor->max_number = max_number;
  descriptor->default_number = default_number;
  descriptor->step_number = step_number;
  return descriptor;
}

static float *_rgblevels_value_pointer(const dt_iop_module_t *module,
                                       const gboolean use_defaults,
                                       const gint channel,
                                       const gint handle)
{
  dt_introspection_field_t *levels_field = _find_field_by_name(module, "levels");
  if(!levels_field || levels_field->header.type != DT_INTROSPECTION_TYPE_ARRAY)
    return NULL;

  gpointer levels = _field_data(module, levels_field, use_defaults);
  dt_introspection_field_t *row_field = NULL;
  gpointer row = dt_introspection_access_array(levels_field, levels, channel, &row_field);
  if(!row || !row_field || row_field->header.type != DT_INTROSPECTION_TYPE_ARRAY)
    return NULL;

  dt_introspection_field_t *value_field = NULL;
  gpointer value = dt_introspection_access_array(row_field, row, handle, &value_field);
  if(!value || !value_field || value_field->header.type != DT_INTROSPECTION_TYPE_FLOAT)
    return NULL;

  return value;
}

static gboolean _read_rgblevels_number(const dt_agent_action_descriptor_t *descriptor,
                                       double *out_number)
{
  if(!descriptor || !descriptor->module || !out_number)
    return FALSE;

  float *value = _rgblevels_value_pointer(descriptor->module, FALSE,
                                          descriptor->channel_index,
                                          descriptor->element_index);
  if(!value)
    return FALSE;

  *out_number = *value;
  return TRUE;
}

static gboolean _write_rgblevels_number(const dt_agent_action_descriptor_t *descriptor,
                                        const double requested_number,
                                        double *out_applied_number)
{
  if(!descriptor || !descriptor->module)
    return FALSE;

  if(DT_ACTION_IS_INVALID(dt_action_process("iop/rgblevels/channel",
                                            descriptor->module->multi_priority,
                                            _rgblevels_channel_ids[descriptor->channel_index],
                                            "activate",
                                            1.0f)))
    return FALSE;

  const float applied = dt_action_process(descriptor->action_path,
                                          descriptor->module->multi_priority,
                                          descriptor->element_name,
                                          "set",
                                          requested_number);
  if(DT_ACTION_IS_INVALID(applied))
    return FALSE;

  if(out_applied_number)
    *out_applied_number = applied;
  return TRUE;
}

static dt_draw_curve_t *_colorzones_curve(const dt_iop_module_t *module,
                                          const gboolean use_defaults,
                                          const gint channel_index)
{
  dt_introspection_field_t *curve_field = _find_field_by_name(module, "curve");
  dt_introspection_field_t *curve_num_nodes_field = _find_field_by_name(module, "curve_num_nodes");
  dt_introspection_field_t *curve_type_field = _find_field_by_name(module, "curve_type");
  dt_introspection_field_t *select_by_field = _find_field_by_name(module, "channel");
  dt_introspection_field_t *splines_version_field = _find_field_by_name(module, "splines_version");
  if(!curve_field || !curve_num_nodes_field || !curve_type_field || !select_by_field
     || !splines_version_field)
    return NULL;

  dt_introspection_field_t *channel_curve_field = NULL;
  gpointer curve_data = _field_data(module, curve_field, use_defaults);
  dt_agent_colorzones_node_t *curve = dt_introspection_access_array(curve_field,
                                                                    curve_data,
                                                                    channel_index,
                                                                    &channel_curve_field);
  if(!curve)
    return NULL;

  dt_introspection_field_t *nodes_field = NULL;
  gpointer nodes_data = _field_data(module, curve_num_nodes_field, use_defaults);
  int *nodes = dt_introspection_access_array(curve_num_nodes_field, nodes_data, channel_index, &nodes_field);
  if(!nodes || *nodes < 2)
    return NULL;

  dt_introspection_field_t *type_field = NULL;
  gpointer type_data = _field_data(module, curve_type_field, use_defaults);
  int *curve_type = dt_introspection_access_array(curve_type_field, type_data, channel_index, &type_field);
  int *select_by = _field_data(module, select_by_field, use_defaults);
  int *splines_version = _field_data(module, splines_version_field, use_defaults);
  if(!curve_type || !select_by || !splines_version)
    return NULL;

  dt_draw_curve_t *draw_curve = dt_draw_curve_new(0.0f, 1.0f, *curve_type);
  if(!draw_curve)
    return NULL;

  if(*splines_version == 0)
  {
    const gboolean periodic = *select_by == 2;
    dt_draw_curve_add_point(draw_curve, curve[*nodes - 2].x - 1.0f,
                            periodic ? curve[*nodes - 2].y : curve[0].y);
    for(int k = 0; k < *nodes; k++)
      dt_draw_curve_add_point(draw_curve, curve[k].x, curve[k].y);
    dt_draw_curve_add_point(draw_curve, curve[1].x + 1.0f,
                            periodic ? curve[1].y : curve[*nodes - 1].y);
  }
  else
  {
    for(int k = 0; k < *nodes; k++)
      dt_draw_curve_add_point(draw_curve, curve[k].x, curve[k].y);
  }

  return draw_curve;
}

static gboolean _colorzones_current_value(const dt_iop_module_t *module,
                                          const gboolean use_defaults,
                                          const gint channel_index,
                                          const gint band_index,
                                          double *out_number)
{
  if(!module || !out_number)
    return FALSE;

  dt_introspection_field_t *curve_field = _find_field_by_name(module, "curve");
  dt_introspection_field_t *curve_num_nodes_field = _find_field_by_name(module, "curve_num_nodes");
  if(!curve_field || !curve_num_nodes_field)
    return FALSE;

  dt_introspection_field_t *channel_curve_field = NULL;
  gpointer curve_data = _field_data(module, curve_field, use_defaults);
  dt_agent_colorzones_node_t *curve = dt_introspection_access_array(curve_field,
                                                                    curve_data,
                                                                    channel_index,
                                                                    &channel_curve_field);
  dt_introspection_field_t *nodes_field = NULL;
  gpointer nodes_data = _field_data(module, curve_num_nodes_field, use_defaults);
  int *nodes = dt_introspection_access_array(curve_num_nodes_field, nodes_data, channel_index, &nodes_field);
  if(!curve || !nodes || *nodes < 2)
    return FALSE;

  const float x = (float)band_index / DT_AGENT_COLORZONES_BANDS;
  for(int node_index = 0; node_index < *nodes; node_index++)
  {
    if(fabsf(curve[node_index].x - x) <= (1.0f / 16.0f))
    {
      *out_number = curve[node_index].y * 2.0 - 1.0;
      return TRUE;
    }
  }

  dt_draw_curve_t *draw_curve = _colorzones_curve(module, use_defaults, channel_index);
  if(!draw_curve)
    return FALSE;

  *out_number = dt_draw_curve_calc_value(draw_curve, x) * 2.0 - 1.0;
  dt_draw_curve_destroy(draw_curve);
  return TRUE;
}

static gboolean _read_colorzones_number(const dt_agent_action_descriptor_t *descriptor,
                                        double *out_number)
{
  if(!descriptor || !descriptor->module || !out_number)
    return FALSE;

  return _colorzones_current_value(descriptor->module,
                                   FALSE,
                                   descriptor->channel_index,
                                   descriptor->element_index,
                                   out_number);
}

static gboolean _write_colorzones_number(const dt_agent_action_descriptor_t *descriptor,
                                         const double requested_number,
                                         double *out_applied_number)
{
  if(!descriptor || !descriptor->module)
    return FALSE;

  const float y = CLAMP((float)((requested_number + 1.0) * 0.5), 0.0f, 1.0f);

  if(DT_ACTION_IS_INVALID(dt_action_process("iop/colorzones/channel",
                                            descriptor->module->multi_priority,
                                            _colorzones_channel_ids[descriptor->channel_index],
                                            "activate",
                                            1.0f)))
    return FALSE;

  const float applied = dt_action_process(descriptor->action_path,
                                          descriptor->module->multi_priority,
                                          descriptor->element_name,
                                          "set",
                                          y);
  if(DT_ACTION_IS_INVALID(applied))
    return FALSE;

  if(out_applied_number)
    *out_applied_number = (applied - DT_VALUE_PATTERN_PLUS_MINUS) * 2.0 - 1.0;
  return TRUE;
}

static void _collect_rgblevels_descriptors(dt_iop_module_t *module,
                                           dt_action_target_t *referral,
                                           GPtrArray *descriptors)
{
  if(!module || !referral || !referral->action || g_strcmp0(module->op, "rgblevels") != 0
     || g_strcmp0(referral->action->id, "levels") != 0)
    return;

  g_autofree gchar *action_path = _action_full_id(referral->action);
  if(!dt_agent_catalog_is_action_path_allowed(action_path))
    return;

  for(int channel = 0; channel < DT_AGENT_RGBLEVELS_CHANNELS; channel++)
    for(int handle = 0; handle < DT_AGENT_RGBLEVELS_HANDLES; handle++)
    {
      float *default_value = _rgblevels_value_pointer(module, TRUE, channel, handle);
      if(!default_value)
        continue;

      g_autofree gchar *setting_suffix = g_strdup_printf("%s.%s",
                                                         _rgblevels_channel_ids[channel],
                                                         _rgblevels_handle_ids[handle]);
      g_autofree gchar *label = g_strdup_printf("%s %s",
                                                _rgblevels_channel_labels[channel],
                                                _rgblevels_handle_labels[handle]);
      dt_agent_action_descriptor_t *descriptor = _new_float_descriptor(module,
                                                                       GTK_IS_WIDGET(referral->target)
                                                                         ? GTK_WIDGET(referral->target)
                                                                         : NULL,
                                                                       action_path,
                                                                       setting_suffix,
                                                                       label,
                                                                       0.0,
                                                                       1.0,
                                                                       *default_value,
                                                                       0.001);
      descriptor->binding = DT_AGENT_DESCRIPTOR_BINDING_RGBLEVELS_HANDLE;
      descriptor->element_name = g_strdup(_rgblevels_handle_ids[handle]);
      descriptor->channel_index = channel;
      descriptor->element_index = handle;
      g_ptr_array_add(descriptors, descriptor);
    }
}

static void _collect_colorzones_descriptors(dt_iop_module_t *module,
                                            dt_action_target_t *referral,
                                            GPtrArray *descriptors)
{
  if(!module || !referral || !referral->action || g_strcmp0(module->op, "colorzones") != 0
     || g_strcmp0(referral->action->id, "graph") != 0)
    return;

  g_autofree gchar *action_path = _action_full_id(referral->action);
  if(!dt_agent_catalog_is_action_path_allowed(action_path))
    return;

  for(int channel = 0; channel < DT_AGENT_COLORZONES_CHANNELS; channel++)
    for(int band = 0; band < DT_AGENT_COLORZONES_BANDS; band++)
    {
      double default_number = 0.0;
      if(!_colorzones_current_value(module, TRUE, channel, band, &default_number))
        continue;

      g_autofree gchar *setting_suffix = g_strdup_printf("%s.%s",
                                                         _colorzones_channel_ids[channel],
                                                         _colorzones_band_ids[band]);
      g_autofree gchar *label = g_strdup_printf("%s %s",
                                                _colorzones_channel_labels[channel],
                                                _colorzones_band_labels[band]);
      dt_agent_action_descriptor_t *descriptor = _new_float_descriptor(module,
                                                                       GTK_IS_WIDGET(referral->target)
                                                                         ? GTK_WIDGET(referral->target)
                                                                         : NULL,
                                                                       action_path,
                                                                       setting_suffix,
                                                                       label,
                                                                       -1.0,
                                                                       1.0,
                                                                       default_number,
                                                                       0.01);
      descriptor->binding = DT_AGENT_DESCRIPTOR_BINDING_COLORZONES_BAND;
      descriptor->element_name = g_strdup(_colorzones_band_ids[band]);
      descriptor->channel_index = channel;
      descriptor->element_index = band;
      g_ptr_array_add(descriptors, descriptor);
    }
}

static dt_agent_action_descriptor_t *_descriptor_for_widget(dt_iop_module_t *module,
                                                            dt_action_target_t *referral)
{
  if(!module || !referral || !referral->action || !referral->target)
    return NULL;
  if(!GTK_IS_WIDGET(referral->target))
    return NULL;

  GtkWidget *widget = GTK_WIDGET(referral->target);
  dt_introspection_field_t *field = _find_field_for_widget(module, widget, referral);
  if(!field)
    return NULL;

  dt_agent_operation_kind_t operation_kind = DT_AGENT_OPERATION_UNKNOWN;
  if(_is_numeric_field(field))
    operation_kind = DT_AGENT_OPERATION_SET_FLOAT;
  else if(field->header.type == DT_INTROSPECTION_TYPE_ENUM)
    operation_kind = DT_AGENT_OPERATION_SET_CHOICE;
  else if(field->header.type == DT_INTROSPECTION_TYPE_BOOL)
    operation_kind = DT_AGENT_OPERATION_SET_BOOL;

  if(operation_kind == DT_AGENT_OPERATION_UNKNOWN)
    return NULL;

  g_autofree gchar *action_path = _action_full_id(referral->action);
  if(!dt_agent_catalog_is_action_path_allowed(action_path))
    return NULL;

  dt_agent_action_descriptor_t *descriptor = g_new0(dt_agent_action_descriptor_t, 1);
  descriptor->module_id = _build_module_id(module);
  descriptor->module_label = _build_module_label(module);
  descriptor->setting_id = _build_setting_id(action_path, module);
  descriptor->capability_id = _build_capability_id(descriptor->setting_id);
  descriptor->label = g_strdup(referral->action->label ? referral->action->label
                                                       : field->header.field_name);
  descriptor->kind_name = g_strdup(dt_agent_operation_kind_to_string(operation_kind));
  descriptor->target_type = g_strdup("darktable-action");
  descriptor->action_path = g_strdup(action_path);
  descriptor->operation_kind = operation_kind;
  descriptor->binding = DT_AGENT_DESCRIPTOR_BINDING_WIDGET;
  descriptor->module = module;
  descriptor->widget = widget;

  switch(operation_kind)
  {
    case DT_AGENT_OPERATION_SET_FLOAT:
      if(!_initialize_float_descriptor(descriptor, widget))
      {
        dt_agent_action_descriptor_free(descriptor);
        return NULL;
      }
      break;
    case DT_AGENT_OPERATION_SET_CHOICE:
      descriptor->supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET;
      _populate_choice_options(descriptor, widget, referral->action, field);
      break;
    case DT_AGENT_OPERATION_SET_BOOL:
      descriptor->supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET;
      descriptor->has_default_bool = TRUE;
      if(GTK_IS_TOGGLE_BUTTON(widget))
        descriptor->default_bool = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(widget));
      else
        descriptor->default_bool = field->Bool.Default;
      break;
    case DT_AGENT_OPERATION_UNKNOWN:
    default:
      break;
  }

  return descriptor;
}

static dt_agent_action_descriptor_t *_descriptor_for_module_toggle(dt_iop_module_t *module)
{
  if(!module || !module->off)
    return NULL;

  dt_action_target_t *referral = NULL;
  for(GSList *iter = module->widget_list; iter; iter = g_slist_next(iter))
  {
    dt_action_target_t *candidate = iter->data;
    if(candidate && candidate->target == module->off)
    {
      referral = candidate;
      break;
    }
  }

  if(!referral || !referral->action)
    return NULL;

  g_autofree gchar *action_path = _action_full_id(referral->action);
  if(!dt_agent_catalog_is_action_path_allowed(action_path))
    return NULL;

  dt_agent_action_descriptor_t *descriptor = g_new0(dt_agent_action_descriptor_t, 1);
  descriptor->module_id = _build_module_id(module);
  descriptor->module_label = _build_module_label(module);
  descriptor->setting_id = _build_setting_id(action_path, module);
  descriptor->capability_id = _build_capability_id(descriptor->setting_id);
  descriptor->label = g_strdup_printf("%s enabled", module->name());
  descriptor->kind_name = g_strdup("set-bool");
  descriptor->target_type = g_strdup("darktable-action");
  descriptor->action_path = g_strdup(action_path);
  descriptor->operation_kind = DT_AGENT_OPERATION_SET_BOOL;
  descriptor->supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET;
  descriptor->widget = module->off;
  descriptor->has_default_bool = TRUE;
  descriptor->default_bool = module->default_enabled;
  return descriptor;
}

static void _add_descriptor_unique(GPtrArray *descriptors,
                                   GHashTable *seen_setting_ids,
                                   dt_agent_action_descriptor_t *descriptor)
{
  if(!descriptors || !seen_setting_ids || !descriptor)
  {
    dt_agent_action_descriptor_free(descriptor);
    return;
  }

  if(!descriptor->setting_id || g_hash_table_contains(seen_setting_ids, descriptor->setting_id))
  {
    dt_agent_action_descriptor_free(descriptor);
    return;
  }
  if(!dt_agent_catalog_is_action_path_allowed(descriptor->action_path))
  {
    dt_agent_action_descriptor_free(descriptor);
    return;
  }

  g_hash_table_add(seen_setting_ids, g_strdup(descriptor->setting_id));
  g_ptr_array_add(descriptors, descriptor);
}

void dt_agent_action_descriptor_free(gpointer data)
{
  dt_agent_action_descriptor_t *descriptor = data;
  if(!descriptor)
    return;

  g_free(descriptor->module_id);
  g_free(descriptor->module_label);
  g_free(descriptor->capability_id);
  g_free(descriptor->setting_id);
  g_free(descriptor->label);
  g_free(descriptor->kind_name);
  g_free(descriptor->target_type);
  g_free(descriptor->action_path);
  g_free(descriptor->element_name);
  if(descriptor->choices)
    g_ptr_array_unref(descriptor->choices);
  g_free(descriptor);
}

dt_agent_action_descriptor_t *dt_agent_action_descriptor_copy(
  const dt_agent_action_descriptor_t *src)
{
  if(!src)
    return NULL;

  dt_agent_action_descriptor_t *dest = g_new0(dt_agent_action_descriptor_t, 1);
  dest->module_id = g_strdup(src->module_id);
  dest->module_label = g_strdup(src->module_label);
  dest->capability_id = g_strdup(src->capability_id);
  dest->setting_id = g_strdup(src->setting_id);
  dest->label = g_strdup(src->label);
  dest->kind_name = g_strdup(src->kind_name);
  dest->target_type = g_strdup(src->target_type);
  dest->action_path = g_strdup(src->action_path);
  dest->operation_kind = src->operation_kind;
  dest->supported_modes = src->supported_modes;
  dest->binding = src->binding;
  dest->module = src->module;
  dest->widget = src->widget;
  dest->element_name = g_strdup(src->element_name);
  dest->channel_index = src->channel_index;
  dest->element_index = src->element_index;
  dest->has_number_range = src->has_number_range;
  dest->min_number = src->min_number;
  dest->max_number = src->max_number;
  dest->default_number = src->default_number;
  dest->step_number = src->step_number;
  if(src->choices)
  {
    dest->choices = g_ptr_array_new_with_free_func(dt_agent_choice_option_free);
    for(guint i = 0; i < src->choices->len; i++)
    {
      dt_agent_choice_option_t *option = g_ptr_array_index(src->choices, i);
      g_ptr_array_add(dest->choices, dt_agent_choice_option_copy(option));
    }
  }
  dest->has_default_choice_value = src->has_default_choice_value;
  dest->default_choice_value = src->default_choice_value;
  dest->has_default_bool = src->has_default_bool;
  dest->default_bool = src->default_bool;
  return dest;
}

gboolean dt_agent_catalog_collect_descriptors(const dt_develop_t *dev,
                                              GPtrArray *descriptors,
                                              GError **error)
{
  if(!dev || !descriptors)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("missing darkroom state"));
    return FALSE;
  }

  g_ptr_array_set_size(descriptors, 0);
  g_autoptr(GHashTable) seen_setting_ids = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);

  for(const GList *iter = dev->iop; iter; iter = g_list_next(iter))
  {
    dt_iop_module_t *module = iter->data;
    if(!module)
      continue;

    dt_agent_action_descriptor_t *toggle_descriptor = _descriptor_for_module_toggle(module);
    _add_descriptor_unique(descriptors, seen_setting_ids, toggle_descriptor);

    for(GSList *widget_iter = module->widget_list; widget_iter; widget_iter = g_slist_next(widget_iter))
    {
      dt_action_target_t *referral = widget_iter->data;
      dt_agent_action_descriptor_t *descriptor = _descriptor_for_widget(module, referral);
      _add_descriptor_unique(descriptors, seen_setting_ids, descriptor);

      g_autoptr(GPtrArray) custom_descriptors = g_ptr_array_new();
      _collect_rgblevels_descriptors(module, referral, custom_descriptors);
      _collect_colorzones_descriptors(module, referral, custom_descriptors);
      while(custom_descriptors->len > 0)
      {
        dt_agent_action_descriptor_t *custom
          = g_ptr_array_remove_index_fast(custom_descriptors, custom_descriptors->len - 1);
        _add_descriptor_unique(descriptors, seen_setting_ids, custom);
      }
    }
  }

  return TRUE;
}

dt_agent_action_descriptor_t *dt_agent_catalog_find_descriptor(const dt_develop_t *dev,
                                                               const char *action_path,
                                                               const char *setting_id,
                                                               GError **error)
{
  if(!dt_agent_catalog_is_action_path_allowed(action_path))
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                _("unsupported action path: %s"),
                action_path ? action_path : _("unknown"));
    return NULL;
  }

  g_autoptr(GPtrArray) descriptors = g_ptr_array_new_with_free_func(dt_agent_action_descriptor_free);
  if(!dt_agent_catalog_collect_descriptors(dev, descriptors, error))
    return NULL;

  for(guint i = 0; i < descriptors->len; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = g_ptr_array_index(descriptors, i);
    if(g_strcmp0(descriptor->action_path, action_path) != 0)
      continue;
    if(setting_id && setting_id[0] && g_strcmp0(descriptor->setting_id, setting_id) != 0)
      continue;
    return dt_agent_action_descriptor_copy(descriptor);
  }

  g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
              _("unsupported action path: %s"),
              action_path ? action_path : _("unknown"));
  return NULL;
}

gboolean dt_agent_catalog_supports_mode(const dt_agent_action_descriptor_t *descriptor,
                                        dt_agent_value_mode_t mode)
{
  if(!descriptor)
    return FALSE;

  switch(mode)
  {
    case DT_AGENT_VALUE_MODE_SET:
      return (descriptor->supported_modes & DT_AGENT_VALUE_MODE_FLAG_SET) != 0;
    case DT_AGENT_VALUE_MODE_DELTA:
      return (descriptor->supported_modes & DT_AGENT_VALUE_MODE_FLAG_DELTA) != 0;
    case DT_AGENT_VALUE_MODE_UNKNOWN:
    default:
      return FALSE;
  }
}

double dt_agent_catalog_clamp_number(const dt_agent_action_descriptor_t *descriptor,
                                     double requested_number)
{
  if(!descriptor || !descriptor->has_number_range)
    return requested_number;

  return CLAMP(requested_number, descriptor->min_number, descriptor->max_number);
}

gboolean dt_agent_catalog_read_current_number(const dt_agent_action_descriptor_t *descriptor,
                                              double *out_number,
                                              GError **error)
{
  if(!descriptor || descriptor->operation_kind != DT_AGENT_OPERATION_SET_FLOAT || !out_number)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent action descriptor is incomplete"));
    return FALSE;
  }

  switch(descriptor->binding)
  {
    case DT_AGENT_DESCRIPTOR_BINDING_WIDGET:
      if(!descriptor->widget)
        break;
      *out_number = dt_bauhaus_slider_get(descriptor->widget);
      return TRUE;
    case DT_AGENT_DESCRIPTOR_BINDING_RGBLEVELS_HANDLE:
      return _read_rgblevels_number(descriptor, out_number);
    case DT_AGENT_DESCRIPTOR_BINDING_COLORZONES_BAND:
      return _read_colorzones_number(descriptor, out_number);
    default:
      break;
  }

  g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
              "%s", _("agent action descriptor is incomplete"));
  return FALSE;
}

gboolean dt_agent_catalog_read_current_choice(const dt_agent_action_descriptor_t *descriptor,
                                              gint *out_choice_value,
                                              gchar **out_choice_id,
                                              GError **error)
{
  if(!descriptor || !descriptor->widget || descriptor->operation_kind != DT_AGENT_OPERATION_SET_CHOICE
     || !out_choice_value)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent choice descriptor is incomplete"));
    return FALSE;
  }

  *out_choice_value = GPOINTER_TO_INT(dt_bauhaus_combobox_get_data(descriptor->widget));
  if(out_choice_id)
  {
    *out_choice_id = NULL;
    if(descriptor->choices)
      for(guint i = 0; i < descriptor->choices->len; i++)
      {
        const dt_agent_choice_option_t *option = g_ptr_array_index(descriptor->choices, i);
        if(option->choice_value == *out_choice_value)
        {
          *out_choice_id = g_strdup(option->choice_id);
          break;
        }
      }
  }
  return TRUE;
}

gboolean dt_agent_catalog_read_current_bool(const dt_agent_action_descriptor_t *descriptor,
                                            gboolean *out_bool_value,
                                            GError **error)
{
  if(!descriptor || !descriptor->widget || descriptor->operation_kind != DT_AGENT_OPERATION_SET_BOOL
     || !out_bool_value)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent bool descriptor is incomplete"));
    return FALSE;
  }

  if(GTK_IS_TOGGLE_BUTTON(descriptor->widget))
    *out_bool_value = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(descriptor->widget));
  else
    *out_bool_value = GPOINTER_TO_INT(dt_bauhaus_combobox_get_data(descriptor->widget)) != 0;

  return TRUE;
}

gboolean dt_agent_catalog_write_number(const dt_agent_action_descriptor_t *descriptor,
                                       double requested_number,
                                       double *out_applied_number,
                                       GError **error)
{
  if(!descriptor || descriptor->operation_kind != DT_AGENT_OPERATION_SET_FLOAT)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent action descriptor is incomplete"));
    return FALSE;
  }

  const double clamped_number = dt_agent_catalog_clamp_number(descriptor, requested_number);
  switch(descriptor->binding)
  {
    case DT_AGENT_DESCRIPTOR_BINDING_WIDGET:
      if(!descriptor->widget)
        break;
      dt_bauhaus_slider_set(descriptor->widget, clamped_number);
      if(out_applied_number)
        *out_applied_number = dt_bauhaus_slider_get(descriptor->widget);
      return TRUE;
    case DT_AGENT_DESCRIPTOR_BINDING_RGBLEVELS_HANDLE:
      return _write_rgblevels_number(descriptor, clamped_number, out_applied_number);
    case DT_AGENT_DESCRIPTOR_BINDING_COLORZONES_BAND:
      return _write_colorzones_number(descriptor, clamped_number, out_applied_number);
    default:
      break;
  }

  g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
              "%s", _("agent action descriptor is incomplete"));
  return FALSE;
}

gboolean dt_agent_catalog_write_choice(const dt_agent_action_descriptor_t *descriptor,
                                       gint requested_choice_value,
                                       gint *out_applied_choice_value,
                                       GError **error)
{
  if(!descriptor || !descriptor->widget || descriptor->operation_kind != DT_AGENT_OPERATION_SET_CHOICE)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent choice descriptor is incomplete"));
    return FALSE;
  }

  if(!dt_bauhaus_combobox_set_from_value(descriptor->widget, requested_choice_value))
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                _("unsupported choice value for action path: %s"),
                descriptor->action_path ? descriptor->action_path : _("unknown"));
    return FALSE;
  }

  if(out_applied_choice_value)
    *out_applied_choice_value = GPOINTER_TO_INT(dt_bauhaus_combobox_get_data(descriptor->widget));

  return TRUE;
}

gboolean dt_agent_catalog_write_bool(const dt_agent_action_descriptor_t *descriptor,
                                     gboolean requested_bool_value,
                                     gboolean *out_applied_bool_value,
                                     GError **error)
{
  if(!descriptor || !descriptor->widget || descriptor->operation_kind != DT_AGENT_OPERATION_SET_BOOL)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent bool descriptor is incomplete"));
    return FALSE;
  }

  if(GTK_IS_TOGGLE_BUTTON(descriptor->widget))
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(descriptor->widget), requested_bool_value);
  else if(!dt_bauhaus_combobox_set_from_value(descriptor->widget, requested_bool_value ? 1 : 0))
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                _("failed to apply bool action path: %s"),
                descriptor->action_path ? descriptor->action_path : _("unknown"));
    return FALSE;
  }

  if(out_applied_bool_value)
    dt_agent_catalog_read_current_bool(descriptor, out_applied_bool_value, NULL);

  return TRUE;
}
