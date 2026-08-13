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

set_target_properties(overlay PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin"
    OUTPUT_NAME "overlay"
)
