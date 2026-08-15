#pragma once

#include <string>

namespace overlay {

struct CleanResult {
    bool isClean = true;
    std::string reason;   // 不干净的原因（供日志）
};

// 清洗质量评估器：判定清洗后文本是否"干净"，决定是否触发 AI 兜底
class CleanlinessChecker {
public:
    CleanResult check(const std::wstring& text);

private:
    static bool hasUnclosedBraces(const std::wstring& text);
    static bool hasGarbageChars(const std::wstring& text);
    static bool isLengthAbnormal(const std::wstring& text);
    static bool hasConsecutiveRepeat(const std::wstring& text);
};

}  // namespace overlay
