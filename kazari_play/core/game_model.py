"""游戏数据模型 - Game 类定义"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Game:
    """游戏数据类

    封装一款 Galgame 的全部元信息，支持与数据库行互相转换。
    """
    id: str = ""
    title: str = ""
    exe_path: str = ""
    folder: str = ""
    cover_path: str = ""
    engine: str = ""
    tags: List[str] = field(default_factory=list)
    is_favorite: bool = False
    play_count: int = 0
    play_time: int = 0           # 总游玩时长（分钟）
    last_played: str = ""        # ISO 格式
    date_added: str = ""         # ISO 格式，空时由数据库填 CURRENT_TIMESTAMP
    rating: int = 0              # 1-5，0 表示未评分
    logo_path: str = ""          # Logo 图片路径（叠加在封面上）
    description: str = ""        # 游戏描述/简介
    launch_exe_path: str = ""    # 自定义启动 exe 路径（为空时回退到 exe_path）
    # VNDB 元数据字段（v2 新增，VNDB 匹配后填充）
    vndb_id: str = ""            # VNDB 作品 ID，如 "v1234"
    released: str = ""           # 发售日 ISO 格式（YYYY-MM-DD）
    developer: str = ""          # 开发商名称
    length_minutes: int = 0      # 预计游玩时长（分钟，VNDB length 字段转换）
    category_id: int = 0         # 分类归属（0 = 未分类；v2.4 新增）

    def to_dict(self) -> dict:
        """序列化为字典（供 repository 写入数据库使用）"""
        return {
            "id": self.id,
            "title": self.title,
            "exe_path": self.exe_path,
            "folder": self.folder,
            "cover_path": self.cover_path or "",
            "engine": self.engine or "",
            "tags": ",".join(self.tags) if self.tags else "",
            "is_favorite": 1 if self.is_favorite else 0,
            "play_count": self.play_count,
            "play_time": self.play_time,
            "last_played": self.last_played or "",
            "date_added": self.date_added or "",
            "rating": self.rating,
            "logo_path": self.logo_path or "",
            "description": self.description or "",
            "launch_exe_path": self.launch_exe_path or "",
            "vndb_id": self.vndb_id or "",
            "released": self.released or "",
            "developer": self.developer or "",
            "length_minutes": self.length_minutes or 0,
            "category_id": self.category_id or 0,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Game":
        """从字典反序列化"""
        tags = data.get("tags", "")
        if isinstance(tags, str):
            tags = [t for t in tags.split(",") if t] if tags else []
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            exe_path=data.get("exe_path", ""),
            folder=data.get("folder", ""),
            cover_path=data.get("cover_path", "") or "",
            engine=data.get("engine", "") or "",
            tags=tags,
            is_favorite=bool(data.get("is_favorite", 0)),
            play_count=data.get("play_count", 0) or 0,
            play_time=data.get("play_time", 0) or 0,
            last_played=data.get("last_played", "") or "",
            date_added=data.get("date_added", "") or "",
            rating=data.get("rating", 0) or 0,
            logo_path=data.get("logo_path", "") or "",
            description=data.get("description", "") or "",
            launch_exe_path=data.get("launch_exe_path", "") or "",
            vndb_id=data.get("vndb_id", "") or "",
            released=data.get("released", "") or "",
            developer=data.get("developer", "") or "",
            length_minutes=data.get("length_minutes", 0) or 0,
            category_id=data.get("category_id", 0) or 0,
        )

    def add_tag(self, tag: str) -> None:
        """新增标签（去重）"""
        if tag and tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """移除标签"""
        if tag in self.tags:
            self.tags.remove(tag)

    def format_play_time(self) -> str:
        """将 play_time（分钟）格式化为可读字符串"""
        minutes = self.play_time
        if minutes < 60:
            return f"{minutes} 分钟"
        hours, mins = divmod(minutes, 60)
        if hours < 24:
            return f"{hours} 小时 {mins} 分钟"
        days, hours = divmod(hours, 24)
        return f"{days} 天 {hours} 小时"

    def __str__(self) -> str:
        fav = "★" if self.is_favorite else " "
        return f"[{fav}] {self.title}  ({self.engine})  -  {self.format_play_time()}"
