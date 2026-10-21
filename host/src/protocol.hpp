#pragma once

#include <cmath>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>

#include "json.hpp"

namespace host {

constexpr std::size_t kMaxFrame = 8u * 1024u * 1024u;

class ProtocolError : public std::runtime_error {
public:
    explicit ProtocolError(const std::string& message) : std::runtime_error(message) {}
};

inline bool containsNonFiniteToken(const std::string& body) {
    bool in_string = false;
    bool escaped = false;
    for (std::size_t i = 0; i < body.size(); ++i) {
        const char ch = body[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
            continue;
        }
        if (body.compare(i, 3, "NaN") == 0
            || body.compare(i, 8, "Infinity") == 0) {
            return true;
        }
    }
    return false;
}

inline void validateJsonValue(const nlohmann::json& value) {
    if (value.is_number_float() && !std::isfinite(value.get<double>())) {
        throw ProtocolError("non-finite JSON number");
    }
    if (value.is_array()) {
        for (const auto& item : value) {
            validateJsonValue(item);
        }
    } else if (value.is_object()) {
        for (const auto& item : value.items()) {
            validateJsonValue(item.value());
        }
    }
}

inline std::string encodeFrame(const nlohmann::json& value) {
    validateJsonValue(value);
    std::string body;
    try {
        body = value.dump();
    } catch (const std::exception& exc) {
        throw ProtocolError(std::string("JSON encode failed: ") + exc.what());
    }
    if (body.size() > kMaxFrame) {
        throw ProtocolError("frame too large");
    }
    std::string frame;
    frame.reserve(4 + body.size());
    const auto size = static_cast<std::uint32_t>(body.size());
    frame.push_back(static_cast<char>(size & 0xffu));
    frame.push_back(static_cast<char>((size >> 8u) & 0xffu));
    frame.push_back(static_cast<char>((size >> 16u) & 0xffu));
    frame.push_back(static_cast<char>((size >> 24u) & 0xffu));
    frame.append(body);
    return frame;
}

inline std::optional<nlohmann::json> decodeFrame(std::string& buffer) {
    if (buffer.size() < 4) {
        return std::nullopt;
    }
    const auto size =
        static_cast<std::uint32_t>(static_cast<unsigned char>(buffer[0]))
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(buffer[1])) << 8u)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(buffer[2])) << 16u)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(buffer[3])) << 24u);
    if (size == 0) {
        throw ProtocolError("empty frame");
    }
    if (size > kMaxFrame) {
        throw ProtocolError("frame too large");
    }
    if (buffer.size() < 4u + size) {
        return std::nullopt;
    }
    const std::string body = buffer.substr(4, size);
    if (containsNonFiniteToken(body)) {
        throw ProtocolError("non-finite JSON number");
    }
    nlohmann::json value;
    try {
        value = nlohmann::json::parse(body);
    } catch (const std::exception& exc) {
        throw ProtocolError(std::string("invalid frame JSON: ") + exc.what());
    }
    if (!value.is_object()) {
        throw ProtocolError("frame must be an object");
    }
    validateJsonValue(value);
    buffer.erase(0, 4u + size);
    return value;
}

}  // namespace host
