#include "toast_window.h"

#include "protocol.h"

#undef DrawText

#include <d2d1.h>
#include <d2d1helper.h>
#include <dwrite.h>
#include <wincodec.h>

#include <string>

namespace {

constexpr UINT WM_APP_SHOW = WM_APP + 1;
constexpr UINT WM_APP_HIDE = WM_APP + 2;
constexpr UINT WM_APP_QUIT = WM_APP + 3;
constexpr UINT_PTR TIMER_HIDE = 1;
constexpr UINT_PTR TIMER_ANIM = 2;

constexpr int MARGIN = 8;
constexpr int PAD = 8;
constexpr int THUMB_W = 72;
constexpr int THUMB_H = 48;
constexpr int ANIM_DURATION_MS = 250;
constexpr int ANIM_INTERVAL_MS = 16;

std::wstring Utf8ToWide(const std::string& s) {
    if (s.empty()) {
        return {};
    }
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    if (n <= 0) {
        return {};
    }
    std::wstring w(static_cast<size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), &w[0], n);
    return w;
}

std::wstring TrimToLength(const std::wstring& s, size_t maxChars) {
    if (s.size() <= maxChars) {
        return s;
    }
    return s.substr(0, maxChars - 1) + L"\u2026";
}

float EaseOutCubic(float t) {
    float u = 1.0f - t;
    return 1.0f - u * u * u;
}

float EaseInQuad(float t) {
    return t * t;
}

}  // namespace

ToastWindow::~ToastWindow() {
    if (m_hwnd) {
        DestroyWindow(m_hwnd);
    }
    releaseGraphics();
}

bool ToastWindow::initialize(HINSTANCE hInstance) {
    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = &ToastWindow::wndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = L"KazariPlayOverlayToast";
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    RegisterClassExW(&wc);

    m_hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        wc.lpszClassName, L"", WS_POPUP,
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

    hr = m_wicFactory->CreateBitmap(m_width, m_height, GUID_WICPixelFormat32bppPBGRA,
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

    hr = m_renderTarget->CreateSolidColorBrush(
        D2D1::ColorF(1.0f, 0.9725f, 0.9608f, 0.96f), &m_bgBrush);
    hr = m_renderTarget->CreateSolidColorBrush(
        D2D1::ColorF(0.2902f, 0.2627f, 0.3451f, 1.0f), &m_titleBrush);
    hr = m_renderTarget->CreateSolidColorBrush(
        D2D1::ColorF(0.6118f, 0.5725f, 0.6588f, 1.0f), &m_subBrush);
    hr = m_renderTarget->CreateSolidColorBrush(
        D2D1::ColorF(1.0f, 0.5608f, 0.6706f, 1.0f), &m_borderBrush);
    hr = m_renderTarget->CreateSolidColorBrush(
        D2D1::ColorF(1.0f, 0.8431f, 0.8784f, 1.0f), &m_softBrush);

    hr = m_dwriteFactory->CreateTextFormat(
        L"Microsoft YaHei UI", nullptr, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 14.0f, L"zh-CN", &m_titleFormat);
    hr = m_dwriteFactory->CreateTextFormat(
        L"Microsoft YaHei UI", nullptr, DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 11.0f, L"zh-CN", &m_subFormat);

    return true;
}

LRESULT CALLBACK ToastWindow::wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    ToastWindow* self = nullptr;
    if (msg == WM_NCCREATE) {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        self = static_cast<ToastWindow*>(cs->lpCreateParams);
        self->m_hwnd = hwnd;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    } else {
        self = reinterpret_cast<ToastWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    }
    if (self) {
        return self->handleMessage(msg, wParam, lParam);
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

LRESULT ToastWindow::handleMessage(UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_APP_SHOW: {
            auto* sm = reinterpret_cast<protocol::ShowMessage*>(lParam);
            if (sm) {
                show(reinterpret_cast<HWND>(static_cast<UINT_PTR>(sm->hwnd)),
                     sm->path, sm->title, sm->duration_ms);
                delete sm;
            }
            return 0;
        }
        case WM_APP_HIDE:
            hide();
            return 0;
        case WM_APP_QUIT:
            requestQuit();
            return 0;
        case WM_TIMER:
            if (wParam == TIMER_ANIM) {
                handleAnimFrame();
            } else if (wParam == TIMER_HIDE) {
                hide();
            }
            return 0;
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(m_hwnd, msg, wParam, lParam);
    }
}

bool ToastWindow::loadThumbnail(const std::wstring& pngPath, ID2D1Bitmap** out) {
    IWICBitmapDecoder* decoder = nullptr;
    HRESULT hr = m_wicFactory->CreateDecoderFromFilename(
        pngPath.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &decoder);
    if (FAILED(hr)) {
        return false;
    }
    IWICBitmapFrameDecode* frame = nullptr;
    decoder->GetFrame(0, &frame);
    IWICFormatConverter* converter = nullptr;
    m_wicFactory->CreateFormatConverter(&converter);
    hr = converter->Initialize(frame, GUID_WICPixelFormat32bppPBGRA,
                               WICBitmapDitherTypeNone, nullptr, 0.0f,
                               WICBitmapPaletteTypeMedianCut);
    bool ok = SUCCEEDED(hr);
    if (ok) {
        hr = m_renderTarget->CreateBitmapFromWicBitmap(converter, nullptr, out);
        ok = SUCCEEDED(hr);
    }
    converter->Release();
    frame->Release();
    decoder->Release();
    return ok;
}

bool ToastWindow::render(const std::wstring& pngPath, const std::wstring& title) {
    if (!m_renderTarget) {
        return false;
    }
    m_renderTarget->BeginDraw();
    m_renderTarget->Clear(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.0f));

    D2D1_ROUNDED_RECT card = D2D1::RoundedRect(
        D2D1::RectF(0.0f, 0.0f, static_cast<float>(m_width), static_cast<float>(m_height)),
        12.0f, 12.0f);
    m_renderTarget->FillRoundedRectangle(card, m_bgBrush);
    m_renderTarget->DrawRoundedRectangle(card, m_borderBrush, 1.5f);

    ID2D1Bitmap* thumb = nullptr;
    if (loadThumbnail(pngPath, &thumb)) {
        D2D1_ROUNDED_RECT thumbRect = D2D1::RoundedRect(
            D2D1::RectF(static_cast<float>(PAD), static_cast<float>(PAD),
                        static_cast<float>(PAD + THUMB_W), static_cast<float>(PAD + THUMB_H)),
            8.0f, 8.0f);
        m_renderTarget->FillRoundedRectangle(thumbRect, m_softBrush);
        m_renderTarget->DrawBitmap(
            thumb,
            D2D1::RectF(static_cast<float>(PAD), static_cast<float>(PAD),
                        static_cast<float>(PAD + THUMB_W), static_cast<float>(PAD + THUMB_H)));
        thumb->Release();
    }

    float textX = static_cast<float>(PAD + THUMB_W + 10);
    m_renderTarget->DrawText(L"\u622a\u56fe\u5df2\u4fdd\u5b58", 5, m_titleFormat,
                             D2D1::RectF(textX, 13.0f, static_cast<float>(m_width - PAD),
                                         static_cast<float>(m_height - PAD)),
                             m_titleBrush, D2D1_DRAW_TEXT_OPTIONS_CLIP);
    std::wstring sub = TrimToLength(title, 22);
    m_renderTarget->DrawText(sub.c_str(), static_cast<UINT32>(sub.size()), m_subFormat,
                             D2D1::RectF(textX, 36.0f, static_cast<float>(m_width - PAD),
                                         static_cast<float>(m_height - PAD)),
                             m_subBrush, D2D1_DRAW_TEXT_OPTIONS_CLIP);

    HRESULT hr = m_renderTarget->EndDraw();
    return SUCCEEDED(hr);
}

void ToastWindow::paintLayered(int x, int y) {
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
    UpdateLayeredWindow(m_hwnd, screenDc, &ptDest, &sz, memDc, &ptSrc, 0, &blend, ULW_ALPHA);

    SelectObject(memDc, oldBmp);
    DeleteObject(hbmp);
    DeleteDC(memDc);
    ReleaseDC(nullptr, screenDc);
    lock->Release();
}

void ToastWindow::show(HWND gameHwnd, const std::string& pngPathUtf8,
                       const std::string& titleUtf8, int durationMs) {
    if (durationMs > 0) {
        m_durationMs = durationMs;
    }

    RECT gr = {};
    if (!gameHwnd || !GetWindowRect(gameHwnd, &gr) ||
        gr.right <= gr.left || gr.bottom <= gr.top) {
        return;
    }

    if (!render(Utf8ToWide(pngPathUtf8), Utf8ToWide(titleUtf8))) {
        return;
    }

    stopTimers();

    int targetX = gr.right - m_width - MARGIN;
    int targetY = gr.bottom - m_height - MARGIN;
    int startY = gr.bottom;
    m_hideY = gr.bottom;

    m_x = targetX;
    m_y = startY;
    paintLayered(targetX, startY);
    SetWindowPos(m_hwnd, HWND_TOPMOST, targetX, startY, m_width, m_height,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    ShowWindow(m_hwnd, SW_SHOWNOACTIVATE);

    m_state = AnimState::SlideIn;
    m_slideFromY = startY;
    m_slideToY = targetY;
    m_animStart = GetTickCount64();
    m_animTimerId = SetTimer(m_hwnd, TIMER_ANIM, ANIM_INTERVAL_MS, nullptr);
}

void ToastWindow::hide() {
    if (m_state != AnimState::SlideIn && m_state != AnimState::Shown) {
        return;
    }
    stopTimers();
    m_state = AnimState::SlideOut;
    m_slideFromY = m_y;
    m_slideToY = m_hideY;
    m_animStart = GetTickCount64();
    m_animTimerId = SetTimer(m_hwnd, TIMER_ANIM, ANIM_INTERVAL_MS, nullptr);
}

void ToastWindow::requestQuit() {
    stopTimers();
    ShowWindow(m_hwnd, SW_HIDE);
    DestroyWindow(m_hwnd);
}

void ToastWindow::stopTimers() {
    if (m_animTimerId) {
        KillTimer(m_hwnd, m_animTimerId);
        m_animTimerId = 0;
    }
    if (m_hideTimerId) {
        KillTimer(m_hwnd, m_hideTimerId);
        m_hideTimerId = 0;
    }
}

void ToastWindow::setY(int y) {
    m_y = y;
    SetWindowPos(m_hwnd, HWND_TOPMOST, m_x, y, m_width, m_height,
                 SWP_NOACTIVATE | SWP_NOZORDER);
}

void ToastWindow::handleAnimFrame() {
    float t = static_cast<float>(GetTickCount64() - m_animStart) / ANIM_DURATION_MS;
    if (t >= 1.0f) {
        if (m_state == AnimState::SlideIn) {
            m_state = AnimState::Shown;
            setY(m_slideToY);
            KillTimer(m_hwnd, m_animTimerId);
            m_animTimerId = 0;
            m_hideTimerId = SetTimer(m_hwnd, TIMER_HIDE, m_durationMs, nullptr);
        } else {
            m_state = AnimState::Hidden;
            ShowWindow(m_hwnd, SW_HIDE);
            KillTimer(m_hwnd, m_animTimerId);
            m_animTimerId = 0;
        }
        return;
    }

    int y;
    if (m_state == AnimState::SlideIn) {
        y = m_slideFromY + static_cast<int>((m_slideToY - m_slideFromY) * EaseOutCubic(t));
    } else {
        y = m_slideFromY + static_cast<int>((m_slideToY - m_slideFromY) * EaseInQuad(t));
    }
    setY(y);
}

void ToastWindow::releaseGraphics() {
    if (m_titleFormat) m_titleFormat->Release();
    if (m_subFormat) m_subFormat->Release();
    if (m_titleBrush) m_titleBrush->Release();
    if (m_subBrush) m_subBrush->Release();
    if (m_bgBrush) m_bgBrush->Release();
    if (m_borderBrush) m_borderBrush->Release();
    if (m_softBrush) m_softBrush->Release();
    if (m_renderTarget) m_renderTarget->Release();
    if (m_wicBitmap) m_wicBitmap->Release();
    if (m_dwriteFactory) m_dwriteFactory->Release();
    if (m_wicFactory) m_wicFactory->Release();
    if (m_d2dFactory) m_d2dFactory->Release();
    CoUninitialize();
    m_titleFormat = nullptr;
    m_subFormat = nullptr;
    m_titleBrush = nullptr;
    m_subBrush = nullptr;
    m_bgBrush = nullptr;
    m_borderBrush = nullptr;
    m_softBrush = nullptr;
    m_renderTarget = nullptr;
    m_wicBitmap = nullptr;
    m_dwriteFactory = nullptr;
    m_wicFactory = nullptr;
    m_d2dFactory = nullptr;
}
