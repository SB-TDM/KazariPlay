#include "engine_policy.h"

#include <algorithm>
#include <cctype>

namespace overlay {

std::vector<std::string> EnginePolicy::selectDefaults(const std::string& engine) {
    // 安全档（默认开）：基础清理 + 常用去重（带长度/非重复保护）。
    // 激进过滤器（incremental_dedup / dedup_mixed_lines / shift_jis / quote_only /
    // line_trimmer 等）默认关闭，需用户在详情页手动开启——避免误伤正常字幕
    // （叠词、短重复、ABAB 等），与 LunaTranslator 默认保守一致。
    const std::vector<std::string> kSafe = {
        "furigana", "control_char", "dedup_chars", "dedup_lines", "unicode_normalize"};

    // 深度 Hook 引擎：输出干净，最小清洗
    if (isDeepHookEngine(engine)) {
        return {"control_char", "unicode_normalize"};
    }
    // krkr 系：注音 + 重复字符 + 整句重复（安全档）
    if (containsAny(engine, {"krkr", "KiriKiri", "krkr2", "krkrZ"})) {
        return kSafe;
    }
    // Unity：安全档
    if (containsAny(engine, {"Unity"})) {
        return kSafe;
    }
    // RPGMaker：安全档（去掉了 line_trimmer 激进项）
    if (containsAny(engine, {"RPGMaker", "RPG Maker"})) {
        return kSafe;
    }
    // Light.vn：重复字符 + 控制字符 + 正规化
    if (containsAny(engine, {"Light.vn", "light.vn", "Lightvn"})) {
        return {"dedup_chars", "control_char", "unicode_normalize"};
    }
    // TyranoScript：HTML 标签 + 安全档
    if (containsAny(engine, {"TyranoScript", "Tyrano"})) {
        return {"html_tag", "furigana", "control_char", "unicode_normalize"};
    }
    // 未知引擎：安全档（不再全开 shift_jis 等激进项）
    return kSafe;
}

bool EnginePolicy::isDeepHookEngine(const std::string& engine) {
    return containsAny(engine, {"Ren'Py", "Renpy", "renpy"});
}

bool EnginePolicy::containsAny(const std::string& engine,
                               const std::vector<std::string>& keywords) {
    std::string lower;
    lower.reserve(engine.size());
    for (char c : engine) {
        lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    for (const auto& kw : keywords) {
        std::string kl;
        kl.reserve(kw.size());
        for (char c : kw) {
            kl += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
        if (lower.find(kl) != std::string::npos) return true;
    }
    return false;
}

}  // namespace overlay
