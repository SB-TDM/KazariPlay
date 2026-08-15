#pragma once

#include <string>

namespace overlay {

// 过滤器基类：每个过滤器职责单一、可独立开关、顺序可调
class TextFilter {
public:
    virtual ~TextFilter() = default;

    // 执行过滤，返回清洗后的文本
    // 若返回空字符串，表示文本被完全过滤掉，应丢弃
    virtual std::wstring apply(const std::wstring& text) = 0;

    // 过滤器 ID（用于配置引用）
    virtual std::string id() const = 0;

    // 是否仅对 Hook 模式有效（OCR 不用）
    virtual bool isHookOnly() const { return false; }
};

}  // namespace overlay
