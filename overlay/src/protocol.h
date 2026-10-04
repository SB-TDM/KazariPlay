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

struct Command {
    MsgType type = MsgType::Unknown;
    ShowMessage show;
};

inline Command parseCommand(const std::string& line) {
    Command cmd;
    try {
        const auto j = nlohmann::json::parse(line);
        if (!j.is_object() || !j.contains("type")) {
            return cmd;
        }
        const auto type = j["type"].get<std::string>();
        if (type == "show") {
            cmd.type = MsgType::Show;
            cmd.show.hwnd = j.value("hwnd", std::uint64_t(0));
            cmd.show.path = j.value("path", std::string());
            cmd.show.title = j.value("title", std::string());
            cmd.show.duration_ms = static_cast<int>(j.value("duration", 3.0) * 1000.0);
        } else if (type == "hide") {
            cmd.type = MsgType::Hide;
        } else if (type == "quit") {
            cmd.type = MsgType::Quit;
        } else if (type == "ping") {
            cmd.type = MsgType::Ping;
        }
    } catch (...) {
        cmd.type = MsgType::Unknown;
    }
    return cmd;
}

}  // namespace protocol
