"""配置读写工具 - 管理 config.json

配置文件默认放在 %APPDATA%\\KazariPlay\\config.json，
首次读取时若不存在则写入默认配置。

用法:
    from utils.config import Config
    cfg = Config()
    theme = cfg.get("theme", "dark")
    cfg.set("theme", "light")
    cfg.save()
"""
import json
import os
from typing import Any, Dict, Optional

from utils.path_utils import get_default_config_path
from utils.singleton import singleton


# 默认配置（与 read.md 中 config.json 结构一致）
DEFAULT_CONFIG: Dict[str, Any] = {
    "library_paths": [],
    "theme": "light",
    "hotkeys": {
        "emergency_hide": "ctrl+f12",
        "fullscreen_toggle": "f11",
        "mute_toggle": "ctrl+m",
    },
    "disguise_scene": "excel",
    "auto_scan_on_startup": True,
    "show_console": True,
    "cover_size": "medium",
    "language": "zh-CN",
    "log_level": "INFO",
}


@singleton
class Config:
    """JSON 配置读写器（单例）

    首次实例化时加载配置文件，不存在则创建并写入默认值。
    修改后需显式调用 save() 才会持久化。
    """

    def __init__(self, config_path: Optional[str] = None):
        # 单例装饰器会复用实例，这里用标志位避免重复初始化
        if getattr(self, "_loaded", False):
            return
        self._path = config_path or get_default_config_path()
        self._data: Dict[str, Any] = {}
        self._loaded = True
        self.load()

    def load(self) -> None:
        """从磁盘加载配置；文件不存在时写入默认配置"""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 合并默认值（保证新字段有默认值，旧配置不丢字段）
                self._data = {**DEFAULT_CONFIG, **loaded}
            except (json.JSONDecodeError, OSError):
                self._data = DEFAULT_CONFIG.copy()
        else:
            self._data = DEFAULT_CONFIG.copy()
            self.save()  # 首次创建

    def save(self) -> bool:
        """保存配置到磁盘"""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=4)
            return True
        except OSError:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """读取配置项，支持嵌套键（如 'hotkeys.emergency_hide'）"""
        parts = key.split(".")
        cur = self._data
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur

    def set(self, key: str, value: Any) -> None:
        """写入配置项，支持嵌套键"""
        parts = key.split(".")
        cur = self._data
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value

    def get_all(self) -> Dict[str, Any]:
        """返回完整配置字典（只读视图）"""
        return dict(self._data)

    def reset(self) -> None:
        """重置为默认配置"""
        self._data = DEFAULT_CONFIG.copy()
        self.save()

    @property
    def path(self) -> str:
        """配置文件路径"""
        return self._path
