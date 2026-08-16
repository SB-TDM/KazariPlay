#pragma once

#include <windows.h>

#include <functional>
#include <string>

#include "subtitle_style.h"

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
// V1.2：外观/位置全部参数化（SubtitleStyle），支持控制面板实时下发与拖拽定位。
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

    // 应用字幕样式（控制面板下发 JSON；运行中立即重绘）
    void applyStyle(const std::string& styleJson);

    // 进入/退出拖拽定位模式：拖拽时窗口接受鼠标并暂停跟随，
    // 松开后回传新位置百分比给控制面板，并自动退出拖拽模式
    void setDragMode(bool drag);

    // 拖拽结束回传位置百分比（x: 字幕中心/窗口宽, y: 字幕条顶/窗口高）
    void setPositionCallback(std::function<void(float xPct, float yPct)> cb) {
        m_posCb = std::move(cb);
    }

    // 示例字幕（控制面板预览用；无游戏窗口时回退主显示器底部）
    void showPreview();

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
    void reposition(const RECT& gr, bool force = false);  // 按目标 rect 定位+重绘；force=样式变化强制重绘
    RECT resolveTargetRect();                  // 游戏窗口 rect，无则回退主显示器
    void stopFollow();                         // 停止跟随 timer

    // 按样式 + 游戏窗口 rect 计算字幕窗口几何
    void computeGeometry(const RECT& gr, int& sx, int& sy, int& sw, int& sh);
    RECT monitorRectFor(const RECT& rc) const;   // rc 所在显示器边界（多显示器换算/钳制基准）
    float contentHeight() const;               // 按样式估算内容高度（原文行+间距+译文行+内边距）

    // 文本宽度测量（DWrite layout）
    float measureTextWidth(const std::wstring& text, IDWriteTextFormat* fmt, float maxW);

    void applyWindowTransparent(bool transparent);  // 切换鼠标穿透（WS_EX_TRANSPARENT）

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

    SubtitleStyle m_style;                     // 当前样式（默认 = 原主题）
    bool m_dragMode = false;                   // 拖拽定位模式
    bool m_dragging = false;                   // 正在拖拽
    POINT m_dragStart = {};                    // 拖拽按下位置（屏幕坐标）
    int m_dragWinX = 0, m_dragWinY = 0;        // 按下时窗口位置
    std::function<void(float, float)> m_posCb; // 拖拽结束回传
    bool m_noWinLogged = false;                // 无游戏窗口日志节流标志

    ID2D1Factory* m_d2dFactory = nullptr;
    IWICImagingFactory* m_wicFactory = nullptr;
    IDWriteFactory* m_dwriteFactory = nullptr;
    IWICBitmap* m_wicBitmap = nullptr;
    ID2D1RenderTarget* m_renderTarget = nullptr;
    IDWriteTextFormat* m_origFormat = nullptr;
    IDWriteTextFormat* m_transFormat = nullptr;
};

}  // namespace overlay
