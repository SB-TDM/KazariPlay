#include "incremental_dedup.h"

#include <vector>

namespace overlay {

std::wstring IncrementalDedupFilter::apply(const std::wstring& text) {
    // 预处理：压缩连续重复字符（dedup_chars 众数对混合重复文本可能未去净，
    // 如 "「「ええ、" 残留，影响递增段识别）
    std::wstring t;
    t.reserve(text.size());
    for (size_t i = 0; i < text.size();) {
        size_t j = i + 1;
        while (j < text.size() && text[j] == text[i]) ++j;
        if (text[i] == L'.' && (j - i) >= 2) {
            t.append(text, i, j - i);   // 省略号 "..." 是语义，保留
        } else {
            t += text[i];               // 连续重复字符压缩为 1 个
        }
        i = j;
    }
    const size_t n = t.size();
    if (n < 6) return text;

    // 候选"段种子" P = t[0..segLen)。要求 P 至少出现 3 次（≥3 个递增段）。
    // 找"最长连续递增前缀"：段 j+1 是段 j 的前缀扩展。最后一段可能因渲染
    // 中途截断而回退（不完整句），容错处理——返回递增链的顶点段。
    for (size_t segLen = 1; segLen * 3 <= n; ++segLen) {
        std::vector<size_t> pos;
        pos.push_back(0);
        for (size_t i = segLen; i + segLen <= n; ++i) {
            if (t.compare(i, segLen, t, 0, segLen) == 0) {
                pos.push_back(i);
            }
        }
        if (pos.size() < 3) continue;

        size_t lastGood = 0;
        bool anyInc = false;
        for (size_t j = 0; j + 1 < pos.size(); ++j) {
            const size_t s1 = pos[j];
            const size_t l1 = pos[j + 1] - pos[j];
            const size_t s2 = pos[j + 1];
            const size_t l2 = (j + 2 < pos.size()) ? pos[j + 2] - pos[j + 1]
                                                   : n - pos[j + 1];
            if (l1 <= l2 && t.compare(s2, l1, t, s1, l1) == 0) {
                lastGood = j;
                anyInc = true;
            } else {
                break;
            }
        }
        if (anyInc) {
            // 顶点段（最后一个递增段）＝递增链的完整句（或最接近的完整句）
            const size_t segStart = pos[lastGood + 1];
            const size_t segEnd =
                (lastGood + 2 < pos.size()) ? pos[lastGood + 2] : n;
            return t.substr(segStart, segEnd - segStart);
        }
    }
    return text;
}

}  // namespace overlay
