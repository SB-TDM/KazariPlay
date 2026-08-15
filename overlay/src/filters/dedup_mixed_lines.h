#pragma once

#include "../text_filter.h"

namespace overlay {

// 混合重复行去重：S1S1S1S2S2S2 → S1S2（每行连续重复，压缩为一行）
class DedupMixedLinesFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "dedup_mixed_lines"; }
    bool isHookOnly() const override { return true; }
};

}  // namespace overlay
