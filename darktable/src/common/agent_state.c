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

#include "common/agent_state.h"

#include "common/agent_catalog.h"
#include "develop/develop.h"

#include <glib/gi18n.h>
#include <string.h>

typedef enum dt_agent_state_error_t
{
  DT_AGENT_STATE_ERROR_INVALID = 1,
} dt_agent_state_error_t;

static GQuark _agent_state_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-state-error");
}

static void _agent_image_control_free(gpointer data)
{
  dt_agent_image_control_t *control = data;
  if(!control)
    return;

  g_free(control->capability_id);
  g_free(control->label);
  g_free(control->action_path);
  g_free(control);
}

static dt_agent_image_control_t *_agent_image_control_copy(const dt_agent_image_control_t *src)
{
  dt_agent_image_control_t *dest = g_new0(dt_agent_image_control_t, 1);
  dest->capability_id = g_strdup(src->capability_id);
  dest->label = g_strdup(src->label);
  dest->action_path = g_strdup(src->action_path);
  dest->has_current_number = src->has_current_number;
  dest->current_number = src->current_number;
  return dest;
}

static void _agent_history_item_free(gpointer data)
{
  dt_agent_history_item_t *item = data;
  if(!item)
    return;

  g_free(item->module);
  g_free(item->instance_name);
  g_free(item);
}

static dt_agent_history_item_t *_agent_history_item_copy(const dt_agent_history_item_t *src)
{
  dt_agent_history_item_t *dest = g_new0(dt_agent_history_item_t, 1);
  dest->num = src->num;
  dest->module = g_strdup(src->module);
  dest->enabled = src->enabled;
  dest->multi_priority = src->multi_priority;
  dest->instance_name = g_strdup(src->instance_name);
  dest->iop_order = src->iop_order;
  return dest;
}

void dt_agent_image_metadata_clear(dt_agent_image_metadata_t *metadata)
{
  if(!metadata)
    return;

  g_free(metadata->image_name);
  g_free(metadata->camera_maker);
  g_free(metadata->camera_model);
  memset(metadata, 0, sizeof(*metadata));
}

void dt_agent_image_state_init(dt_agent_image_state_t *state)
{
  if(!state)
    return;

  memset(state, 0, sizeof(*state));
  state->controls = g_ptr_array_new_with_free_func(_agent_image_control_free);
  state->history = g_ptr_array_new_with_free_func(_agent_history_item_free);
}

void dt_agent_image_state_clear(dt_agent_image_state_t *state)
{
  if(!state)
    return;

  dt_agent_image_metadata_clear(&state->metadata);
  if(state->controls)
    g_ptr_array_unref(state->controls);
  if(state->history)
    g_ptr_array_unref(state->history);
  memset(state, 0, sizeof(*state));
}

void dt_agent_image_state_copy(dt_agent_image_state_t *dest,
                               const dt_agent_image_state_t *src)
{
  dt_agent_image_state_init(dest);
  dest->has_current_exposure = src->has_current_exposure;
  dest->current_exposure = src->current_exposure;
  dest->history_position = src->history_position;
  dest->history_count = src->history_count;
  dest->metadata.has_image_id = src->metadata.has_image_id;
  dest->metadata.image_id = src->metadata.image_id;
  dest->metadata.image_name = g_strdup(src->metadata.image_name);
  dest->metadata.camera_maker = g_strdup(src->metadata.camera_maker);
  dest->metadata.camera_model = g_strdup(src->metadata.camera_model);
  dest->metadata.width = src->metadata.width;
  dest->metadata.height = src->metadata.height;
  dest->metadata.exif_exposure_seconds = src->metadata.exif_exposure_seconds;
  dest->metadata.exif_aperture = src->metadata.exif_aperture;
  dest->metadata.exif_iso = src->metadata.exif_iso;
  dest->metadata.exif_focal_length = src->metadata.exif_focal_length;

  for(guint i = 0; i < src->controls->len; i++)
  {
    const dt_agent_image_control_t *control = g_ptr_array_index(src->controls, i);
    g_ptr_array_add(dest->controls, _agent_image_control_copy(control));
  }

  for(guint i = 0; i < src->history->len; i++)
  {
    const dt_agent_history_item_t *item = g_ptr_array_index(src->history, i);
    g_ptr_array_add(dest->history, _agent_history_item_copy(item));
  }
}

static void _collect_metadata(const dt_develop_t *dev, dt_agent_image_state_t *state)
{
  const dt_image_t *image = &dev->image_storage;
  state->metadata.has_image_id = image->id > 0;
  state->metadata.image_id = image->id;
  state->metadata.image_name = image->filename[0] ? g_strdup(image->filename) : NULL;
  state->metadata.camera_maker = image->camera_maker[0] ? g_strdup(image->camera_maker) : NULL;
  state->metadata.camera_model = image->camera_model[0] ? g_strdup(image->camera_model) : NULL;
  state->metadata.width = image->width;
  state->metadata.height = image->height;
  state->metadata.exif_exposure_seconds = image->exif_exposure;
  state->metadata.exif_aperture = image->exif_aperture;
  state->metadata.exif_iso = image->exif_iso;
  state->metadata.exif_focal_length = image->exif_focal_length;
}

static void _collect_controls(dt_agent_image_state_t *state)
{
  guint descriptor_count = 0;
  const dt_agent_action_descriptor_t *descriptors
    = dt_agent_catalog_descriptors(&descriptor_count);

  for(guint i = 0; i < descriptor_count; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = &descriptors[i];
    dt_agent_image_control_t *control = g_new0(dt_agent_image_control_t, 1);
    control->capability_id = g_strdup(descriptor->capability_id);
    control->label = g_strdup(descriptor->label);
    control->action_path = g_strdup(descriptor->action_path);

    GError *read_error = NULL;
    if(dt_agent_catalog_read_current_number(descriptor, &control->current_number, &read_error))
    {
      control->has_current_number = TRUE;
      if(g_strcmp0(descriptor->action_path, "iop/exposure/exposure") == 0)
      {
        state->has_current_exposure = TRUE;
        state->current_exposure = control->current_number;
      }
    }
    g_clear_error(&read_error);

    g_ptr_array_add(state->controls, control);
  }
}

static void _collect_history(const dt_develop_t *dev, dt_agent_image_state_t *state)
{
  state->history_position = dev->history_end;
  state->history_count = g_list_length(dev->history);

  gint index = 0;
  for(const GList *iter = dev->history; iter && index < dev->history_end; iter = g_list_next(iter), index++)
  {
    const dt_dev_history_item_t *history_item = iter->data;
    if(!history_item)
      continue;

    dt_agent_history_item_t *item = g_new0(dt_agent_history_item_t, 1);
    item->num = history_item->num;
    item->module = history_item->op_name[0] ? g_strdup(history_item->op_name) : NULL;
    item->enabled = history_item->enabled;
    item->multi_priority = history_item->multi_priority;
    item->instance_name = history_item->multi_name[0] ? g_strdup(history_item->multi_name) : NULL;
    item->iop_order = history_item->iop_order;
    g_ptr_array_add(state->history, item);
  }
}

gboolean dt_agent_image_state_collect_from_dev(const dt_develop_t *dev,
                                               dt_agent_image_state_t *state,
                                               GError **error)
{
  if(!dev || !state)
  {
    g_set_error(error, _agent_state_error_quark(), DT_AGENT_STATE_ERROR_INVALID,
                "%s", _("missing darkroom state"));
    return FALSE;
  }

  dt_agent_image_state_clear(state);
  dt_agent_image_state_init(state);

  _collect_metadata(dev, state);
  _collect_controls(state);
  _collect_history(dev, state);
  return TRUE;
}
