"""时间格式化工具"""
from datetime import datetime
from typing import Optional


def format_play_time(minutes: int) -> str:
    """将分钟数格式化为可读的游玩时长（最大单位到小时，不显示天数）

    Examples:
        0  -> "未游玩"
        30 -> "30 分钟"
        90 -> "1 小时 30 分钟"
        1500 (25h) -> "25 小时"
    """
    if not minutes or minutes <= 0:
        return "未游玩"
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, mins = divmod(minutes, 60)
    # 总游玩时长最大单位到小时，不显示天数（长时游玩直接累计小时）
    return f"{hours} 小时 {mins} 分钟" if mins else f"{hours} 小时"


def format_relative_time(iso_str: str, now: Optional[datetime] = None) -> str:
    """把 ISO 时间格式化为相对时间描述（如 "3 天前"）

    Args:
        iso_str: ISO 格式时间
        now:     当前时间（测试可注入），默认 datetime.now()
    """
    if not iso_str:
        return "从未"
    try:
        dt = datetime.fromisoformat(iso_str.split(".")[0])
    except (ValueError, TypeError):
        return iso_str

    now = now or datetime.now()
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "刚刚"
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 86400 * 30:
        return f"{seconds // 86400} 天前"
    if seconds < 86400 * 365:
        return f"{seconds // (86400 * 30)} 个月前"
    return f"{seconds // (86400 * 365)} 年前"
