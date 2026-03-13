/*
    Minimal stubs for agent common unit tests.
*/

#include <glib.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/action.h"
#include "common/agent_protocol.h"
#include "common/curl_tools.h"
#include "common/darktable.h"
#include "control/conf.h"
#include "control/jobs.h"
#include "views/view.h"

darktable_t darktable;
static float _stub_exposure_value = 0.0f;

struct _dt_job_t
{
  dt_job_execute_callback execute;
  void *params;
  dt_job_destroy_callback destroy;
};

__attribute__((constructor))
static void _init_darktable_stub(void)
{
  darktable.unmuted = 0x7FFFFFFF;
}

void dt_print_ext(const char *msg, ...)
{
  va_list ap;
  va_start(ap, msg);
  vfprintf(stderr, msg, ap);
  va_end(ap);
  fputc('\n', stderr);
}

void dt_control_log(const char *msg, ...)
{
  va_list ap;
  va_start(ap, msg);
  vfprintf(stderr, msg, ap);
  va_end(ap);
  fputc('\n', stderr);
}

const char *dt_conf_get_string_const(const char *name)
{
  (void)name;
  const char *endpoint = getenv("DT_AGENT_TEST_ENDPOINT");
  return endpoint && endpoint[0] ? endpoint : DT_AGENT_CHAT_DEFAULT_ENDPOINT;
}

int dt_conf_get_int(const char *name)
{
  (void)name;
  return 5;
}

void dt_curl_init(CURL *curl, gboolean verbose)
{
  (void)curl;
  (void)verbose;
}

dt_job_t *dt_control_job_create(dt_job_execute_callback execute, const char *msg, ...)
{
  (void)msg;
  dt_job_t *job = g_malloc0(sizeof(*job));
  job->execute = execute;
  return job;
}

void dt_control_job_dispose(dt_job_t *job)
{
  if(!job) return;
  if(job->destroy)
    job->destroy(job->params);
  g_free(job);
}

void dt_control_job_set_params(dt_job_t *job, void *params, dt_job_destroy_callback callback)
{
  job->params = params;
  job->destroy = callback;
}

void *dt_control_job_get_params(const dt_job_t *job)
{
  return job ? job->params : NULL;
}

gboolean dt_control_add_job(dt_job_queue_t queue_id, dt_job_t *job)
{
  (void)queue_id;
  if(!job || !job->execute)
    return FALSE;
  job->execute(job);
  return TRUE;
}

dt_view_type_flags_t dt_view_get_current(void)
{
  return DT_VIEW_DARKROOM;
}

void dt_agent_test_set_exposure_value(const float value)
{
  _stub_exposure_value = value;
}

float dt_agent_test_get_exposure_value(void)
{
  return _stub_exposure_value;
}

float dt_action_process(const gchar *action,
                         int instance,
                         const gchar *element,
                         const gchar *effect,
                         float move_size)
{
  (void)action;
  (void)instance;
  (void)element;

  if(move_size == DT_READ_ACTION_ONLY)
    return _stub_exposure_value;

  if(effect && g_strcmp0(effect, "set") == 0)
  {
    _stub_exposure_value = move_size;
    return _stub_exposure_value;
  }

  return DT_ACTION_NOT_VALID;
}
