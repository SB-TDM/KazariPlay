#pragma once

#include "../text_filter.h"

namespace overlay {

// 递增拼接去重：处理逐字渲染 hook 抓到的"渐进累积"文本。
// 如「マ「マジ「マジで「マジです「マジです。 → 「マジです。
// （每段 = 前段 + 新增字符，最后一段是完整句）
class IncrementalDedupFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "incremental_dedup"; }
    bool isHookOnly() const override { return true; }
};

}  // namespace overlay
