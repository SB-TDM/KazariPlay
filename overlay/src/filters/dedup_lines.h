#pragma once

#include "../text_filter.h"

namespace overlay {

// 重复行/整段重复去重：ABCDABCDABCD → ABCD（引擎快速刷新整行/整段文本）
class DedupLinesFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "dedup_lines"; }
    bool isHookOnly() const override { return true; }
};

}  // namespace overlay
