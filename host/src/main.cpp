#include "webview.hpp"
#include "window.hpp"

#include <objbase.h>
#include <windows.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    const HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(com)) {
        return 1;
    }

    WebViewHost webview;
    Window window;
    if (!window.create(instance, &webview)) {
        CoUninitialize();
        return 1;
    }
    if (!webview.initialize(window.hwnd())) {
        CoUninitialize();
        return 1;
    }
    window.show();

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    CoUninitialize();
    return static_cast<int>(message.wParam);
}
