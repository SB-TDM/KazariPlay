#pragma once

#include <windows.h>

#include <string>

struct ID2D1Factory;
struct ID2D1RenderTarget;
struct ID2D1SolidColorBrush;
struct IWICImagingFactory;
struct IWICBitmap;
struct IDWriteFactory;
struct IDWriteTextFormat;

namespace overlay {

// 底部全宽字幕窗口：Direct2D 画到 WIC 位图 → UpdateLayeredWindow 整帧上传
// （分层窗口唯一可行的画法，照抄 toast_window.cpp 的管线，见计划书 3.3）
class SubtitleWindow {
public:
    SubtitleWindow() = default;
    ~SubtitleWindow();

    bool initialize(HINSTANCE hInstance);

    // 显示字幕（先显示原文）：绑定到游戏窗口，翻译完成后用 updateTranslated 替换
    void show(HWND gameHwnd, const std::wstring& original);

    // 更新译文（AI 翻译完成后调用，替换字幕译文并重绘）
    void updateTranslated(const std::wstring& translated);

    // 设置游戏进程 PID（跟随轮询里找不到窗口时用它重新查找）
    void setGamePid(DWORD pid) { m_gamePid = pid; }

    // 隐藏字幕
    void hide();

    void shutdown();

    HWND hwnd() const { return m_hwnd; }

private:
    static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);
    LRESULT handleMessage(UINT msg, WPARAM wParam, LPARAM lParam);

    bool ensureSize(int width, int height);   // 尺寸变化时重建 WIC 位图/渲染目标
    HWND findGameWindow();                    // 按 m_gamePid 找游戏主窗口（找不到返回 nullptr）
    void render();
    void paintLayered(int x, int y);
    void releaseGraphics();
    void updatePosition();                     // 跟随：按游戏窗口当前 rect 重新定位
    void stopFollow();                         // 停止跟随 timer

    HWND m_hwnd = nullptr;
    HWND m_gameHwnd = nullptr;                 // 跟随目标（游戏主窗口）
    DWORD m_gamePid = 0;                       // 游戏进程 PID（重新查找窗口用）
    UINT_PTR m_followTimer = 0;                // 跟随轮询 timer
    int m_lastX = 0, m_lastY = 0, m_lastW = 0, m_lastH = 0;
    int m_width = 1;
    int m_height = 1;
    bool m_visible = false;

    std::wstring m_original;
    std::wstring m_translated;

    ID2D1Factory* m_d2dFactory = nullptr;
    IWICImagingFactory* m_wicFactory = nullptr;
    IDWriteFactory* m_dwriteFactory = nullptr;
    IWICBitmap* m_wicBitmap = nullptr;
    ID2D1RenderTarget* m_renderTarget = nullptr;
    ID2D1SolidColorBrush* m_bgBrush = nullptr;
    ID2D1SolidColorBrush* m_origBrush = nullptr;
    ID2D1SolidColorBrush* m_transBrush = nullptr;
    IDWriteTextFormat* m_origFormat = nullptr;
    IDWriteTextFormat* m_transFormat = nullptr;
};

}  // namespace overlay
