/*
    This file is part of darktable,
    Copyright (C) 2026 darktable developers.
*/

#include <assert.h>
#include <math.h>

#include <glib.h>

#include "common/agent_actions.h"
#include "common/agent_client.h"

void dt_agent_test_set_exposure_value(float value);
float dt_agent_test_get_exposure_value(void);

typedef struct dt_agent_client_smoke_state_t
{
  GMainLoop *loop;
  gboolean callback_called;
} dt_agent_client_smoke_state_t;

static void on_result(const dt_agent_client_result_t *result, gpointer user_data)
{
  dt_agent_client_smoke_state_t *state = user_data;
  state->callback_called = TRUE;

  assert(result != NULL);
  assert(result->transport_error == NULL);
  assert(result->has_response);
  assert(result->http_status == 200);
  assert(g_strcmp0(result->response.request_id, "client-smoke-req") == 0);
  assert(g_strcmp0(result->response.conversation_id, "client-smoke-conv") == 0);
  assert(g_strcmp0(result->response.status, "ok") == 0);
  assert(result->response.actions != NULL);
  assert(result->response.actions->len == 1);

  dt_agent_test_set_exposure_value(0.3f);
  assert(dt_agent_actions_apply_response(&result->response, NULL));
  assert(fabs(dt_agent_test_get_exposure_value() - 1.0f) < 1e-6);

  g_main_loop_quit(state->loop);
}

int main(void)
{
  dt_agent_chat_request_t request;
  dt_agent_chat_request_init(&request);
  request.request_id = g_strdup("client-smoke-req");
  request.conversation_id = g_strdup("client-smoke-conv");
  request.message_text = g_strdup("Brighten this image");
  request.ui_context.view = g_strdup("darkroom");
  request.ui_context.has_image_id = TRUE;
  request.ui_context.image_id = 42;
  request.ui_context.image_name = g_strdup("IMG_0042.CR3");
  request.mock_action_id = g_strdup("brighten-exposure");

  dt_agent_client_smoke_state_t state = { 0 };
  state.loop = g_main_loop_new(NULL, FALSE);

  dt_job_t *job = dt_agent_client_chat_async(&request, on_result, &state, NULL);
  assert(job != NULL);

  while(!state.callback_called)
    g_main_context_iteration(NULL, TRUE);

  assert(state.callback_called);
  g_main_loop_unref(state.loop);
  dt_agent_chat_request_clear(&request);
  return 0;
}
