#pragma once

#include "../text_filter.h"

namespace overlay {

// 仅保留「」内内容（丢弃旁白）。注意：默认不启用，会丢旁白，仅用户显式开启
class QuoteOnlyFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "quote_only"; }
};

}  // namespace overlay
