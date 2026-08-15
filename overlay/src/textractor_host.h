#pragma once

#include <windows.h>

// 必须先于 host.h 包含：官方 types.h 依赖 common.h 的 AutoHandle/Synchronized
#include "common.h"

#include <atomic>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "host.h"   // 官方 Textractor host.h（third_party/textractor/）

namespace overlay {

struct HookText {
    int64_t handle = 0;        // TextThread ID
    uint64_t addr = 0;         // Hook 地址（ThreadParam.addr）
    std::string hook_name;     // Hook 名称（UTF-8）
    std::string hook_code;     // 序列化 HookParam（kzh: 格式，持久化用）
    std::wstring text;         // 提取的原文（UTF-16）
    bool internal = false;     // 内建线程消息（console/clipboard，如注入失败提示）
};

using TextCallback = std::function<void(const HookText&)>;
using CandidatesCallback = std::function<void()>;

// Textractor host 封装（静态链接 hostlib.lib，官方 v5.2.0）
//
// 线程模型（见计划书 3.1/3.2）：
// - Host::Start 必须在 UI 线程调用（内部 SetWindowsHookEx 需要消息循环线程）；
// - 文本/连接/线程回调由 host 内部线程触发，必须快速返回（只入队/通知）；
// - 本类只做转发与候选收集，稳定/翻译在 overlay 其他模块。
class TextractorHost {
public:
    TextractorHost();
    ~TextractorHost();

    // 初始化并启动 host（UI 线程调用；注册回调 + 创建管道）
    bool initialize();

    // 注入游戏进程并启动 Hook 采集（仅支持 64 位游戏；32 位返回 false）
    bool inject(DWORD pid, bool isX64);

    // 注入指定 HookCode（已保存配置的快速恢复；空 code 时进入候选收集模式）
    bool insertHook(DWORD pid, const std::string& hookCode);

    // 设置文本编码（0=引擎默认 Shift-JIS / 932 日文 / 936 简体中文 / 65001 UTF-8）
    void setCodepage(int codepage);

    // 卸载游戏进程
    bool detach(DWORD pid);

    // 注册文本回调（host 线程调用，必须快速返回）
    void setTextCallback(TextCallback cb);

    // 候选列表变化回调（host 线程调用；用于节流后回传 hook_candidates 给 Python）
    void setCandidatesCallback(CandidatesCallback cb);

    // 候选收集模式：收集所有 TextThread 的文本供用户选择
    void setCandidateMode(bool enabled);

    // 限定只处理某个 handle（用户选定 Hook 点后，同一运行内有效）
    void setSelectedHandle(int64_t handle);

    // 限定只处理某个 hook 地址（按地址过滤，跨运行稳定；addr=0 不过滤）
    void setSelectedAddress(std::uintptr_t addr);

    // 按 hook_code 设置过滤（解析其中地址；供 select_hook / 持久化恢复用）
    void setSelectedByHookCode(const std::string& code);

    // 获取当前收集的候选列表
    std::vector<HookText> candidates() const;

    // 是否已启动（initialize 成功）
    bool ready() const { return m_started.load(); }

    // 最近一次收到文本的时间（用于 30s 无输出检测）
    ULONGLONG lastTextTick() const { return m_lastTextTick.load(); }

    // 当前已连接的游戏进程（onProcessConnect 设置）
    DWORD connectedPid() const { return m_connectedPid.load(); }

    // 清理（Detach 已连接进程）
    void shutdown();

    // ---- host 回调（host 内部线程调用）----
    static void onProcessConnect(DWORD processId);
    static void onProcessDisconnect(DWORD processId);
    static void onCreateThread(TextThread& thread);
    static void onDestroyThread(TextThread& thread);
    static bool onTextOutput(TextThread& thread, std::wstring& sentence);

private:
    void dispatchText(const HookText& ht);

    // HookParam 序列化/解析（kzh: 自有格式，持久化与恢复注入用）
    static std::string serializeHookParam(const HookParam& hp);
    static bool parseHookParam(const std::string& code, HookParam& hp);

    std::atomic<bool> m_started{false};
    std::atomic<bool> m_candidateMode{false};
    std::atomic<int64_t> m_selectedHandle{-1};
    std::atomic<std::uintptr_t> m_selectedAddress{0};   // 选定 hook 地址（0=不过滤）
    std::string m_selectedFunction;   // 选定 hook 的函数名（address=0 时按它过滤；m_cs 保护）
    std::atomic<ULONGLONG> m_lastTextTick{0};
    std::atomic<DWORD> m_connectedPid{0};
    int m_codepage = 0;   // 文本编码（start_hook 设置，insertHook 时应用到 HookParam）
    TextCallback m_callback;
    CandidatesCallback m_candidatesCallback;
    mutable std::vector<HookText> m_candidates;
    mutable CRITICAL_SECTION m_cs;
    static TextractorHost* s_instance;
};

}  // namespace overlay
