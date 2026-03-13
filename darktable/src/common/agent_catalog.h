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

#include "common/agent_protocol.h"

G_BEGIN_DECLS

#define DT_AGENT_VALUE_MODE_FLAG_SET (1u << 0)
#define DT_AGENT_VALUE_MODE_FLAG_DELTA (1u << 1)

typedef struct dt_agent_action_descriptor_t
{
  const gchar *capability_id;
  const gchar *label;
  const gchar *action_path;
  dt_agent_operation_kind_t operation_kind;
  double min_number;
  double max_number;
  double default_number;
  double step_number;
  guint supported_modes;
} dt_agent_action_descriptor_t;

const dt_agent_action_descriptor_t *dt_agent_catalog_get_descriptor(const char *action_path);
const dt_agent_action_descriptor_t *dt_agent_catalog_descriptors(guint *count);

gboolean dt_agent_catalog_supports_mode(const dt_agent_action_descriptor_t *descriptor,
                                        dt_agent_value_mode_t mode);
double dt_agent_catalog_clamp_number(const dt_agent_action_descriptor_t *descriptor,
                                     double requested_number);
gboolean dt_agent_catalog_read_current_number(const dt_agent_action_descriptor_t *descriptor,
                                              double *out_number,
                                              GError **error);
gboolean dt_agent_catalog_write_number(const dt_agent_action_descriptor_t *descriptor,
                                       double requested_number,
                                       double *out_applied_number,
                                       GError **error);

G_END_DECLS
