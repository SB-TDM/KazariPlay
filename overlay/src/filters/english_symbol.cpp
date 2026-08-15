#include "english_symbol.h"

namespace overlay {

bool EnglishSymbolFilter::isSymbol(wchar_t ch) {
    // 常见英文标点/符号
    return (ch >= L'!' && ch <= L'/') || (ch >= L':' && ch <= L'@') ||
           (ch >= L'[' && ch <= L'`') || (ch >= L'{' && ch <= L'~');
}

std::wstring EnglishSymbolFilter::apply(const std::wstring& text) {
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t ch : text) {
        if (!isSymbol(ch)) {
            result += ch;
        }
    }
    return result;
}

}  // namespace overlay
