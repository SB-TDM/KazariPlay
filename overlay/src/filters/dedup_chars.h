#pragma once

#include "../text_filter.h"

namespace overlay {

// 重复字符去重：AAAABBBB → AB（多层渲染导致的同字多次提取）
class DedupCharsFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "dedup_chars"; }
    bool isHookOnly() const override { return true; }

    // 重复次数：0=自动分析（众数），>0=指定次数
    void setRepeatCount(int count) { m_repeatCount = count; }
    // 是否保留单次出现的字符（标点等）
    void setKeepSingletons(bool keep) { m_keepSingletons = keep; }

private:
    // 扫描前若干个不同字符的连续出现次数，取众数作为重复周期
    static int analyzeRepeatPeriod(const std::wstring& text);

    int m_repeatCount = 0;
    bool m_keepSingletons = true;
};

}  // namespace overlay
