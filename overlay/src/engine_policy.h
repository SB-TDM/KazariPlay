#pragma once

#include <string>
#include <vector>

namespace overlay {

// 引擎策略器：根据 game.engine 自动选择默认启用的过滤器组合
class EnginePolicy {
public:
    // 根据引擎名返回默认启用的过滤器 ID 列表（按顺序）
    static std::vector<std::string> selectDefaults(const std::string& engine);

    // 判定引擎是否属于"深度 Hook 引擎"（输出完整句，几乎无污染）
    static bool isDeepHookEngine(const std::string& engine);

private:
    static bool containsAny(const std::string& engine,
                            const std::vector<std::string>& keywords);
};

}  // namespace overlay
