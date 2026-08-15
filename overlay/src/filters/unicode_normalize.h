#pragma once

#include "../text_filter.h"

namespace overlay {

// Unicode 正规化：全角英数字/标点 → 半角
class UnicodeNormalizerFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "unicode_normalize"; }

private:
    static wchar_t fullToHalf(wchar_t ch);
};

}  // namespace overlay
