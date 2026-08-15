#include "shift_jis.h"

namespace overlay {

bool ShiftJisFilter::isShiftJisEncodable(wchar_t ch) {
    if (ch >= 0x20 && ch <= 0x7E) return true;         // ASCII 可打印
    if (ch >= 0xFF61 && ch <= 0xFF9F) return true;     // 半角片假名
    if (ch >= 0x3040 && ch <= 0x309F) return true;     // 平假名
    if (ch >= 0x30A0 && ch <= 0x30FF) return true;     // 片假名
    if (ch >= 0x4E00 && ch <= 0x9FFF) return true;     // CJK 汉字
    if (ch >= 0x3000 && ch <= 0x303F) return true;     // 全角标点
    if (ch == L'\n' || ch == L'\r' || ch == L'\t') return true;
    return false;
}

std::wstring ShiftJisFilter::apply(const std::wstring& text) {
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t ch : text) {
        if (isShiftJisEncodable(ch)) {
            result += ch;
        }
    }
    return result;
}

}  // namespace overlay
