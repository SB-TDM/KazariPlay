#pragma once

#include "../text_filter.h"

namespace overlay {

// 行截取：只保留前 N 行或后 N 行
class LineTrimmerFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "line_trimmer"; }

    void setMaxLines(int n) { m_maxLines = n; }
    void setFromEnd(bool fromEnd) { m_fromEnd = fromEnd; }

private:
    int m_maxLines = 1;
    bool m_fromEnd = false;
};

}  // namespace overlay
