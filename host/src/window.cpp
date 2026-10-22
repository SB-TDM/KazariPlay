#include "window.hpp"

#include "backend.hpp"
#include "dialog.hpp"
#include "webview.hpp"

#include <algorithm>
#include <dwmapi.h>
#include <windowsx.h>

namespace {
constexpr wchar_t kClassName[] = L"KazariPlayHost";
constexpr UINT kBackendMessage = WM_APP + 20;

int dip(int value, int dpi) {
    return MulDiv(value, dpi, 96);
}

}  // namespace

bool Window::create(HINSTANCE instance, WebViewHost* webview) {
    webview_ = webview;
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = instance;
    wc.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(101));
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = nullptr;
    wc.lpszClassName = kClassName;
    if (!RegisterClassExW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
        return false;
    }

    MONITORINFO monitor{};
    monitor.cbSize = sizeof(monitor);
    GetMonitorInfoW(MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY), &monitor);
    const int workWidth = monitor.rcWork.right - monitor.rcWork.left;
    const int workHeight = monitor.rcWork.bottom - monitor.rcWork.top;
    const int width = std::max(900, MulDiv(workWidth, 82, 100));
    const int height = std::max(620, MulDiv(workHeight, 82, 100));
    const int x = monitor.rcWork.left + (workWidth - width) / 2;
    const int y = monitor.rcWork.top + (workHeight - height) / 2;

    hwnd_ = CreateWindowExW(
        0, kClassName, L"KazariPlay WinHost",
        WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU,
        x, y, width, height, nullptr, nullptr, instance, this);
    if (!hwnd_) {
        return false;
    }
    dpi_ = GetDpiForWindow(hwnd_);
    onSize();
    return true;
}

void Window::show() {
    ShowWindow(hwnd_, SW_SHOW);
    UpdateWindow(hwnd_);
    SetFocus(hwnd_);
}

void Window::setCaptionRects(const CaptionRects& rects) {
    captions_ = rects;
}

void Window::applyDpi(UINT dpi) {
    dpi_ = dpi;
    onSize();
}

void Window::onBackendPayload(const std::string& payload) {
    try {
        const auto message = nlohmann::json::parse(payload);
        if (message.value("type", "") == "dialog" && backend_) {
            backend_->sendDialogResult(showFileDialog(hwnd_, message));
            return;
        }
    } catch (const std::exception&) {
    }
    if (webview_) {
        webview_->postBackendMessage(payload);
    }
}

void Window::onSize() {
    if (!hwnd_) return;
    RECT client{};
    GetClientRect(hwnd_, &client);
    captions_ = captionRectsFor(client, static_cast<int>(dpi_));
    if (webview_) {
        webview_->resize(client);
    }
}

void Window::onDpiChanged(UINT dpi, const RECT& suggested) {
    dpi_ = dpi;
    SetWindowPos(hwnd_, nullptr, suggested.left, suggested.top,
                 suggested.right - suggested.left, suggested.bottom - suggested.top,
                 SWP_NOZORDER | SWP_NOACTIVATE);
    onSize();
    if (webview_) {
        webview_->setDpi(dpi);
    }
}

LRESULT CALLBACK Window::WndProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
    Window* self = reinterpret_cast<Window*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(lParam);
        self = reinterpret_cast<Window*>(create->lpCreateParams);
        self->hwnd_ = hwnd;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    }
    if (self) {
        return self->handleMessage(message, wParam, lParam);
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

LRESULT Window::handleMessage(UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
    case WM_CREATE: {
        MARGINS margins{-1, -1, -1, -1};
        DwmExtendFrameIntoClientArea(hwnd_, &margins);
        return 0;
    }
    case WM_NCCALCSIZE:
        if (wParam) {
            auto* params = reinterpret_cast<NCCALCSIZE_PARAMS*>(lParam);
            if (maximized_) {
                MONITORINFO monitor{};
                monitor.cbSize = sizeof(monitor);
                GetMonitorInfoW(MonitorFromWindow(hwnd_, MONITOR_DEFAULTTONEAREST), &monitor);
                params->rgrc[0] = monitor.rcWork;
            }
            return 0;
        }
        break;
    case WM_NCHITTEST: {
        POINT point{GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
        ScreenToClient(hwnd_, &point);
        RECT client{};
        GetClientRect(hwnd_, &client);
        return regionAt(point, captions_, client, static_cast<int>(dpi_), maximized_);
    }
    case WM_GETMINMAXINFO: {
        auto* info = reinterpret_cast<MINMAXINFO*>(lParam);
        info->ptMinTrackSize.x = dip(900, static_cast<int>(dpi_));
        info->ptMinTrackSize.y = dip(620, static_cast<int>(dpi_));
        return 0;
    }
    case WM_SIZE:
        maximized_ = IsZoomed(hwnd_) != FALSE;
        onSize();
        return 0;
    case WM_DPICHANGED:
        onDpiChanged(LOWORD(wParam), *reinterpret_cast<RECT*>(lParam));
        return 0;
    case WM_SETFOCUS:
        if (webview_) webview_->focus();
        return 0;
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MBUTTONDBLCLK:
    case WM_MOUSEWHEEL:
    case WM_MOUSEHWHEEL:
        if (webview_ && webview_->onMouse(message, wParam, lParam)) {
            if (message == WM_LBUTTONDOWN) SetCapture(hwnd_);
            if (message == WM_LBUTTONUP) ReleaseCapture();
            return 0;
        }
        break;
    case WM_MOUSELEAVE:
        if (webview_) webview_->onMouse(message, wParam, lParam);
        return 0;
    case kBackendMessage: {
        auto* payload = reinterpret_cast<std::string*>(lParam);
        if (payload) {
            onBackendPayload(*payload);
            delete payload;
        }
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT: {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(hwnd_, &paint);
        RECT client{};
        GetClientRect(hwnd_, &client);
        HBRUSH brush = CreateSolidBrush(RGB(255, 215, 224));
        FillRect(dc, &client, brush);
        DeleteObject(brush);
        EndPaint(hwnd_, &paint);
        return 0;
    }
    case WM_CLOSE:
        DestroyWindow(hwnd_);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        break;
    }
    return DefWindowProcW(hwnd_, message, wParam, lParam);
}
