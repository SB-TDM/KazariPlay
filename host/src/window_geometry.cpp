#include "window.hpp"

#include <algorithm>

namespace {
constexpr int kTitlebarDip = 40;
constexpr int kButtonDip = 46;

int dip(int value, int dpi) {
    return MulDiv(value, dpi, 96);
}

bool contains(const RECT& rect, POINT point) {
    return point.x >= rect.left && point.x < rect.right
        && point.y >= rect.top && point.y < rect.bottom;
}
}  // namespace

CaptionRects captionRectsFor(RECT client, int dpi) {
    const int titlebar = dip(kTitlebarDip, dpi);
    const int button = dip(kButtonDip, dpi);
    const int right = client.right;
    CaptionRects result;
    result.titlebar = RECT{0, 0, client.right, titlebar};
    result.close = RECT{right - button, 0, right, titlebar};
    result.maximize = RECT{right - button * 2, 0, right - button, titlebar};
    result.minimize = RECT{right - button * 3, 0, right - button * 2, titlebar};
    return result;
}

LRESULT regionAt(POINT point, const CaptionRects& captions, RECT client,
                 int dpi, bool maximized) {
    if (!maximized) {
        const int border = std::max(4, dip(8, dpi));
        const bool left = point.x < border;
        const bool right = point.x >= client.right - border;
        const bool top = point.y < border;
        const bool bottom = point.y >= client.bottom - border;
        if (left && top) return HTTOPLEFT;
        if (right && top) return HTTOPRIGHT;
        if (left && bottom) return HTBOTTOMLEFT;
        if (right && bottom) return HTBOTTOMRIGHT;
        if (left) return HTLEFT;
        if (right) return HTRIGHT;
        if (top) return HTTOP;
        if (bottom) return HTBOTTOM;
    }

    if (contains(captions.close, point)) return HTCLOSE;
    if (contains(captions.maximize, point)) return HTMAXBUTTON;
    if (contains(captions.minimize, point)) return HTMINBUTTON;
    if (contains(captions.titlebar, point)) return HTCAPTION;
    return HTCLIENT;
}
