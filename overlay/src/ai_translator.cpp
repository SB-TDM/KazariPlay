#include "ai_translator.h"

#include <winhttp.h>

#include <cstdio>
#include <cwchar>
#include <string>

#pragma comment(lib, "winhttp.lib")

namespace overlay {

namespace {

// 调试日志（写 overlay/bin(|bin32)/debug.log，与 main.cpp LogToFile 同路径）
void LogAI(const std::string& msg) {
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
        std::snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u] %s\n",
                      st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg.c_str());
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}

const char* TaskName(AiTranslator::TaskType type) {
    return type == AiTranslator::TaskType::Clean ? "clean" : "translate";
}

std::string JsonEscape(const std::string& s) {
    std::string out;
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    // 跳过控制字符
                } else {
                    out += c;
                }
        }
    }
    return out;
}

const char* LangName(const std::string& code) {
    if (code == "zh") return "中文";
    if (code == "ja") return "日语";
    if (code == "en") return "英语";
    if (code == "ko") return "韩语";
    if (code == "fr") return "法语";
    if (code == "de") return "德语";
    if (code == "ru") return "俄语";
    if (code == "es") return "西班牙语";
    return code.c_str();
}

// 简易 JSON 提取：取 {"choices":[{"message":{"content":"..."}}]} 的 content
bool ParseJsonContent(const std::string& body, std::string& out) {
    std::string key = "\"content\":";
    size_t pos = body.find(key);
    if (pos == std::string::npos) {
        return false;
    }
    pos += key.size();
    while (pos < body.size() && (body[pos] == ' ' || body[pos] == '"')) {
        ++pos;
    }
    std::string result;
    while (pos < body.size()) {
        char c = body[pos];
        if (c == '\\' && pos + 1 < body.size()) {
            char n = body[pos + 1];
            if (n == 'n') result += '\n';
            else if (n == '"') result += '"';
            else if (n == '\\') result += '\\';
            else result += n;
            pos += 2;
            continue;
        }
        if (c == '"') {
            break;
        }
        result += c;
        ++pos;
    }
    if (result.empty()) {
        return false;
    }
    out = result;
    return true;
}

}  // namespace

AiTranslator::~AiTranslator() {
    shutdown();
}

void AiTranslator::configure(const std::string& baseUrl, const std::string& apiKey,
                             const std::string& model,
                             const std::string& sourceLang, const std::string& targetLang) {
    m_baseUrl = baseUrl;
    m_apiKey = apiKey;
    m_model = model.empty() ? "deepseek-chat" : model;
    m_src = sourceLang.empty() ? "ja" : sourceLang;
    m_dst = targetLang.empty() ? "zh" : targetLang;
    m_configured = !m_baseUrl.empty() && !m_apiKey.empty();

    if (!m_worker.joinable() && m_configured) {
        m_stop = false;
        m_worker = std::thread([this] { workerLoop(); });
    }
}

void AiTranslator::shutdown() {
    if (!m_worker.joinable()) {
        return;
    }
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_stop = true;
    }
    m_cv.notify_all();
    if (m_worker.joinable()) {
        m_worker.join();
    }
}

void AiTranslator::translateAsync(int64_t handle, const std::string& text) {
    if (!m_configured || text.empty()) {
        return;
    }
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        if (m_queue.size() < 64) {   // 有界队列，防积压
            m_queue.push_back(Task{handle, TaskType::Translate, text});
        }
    }
    m_cv.notify_one();
}

void AiTranslator::cleanAsync(int64_t handle, const std::string& text) {
    if (!m_configured || text.empty()) {
        return;
    }
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        if (m_queue.size() < 64) {
            m_queue.push_back(Task{handle, TaskType::Clean, text});
        }
    }
    m_cv.notify_one();
}

bool AiTranslator::translateSync(const std::string& text, std::string& out, std::string& err) {
    if (!m_configured || text.empty()) {
        err = "AI 翻译未配置或文本为空";
        return false;
    }
    return doRequest(text, TaskType::Translate, out);
}

void AiTranslator::workerLoop() {
    while (true) {
        Task item;
        {
            std::unique_lock<std::mutex> lk(m_mutex);
            m_cv.wait(lk, [this] { return m_stop || !m_queue.empty(); });
            if (m_stop && m_queue.empty()) {
                break;
            }
            item = std::move(m_queue.front());
            m_queue.pop_front();
        }
        std::string out;
        if (!doRequest(item.text, item.type, out)) {
            LogAI(std::string("AI request FAIL type=") + TaskName(item.type) +
                  " text=" + item.text.substr(0, 50));
            continue;
        }
        if (item.type == TaskType::Translate) {
            if (m_callback) {
                m_callback(item.handle, item.text, out);
            }
        } else {
            if (m_cleanCallback) {
                m_cleanCallback(item.handle, item.text, out);
            }
        }
    }
}

bool AiTranslator::doRequest(const std::string& text, TaskType type, std::string& out) {
    std::string srcName = LangName(m_src);
    std::string dstName = LangName(m_dst);

    std::string body;
    if (type == TaskType::Clean) {
        // AI 兜底清洗：只清洗不翻译（过滤器链无法确定的脏文本）
        body += "{\"model\":\"" + JsonEscape(m_model) + "\",";
        body += "\"temperature\":0,\"max_tokens\":1024,";
        body += "\"messages\":[";
        body += "{\"role\":\"system\",\"content\":\"";
        body += "你是一名游戏文本清洗器。以下是 Hook 从游戏内存提取的文本，可能包含："
                "重复字符（如\\\"恵恵恵麻麻麻\\\"是\\\"恵麻\\\"被多次渲染）、"
                "注音标记（如\\\"{漢字/かな}\\\"应保留汉字）、控制字符或乱码、"
                "HTML/脚本标签、递增拼接的重复段（如\\\"「マ「マジ…\\\"应保留最后完整句）。"
                "请只输出清洗后的纯" + srcName + "文本，不要翻译，不要解释，不要添加任何额外内容。\"},";
        body += "{\"role\":\"user\",\"content\":\"" + JsonEscape(text) + "\"}";
        body += "]}";
    } else {
        body += "{\"model\":\"" + JsonEscape(m_model) + "\",";
        body += "\"temperature\":0.3,\"max_tokens\":1024,";
        body += "\"messages\":[";
        body += "{\"role\":\"system\",\"content\":\"";
        body += "你是一名专业的视觉小说/游戏本地化译者。将用户提供的" + srcName + "文本翻译为" + dstName + "，";
        body += "只输出译文本身，不要任何解释、注释或额外内容；保留人名、专有名词的常用译法；根据语境选择自然的表达。\"},";
        body += "{\"role\":\"user\",\"content\":\"" + JsonEscape(text) + "\"}";
        body += "]}";
    }

    std::string url = m_baseUrl;
    if (url.rfind("http", 0) != 0) {
        url = "https://" + url;
    }
    while (!url.empty() && url.back() == '/') {
        url.pop_back();
    }
    url += "/chat/completions";

    std::string scheme = "https";
    std::string host, path = "/chat/completions";
    size_t p = url.find("://");
    if (p != std::string::npos) {
        scheme = url.substr(0, p);
        std::string rest = url.substr(p + 3);
        size_t slash = rest.find('/');
        if (slash == std::string::npos) {
            host = rest;
        } else {
            host = rest.substr(0, slash);
            path = rest.substr(slash);
        }
    } else {
        host = url;
    }

    INTERNET_PORT port = (scheme == "http") ? 80 : 443;
    size_t colon = host.rfind(':');
    if (colon != std::string::npos) {
        port = static_cast<INTERNET_PORT>(std::stoi(host.substr(colon + 1)));
        host = host.substr(0, colon);
    }

    HINTERNET hSession = WinHttpOpen(L"KazariPlay/1.0",
                                     WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) {
        LogAI("AI open FAIL err=" + std::to_string(GetLastError()));
        return false;
    }
    std::wstring wHost(host.begin(), host.end());
    HINTERNET hConnect = WinHttpConnect(hSession, wHost.c_str(), port, 0);
    if (!hConnect) {
        LogAI("AI connect FAIL host=" + host + " err=" + std::to_string(GetLastError()));
        WinHttpCloseHandle(hSession);
        return false;
    }
    std::wstring wPath(path.begin(), path.end());
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", wPath.c_str(), nullptr,
                                            WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                            scheme == "http" ? 0 : WINHTTP_FLAG_SECURE);
    if (!hRequest) {
        LogAI("AI openrequest FAIL err=" + std::to_string(GetLastError()));
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    std::wstring auth = L"Authorization: Bearer ";
    for (char c : m_apiKey) auth += static_cast<wchar_t>(c);
    std::wstring hdrAll = L"Content-Type: application/json\r\n" + auth;
    WinHttpSetTimeouts(hRequest, 5000, 5000, 30000, 30000);

    BOOL sent = WinHttpSendRequest(hRequest, hdrAll.c_str(), (DWORD)-1,
                                   (LPVOID)body.data(), (DWORD)body.size(),
                                   (DWORD)body.size(), 0);
    bool ok = false;
    if (!sent) {
        LogAI("AI send FAIL err=" + std::to_string(GetLastError()));
    } else if (!WinHttpReceiveResponse(hRequest, nullptr)) {
        LogAI("AI recv FAIL err=" + std::to_string(GetLastError()));
    } else {
        std::string respBody;
        DWORD avail = 0;
        while (WinHttpQueryDataAvailable(hRequest, &avail) && avail > 0) {
            std::string buf(avail, '\0');
            DWORD read = 0;
            if (!WinHttpReadData(hRequest, &buf[0], avail, &read)) {
                break;
            }
            respBody.append(buf, 0, read);
        }
        DWORD status = 0;
        DWORD slen = sizeof(status);
        if (WinHttpQueryHeaders(hRequest, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                WINHTTP_HEADER_NAME_BY_INDEX, &status, &slen,
                                WINHTTP_NO_HEADER_INDEX)) {
            LogAI("AI http status=" + std::to_string(status));
        }
        ok = ParseJsonContent(respBody, out);
        if (!ok) {
            std::string snippet = respBody.substr(0, 300);
            LogAI("AI parse FAIL resp=" + snippet);
        }
    }
    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return ok;
}

}  // namespace overlay
