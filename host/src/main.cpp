#include "webview.hpp"
#include "window.hpp"

#include <iterator>
#include <objbase.h>
#include <windows.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    const HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(com)) {
        return 1;
    }

    wchar_t assetRoot[MAX_PATH * 4]{};
    GetEnvironmentVariableW(L"KAZARIPLAY_ASSET_ROOT", assetRoot,
                            static_cast<DWORD>(std::size(assetRoot)));

    WebViewHost webview;
    Window window;
    if (!window.create(instance, &webview)) {
        CoUninitialize();
        return 1;
    }
    if (!webview.initialize(window.hwnd(), assetRoot)) {
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
