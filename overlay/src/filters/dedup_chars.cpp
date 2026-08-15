#include "dedup_chars.h"

#include <unordered_map>

namespace overlay {

int DedupCharsFilter::analyzeRepeatPeriod(const std::wstring& text) {
    // 统计前若干个不同字符的连续出现次数，取众数作为周期
    std::unordered_map<wchar_t, int> firstSeenCount;
    int consecutive = 1;
    for (size_t i = 1; i < text.size() && firstSeenCount.size() < 20; ++i) {
        if (text[i] == text[i - 1]) {
            consecutive++;
        } else {
            if (firstSeenCount.find(text[i - 1]) == firstSeenCount.end()) {
                firstSeenCount[text[i - 1]] = consecutive;
            }
            consecutive = 1;
        }
    }
    // 整个文本为同一字符（如"翔翔翔"）时，上面的循环从未在字符切换处记录，
    // firstSeenCount 为空 → 应记录首个字符的连续次数（否则误判为"无重复"）
    if (firstSeenCount.empty() && !text.empty()) {
        firstSeenCount[text[0]] = consecutive;
    }
    if (firstSeenCount.empty()) return 1;

    std::unordered_map<int, int> countFreq;
    for (const auto& [ch, cnt] : firstSeenCount) {
        if (cnt > 1) countFreq[cnt]++;
    }
    if (countFreq.empty()) return 1;

    int mode = 1, modeFreq = 0;
    for (const auto& [cnt, freq] : countFreq) {
        if (freq > modeFreq) { modeFreq = freq; mode = cnt; }
    }
    return mode;
}

std::wstring DedupCharsFilter::apply(const std::wstring& text) {
    if (text.empty()) return L"";

    int repeat = m_repeatCount;
    if (repeat <= 0) {
        repeat = analyzeRepeatPeriod(text);
        if (repeat <= 1) return text;   // 无重复
    }

    std::wstring result;
    result.reserve(text.size() / repeat + 8);
    int consecutive = 1;
    for (size_t i = 1; i <= text.size(); ++i) {
        if (i < text.size() && text[i] == text[i - 1]) {
            consecutive++;
        } else {
            if (consecutive >= repeat) {
                result += text[i - 1];   // 重复字符，保留 1 个
            } else if (m_keepSingletons) {
                result.append(text, i - static_cast<size_t>(consecutive),
                              static_cast<size_t>(consecutive));
            }
            consecutive = 1;
        }
    }
    return result;
}

}  // namespace overlay
