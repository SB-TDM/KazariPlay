#include "control_char.h"

namespace overlay {

std::wstring ControlCharFilter::apply(const std::wstring& text) {
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t ch : text) {
        if (ch >= 0x20 || ch == L'\t' || ch == L'\n' || ch == L'\r') {
            result += ch;
        }
    }
    return result;
}

}  // namespace overlay
