#include "unicode_normalize.h"

namespace overlay {

wchar_t UnicodeNormalizerFilter::fullToHalf(wchar_t ch) {
    if (ch >= 0xFF10 && ch <= 0xFF19) return static_cast<wchar_t>(ch - 0xFF10 + L'0');
    if (ch >= 0xFF21 && ch <= 0xFF3A) return static_cast<wchar_t>(ch - 0xFF21 + L'A');
    if (ch >= 0xFF41 && ch <= 0xFF5A) return static_cast<wchar_t>(ch - 0xFF41 + L'a');
    if (ch == 0x3000) return L' ';
    switch (ch) {
        case 0xFF01: return L'!';
        case 0xFF02: return L'"';
        case 0xFF03: return L'#';
        case 0xFF05: return L'%';
        case 0xFF06: return L'&';
        case 0xFF07: return L'\'';
        case 0xFF08: return L'(';
        case 0xFF09: return L')';
        case 0xFF0A: return L'*';
        case 0xFF0B: return L'+';
        case 0xFF0C: return L',';
        case 0xFF0D: return L'-';
        case 0xFF0E: return L'.';
        case 0xFF0F: return L'/';
        case 0xFF1A: return L':';
        case 0xFF1B: return L';';
        case 0xFF1C: return L'<';
        case 0xFF1D: return L'=';
        case 0xFF1E: return L'>';
        case 0xFF1F: return L'?';
        case 0xFF20: return L'@';
        case 0xFF3B: return L'[';
        case 0xFF3C: return L'\\';
        case 0xFF3D: return L']';
        case 0xFF3E: return L'^';
        case 0xFF3F: return L'_';
        case 0xFF40: return L'`';
        case 0xFF5B: return L'{';
        case 0xFF5C: return L'|';
        case 0xFF5D: return L'}';
        case 0xFF5E: return L'~';
        case 0xFF04: return L'$';
        default: return ch;
    }
}

std::wstring UnicodeNormalizerFilter::apply(const std::wstring& text) {
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t ch : text) {
        result += fullToHalf(ch);
    }
    return result;
}

}  // namespace overlay
