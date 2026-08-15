#include "subtitle_window.h"

#undef DrawText

#include <d2d1.h>
#include <d2d1helper.h>
#include <dwrite.h>
#include <wincodec.h>

#include <algorithm>
#include <string>

namespace overlay {

namespace {
constexpr wchar_t kClassName[] = L"KazariPlaySubtitle";
constexpr UINT_PTR TIMER_FOLLOW = 0x6001;   // 跟随游戏窗口轮询（200ms）
constexpr UINT FOLLOW_INTERVAL_MS = 200;

// 轻量调试日志（与 main.cpp LogToFile 相同实现，独立副本）
void LogSub(const std::string& msg) {
    wchar_t exePath[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    std::wstring p(exePath);
    auto pos = p.find_last_of(L"\\/");
    std::wstring dir = pos == std::wstring::npos ? L"." : p.substr(0, pos);
    std::wstring logPath = dir + L"\\debug.log";
    FILE* f = nullptr;
    if (_wfopen_s(&f, logPath.c_str(), L"ab") == 0 && f) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        char line[512];
        std::snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u] [sub] %s\n",
                      st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg.c_str());
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}
}  // namespace

SubtitleWindow::~SubtitleWindow() {
    shutdown();
}

bool SubtitleWindow::initialize(HINSTANCE hInstance) {
    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = &SubtitleWindow::wndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = kClassName;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    RegisterClassExW(&wc);

    // 与 toast 相同：分层 + 透明穿透 + 置顶 + 不激活
    m_hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        kClassName, L"", WS_POPUP,
        0, 0, m_width, m_height, nullptr, nullptr, hInstance, this);
    if (!m_hwnd) {
        return false;
    }

    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hr)) {
        return false;
    }
    hr = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &m_d2dFactory);
    if (FAILED(hr)) {
        return false;
    }
    hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                          IID_PPV_ARGS(&m_wicFactory));
    if (FAILED(hr)) {
        return false;
    }
    hr = DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                             reinterpret_cast<IUnknown**>(&m_dwriteFactory));
    if (FAILED(hr)) {
        return false;
    }

    // 字体：日文 MS Gothic（显示完整），中文 Microsoft YaHei UI
    m_dwriteFactory->CreateTextFormat(
        L"MS Gothic", nullptr, DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 15.0f, L"ja-jp", &m_origFormat);
    m_dwriteFactory->CreateTextFormat(
        L"Microsoft YaHei UI", nullptr, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 22.0f, L"zh-cn", &m_transFormat);

    return ensureSize(m_width, m_height);
}

bool SubtitleWindow::ensureSize(int width, int height) {
    if (m_renderTarget && width == m_width && height == m_height) {
        return true;
    }
    // 释放旧的位图/渲染目标，按新尺寸重建
    if (m_renderTarget) {
        m_renderTarget->Release();
        m_renderTarget = nullptr;
    }
    if (m_wicBitmap) {
        m_wicBitmap->Release();
        m_wicBitmap = nullptr;
    }
    m_width = width;
    m_height = height;

    HRESULT hr = m_wicFactory->CreateBitmap(
        m_width, m_height, GUID_WICPixelFormat32bppPBGRA,
        WICBitmapCacheOnLoad, &m_wicBitmap);
    if (FAILED(hr)) {
        return false;
    }
    D2D1_RENDER_TARGET_PROPERTIES props = D2D1::RenderTargetProperties(
        D2D1_RENDER_TARGET_TYPE_DEFAULT,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED),
        0.0f, 0.0f, D2D1_RENDER_TARGET_USAGE_NONE, D2D1_FEATURE_LEVEL_DEFAULT);
    hr = m_d2dFactory->CreateWicBitmapRenderTarget(m_wicBitmap, props, &m_renderTarget);
    if (FAILED(hr)) {
        return false;
    }

    // 半透明黑背景（alpha≈0.72），原文半透明白，译文纯白
    if (!m_bgBrush) {
        m_renderTarget->CreateSolidColorBrush(
            D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.72f), &m_bgBrush);
    }
    if (!m_origBrush) {
        m_renderTarget->CreateSolidColorBrush(
            D2D1::ColorF(1.0f, 1.0f, 1.0f, 0.65f), &m_origBrush);
    }
    if (!m_transBrush) {
        m_renderTarget->CreateSolidColorBrush(
            D2D1::ColorF(1.0f, 1.0f, 1.0f, 1.0f), &m_transBrush);
    }
    return true;
}

HWND SubtitleWindow::findGameWindow() {
    if (!m_gamePid) {
        return nullptr;
    }
    struct EnumCtx { DWORD pid; HWND hwnd; };
    EnumCtx ctx{m_gamePid, nullptr};
    ::EnumWindows([](HWND hwnd, LPARAM lParam) -> BOOL {
        auto* c = reinterpret_cast<EnumCtx*>(lParam);
        DWORD pid = 0;
        GetWindowThreadProcessId(hwnd, &pid);
        if (pid != c->pid) return TRUE;
        if (!IsWindowVisible(hwnd)) return TRUE;
        if (GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW) return TRUE;
        c->hwnd = hwnd;
        return FALSE;
    }, reinterpret_cast<LPARAM>(&ctx));
    return ctx.hwnd;
}

void SubtitleWindow::show(HWND gameHwnd, const std::wstring& original) {
    if (!gameHwnd) {
        gameHwnd = findGameWindow();
    }
    RECT gr = {};
    bool ok = gameHwnd && GetWindowRect(gameHwnd, &gr) &&
              gr.right > gr.left && gr.bottom > gr.top;
    if (!ok) {
        LogSub("show: no game window (pid=" + std::to_string(m_gamePid) +
               "), fallback to primary monitor");
        // 找不到游戏窗口（未 start_hook 或窗口已关）：回退到主显示器底部
        POINT pt = {0, 0};
        HMONITOR mon = MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY);
        MONITORINFO mi = {};
        mi.cbSize = sizeof(mi);
        if (GetMonitorInfoW(mon, &mi)) {
            gr = mi.rcMonitor;
        } else {
            gr.left = 0; gr.top = 0;
            gr.right = GetSystemMetrics(SM_CXSCREEN);
            gr.bottom = GetSystemMetrics(SM_CYSCREEN);
        }
    }
    int gw = gr.right - gr.left;
    int gh = gr.bottom - gr.top;
    int sw = gw;
    int sh = std::max(1, gh / 5);            // 高度 = 高度 / 5
    int sx = gr.left;
    int sy = gr.bottom - sh;

    if (!ensureSize(sw, sh)) {
        LogSub("show: ensureSize FAIL");
        return;
    }
    m_original = original;
    m_translated.clear();                    // 先只显示原文，翻译完成后替换
    render();
    paintLayered(sx, sy);
    SetWindowPos(m_hwnd, HWND_TOPMOST, sx, sy, sw, sh,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    ShowWindow(m_hwnd, SW_SHOWNOACTIVATE);
    m_visible = true;
    // 跟随游戏窗口：记录目标与当前几何，启动轮询 timer
    m_gameHwnd = gameHwnd;
    m_lastX = sx; m_lastY = sy; m_lastW = sw; m_lastH = sh;
    if (!m_followTimer) {
        m_followTimer = SetTimer(m_hwnd, TIMER_FOLLOW, FOLLOW_INTERVAL_MS, nullptr);
    }
    LogSub("show: ok size=" + std::to_string(sw) + "x" + std::to_string(sh) +
           " pos=" + std::to_string(sx) + "," + std::to_string(sy));
}

void SubtitleWindow::updateTranslated(const std::wstring& translated) {
    if (!m_visible) {
        return;
    }
    m_translated = translated;
    render();
    paintLayered(m_lastX, m_lastY);
    LogSub("updateTranslated: ok");
}

void SubtitleWindow::hide() {
    if (m_visible) {
        ShowWindow(m_hwnd, SW_HIDE);
        m_visible = false;
    }
    stopFollow();
}

void SubtitleWindow::stopFollow() {
    if (m_followTimer) {
        KillTimer(m_hwnd, m_followTimer);
        m_followTimer = 0;
    }
    m_gameHwnd = nullptr;
}

// 跟随：游戏窗口移动/缩放后重新定位字幕（每 200ms 轮询一次几何变化）
void SubtitleWindow::updatePosition() {
    if (!m_visible) {
        return;
    }
    // 跟随目标失效时，用游戏 PID 重新查找窗口（避免永久停在全屏回退位置）
    if (!m_gameHwnd || !IsWindow(m_gameHwnd)) {
        m_gameHwnd = findGameWindow();
        if (!m_gameHwnd) {
            LogSub("updatePosition: findGameWindow null (pid=" +
                   std::to_string(m_gamePid) + ")");
            return;
        }
        LogSub("updatePosition: refound game window (pid=" +
               std::to_string(m_gamePid) + ")");
    }
    RECT gr = {};
    if (!GetWindowRect(m_gameHwnd, &gr) ||
        gr.right <= gr.left || gr.bottom <= gr.top) {
        return;
    }
    int gw = gr.right - gr.left;
    int gh = gr.bottom - gr.top;
    int sw = gw;
    int sh = std::max(1, gh / 5);
    int sx = gr.left;
    int sy = gr.bottom - sh;
    if (sx == m_lastX && sy == m_lastY && sw == m_lastW && sh == m_lastH) {
        return;   // 未变化
    }
    if (!ensureSize(sw, sh)) {
        return;
    }
    render();
    paintLayered(sx, sy);
    SetWindowPos(m_hwnd, HWND_TOPMOST, sx, sy, sw, sh,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    m_lastX = sx; m_lastY = sy; m_lastW = sw; m_lastH = sh;
    LogSub("follow: reposition to " + std::to_string(sx) + "," + std::to_string(sy) +
           " " + std::to_string(sw) + "x" + std::to_string(sh));
}

void SubtitleWindow::shutdown() {
    if (m_hwnd) {
        DestroyWindow(m_hwnd);
        m_hwnd = nullptr;
    }
    releaseGraphics();
}

void SubtitleWindow::render() {
    if (!m_renderTarget) {
        return;
    }
    m_renderTarget->BeginDraw();
    m_renderTarget->Clear(D2D1::ColorF(0, 0, 0, 0));   // 全透明

    float w = static_cast<float>(m_width);
    float h = static_cast<float>(m_height);

    // 半透明黑色背景
    m_renderTarget->FillRectangle(D2D1::RectF(0, 0, w, h), m_bgBrush);

    float pad = w / 40.0f;
    float midY = h / 2.0f;

    // 日文原文（上半，小字，半透明）
    D2D1_RECT_F origRect = D2D1::RectF(pad, h * 0.1f, w - pad, midY - 4);
    m_origFormat->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER);
    m_renderTarget->DrawText(
        m_original.c_str(), static_cast<UINT32>(m_original.size()),
        m_origFormat, origRect, m_origBrush, D2D1_DRAW_TEXT_OPTIONS_CLIP);

    // 中文译文（下半，大字，白色）
    D2D1_RECT_F transRect = D2D1::RectF(pad, midY + 4, w - pad, h - h * 0.1f);
    m_transFormat->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER);
    m_renderTarget->DrawText(
        m_translated.c_str(), static_cast<UINT32>(m_translated.size()),
        m_transFormat, transRect, m_transBrush, D2D1_DRAW_TEXT_OPTIONS_CLIP);

    HRESULT hr = m_renderTarget->EndDraw();
    if (FAILED(hr)) {
        LogSub("render: EndDraw FAILED hr=0x" + std::to_string(static_cast<unsigned long>(hr)));
    }
}

void SubtitleWindow::paintLayered(int x, int y) {
    // 与 toast_window.cpp::paintLayered 相同：WIC 位图 Lock → DIB → UpdateLayeredWindow
    WICRect rc = {0, 0, m_width, m_height};
    IWICBitmapLock* lock = nullptr;
    if (FAILED(m_wicBitmap->Lock(&rc, WICBitmapLockRead, &lock))) {
        return;
    }
    UINT bufferSize = 0;
    BYTE* data = nullptr;
    lock->GetDataPointer(&bufferSize, &data);
    UINT stride = 0;
    lock->GetStride(&stride);

    HDC screenDc = GetDC(nullptr);
    BITMAPINFO bmi = {};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = m_width;
    bmi.bmiHeader.biHeight = -m_height;
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    void* bits = nullptr;
    HBITMAP hbmp = CreateDIBSection(screenDc, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (hbmp && bits) {
        memcpy(bits, data, bufferSize);
    }
    HDC memDc = CreateCompatibleDC(screenDc);
    HGDIOBJ oldBmp = SelectObject(memDc, hbmp);

    POINT ptDest = {x, y};
    POINT ptSrc = {0, 0};
    SIZE sz = {m_width, m_height};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    BOOL ok = UpdateLayeredWindow(m_hwnd, screenDc, &ptDest, &sz, memDc, &ptSrc, 0, &blend, ULW_ALPHA);
    if (!ok) {
        LogSub("paintLayered: UpdateLayeredWindow FAILED err=" +
               std::to_string(static_cast<unsigned long>(GetLastError())));
    } else {
        LogSub("paintLayered: ok " + std::to_string(m_width) + "x" + std::to_string(m_height));
    }

    SelectObject(memDc, oldBmp);
    DeleteObject(hbmp);
    DeleteDC(memDc);
    ReleaseDC(nullptr, screenDc);
    lock->Release();
}

void SubtitleWindow::releaseGraphics() {
    if (m_transFormat) m_transFormat->Release();
    if (m_origFormat) m_origFormat->Release();
    if (m_transBrush) m_transBrush->Release();
    if (m_origBrush) m_origBrush->Release();
    if (m_bgBrush) m_bgBrush->Release();
    if (m_renderTarget) m_renderTarget->Release();
    if (m_wicBitmap) m_wicBitmap->Release();
    if (m_dwriteFactory) m_dwriteFactory->Release();
    if (m_wicFactory) m_wicFactory->Release();
    if (m_d2dFactory) m_d2dFactory->Release();
    CoUninitialize();
    m_transFormat = nullptr;
    m_origFormat = nullptr;
    m_transBrush = nullptr;
    m_origBrush = nullptr;
    m_bgBrush = nullptr;
    m_renderTarget = nullptr;
    m_wicBitmap = nullptr;
    m_dwriteFactory = nullptr;
    m_wicFactory = nullptr;
    m_d2dFactory = nullptr;
}

LRESULT CALLBACK SubtitleWindow::wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    SubtitleWindow* self = nullptr;
    if (msg == WM_NCCREATE) {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        self = static_cast<SubtitleWindow*>(cs->lpCreateParams);
        self->m_hwnd = hwnd;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    } else {
        self = reinterpret_cast<SubtitleWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    }
    if (self) {
        return self->handleMessage(msg, wParam, lParam);
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

LRESULT SubtitleWindow::handleMessage(UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_TIMER:
            if (wParam == TIMER_FOLLOW) {
                updatePosition();
            }
            return 0;
        case WM_DESTROY:
            stopFollow();
            return 0;
        default:
            return DefWindowProcW(m_hwnd, msg, wParam, lParam);
    }
}

}  // namespace overlay
