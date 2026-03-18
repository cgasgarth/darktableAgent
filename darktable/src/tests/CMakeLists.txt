include_directories("${CMAKE_CURRENT_BINARY_DIR}/../")

add_executable(darktable-test-variables variables.c)
target_link_libraries(darktable-test-variables lib_darktable)

add_executable(darktable-test-agent-catalog agent_catalog.c)
target_link_libraries(darktable-test-agent-catalog lib_darktable)

add_test(NAME darktable-test-agent-catalog COMMAND darktable-test-agent-catalog)

if(WIN32)
    # This tester sets up a darktable instance (of sorts). Hence it expects libraries at ../lib/darktable
    # Easiest way to comply with this on Windows: Put tester executable in same directory as darktable executable
    set_target_properties(darktable-test-variables PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${DARKTABLE_BINDIR}
    )
    set_target_properties(darktable-test-agent-catalog PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${DARKTABLE_BINDIR}
    )
endif(WIN32)

if(cmocka_FOUND)
  add_subdirectory(unittests)
endif()
