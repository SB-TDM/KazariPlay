"""评分规范化工具 — 全链路统一 0-5 半星制（0.5 步进）

- 用户评分（详情星级滑条 / 编辑表单）与来源评分（VNDB/Ymgal 0-100）共用，
  统一在写入前对齐到 0.5 步进；0 表示未评分。
"""
from typing import Optional


def normalize_rating(value) -> Optional[float]:
    """用户评分规范化：0-5、0.5 步进；非法输入（非数字/NaN/越界）返回 None"""
    try:
        r = float(value)
    except (TypeError, ValueError):
        return None
    if r != r or r < 0 or r > 5:  # NaN / 越界
        return None
    return round(r * 2) / 2


def rating_from_100(score) -> float:
    """0-100 分制来源评分 → 0-5 半星制（低于 1 星视为未评分）"""
    try:
        raw = float(score)
    except (TypeError, ValueError):
        return 0.0
    if raw <= 0:
        return 0.0
    r = int(raw / 10 + 0.5) / 2
    return r if r >= 1 else 0.0
