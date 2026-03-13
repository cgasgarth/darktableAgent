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

typedef struct dt_agent_client_result_t
{
  gint http_status;
  gchar *endpoint;
  gchar *transport_error;
  gboolean has_response;
  dt_agent_chat_response_t response;
} dt_agent_client_result_t;

typedef void (*dt_agent_client_callback_t)(const dt_agent_client_result_t *result,
                                           gpointer user_data);

void dt_agent_client_result_clear(dt_agent_client_result_t *result);
char *dt_agent_client_dup_endpoint(void);

dt_job_t *dt_agent_client_chat_async(const dt_agent_chat_request_t *request,
                                     dt_agent_client_callback_t callback,
                                     gpointer user_data,
                                     GDestroyNotify destroy);

G_END_DECLS
