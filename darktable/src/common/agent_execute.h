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

#pragma once

#include "common/agent_protocol.h"

G_BEGIN_DECLS

typedef enum dt_agent_execution_status_t
{
  DT_AGENT_EXECUTION_STATUS_UNKNOWN = 0,
  DT_AGENT_EXECUTION_STATUS_APPLIED,
  DT_AGENT_EXECUTION_STATUS_BLOCKED,
  DT_AGENT_EXECUTION_STATUS_FAILED,
} dt_agent_execution_status_t;

typedef struct dt_agent_execution_result_t
{
  gchar *operation_id;
  gchar *action_path;
  dt_agent_execution_status_t status;
  gchar *message;
  gboolean has_value_before;
  double value_before;
  gboolean has_value_after;
  double value_after;
} dt_agent_execution_result_t;

typedef struct dt_agent_execution_report_t
{
  GPtrArray *results;
  guint applied_count;
  guint blocked_count;
  guint failed_count;
} dt_agent_execution_report_t;

void dt_agent_execution_report_init(dt_agent_execution_report_t *report);
void dt_agent_execution_report_clear(dt_agent_execution_report_t *report);

const char *dt_agent_execution_status_to_string(dt_agent_execution_status_t status);

gboolean dt_agent_execute_response(const dt_agent_chat_response_t *response,
                                   dt_agent_execution_report_t *report,
                                   GError **error);

G_END_DECLS
