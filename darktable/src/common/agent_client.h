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

typedef struct _dt_job_t dt_job_t;
typedef struct dt_agent_client_request_t dt_agent_client_request_t;

typedef struct dt_agent_client_result_t
{
  gint http_status;
  gchar *endpoint;
  gchar *transport_error;
  gboolean cancelled;
  gboolean has_response;
  dt_agent_chat_response_t response;
} dt_agent_client_result_t;

typedef struct dt_agent_client_progress_t
{
  gint http_status;
  gchar *endpoint;
  gchar *transport_error;
  gboolean cancelled;
  gboolean found;
  gboolean has_response;
  gchar *status;
  gchar *message;
  gchar *last_tool_name;
  guint tool_calls_used;
  guint tool_calls_max;
  guint applied_operation_count;
  dt_agent_chat_response_t response;
} dt_agent_client_progress_t;

typedef void (*dt_agent_client_callback_t)(const dt_agent_client_result_t *result,
                                           gpointer user_data);
typedef void (*dt_agent_client_progress_callback_t)(const dt_agent_client_progress_t *progress,
                                                    gpointer user_data);

void dt_agent_client_result_clear(dt_agent_client_result_t *result);
void dt_agent_client_progress_clear(dt_agent_client_progress_t *progress);
char *dt_agent_client_dup_endpoint(void);
void dt_agent_client_request_cancel(dt_agent_client_request_t *request, const char *reason);
void dt_agent_client_request_unref(dt_agent_client_request_t *request);

dt_agent_client_request_t *dt_agent_client_chat_async(const dt_agent_chat_request_t *request,
                                                      dt_agent_client_callback_t callback,
                                                      dt_agent_client_progress_callback_t progress_callback,
                                                      gpointer user_data,
                                                      GDestroyNotify destroy,
                                                      GError **error);

G_END_DECLS
