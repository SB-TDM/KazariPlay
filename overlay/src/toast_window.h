#pragma once

#include <windows.h>
#include <string>

struct ID2D1Factory;
struct ID2D1RenderTarget;
struct ID2D1SolidColorBrush;
struct ID2D1Bitmap;
struct IWICImagingFactory;
struct IWICBitmap;
struct IDWriteFactory;
struct IDWriteTextFormat;

class ToastWindow {
public:
    ToastWindow() = default;
    ~ToastWindow();

    bool initialize(HINSTANCE hInstance);
    void show(HWND gameHwnd, const std::string& pngPathUtf8, const std::string& titleUtf8, int durationMs);
    void hide();
    void requestQuit();

    HWND hwnd() const { return m_hwnd; }

private:
    static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);
    LRESULT handleMessage(UINT msg, WPARAM wParam, LPARAM lParam);

    bool render(const std::wstring& pngPath, const std::wstring& title);
    bool loadThumbnail(const std::wstring& pngPath, ID2D1Bitmap** out);
    void paintLayered(int x, int y);
    void releaseGraphics();
    void handleAnimFrame();
    void setY(int y);
    void stopTimers();

    HWND m_hwnd = nullptr;
    UINT_PTR m_hideTimerId = 0;
    UINT_PTR m_animTimerId = 0;
    int m_width = 256;
    int m_height = 64;
    int m_durationMs = 3000;
    int m_x = 0;
    int m_y = 0;

    enum class AnimState { Hidden, SlideIn, Shown, SlideOut };
    AnimState m_state = AnimState::Hidden;
    ULONGLONG m_animStart = 0;
    int m_slideFromY = 0;
    int m_slideToY = 0;
    int m_hideY = 0;

    ID2D1Factory* m_d2dFactory = nullptr;
    IWICImagingFactory* m_wicFactory = nullptr;
    IDWriteFactory* m_dwriteFactory = nullptr;
    IWICBitmap* m_wicBitmap = nullptr;
    ID2D1RenderTarget* m_renderTarget = nullptr;
    ID2D1SolidColorBrush* m_bgBrush = nullptr;
    ID2D1SolidColorBrush* m_titleBrush = nullptr;
    ID2D1SolidColorBrush* m_subBrush = nullptr;
    ID2D1SolidColorBrush* m_borderBrush = nullptr;
    ID2D1SolidColorBrush* m_softBrush = nullptr;
    IDWriteTextFormat* m_titleFormat = nullptr;
    IDWriteTextFormat* m_subFormat = nullptr;
};
