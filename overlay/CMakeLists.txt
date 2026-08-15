cmake_minimum_required(VERSION 3.16)
project(KazariPlayOverlay CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(overlay WIN32
    src/main.cpp
    src/toast_window.cpp
    src/pipe_server.cpp
    src/textractor_host.cpp
    src/text_stabilizer.cpp
    src/subtitle_window.cpp
    src/ai_translator.cpp
    src/filter_chain.cpp
    src/engine_policy.cpp
    src/cleanliness_checker.cpp
    src/filters/dedup_chars.cpp
    src/filters/dedup_lines.cpp
    src/filters/dedup_mixed_lines.cpp
    src/filters/furigana.cpp
    src/filters/html_tag.cpp
    src/filters/control_char.cpp
    src/filters/shift_jis.cpp
    src/filters/english_symbol.cpp
    src/filters/quote_only.cpp
    src/filters/unicode_normalize.cpp
    src/filters/line_trimmer.cpp
    src/filters/regex_replace.cpp
    src/filters/incremental_dedup.cpp
)

target_include_directories(overlay PRIVATE
    src
    third_party
    third_party/textractor
)

# 静态链接 hostlib.lib（官方 Textractor v5.2.0 host 静态库，见 third_party/textractor）
target_link_libraries(overlay PRIVATE
    d2d1 dwrite windowscodecs ole32 user32 gdi32
    ${CMAKE_SOURCE_DIR}/third_party/textractor/hostlib.lib
)

target_compile_definitions(overlay PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)

set_target_properties(overlay PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin"
    OUTPUT_NAME "overlay"
)

# 运行时依赖的 DLL 复制到输出目录（存在才复制，缺失时构建不失败）
add_custom_command(TARGET overlay POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/third_party/textractor/host.dll
        ${CMAKE_SOURCE_DIR}/bin/host.dll
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/third_party/textractor/texthook32.dll
        ${CMAKE_SOURCE_DIR}/bin/texthook32.dll
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/third_party/textractor/texthook64.dll
        ${CMAKE_SOURCE_DIR}/bin/texthook64.dll
)
