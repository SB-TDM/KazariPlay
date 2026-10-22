#include "webview.hpp"

#include "backend.hpp"

#include <string>
#include <windowsx.h>

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

namespace {
constexpr wchar_t kBridgeScript[] = LR"JS(
(function(){
  const host = {
    ready: true,
    _pending: new Map(),
    _seq: 0,
    invoke(name, args) {
      const id = ++this._seq;
      const promise = new Promise((resolve, reject) => {
        this._pending.set(id, {resolve, reject});
      });
      window.chrome.webview.postMessage({type:'call', id:id, method:name, args:args});
      return promise;
    },
    _settle(id, ok, value) {
      const item = this._pending.get(id);
      if (!item) return;
      this._pending.delete(id);
      if (ok) item.resolve(value);
      else item.reject(new Error(String(value && value.message || value || 'backend error')));
    }
  };
  Object.defineProperty(window, '__host', {value: host, configurable: false});
  const chunks = new Map();
  window.chrome.webview.addEventListener('message', function(event) {
    const message = event.data;
    if (!message) return;
    if (message.type === 'result') {
      host._settle(message.id, !!message.ok,
        message.ok ? message.result : message.error);
      return;
    }
    if (message.type !== 'result_chunk') return;
    let state = chunks.get(message.id);
    if (!state) {
      state = {parts: new Array(message.count), received: 0, total: message.total_bytes};
      chunks.set(message.id, state);
    }
    if (!state.parts[message.index]) state.received += 1;
    state.parts[message.index] = message.data;
    if (state.received !== message.count) return;
    chunks.delete(message.id);
    try {
      const binary = atob(state.parts.join(''));
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const inner = JSON.parse(new TextDecoder().decode(bytes));
      host._settle(inner.id, !!inner.ok,
        inner.ok ? inner.result : inner.error);
    } catch (e) {
      host._settle(message.id, false, String(e));
    }
  });
  document.addEventListener('DOMContentLoaded', function() {
    window.chrome.webview.postMessage({type:'ui_ready'});
  });
})();
)JS";

std::wstring widen(const std::string& value) {
    if (value.empty()) return {};
    const int length = MultiByteToWideChar(CP_UTF8, 0, value.data(),
                                           static_cast<int>(value.size()), nullptr, 0);
    std::wstring out(length, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                        out.data(), length);
    return out;
}

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

bool WebViewHost::initialize(HWND hwnd, const std::wstring& assetRoot,
                             BackendProcess* backend, bool navigateNow) {
    hwnd_ = hwnd;
    asset_root_ = assetRoot;
    backend_ = backend;
    navigation_ready_ = navigateNow;
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
    installBridge();
    if (!navigation_ready_ && webview_) {
        webview_->Navigate(L"about:blank");
    }
    ready_ = true;
}

void WebViewHost::loadAssets(const std::wstring& assetRoot) {
    asset_root_ = assetRoot;
    navigation_ready_ = true;
    if (script_ready_ && webview_ && !navigation_started_) {
        navigate();
    }
}

void WebViewHost::installBridge() {
    auto message_handler = Callback<ICoreWebView2WebMessageReceivedEventHandler>(
        [this](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
            LPWSTR raw = nullptr;
            if (FAILED(args->get_WebMessageAsJson(&raw)) || !raw) {
                return S_OK;
            }
            const std::wstring text(raw);
            CoTaskMemFree(raw);
            try {
                const int length = WideCharToMultiByte(
                    CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                    nullptr, 0, nullptr, nullptr);
                std::string utf8(length, '\0');
                WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                    utf8.data(), length, nullptr, nullptr);
                const auto message = nlohmann::json::parse(utf8);
                if (message.value("type", "") == "call" && backend_) {
                    backend_->sendCall(message.value("id", 0),
                                       message.value("method", ""),
                                       message.value("args", nlohmann::json::array()));
                }
            } catch (const std::exception&) {
            }
            return S_OK;
        });
    EventRegistrationToken token{};
    webview_->add_WebMessageReceived(message_handler.Get(), &token);

    auto script_handler =
        Callback<ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler>(
            [this](HRESULT, LPCWSTR) -> HRESULT {
                script_ready_ = true;
                if (navigation_ready_ && !navigation_started_) navigate();
                return S_OK;
            });
    if (FAILED(webview_->AddScriptToExecuteOnDocumentCreated(
            kBridgeScript, script_handler.Get()))) {
        script_ready_ = true;
        if (navigation_ready_ && !navigation_started_) navigate();
    }
}

void WebViewHost::navigate() {
    if (!navigation_ready_ || !webview_ || navigation_started_) {
        return;
    }
    navigation_started_ = true;
    if (asset_root_.empty()) {
        webview_->NavigateToString(kTestPage);
        return;
    }
    ComPtr<ICoreWebView2_3> webview3;
    if (FAILED(webview_.As(&webview3))
            || FAILED(webview3->SetVirtualHostNameToFolderMapping(
                L"appassets.example", asset_root_.c_str(),
                COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_ALLOW))) {
        MessageBoxW(hwnd_, L"Web asset virtual host setup failed.",
                    L"KazariPlay", MB_ICONERROR);
        return;
    }
    if (FAILED(webview_->Navigate(L"https://appassets.example/index.html"))) {
        MessageBoxW(hwnd_, L"Web asset navigation failed.",
                    L"KazariPlay", MB_ICONERROR);
    }
}

void WebViewHost::postBackendMessage(const std::string& message) {
    if (!webview_) return;
    try {
        const auto value = nlohmann::json::parse(message);
        if (value.value("type", "") == "eval") {
            const std::wstring code = widen(value.value("code", ""));
            webview_->ExecuteScript(code.c_str(), nullptr);
            return;
        }
        const std::wstring json = widen(message);
        webview_->PostWebMessageAsJson(json.c_str());
    } catch (const std::exception&) {
    }
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
