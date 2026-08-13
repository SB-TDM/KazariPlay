#pragma once

#include <cstdint>
#include <string>

#include "json.hpp"

namespace protocol {

enum class MsgType { Show, Hide, Quit, Ping, Unknown };

struct ShowMessage {
    std::uint64_t hwnd = 0;
    std::string path;
    std::string title;
    int duration_ms = 3000;
};

inline MsgType parse(const std::string& line, ShowMessage& out) {
    try {
        nlohmann::json j = nlohmann::json::parse(line);
        if (!j.is_object() || !j.contains("type")) {
            return MsgType::Unknown;
        }
        const std::string type = j["type"].get<std::string>();
        if (type == "show") {
            out.hwnd = j.value("hwnd", std::uint64_t(0));
            out.path = j.value("path", std::string());
            out.title = j.value("title", std::string());
            double duration = j.value("duration", 3.0);
            out.duration_ms = static_cast<int>(duration * 1000.0);
            return MsgType::Show;
        }
        if (type == "hide") {
            return MsgType::Hide;
        }
        if (type == "quit") {
            return MsgType::Quit;
        }
        if (type == "ping") {
            return MsgType::Ping;
        }
        return MsgType::Unknown;
    } catch (...) {
        return MsgType::Unknown;
    }
}

}  // namespace protocol
