/*
    This file is part of darktable,
    Copyright (C) 2026 darktable developers.

    darktable is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
*/

#include <assert.h>
#include <math.h>
#include <string.h>

#include <glib.h>

#include "common/agent_actions.h"
#include "common/agent_protocol.h"

void dt_agent_test_set_exposure_value(float value);
float dt_agent_test_get_exposure_value(void);

static void test_request_serialization(void)
{
  dt_agent_chat_request_t request;
  dt_agent_chat_request_init(&request);
  request.request_id = g_strdup("req-1");
  request.conversation_id = g_strdup("conv-1");
  request.message_text = g_strdup("Please brighten this image");
  request.ui_context.view = g_strdup("darkroom");
  request.ui_context.has_image_id = TRUE;
  request.ui_context.image_id = 42;
  request.ui_context.image_name = g_strdup("IMG_0042.CR3");
  request.mock_action_id = g_strdup("brighten-exposure");

  gchar *json = dt_agent_chat_request_serialize(&request, NULL);
  assert(json != NULL);
  assert(strstr(json, "\"schemaVersion\":\"1.0\"") != NULL);
  assert(strstr(json, "\"requestId\":\"req-1\"") != NULL);
  assert(strstr(json, "\"conversationId\":\"conv-1\"") != NULL);
  assert(strstr(json, "\"imageId\":42") != NULL);
  assert(strstr(json, "\"mockActionId\":\"brighten-exposure\"") != NULL);

  g_free(json);
  dt_agent_chat_request_clear(&request);
}

static void test_response_parsing_adjust_exposure(void)
{
  const char *json =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-2\","
    "\"conversationId\":\"conv-2\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"Planned it.\"},"
    "\"actions\":[{"
      "\"actionId\":\"adjust-exposure-brighten\","
      "\"type\":\"adjust-exposure\","
      "\"status\":\"planned\","
      "\"parameters\":{\"deltaEv\":0.7}"
    "}],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
  assert(strcmp(response.status, "ok") == 0);
  assert(response.actions->len == 1);

  const dt_agent_chat_action_t *action = g_ptr_array_index(response.actions, 0);
  assert(strcmp(action->action_id, "adjust-exposure-brighten") == 0);
  assert(action->type == DT_AGENT_ACTION_ADJUST_EXPOSURE);
  assert(fabs(action->delta_ev - 0.7) < 1e-6);

  dt_agent_chat_response_clear(&response);
}

static void test_invalid_responses_are_rejected(void)
{
  const char *bad_schema =
    "{"
    "\"schemaVersion\":\"9.9\","
    "\"requestId\":\"req-bad-schema\","
    "\"conversationId\":\"conv-bad-schema\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"nope\"},"
    "\"actions\":[],"
    "\"error\":null"
    "}";
  const char *bad_role =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-bad-role\","
    "\"conversationId\":\"conv-bad-role\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"user\",\"text\":\"nope\"},"
    "\"actions\":[],"
    "\"error\":null"
    "}";
  const char *bad_action_status =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-bad-action-status\","
    "\"conversationId\":\"conv-bad-action-status\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"nope\"},"
    "\"actions\":[{"
      "\"actionId\":\"adjust-exposure-brighten\","
      "\"type\":\"adjust-exposure\","
      "\"status\":\"surprise\","
      "\"parameters\":{\"deltaEv\":0.7}"
    "}],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert(!dt_agent_chat_response_parse_data(bad_schema, -1, &response, NULL));
  assert(!dt_agent_chat_response_parse_data(bad_role, -1, &response, NULL));
  assert(!dt_agent_chat_response_parse_data(bad_action_status, -1, &response, NULL));
}

static void test_apply_response_adjust_exposure(void)
{
  const char *json =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-3\","
    "\"conversationId\":\"conv-3\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"Planned it.\"},"
    "\"actions\":[{"
      "\"actionId\":\"adjust-exposure-brighten\","
      "\"type\":\"adjust-exposure\","
      "\"status\":\"planned\","
      "\"parameters\":{\"deltaEv\":0.7}"
    "}],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert(dt_agent_chat_response_parse_data(json, -1, &response, NULL));

  dt_agent_test_set_exposure_value(0.3f);
  assert(dt_agent_actions_apply_response(&response, NULL));
  assert(fabs(dt_agent_test_get_exposure_value() - 1.0f) < 1e-6);

  dt_agent_chat_response_clear(&response);
}

static void test_apply_response_rejects_non_planned_action(void)
{
  const char *json =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-4\","
    "\"conversationId\":\"conv-4\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"Already done\"},"
    "\"actions\":[{"
      "\"actionId\":\"adjust-exposure-brighten\","
      "\"type\":\"adjust-exposure\","
      "\"status\":\"applied\","
      "\"parameters\":{\"deltaEv\":0.7}"
    "}],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert(dt_agent_chat_response_parse_data(json, -1, &response, NULL));

  dt_agent_test_set_exposure_value(0.3f);
  assert(!dt_agent_actions_apply_response(&response, NULL));
  assert(fabs(dt_agent_test_get_exposure_value() - 0.3f) < 1e-6);

  dt_agent_chat_response_clear(&response);
}

int main(void)
{
  test_request_serialization();
  test_response_parsing_adjust_exposure();
  test_invalid_responses_are_rejected();
  test_apply_response_adjust_exposure();
  test_apply_response_rejects_non_planned_action();
  return 0;
}
