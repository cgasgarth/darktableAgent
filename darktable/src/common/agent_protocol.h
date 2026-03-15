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

#include "common/agent_capabilities.h"
#include "common/agent_state.h"

#include <glib.h>

G_BEGIN_DECLS

#define DT_AGENT_CHAT_SCHEMA_VERSION "3.0"
#define DT_AGENT_CHAT_SERVER_URL_CONF "plugins/ai/agent/server_url"
#define DT_AGENT_CHAT_TIMEOUT_SECONDS_CONF "plugins/ai/agent/timeout_seconds"
#define DT_AGENT_CHAT_DEFAULT_ENDPOINT "http://127.0.0.1:8001/v1/chat"
#define DT_AGENT_CHAT_DEFAULT_MAX_REFINEMENT_TURNS 10

typedef enum dt_agent_operation_kind_t
{
  DT_AGENT_OPERATION_UNKNOWN = 0,
  DT_AGENT_OPERATION_SET_FLOAT,
  DT_AGENT_OPERATION_SET_CHOICE,
  DT_AGENT_OPERATION_SET_BOOL,
} dt_agent_operation_kind_t;

typedef enum dt_agent_value_mode_t
{
  DT_AGENT_VALUE_MODE_UNKNOWN = 0,
  DT_AGENT_VALUE_MODE_SET,
  DT_AGENT_VALUE_MODE_DELTA,
} dt_agent_value_mode_t;

typedef enum dt_agent_refinement_mode_t
{
  DT_AGENT_REFINEMENT_MODE_UNKNOWN = 0,
  DT_AGENT_REFINEMENT_MODE_SINGLE,
  DT_AGENT_REFINEMENT_MODE_MULTI,
} dt_agent_refinement_mode_t;

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
  gchar *app_session_id;
  gchar *image_session_id;
  gchar *conversation_id;
  gchar *turn_id;
  gchar *image_revision_id;
  gchar *message_text;
  dt_agent_refinement_mode_t refinement_mode;
  gboolean refinement_enabled;
  guint refinement_pass_index;
  guint refinement_max_passes;
  gboolean refinement_automatic_continuation;
  gchar *refinement_goal_text;
  dt_agent_ui_context_t ui_context;
  GPtrArray *capabilities;
  dt_agent_image_state_t image_state;
} dt_agent_chat_request_t;

typedef struct dt_agent_chat_operation_t
{
  gchar *operation_id;
  gint sequence;
  dt_agent_operation_kind_t kind;
  gchar *kind_name;
  gchar *status;
  gchar *target_type;
  gchar *action_path;
  gchar *setting_id;
  dt_agent_value_mode_t value_mode;
  double number;
  gboolean has_choice_value;
  gint choice_value;
  gchar *choice_id;
  gboolean has_bool_value;
  gboolean bool_value;
} dt_agent_chat_operation_t;

typedef struct dt_agent_chat_response_t
{
  gchar *schema_version;
  gchar *request_id;
  gchar *app_session_id;
  gchar *image_session_id;
  gchar *conversation_id;
  gchar *turn_id;
  gchar *plan_id;
  gchar *base_image_revision_id;
  gchar *status;
  gchar *message_role;
  gchar *message_text;
  GPtrArray *operations;
  dt_agent_refinement_mode_t refinement_mode;
  gboolean refinement_enabled;
  guint refinement_pass_index;
  guint refinement_max_passes;
  gboolean refinement_continue;
  gchar *refinement_stop_reason;
  gchar *error_code;
  gchar *error_message;
} dt_agent_chat_response_t;

void dt_agent_ui_context_clear(dt_agent_ui_context_t *ui_context);

void dt_agent_chat_request_init(dt_agent_chat_request_t *request);
void dt_agent_chat_request_clear(dt_agent_chat_request_t *request);
void dt_agent_chat_request_copy(dt_agent_chat_request_t *dest,
                                const dt_agent_chat_request_t *src);

void dt_agent_chat_operation_free(gpointer operation);

void dt_agent_chat_response_init(dt_agent_chat_response_t *response);
void dt_agent_chat_response_clear(dt_agent_chat_response_t *response);

const char *dt_agent_operation_kind_to_string(dt_agent_operation_kind_t kind);
dt_agent_operation_kind_t dt_agent_operation_kind_from_string(const char *kind_name);

const char *dt_agent_value_mode_to_string(dt_agent_value_mode_t mode);
dt_agent_value_mode_t dt_agent_value_mode_from_string(const char *mode_name);

const char *dt_agent_refinement_mode_to_string(dt_agent_refinement_mode_t mode);
dt_agent_refinement_mode_t dt_agent_refinement_mode_from_string(const char *mode_name);

gchar *dt_agent_chat_request_serialize(const dt_agent_chat_request_t *request,
                                       GError **error);
gboolean dt_agent_chat_response_parse_data(const gchar *data,
                                           gssize length,
                                           dt_agent_chat_response_t *response,
                                           GError **error);

G_END_DECLS
