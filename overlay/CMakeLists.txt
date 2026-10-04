cmake_minimum_required(VERSION 3.16)
project(KazariPlayOverlay CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(overlay WIN32
    src/main.cpp
    src/toast_window.cpp
    src/pipe_server.cpp
)
target_include_directories(overlay PRIVATE src third_party)
target_link_libraries(overlay PRIVATE d2d1 dwrite windowscodecs ole32 user32 gdi32)
target_compile_definitions(overlay PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
if(MSVC)
    target_compile_options(overlay PRIVATE /utf-8)
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(OVERLAY_OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/bin")
else()
    set(OVERLAY_OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/bin32")
endif()
set_target_properties(overlay PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${OVERLAY_OUTPUT}"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${OVERLAY_OUTPUT}"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${OVERLAY_OUTPUT}"
    OUTPUT_NAME "overlay"
)
