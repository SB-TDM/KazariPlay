#pragma once

#include <windows.h>

#include <functional>
#include <string>
#include <unordered_map>

namespace overlay {

using StableCallback = std::function<void(int64_t handle, const std::wstring& text)>;

// C++ 版自适应文本稳定器：基于 engine 选超时，去重 + 追加合并 + debounce。
//
// 线程模型（跨线程坑，见计划书 3.2）：
// - feed() 由 host.dll 回调线程调用：只在 CRITICAL_SECTION 内更新状态，
//   然后 PostMessage(WM_APP_STABLE_UPDATE) 通知 UI 线程，绝不在回调线程 SetTimer；
// - SetTimer/KillTimer 全部在 UI 线程（本类自建隐藏消息窗口）执行；
// - 稳定回调（一页文本显示完毕）在 UI 线程触发。
class TextStabilizer {
public:
    explicit TextStabilizer(const std::string& engine);
    ~TextStabilizer();

    // 注册稳定回调
    void setStableCallback(StableCallback cb);

    // 设置引擎（StartHook 时由管道线程调用；仅更新超时策略，线程安全）
    void setEngine(const std::string& engine);

    // 喂入一条 Hook 文本（host 线程调用，必须快速返回）
    void feed(int64_t handle, const std::wstring& text);

    // 重置（游戏切换或 Hook 点切换时；handle<0 表示全部重置）
    void reset(int64_t handle = -1);

    HWND hwnd() const { return m_hwnd; }

private:
    struct State {
        std::wstring text;
        UINT_PTR timerId = 0;
        bool pending = false;      // 已投递 WM_APP_STABLE_UPDATE（合并用）
        ULONGLONG lastFeedTick = 0;
        ULONGLONG lastLogTick = 0; // 上次写日志的时间（节流，观察用）
        int retry = 0;             // 句子未结束时已重试次数（等待完整句）
    };

    UINT selectTimeout() const;
    void onUiTimerUpdate(int64_t handle);     // UI 线程：收到通知后重置 timer
    void onTimerTick(UINT_PTR id);            // UI 线程：debounce 到期
    void resetTimer(int64_t handle, State& st);

    static UINT_PTR TimerIdOf(int64_t handle) {
        return static_cast<UINT_PTR>(handle + 1);   // 0 号 timer id 非法，+1 偏移
    }
    static int64_t HandleOf(UINT_PTR id) {
        return static_cast<int64_t>(id - 1);
    }

    static float similarity(const std::wstring& a, const std::wstring& b);

    static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);
    LRESULT handleMessage(UINT msg, WPARAM wParam, LPARAM lParam);

    std::string m_engine;
    UINT m_timeout;
    std::unordered_map<int64_t, State> m_states;
    CRITICAL_SECTION m_cs;
    StableCallback m_callback;
    HWND m_hwnd = nullptr;
    bool m_windowRegistered = false;
};

}  // namespace overlay
