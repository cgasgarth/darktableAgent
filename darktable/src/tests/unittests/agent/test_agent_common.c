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

#include <setjmp.h>
#include <stdarg.h>
#include <stddef.h>
#include <string.h>

#include <cmocka.h>

#include "common/agent_actions.h"
#include "common/agent_protocol.h"

void dt_agent_test_set_exposure_value(float value);
float dt_agent_test_get_exposure_value(void);

static void test_request_serialization(void **state)
{
  (void)state;

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

  assert_non_null(json);
  assert_non_null(strstr(json, "\"schemaVersion\":\"1.0\""));
  assert_non_null(strstr(json, "\"requestId\":\"req-1\""));
  assert_non_null(strstr(json, "\"conversationId\":\"conv-1\""));
  assert_non_null(strstr(json, "\"imageId\":42"));
  assert_non_null(strstr(json, "\"mockActionId\":\"brighten-exposure\""));

  g_free(json);
  dt_agent_chat_request_clear(&request);
}

static void test_response_parsing_adjust_exposure(void **state)
{
  (void)state;

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
  assert_true(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
  assert_string_equal(response.status, "ok");
  assert_int_equal(response.actions->len, 1);

  const dt_agent_chat_action_t *action = g_ptr_array_index(response.actions, 0);
  assert_string_equal(action->action_id, "adjust-exposure-brighten");
  assert_int_equal(action->type, DT_AGENT_ACTION_ADJUST_EXPOSURE);
  assert_float_equal(action->delta_ev, 0.7, 1e-6);

  dt_agent_chat_response_clear(&response);
}

static void test_response_parsing_error_envelope(void **state)
{
  (void)state;

  const char *json =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"\","
    "\"conversationId\":\"\","
    "\"status\":\"error\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"bad request\"},"
    "\"actions\":[],"
    "\"error\":{\"code\":\"invalid_request\",\"message\":\"bad request\"}"
    "}";

  dt_agent_chat_response_t response;
  assert_true(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
  assert_string_equal(response.status, "error");
  assert_string_equal(response.error_code, "invalid_request");
  assert_string_equal(response.error_message, "bad request");

  dt_agent_chat_response_clear(&response);
}

static void test_response_rejects_invalid_schema_version(void **state)
{
  (void)state;

  const char *json =
    "{"
    "\"schemaVersion\":\"9.9\","
    "\"requestId\":\"req-bad-schema\","
    "\"conversationId\":\"conv-bad-schema\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"assistant\",\"text\":\"nope\"},"
    "\"actions\":[],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert_false(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
}

static void test_response_rejects_invalid_message_role(void **state)
{
  (void)state;

  const char *json =
    "{"
    "\"schemaVersion\":\"1.0\","
    "\"requestId\":\"req-bad-role\","
    "\"conversationId\":\"conv-bad-role\","
    "\"status\":\"ok\","
    "\"message\":{\"role\":\"user\",\"text\":\"nope\"},"
    "\"actions\":[],"
    "\"error\":null"
    "}";

  dt_agent_chat_response_t response;
  assert_false(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
}

static void test_response_rejects_invalid_action_status(void **state)
{
  (void)state;

  const char *json =
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
  assert_false(dt_agent_chat_response_parse_data(json, -1, &response, NULL));
}

static void test_adjust_exposure_target_clamps(void **state)
{
  (void)state;

  double target = 0.0;
  assert_true(dt_agent_actions_compute_adjust_exposure_target(17.8, 1.0, &target, NULL));
  assert_float_equal(target, 18.0, 1e-9);

  assert_true(dt_agent_actions_compute_adjust_exposure_target(-17.8, -1.0, &target, NULL));
  assert_float_equal(target, -18.0, 1e-9);
}

static void test_apply_response_adjust_exposure(void **state)
{
  (void)state;

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
  assert_true(dt_agent_chat_response_parse_data(json, -1, &response, NULL));

  dt_agent_test_set_exposure_value(0.3f);
  assert_true(dt_agent_actions_apply_response(&response, NULL));
  assert_float_equal(dt_agent_test_get_exposure_value(), 1.0f, 1e-6);

  dt_agent_chat_response_clear(&response);
}

static void test_apply_response_rejects_non_planned_action(void **state)
{
  (void)state;

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
  assert_true(dt_agent_chat_response_parse_data(json, -1, &response, NULL));

  dt_agent_test_set_exposure_value(0.3f);
  assert_false(dt_agent_actions_apply_response(&response, NULL));
  assert_float_equal(dt_agent_test_get_exposure_value(), 0.3f, 1e-6);

  dt_agent_chat_response_clear(&response);
}

int main(void)
{
  const struct CMUnitTest tests[] = {
    cmocka_unit_test(test_request_serialization),
    cmocka_unit_test(test_response_parsing_adjust_exposure),
    cmocka_unit_test(test_response_parsing_error_envelope),
    cmocka_unit_test(test_response_rejects_invalid_schema_version),
    cmocka_unit_test(test_response_rejects_invalid_message_role),
    cmocka_unit_test(test_response_rejects_invalid_action_status),
    cmocka_unit_test(test_adjust_exposure_target_clamps),
    cmocka_unit_test(test_apply_response_adjust_exposure),
    cmocka_unit_test(test_apply_response_rejects_non_planned_action),
  };

  return cmocka_run_group_tests(tests, NULL, NULL);
}
