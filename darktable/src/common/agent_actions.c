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

#include "common/agent_actions.h"

#include "common/action.h"
#include "control/control.h"
#include "gui/accelerators.h"
#include "views/view.h"

#include <glib/gi18n.h>

typedef enum dt_agent_actions_error_t
{
  DT_AGENT_ACTIONS_ERROR_INVALID = 1,
} dt_agent_actions_error_t;

static GQuark _agent_actions_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-actions-error");
}

static gboolean _apply_set_float_operation(const dt_agent_chat_operation_t *operation,
                                           GError **error)
{
  float target = (float)operation->number;

  if(operation->value_mode == DT_AGENT_VALUE_MODE_DELTA)
  {
    // Slider actions expose actual values only when read through the "set" effect.
    const float current
      = dt_action_process(operation->action_path, 0, NULL, "set", DT_READ_ACTION_ONLY);
    if(DT_ACTION_IS_INVALID(current))
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  _("failed to read action path: %s"),
                  operation->action_path ? operation->action_path : _("unknown"));
      return FALSE;
    }

    target = current + (float)operation->number;
  }
  else if(operation->value_mode != DT_AGENT_VALUE_MODE_SET)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("unsupported numeric value mode"));
    return FALSE;
  }

  const float applied
    = dt_action_process(operation->action_path, 0, NULL, "set", target);
  if(DT_ACTION_IS_INVALID(applied))
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                _("failed to apply action path: %s"),
                operation->action_path ? operation->action_path : _("unknown"));
    return FALSE;
  }

  dt_print(DT_DEBUG_CONTROL,
           "[agent_actions] applied operation id=%s path=%s mode=%s value=%.3f",
           operation->operation_id ? operation->operation_id : "",
           operation->action_path ? operation->action_path : "",
           dt_agent_value_mode_to_string(operation->value_mode),
           operation->number);

  return TRUE;
}

gboolean dt_agent_actions_apply_response(const dt_agent_chat_response_t *response,
                                         GError **error)
{
  if(!response)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("missing chat response"));
    return FALSE;
  }

  if(!response->operations)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("chat response is missing operations"));
    return FALSE;
  }

  if(dt_view_get_current() != DT_VIEW_DARKROOM)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("agent edits require darkroom view"));
    return FALSE;
  }

  for(guint i = 0; i < response->operations->len; i++)
  {
    const dt_agent_chat_operation_t *operation = g_ptr_array_index(response->operations, i);

    if(g_strcmp0(operation->status, "planned") != 0)
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  _("unsupported operation status: %s"),
                  operation->status ? operation->status : _("unknown"));
      return FALSE;
    }

    switch(operation->kind)
    {
      case DT_AGENT_OPERATION_SET_FLOAT:
        if(!_apply_set_float_operation(operation, error))
          return FALSE;
        break;
      case DT_AGENT_OPERATION_UNKNOWN:
      default:
        g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                    _("unsupported operation kind: %s"),
                    operation->kind_name ? operation->kind_name : _("unknown"));
        return FALSE;
    }
  }

  return TRUE;
}
