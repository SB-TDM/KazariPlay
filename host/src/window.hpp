#pragma once

#include <windows.h>

class WebViewHost;

struct CaptionRects {
    RECT titlebar{};
    RECT minimize{};
    RECT maximize{};
    RECT close{};
};

LRESULT regionAt(POINT client, const CaptionRects& captions, RECT clientRect,
                 int dpi, bool maximized);
CaptionRects captionRectsFor(RECT clientRect, int dpi);

class Window {
public:
    bool create(HINSTANCE instance, WebViewHost* webview);
    void show();
    HWND hwnd() const { return hwnd_; }
    void setCaptionRects(const CaptionRects& rects);
    bool isMaximized() const { return maximized_; }
    void applyDpi(UINT dpi);

private:
    static LRESULT CALLBACK WndProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam);
    LRESULT handleMessage(UINT message, WPARAM wParam, LPARAM lParam);
    void onSize();
    void onDpiChanged(UINT dpi, const RECT& suggested);

    HWND hwnd_ = nullptr;
    WebViewHost* webview_ = nullptr;
    CaptionRects captions_{};
    UINT dpi_ = 96;
    bool maximized_ = false;
};
