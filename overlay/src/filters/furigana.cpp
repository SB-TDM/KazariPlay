#include "furigana.h"

namespace overlay {

const std::wregex FuriganaFilter::s_slashPattern(LR"(\{([^{}:/]+)/[^{}]+\})");
const std::wregex FuriganaFilter::s_colonPattern(LR"(\{([^{}:]+):[^{}]+\})");
const std::wregex FuriganaFilter::s_anyBracePattern(LR"(\{[^{}]*\})");

std::wstring FuriganaFilter::apply(const std::wstring& text) {
    std::wstring result = text;
    result = std::regex_replace(result, s_slashPattern, L"$1");
    result = std::regex_replace(result, s_colonPattern, L"$1");
    result = std::regex_replace(result, s_anyBracePattern, L"");
    return result;
}

}  // namespace overlay
