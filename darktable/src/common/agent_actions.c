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
#include "common/darktable.h"
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

gboolean dt_agent_actions_compute_adjust_exposure_target(double current_ev,
                                                         double delta_ev,
                                                         double *target_ev,
                                                         GError **error)
{
  if(!target_ev)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "target exposure pointer is NULL");
    return FALSE;
  }

  *target_ev = CLAMP(current_ev + delta_ev, -18.0, 18.0);
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

  if(!response->actions)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("chat response is missing actions"));
    return FALSE;
  }

  if(dt_view_get_current() != DT_VIEW_DARKROOM)
  {
    g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                "%s", _("AI exposure actions require darkroom view"));
    return FALSE;
  }

  for(guint i = 0; i < response->actions->len; i++)
  {
    const dt_agent_chat_action_t *action = g_ptr_array_index(response->actions, i);
    if(g_strcmp0(action->status, "planned") != 0)
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  _("unsupported AI action status: %s"),
                  action->status ? action->status : _("unknown"));
      return FALSE;
    }

    if(action->type != DT_AGENT_ACTION_ADJUST_EXPOSURE)
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  _("unsupported AI action type: %s"),
                  action->type_name ? action->type_name : dt_agent_action_type_to_string(action->type));
      return FALSE;
    }

    const float current_ev
      = dt_action_process("iop/exposure/exposure", 0, NULL, NULL, DT_READ_ACTION_ONLY);
    if(DT_ACTION_IS_INVALID(current_ev))
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  "%s", _("failed to read the current exposure control"));
      return FALSE;
    }

    double target_ev = 0.0;
    if(!dt_agent_actions_compute_adjust_exposure_target(current_ev, action->delta_ev,
                                                        &target_ev, error))
      return FALSE;

    const float applied
      = dt_action_process("iop/exposure/exposure", 0, NULL, "set", target_ev);
    if(DT_ACTION_IS_INVALID(applied))
    {
      g_set_error(error, _agent_actions_error_quark(), DT_AGENT_ACTIONS_ERROR_INVALID,
                  "%s", _("failed to apply the exposure control"));
      return FALSE;
    }

    dt_print(DT_DEBUG_AI,
             "[agent_actions] applied exposure action id=%s delta=%.3f current=%.3f target=%.3f",
             action->action_id ? action->action_id : "",
             action->delta_ev,
             current_ev,
             target_ev);
    dt_control_log(_("applied AI exposure adjustment %.2f EV"), action->delta_ev);
  }

  return TRUE;
}
