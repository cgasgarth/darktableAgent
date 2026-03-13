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

gboolean dt_agent_actions_apply_response(const dt_agent_chat_response_t *response,
                                         GError **error)
{
  dt_agent_execution_report_t report;
  dt_agent_execution_report_init(&report);
  const gboolean ok = dt_agent_execute_response(response, &report, error);
  dt_agent_execution_report_clear(&report);
  return ok;
}
