#pragma once

#include "../text_filter.h"

namespace overlay {

// 控制字符过滤：丢弃 ASCII 控制字符（0x00-0x1F, 0x7F），保留 \t\n\r
class ControlCharFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "control_char"; }
};

}  // namespace overlay
