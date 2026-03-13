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

typedef struct dt_agent_capability_t
{
  gchar *capability_id;
  gchar *label;
  gchar *kind;
  gchar *target_type;
  gchar *action_path;
  guint supported_modes;
  double min_number;
  double max_number;
  double default_number;
  double step_number;
} dt_agent_capability_t;

void dt_agent_capability_free(gpointer data);
dt_agent_capability_t *dt_agent_capability_copy(const dt_agent_capability_t *src);

gboolean dt_agent_capabilities_collect(GPtrArray *capabilities, GError **error);

G_END_DECLS
