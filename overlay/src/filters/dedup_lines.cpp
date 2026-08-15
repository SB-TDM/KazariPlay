#include "dedup_lines.h"

namespace overlay {

std::wstring DedupLinesFilter::apply(const std::wstring& text) {
    // 长度阈值：≥8 字符才检测整段周期重复。
    // 保护叠词/短重复（"どんどん"、"はい、はい" 等是正常表达，不是渲染重复）
    if (text.size() < 8) return text;

    // 检测整段的最小重复周期 p（无换行的整句重复也适用）：
    // "帰りのホームルーム。　帰りのホームルーム。　" → p=12 → 取前 12
    // 要求匹配率 ≥90%（避免误伤"はい、はい"这类自然重复）
    for (size_t p = 2; p <= text.size() / 2; ++p) {
        size_t matched = 0;
        for (size_t i = 0; i < text.size(); ++i) {
            if (text[i] == text[i % p]) ++matched;
        }
        if (matched * 10 >= text.size() * 9) {
            return text.substr(0, p);
        }
    }
    return text;
}

}  // namespace overlay
