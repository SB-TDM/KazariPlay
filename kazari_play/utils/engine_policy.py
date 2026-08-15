"""引擎→清洗过滤器默认策略（镜像 overlay/src/engine_policy.cpp，须保持一致）

未启动游戏时，前端清洗配置面板据此显示"引擎默认勾选"的过滤器。
游戏运行中则由 C++ 返回真实生效配置。
"""

# 深度 Hook 引擎关键词（输出完整句，几乎无污染）
_DEEP_HOOK = ("ren'py", "renpy")

# 安全档（默认开）：基础清理 + 常用去重（带长度/非重复保护）。
# 激进过滤器（incremental_dedup / dedup_mixed_lines / shift_jis / quote_only /
# line_trimmer 等）默认关闭，需用户在详情页手动开启——避免误伤正常字幕
# （叠词、短重复、ABAB 等），与 LunaTranslator 默认保守一致。
_SAFE = ["furigana", "control_char", "dedup_chars", "dedup_lines", "unicode_normalize"]

# 引擎关键词 → 默认启用的过滤器（按顺序，order 依次递增）
_ENGINE_RULES = [
    (("krkr", "kirikiri", "krkr2", "krkrz"), list(_SAFE)),
    (("unity",), list(_SAFE)),
    (("rpgmaker", "rpg maker"), list(_SAFE)),
    (("light.vn", "lightvn"), ["dedup_chars", "control_char", "unicode_normalize"]),
    (("tyranoscript", "tyrano"), ["html_tag", "furigana", "control_char", "unicode_normalize"]),
]


def select_defaults(engine: str) -> list:
    """返回引擎默认启用的过滤器 ID 列表（顺序即执行顺序）"""
    e = (engine or "").lower()
    for kw in _DEEP_HOOK:
        if kw in e:
            return ["control_char", "unicode_normalize"]
    for keywords, filters in _ENGINE_RULES:
        for kw in keywords:
            if kw in e:
                return list(filters)
    return list(_SAFE)


def default_filter_config(engine: str) -> list:
    """返回带 enabled/order 的过滤器配置（供前端显示引擎默认勾选）"""
    return [{"id": fid, "enabled": True, "order": i}
            for i, fid in enumerate(select_defaults(engine))]
