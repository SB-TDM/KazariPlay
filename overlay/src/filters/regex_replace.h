#pragma once

#include "../text_filter.h"

#include <regex>
#include <string>
#include <vector>

namespace overlay {

struct RegexRule {
    std::wstring pattern;
    std::wstring replacement;
    bool isRegex = true;
};

// 正则/字面量替换（用户自定义规则）
class RegexReplaceFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "regex_replace"; }

    void setRules(const std::vector<RegexRule>& rules) { m_rules = rules; }

private:
    std::vector<RegexRule> m_rules;
};

}  // namespace overlay
