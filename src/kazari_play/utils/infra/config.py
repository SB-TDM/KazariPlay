"""配置读写工具 - 管理 config.json

配置文件默认放在 %APPDATA%\\KazariPlay\\config.json，
首次读取时若不存在则写入默认配置。

用法:
    from utils.infra.config import Config
    cfg = Config()
    theme = cfg.get("theme", "dark")
    cfg.set("theme", "light")
    cfg.save()
"""
import copy
import json
import os
import tempfile
import threading
from typing import Any, Dict, Optional

from utils.infra.path_utils import get_default_config_path
from utils.infra.singleton import singleton


# 默认配置（与 read.md 中 config.json 结构一致）
DEFAULT_CONFIG: Dict[str, Any] = {
    "theme": "light",
    "hotkeys": {
        "emergency_hide": "ctrl+f12",
        "fullscreen_toggle": "f11",
        "mute_toggle": "ctrl+m",
        "screenshot": "f12",
    },
    "disguise_scene": "excel",
    "show_console": True,
    "cover_size": "medium",
    "language": "zh-CN",
    "log_level": "INFO",
    # 网络代理：system=跟随 Windows / direct=直连 / custom=使用 proxy_url
    "network": {
        "proxy_mode": "direct",
        "proxy_url": "",
    },
    "overlay": {
        "enabled": True,
        "exe_path": "",
        "toast_duration": 3.0,
        "position": "bottom_right",
    },
    # 元数据多源检索（可在设置页勾选哪些源参与"混合"检索）
    "metadata_sources": {
        "single": "vndb",
        "mixed": ["vndb", "bangumi", "kungal"],
        "defaults_version": 2,
        "kungal_concurrency": 4,
        "match_concurrency": 4,
        "shionlib_api_key": "",
    },
    # 封面下载（VNDB 封面 CDN 慢，超时/并发可调；并发改动重启生效）
    "cover_download": {
        "timeout": 90,          # 单张封面下载超时（秒）
        "max_concurrent": 4,    # 同时下载的封面数上限
        "preferred_source": "auto",  # auto / vndb / kungal / bangumi / ymgal
    },
}


@singleton
class Config:
    """JSON 配置读写器（单例）

    首次实例化时加载配置文件，不存在则创建并写入默认值。
    修改后需显式调用 save() 才会持久化。
    """

    @staticmethod
    def _deep_merge(base: dict, extra: dict) -> dict:
        """递归合并：补充默认字段并保留旧配置中的扩展数据"""
        out = copy.deepcopy(base)
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = Config._deep_merge(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out

    def __init__(self, config_path: Optional[str] = None):
        # 单例装饰器会复用实例，这里用标志位避免重复初始化
        if getattr(self, "_loaded", False):
            return
        self._path = config_path or get_default_config_path()
        self._data: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._loaded = True
        self.load()

    def load(self) -> None:
        """从磁盘加载配置；文件不存在时写入默认配置"""
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if not isinstance(loaded, dict):
                        raise TypeError("config root must be an object")
                    sources = loaded.get("metadata_sources") or {}
                    legacy_mixed = sources.get("mixed")
                    has_defaults_version = "defaults_version" in sources
                    # 深合并默认值：旧配置缺失的嵌套新字段自动补默认
                    self._data = self._deep_merge(DEFAULT_CONFIG, loaded)
                    if (not has_defaults_version and isinstance(legacy_mixed, list)
                            and legacy_mixed and "kungal" not in legacy_mixed):
                        self._data["metadata_sources"]["mixed"] = [
                            *legacy_mixed, "kungal"]
                        self._data["metadata_sources"]["defaults_version"] = 2
                        self.save()
                except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError):
                    self._data = copy.deepcopy(DEFAULT_CONFIG)
            else:
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self.save()  # 首次创建

    def save(self) -> bool:
        """原子保存配置到磁盘"""
        with self._lock:
            tmp_path = ""
            try:
                parent = os.path.dirname(self._path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(
                    prefix=".config-", suffix=".tmp", dir=parent or ".")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=4)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self._path)
                return True
            except (OSError, TypeError, ValueError):
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
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
        with self._lock:
            parts = key.split(".")
            cur = self._data
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = value

    def get_all(self) -> Dict[str, Any]:
        """返回完整配置字典（只读视图）"""
        with self._lock:
            return copy.deepcopy(self._data)

    def reset(self) -> None:
        """重置为默认配置"""
        with self._lock:
            legacy = {key: copy.deepcopy(self._data[key]) for key in
                      ("translate", "textractor", "clean", "subtitle") if key in self._data}
            legacy_enabled = self.get("overlay.subtitle_enabled")
            self._data = copy.deepcopy(DEFAULT_CONFIG)
            self._data.update(legacy)
            if legacy_enabled is not None:
                self._data["overlay"] = dict(self._data["overlay"])
                self._data["overlay"]["subtitle_enabled"] = legacy_enabled
            self.save()

    @property
    def path(self) -> str:
        """配置文件路径"""
        return self._path
