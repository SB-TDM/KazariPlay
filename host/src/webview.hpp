#pragma once

#include <windows.h>

#include <string>

#include <dcomp.h>
#include "json.hpp"
#include <wrl/client.h>
#include <wrl/event.h>

#include "WebView2.h"

class BackendProcess;

class WebViewHost {
public:
    bool initialize(HWND hwnd, const std::wstring& assetRoot, BackendProcess* backend);
    void resize(RECT client);
    void focus();
    void setDpi(UINT dpi);
    bool onMouse(UINT message, WPARAM wParam, LPARAM lParam);
    void postBackendMessage(const std::string& message);
    bool ready() const { return ready_; }

private:
    void onEnvironment(HRESULT error, ICoreWebView2Environment* environment);
    void onComposition(HRESULT error, ICoreWebView2CompositionController* composition);
    bool setupVisuals();
    void navigate();
    void installBridge();

    HWND hwnd_ = nullptr;
    std::wstring asset_root_;
    BackendProcess* backend_ = nullptr;
    UINT dpi_ = 96;
    bool ready_ = false;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment> environment_;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment3> environment3_;
    Microsoft::WRL::ComPtr<ICoreWebView2CompositionController> composition_;
    Microsoft::WRL::ComPtr<ICoreWebView2Controller> controller_;
    Microsoft::WRL::ComPtr<ICoreWebView2> webview_;
    Microsoft::WRL::ComPtr<IDCompositionDevice> dcomp_device_;
    Microsoft::WRL::ComPtr<IDCompositionTarget> dcomp_target_;
    Microsoft::WRL::ComPtr<IDCompositionVisual> dcomp_root_;
    Microsoft::WRL::ComPtr<IDCompositionVisual> dcomp_webview_;
    bool tracking_leave_ = false;
};
