#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "json.hpp"

namespace protocol {

// 消息类型
// Python -> C++：
//   show/hide/quit/ping（原有 toast）
//   start_hook/stop_hook（Hook 控制；start_hook 带 AI 翻译配置）
//   hide_subtitle / test_translate / select_hook
//   update_filter_config / query_filter_config（清洗过滤器配置）
// C++ -> Python（回传）：
//   stable_text / hook_candidates / hook_error / test_translate_result / filter_config_response
enum class MsgType {
    Show, Hide, Quit, Ping,
    StartHook, StopHook,
    HideSubtitle, TestTranslate,
    SelectHook,
    UpdateFilterConfig, QueryFilterConfig,
    SetSubtitleEnabled,
    StableText, HookCandidates, HookError, TestTranslateResult, FilterConfigResponse,
    Unknown
};

struct ShowMessage {
    std::uint64_t hwnd = 0;
    std::string path;
    std::string title;
    int duration_ms = 3000;
};

struct HookStartMessage {
    std::uint64_t pid = 0;
    std::string engine;
    std::string hook_code;   // 空 = 首次需选择
    bool is_x64 = true;
    int codepage = 0;        // 文本编码：0=引擎默认(Shift-JIS)/932/936/65001
    // AI 翻译配置（C++ 内部翻译用）
    std::string ai_base_url;
    std::string ai_api_key;
    std::string ai_model;
    std::string src_lang;    // 源语言（ja）
    std::string dst_lang;    // 目标语言（zh）
    int ai_clean_mode = 0;   // AI 兜底清洗：0=关, 1=脏文本才洗, 2=每条都洗
};

struct SubtitleMessage {
    std::string original;
    std::string translated;
    std::uint64_t game_hwnd = 0;   // 游戏窗口句柄（Python 端查找，0 = 由 C++ 兜底查找）
};

struct TestTranslateMessage {
    std::string text;
    std::string ai_base_url;
    std::string ai_api_key;
    std::string ai_model;
    std::string src_lang;
    std::string dst_lang;
};

struct SelectHookMessage {
    std::int64_t handle = 0;
    std::string hook_code;   // 选定的 hook 序列化（含地址，跨运行过滤用）
};

struct FilterConfigMessage {
    std::string id;
    bool enabled = true;
    int order = 0;
};

struct UpdateFilterConfigMessage {
    std::vector<FilterConfigMessage> filters;
};

struct SetSubtitleEnabledMessage {
    bool enabled = true;
};

// Python -> C++ 统一命令结构
struct Command {
    MsgType type = MsgType::Unknown;
    ShowMessage show;
    HookStartMessage start_hook;
    SubtitleMessage subtitle;
    TestTranslateMessage test_translate;
    SelectHookMessage select_hook;
    UpdateFilterConfigMessage update_filter_config;
    SetSubtitleEnabledMessage set_subtitle_enabled;
};

inline Command parseCommand(const std::string& line) {
    Command cmd;
    try {
        nlohmann::json j = nlohmann::json::parse(line);
        if (!j.is_object() || !j.contains("type")) {
            return cmd;
        }
        const std::string type = j["type"].get<std::string>();
        if (type == "show") {
            cmd.type = MsgType::Show;
            cmd.show.hwnd = j.value("hwnd", std::uint64_t(0));
            cmd.show.path = j.value("path", std::string());
            cmd.show.title = j.value("title", std::string());
            double duration = j.value("duration", 3.0);
            cmd.show.duration_ms = static_cast<int>(duration * 1000.0);
        } else if (type == "hide") {
            cmd.type = MsgType::Hide;
        } else if (type == "quit") {
            cmd.type = MsgType::Quit;
        } else if (type == "ping") {
            cmd.type = MsgType::Ping;
        } else if (type == "start_hook") {
            cmd.type = MsgType::StartHook;
            cmd.start_hook.pid = j.value("pid", std::uint64_t(0));
            cmd.start_hook.engine = j.value("engine", std::string());
            cmd.start_hook.hook_code = j.value("hook_code", std::string());
            cmd.start_hook.is_x64 = j.value("is_x64", true);
            cmd.start_hook.codepage = j.value("codepage", 0);
            cmd.start_hook.ai_base_url = j.value("ai_base_url", std::string());
            cmd.start_hook.ai_api_key = j.value("ai_api_key", std::string());
            cmd.start_hook.ai_model = j.value("ai_model", std::string());
            cmd.start_hook.src_lang = j.value("src_lang", std::string());
            cmd.start_hook.dst_lang = j.value("dst_lang", std::string());
            cmd.start_hook.ai_clean_mode = j.value("ai_clean_mode", 0);
        } else if (type == "stop_hook") {
            cmd.type = MsgType::StopHook;
        } else if (type == "hide_subtitle") {
            cmd.type = MsgType::HideSubtitle;
        } else if (type == "test_translate") {
            cmd.type = MsgType::TestTranslate;
            cmd.test_translate.text = j.value("text", std::string());
            cmd.test_translate.ai_base_url = j.value("ai_base_url", std::string());
            cmd.test_translate.ai_api_key = j.value("ai_api_key", std::string());
            cmd.test_translate.ai_model = j.value("ai_model", std::string());
            cmd.test_translate.src_lang = j.value("src_lang", std::string());
            cmd.test_translate.dst_lang = j.value("dst_lang", std::string());
        } else if (type == "select_hook") {
            cmd.type = MsgType::SelectHook;
            cmd.select_hook.handle = j.value("handle", std::int64_t(0));
            cmd.select_hook.hook_code = j.value("hook_code", std::string());
        } else if (type == "update_filter_config") {
            cmd.type = MsgType::UpdateFilterConfig;
            if (j.contains("filters") && j["filters"].is_array()) {
                for (const auto& f : j["filters"]) {
                    FilterConfigMessage fc;
                    fc.id = f.value("id", std::string());
                    fc.enabled = f.value("enabled", true);
                    fc.order = f.value("order", 0);
                    cmd.update_filter_config.filters.push_back(std::move(fc));
                }
            }
        } else if (type == "query_filter_config") {
            cmd.type = MsgType::QueryFilterConfig;
        } else if (type == "set_subtitle_enabled") {
            cmd.type = MsgType::SetSubtitleEnabled;
            cmd.set_subtitle_enabled.enabled = j.value("enabled", true);
        }
    } catch (...) {
        cmd.type = MsgType::Unknown;
    }
    return cmd;
}

// ---------- C++ -> Python 序列化 ----------

inline std::string serializeStableText(std::int64_t handle, const std::string& text) {
    nlohmann::json j;
    j["type"] = "stable_text";
    j["handle"] = handle;
    j["text"] = text;
    return j.dump();
}

struct HookCandidate {
    std::int64_t handle = 0;
    std::string hook_name;
    std::string hook_code;
    std::string text;   // UTF-8 预览
};

inline std::string serializeHookCandidates(const std::vector<HookCandidate>& cands) {
    nlohmann::json j;
    j["type"] = "hook_candidates";
    nlohmann::json list = nlohmann::json::array();
    for (const auto& c : cands) {
        nlohmann::json item;
        item["handle"] = c.handle;
        item["hook_name"] = c.hook_name;
        item["hook_code"] = c.hook_code;
        item["text"] = c.text;
        list.push_back(std::move(item));
    }
    j["list"] = std::move(list);
    return j.dump();
}

inline std::string serializeHookError(const std::string& msg) {
    nlohmann::json j;
    j["type"] = "hook_error";
    j["msg"] = msg;
    return j.dump();
}

inline std::string serializeTestTranslateResult(bool ok, const std::string& result,
                                                const std::string& error) {
    nlohmann::json j;
    j["type"] = "test_translate_result";
    j["ok"] = ok;
    j["result"] = result;
    j["error"] = error;
    return j.dump();
}

// 清洗过滤器配置回传（available = 全部过滤器 + 当前 enabled/order）
inline std::string serializeFilterConfigResponse(
    const std::vector<FilterConfigMessage>& filters) {
    nlohmann::json j;
    j["type"] = "filter_config_response";
    nlohmann::json list = nlohmann::json::array();
    for (const auto& f : filters) {
        nlohmann::json item;
        item["id"] = f.id;
        item["enabled"] = f.enabled;
        item["order"] = f.order;
        list.push_back(std::move(item));
    }
    j["filters"] = std::move(list);
    return j.dump();
}

}  // namespace protocol
