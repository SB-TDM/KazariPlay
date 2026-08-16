#include "subtitle_window.h"

#undef DrawText

#include <d2d1.h>
#include <d2d1helper.h>
#include <dwrite.h>
#include <wincodec.h>
#include <windowsx.h>   // GET_X_LPARAM / GET_Y_LPARAM

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
    wc.hCursor = LoadCursor(nullptr, IDC_SIZEALL);
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

    // 文本格式：按当前样式（默认）创建；样式变更时由 applyStyle 重建
    auto weight = static_cast<DWRITE_FONT_WEIGHT>(m_style.font_weight);
    m_dwriteFactory->CreateTextFormat(
        m_style.font.c_str(), nullptr, weight, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, m_style.font_size, L"zh-cn", &m_transFormat);
    auto origWeight = static_cast<DWRITE_FONT_WEIGHT>(
        std::max(100, static_cast<int>(m_style.font_weight * 0.7f)));
    m_dwriteFactory->CreateTextFormat(
        m_style.font.c_str(), nullptr, origWeight, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, m_style.font_size * 0.7f, L"ja-jp", &m_origFormat);

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

// 返回 rc 所在显示器的工作区边界；rc 未命中任何显示器时回退 rc 自身
RECT SubtitleWindow::monitorRectFor(const RECT& rc) const {
    HMONITOR mon = MonitorFromRect(&rc, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi = {};
    mi.cbSize = sizeof(mi);
    if (GetMonitorInfoW(mon, &mi)) {
        return mi.rcMonitor;
    }
    return rc;
}

// 按样式 + 目标 rect 计算字幕窗口几何（宽=全宽，高=内容高，位置按百分比）
void SubtitleWindow::computeGeometry(const RECT& gr, int& sx, int& sy, int& sw, int& sh) {
    sw = gr.right - gr.left;
    int gh = gr.bottom - gr.top;
    sh = static_cast<int>(contentHeight());
    if (sh < 8) sh = 8;
    if (sh > gh / 2) sh = gh / 2;   // 上限：窗口高的一半
    sx = static_cast<int>(gr.left + m_style.pos_x * sw - sw / 2.0f);
    sy = static_cast<int>(gr.top + m_style.pos_y * gh);
    if (m_style.avoid_bottom) {
        int maxSy = gr.bottom - sh - static_cast<int>(m_style.avoid_bottom_px);
        if (sy > maxSy) sy = maxSy;
    }
    if (sy < gr.top) sy = gr.top;
    // clamp 到目标显示器内（多显示器下以 gr 所在显示器为准，防止滑块拖出可视区）
    RECT mon = monitorRectFor(gr);
    int scrL = mon.left;
    int scrT = mon.top;
    int scrW = mon.right - mon.left;
    int scrH = mon.bottom - mon.top;
    sx = std::max(scrL, std::min(sx, scrL + scrW - sw));
    sy = std::max(scrT, std::min(sy, scrT + scrH - sh));
}

float SubtitleWindow::contentHeight() const {
    float origH = m_style.font_size * 0.7f * 1.35f;
    float transH = m_style.font_size * 1.35f;
    float pad = m_style.bg_mode == 2 ? 2.0f : m_style.padding;
    if (!m_style.show_source) {
        return transH + 2.0f * pad;   // 仅译文行
    }
    return origH + m_style.line_gap + transH + 2.0f * pad;
}

float SubtitleWindow::measureTextWidth(const std::wstring& text, IDWriteTextFormat* fmt,
                                       float maxW) {
    if (text.empty() || !fmt || maxW <= 0) {
        return 0.0f;
    }
    IDWriteTextLayout* layout = nullptr;
    if (FAILED(m_dwriteFactory->CreateTextLayout(
            text.c_str(), static_cast<UINT32>(text.size()), fmt, maxW, 10000.0f, &layout))) {
        return 0.0f;
    }
    DWRITE_TEXT_METRICS m = {};
    layout->GetMetrics(&m);
    layout->Release();
    return m.width;
}

void SubtitleWindow::applyWindowTransparent(bool transparent) {
    LONG_PTR ex = GetWindowLongPtrW(m_hwnd, GWL_EXSTYLE);
    if (transparent) {
        ex |= WS_EX_TRANSPARENT;
    } else {
        ex &= ~WS_EX_TRANSPARENT;
    }
    SetWindowLongPtrW(m_hwnd, GWL_EXSTYLE, ex);
}

// 目标 rect：优先游戏窗口；无则回退主显示器（预览模式也能量化定位）
RECT SubtitleWindow::resolveTargetRect() {
    RECT gr = {};
    HWND g = m_gameHwnd;
    if (g && !IsWindow(g)) {
        g = nullptr;
    }
    if (!g) {
        g = findGameWindow();
    }
    if (g && GetWindowRect(g, &gr) && gr.right > gr.left && gr.bottom > gr.top) {
        return gr;
    }
    // 无游戏窗口：以字幕窗口当前所在显示器为基准（拖拽/预览在多显示器下保持一致）
    HMONITOR mon = MonitorFromWindow(m_hwnd, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi = {};
    mi.cbSize = sizeof(mi);
    if (GetMonitorInfoW(mon, &mi)) {
        return mi.rcMonitor;
    }
    gr.left = 0;
    gr.top = 0;
    gr.right = GetSystemMetrics(SM_CXSCREEN);
    gr.bottom = GetSystemMetrics(SM_CYSCREEN);
    return gr;
}

// 按目标 rect 重新定位 + 重绘（几何无变化且非 force 时跳过）
void SubtitleWindow::reposition(const RECT& gr, bool force) {
    if (!m_visible) {
        return;
    }
    int sx, sy, sw, sh;
    computeGeometry(gr, sx, sy, sw, sh);
    const bool geomChanged = (sx != m_lastX || sy != m_lastY ||
                              sw != m_lastW || sh != m_lastH);
    if (!force && !geomChanged) {
        return;
    }
    if (!ensureSize(sw, sh)) {
        return;
    }
    render();
    paintLayered(sx, sy);
    if (geomChanged) {
        SetWindowPos(m_hwnd, HWND_TOPMOST, sx, sy, sw, sh,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
        m_lastX = sx; m_lastY = sy; m_lastW = sw; m_lastH = sh;
        LogSub("reposition: " + std::to_string(sx) + "," + std::to_string(sy) +
               " " + std::to_string(sw) + "x" + std::to_string(sh));
    }
}

void SubtitleWindow::show(HWND gameHwnd, const std::wstring& original) {
    if (!m_style.enabled) {
        return;   // 字幕总开关关闭：不显示
    }
    if (!gameHwnd) {
        gameHwnd = findGameWindow();
    }
    m_gameHwnd = gameHwnd;
    RECT gr = resolveTargetRect();
    int sx, sy, sw, sh;
    computeGeometry(gr, sx, sy, sw, sh);

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
    // 跟随游戏窗口：记录目标与当前几何，启动轮询 timer（拖拽模式不跟随）
    m_lastX = sx; m_lastY = sy; m_lastW = sw; m_lastH = sh;
    if (!m_dragMode && !m_followTimer) {
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

void SubtitleWindow::applyStyle(const std::string& styleJson) {
    m_style = ParseSubtitleStyle(styleJson);
    // 重建文本格式（字体/字号/字重可能变化）
    if (m_dwriteFactory) {
        if (m_transFormat) { m_transFormat->Release(); m_transFormat = nullptr; }
        if (m_origFormat) { m_origFormat->Release(); m_origFormat = nullptr; }
        auto weight = static_cast<DWRITE_FONT_WEIGHT>(m_style.font_weight);
        m_dwriteFactory->CreateTextFormat(
            m_style.font.c_str(), nullptr, weight, DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL, m_style.font_size, L"zh-cn", &m_transFormat);
        auto origWeight = static_cast<DWRITE_FONT_WEIGHT>(
            std::max(100, static_cast<int>(m_style.font_weight * 0.7f)));
        m_dwriteFactory->CreateTextFormat(
            m_style.font.c_str(), nullptr, origWeight, DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL, m_style.font_size * 0.7f, L"ja-jp", &m_origFormat);
    }
    LogSub("applyStyle: mode=" + std::to_string(m_style.bg_mode) +
           " size=" + std::to_string(static_cast<int>(m_style.font_size)) +
           " pos=" + std::to_string(m_style.pos_x) + "," + std::to_string(m_style.pos_y));
    // 运行中立即按新样式强制重绘（无游戏窗口时回退主显示器，预览模式同样生效）
    if (m_visible) {
        reposition(resolveTargetRect(), true);
    }
}

void SubtitleWindow::setDragMode(bool drag) {
    m_dragMode = drag;
    if (drag) {
        applyWindowTransparent(false);   // 拖拽时需要接收鼠标（去掉穿透）
        if (!m_visible) {
            showPreview();   // 无字幕时显示预览字幕供拖拽
            return;          // show 内部按 m_dragMode 不会启动跟随
        }
        stopFollow();
    } else {
        applyWindowTransparent(true);
        if (m_visible && m_gamePid && !m_followTimer) {
            m_gameHwnd = findGameWindow();
            m_followTimer = SetTimer(m_hwnd, TIMER_FOLLOW, FOLLOW_INTERVAL_MS, nullptr);
        }
    }
    LogSub(std::string("setDragMode: ") + (drag ? "on" : "off"));
}

void SubtitleWindow::showPreview() {
    // 控制面板预览：示例字幕（无游戏窗口时回退主显示器）
    show(nullptr, L"こんにちは、世界");
    updateTranslated(L"你好，世界");
}

// 跟随：游戏窗口移动/缩放后重新定位字幕（每 200ms 轮询一次几何变化）
void SubtitleWindow::updatePosition() {
    if (!m_visible || m_dragMode) {
        return;
    }
    // 跟随目标失效时，用游戏 PID 重新查找窗口（避免永久停在全屏回退位置）
    if (!m_gameHwnd || !IsWindow(m_gameHwnd)) {
        m_gameHwnd = findGameWindow();
        if (!m_gameHwnd) {
            // 日志节流：状态稳定时只记录一次，避免无游戏场景下每 200ms 刷盘
            if (!m_noWinLogged) {
                LogSub("updatePosition: no game window (pid=" +
                       std::to_string(m_gamePid) + ")");
                m_noWinLogged = true;
            }
            return;
        }
        m_noWinLogged = false;
        LogSub("updatePosition: refound game window (pid=" +
               std::to_string(m_gamePid) + ")");
    }
    RECT gr = {};
    if (!GetWindowRect(m_gameHwnd, &gr) ||
        gr.right <= gr.left || gr.bottom <= gr.top) {
        return;
    }
    reposition(gr);
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
    ID2D1RenderTarget* rt = m_renderTarget;
    rt->BeginDraw();
    rt->Clear(D2D1::ColorF(0, 0, 0, 0));   // 全透明

    const float w = static_cast<float>(m_width);
    const float pad = m_style.bg_mode == 2 ? 4.0f : m_style.padding;
    const float origH = m_style.font_size * 0.7f * 1.35f;
    const float transH = m_style.font_size * 1.35f;
    const float boardH = contentHeight();

    // 背景：无底板时不画
    if (m_style.bg_mode != 2) {
        // 测量文本宽度（仅译文时只看译文；自适应底板取最大行；通栏取全宽）
        float maxW = w * m_style.max_width;
        float origW = m_style.show_source ? measureTextWidth(m_original, m_origFormat, maxW) : 0.0f;
        float transW = measureTextWidth(m_translated, m_transFormat, maxW);
        float boardW = (m_style.bg_mode == 1)
                           ? w
                           : std::max(origW, transW) + 2.0f * pad;
        if (boardW > w) boardW = w;

        float bx = 0.0f;
        if (m_style.bg_mode == 0) {
            bx = m_style.align == 0 ? (w - boardW) / 2.0f
                                    : (m_style.align == 1 ? 0.0f : w - boardW);
        }
        D2D1_ROUNDED_RECT rr = D2D1::RoundedRect(
            D2D1::RectF(bx, 0, bx + boardW, boardH), m_style.corner, m_style.corner);

        if (m_style.gradient && boardH > 1.0f) {
            ID2D1GradientStopCollection* stops = nullptr;
            D2D1_GRADIENT_STOP gs[2] = {
                {0.0f, D2D1::ColorF(m_style.bg_r, m_style.bg_g, m_style.bg_b, m_style.bg_a)},
                {1.0f, D2D1::ColorF(m_style.grad_r, m_style.grad_g, m_style.grad_b, m_style.grad_a)}};
            if (SUCCEEDED(rt->CreateGradientStopCollection(gs, 2, &stops))) {
                ID2D1LinearGradientBrush* grad = nullptr;
                D2D1_LINEAR_GRADIENT_BRUSH_PROPERTIES lgb = D2D1::LinearGradientBrushProperties(
                    D2D1::Point2F(bx, 0), D2D1::Point2F(bx, boardH));
                if (SUCCEEDED(rt->CreateLinearGradientBrush(lgb, stops, &grad))) {
                    rt->FillRoundedRectangle(rr, grad);
                    grad->Release();
                }
                stops->Release();
            }
        } else {
            ID2D1SolidColorBrush* bg = nullptr;
            if (SUCCEEDED(rt->CreateSolidColorBrush(D2D1::ColorF(
                    m_style.bg_r, m_style.bg_g, m_style.bg_b, m_style.bg_a), &bg))) {
                rt->FillRoundedRectangle(rr, bg);
                bg->Release();
            }
        }
        // 边框
        if (m_style.border) {
            ID2D1SolidColorBrush* border = nullptr;
            if (SUCCEEDED(rt->CreateSolidColorBrush(D2D1::ColorF(
                    m_style.border_r, m_style.border_g, m_style.border_b, m_style.border_a),
                    &border))) {
                rt->DrawRoundedRectangle(rr, border, m_style.border_w);
                border->Release();
            }
        }
    }

    // 文本绘制辅助：阴影 → 描边（8 向）→ 主文本
    auto drawLine = [&](const std::wstring& text, IDWriteTextFormat* fmt,
                        const D2D1_RECT_F& rect, ID2D1Brush* brush,
                        float dx, float dy) {
        D2D1_RECT_F r = rect;
        r.left += dx; r.right += dx; r.top += dy; r.bottom += dy;
        rt->DrawText(text.c_str(), static_cast<UINT32>(text.size()), fmt, r, brush,
                     D2D1_DRAW_TEXT_OPTIONS_CLIP);
    };

    // 文本区域（窗口内）
    float textL = pad;
    float textR = w - pad;
    if (m_style.bg_mode == 0) {
        float maxW = w * m_style.max_width;
        float origW = m_style.show_source ? measureTextWidth(m_original, m_origFormat, maxW) : 0.0f;
        float transW = measureTextWidth(m_translated, m_transFormat, maxW);
        float boardW = std::max(origW, transW) + 2.0f * pad;
        if (boardW > w) boardW = w;
        float bx = m_style.align == 0 ? (w - boardW) / 2.0f
                                      : (m_style.align == 1 ? 0.0f : w - boardW);
        textL = bx + pad;
        textR = bx + boardW - pad;
    }
    // 仅译文时译文行从 pad 顶开始；含原文时译文行位于原文行下方
    D2D1_RECT_F origRect = D2D1::RectF(textL, pad, textR, pad + origH);
    float transTop = m_style.show_source ? (pad + origH + m_style.line_gap) : pad;
    D2D1_RECT_F transRect = D2D1::RectF(textL, transTop, textR, transTop + transH);

    // 对齐
    DWRITE_TEXT_ALIGNMENT align = m_style.align == 0
        ? DWRITE_TEXT_ALIGNMENT_CENTER
        : (m_style.align == 1 ? DWRITE_TEXT_ALIGNMENT_LEADING
                              : DWRITE_TEXT_ALIGNMENT_TRAILING);
    m_origFormat->SetTextAlignment(align);
    m_transFormat->SetTextAlignment(align);

    // 文字色 brush（原文字号小、透明度打折）
    ID2D1SolidColorBrush* origBrush = nullptr;
    ID2D1SolidColorBrush* transBrush = nullptr;
    rt->CreateSolidColorBrush(D2D1::ColorF(m_style.text_r, m_style.text_g, m_style.text_b,
                                           m_style.text_a * 0.65f), &origBrush);
    rt->CreateSolidColorBrush(D2D1::ColorF(m_style.text_r, m_style.text_g, m_style.text_b,
                                           m_style.text_a), &transBrush);

    // 阴影 / 描边 brush（需要时创建）
    ID2D1SolidColorBrush* shadowBrush = nullptr;
    ID2D1SolidColorBrush* outlineBrush = nullptr;
    if (m_style.shadow) {
        rt->CreateSolidColorBrush(D2D1::ColorF(m_style.shadow_r, m_style.shadow_g,
                                               m_style.shadow_b, m_style.shadow_a),
                                  &shadowBrush);
    }
    if (m_style.outline) {
        rt->CreateSolidColorBrush(D2D1::ColorF(m_style.outline_r, m_style.outline_g,
                                               m_style.outline_b, m_style.outline_a),
                                  &outlineBrush);
    }

    auto drawWithEffects = [&](const std::wstring& text, IDWriteTextFormat* fmt,
                               const D2D1_RECT_F& rect, ID2D1Brush* main) {
        if (text.empty()) {
            return;
        }
        if (shadowBrush) {
            drawLine(text, fmt, rect, shadowBrush, m_style.shadow_off, m_style.shadow_off);
        }
        if (outlineBrush) {
            float ow = m_style.outline_w;
            for (int dx = -1; dx <= 1; ++dx) {
                for (int dy = -1; dy <= 1; ++dy) {
                    if (dx == 0 && dy == 0) continue;
                    drawLine(text, fmt, rect, outlineBrush, dx * ow, dy * ow);
                }
            }
        }
        drawLine(text, fmt, rect, main, 0, 0);
    };

    if (m_style.show_source) {
        drawWithEffects(m_original, m_origFormat, origRect, origBrush);
    }
    drawWithEffects(m_translated, m_transFormat, transRect, transBrush);

    if (outlineBrush) outlineBrush->Release();
    if (shadowBrush) shadowBrush->Release();
    if (transBrush) transBrush->Release();
    if (origBrush) origBrush->Release();

    HRESULT hr = rt->EndDraw();
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
    if (m_renderTarget) m_renderTarget->Release();
    if (m_wicBitmap) m_wicBitmap->Release();
    if (m_dwriteFactory) m_dwriteFactory->Release();
    if (m_wicFactory) m_wicFactory->Release();
    if (m_d2dFactory) m_d2dFactory->Release();
    CoUninitialize();
    m_transFormat = nullptr;
    m_origFormat = nullptr;
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
        // 拖拽定位模式：按下 → 移动 → 松开回传新位置
        case WM_LBUTTONDOWN:
            if (m_dragMode) {
                m_dragging = true;
                RECT wr = {};
                GetWindowRect(m_hwnd, &wr);
                m_dragWinX = wr.left;
                m_dragWinY = wr.top;
                // 记录按下时鼠标的屏幕坐标（客户区坐标随窗口移动而变，会导致拖拽振荡）
                GetCursorPos(&m_dragStart);
                SetCapture(m_hwnd);
                return 0;
            }
            break;
        case WM_MOUSEMOVE:
            if (m_dragMode && m_dragging) {
                POINT pt = {};
                GetCursorPos(&pt);   // 用屏幕坐标计算位移，与窗口当前位置解耦
                SetWindowPos(m_hwnd, HWND_TOPMOST,
                             m_dragWinX + (pt.x - m_dragStart.x),
                             m_dragWinY + (pt.y - m_dragStart.y),
                             0, 0, SWP_NOSIZE | SWP_NOACTIVATE);
                return 0;
            }
            break;
        case WM_LBUTTONUP:
            if (m_dragMode && m_dragging) {
                m_dragging = false;
                ReleaseCapture();
                // 换算新位置百分比并回传（相对游戏窗口；无窗口用字幕窗口所在显示器）
                RECT wr = {}, gr = {};
                GetWindowRect(m_hwnd, &wr);
                HWND g = m_gameHwnd ? m_gameHwnd : findGameWindow();
                bool gotGr = g && GetWindowRect(g, &gr) && gr.right > gr.left;
                if (!gotGr) {
                    HMONITOR mon = MonitorFromWindow(m_hwnd, MONITOR_DEFAULTTONEAREST);
                    MONITORINFO mi = {};
                    mi.cbSize = sizeof(mi);
                    if (GetMonitorInfoW(mon, &mi)) gr = mi.rcMonitor;
                    else {
                        gr.left = 0; gr.top = 0;
                        gr.right = GetSystemMetrics(SM_CXSCREEN);
                        gr.bottom = GetSystemMetrics(SM_CYSCREEN);
                    }
                }
                int gw = gr.right - gr.left;
                int gh = gr.bottom - gr.top;
                if (gw > 0 && gh > 0) {
                    int sw = m_lastW;
                    float pctX = static_cast<float>(wr.left - gr.left + sw / 2) / gw;
                    float pctY = static_cast<float>(wr.top - gr.top) / gh;
                    m_style.pos_x = std::max(0.0f, std::min(1.0f, pctX));
                    m_style.pos_y = std::max(0.0f, std::min(1.0f, pctY));
                    m_lastX = wr.left;
                    m_lastY = wr.top;
                    if (m_posCb) {
                        m_posCb(m_style.pos_x, m_style.pos_y);
                    }
                }
                setDragMode(false);   // 自动退出拖拽，恢复穿透与跟随
                return 0;
            }
            break;
        case WM_DESTROY:
            stopFollow();
            return 0;
        default:
            break;
    }
    return DefWindowProcW(m_hwnd, msg, wParam, lParam);
}

}  // namespace overlay
