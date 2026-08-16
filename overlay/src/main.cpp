#include <windows.h>

#include <algorithm>
#include <atomic>
#include <string>
#include <thread>
#include <vector>

#include "ai_translator.h"
#include "cleanliness_checker.h"
#include "engine_policy.h"
#include "filter_chain.h"
#include "pipe_server.h"
#include "protocol.h"
#include "subtitle_window.h"
#include "text_stabilizer.h"
#include "textractor_host.h"
#include "toast_window.h"

namespace {

constexpr UINT WM_APP_SHOW = WM_APP + 1;
constexpr UINT WM_APP_HIDE = WM_APP + 2;
constexpr UINT WM_APP_QUIT = WM_APP + 3;

// 轻量调试日志（overlay\bin\debug.log），用于冒烟测试与现场排查
// 消息均为 ASCII，用二进制追加模式避免编码/BOM 干扰
void LogToFile(const std::string& msg) {
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
        std::snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u] %s\n",
                      st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg.c_str());
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}

// 命令窗口消息（UI 线程处理字幕/稳定器操作；管道线程仅 PostMessage，不直接碰 D2D）
constexpr UINT WM_APP_CMD_SUBTITLE = WM_APP + 0x30;           // 显示原文字幕
constexpr UINT WM_APP_CMD_UPDATE_TRANSLATED = WM_APP + 0x31;  // AI 翻译完成，更新译文
constexpr UINT WM_APP_CMD_HIDE_SUBTITLE = WM_APP + 0x32;      // 仅隐藏字幕
constexpr UINT WM_APP_CMD_STOP_HOOK = WM_APP + 0x33;          // 隐藏字幕 + 重置稳定器
constexpr wchar_t kCmdClassName[] = L"KazariPlayCmdWindow";

void EnableDpiAwareness() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32) {
        using SetProcessDpiAwarenessContextFn = BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT);
        auto fn = reinterpret_cast<SetProcessDpiAwarenessContextFn>(
            GetProcAddress(user32, "SetProcessDpiAwarenessContext"));
        if (fn) {
            fn(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        }
    }
}

std::string PipeNameFromArg(const std::string& arg) {
    if (arg.empty()) {
        return "KazariPlayOverlay";
    }
    auto pos = arg.find_first_not_of(" \t");
    if (pos == std::string::npos) {
        return "KazariPlayOverlay";
    }
    auto end = arg.find_last_not_of(" \t");
    return arg.substr(pos, end - pos + 1);
}

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

std::string WideToUtf8(const std::wstring& w) {
    if (w.empty()) {
        return {};
    }
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()),
                                nullptr, 0, nullptr, nullptr);
    if (n <= 0) {
        return {};
    }
    std::string s(static_cast<size_t>(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()),
                        &s[0], n, nullptr, nullptr);
    return s;
}

std::wstring GetExeDir() {
    wchar_t buf[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, buf, MAX_PATH);
    std::wstring p(buf);
    auto pos = p.find_last_of(L"\\/");
    return pos == std::wstring::npos ? L"" : p.substr(0, pos);
}

struct CmdContext {
    overlay::SubtitleWindow* subtitle = nullptr;
    overlay::TextStabilizer* stabilizer = nullptr;
    overlay::AiTranslator* ai = nullptr;
    std::atomic<DWORD>* gamePid = nullptr;
};

struct EnumCtx {
    DWORD pid = 0;
    HWND hwnd = nullptr;
};

BOOL CALLBACK FindMainWindowProc(HWND hwnd, LPARAM lParam) {
    auto* ctx = reinterpret_cast<EnumCtx*>(lParam);
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != ctx->pid) {
        return TRUE;
    }
    if (!IsWindowVisible(hwnd)) {
        return TRUE;
    }
    LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    if (ex & WS_EX_TOOLWINDOW) {
        return TRUE;
    }
    ctx->hwnd = hwnd;
    return FALSE;   // 找到主窗口即停
}

HWND FindMainWindowByPid(DWORD pid) {
    if (!pid) {
        return nullptr;
    }
    EnumCtx ctx{pid, nullptr};
    EnumWindows(FindMainWindowProc, reinterpret_cast<LPARAM>(&ctx));
    return ctx.hwnd;
}

LRESULT CALLBACK CmdWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    CmdContext* ctx = nullptr;
    if (msg == WM_NCCREATE) {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        ctx = static_cast<CmdContext*>(cs->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(ctx));
    } else {
        ctx = reinterpret_cast<CmdContext*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    }
    if (!ctx) {
        return DefWindowProcW(hwnd, msg, wParam, lParam);
    }
    switch (msg) {
        case WM_APP_CMD_SUBTITLE: {
            auto* sm = reinterpret_cast<protocol::SubtitleMessage*>(lParam);
            if (sm) {
                HWND game = sm->game_hwnd
                                ? reinterpret_cast<HWND>(sm->game_hwnd)
                                : FindMainWindowByPid(ctx->gamePid->load());
                ctx->subtitle->show(game, Utf8ToWide(sm->original));
                delete sm;
            }
            return 0;
        }
        case WM_APP_CMD_UPDATE_TRANSLATED: {
            auto* sm = reinterpret_cast<protocol::SubtitleMessage*>(lParam);
            if (sm) {
                ctx->subtitle->updateTranslated(Utf8ToWide(sm->translated));
                delete sm;
            }
            return 0;
        }
        case WM_APP_CMD_HIDE_SUBTITLE:
            ctx->subtitle->hide();
            return 0;
        case WM_APP_CMD_STOP_HOOK:
            ctx->subtitle->hide();
            ctx->stabilizer->reset();
            if (ctx->ai) {
                ctx->ai->shutdown();
            }
            return 0;
        default:
            return DefWindowProcW(hwnd, msg, wParam, lParam);
    }
}

HWND CreateCmdWindow(HINSTANCE hInstance, CmdContext* ctx) {
    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = &CmdWndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = kCmdClassName;
    RegisterClassExW(&wc);
    return CreateWindowExW(0, kCmdClassName, L"", WS_POPUP,
                           0, 0, 0, 0, HWND_MESSAGE, nullptr, hInstance, ctx);
}

// 宽字符 LCS 相似度（0~1）：用于拦截"同一句的渐进/微差版本"重复翻译
float TextSimilarity(const std::wstring& a, const std::wstring& b) {
    if (a.empty() && b.empty()) {
        return 1.0f;
    }
    if (a.empty() || b.empty()) {
        return 0.0f;
    }
    const size_t n = a.size(), m = b.size();
    if (n * m > 4'000'000) {
        if (n <= m && b.compare(0, n, a) == 0) return 1.0f;
        if (m <= n && a.compare(0, m, b) == 0) return 1.0f;
        return 0.5f;
    }
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

}  // namespace

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR lpCmdLine, int) {
    EnableDpiAwareness();

    ToastWindow toast;
    if (!toast.initialize(hInstance)) {
        return 1;
    }
    LogToFile("init: toast ok");

    overlay::SubtitleWindow subtitle;
    if (!subtitle.initialize(hInstance)) {
        return 1;
    }
    LogToFile("init: subtitle ok");

    overlay::TextractorHost host;
    // 静态链接 hostlib.lib：直接在 UI 线程启动（内部 SetWindowsHookEx 需要消息循环线程）
    host.initialize();
    LogToFile(std::string("init: host started=") + (host.ready() ? "yes" : "no"));

    // 稳定器：UI 线程创建（隐藏消息窗口，SetTimer 依赖 UI 线程消息循环）
    overlay::TextStabilizer stabilizer("");
    LogToFile("init: stabilizer ok");

    // 过滤器链（引擎感知默认策略在 start_hook 时配置）+ 清洗质量评估
    overlay::FilterChain filterChain;
    overlay::CleanlinessChecker cleanlinessChecker;
    LogToFile("init: cleaner ok");

    std::atomic<DWORD> gamePid{0};
    std::string currentEngine;   // 当前引擎名（过滤器链恢复默认策略用）
    std::atomic<int> aiCleanMode{0};   // AI 兜底清洗：0=关, 1=脏才洗, 2=每条都洗
    std::atomic<bool> subtitleEnabled{true};   // 实时翻译开关（关闭时隐藏并停止字幕）
    overlay::AiTranslator ai;
    CmdContext cmdCtx{&subtitle, &stabilizer, &ai, &gamePid};
    HWND cmdHwnd = CreateCmdWindow(hInstance, &cmdCtx);
    LogToFile("init: cmd window ok");

    std::string pipeName = PipeNameFromArg(lpCmdLine ? lpCmdLine : "");

    // server 在自身构造期不可被 lambda 捕获（尚未进入作用域），
    // 用指针间接引用：所有 handler 调用发生在 server.start() 之后，指针必已赋值。
    PipeServer* serverPtr = nullptr;
    PipeServer server(pipeName, [&](const std::string& msg) {
        protocol::Command cmd = protocol::parseCommand(msg);
        // 注意：此处不逐条记日志——stable_text 高频场景写盘会拖垮性能
        switch (cmd.type) {
            case protocol::MsgType::Show: {
                auto* p = new protocol::ShowMessage(cmd.show);
                PostMessageW(toast.hwnd(), WM_APP_SHOW, 0, reinterpret_cast<LPARAM>(p));
                break;
            }
            case protocol::MsgType::Hide:
                PostMessageW(toast.hwnd(), WM_APP_HIDE, 0, 0);
                break;
            case protocol::MsgType::Quit:
                LogToFile("quit received, posting to toast hwnd");
                PostMessageW(toast.hwnd(), WM_APP_QUIT, 0, 0);
                break;
            case protocol::MsgType::StartHook: {
                if (!host.ready()) {
                    if (serverPtr) {
                        serverPtr->sendToClient(protocol::serializeHookError(
                            "host 未就绪，无法注入"));
                    }
                    break;
                }
                const DWORD pid = static_cast<DWORD>(cmd.start_hook.pid);
                if (!host.inject(pid, cmd.start_hook.is_x64)) {
                    if (serverPtr) {
                        serverPtr->sendToClient(protocol::serializeHookError(
                            "注入失败（可能需管理员权限、游戏位数与 overlay 不匹配或游戏不兼容）"));
                    }
                    break;
                }
                gamePid = pid;
                subtitle.setGamePid(pid);
                stabilizer.setEngine(cmd.start_hook.engine);
                host.setCodepage(cmd.start_hook.codepage);
                currentEngine = cmd.start_hook.engine;
                aiCleanMode.store(cmd.start_hook.ai_clean_mode);
                // 配置过滤器链：按引擎选默认过滤器组合
                {
                    auto defaults =
                        overlay::EnginePolicy::selectDefaults(cmd.start_hook.engine);
                    std::vector<overlay::FilterConfig> cfgs;
                    cfgs.reserve(defaults.size());
                    for (size_t i = 0; i < defaults.size(); ++i) {
                        overlay::FilterConfig cfg;
                        cfg.id = defaults[i];
                        cfg.enabled = true;
                        cfg.order = static_cast<int>(i);
                        cfgs.push_back(std::move(cfg));
                    }
                    filterChain.configure(cfgs);
                    LogToFile("filter chain: " +
                              std::to_string(cfgs.size()) + " filters for engine '" +
                              cmd.start_hook.engine + "'");
                }
                // 配置 C++ 内部 AI 翻译
                ai.configure(cmd.start_hook.ai_base_url, cmd.start_hook.ai_api_key,
                             cmd.start_hook.ai_model, cmd.start_hook.src_lang,
                             cmd.start_hook.dst_lang);
                const bool hookEmpty = cmd.start_hook.hook_code.empty();
                const bool insOk = host.insertHook(pid, cmd.start_hook.hook_code);
                LogToFile("start_hook: pid=" + std::to_string(pid) +
                          " empty=" + std::to_string(hookEmpty) +
                          " insert=" + std::to_string(insOk) +
                          " ai=" + std::to_string(ai.configured()) +
                          " code='" + cmd.start_hook.hook_code + "'");
                // 看门狗：30 秒内无文本 → 回传 hook_error
                const ULONGLONG startedTick = GetTickCount64();
                std::thread([&host, serverPtr, startedTick]() {
                    Sleep(30000);
                    if (!host.ready()) {
                        return;
                    }
                    if (host.lastTextTick() < startedTick) {
                        if (serverPtr) {
                            serverPtr->sendToClient(protocol::serializeHookError(
                                "30 秒内未捕获到游戏文本，可能不支持 Hook 或 Hook 点不正确"));
                        }
                    }
                }).detach();
                break;
            }
            case protocol::MsgType::StopHook: {
                DWORD pid = gamePid.load();
                if (pid) {
                    host.detach(pid);
                }
                gamePid = 0;
                PostMessageW(cmdHwnd, WM_APP_CMD_STOP_HOOK, 0, 0);
                break;
            }
            case protocol::MsgType::HideSubtitle:
                PostMessageW(cmdHwnd, WM_APP_CMD_HIDE_SUBTITLE, 0, 0);
                break;
            case protocol::MsgType::TestTranslate: {
                // 设置页测试翻译：用消息内 AI 配置，同步调用 AI，结果回传 Python
                ai.configure(cmd.test_translate.ai_base_url,
                             cmd.test_translate.ai_api_key,
                             cmd.test_translate.ai_model,
                             cmd.test_translate.src_lang,
                             cmd.test_translate.dst_lang);
                std::string out, err;
                bool ok = ai.translateSync(cmd.test_translate.text, out, err);
                if (serverPtr) {
                    serverPtr->sendToClient(
                        protocol::serializeTestTranslateResult(ok, out, err));
                }
                break;
            }
            case protocol::MsgType::SelectHook:
                LogToFile("select_hook: handle=" +
                          std::to_string(cmd.select_hook.handle) +
                          " code='" + cmd.select_hook.hook_code + "'");
                // 同时设置 handle（当前运行内可靠过滤）与地址（跨运行过滤）
                host.setSelectedByHookCode(cmd.select_hook.hook_code);
                host.setSelectedHandle(cmd.select_hook.handle);
                break;
            case protocol::MsgType::UpdateFilterConfig: {
                std::vector<overlay::FilterConfig> cfgs;
                for (const auto& fc : cmd.update_filter_config.filters) {
                    overlay::FilterConfig cfg;
                    cfg.id = fc.id;
                    cfg.enabled = fc.enabled;
                    cfg.order = fc.order;
                    cfgs.push_back(std::move(cfg));
                }
                if (cfgs.empty()) {
                    // 空列表 = 恢复引擎自动策略
                    auto defaults =
                        overlay::EnginePolicy::selectDefaults(currentEngine);
                    for (size_t i = 0; i < defaults.size(); ++i) {
                        overlay::FilterConfig cfg;
                        cfg.id = defaults[i];
                        cfg.enabled = true;
                        cfg.order = static_cast<int>(i);
                        cfgs.push_back(std::move(cfg));
                    }
                }
                filterChain.configure(cfgs);
                LogToFile("update_filter_config: " + std::to_string(cfgs.size()) +
                          " filters");
                break;
            }
            case protocol::MsgType::QueryFilterConfig: {
                auto avail = filterChain.listAvailable();
                std::vector<protocol::FilterConfigMessage> out;
                out.reserve(avail.size());
                for (const auto& a : avail) {
                    protocol::FilterConfigMessage fc;
                    fc.id = a.id;
                    fc.enabled = a.enabled;
                    fc.order = a.order;
                    out.push_back(std::move(fc));
                }
                if (serverPtr) {
                    serverPtr->sendToClient(
                        protocol::serializeFilterConfigResponse(out));
                }
                break;
            }
            case protocol::MsgType::SetSubtitleEnabled:
                subtitleEnabled.store(cmd.set_subtitle_enabled.enabled);
                if (!cmd.set_subtitle_enabled.enabled) {
                    PostMessageW(cmdHwnd, WM_APP_CMD_HIDE_SUBTITLE, 0, 0);
                }
                LogToFile("set_subtitle_enabled: " +
                          std::string(cmd.set_subtitle_enabled.enabled ? "on" : "off"));
                break;
            case protocol::MsgType::SetSubtitleStyle:
                subtitle.applyStyle(cmd.set_subtitle_style.style_json);
                break;
            case protocol::MsgType::SetSubtitleDrag:
                subtitle.setDragMode(cmd.set_subtitle_drag.drag);
                break;
            case protocol::MsgType::PreviewSubtitle:
                subtitle.showPreview();
                break;
            case protocol::MsgType::Ping:
            case protocol::MsgType::Unknown:
            default:
                break;
        }
    });
    serverPtr = &server;

    // 字幕拖拽结束 → 回传位置百分比给控制面板（UI 线程触发）
    subtitle.setPositionCallback([&serverPtr](float xPct, float yPct) {
        if (serverPtr) {
            serverPtr->sendToClient(protocol::serializeSubtitlePos(xPct, yPct));
        }
    });

    // 稳定回调（UI 线程）：文本稳定后 → 过滤器链清洗 → 显示原文 → 异步 AI 翻译 → 更新译文
    // 若启用 AI 兜底清洗且文本脏：先显示原文 → 异步清洗 → 更新字幕 + 翻译
    stabilizer.setStableCallback([&ai, &cmdHwnd, &gamePid, &filterChain,
                                  &cleanlinessChecker, &aiCleanMode, &subtitleEnabled](
                                     int64_t handle, const std::wstring& text) {
        // 实时翻译开关关闭 → 不显示也不翻译
        if (!subtitleEnabled.load()) {
            return;
        }
        // 1) 过滤器链清洗（去重/注音/标签/乱码等）；空表示被过滤光，丢弃
        std::wstring cleaned = filterChain.run(text);
        if (cleaned.empty()) {
            return;
        }
        // 2) 短文本过滤：清洗后 ≤2 个有效字符 → 人名标签/噪声，不显示不翻译
        {
            size_t validCount = 0;
            for (wchar_t ch : cleaned) {
                if (ch != L' ' && ch != L'\t' && ch != L'\r' && ch != L'\n') {
                    ++validCount;
                }
            }
            if (validCount <= 2) {
                return;
            }
        }
        // 清洗日志（节流）：记录清洗前后，用于排查清洗效果
        static std::atomic<ULONGLONG> lastCleanLog{0};
        ULONGLONG nowTick = GetTickCount64();
        if (cleaned != text && nowTick - lastCleanLog.load() >= 500) {
            lastCleanLog.store(nowTick);
            std::string rawLog = WideToUtf8(text);
            std::string clLog = WideToUtf8(cleaned);
            if (rawLog.size() > 120) rawLog = rawLog.substr(0, 120);
            if (clLog.size() > 120) clLog = clLog.substr(0, 120);
            LogToFile("[clean] raw=" + rawLog + " => cleaned=" + clLog);
        }
        std::string utf8 = WideToUtf8(cleaned);

        // 3) 最近翻译去重：与最近几条清洗文本相似度过高（渐进/微差版本）→ 跳过，避免重复翻译。
        //    但若新文本是旧文本的"扩展"（更长且以旧文本开头，如不完整句→完整句），
        //    则更新 recentClean 并继续处理，保证完整句不被误杀。
        {
            static std::vector<std::pair<std::wstring, ULONGLONG>> recentClean;
            const ULONGLONG tickNow = GetTickCount64();
            for (auto it = recentClean.begin(); it != recentClean.end();) {
                if (tickNow - it->second > 3000) {
                    it = recentClean.erase(it);
                } else {
                    ++it;
                }
            }
            bool skip = false;
            bool added = false;
            for (auto& r : recentClean) {
                if (TextSimilarity(r.first, cleaned) > 0.85f) {
                    if (cleaned.size() > r.first.size() &&
                        cleaned.compare(0, r.first.size(), r.first) == 0) {
                        r.first = cleaned;   // 扩展：更新为完整句，继续处理
                        added = true;
                    } else {
                        skip = true;
                    }
                    break;
                }
            }
            if (skip) {
                LogToFile("[dedup] skip: " + utf8.substr(0, 60));
                return;
            }
            if (!added) {
                recentClean.emplace_back(cleaned, tickNow);
                if (recentClean.size() > 5) {
                    recentClean.erase(recentClean.begin());
                }
            }
        }

        // 4) 判定是否需要 AI 兜底清洗
        bool needAiClean = false;
        int mode = aiCleanMode.load();
        if (mode == 2) {
            needAiClean = true;
        } else if (mode == 1 && !cleanlinessChecker.check(cleaned).isClean) {
            LogToFile("[ai_clean] dirty: " + utf8);
            needAiClean = true;
        }
        if (needAiClean) {
            // 先显示原文（清洗前），异步 AI 清洗完成后更新字幕 + 翻译
            HWND game = FindMainWindowByPid(gamePid.load());
            auto* sp = new protocol::SubtitleMessage();
            sp->original = utf8;
            sp->game_hwnd = reinterpret_cast<std::uint64_t>(game);
            PostMessageW(cmdHwnd, WM_APP_CMD_SUBTITLE, 0, reinterpret_cast<LPARAM>(sp));
            ai.cleanAsync(handle, utf8);
            return;
        }

        // 5) 先显示原文（先原文后替换）
        HWND game = FindMainWindowByPid(gamePid.load());
        auto* sp = new protocol::SubtitleMessage();
        sp->original = utf8;
        sp->game_hwnd = reinterpret_cast<std::uint64_t>(game);
        PostMessageW(cmdHwnd, WM_APP_CMD_SUBTITLE, 0, reinterpret_cast<LPARAM>(sp));
        // 6) 异步翻译（worker 线程），完成后 PostMessage 更新译文
        ai.translateAsync(handle, utf8);
    });
    // AI 翻译完成回调（worker 线程）→ PostMessage 到 UI 线程更新字幕
    ai.setCallback([&cmdHwnd](int64_t, const std::string&,
                              const std::string& translated) {
        LogToFile("[ai] translate done: " + translated.substr(0, 60));
        auto* tp = new protocol::SubtitleMessage();
        tp->translated = translated;
        PostMessageW(cmdHwnd, WM_APP_CMD_UPDATE_TRANSLATED, 0,
                     reinterpret_cast<LPARAM>(tp));
    });
    // AI 兜底清洗完成回调（worker 线程）→ 更新字幕为清洗后文本 + 触发翻译
    ai.setCleanCallback([&cmdHwnd, &ai](int64_t handle, const std::string&,
                                        const std::string& cleaned) {
        LogToFile("[ai] clean done: " + cleaned.substr(0, 60));
        auto* sp = new protocol::SubtitleMessage();
        sp->original = cleaned;
        PostMessageW(cmdHwnd, WM_APP_CMD_SUBTITLE, 0, reinterpret_cast<LPARAM>(sp));
        ai.translateAsync(handle, cleaned);
    });

    // Hook 文本回调（host 线程）→ 喂给稳定器（feed 内部锁 + PostMessage，安全）；
    // 内建线程消息（internal）只记录日志，供排查注入失败等。
    // 观察日志：非 internal 文本节流记录（[hook]），看扒取内容与 handle 分布
    std::atomic<ULONGLONG> lastHookLogTick{0};
    host.setTextCallback([&stabilizer, &lastHookLogTick](const overlay::HookText& ht) {
        if (ht.internal) {
            LogToFile("host console: " + WideToUtf8(ht.text));
            return;
        }
        ULONGLONG now = GetTickCount64();
        ULONGLONG last = lastHookLogTick.load();
        if (now - last >= 300) {
            if (lastHookLogTick.compare_exchange_strong(last, now)) {
                std::string t = WideToUtf8(ht.text);
                if (t.size() > 150) t = t.substr(0, 150);
                LogToFile("[hook] handle=" + std::to_string(ht.handle) + " text=" + t);
            }
        }
        stabilizer.feed(ht.handle, ht.text);
    });

    // 候选列表变化 → 节流（500ms）回传 hook_candidates 给 Python（host 线程触发）
    std::atomic<ULONGLONG> lastCandPush{0};
    host.setCandidatesCallback([&host, &serverPtr, &lastCandPush]() {
        ULONGLONG now = GetTickCount64();
        ULONGLONG last = lastCandPush.load();
        if (now - last < 500) {
            return;
        }
        if (!lastCandPush.compare_exchange_strong(last, now)) {
            return;
        }
        if (!serverPtr) {
            return;
        }
        auto cands = host.candidates();
        std::vector<protocol::HookCandidate> out;
        out.reserve(cands.size());
        for (const auto& c : cands) {
            protocol::HookCandidate hc;
            hc.handle = c.handle;
            hc.hook_name = c.hook_name;
            hc.hook_code = c.hook_code;
            std::string t = WideToUtf8(c.text);
            if (t.size() > 200) {
                t = t.substr(0, 200);   // 截断，省管道带宽（前端只做预览）
            }
            hc.text = std::move(t);
            out.push_back(std::move(hc));
        }
        serverPtr->sendToClient(protocol::serializeHookCandidates(out));
    });

    // 客户端（Python）断开 → overlay 自动退出，防残留进程干扰下次注入
    server.setOnDisconnect([&toast]() {
        PostMessageW(toast.hwnd(), WM_APP_QUIT, 0, 0);
    });

    server.start();
    LogToFile("overlay started, waiting for messages");

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    LogToFile("message loop exited");

    host.shutdown();
    subtitle.shutdown();
    ai.shutdown();
    if (cmdHwnd) {
        DestroyWindow(cmdHwnd);
    }
    LogToFile("overlay exiting");
    return 0;
}
