find_package(PkgConfig REQUIRED)
pkg_check_modules(AGENT_TEST_DEPS REQUIRED
  glib-2.0
  gobject-2.0
  gio-2.0
  gmodule-2.0
  json-glib-1.0
  gtk+-3.0
  librsvg-2.0)

add_cmocka_test(test_agent_common
                SOURCES test_agent_common.c
                        agent_stubs.c
                        ../../../common/agent_protocol.c
                        ../../../common/agent_actions.c
                LINK_LIBRARIES cmocka::cmocka ${AGENT_TEST_DEPS_LIBRARIES})

target_include_directories(test_agent_common PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../../..
  ${AGENT_TEST_DEPS_INCLUDE_DIRS})

target_link_directories(test_agent_common PRIVATE ${AGENT_TEST_DEPS_LIBRARY_DIRS})
