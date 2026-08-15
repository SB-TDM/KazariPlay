// 必须先包含 common.h（AutoHandle/Synchronized 等工具类型，types.h 依赖）
#include "common.h"

#include "textractor_host.h"

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <sstream>

namespace overlay {

TextractorHost* TextractorHost::s_instance = nullptr;

namespace {

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

std::string HexEncode(const std::wstring& s) {
    std::string out;
    for (wchar_t c : s) {
        char buf[8];
        std::snprintf(buf, sizeof(buf), "%04X", static_cast<unsigned>(c));
        out += buf;
    }
    return out;
}

// 字节串 → 十六进制（char[] 字段用，保留原始字节）
std::string HexEncodeBytes(const char* data, size_t len) {
    std::string out;
    for (size_t i = 0; i < len; ++i) {
        char buf[4];
        std::snprintf(buf, sizeof(buf), "%02X", static_cast<unsigned char>(data[i]));
        out += buf;
    }
    return out;
}

std::string HexDecodeBytes(const std::string& hex) {
    std::string out;
    for (size_t i = 0; i + 2 <= hex.size(); i += 2) {
        auto val = [&](char c) -> int {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        };
        int hi = val(hex[i]), lo = val(hex[i + 1]);
        if (hi < 0 || lo < 0) {
            return {};
        }
        out.push_back(static_cast<char>((hi << 4) | lo));
    }
    return out;
}

std::wstring HexDecode(const std::string& hex) {
    std::wstring out;
    for (size_t i = 0; i + 4 <= hex.size(); i += 4) {
        unsigned v = 0;
        for (int k = 0; k < 4; ++k) {
            char c = hex[i + k];
            int d = -1;
            if (c >= '0' && c <= '9') d = c - '0';
            else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
            if (d < 0) return {};
            v = (v << 4) | static_cast<unsigned>(d);
        }
        out.push_back(static_cast<wchar_t>(v));
    }
    return out;
}

std::string WideToHexStr(const std::wstring& s) { return HexEncode(s); }
std::wstring HexStrToWide(const std::string& hex) { return HexDecode(hex); }

// 解析 16 进制数（含 0x 前缀），失败返回 false
bool ParseHexU64(const std::string& s, uint64_t& out) {
    size_t i = 0;
    if (s.size() >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        i = 2;
    }
    uint64_t v = 0;
    bool any = false;
    for (; i < s.size(); ++i) {
        char c = static_cast<char>(std::tolower(static_cast<unsigned char>(s[i])));
        int d = -1;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        if (d < 0) break;
        v = (v << 4) | static_cast<uint64_t>(d);
        any = true;
    }
    if (!any) {
        return false;
    }
    out = v;
    return true;
}

std::string U64Hex(uint64_t v) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%llX", static_cast<unsigned long long>(v));
    return buf;
}

// 诊断日志：写入 overlay/bin(|bin32)/debug.log（与 main.cpp LogToFile 同路径）
void LogDiag(const std::string& msg) {
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
        char line[1024];
        std::snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u] [diag] %s\n",
                      st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg.c_str());
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}

}  // namespace

TextractorHost::TextractorHost() {
    InitializeCriticalSection(&m_cs);
    s_instance = this;
}

TextractorHost::~TextractorHost() {
    shutdown();
    DeleteCriticalSection(&m_cs);
    if (s_instance == this) {
        s_instance = nullptr;
    }
}

bool TextractorHost::initialize() {
    if (m_started.load()) {
        return true;
    }
    // Host::Start 必须在 UI 线程（有消息循环）调用：内部 SetWindowsHookExW
    // 绑定当前线程，以及 CreatePipe 等待 texthook 连接。
    Host::Start(onProcessConnect, onProcessDisconnect,
                onCreateThread, onDestroyThread, onTextOutput);
    m_started = true;
    return true;
}

bool TextractorHost::inject(DWORD pid, bool isX64) {
    if (!m_started.load() || pid == 0) {
        return false;
    }
    // isX64 仅用于 OverlayClient 选择 overlay 二进制版本（x86 游戏 → x86 overlay，
    // x64 游戏 → x64 overlay）；host 自身按编译位数注入对应游戏。
    // x64 host 会拒绝注入 32 位（WOW64）进程，注入失败由 30s 看门狗兜底提示。
    (void)isX64;
    m_connectedPid = 0;
    Host::InjectProcess(pid);   // 异步线程注入
    // 等待进程连接回调（最多 5 秒）
    for (int i = 0; i < 50; ++i) {
        if (m_connectedPid.load() == pid) {
            return true;
        }
        Sleep(100);
    }
    return false;
}

void TextractorHost::setCodepage(int codepage) {
    m_codepage = codepage;
}

bool TextractorHost::insertHook(DWORD pid, const std::string& hookCode) {
    if (!m_started.load() || pid == 0) {
        return false;
    }
    if (hookCode.empty()) {
        // 首次：候选模式（只收集候选，不出字幕；onTextOutput 里不喂稳定器）
        m_selectedHandle = -1;
        m_selectedAddress = 0;
        setCandidateMode(true);
        return true;
    }
    // 二次启动（已有 hook_code）：手动插入指定 hook 点。
    // 虽然可能被 Textractor 自动识别引擎（如 KiriKiriZ）替代，但手动插入的
    // UserHook 在部分引擎上是抓取对话文本的唯一可靠途径（自动 hook 常只抓系统 UI）。
    HookParam hp;
    if (!parseHookParam(hookCode, hp)) {
        return false;
    }
    m_selectedAddress = hp.address;
    m_selectedHandle = -1;
    m_candidateMode = false;
    {
        EnterCriticalSection(&m_cs);
        m_selectedFunction.assign(hp.function, strnlen(hp.function, MAX_MODULE_SIZE));
        LeaveCriticalSection(&m_cs);
    }
    if (m_codepage > 0) {
        hp.codepage = static_cast<UINT>(m_codepage);   // 用户指定编码覆盖默认 Shift-JIS
    }
    try {
        Host::InsertHook(pid, hp);
        return true;
    } catch (const std::exception&) {
        return false;   // 进程未连接
    }
}

bool TextractorHost::detach(DWORD pid) {
    if (!m_started.load() || pid == 0) {
        return false;
    }
    try {
        Host::DetachProcess(pid);
    } catch (const std::exception&) {
        return false;
    }
    if (m_connectedPid.load() == pid) {
        m_connectedPid = 0;
    }
    m_selectedHandle = -1;
    m_candidateMode = false;
    EnterCriticalSection(&m_cs);
    m_selectedFunction.clear();
    LeaveCriticalSection(&m_cs);
    return true;
}

void TextractorHost::setTextCallback(TextCallback cb) {
    m_callback = std::move(cb);
}

void TextractorHost::setCandidatesCallback(CandidatesCallback cb) {
    m_candidatesCallback = std::move(cb);
}

void TextractorHost::setCandidateMode(bool enabled) {
    m_candidateMode = enabled;
    if (enabled) {
        EnterCriticalSection(&m_cs);
        m_candidates.clear();
        m_selectedFunction.clear();
        LeaveCriticalSection(&m_cs);
    }
}

void TextractorHost::setSelectedHandle(int64_t handle) {
    // 保留 m_selectedAddress（二次启动按地址过滤的兜底），handle 用于当前运行内过滤
    m_selectedHandle = handle;
    m_candidateMode = false;
}

void TextractorHost::setSelectedAddress(std::uintptr_t addr) {
    m_selectedAddress = addr;
    m_selectedHandle = -1;
    m_candidateMode = false;
}

void TextractorHost::setSelectedByHookCode(const std::string& code) {
    HookParam hp;
    if (parseHookParam(code, hp)) {
        m_selectedAddress = hp.address;
        m_selectedHandle = -1;
        m_candidateMode = false;
        EnterCriticalSection(&m_cs);
        m_selectedFunction.assign(hp.function, strnlen(hp.function, MAX_MODULE_SIZE));
        LeaveCriticalSection(&m_cs);
    } else {
        // 解析失败（如空 hook_code）：保持候选模式，避免"全不过滤"导致残缺文本进字幕
        m_selectedAddress = 0;
        m_selectedHandle = -1;
        m_candidateMode = true;
        EnterCriticalSection(&m_cs);
        m_candidates.clear();
        m_selectedFunction.clear();
        LeaveCriticalSection(&m_cs);
    }
}

std::vector<HookText> TextractorHost::candidates() const {
    EnterCriticalSection(&m_cs);
    std::vector<HookText> out = m_candidates;
    LeaveCriticalSection(&m_cs);
    return out;
}

void TextractorHost::shutdown() {
    DWORD pid = m_connectedPid.load();
    if (m_started.load() && pid) {
        try {
            Host::DetachProcess(pid);
        } catch (const std::exception&) {
        }
    }
    m_connectedPid = 0;
    m_started = false;
    m_selectedHandle = -1;
    m_candidateMode = false;
}

// ---------- host 回调（host 内部线程） ----------

void TextractorHost::onProcessConnect(DWORD processId) {
    if (s_instance) {
        s_instance->m_connectedPid = processId;
    }
}

void TextractorHost::onProcessDisconnect(DWORD processId) {
    if (s_instance && s_instance->m_connectedPid.load() == processId) {
        s_instance->m_connectedPid = 0;
        s_instance->m_selectedHandle = -1;
    }
}

void TextractorHost::onCreateThread(TextThread& thread) {
    // 内建线程（console/clipboard）与候选收集无文本，忽略；
    // 真实游戏线程的文本在 onTextOutput 收集。
    (void)thread;
}

void TextractorHost::onDestroyThread(TextThread& thread) {
    (void)thread;
}

bool TextractorHost::onTextOutput(TextThread& thread, std::wstring& sentence) {
    if (!s_instance) {
        return true;
    }
    TextractorHost* self = s_instance;

    // 内建线程（console/clipboard 的 processId 为 0）：host 内部消息
    // （如 INJECT_FAILED / NEED_32_BIT / ALREADY_INJECTED），转发给上层日志。
    if (thread.tp.processId == 0) {
        HookText ht;
        ht.handle = thread.handle;
        ht.internal = true;
        ht.text = sentence;
        if (self->m_callback) {
            self->m_callback(ht);
        }
        return true;
    }

    self->m_lastTextTick = GetTickCount64();

    int64_t selected = self->m_selectedHandle.load();
    if (selected >= 0) {
        // 当前运行内（用户已选定）：只按 handle 过滤，可靠。
        // 不再叠加 address/function 过滤——Textractor 自动 GDI hook 的
        // hp.function 可能为空，叠加 function 匹配会把选定 handle 也过滤掉。
        if (thread.handle != selected) {
            return true;
        }
    } else {
        // 跨运行（二次启动恢复 hook_code，handle 已失效）：按 address/function 过滤
        std::uintptr_t selAddr = self->m_selectedAddress.load();
        if (selAddr != 0 && thread.hp.address != selAddr) {
            return true;   // 地址 hook：按地址过滤
        }
        if (selAddr == 0 && !self->m_selectedFunction.empty()) {
            std::string selFunc;
            EnterCriticalSection(&self->m_cs);
            selFunc = self->m_selectedFunction;
            LeaveCriticalSection(&self->m_cs);
            // thread.hp.function 为空（自动 GDI hook 常如此）时跳过 function 匹配，避免误杀
            if (thread.hp.function[0] != '\0' &&
                strncmp(thread.hp.function, selFunc.c_str(), MAX_MODULE_SIZE) != 0) {
                return true;
            }
        }
    }

    // 诊断：节流记录过滤状态（观察用，确认地址/handle 过滤是否生效）
    static std::atomic<ULONGLONG> lastDiagTick{0};
    ULONGLONG nowDiag = GetTickCount64();
    if (nowDiag - lastDiagTick.load() >= 300) {
        lastDiagTick.store(nowDiag);
        LogDiag("filter handle=" + std::to_string(thread.handle) +
                " addr=0x" + U64Hex(thread.hp.address) +
                " selected=" + std::to_string(selected) +
                " selAddr=0x" + U64Hex(self->m_selectedAddress.load()) +
                " cand=" + std::to_string(self->m_candidateMode.load()));
    }

    HookText ht;
    ht.handle = thread.handle;
    ht.addr = thread.tp.addr;
    ht.hook_name = WideToUtf8(thread.name);
    ht.hook_code = self->serializeHookParam(thread.hp);
    ht.text = sentence;   // UTF-16 原文（回调可改，但我们不改）

    if (self->m_candidateMode) {
        bool changed = false;
        EnterCriticalSection(&self->m_cs);
        bool found = false;
        for (auto& c : self->m_candidates) {
            if (c.handle == ht.handle) {
                if (c.text != ht.text || c.hook_code != ht.hook_code) {
                    c.text = ht.text;
                    c.hook_code = ht.hook_code;
                    changed = true;
                }
                found = true;
                break;
            }
        }
        if (!found && self->m_candidates.size() < 200) {
            self->m_candidates.push_back(ht);
            changed = true;
        }
        LeaveCriticalSection(&self->m_cs);
        if (changed && self->m_candidatesCallback) {
            self->m_candidatesCallback();   // 必须快速返回（main.cpp 节流推送）
        }
        return true;   // 候选模式：只收集候选，不喂稳定器（字幕）
    }

    if (self->m_callback) {
        self->m_callback(ht);   // 必须快速返回（入队/通知）
    }
    return true;   // 保持 host 默认行为（文本入 storage）
}

void TextractorHost::dispatchText(const HookText& ht) {
    (void)ht;
}

// ---------- HookParam 序列化/解析 ----------

// 自有格式：kzh:<address>:<type>:<codepage>:<offset>:<index>:<split>:<split_index>:
//                <null_length>:<length_offset>:<padding>:<user_value>:<module_hex>:
//                <function_hex>:<name_hex>
std::string TextractorHost::serializeHookParam(const HookParam& hp) {
    std::string s = "kzh:";
    s += U64Hex(hp.address) + ":";
    s += U64Hex(hp.type) + ":";
    s += U64Hex(hp.codepage) + ":";
    s += std::to_string(static_cast<long long>(hp.offset)) + ":";
    s += std::to_string(static_cast<long long>(hp.index)) + ":";
    s += std::to_string(static_cast<long long>(hp.split)) + ":";
    s += std::to_string(static_cast<long long>(hp.split_index)) + ":";
    s += std::to_string(static_cast<long long>(hp.null_length)) + ":";
    s += std::to_string(static_cast<long long>(hp.length_offset)) + ":";
    s += U64Hex(hp.padding) + ":";
    s += U64Hex(hp.user_value) + ":";
    s += WideToHexStr(hp.module) + ":";
    s += HexEncodeBytes(hp.function, strnlen(hp.function, MAX_MODULE_SIZE)) + ":";
    s += HexEncodeBytes(hp.name, strnlen(hp.name, HOOK_NAME_SIZE));
    return s;
}

bool TextractorHost::parseHookParam(const std::string& code, HookParam& hp) {
    hp = {};
    if (code.rfind("kzh:", 0) != 0) {
        return false;
    }
    std::vector<std::string> parts;
    std::string cur;
    std::istringstream ss(code.substr(4));
    while (std::getline(ss, cur, ':')) {
        parts.push_back(cur);
    }
    if (parts.size() < 12) {
        return false;
    }
    auto num = [&](size_t i, long long& out) -> bool {
        try {
            out = std::stoll(parts[i]);
            return true;
        } catch (...) {
            return false;
        }
    };
    uint64_t addr64 = 0;
    if (!ParseHexU64(parts[0], addr64)) return false;
    hp.address = static_cast<uintptr_t>(addr64);
    {
        uint64_t tmp = 0;
        if (ParseHexU64(parts[1], tmp)) hp.type = static_cast<DWORD>(tmp);
        if (ParseHexU64(parts[2], tmp)) hp.codepage = static_cast<UINT>(tmp);
    }
    long long v;
    if (num(3, v)) hp.offset = static_cast<int>(v);
    if (num(4, v)) hp.index = static_cast<int>(v);
    if (num(5, v)) hp.split = static_cast<int>(v);
    if (num(6, v)) hp.split_index = static_cast<int>(v);
    if (num(7, v)) hp.null_length = static_cast<int>(v);
    if (num(8, v)) hp.length_offset = static_cast<short>(v);
    {
        uint64_t tmp = 0;
        if (ParseHexU64(parts[9], tmp)) hp.padding = static_cast<uintptr_t>(tmp);
        if (ParseHexU64(parts[10], tmp)) hp.user_value = static_cast<DWORD>(tmp);
    }
    if (parts.size() > 11) {
        std::wstring m = HexStrToWide(parts[11]);
        wcsncpy_s(hp.module, MAX_MODULE_SIZE, m.c_str(), _TRUNCATE);
    }
    if (parts.size() > 12) {
        std::string f = HexDecodeBytes(parts[12]);
        strncpy_s(hp.function, MAX_MODULE_SIZE, f.c_str(), _TRUNCATE);
    }
    if (parts.size() > 13) {
        std::string nm = HexDecodeBytes(parts[13]);
        strncpy_s(hp.name, HOOK_NAME_SIZE, nm.c_str(), _TRUNCATE);
    }
    return true;
}

}  // namespace overlay
