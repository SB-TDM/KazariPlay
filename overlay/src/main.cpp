#include <windows.h>

#include <string>

#include "pipe_server.h"
#include "protocol.h"
#include "toast_window.h"

namespace {

constexpr UINT WM_APP_SHOW = WM_APP + 1;
constexpr UINT WM_APP_HIDE = WM_APP + 2;
constexpr UINT WM_APP_QUIT = WM_APP + 3;

void EnableDpiAwareness() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32) {
        using SetProcessDpiAwarenessContextFn = BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT);
        auto fn = reinterpret_cast<SetProcessDpiAwarenessContextFn>(
            GetProcAddress(user32, "SetProcessDpiAwarenessContext"));
        if (fn) {
            fn(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        }
    }
}

std::string PipeNameFromArg(const std::string& arg) {
    if (arg.empty()) {
        return "KazariPlayOverlay";
    }
    auto pos = arg.find_first_not_of(" \t");
    if (pos == std::string::npos) {
        return "KazariPlayOverlay";
    }
    auto end = arg.find_last_not_of(" \t");
    return arg.substr(pos, end - pos + 1);
}

}  // namespace

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR lpCmdLine, int) {
    EnableDpiAwareness();

    ToastWindow toast;
    if (!toast.initialize(hInstance)) {
        return 1;
    }

    std::string pipeName = PipeNameFromArg(lpCmdLine ? lpCmdLine : "");

    PipeServer server(pipeName, [&toast](const std::string& msg) {
        protocol::ShowMessage sm;
        protocol::MsgType type = protocol::parse(msg, sm);
        switch (type) {
            case protocol::MsgType::Show: {
                auto* p = new protocol::ShowMessage(sm);
                PostMessageW(toast.hwnd(), WM_APP_SHOW, 0, reinterpret_cast<LPARAM>(p));
                break;
            }
            case protocol::MsgType::Hide:
                PostMessageW(toast.hwnd(), WM_APP_HIDE, 0, 0);
                break;
            case protocol::MsgType::Quit:
                PostMessageW(toast.hwnd(), WM_APP_QUIT, 0, 0);
                break;
            case protocol::MsgType::Ping:
            case protocol::MsgType::Unknown:
            default:
                break;
        }
    });
    server.start();

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
