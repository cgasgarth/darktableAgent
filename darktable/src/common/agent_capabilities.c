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
  return dest;
}

gboolean dt_agent_capabilities_collect(GPtrArray *capabilities, GError **error)
{
  if(!capabilities)
  {
    g_set_error(error, _agent_capabilities_error_quark(),
                DT_AGENT_CAPABILITIES_ERROR_INVALID,
                "%s", _("missing agent capability manifest"));
    return FALSE;
  }

  g_ptr_array_set_size(capabilities, 0);

  guint descriptor_count = 0;
  const dt_agent_action_descriptor_t *descriptors
    = dt_agent_catalog_descriptors(&descriptor_count);

  for(guint i = 0; i < descriptor_count; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = &descriptors[i];
    dt_agent_capability_t *capability = g_new0(dt_agent_capability_t, 1);
    capability->capability_id = g_strdup(descriptor->capability_id);
    capability->label = g_strdup(descriptor->label);
    capability->kind = g_strdup(dt_agent_operation_kind_to_string(descriptor->operation_kind));
    capability->target_type = g_strdup("darktable-action");
    capability->action_path = g_strdup(descriptor->action_path);
    capability->supported_modes = descriptor->supported_modes;
    capability->min_number = descriptor->min_number;
    capability->max_number = descriptor->max_number;
    capability->default_number = descriptor->default_number;
    capability->step_number = descriptor->step_number;
    g_ptr_array_add(capabilities, capability);
  }

  return TRUE;
}
