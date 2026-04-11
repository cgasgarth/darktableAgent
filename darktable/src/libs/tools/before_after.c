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

#include "common/darktable.h"
#include "control/signal.h"
#include "dtgtk/togglebutton.h"
#include "gui/accelerators.h"
#include "libs/lib.h"
#include "libs/lib_api.h"

DT_MODULE(1)

typedef struct dt_lib_before_after_t
{
  GtkWidget *button;
} dt_lib_before_after_t;

static void _before_after_toggled(GtkToggleButton *button,
                                  dt_lib_module_t *self);

static void _before_after_sync(dt_lib_module_t *self)
{
  dt_lib_before_after_t *d = self->data;

  gboolean active = FALSE;
  if(darktable.lib->proxy.snapshots.module
     && darktable.lib->proxy.snapshots.is_before_after_active)
  {
    active = darktable.lib->proxy.snapshots.is_before_after_active(
      darktable.lib->proxy.snapshots.module);
  }

  g_signal_handlers_block_by_func(d->button, _before_after_toggled, self);
  gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(d->button), active);
  g_signal_handlers_unblock_by_func(d->button, _before_after_toggled, self);
}

static void _before_after_toggled(GtkToggleButton *button,
                                  dt_lib_module_t *self)
{
  if(!darktable.lib->proxy.snapshots.module
     || !darktable.lib->proxy.snapshots.set_before_after)
  {
    _before_after_sync(self);
    return;
  }

  darktable.lib->proxy.snapshots.set_before_after(
    darktable.lib->proxy.snapshots.module,
    gtk_toggle_button_get_active(button));
}

static void _develop_image_changed(gpointer instance,
                                   dt_lib_module_t *self)
{
  (void)instance;
  dt_lib_gui_queue_update(self);
}

static void _view_changed(gpointer instance,
                          dt_view_t *old_view,
                          dt_view_t *new_view,
                          dt_lib_module_t *self)
{
  (void)instance;
  (void)old_view;
  (void)new_view;
  dt_lib_gui_queue_update(self);
}

const char *name(dt_lib_module_t *self)
{
  return _("before/after");
}

dt_view_type_flags_t views(dt_lib_module_t *self)
{
  return DT_VIEW_DARKROOM;
}

uint32_t container(dt_lib_module_t *self)
{
  return DT_UI_CONTAINER_PANEL_CENTER_TOP_RIGHT;
}

int expandable(dt_lib_module_t *self)
{
  return 0;
}

int position(const dt_lib_module_t *self)
{
  return 1002;
}

void gui_init(dt_lib_module_t *self)
{
  dt_lib_before_after_t *d = g_malloc0(sizeof(dt_lib_before_after_t));
  self->data = d;

  self->widget = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
  d->button = dtgtk_togglebutton_new(dtgtk_cairo_paint_eye_toggle, 0, NULL);
  gtk_widget_set_tooltip_text(d->button,
                              _("toggle before/after split compare"));
  dt_action_define(DT_ACTION(self), NULL, N_("toggle"), d->button, &dt_action_def_toggle);
  g_signal_connect(G_OBJECT(d->button), "toggled",
                   G_CALLBACK(_before_after_toggled), self);
  gtk_box_pack_start(GTK_BOX(self->widget), d->button, FALSE, FALSE, 0);

  DT_CONTROL_SIGNAL_HANDLE(DT_SIGNAL_DEVELOP_IMAGE_CHANGED, _develop_image_changed);
  DT_CONTROL_SIGNAL_HANDLE(DT_SIGNAL_VIEWMANAGER_VIEW_CHANGED, _view_changed);

  _before_after_sync(self);
}

void gui_cleanup(dt_lib_module_t *self)
{
  g_free(self->data);
  self->data = NULL;
}

void gui_update(dt_lib_module_t *self)
{
  _before_after_sync(self);
}
