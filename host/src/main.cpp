#include "backend.hpp"
#include "webview.hpp"
#include "window.hpp"

#include <iterator>
#include <objbase.h>
#include <shellapi.h>
#include <string>
#include <vector>
#include <windows.h>

namespace {
std::wstring envValue(const wchar_t* name) {
    wchar_t buffer[32768]{};
    const DWORD length = GetEnvironmentVariableW(
        name, buffer, static_cast<DWORD>(std::size(buffer)));
    return length ? std::wstring(buffer, length) : std::wstring();
}

std::wstring widenUtf8(const std::string& value) {
    if (value.empty()) return {};
    const int length = MultiByteToWideChar(
        CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    std::wstring out(length, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                        out.data(), length);
    return out;
}
std::wstring exeDirectory() {
    wchar_t path[MAX_PATH * 4]{};
    const DWORD length = GetModuleFileNameW(nullptr, path,
                                             static_cast<DWORD>(std::size(path)));
    if (!length) return {};
    std::wstring value(path, length);
    const auto slash = value.find_last_of(L"\\/");
    return slash == std::wstring::npos ? std::wstring() : value.substr(0, slash);
}

std::wstring quoteArg(const std::wstring& value) {
    return L"\"" + value + L"\"";
}

int runHelperIfRequested() {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return -1;
    bool helper = false;
    for (int i = 1; i < argc; ++i) {
        const std::wstring arg = argv[i];
        if (arg == L"--apply-update" || arg == L"--apply-rollback") {
            helper = true;
            break;
        }
    }
    if (!helper) {
        LocalFree(argv);
        return -1;
    }

    std::wstring backend = envValue(L"KAZARIPLAY_BACKEND_EXE");
    if (backend.empty()) {
        const std::wstring dir = exeDirectory();
        if (!dir.empty()) backend = dir + L"\\KazariPlayBackend.exe";
    }
    std::wstring command;
    std::wstring workdir = envValue(L"KAZARIPLAY_DEV_ROOT");
    if (!backend.empty() && GetFileAttributesW(backend.c_str()) != INVALID_FILE_ATTRIBUTES) {
        command = quoteArg(backend);
        if (workdir.empty()) workdir = exeDirectory();
    } else {
        const std::wstring python = envValue(L"KAZARIPLAY_DEV_PYTHON");
        const std::wstring script = envValue(L"KAZARIPLAY_BACKEND_SCRIPT");
        if (python.empty() || script.empty()) {
            MessageBoxW(nullptr, L"Update helper backend is unavailable.",
                        L"KazariPlay", MB_ICONERROR);
            LocalFree(argv);
            return 2;
        }
        command = quoteArg(python) + L" -B " + quoteArg(script);
    }
    for (int i = 1; i < argc; ++i) {
        command += L" " + quoteArg(argv[i]);
    }
    LocalFree(argv);

    std::vector<wchar_t> commandLine(command.begin(), command.end());
    commandLine.push_back(L'\0');
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION info{};
    if (!CreateProcessW(nullptr, commandLine.data(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW,
                        nullptr, workdir.empty() ? nullptr : workdir.c_str(),
                        &startup, &info)) {
        return 2;
    }
    WaitForSingleObject(info.hProcess, INFINITE);
    DWORD code = 2;
    GetExitCodeProcess(info.hProcess, &code);
    CloseHandle(info.hThread);
    CloseHandle(info.hProcess);
    return static_cast<int>(code);
}
}  // namespace

namespace {
bool activateExistingInstance() {
    for (int attempt = 0; attempt < 100; ++attempt) {
        HWND existing = FindWindowW(L"KazariPlayHost", nullptr);
        if (existing) {
            if (IsIconic(existing)) {
                ShowWindow(existing, SW_RESTORE);
            }
            SetForegroundWindow(existing);
            return true;
        }
        Sleep(100);
    }
    return false;
}
}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    const int helperExit = runHelperIfRequested();
    if (helperExit >= 0) {
        return helperExit;
    }
    const HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(com)) {
        return 1;
    }

    HANDLE instanceMutex = CreateMutexW(nullptr, FALSE, L"Local\\KazariPlay.WinHost");
    if (!instanceMutex) {
        CoUninitialize();
        return 1;
    }
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        const bool activated = activateExistingInstance();
        CloseHandle(instanceMutex);
        CoUninitialize();
        return activated ? 0 : 1;
    }

    WebViewHost webview;
    Window window;
    if (!window.create(instance, &webview)) {
        CloseHandle(instanceMutex);
        CoUninitialize();
        return 1;
    }

    std::wstring workdir = envValue(L"KAZARIPLAY_DEV_ROOT");
    if (workdir.empty()) {
        wchar_t current[MAX_PATH]{};
        if (GetCurrentDirectoryW(MAX_PATH, current)) {
            workdir = current;
        }
    }
    std::wstring python = envValue(L"KAZARIPLAY_DEV_PYTHON");
    if (python.empty()) python = L"python";
    std::wstring script = envValue(L"KAZARIPLAY_BACKEND_SCRIPT");
    if (script.empty()) {
        script = workdir + L"\\src\\kazari_play\\backend_main.py";
    }

    BackendProcess backend;
    const auto backendHandler = [&window](const nlohmann::json& message) {
        auto* payload = new std::string(message.dump());
        if (!PostMessageW(window.hwnd(), WM_APP + 20, 0,
                          reinterpret_cast<LPARAM>(payload))) {
            delete payload;
        }
    };
    window.setBackend(&backend);
    if (!backend.start(window.hwnd(), python, script, workdir, backendHandler)) {
        MessageBoxW(window.hwnd(), L"Python backend did not start or become ready.",
                    L"KazariPlay", MB_ICONERROR);
        CloseHandle(instanceMutex);
        CoUninitialize();
        return 1;
    }
    const std::string assetRootUtf8 = backend.ready().value("asset_root", "");
    if (!webview.initialize(window.hwnd(), widenUtf8(assetRootUtf8), &backend)) {
        backend.stop();
        CloseHandle(instanceMutex);
        CoUninitialize();
        return 1;
    }
    window.show();

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    backend.stop();
    CloseHandle(instanceMutex);
    CoUninitialize();
    return static_cast<int>(message.wParam);
}
