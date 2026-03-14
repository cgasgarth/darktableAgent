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
#include "common/colorspaces.h"
#include "develop/develop.h"
#include "imageio/imageio_common.h"
#include "imageio/imageio_module.h"

#include <gdk-pixbuf/gdk-pixbuf.h>
#include <glib/gi18n.h>
#include <math.h>
#include <string.h>

typedef enum dt_agent_state_error_t
{
  DT_AGENT_STATE_ERROR_INVALID = 1,
} dt_agent_state_error_t;

typedef struct dt_agent_memory_format_t
{
  dt_imageio_module_data_t head;
  float *buf;
} dt_agent_memory_format_t;

static GQuark _agent_state_error_quark(void)
{
  return g_quark_from_static_string("dt-agent-state-error");
}

static const char *_memory_mime(dt_imageio_module_data_t *data)
{
  (void)data;
  return "memory";
}

static int _memory_levels(dt_imageio_module_data_t *data)
{
  (void)data;
  return IMAGEIO_RGB | IMAGEIO_FLOAT;
}

static int _memory_bpp(dt_imageio_module_data_t *data)
{
  (void)data;
  return 32;
}

static int _memory_write_image(dt_imageio_module_data_t *data,
                               const char *filename,
                               const void *in,
                               dt_colorspaces_color_profile_type_t over_type,
                               const char *over_filename,
                               void *exif,
                               const int exif_len,
                               const dt_imgid_t imgid,
                               const int num,
                               const int total,
                               dt_dev_pixelpipe_t *pipe,
                               const gboolean export_masks)
{
  (void)filename;
  (void)over_type;
  (void)over_filename;
  (void)exif;
  (void)exif_len;
  (void)imgid;
  (void)num;
  (void)total;
  (void)pipe;
  (void)export_masks;

  dt_agent_memory_format_t *format = (dt_agent_memory_format_t *)data;
  format->buf = malloc(sizeof(float) * 4 * format->head.width * format->head.height);
  if(!format->buf)
    return 1;

  memcpy(format->buf, in, sizeof(float) * 4 * format->head.width * format->head.height);
  return 0;
}

static void _preview_pixels_destroy(guchar *pixels, gpointer data)
{
  (void)data;
  g_free(pixels);
}

static void _agent_image_control_free(gpointer data)
{
  dt_agent_image_control_t *control = data;
  if(!control)
    return;

  g_free(control->setting_id);
  g_free(control->capability_id);
  g_free(control->label);
  g_free(control->kind);
  g_free(control->action_path);
  g_free(control->current_choice_id);
  if(control->choices)
    g_ptr_array_unref(control->choices);
  g_free(control);
}

static dt_agent_image_control_t *_agent_image_control_copy(const dt_agent_image_control_t *src)
{
  dt_agent_image_control_t *dest = g_new0(dt_agent_image_control_t, 1);
  dest->setting_id = g_strdup(src->setting_id);
  dest->capability_id = g_strdup(src->capability_id);
  dest->label = g_strdup(src->label);
  dest->kind = g_strdup(src->kind);
  dest->action_path = g_strdup(src->action_path);
  dest->supported_modes = src->supported_modes;
  dest->has_current_number = src->has_current_number;
  dest->current_number = src->current_number;
  if(src->choices)
  {
    dest->choices = g_ptr_array_new_with_free_func(dt_agent_choice_option_free);
    for(guint i = 0; i < src->choices->len; i++)
    {
      dt_agent_choice_option_t *option = g_ptr_array_index(src->choices, i);
      g_ptr_array_add(dest->choices, dt_agent_choice_option_copy(option));
    }
  }
  dest->has_default_choice_value = src->has_default_choice_value;
  dest->default_choice_value = src->default_choice_value;
  dest->has_current_choice_value = src->has_current_choice_value;
  dest->current_choice_value = src->current_choice_value;
  dest->current_choice_id = g_strdup(src->current_choice_id);
  dest->has_default_bool = src->has_default_bool;
  dest->default_bool = src->default_bool;
  dest->has_current_bool = src->has_current_bool;
  dest->current_bool = src->current_bool;
  dest->min_number = src->min_number;
  dest->max_number = src->max_number;
  dest->default_number = src->default_number;
  dest->step_number = src->step_number;
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
  g_free(state->preview.preview_id);
  g_free(state->preview.mime_type);
  g_free(state->preview.base64_data);
  memset(state, 0, sizeof(*state));
}

void dt_agent_image_state_copy(dt_agent_image_state_t *dest,
                               const dt_agent_image_state_t *src)
{
  dt_agent_image_state_init(dest);
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

  dest->preview.available = src->preview.available;
  dest->preview.preview_id = g_strdup(src->preview.preview_id);
  dest->preview.mime_type = g_strdup(src->preview.mime_type);
  dest->preview.width = src->preview.width;
  dest->preview.height = src->preview.height;
  dest->preview.base64_data = g_strdup(src->preview.base64_data);

  dest->histogram.available = src->histogram.available;
  dest->histogram.bin_count = src->histogram.bin_count;
  memcpy(dest->histogram.red, src->histogram.red, sizeof(src->histogram.red));
  memcpy(dest->histogram.green, src->histogram.green, sizeof(src->histogram.green));
  memcpy(dest->histogram.blue, src->histogram.blue, sizeof(src->histogram.blue));
  memcpy(dest->histogram.luma, src->histogram.luma, sizeof(src->histogram.luma));
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

static void _control_copy_choices(dt_agent_image_control_t *control,
                                  const dt_agent_action_descriptor_t *descriptor)
{
  if(!descriptor->choices)
    return;

  control->choices = g_ptr_array_new_with_free_func(dt_agent_choice_option_free);
  for(guint i = 0; i < descriptor->choices->len; i++)
  {
    dt_agent_choice_option_t *option = g_ptr_array_index(descriptor->choices, i);
    g_ptr_array_add(control->choices, dt_agent_choice_option_copy(option));
  }
}

static void _collect_controls(const dt_develop_t *dev, dt_agent_image_state_t *state)
{
  g_autoptr(GPtrArray) descriptors = g_ptr_array_new_with_free_func(dt_agent_action_descriptor_free);
  if(!dt_agent_catalog_collect_descriptors(dev, descriptors, NULL))
    return;

  for(guint i = 0; i < descriptors->len; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = g_ptr_array_index(descriptors, i);
    dt_agent_image_control_t *control = g_new0(dt_agent_image_control_t, 1);
    control->setting_id = g_strdup(descriptor->setting_id);
    control->capability_id = g_strdup(descriptor->capability_id);
    control->label = g_strdup(descriptor->label);
    control->kind = g_strdup(descriptor->kind_name);
    control->action_path = g_strdup(descriptor->action_path);
    control->supported_modes = descriptor->supported_modes;
    control->min_number = descriptor->min_number;
    control->max_number = descriptor->max_number;
    control->default_number = descriptor->default_number;
    control->step_number = descriptor->step_number;
    control->has_default_choice_value = descriptor->has_default_choice_value;
    control->default_choice_value = descriptor->default_choice_value;
    control->has_default_bool = descriptor->has_default_bool;
    control->default_bool = descriptor->default_bool;
    _control_copy_choices(control, descriptor);

    switch(descriptor->operation_kind)
    {
      case DT_AGENT_OPERATION_SET_FLOAT:
        control->has_current_number
          = dt_agent_catalog_read_current_number(descriptor, &control->current_number, NULL);
        break;
      case DT_AGENT_OPERATION_SET_CHOICE:
        control->has_current_choice_value = dt_agent_catalog_read_current_choice(
          descriptor, &control->current_choice_value, &control->current_choice_id, NULL);
        break;
      case DT_AGENT_OPERATION_SET_BOOL:
        control->has_current_bool
          = dt_agent_catalog_read_current_bool(descriptor, &control->current_bool, NULL);
        break;
      case DT_AGENT_OPERATION_UNKNOWN:
      default:
        break;
    }

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

static void _collect_histogram_from_buffer(dt_agent_image_state_t *state,
                                           const float *buf,
                                           const gint width,
                                           const gint height)
{
  if(!buf || width <= 0 || height <= 0)
    return;

  state->histogram.available = TRUE;
  state->histogram.bin_count = 256;

  const gint pixels = width * height;
  for(gint i = 0; i < pixels; i++)
  {
    const float red = CLAMPS(buf[4 * i + 0], 0.0f, 1.0f);
    const float green = CLAMPS(buf[4 * i + 1], 0.0f, 1.0f);
    const float blue = CLAMPS(buf[4 * i + 2], 0.0f, 1.0f);
    const float luma = CLAMPS(0.2126f * red + 0.7152f * green + 0.0722f * blue, 0.0f, 1.0f);

    const gint red_bin = CLAMP((gint)lrintf(red * 255.0f), 0, 255);
    const gint green_bin = CLAMP((gint)lrintf(green * 255.0f), 0, 255);
    const gint blue_bin = CLAMP((gint)lrintf(blue * 255.0f), 0, 255);
    const gint luma_bin = CLAMP((gint)lrintf(luma * 255.0f), 0, 255);

    state->histogram.red[red_bin]++;
    state->histogram.green[green_bin]++;
    state->histogram.blue[blue_bin]++;
    state->histogram.luma[luma_bin]++;
  }
}

static void _collect_preview_from_buffer(dt_agent_image_state_t *state,
                                         const dt_develop_t *dev,
                                         const float *buf,
                                         const gint width,
                                         const gint height)
{
  if(!buf || width <= 0 || height <= 0 || !state->metadata.has_image_id)
    return;

  guchar *pixels = g_malloc(sizeof(guchar) * width * height * 3);
  for(gint i = 0; i < width * height; i++)
  {
    pixels[3 * i + 0] = CLAMP((gint)lrintf(CLAMPS(buf[4 * i + 0], 0.0f, 1.0f) * 255.0f), 0, 255);
    pixels[3 * i + 1] = CLAMP((gint)lrintf(CLAMPS(buf[4 * i + 1], 0.0f, 1.0f) * 255.0f), 0, 255);
    pixels[3 * i + 2] = CLAMP((gint)lrintf(CLAMPS(buf[4 * i + 2], 0.0f, 1.0f) * 255.0f), 0, 255);
  }

  GdkPixbuf *pixbuf = gdk_pixbuf_new_from_data(pixels,
                                               GDK_COLORSPACE_RGB,
                                               FALSE,
                                               8,
                                               width,
                                               height,
                                               width * 3,
                                               _preview_pixels_destroy,
                                               NULL);
  if(!pixbuf)
  {
    g_free(pixels);
    return;
  }

  gchar *jpeg_data = NULL;
  gsize jpeg_size = 0;
  GError *save_error = NULL;
  if(!gdk_pixbuf_save_to_buffer(pixbuf,
                                &jpeg_data,
                                &jpeg_size,
                                "jpeg",
                                &save_error,
                                "quality",
                                "85",
                                NULL))
  {
    g_object_unref(pixbuf);
    g_clear_error(&save_error);
    return;
  }

  g_object_unref(pixbuf);

  state->preview.available = TRUE;
  state->preview.preview_id
    = g_strdup_printf("preview-%" G_GINT64_FORMAT "-history-%d",
                      state->metadata.image_id,
                      dev->history_end);
  state->preview.mime_type = g_strdup("image/jpeg");
  state->preview.width = width;
  state->preview.height = height;
  state->preview.base64_data = g_base64_encode((const guchar *)jpeg_data, jpeg_size);
  g_free(jpeg_data);
}

static void _collect_render_snapshot(const dt_develop_t *dev, dt_agent_image_state_t *state)
{
  if(!state->metadata.has_image_id)
    return;

  dt_imageio_module_format_t format = { 0 };
  dt_agent_memory_format_t memory = { 0 };
  format.bpp = _memory_bpp;
  format.write_image = _memory_write_image;
  format.levels = _memory_levels;
  format.mime = _memory_mime;
  memory.head.max_width = 1000;
  memory.head.max_height = 1000;
  memory.head.style[0] = '\0';

  if(dt_imageio_export_with_flags(state->metadata.image_id,
                                  "unused",
                                  &format,
                                  (dt_imageio_module_data_t *)&memory,
                                  TRUE,
                                  FALSE,
                                  FALSE,
                                  FALSE,
                                  FALSE,
                                  1.0,
                                  FALSE,
                                  NULL,
                                  FALSE,
                                  FALSE,
                                  DT_COLORSPACE_SRGB,
                                  NULL,
                                  DT_INTENT_PERCEPTUAL,
                                  NULL,
                                  NULL,
                                  1,
                                  1,
                                  NULL,
                                  dev->history_end))
  {
    return;
  }

  _collect_preview_from_buffer(state, dev, memory.buf, memory.head.width, memory.head.height);
  _collect_histogram_from_buffer(state, memory.buf, memory.head.width, memory.head.height);
  free(memory.buf);
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
  _collect_controls(dev, state);
  _collect_history(dev, state);
  _collect_render_snapshot(dev, state);
  return TRUE;
}
