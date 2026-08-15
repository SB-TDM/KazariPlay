#include "text_stabilizer.h"

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <vector>

namespace overlay {

namespace {
constexpr UINT WM_APP_STABLE_UPDATE = WM_APP + 0x50;
constexpr float kSimilarityThreshold = 0.85f;
constexpr wchar_t kClassName[] = L"KazariPlayTextStabilizer";
constexpr ULONGLONG kStabLogInterval = 200;   // 观察日志节流（ms），避免刷爆
constexpr int kMaxSentenceRetry = 8;          // 长句未明确结束时最多再等几轮（等完整句）

// 判断文本是否以"明确结束标点"结尾（避免把渲染中途的不完整句 flush 出去）。
// 半角标点（. ! ?）、空格、省略号等常出现在句子中间（如 "·····. !"），
// 不视为明确结束——让稳定器再等一轮，等完整句到达。
bool IsSentenceEnd(const std::wstring& t) {
    if (t.empty()) return true;
    const wchar_t c = t.back();
    if (c == L'。' || c == L'！' || c == L'？' || c == L'」' || c == L'』' ||
        c == L'）' || c == L'…' || c == L'\n' || c == L'\r') {
        return true;   // 全角标点/引号：明确结束
    }
    return false;      // 半角标点、空格、无标点 → 不明确，再等
}

// 观察日志：写入 overlay/bin(|bin32)/debug.log（与 main.cpp LogToFile 同路径）
void LogStab(const std::string& msg) {
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
        char line[2048];
        std::snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u] [stab] %s\n",
                      st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg.c_str());
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}

std::wstring TruncateW(const std::wstring& s, size_t max) {
    if (s.size() <= max) return s;
    return s.substr(0, max) + L"...";
}

}  // namespace

TextStabilizer::TextStabilizer(const std::string& engine)
    : m_engine(engine), m_timeout(selectTimeout()) {
    InitializeCriticalSection(&m_cs);

    // 隐藏消息窗口：必须在 UI 线程创建（构造函数运行在 WinMain 主线程，
    // 消息循环同线程，因此 SetTimer 有效）。
    if (!m_windowRegistered) {
        WNDCLASSEXW wc = {};
        wc.cbSize = sizeof(wc);
        wc.lpfnWndProc = &TextStabilizer::wndProc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.lpszClassName = kClassName;
        RegisterClassExW(&wc);
        m_windowRegistered = true;
    }
    m_hwnd = CreateWindowExW(0, kClassName, L"",
                             WS_POPUP, 0, 0, 0, 0,
                             HWND_MESSAGE, nullptr, GetModuleHandleW(nullptr), this);
}

TextStabilizer::~TextStabilizer() {
    if (m_hwnd) {
        // 清理所有 timer
        EnterCriticalSection(&m_cs);
        for (auto& kv : m_states) {
            if (kv.second.timerId) {
                KillTimer(m_hwnd, kv.second.timerId);
            }
        }
        m_states.clear();
        LeaveCriticalSection(&m_cs);
        DestroyWindow(m_hwnd);
        m_hwnd = nullptr;
    }
    DeleteCriticalSection(&m_cs);
    if (m_windowRegistered) {
        UnregisterClassW(kClassName, GetModuleHandleW(nullptr));
        m_windowRegistered = false;
    }
}

UINT TextStabilizer::selectTimeout() const {
    // 引擎到 Hook 行为映射（与计划书一致）
    auto has = [this](const char* kw) {
        return m_engine.find(kw) != std::string::npos;
    };
    if (has("krkr") || has("KiriKiri") || has("krkr2") || has("krkrZ") ||
        has("Ren'Py") || has("RenPy")) {
        return 300;   // 深度 Hook 引擎：渲染可能分次，等待完整句
    }
    if (has("Unity") || has("RPGMaker") || has("RPG Maker") || has("Light.vn")) {
        return 300;   // 中间引擎：短 debounce
    }
    return 600;       // 未知引擎：逐字兜底
}

void TextStabilizer::setStableCallback(StableCallback cb) {
    m_callback = std::move(cb);
}

void TextStabilizer::setEngine(const std::string& engine) {
    EnterCriticalSection(&m_cs);
    m_engine = engine;
    m_timeout = selectTimeout();
    LeaveCriticalSection(&m_cs);
}

void TextStabilizer::feed(int64_t handle, const std::wstring& raw) {
    if (raw.empty()) {
        return;
    }
    // 去重/清洗已移至稳定后的过滤器链（TextCleaner），稳定器只做 debounce + 追加合并
    std::wstring text = raw;
    std::wstring logText;    // 待写日志（锁外写，避免 I/O 占用临界区）
    std::string logAction;
    const ULONGLONG nowTick = GetTickCount64();
    EnterCriticalSection(&m_cs);
    auto it = m_states.find(handle);
    if (it == m_states.end()) {
        State st;
        st.text = text;
        st.pending = true;
        st.lastFeedTick = nowTick;
        st.lastLogTick = nowTick;
        m_states.emplace(handle, std::move(st));
        LeaveCriticalSection(&m_cs);
        logAction = "new";
        logText = text;
        PostMessageW(m_hwnd, WM_APP_STABLE_UPDATE, static_cast<WPARAM>(handle), 0);
    } else {
        State& st = it->second;
        if (!st.text.empty()) {
            const bool isAppend =
                text.size() > st.text.size() &&
                text.compare(0, st.text.size(), st.text) == 0;
            if (isAppend) {
                st.text = text;                    // 逐字追加合并
                st.retry = 0;
                if (nowTick - st.lastLogTick >= kStabLogInterval) {
                    st.lastLogTick = nowTick;
                    logAction = "append";
                    logText = text;
                }
            } else if (similarity(st.text, text) < kSimilarityThreshold) {
                // 全新文本：立即冲刷旧文本（不等超时，减少延迟）
                std::wstring old = std::move(st.text);
                st.text = text;
                st.retry = 0;
                st.lastLogTick = nowTick;
                logAction = "flush";
                logText = old + L" ==> " + text;
                LeaveCriticalSection(&m_cs);
                if (m_callback) {
                    m_callback(handle, old);
                }
                EnterCriticalSection(&m_cs);
            } else {
                // 高度相似（重复/微变）：忽略
                if (nowTick - st.lastLogTick >= kStabLogInterval) {
                    st.lastLogTick = nowTick;
                    logAction = "ignore";
                    logText = L"old=" + st.text + L" new=" + text;
                }
            }
        } else {
            st.text = text;
            st.retry = 0;
            st.lastLogTick = nowTick;
            logAction = "start";
            logText = text;
        }
        st.lastFeedTick = nowTick;
        const bool needPost = !st.pending;
        st.pending = true;
        LeaveCriticalSection(&m_cs);
        if (needPost) {
            PostMessageW(m_hwnd, WM_APP_STABLE_UPDATE, static_cast<WPARAM>(handle), 0);
        }
    }
    if (!logAction.empty()) {
        std::wstring s = TruncateW(logText, 150);
        std::string utf8;
        int n = WideCharToMultiByte(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()),
                                    nullptr, 0, nullptr, nullptr);
        if (n > 0) {
            utf8.resize(n);
            WideCharToMultiByte(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()),
                                &utf8[0], n, nullptr, nullptr);
        }
        LogStab("handle=" + std::to_string(handle) + " " + logAction + " text=" + utf8);
    }
}

void TextStabilizer::reset(int64_t handle) {
    EnterCriticalSection(&m_cs);
    if (handle < 0) {
        for (auto& kv : m_states) {
            if (kv.second.timerId) {
                KillTimer(m_hwnd, kv.second.timerId);
            }
        }
        m_states.clear();
    } else {
        auto it = m_states.find(handle);
        if (it != m_states.end()) {
            if (it->second.timerId) {
                KillTimer(m_hwnd, it->second.timerId);
            }
            m_states.erase(it);
        }
    }
    LeaveCriticalSection(&m_cs);
}

// ---------- UI 线程 ----------

void TextStabilizer::onUiTimerUpdate(int64_t handle) {
    EnterCriticalSection(&m_cs);
    auto it = m_states.find(handle);
    if (it != m_states.end()) {
        it->second.pending = false;
        resetTimer(handle, it->second);
    }
    LeaveCriticalSection(&m_cs);
}

void TextStabilizer::onTimerTick(UINT_PTR id) {
    const int64_t handle = HandleOf(id);
    std::wstring text;
    EnterCriticalSection(&m_cs);
    auto it = m_states.find(handle);
    if (it != m_states.end()) {
        // 长文本（≥15 字符）且无明确结束标点 → 可能是渲染中途截断，再等一轮，等完整句。
        // 短文本（<15）无标点直接 flush（短句一般不截断，避免无标点短句延迟）。
        if (!IsSentenceEnd(it->second.text) && it->second.retry < kMaxSentenceRetry &&
            it->second.text.size() >= 15) {
            ++it->second.retry;
            resetTimer(handle, it->second);
            LeaveCriticalSection(&m_cs);
            return;
        }
        text = std::move(it->second.text);
        it->second.timerId = 0;
        it->second.pending = false;
        m_states.erase(it);
    }
    LeaveCriticalSection(&m_cs);
    // 双保险：回传前再判空（清洗链在稳定回调后执行）
    if (!text.empty() && m_callback) {
        m_callback(handle, text);
    }
}

void TextStabilizer::resetTimer(int64_t handle, State& st) {
    if (st.timerId) {
        KillTimer(m_hwnd, st.timerId);
    }
    st.timerId = TimerIdOf(handle);
    SetTimer(m_hwnd, st.timerId, m_timeout, nullptr);
}

float TextStabilizer::similarity(const std::wstring& a, const std::wstring& b) {
    if (a.empty() && b.empty()) {
        return 1.0f;
    }
    if (a.empty() || b.empty()) {
        return 0.0f;
    }
    const size_t n = a.size(), m = b.size();
    // 超长保护：退化为前缀/包含判断（对话文本一般远小于此）
    if (n * m > 4'000'000) {
        if (n <= m && b.compare(0, n, a) == 0) return 1.0f;
        if (m <= n && a.compare(0, m, b) == 0) return 1.0f;
        return 0.5f;
    }
    // LCS 滚动数组（O(n*m) 时间，O(m) 空间）
    std::vector<size_t> prev(m + 1, 0), cur(m + 1, 0);
    for (size_t i = 1; i <= n; ++i) {
        for (size_t j = 1; j <= m; ++j) {
            if (a[i - 1] == b[j - 1]) {
                cur[j] = prev[j - 1] + 1;
            } else {
                cur[j] = std::max(prev[j], cur[j - 1]);
            }
        }
        std::swap(prev, cur);
        std::fill(cur.begin(), cur.end(), 0);
    }
    return static_cast<float>(prev[m]) / static_cast<float>(std::max(n, m));
}

LRESULT CALLBACK TextStabilizer::wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    TextStabilizer* self = nullptr;
    if (msg == WM_NCCREATE) {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        self = static_cast<TextStabilizer*>(cs->lpCreateParams);
        self->m_hwnd = hwnd;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    } else {
        self = reinterpret_cast<TextStabilizer*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    }
    if (self) {
        return self->handleMessage(msg, wParam, lParam);
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

LRESULT TextStabilizer::handleMessage(UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_APP_STABLE_UPDATE:
            onUiTimerUpdate(static_cast<int64_t>(wParam));
            return 0;
        case WM_TIMER:
            onTimerTick(static_cast<UINT_PTR>(wParam));
            return 0;
        default:
            return DefWindowProcW(m_hwnd, msg, wParam, lParam);
    }
}

}  // namespace overlay
