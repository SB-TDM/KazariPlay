#pragma once

#include "../text_filter.h"
#include <regex>

namespace overlay {

// 注音清理：{漢字/かな}→漢字，{漢字:かな}→漢字，残留 {xxx}→删除
class FuriganaFilter : public TextFilter {
public:
    std::wstring apply(const std::wstring& text) override;
    std::string id() const override { return "furigana"; }

private:
    static const std::wregex s_slashPattern;   // {漢字/かな}
    static const std::wregex s_colonPattern;   // {漢字:かな}
    static const std::wregex s_anyBracePattern;  // 残留 {任意}
};

}  // namespace overlay
