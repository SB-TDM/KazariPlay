#include "protocol.hpp"

#include <cstdint>
#include <iostream>
#include <string>

namespace {

int failures = 0;

void check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

std::string fromHex(const std::string& hex) {
    std::string out;
    out.reserve(hex.size() / 2);
    for (std::size_t i = 0; i + 1 < hex.size(); i += 2) {
        out.push_back(static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
    }
    return out;
}

std::string toHex(const std::string& data) {
    static constexpr char digits[] = "0123456789abcdef";
    std::string out;
    out.reserve(data.size() * 2);
    for (const unsigned char ch : data) {
        out.push_back(digits[ch >> 4u]);
        out.push_back(digits[ch & 0x0fu]);
    }
    return out;
}

void expectProtocolError(const char* message, const std::string& data) {
    try {
        std::string buffer = data;
        (void)host::decodeFrame(buffer);
        check(false, message);
    } catch (const host::ProtocolError&) {
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 3 && std::string(argv[1]) == "--encode") {
        try {
            std::cout << toHex(host::encodeFrame(nlohmann::json::parse(argv[2]))) << '\n';
            return 0;
        } catch (const std::exception& exc) {
            std::cerr << exc.what() << '\n';
            return 1;
        }
    }
    if (argc == 3 && std::string(argv[1]) == "--decode") {
        try {
            std::string buffer = fromHex(argv[2]);
            const auto value = host::decodeFrame(buffer);
            if (!value.has_value() || !buffer.empty()) {
                std::cerr << "incomplete or trailing frame data\n";
                return 1;
            }
            std::cout << value->dump() << '\n';
            return 0;
        } catch (const std::exception& exc) {
            std::cerr << exc.what() << '\n';
            return 1;
        }
    }

    const auto ready = host::encodeFrame(nlohmann::json{{"type", "ready"}});
    check(ready == fromHex("100000007b2274797065223a227265616479227d"),
          "ready golden frame");

    {
        std::string buffer = ready;
        const auto decoded = host::decodeFrame(buffer);
        check(decoded.has_value(), "ready decodes");
        check(decoded->is_object(), "ready is object");
        check((*decoded)["type"] == "ready", "ready type");
        check(buffer.empty(), "ready buffer consumed");
    }

    {
        const std::string raw = ready + host::encodeFrame(nlohmann::json{{"type", "shutdown"}});
        std::string buffer = raw.substr(0, 3);
        check(!host::decodeFrame(buffer).has_value(), "partial prefix waits");
        check(buffer.size() == 3, "partial prefix not consumed");
        buffer = raw;
        const auto first = host::decodeFrame(buffer);
        check(first.has_value() && (*first)["type"] == "ready", "first combined frame");
        const auto second = host::decodeFrame(buffer);
        check(second.has_value() && (*second)["type"] == "shutdown", "second combined frame");
        check(buffer.empty(), "combined frames consumed");
    }

    {
        std::string trunc = ready.substr(0, ready.size() - 1);
        check(!host::decodeFrame(trunc).has_value(), "partial body waits");
        check(trunc.size() == ready.size() - 1, "partial body not consumed");
    }

    {
        const auto unicode = host::encodeFrame(nlohmann::json{{"type", "toast"}, {"text", "你好"}});
        std::string buffer = unicode;
        const auto decoded = host::decodeFrame(buffer);
        check(decoded.has_value() && (*decoded)["text"] == "你好", "unicode roundtrip");
    }

    expectProtocolError("empty frame rejected", std::string(4, '\0'));
    expectProtocolError("invalid JSON rejected", fromHex("010000007b"));
    expectProtocolError("non-object rejected", fromHex("020000005b5d"));
    expectProtocolError("NaN rejected", fromHex(
        "180000007b2274797065223a2278222c2276616c7565223a4e614e7d"));

    {
        std::string oversize(4, '\0');
        const std::uint32_t size = host::kMaxFrame + 1;
        oversize[0] = static_cast<char>(size & 0xffu);
        oversize[1] = static_cast<char>((size >> 8u) & 0xffu);
        oversize[2] = static_cast<char>((size >> 16u) & 0xffu);
        oversize[3] = static_cast<char>((size >> 24u) & 0xffu);
        expectProtocolError("oversize prefix rejected", oversize);
    }

    if (failures != 0) {
        std::cerr << failures << " protocol check(s) failed\n";
        return 1;
    }
    std::cout << "HOST_PROTOCOL_TEST PASS\n";
    return 0;
}
