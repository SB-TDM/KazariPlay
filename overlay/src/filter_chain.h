#pragma once

#include "text_filter.h"

#include <windows.h>

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace overlay {

struct FilterConfig {
    std::string id;
    bool enabled = true;
    int order = 0;          // 执行顺序，越小越先执行
    std::string args_json;  // 过滤器参数（JSON 字符串，暂未使用）
};

// 过滤器链：按 order 有序执行已启用的过滤器。
// 线程安全：configure（管道线程）与 run（UI 线程）可并发调用。
class FilterChain {
public:
    FilterChain();
    ~FilterChain();

    // 注册所有内置过滤器
    void registerBuiltins();

    // 按配置启用/禁用过滤器（重复调用会重置链）
    void configure(const std::vector<FilterConfig>& configs);

    // 执行过滤器链；返回清洗后的文本，空字符串表示被过滤光
    std::wstring run(const std::wstring& text);

    // 获取所有过滤器（带当前启用状态与顺序，供前端展示）
    std::vector<FilterConfig> listAvailable() const;

private:
    mutable CRITICAL_SECTION m_cs;
    std::vector<std::unique_ptr<TextFilter>> m_allFilters;
    std::vector<std::pair<int, TextFilter*>> m_enabled;  // (order, filter)，已排序
};

}  // namespace overlay
