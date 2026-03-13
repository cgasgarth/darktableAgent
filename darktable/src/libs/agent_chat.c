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
#include "common/agent_client.h"
#include "common/agent_protocol.h"
#include "common/darktable.h"
#include "control/conf.h"
#include "gui/gtk.h"
#include "gui/gtkentry.h"
#include "libs/lib.h"
#include "libs/lib_api.h"

#include <glib/gi18n.h>

DT_MODULE(1)

#define DT_AGENT_CHAT_WINDOW_HEIGHT_CONF "plugins/darkroom/agent_chat/windowheight"

typedef struct dt_agent_chat_submission_t
{
  dt_lib_module_t *self;
  gchar *display_prompt;
  gchar *mock_action_id;
  gchar *request_id;
  gchar *conversation_id;
  gboolean has_image_id;
  gint64 image_id;
} dt_agent_chat_submission_t;

typedef struct dt_lib_agent_chat_t
{
  GtkWidget *conversation_view;
  GtkWidget *input_entry;
  GtkWidget *send_button;
  GtkWidget *brighten_button;
  GtkWidget *darken_button;
  GtkWidget *status_label;
  GtkWidget *error_label;
  GtkWidget *spinner;
  gchar *conversation_id;
  gboolean is_loading;
} dt_lib_agent_chat_t;

const char *name(dt_lib_module_t *self)
{
  return _("agent chat");
}

const char *description(dt_lib_module_t *self)
{
  return _("chat-based editing assistant for darkroom\n"
           "send prompts or use quick mock exposure actions");
}

dt_view_type_flags_t views(dt_lib_module_t *self)
{
  return DT_VIEW_DARKROOM;
}

uint32_t container(dt_lib_module_t *self)
{
  return DT_UI_CONTAINER_PANEL_LEFT_CENTER;
}

int position(const dt_lib_module_t *self)
{
  return 875;
}

static void _agent_chat_submission_free(gpointer data)
{
  dt_agent_chat_submission_t *submission = data;
  if(!submission) return;
  g_free(submission->display_prompt);
  g_free(submission->mock_action_id);
  g_free(submission->request_id);
  g_free(submission->conversation_id);
  g_free(submission);
}

static dt_agent_chat_submission_t *_agent_chat_submission_new(dt_lib_module_t *self,
                                                              const char *display_prompt,
                                                              const char *mock_action_id,
                                                              const dt_agent_chat_request_t *request)
{
  dt_agent_chat_submission_t *submission = g_malloc0(sizeof(*submission));
  submission->self = self;
  submission->display_prompt = g_strdup(display_prompt);
  submission->mock_action_id = g_strdup(mock_action_id);
  submission->request_id = g_strdup(request->request_id);
  submission->conversation_id = g_strdup(request->conversation_id);
  submission->has_image_id = request->ui_context.has_image_id;
  submission->image_id = request->ui_context.image_id;
  return submission;
}

static void _agent_chat_update_sensitivity(dt_lib_module_t *self)
{
  dt_lib_agent_chat_t *d = self->data;
  const gboolean sensitive = !d->is_loading;

  gtk_widget_set_sensitive(d->input_entry, sensitive);
  gtk_widget_set_sensitive(d->send_button, sensitive);
  gtk_widget_set_sensitive(d->brighten_button, sensitive);
  gtk_widget_set_sensitive(d->darken_button, sensitive);
}

static void _agent_chat_set_loading(dt_lib_module_t *self, const gboolean is_loading)
{
  dt_lib_agent_chat_t *d = self->data;
  d->is_loading = is_loading;

  gtk_widget_set_visible(d->spinner, is_loading);
  if(is_loading)
    gtk_spinner_start(GTK_SPINNER(d->spinner));
  else
    gtk_spinner_stop(GTK_SPINNER(d->spinner));

  _agent_chat_update_sensitivity(self);
}

static void _agent_chat_set_status(dt_lib_module_t *self, const char *status)
{
  dt_lib_agent_chat_t *d = self->data;
  gtk_label_set_text(GTK_LABEL(d->status_label), status ? status : "");
}

static void _agent_chat_set_error(dt_lib_module_t *self, const char *error)
{
  dt_lib_agent_chat_t *d = self->data;
  gtk_label_set_text(GTK_LABEL(d->error_label), error ? error : "");
  gtk_widget_set_visible(d->error_label, error && error[0] != '\0');
}

static void _agent_chat_scroll_to_end(dt_lib_agent_chat_t *d)
{
  GtkWidget *parent = gtk_widget_get_parent(d->conversation_view);
  if(!GTK_IS_SCROLLED_WINDOW(parent)) return;

  GtkAdjustment *adj = gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(parent));
  gtk_adjustment_set_value(adj, gtk_adjustment_get_upper(adj));
}

static void _agent_chat_append_message(dt_lib_module_t *self,
                                       const char *speaker,
                                       const char *message)
{
  dt_lib_agent_chat_t *d = self->data;
  GtkTextBuffer *buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(d->conversation_view));
  GtkTextIter end;
  gtk_text_buffer_get_end_iter(buffer, &end);

  if(gtk_text_buffer_get_char_count(buffer) > 0)
    gtk_text_buffer_insert(buffer, &end, "\n\n", -1);

  gchar *line = g_strdup_printf(_("%s: %s"), speaker, message ? message : "");
  gtk_text_buffer_insert(buffer, &end, line, -1);
  g_free(line);

  _agent_chat_scroll_to_end(d);
}

static void _agent_chat_append_apply_summary(dt_lib_module_t *self,
                                             const dt_agent_chat_response_t *response)
{
  if(!response || !response->actions || response->actions->len == 0)
    return;

  GString *summary = g_string_new(NULL);
  for(guint i = 0; i < response->actions->len; i++)
  {
    const dt_agent_chat_action_t *action = g_ptr_array_index(response->actions, i);
    if(i > 0) g_string_append(summary, "; ");

    if(action->type == DT_AGENT_ACTION_ADJUST_EXPOSURE)
      g_string_append_printf(summary, _("applied exposure %.2f EV"), action->delta_ev);
    else
      g_string_append_printf(summary, _("applied %s"),
                             action->type_name ? action->type_name : _("unknown action"));
  }

  _agent_chat_append_message(self, _("system"), summary->str);
  g_string_free(summary, TRUE);
}

static void _agent_chat_fill_ui_context(dt_agent_chat_request_t *request)
{
  request->ui_context.view = g_strdup("darkroom");

  if(darktable.develop && darktable.develop->image_storage.id > 0)
  {
    request->ui_context.has_image_id = TRUE;
    request->ui_context.image_id = darktable.develop->image_storage.id;
  }

  if(darktable.develop && darktable.develop->image_storage.filename[0] != '\0')
    request->ui_context.image_name = g_strdup(darktable.develop->image_storage.filename);
}

static gboolean _agent_chat_build_request(dt_lib_module_t *self,
                                          const char *message_text,
                                          const char *mock_action_id,
                                          dt_agent_chat_request_t *request,
                                          GError **error)
{
  dt_lib_agent_chat_t *d = self->data;
  dt_agent_chat_request_init(request);

  if(!d->conversation_id)
    d->conversation_id = g_uuid_string_random();

  request->request_id = g_uuid_string_random();
  request->conversation_id = g_strdup(d->conversation_id);
  request->message_text = g_strdup(message_text);
  request->mock_action_id = g_strdup(mock_action_id);
  _agent_chat_fill_ui_context(request);

  if(!request->request_id || !request->conversation_id || !request->message_text)
  {
    g_set_error(error, g_quark_from_static_string("dt-agent-chat-ui"), 1,
                "%s", _("failed to build an agent request"));
    dt_agent_chat_request_clear(request);
    return FALSE;
  }

  return TRUE;
}

static void _agent_chat_handle_transport_error(dt_lib_module_t *self,
                                               const char *error_message)
{
  _agent_chat_set_error(self, error_message ? error_message : _("agent request failed"));
  _agent_chat_set_status(self, _("Request failed"));
  _agent_chat_append_message(self, _("assistant"),
                             error_message ? error_message : _("failed to contact the agent server"));
}

static gboolean _agent_chat_active_image_matches(const dt_agent_chat_submission_t *submission)
{
  if(!submission->has_image_id)
    return TRUE;

  return darktable.develop && darktable.develop->image_storage.id == submission->image_id;
}

static gboolean _agent_chat_is_stale_response(dt_lib_module_t *self,
                                              const dt_agent_chat_submission_t *submission,
                                              const dt_agent_client_result_t *result)
{
  dt_lib_agent_chat_t *d = self->data;

  if(g_strcmp0(d->conversation_id, submission->conversation_id) != 0)
    return TRUE;

  if(!_agent_chat_active_image_matches(submission))
    return TRUE;

  if(result && result->has_response)
  {
    if(g_strcmp0(result->response.request_id, submission->request_id) != 0)
      return TRUE;
    if(g_strcmp0(result->response.conversation_id, submission->conversation_id) != 0)
      return TRUE;
  }

  return FALSE;
}

static void _agent_chat_handle_response(dt_lib_module_t *self,
                                        const dt_agent_chat_response_t *response)
{
  if(response->message_text && response->message_text[0] != '\0')
    _agent_chat_append_message(self, _("assistant"), response->message_text);

  if(g_strcmp0(response->status, "error") == 0)
  {
    const char *error_message = response->error_message ? response->error_message : _("agent server returned an error");
    _agent_chat_set_error(self, error_message);
    _agent_chat_set_status(self, _("Server error"));
    return;
  }

  if(response->actions && response->actions->len > 0)
  {
    GError *apply_error = NULL;
    if(!dt_agent_actions_apply_response(response, &apply_error))
    {
      const char *message = apply_error && apply_error->message ? apply_error->message : _("failed to apply agent changes");
      _agent_chat_set_error(self, message);
      _agent_chat_set_status(self, _("Apply failed"));
      _agent_chat_append_message(self, _("system"), message);
      g_clear_error(&apply_error);
      return;
    }

    _agent_chat_append_apply_summary(self, response);
    _agent_chat_set_status(self, _("Applied mocked changes"));
    return;
  }

  _agent_chat_set_status(self, _("Response received"));
}

static void _agent_chat_request_finished(const dt_agent_client_result_t *result,
                                         gpointer user_data)
{
  dt_agent_chat_submission_t *submission = user_data;
  dt_lib_module_t *self = submission->self;

  if(!self || !self->data)
    return;

  if(_agent_chat_is_stale_response(self, submission, result))
  {
    _agent_chat_set_loading(self, FALSE);
    _agent_chat_set_status(self, _("Ignored stale response"));
    dt_print(DT_DEBUG_AI,
             "[agent_chat] ignoring stale response request=%s conversation=%s",
             submission->request_id ? submission->request_id : "",
             submission->conversation_id ? submission->conversation_id : "");
    return;
  }

  _agent_chat_set_loading(self, FALSE);

  if(result->transport_error || !result->has_response)
  {
    _agent_chat_handle_transport_error(self, result->transport_error);
    return;
  }

  _agent_chat_set_error(self, NULL);
  _agent_chat_handle_response(self, &result->response);
}

static void _agent_chat_submit(dt_lib_module_t *self,
                               const char *prompt,
                               const char *mock_action_id)
{
  dt_lib_agent_chat_t *d = self->data;
  g_autofree gchar *message = g_strstrip(g_strdup(prompt ? prompt : ""));

  if(d->is_loading || !message[0])
    return;

  _agent_chat_append_message(self, _("you"), message);
  _agent_chat_set_error(self, NULL);
  _agent_chat_set_loading(self, TRUE);
  _agent_chat_set_status(self, _("Sending request..."));

  dt_agent_chat_request_t request;
  GError *error = NULL;
  if(!_agent_chat_build_request(self, message, mock_action_id, &request, &error))
  {
    _agent_chat_set_loading(self, FALSE);
    _agent_chat_handle_transport_error(self, error && error->message ? error->message : _("failed to build request"));
    g_clear_error(&error);
    return;
  }

  dt_agent_chat_submission_t *submission = _agent_chat_submission_new(self, message, mock_action_id,
                                                                      &request);
  dt_job_t *job = dt_agent_client_chat_async(&request, _agent_chat_request_finished, submission,
                                             _agent_chat_submission_free);
  dt_agent_chat_request_clear(&request);

  if(!job)
  {
    _agent_chat_set_loading(self, FALSE);
    _agent_chat_handle_transport_error(self, _("failed to queue the agent request"));
  }
}

static void _agent_chat_send_clicked(GtkButton *button, gpointer user_data)
{
  (void)button;
  dt_lib_module_t *self = user_data;
  dt_lib_agent_chat_t *d = self->data;
  const char *text = gtk_entry_get_text(GTK_ENTRY(d->input_entry));

  _agent_chat_submit(self, text, NULL);
  if(!d->is_loading)
    return;

  gtk_entry_set_text(GTK_ENTRY(d->input_entry), "");
}

static void _agent_chat_entry_activate(GtkEntry *entry, gpointer user_data)
{
  (void)entry;
  _agent_chat_send_clicked(NULL, user_data);
}

static void _agent_chat_brighten_clicked(GtkButton *button, gpointer user_data)
{
  (void)button;
  _agent_chat_submit(user_data, _("brighten exposure"), "brighten-exposure");
}

static void _agent_chat_darken_clicked(GtkButton *button, gpointer user_data)
{
  (void)button;
  _agent_chat_submit(user_data, _("darken exposure"), "darken-exposure");
}

void gui_reset(dt_lib_module_t *self)
{
  dt_lib_agent_chat_t *d = self->data;

  g_free(d->conversation_id);
  d->conversation_id = g_uuid_string_random();

  GtkTextBuffer *buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(d->conversation_view));
  gtk_text_buffer_set_text(buffer, "", -1);
  gtk_entry_set_text(GTK_ENTRY(d->input_entry), "");
  _agent_chat_set_error(self, NULL);
  _agent_chat_set_loading(self, FALSE);
  _agent_chat_set_status(self, _("Ready"));
}

void gui_init(dt_lib_module_t *self)
{
  dt_lib_agent_chat_t *d = g_malloc0(sizeof(*d));
  self->data = d;

  GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, DT_PIXEL_APPLY_DPI(6));
  GtkWidget *conversation = gtk_text_view_new();
  GtkWidget *conversation_wrap = dt_ui_resize_wrap(conversation, 220, DT_AGENT_CHAT_WINDOW_HEIGHT_CONF);
  GtkWidget *quick_actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, DT_PIXEL_APPLY_DPI(6));
  GtkWidget *input_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, DT_PIXEL_APPLY_DPI(6));
  GtkWidget *status_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, DT_PIXEL_APPLY_DPI(6));

  d->conversation_view = conversation;
  d->brighten_button = gtk_button_new_with_label(_("brighten exposure"));
  d->darken_button = gtk_button_new_with_label(_("darken exposure"));
  d->input_entry = dt_ui_entry_new(0);
  d->send_button = gtk_button_new_with_label(_("send"));
  d->spinner = gtk_spinner_new();
  d->status_label = gtk_label_new(_("Ready"));
  d->error_label = gtk_label_new(NULL);

  gtk_widget_set_name(root, "agent-chat-ui");
  gtk_widget_set_vexpand(conversation_wrap, TRUE);
  gtk_widget_set_hexpand(conversation_wrap, TRUE);
  gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(conversation), GTK_WRAP_WORD_CHAR);
  gtk_text_view_set_editable(GTK_TEXT_VIEW(conversation), FALSE);
  gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(conversation), FALSE);
  gtk_text_view_set_left_margin(GTK_TEXT_VIEW(conversation), DT_PIXEL_APPLY_DPI(6));
  gtk_text_view_set_right_margin(GTK_TEXT_VIEW(conversation), DT_PIXEL_APPLY_DPI(6));
  gtk_text_view_set_top_margin(GTK_TEXT_VIEW(conversation), DT_PIXEL_APPLY_DPI(6));
  gtk_text_view_set_bottom_margin(GTK_TEXT_VIEW(conversation), DT_PIXEL_APPLY_DPI(6));
  dt_gui_add_class(conversation, "dt_transparent_background");

  gtk_entry_set_placeholder_text(GTK_ENTRY(d->input_entry),
                                 _("ask for an edit or describe a change"));
  gtk_entry_set_activates_default(GTK_ENTRY(d->input_entry), TRUE);
  gtk_widget_set_hexpand(d->input_entry, TRUE);

  gtk_widget_set_halign(d->status_label, GTK_ALIGN_START);
  gtk_widget_set_halign(d->error_label, GTK_ALIGN_START);
  gtk_label_set_xalign(GTK_LABEL(d->status_label), 0.0f);
  gtk_label_set_xalign(GTK_LABEL(d->error_label), 0.0f);
  gtk_widget_set_name(d->error_label, "dt-warning");
  gtk_widget_set_visible(d->spinner, FALSE);
  gtk_widget_set_visible(d->error_label, FALSE);

  gtk_box_pack_start(GTK_BOX(quick_actions), d->brighten_button, TRUE, TRUE, 0);
  gtk_box_pack_start(GTK_BOX(quick_actions), d->darken_button, TRUE, TRUE, 0);

  gtk_box_pack_start(GTK_BOX(input_row), d->input_entry, TRUE, TRUE, 0);
  gtk_box_pack_start(GTK_BOX(input_row), d->send_button, FALSE, FALSE, 0);

  gtk_box_pack_start(GTK_BOX(status_row), d->spinner, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(status_row), d->status_label, TRUE, TRUE, 0);

  gtk_box_pack_start(GTK_BOX(root), conversation_wrap, TRUE, TRUE, 0);
  gtk_box_pack_start(GTK_BOX(root), quick_actions, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(root), input_row, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(root), status_row, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(root), d->error_label, FALSE, FALSE, 0);

  g_signal_connect(d->send_button, "clicked", G_CALLBACK(_agent_chat_send_clicked), self);
  g_signal_connect(d->input_entry, "activate", G_CALLBACK(_agent_chat_entry_activate), self);
  g_signal_connect(d->brighten_button, "clicked", G_CALLBACK(_agent_chat_brighten_clicked), self);
  g_signal_connect(d->darken_button, "clicked", G_CALLBACK(_agent_chat_darken_clicked), self);

  self->widget = root;
  gui_reset(self);
  gtk_widget_show_all(self->widget);
  gtk_widget_set_visible(d->spinner, FALSE);
  gtk_widget_set_visible(d->error_label, FALSE);
}

void gui_cleanup(dt_lib_module_t *self)
{
  dt_lib_agent_chat_t *d = self->data;
  if(!d) return;

  g_free(d->conversation_id);
  g_free(d);
  self->data = NULL;
}

// clang-format off
// modelines: These editor modelines have been set for all relevant files by tools/update_modelines.py
// vim: shiftwidth=2 expandtab tabstop=2 cindent
// kate: tab-indents: off; indent-width 2; replace-tabs on; indent-mode cstyle; remove-trailing-spaces modified;
// clang-format on
