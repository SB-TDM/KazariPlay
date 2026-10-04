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
cl /std:c++17 /utf-8 /DNOMINMAX /MD /O2 /EHsc /W3 /nologo src\main.cpp src\toast_window.cpp src\pipe_server.cpp /I src /I third_party /Fe:bin32\overlay.exe /link d2d1.lib dwrite.lib windowscodecs.lib ole32.lib user32.lib gdi32.lib /SUBSYSTEM:WINDOWS
if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)
echo [DONE] bin32\overlay.exe
