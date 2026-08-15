#include "regex_replace.h"

namespace overlay {

std::wstring RegexReplaceFilter::apply(const std::wstring& text) {
    std::wstring result = text;
    for (const auto& rule : m_rules) {
        if (rule.isRegex) {
            try {
                std::wregex re(rule.pattern);
                result = std::regex_replace(result, re, rule.replacement);
            } catch (...) {
                // 正则编译失败，跳过此规则
            }
        } else {
            size_t pos = 0;
            while ((pos = result.find(rule.pattern, pos)) != std::wstring::npos) {
                result.replace(pos, rule.pattern.size(), rule.replacement);
                pos += rule.replacement.size();
            }
        }
    }
    return result;
}

}  // namespace overlay
