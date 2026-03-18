#include "common/agent_catalog.h"

#include "common/introspection.h"
#include "develop/develop.h"
#include "develop/imageop.h"

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include "win/main_wrapper.h"
#endif

typedef struct test_colorzones_node_t
{
  float x;
  float y;
} test_colorzones_node_t;

typedef struct test_rgblevels_params_t
{
  float levels[3][3];
} test_rgblevels_params_t;

typedef struct test_colorzones_params_t
{
  test_colorzones_node_t curve[3][8];
  int curve_num_nodes[3];
  int curve_type[3];
  int channel;
  int splines_version;
} test_colorzones_params_t;

typedef struct test_fixture_t
{
  dt_develop_t dev;
  dt_iop_module_t rgblevels_module;
  dt_iop_module_so_t rgblevels_so;
  test_rgblevels_params_t rgblevels_params;
  test_rgblevels_params_t rgblevels_defaults;
  dt_action_target_t rgblevels_referral;
  GSList *rgblevels_widget_list;

  dt_iop_module_t colorzones_module;
  dt_iop_module_so_t colorzones_so;
  test_colorzones_params_t colorzones_params;
  test_colorzones_params_t colorzones_defaults;
  dt_action_target_t colorzones_referral;
  GSList *colorzones_widget_list;

  GList *iop_list;
} test_fixture_t;

static int _failures = 0;

#define CHECK(condition, message) \
  do \
  { \
    if(!(condition)) \
    { \
      fprintf(stderr, "FAIL:%s:%d: %s\n", __FILE__, __LINE__, message); \
      _failures++; \
      return; \
    } \
  } while(0)

#define CHECK_STRING(actual, expected, message) \
  CHECK(g_strcmp0((actual), (expected)) == 0, message)

#define CHECK_INT(actual, expected, message) \
  CHECK((actual) == (expected), message)

#define CHECK_FLOAT(actual, expected, epsilon, message) \
  CHECK(fabs((actual) - (expected)) <= (epsilon), message)

static const char *_rgblevels_module_name(void)
{
  return "RGB Levels";
}

static const char *_colorzones_module_name(void)
{
  return "Color Zones";
}

static dt_introspection_field_t _rgblevels_value_field = {
  .Float = {
    .header = {
      .type = DT_INTROSPECTION_TYPE_FLOAT,
      .type_name = "float",
      .name = "levels_value",
      .field_name = "levels_value",
      .size = sizeof(float),
      .offset = 0,
    },
  },
};

static dt_introspection_field_t _rgblevels_row_field = {
  .Array = {
    .header = {
      .type = DT_INTROSPECTION_TYPE_ARRAY,
      .type_name = "float[3]",
      .name = "levels_row",
      .field_name = "levels_row",
      .size = sizeof(float[3]),
      .offset = 0,
    },
    .count = 3,
    .type = DT_INTROSPECTION_TYPE_FLOAT,
    .field = &_rgblevels_value_field,
  },
};

static dt_introspection_field_t _rgblevels_linear_fields[] = {
  {
    .Array = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_ARRAY,
        .type_name = "float[3][3]",
        .name = "levels",
        .field_name = "levels",
        .size = sizeof(((test_rgblevels_params_t *)0)->levels),
        .offset = offsetof(test_rgblevels_params_t, levels),
      },
      .count = 3,
      .type = DT_INTROSPECTION_TYPE_ARRAY,
      .field = &_rgblevels_row_field,
    },
  },
  {
    .header = {
      .type = DT_INTROSPECTION_TYPE_NONE,
    },
  },
};

static dt_introspection_field_t *_rgblevels_get_introspection_linear(void)
{
  return _rgblevels_linear_fields;
}

static dt_introspection_field_t _colorzones_point_field = {
  .Opaque = {
    .header = {
      .type = DT_INTROSPECTION_TYPE_OPAQUE,
      .type_name = "test_colorzones_node_t",
      .name = "curve_point",
      .field_name = "curve_point",
      .size = sizeof(test_colorzones_node_t),
      .offset = 0,
    },
  },
};

static dt_introspection_field_t _colorzones_curve_channel_field = {
  .Array = {
    .header = {
      .type = DT_INTROSPECTION_TYPE_ARRAY,
      .type_name = "test_colorzones_node_t[8]",
      .name = "curve_channel",
      .field_name = "curve_channel",
      .size = sizeof(test_colorzones_node_t[8]),
      .offset = 0,
    },
    .count = 8,
    .type = DT_INTROSPECTION_TYPE_OPAQUE,
    .field = &_colorzones_point_field,
  },
};

static dt_introspection_field_t _colorzones_int_element_field = {
  .Int = {
    .header = {
      .type = DT_INTROSPECTION_TYPE_INT,
      .type_name = "int",
      .name = "int_value",
      .field_name = "int_value",
      .size = sizeof(int),
      .offset = 0,
    },
  },
};

static dt_introspection_field_t _colorzones_linear_fields[] = {
  {
    .Array = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_ARRAY,
        .type_name = "curve",
        .name = "curve",
        .field_name = "curve",
        .size = sizeof(((test_colorzones_params_t *)0)->curve),
        .offset = offsetof(test_colorzones_params_t, curve),
      },
      .count = 3,
      .type = DT_INTROSPECTION_TYPE_ARRAY,
      .field = &_colorzones_curve_channel_field,
    },
  },
  {
    .Array = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_ARRAY,
        .type_name = "int[3]",
        .name = "curve_num_nodes",
        .field_name = "curve_num_nodes",
        .size = sizeof(((test_colorzones_params_t *)0)->curve_num_nodes),
        .offset = offsetof(test_colorzones_params_t, curve_num_nodes),
      },
      .count = 3,
      .type = DT_INTROSPECTION_TYPE_INT,
      .field = &_colorzones_int_element_field,
    },
  },
  {
    .Array = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_ARRAY,
        .type_name = "int[3]",
        .name = "curve_type",
        .field_name = "curve_type",
        .size = sizeof(((test_colorzones_params_t *)0)->curve_type),
        .offset = offsetof(test_colorzones_params_t, curve_type),
      },
      .count = 3,
      .type = DT_INTROSPECTION_TYPE_INT,
      .field = &_colorzones_int_element_field,
    },
  },
  {
    .Int = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_INT,
        .type_name = "int",
        .name = "channel",
        .field_name = "channel",
        .size = sizeof(int),
        .offset = offsetof(test_colorzones_params_t, channel),
      },
    },
  },
  {
    .Int = {
      .header = {
        .type = DT_INTROSPECTION_TYPE_INT,
        .type_name = "int",
        .name = "splines_version",
        .field_name = "splines_version",
        .size = sizeof(int),
        .offset = offsetof(test_colorzones_params_t, splines_version),
      },
    },
  },
  {
    .header = {
      .type = DT_INTROSPECTION_TYPE_NONE,
    },
  },
};

static dt_introspection_field_t *_colorzones_get_introspection_linear(void)
{
  return _colorzones_linear_fields;
}

static void _initialize_rgblevels_module(test_fixture_t *fixture)
{
  static dt_action_t root_action = {
    .id = "iop",
  };
  static dt_action_t module_action = {
    .id = "rgblevels",
    .owner = &root_action,
  };
  static dt_action_t levels_action = {
    .id = "levels",
    .label = "levels",
    .owner = &module_action,
  };

  fixture->rgblevels_defaults.levels[0][0] = 0.05f;
  fixture->rgblevels_defaults.levels[0][1] = 0.25f;
  fixture->rgblevels_defaults.levels[0][2] = 0.75f;
  fixture->rgblevels_defaults.levels[1][0] = 0.10f;
  fixture->rgblevels_defaults.levels[1][1] = 0.50f;
  fixture->rgblevels_defaults.levels[1][2] = 0.85f;
  fixture->rgblevels_defaults.levels[2][0] = 0.15f;
  fixture->rgblevels_defaults.levels[2][1] = 0.55f;
  fixture->rgblevels_defaults.levels[2][2] = 0.95f;

  fixture->rgblevels_params = fixture->rgblevels_defaults;
  fixture->rgblevels_params.levels[2][2] = 0.91f;

  fixture->rgblevels_so.get_introspection_linear = _rgblevels_get_introspection_linear;

  g_strlcpy(fixture->rgblevels_module.op, "rgblevels", sizeof(fixture->rgblevels_module.op));
  fixture->rgblevels_module.name = _rgblevels_module_name;
  fixture->rgblevels_module.multi_priority = 2;
  fixture->rgblevels_module.have_introspection = TRUE;
  fixture->rgblevels_module.so = &fixture->rgblevels_so;
  fixture->rgblevels_module.params = (dt_iop_params_t *)&fixture->rgblevels_params;
  fixture->rgblevels_module.default_params = (dt_iop_params_t *)&fixture->rgblevels_defaults;
  fixture->rgblevels_module.params_size = sizeof(fixture->rgblevels_params);

  fixture->rgblevels_referral.action = &levels_action;
  fixture->rgblevels_referral.target = NULL;
  fixture->rgblevels_widget_list = g_slist_prepend(NULL, &fixture->rgblevels_referral);
  fixture->rgblevels_module.widget_list = fixture->rgblevels_widget_list;
}

static void _initialize_colorzones_curve(test_colorzones_params_t *params)
{
  params->channel = 0;
  params->splines_version = 1;

  for(int channel = 0; channel < 3; channel++)
  {
    params->curve_num_nodes[channel] = 8;
    params->curve_type[channel] = 0;
    for(int band = 0; band < 8; band++)
    {
      params->curve[channel][band].x = band / 8.0f;
      params->curve[channel][band].y = 0.10f + 0.10f * channel + 0.05f * band;
    }
  }
}

static void _initialize_colorzones_module(test_fixture_t *fixture)
{
  static dt_action_t root_action = {
    .id = "iop",
  };
  static dt_action_t module_action = {
    .id = "colorzones",
    .owner = &root_action,
  };
  static dt_action_t graph_action = {
    .id = "graph",
    .label = "graph",
    .owner = &module_action,
  };

  _initialize_colorzones_curve(&fixture->colorzones_defaults);
  fixture->colorzones_params = fixture->colorzones_defaults;
  fixture->colorzones_params.curve[2][7].y = 0.83f;

  fixture->colorzones_so.get_introspection_linear = _colorzones_get_introspection_linear;

  g_strlcpy(fixture->colorzones_module.op, "colorzones", sizeof(fixture->colorzones_module.op));
  fixture->colorzones_module.name = _colorzones_module_name;
  fixture->colorzones_module.multi_priority = 1;
  fixture->colorzones_module.have_introspection = TRUE;
  fixture->colorzones_module.so = &fixture->colorzones_so;
  fixture->colorzones_module.params = (dt_iop_params_t *)&fixture->colorzones_params;
  fixture->colorzones_module.default_params = (dt_iop_params_t *)&fixture->colorzones_defaults;
  fixture->colorzones_module.params_size = sizeof(fixture->colorzones_params);

  fixture->colorzones_referral.action = &graph_action;
  fixture->colorzones_referral.target = NULL;
  fixture->colorzones_widget_list = g_slist_prepend(NULL, &fixture->colorzones_referral);
  fixture->colorzones_module.widget_list = fixture->colorzones_widget_list;
}

static void _setup_fixture(test_fixture_t *fixture)
{
  memset(fixture, 0, sizeof(*fixture));
  _initialize_rgblevels_module(fixture);
  _initialize_colorzones_module(fixture);
  fixture->iop_list = g_list_append(fixture->iop_list, &fixture->rgblevels_module);
  fixture->iop_list = g_list_append(fixture->iop_list, &fixture->colorzones_module);
  fixture->dev.iop = fixture->iop_list;
}

static void _teardown_fixture(test_fixture_t *fixture)
{
  g_slist_free(fixture->rgblevels_widget_list);
  g_slist_free(fixture->colorzones_widget_list);
  g_list_free(fixture->iop_list);
}

static guint _count_binding(const GPtrArray *descriptors, dt_agent_descriptor_binding_t binding)
{
  guint count = 0;
  for(guint i = 0; i < descriptors->len; i++)
  {
    const dt_agent_action_descriptor_t *descriptor = g_ptr_array_index((GPtrArray *)descriptors, i);
    if(descriptor->binding == binding)
      count++;
  }
  return count;
}

static void test_collect_descriptors_includes_graph_bindings_without_crashing(void)
{
  test_fixture_t fixture;
  _setup_fixture(&fixture);

  for(int iteration = 0; iteration < 10; iteration++)
  {
    g_autoptr(GPtrArray) descriptors = g_ptr_array_new_with_free_func(dt_agent_action_descriptor_free);
    CHECK(dt_agent_catalog_collect_descriptors(&fixture.dev, descriptors, NULL),
          "descriptor collection should succeed");
    CHECK_INT((int)descriptors->len, 33, "unexpected descriptor count");
    CHECK_INT((int)_count_binding(descriptors, DT_AGENT_DESCRIPTOR_BINDING_RGBLEVELS_HANDLE),
              9,
              "unexpected RGB Levels descriptor count");
    CHECK_INT((int)_count_binding(descriptors, DT_AGENT_DESCRIPTOR_BINDING_COLORZONES_BAND),
              24,
              "unexpected Color Zones descriptor count");
  }

  _teardown_fixture(&fixture);
}

static void test_find_descriptor_uses_setting_id_for_graph_controls(void)
{
  test_fixture_t fixture;
  _setup_fixture(&fixture);

  dt_agent_action_descriptor_t *descriptor = dt_agent_catalog_find_descriptor(
    &fixture.dev,
    "iop/rgblevels/levels",
    "setting.iop.rgblevels.levels.instance.2.blue.white",
    NULL);
  CHECK(descriptor != NULL, "descriptor lookup should succeed");
  CHECK_INT(descriptor->binding, DT_AGENT_DESCRIPTOR_BINDING_RGBLEVELS_HANDLE,
            "descriptor binding mismatch");
  CHECK_INT(descriptor->channel_index, 2, "descriptor channel mismatch");
  CHECK_INT(descriptor->element_index, 2, "descriptor element mismatch");
  CHECK_STRING(descriptor->element_name, "white", "descriptor element name mismatch");

  double current_number = 0.0;
  CHECK(dt_agent_catalog_read_current_number(descriptor, &current_number, NULL),
        "descriptor read should succeed");
  CHECK_FLOAT(current_number, 0.91, 1e-6, "descriptor read returned wrong value");

  dt_agent_action_descriptor_free(descriptor);
  _teardown_fixture(&fixture);
}

static void test_colorzones_descriptor_reads_exact_node_value(void)
{
  test_fixture_t fixture;
  _setup_fixture(&fixture);

  dt_agent_action_descriptor_t *descriptor = dt_agent_catalog_find_descriptor(
    &fixture.dev,
    "iop/colorzones/graph",
    "setting.iop.colorzones.graph.instance.1.hue.magenta",
    NULL);
  CHECK(descriptor != NULL, "descriptor lookup should succeed");
  CHECK_INT(descriptor->binding, DT_AGENT_DESCRIPTOR_BINDING_COLORZONES_BAND,
            "descriptor binding mismatch");
  CHECK_INT(descriptor->channel_index, 2, "descriptor channel mismatch");
  CHECK_INT(descriptor->element_index, 7, "descriptor element mismatch");

  double current_number = 0.0;
  CHECK(dt_agent_catalog_read_current_number(descriptor, &current_number, NULL),
        "descriptor read should succeed");
  CHECK_FLOAT(current_number, 0.66, 1e-6, "descriptor read returned wrong value");

  dt_agent_action_descriptor_free(descriptor);
  _teardown_fixture(&fixture);
}

int main(void)
{
  test_collect_descriptors_includes_graph_bindings_without_crashing();
  test_find_descriptor_uses_setting_id_for_graph_controls();
  test_colorzones_descriptor_reads_exact_node_value();

  if(_failures > 0)
  {
    fprintf(stderr, "%d test(s) failed\n", _failures);
    return 1;
  }

  printf("darktable-test-agent-catalog: all tests passed\n");
  return 0;
}
