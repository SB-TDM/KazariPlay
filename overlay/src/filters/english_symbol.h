#pragma once

#include "../text_filter.h"

namespace overlay {

// 英文标点过滤：过滤 ASCII 标点符号
class EnglishSymbolFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "english_symbol"; }

private:
    static bool isSymbol(wchar_t ch);
};

}  // namespace overlay
