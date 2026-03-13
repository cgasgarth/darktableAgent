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

#include <glib.h>

G_BEGIN_DECLS

#define DT_AGENT_CHAT_SCHEMA_VERSION "1.0"
#define DT_AGENT_CHAT_SERVER_URL_CONF "plugins/ai/agent/server_url"
#define DT_AGENT_CHAT_TIMEOUT_SECONDS_CONF "plugins/ai/agent/timeout_seconds"
#define DT_AGENT_CHAT_DEFAULT_ENDPOINT "http://127.0.0.1:8001/v1/chat"

typedef enum dt_agent_action_type_t
{
  DT_AGENT_ACTION_UNKNOWN = 0,
  DT_AGENT_ACTION_ADJUST_EXPOSURE,
} dt_agent_action_type_t;

typedef struct dt_agent_ui_context_t
{
  gchar *view;
  gboolean has_image_id;
  gint64 image_id;
  gchar *image_name;
} dt_agent_ui_context_t;

typedef struct dt_agent_chat_request_t
{
  gchar *schema_version;
  gchar *request_id;
  gchar *conversation_id;
  gchar *message_text;
  dt_agent_ui_context_t ui_context;
  gchar *mock_action_id;
} dt_agent_chat_request_t;

typedef struct dt_agent_chat_action_t
{
  gchar *action_id;
  dt_agent_action_type_t type;
  gchar *type_name;
  gchar *status;
  double delta_ev;
} dt_agent_chat_action_t;

typedef struct dt_agent_chat_response_t
{
  gchar *schema_version;
  gchar *request_id;
  gchar *conversation_id;
  gchar *status;
  gchar *message_role;
  gchar *message_text;
  GPtrArray *actions;
  gchar *error_code;
  gchar *error_message;
} dt_agent_chat_response_t;

void dt_agent_ui_context_clear(dt_agent_ui_context_t *ui_context);

void dt_agent_chat_request_init(dt_agent_chat_request_t *request);
void dt_agent_chat_request_clear(dt_agent_chat_request_t *request);
void dt_agent_chat_request_copy(dt_agent_chat_request_t *dest,
                                const dt_agent_chat_request_t *src);

void dt_agent_chat_action_free(gpointer action);

void dt_agent_chat_response_init(dt_agent_chat_response_t *response);
void dt_agent_chat_response_clear(dt_agent_chat_response_t *response);

const char *dt_agent_action_type_to_string(dt_agent_action_type_t type);
dt_agent_action_type_t dt_agent_action_type_from_string(const char *type_name);

gchar *dt_agent_chat_request_serialize(const dt_agent_chat_request_t *request,
                                       GError **error);
gboolean dt_agent_chat_response_parse_data(const gchar *data,
                                           gssize length,
                                           dt_agent_chat_response_t *response,
                                           GError **error);

G_END_DECLS
