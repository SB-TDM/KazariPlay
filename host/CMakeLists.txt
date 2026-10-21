cmake_minimum_required(VERSION 3.20)
project(KazariPlayHost LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(KAZARIPLAY_BUILD_HOST "Build the WinHost executable" ON)
set(KAZARIPLAY_WEBVIEW2_SDK_ROOT "" CACHE PATH "Path to Microsoft.Web.WebView2 native package")
set(KAZARIPLAY_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/build/bin" CACHE PATH "Host output directory")

if(MSVC)
    add_compile_options(/utf-8 /W4)
    add_compile_definitions(UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
endif()

enable_testing()

function(add_host_test name source)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/${source}")
        add_executable(${name} "src/${source}")
        target_include_directories(${name} PRIVATE src ../overlay/third_party)
        add_test(NAME ${name} COMMAND ${name})
        set_target_properties(${name} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY "${KAZARIPLAY_OUTPUT_DIR}"
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${KAZARIPLAY_OUTPUT_DIR}"
        )
        if(MSVC)
            target_compile_options(${name} PRIVATE /WX)
        endif()
    else()
        message(STATUS "${name}: skipped (src/${source} not created yet)")
    endif()
endfunction()

if(KAZARIPLAY_BUILD_HOST)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/main.cpp")
        message(STATUS "KazariPlayHost: skipped (src/main.cpp not created yet)")
    elseif(NOT KAZARIPLAY_WEBVIEW2_SDK_ROOT)
        message(FATAL_ERROR "KAZARIPLAY_WEBVIEW2_SDK_ROOT is required to build KazariPlayHost")
    else()
        set(WEBVIEW2_INCLUDE "${KAZARIPLAY_WEBVIEW2_SDK_ROOT}/build/native/include")
        set(WEBVIEW2_LIB "${KAZARIPLAY_WEBVIEW2_SDK_ROOT}/build/native/x64/WebView2LoaderStatic.lib")
        if(NOT EXISTS "${WEBVIEW2_INCLUDE}/WebView2.h")
            message(FATAL_ERROR "WebView2.h not found under ${WEBVIEW2_INCLUDE}")
        endif()
        if(NOT EXISTS "${WEBVIEW2_LIB}")
            message(FATAL_ERROR "x64 WebView2LoaderStatic.lib not found under ${WEBVIEW2_LIB}")
        endif()

        set(HOST_SOURCES
            src/main.cpp
            src/window.cpp
            src/webview.cpp
            src/backend.cpp
        )
        if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/host.manifest.rc")
            list(APPEND HOST_SOURCES host.manifest.rc)
        endif()

        add_executable(KazariPlayHost WIN32 ${HOST_SOURCES})
        target_include_directories(KazariPlayHost PRIVATE
            src
            ../overlay/third_party
            "${WEBVIEW2_INCLUDE}"
        )
        target_link_libraries(KazariPlayHost PRIVATE
            "${WEBVIEW2_LIB}"
            dcomp
            dwmapi
            ole32
            oleaut32
            shlwapi
            user32
            gdi32
        )
        set_target_properties(KazariPlayHost PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY "${KAZARIPLAY_OUTPUT_DIR}"
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${KAZARIPLAY_OUTPUT_DIR}"
        )
    endif()
endif()

add_host_test(host_protocol_test protocol_test.cpp)
add_host_test(host_window_geometry_test window_geometry_test.cpp)
