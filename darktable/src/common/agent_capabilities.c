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

#include "common/agent_capabilities.h"

#include "common/agent_catalog.h"

#include <glib/gi18n.h>

typedef enum dt_agent_capabilities_error_t
{
  DT_AGENT_CAPABILITIES_ERROR_INVALID = 1,
} dt_agent_capabilities_error_t;

static GQuark _agent_capabilities_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-capabilities-error");
}

void dt_agent_choice_option_free(gpointer data)
{
  dt_agent_choice_option_t *option = data;
  if(!option)
    return;

  g_free(option->choice_id);
  g_free(option->label);
  g_free(option);
}

dt_agent_choice_option_t *dt_agent_choice_option_copy(const dt_agent_choice_option_t *src)
{
  if(!src)
    return NULL;

  dt_agent_choice_option_t *dest = g_new0(dt_agent_choice_option_t, 1);
  dest->choice_value = src->choice_value;
  dest->choice_id = g_strdup(src->choice_id);
  dest->label = g_strdup(src->label);
  return dest;
}

void dt_agent_capability_free(gpointer data)
{
  dt_agent_capability_t *capability = data;
  if(!capability)
    return;

  g_free(capability->capability_id);
  g_free(capability->label);
  g_free(capability->kind);
  g_free(capability->target_type);
  g_free(capability->action_path);
  if(capability->choices)
    g_ptr_array_unref(capability->choices);
  g_free(capability);
}

dt_agent_capability_t *dt_agent_capability_copy(const dt_agent_capability_t *src)
{
  if(!src)
    return NULL;

  dt_agent_capability_t *dest = g_new0(dt_agent_capability_t, 1);
  dest->capability_id = g_strdup(src->capability_id);
  dest->label = g_strdup(src->label);
  dest->kind = g_strdup(src->kind);
  dest->target_type = g_strdup(src->target_type);
  dest->action_path = g_strdup(src->action_path);
  dest->supported_modes = src->supported_modes;
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

gboolean dt_agent_capabilities_collect(const struct dt_develop_t *dev,
                                       GPtrArray *capabilities,
                                       GError **error)
{
  if(!dev || !capabilities)
  {
    g_set_error(error, _agent_capabilities_error_quark(),
                DT_AGENT_CAPABILITIES_ERROR_INVALID,
                "%s", _("missing agent capability manifest"));
    return FALSE;
  }

  g_ptr_array_set_size(capabilities, 0);

  g_autoptr(GPtrArray) descriptors = g_ptr_array_new_with_free_func(dt_agent_action_descriptor_free);
  if(!dt_agent_catalog_collect_descriptors(dev, descriptors, error))
    return FALSE;

  for(guint i = 0; i < descriptors->len; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = g_ptr_array_index(descriptors, i);
    dt_agent_capability_t *capability = g_new0(dt_agent_capability_t, 1);
    capability->capability_id = g_strdup(descriptor->capability_id);
    capability->label = g_strdup(descriptor->label);
    capability->kind = g_strdup(descriptor->kind_name);
    capability->target_type = g_strdup(descriptor->target_type);
    capability->action_path = g_strdup(descriptor->action_path);
    capability->supported_modes = descriptor->supported_modes;
    capability->min_number = descriptor->min_number;
    capability->max_number = descriptor->max_number;
    capability->default_number = descriptor->default_number;
    capability->step_number = descriptor->step_number;
    if(descriptor->choices)
    {
      capability->choices = g_ptr_array_new_with_free_func(dt_agent_choice_option_free);
      for(guint choice_index = 0; choice_index < descriptor->choices->len; choice_index++)
      {
        dt_agent_choice_option_t *option = g_ptr_array_index(descriptor->choices, choice_index);
        g_ptr_array_add(capability->choices, dt_agent_choice_option_copy(option));
      }
    }
    capability->has_default_choice_value = descriptor->has_default_choice_value;
    capability->default_choice_value = descriptor->default_choice_value;
    capability->has_default_bool = descriptor->has_default_bool;
    capability->default_bool = descriptor->default_bool;
    g_ptr_array_add(capabilities, capability);
  }

  return TRUE;
}
