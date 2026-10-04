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
    const auto start = arg.find_first_not_of(" \t");
    if (start == std::string::npos) {
        return "KazariPlayOverlay";
    }
    const auto end = arg.find_last_not_of(" \t");
    return arg.substr(start, end - start + 1);
}

}  // namespace

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR lpCmdLine, int) {
    EnableDpiAwareness();
    ToastWindow toast;
    if (!toast.initialize(hInstance)) {
        return 1;
    }

    PipeServer server(PipeNameFromArg(lpCmdLine ? lpCmdLine : ""),
                      [&toast](const std::string& message) {
        const auto cmd = protocol::parseCommand(message);
        switch (cmd.type) {
            case protocol::MsgType::Show: {
                auto* payload = new protocol::ShowMessage(cmd.show);
                if (!PostMessageW(toast.hwnd(), WM_APP_SHOW, 0,
                                  reinterpret_cast<LPARAM>(payload))) {
                    delete payload;
                }
                break;
            }
            case protocol::MsgType::Hide:
                PostMessageW(toast.hwnd(), WM_APP_HIDE, 0, 0);
                break;
            case protocol::MsgType::Quit:
                PostMessageW(toast.hwnd(), WM_APP_QUIT, 0, 0);
                break;
            default:
                break;
        }
    });
    server.setOnDisconnect([&toast]() {
        PostMessageW(toast.hwnd(), WM_APP_QUIT, 0, 0);
    });
    if (!server.start()) {
        return 1;
    }

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    server.stop();
    return 0;
}
