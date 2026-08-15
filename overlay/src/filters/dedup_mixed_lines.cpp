#include "dedup_mixed_lines.h"

#include <vector>

namespace overlay {

namespace {

std::vector<std::wstring> SplitLines(const std::wstring& text) {
    std::vector<std::wstring> lines;
    std::wstring cur;
    for (wchar_t ch : text) {
        if (ch == L'\n') {
            lines.push_back(cur);
            cur.clear();
        } else if (ch != L'\r') {
            cur += ch;
        }
    }
    if (!cur.empty() || !lines.empty()) {
        lines.push_back(cur);
    }
    return lines;
}

}  // namespace

std::wstring DedupMixedLinesFilter::apply(const std::wstring& text) {
    auto lines = SplitLines(text);
    if (lines.size() < 2) return text;

    std::wstring result;
    std::wstring last;
    bool first = true;
    for (const auto& line : lines) {
        if (!first && line == last) {
            continue;   // 连续重复行，跳过
        }
        if (!first) result += L'\n';
        result += line;
        last = line;
        first = false;
    }
    return result;
}

}  // namespace overlay
