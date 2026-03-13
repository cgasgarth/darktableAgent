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

#include "common/action.h"
#include "gui/accelerators.h"

#include <glib/gi18n.h>

typedef enum dt_agent_catalog_error_t
{
  DT_AGENT_CATALOG_ERROR_INVALID = 1,
} dt_agent_catalog_error_t;

static GQuark _agent_catalog_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-catalog-error");
}

static const dt_agent_action_descriptor_t _agent_catalog[] = {
  {
    .capability_id = "exposure.primary",
    .label = "Exposure",
    .action_path = "iop/exposure/exposure",
    .min_number = -18.0,
    .max_number = 18.0,
    .default_number = 0.0,
    .step_number = 0.01,
    .supported_modes = DT_AGENT_VALUE_MODE_FLAG_SET | DT_AGENT_VALUE_MODE_FLAG_DELTA,
  },
};

const dt_agent_action_descriptor_t *dt_agent_catalog_descriptors(guint *count)
{
  if(count)
    *count = G_N_ELEMENTS(_agent_catalog);

  return _agent_catalog;
}

const dt_agent_action_descriptor_t *dt_agent_catalog_get_descriptor(const char *action_path)
{
  if(!action_path)
    return NULL;

  for(guint i = 0; i < G_N_ELEMENTS(_agent_catalog); i++)
    if(g_strcmp0(_agent_catalog[i].action_path, action_path) == 0)
      return &_agent_catalog[i];

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

gboolean dt_agent_catalog_read_current_number(const dt_agent_action_descriptor_t *descriptor,
                                              double *out_number,
                                              GError **error)
{
  if(!descriptor || !descriptor->action_path || !out_number)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent action descriptor is incomplete"));
    return FALSE;
  }

  const float current
    = dt_action_process(descriptor->action_path, 0, NULL, "set", DT_READ_ACTION_ONLY);
  if(DT_ACTION_IS_INVALID(current))
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                _("failed to read action path: %s"), descriptor->action_path);
    return FALSE;
  }

  *out_number = current;
  return TRUE;
}

gboolean dt_agent_catalog_write_number(const dt_agent_action_descriptor_t *descriptor,
                                       double requested_number,
                                       double *out_applied_number,
                                       GError **error)
{
  if(!descriptor || !descriptor->action_path)
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                "%s", _("agent action descriptor is incomplete"));
    return FALSE;
  }

  const float applied
    = dt_action_process(descriptor->action_path, 0, NULL, "set", (float)requested_number);
  if(DT_ACTION_IS_INVALID(applied))
  {
    g_set_error(error, _agent_catalog_error_quark(), DT_AGENT_CATALOG_ERROR_INVALID,
                _("failed to apply action path: %s"), descriptor->action_path);
    return FALSE;
  }

  if(out_applied_number)
    *out_applied_number = applied;

  return TRUE;
}
