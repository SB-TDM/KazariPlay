#pragma once

#include "../text_filter.h"
#include <regex>

namespace overlay {

// HTML 标签清理：<div>xxx</div> → xxx
class HtmlTagFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "html_tag"; }

private:
    static const std::wregex s_tagPattern;
};

}  // namespace overlay
