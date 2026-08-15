#include "line_trimmer.h"

#include <vector>

namespace overlay {

namespace {

std::vector<std::wstring> SplitLinesLt(const std::wstring& text) {
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

std::wstring LineTrimmerFilter::apply(const std::wstring& text) {
    auto lines = SplitLinesLt(text);
    if (lines.size() <= static_cast<size_t>(m_maxLines) || m_maxLines < 0) {
        return text;
    }
    std::wstring result;
    if (m_fromEnd) {
        for (size_t i = lines.size() - static_cast<size_t>(m_maxLines); i < lines.size(); ++i) {
            if (!result.empty()) result += L'\n';
            result += lines[i];
        }
    } else {
        for (size_t i = 0; i < static_cast<size_t>(m_maxLines); ++i) {
            if (i > 0) result += L'\n';
            result += lines[i];
        }
    }
    return result;
}

}  // namespace overlay
