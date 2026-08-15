#include "html_tag.h"

namespace overlay {

const std::wregex HtmlTagFilter::s_tagPattern(LR"(<[^>]+>)");

std::wstring HtmlTagFilter::apply(const std::wstring& text) {
    return std::regex_replace(text, s_tagPattern, L"");
}

}  // namespace overlay
