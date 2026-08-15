#include "quote_only.h"

namespace overlay {

std::wstring QuoteOnlyFilter::apply(const std::wstring& text) {
    // 提取「...」或『...』内的内容（含引号本身）
    std::wstring result;
    bool inQuote = false;
    wchar_t openQuote = 0;
    for (wchar_t ch : text) {
        if (!inQuote) {
            if (ch == L'「' || ch == L'『') {
                inQuote = true;
                openQuote = ch;
                result += ch;
            }
        } else {
            result += ch;
            if ((openQuote == L'「' && ch == L'」') ||
                (openQuote == L'『' && ch == L'』')) {
                inQuote = false;
            }
        }
    }
    return result;
}

}  // namespace overlay
