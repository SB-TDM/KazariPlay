#include "webview.hpp"

#include <string>
#include <windowsx.h>

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

namespace {
constexpr wchar_t kTestPage[] = LR"HTML(
<!doctype html>
<html lang="zh-CN" data-theme="light">
<head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#ffd7e0;color:#4b2633;font:14px "Microsoft YaHei",sans-serif}
.titlebar{height:40px;display:flex;align-items:center;padding:0 16px;box-sizing:border-box;background:#ffb3c1}
.body{padding:24px}button{font:inherit;padding:8px 16px}
</style></head>
<body>
<div class="titlebar">KazariPlay WinHost input test</div>
<div class="body">
  <p>Type here, use the mouse, resize the window, and try the maximize button.</p>
  <input id="text" placeholder="keyboard / IME test"><button id="button">click me</button>
  <p id="status"></p>
</div>
<script>
const status=document.getElementById('status');
document.getElementById('button').addEventListener('click',()=>status.textContent='button clicked');
document.getElementById('text').addEventListener('input',e=>status.textContent='input: '+e.target.value);
</script>
</body></html>
)HTML";

std::wstring userDataFolder() {
    wchar_t temp[MAX_PATH]{};
    const DWORD length = GetTempPathW(MAX_PATH, temp);
    std::wstring folder = length ? std::wstring(temp, length) : L".\\";
    folder += L"KazariPlayWinHostWebView2";
    CreateDirectoryW(folder.c_str(), nullptr);
    return folder;
}

COREWEBVIEW2_MOUSE_EVENT_KIND mouseKind(UINT message) {
    switch (message) {
    case WM_MOUSEMOVE: return COREWEBVIEW2_MOUSE_EVENT_KIND_MOVE;
    case WM_LBUTTONDOWN: return COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_DOWN;
    case WM_LBUTTONUP: return COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_UP;
    case WM_LBUTTONDBLCLK: return COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_DOUBLE_CLICK;
    case WM_RBUTTONDOWN: return COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_DOWN;
    case WM_RBUTTONUP: return COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_UP;
    case WM_RBUTTONDBLCLK: return COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_DOUBLE_CLICK;
    case WM_MBUTTONDOWN: return COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_DOWN;
    case WM_MBUTTONUP: return COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_UP;
    case WM_MBUTTONDBLCLK: return COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_DOUBLE_CLICK;
    case WM_MOUSEWHEEL: return COREWEBVIEW2_MOUSE_EVENT_KIND_WHEEL;
    case WM_MOUSEHWHEEL: return COREWEBVIEW2_MOUSE_EVENT_KIND_HORIZONTAL_WHEEL;
    case WM_MOUSELEAVE: return COREWEBVIEW2_MOUSE_EVENT_KIND_LEAVE;
    default: return COREWEBVIEW2_MOUSE_EVENT_KIND_MOVE;
    }
}

}  // namespace

bool WebViewHost::initialize(HWND hwnd) {
    hwnd_ = hwnd;
    dpi_ = GetDpiForWindow(hwnd_);
    auto handler = Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
        [this](HRESULT error, ICoreWebView2Environment* environment) -> HRESULT {
            onEnvironment(error, environment);
            return S_OK;
        });
    const std::wstring folder = userDataFolder();
    const HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
        nullptr, folder.c_str(), nullptr, handler.Get());
    if (FAILED(hr)) {
        MessageBoxW(hwnd_, L"WebView2 Runtime is unavailable.", L"KazariPlay", MB_ICONERROR);
        return false;
    }
    return true;
}

void WebViewHost::onEnvironment(HRESULT error, ICoreWebView2Environment* environment) {
    if (FAILED(error) || !environment) {
        MessageBoxW(hwnd_, L"WebView2 environment initialization failed.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    environment_ = environment;
    if (FAILED(environment_->QueryInterface(
            IID_PPV_ARGS(environment3_.ReleaseAndGetAddressOf())))) {
        MessageBoxW(hwnd_, L"WebView2 composition API is unavailable.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    auto handler = Callback<ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler>(
        [this](HRESULT result, ICoreWebView2CompositionController* composition) -> HRESULT {
            onComposition(result, composition);
            return S_OK;
        });
    const HRESULT hr = environment3_->CreateCoreWebView2CompositionController(
        hwnd_, handler.Get());
    if (FAILED(hr)) {
        MessageBoxW(hwnd_, L"WebView2 composition controller creation failed.",
                    L"KazariPlay", MB_ICONERROR);
    }
}

void WebViewHost::onComposition(HRESULT error, ICoreWebView2CompositionController* composition) {
    if (FAILED(error) || !composition) {
        MessageBoxW(hwnd_, L"WebView2 composition controller initialization failed.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    composition_ = composition;
    if (FAILED(composition_->QueryInterface(
            IID_PPV_ARGS(controller_.ReleaseAndGetAddressOf())))) {
        MessageBoxW(hwnd_, L"WebView2 controller interface is unavailable.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    if (!setupVisuals()) {
        MessageBoxW(hwnd_, L"DirectComposition setup failed.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    RECT client{};
    GetClientRect(hwnd_, &client);
    controller_->put_IsVisible(TRUE);
    controller_->put_ZoomFactor(1.0);
    controller_->put_Bounds(client);
    if (FAILED(controller_->get_CoreWebView2(webview_.ReleaseAndGetAddressOf()))) {
        MessageBoxW(hwnd_, L"WebView2 interface is unavailable.", L"KazariPlay", MB_ICONERROR);
        return;
    }
    webview_->NavigateToString(kTestPage);
    ready_ = true;
}

bool WebViewHost::setupVisuals() {
    if (FAILED(DCompositionCreateDevice(
            nullptr, IID_PPV_ARGS(dcomp_device_.ReleaseAndGetAddressOf())))) {
        return false;
    }
    if (FAILED(dcomp_device_->CreateTargetForHwnd(
            hwnd_, TRUE, dcomp_target_.ReleaseAndGetAddressOf()))) {
        return false;
    }
    if (FAILED(dcomp_device_->CreateVisual(dcomp_root_.ReleaseAndGetAddressOf()))
            || FAILED(dcomp_device_->CreateVisual(dcomp_webview_.ReleaseAndGetAddressOf()))) {
        return false;
    }
    if (FAILED(dcomp_root_->AddVisual(dcomp_webview_.Get(), TRUE, nullptr))
            || FAILED(dcomp_target_->SetRoot(dcomp_root_.Get()))) {
        return false;
    }
    if (FAILED(composition_->put_RootVisualTarget(dcomp_webview_.Get()))) {
        return false;
    }
    return SUCCEEDED(dcomp_device_->Commit());
}

void WebViewHost::resize(RECT client) {
    if (controller_) {
        controller_->put_Bounds(client);
    }
}

void WebViewHost::focus() {
    if (controller_) {
        controller_->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
    }
}

void WebViewHost::setDpi(UINT dpi) {
    dpi_ = dpi;
    RECT client{};
    GetClientRect(hwnd_, &client);
    resize(client);
}

bool WebViewHost::onMouse(UINT message, WPARAM wParam, LPARAM lParam) {
    if (!ready_ || !composition_) {
        return false;
    }
    if (message != WM_MOUSELEAVE) {
        TRACKMOUSEEVENT track{};
        track.cbSize = sizeof(track);
        track.dwFlags = TME_LEAVE;
        track.hwndTrack = hwnd_;
        TrackMouseEvent(&track);
    }

    POINT point{GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
    if (message == WM_MOUSEWHEEL || message == WM_MOUSEHWHEEL) {
        ScreenToClient(hwnd_, &point);
    }
    if (message == WM_MOUSELEAVE) {
        point = POINT{0, 0};
    }
    UINT32 mouseData = 0;
    if (message == WM_MOUSEWHEEL || message == WM_MOUSEHWHEEL) {
        mouseData = static_cast<UINT32>(GET_WHEEL_DELTA_WPARAM(wParam));
    }
    if (message == WM_LBUTTONDOWN) {
        focus();
    }
    const auto keys = static_cast<COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS>(
        GET_KEYSTATE_WPARAM(wParam));
    return SUCCEEDED(composition_->SendMouseInput(
        mouseKind(message), keys, mouseData, point));
}
