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

#include <glib.h>

G_BEGIN_DECLS

struct dt_develop_t;

typedef struct dt_agent_image_metadata_t
{
  gboolean has_image_id;
  gint64 image_id;
  gchar *image_name;
  gchar *camera_maker;
  gchar *camera_model;
  gint width;
  gint height;
  double exif_exposure_seconds;
  double exif_aperture;
  double exif_iso;
  double exif_focal_length;
} dt_agent_image_metadata_t;

typedef struct dt_agent_image_control_t
{
  gchar *module_id;
  gchar *module_label;
  gchar *setting_id;
  gchar *capability_id;
  gchar *label;
  gchar *kind;
  gchar *action_path;
  guint supported_modes;
  gboolean has_current_number;
  double current_number;
  GPtrArray *choices;
  gboolean has_default_choice_value;
  gint default_choice_value;
  gboolean has_current_choice_value;
  gint current_choice_value;
  gchar *current_choice_id;
  gboolean has_default_bool;
  gboolean default_bool;
  gboolean has_current_bool;
  gboolean current_bool;
  double min_number;
  double max_number;
  double default_number;
  double step_number;
} dt_agent_image_control_t;

typedef struct dt_agent_history_item_t
{
  gint num;
  gchar *module;
  gboolean enabled;
  gint multi_priority;
  gchar *instance_name;
  gint iop_order;
} dt_agent_history_item_t;

typedef struct dt_agent_image_state_t
{
  gint history_position;
  gint history_count;
  dt_agent_image_metadata_t metadata;
  GPtrArray *controls;
  GPtrArray *history;
  struct
  {
    gboolean available;
    gchar *preview_id;
    gchar *mime_type;
    gint width;
    gint height;
    gchar *base64_data;
  } preview;
  struct
  {
    gboolean available;
    gint bin_count;
    guint32 red[256];
    guint32 green[256];
    guint32 blue[256];
    guint32 luma[256];
  } histogram;
} dt_agent_image_state_t;

void dt_agent_image_metadata_clear(dt_agent_image_metadata_t *metadata);

void dt_agent_image_state_init(dt_agent_image_state_t *state);
void dt_agent_image_state_clear(dt_agent_image_state_t *state);
void dt_agent_image_state_copy(dt_agent_image_state_t *dest,
                               const dt_agent_image_state_t *src);

gboolean dt_agent_image_state_collect_from_dev(const struct dt_develop_t *dev,
                                               dt_agent_image_state_t *state,
                                               GError **error);

G_END_DECLS
