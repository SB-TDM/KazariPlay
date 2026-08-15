#include "cleanliness_checker.h"

namespace overlay {

CleanResult CleanlinessChecker::check(const std::wstring& text) {
    if (text.empty()) {
        return {false, "empty_after_clean"};
    }
    if (hasUnclosedBraces(text)) {
        return {false, "unclosed_braces"};
    }
    if (hasGarbageChars(text)) {
        return {false, "garbage_chars"};
    }
    if (isLengthAbnormal(text)) {
        return {false, "length_abnormal"};
    }
    if (hasConsecutiveRepeat(text)) {
        return {false, "consecutive_repeat"};
    }
    return {true, ""};
}

bool CleanlinessChecker::hasUnclosedBraces(const std::wstring& text) {
    int braceDepth = 0;
    int angleDepth = 0;
    for (wchar_t ch : text) {
        if (ch == L'{') braceDepth++;
        else if (ch == L'}') braceDepth--;
        else if (ch == L'<') angleDepth++;
        else if (ch == L'>') angleDepth--;
    }
    return braceDepth != 0 || angleDepth != 0;
}

bool CleanlinessChecker::hasGarbageChars(const std::wstring& text) {
    for (wchar_t ch : text) {
        if (ch >= 0x20 && ch <= 0x7E) continue;        // ASCII 可打印
        if (ch == L'\n' || ch == L'\r' || ch == L'\t') continue;
        if (ch >= 0x3000 && ch <= 0x30FF) continue;    // 日文标点/假名
        if (ch >= 0x3400 && ch <= 0x9FFF) continue;    // CJK 汉字
        if (ch >= 0xFF00 && ch <= 0xFFEF) continue;    // 全角符号
        return true;   // 不在常见字符范围内，视为乱码
    }
    return false;
}

bool CleanlinessChecker::isLengthAbnormal(const std::wstring& text) {
    return text.size() < 2 || text.size() > 500;
}

bool CleanlinessChecker::hasConsecutiveRepeat(const std::wstring& text) {
    int consecutive = 1;
    for (size_t i = 1; i < text.size(); ++i) {
        if (text[i] == text[i - 1]) {
            consecutive++;
            if (consecutive >= 4) return true;
        } else {
            consecutive = 1;
        }
    }
    return false;
}

}  // namespace overlay
