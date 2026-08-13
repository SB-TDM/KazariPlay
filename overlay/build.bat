@echo off
setlocal enabledelayedexpansion

set "VCVARS="
for %%P in (
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
) do (
    if exist %%P (
        set "VCVARS=%%P"
        goto :found
    )
)
:found

if "%VCVARS%"=="" (
    echo [ERROR] vcvars64.bat not found. Install Visual Studio 2022 Build Tools with C++ workload.
    exit /b 1
)

call "%VCVARS%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to init MSVC environment
    exit /b 1
)

if not exist bin mkdir bin

cl /std:c++17 /O2 /EHsc /W3 /nologo src\main.cpp src\toast_window.cpp src\pipe_server.cpp /I src /I third_party /Fe:bin\overlay.exe /link d2d1.lib dwrite.lib windowscodecs.lib ole32.lib user32.lib gdi32.lib /SUBSYSTEM:WINDOWS
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)

echo [DONE] bin\overlay.exe
