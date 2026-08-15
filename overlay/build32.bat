@echo off
setlocal
set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if not exist "%VCVARS%" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if not exist "%VCVARS%" (
    echo [ERROR] vcvars32.bat not found
    exit /b 1
)
call "%VCVARS%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to init MSVC x86 environment
    exit /b 1
)
if not exist bin32 mkdir bin32
cl /std:c++17 /utf-8 /DNOMINMAX /MD /O2 /EHsc /W3 /nologo src\main.cpp src\ai_translator.cpp src\toast_window.cpp src\pipe_server.cpp src\textractor_host.cpp src\text_stabilizer.cpp src\subtitle_window.cpp src\filter_chain.cpp src\engine_policy.cpp src\cleanliness_checker.cpp src\filters\dedup_chars.cpp src\filters\dedup_lines.cpp src\filters\dedup_mixed_lines.cpp src\filters\furigana.cpp src\filters\html_tag.cpp src\filters\control_char.cpp src\filters\shift_jis.cpp src\filters\english_symbol.cpp src\filters\quote_only.cpp src\filters\unicode_normalize.cpp src\filters\line_trimmer.cpp src\filters\regex_replace.cpp src\filters\incremental_dedup.cpp /I src /I third_party /I third_party\textractor /Fe:bin32\overlay.exe /link d2d1.lib dwrite.lib windowscodecs.lib ole32.lib user32.lib gdi32.lib advapi32.lib winhttp.lib third_party\textractor\hostlib32.lib /SUBSYSTEM:WINDOWS
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)
echo [DONE] bin32\overlay.exe