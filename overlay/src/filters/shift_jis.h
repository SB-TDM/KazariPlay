#pragma once

#include "../text_filter.h"

namespace overlay {

// 非 Shift-JIS 字符过滤：过滤无法用 Shift-JIS 编码的字符（乱码）
class ShiftJisFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "shift_jis"; }

private:
    // 判定一个 wchar_t 是否能用 Shift-JIS 编码
    static bool isShiftJisEncodable(wchar_t ch);
};

}  // namespace overlay
