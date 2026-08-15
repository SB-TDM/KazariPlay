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
        "screenshot": "f12",
    },
    "disguise_scene": "excel",
    "auto_scan_on_startup": True,
    "show_console": True,
    "cover_size": "medium",
    "language": "zh-CN",
    "log_level": "INFO",
    "overlay": {
        "enabled": True,
        "exe_path": "",
        "toast_duration": 3.0,
        "position": "bottom_right",
        "subtitle_enabled": True,   # 是否显示字幕（V1.1 新增）
    },
    # Hook 实时翻译（V1.1 新增）
    "textractor": {
        "host_dir": "",             # host.dll + texthook*.dll 所在目录（空 = overlay 目录自动查找）
        "codepage": 0,              # 文本编码：0=引擎默认(Shift-JIS)/932日文/936简体中文/65001 UTF-8
    },
    "translate": {
        "engine": "ai",             # 仅 AI（OpenAI 兼容大模型，默认 DeepSeek）
        "ai": {
            "base_url": "https://api.deepseek.com",   # OpenAI 兼容端点（自动补 /chat/completions）
            "api_key": "",
            "model": "deepseek-chat",
        },
        "source_lang": "ja",
        "target_lang": "zh",
    },
    # 文本清洗（Hook 模式，见 Hook文本清洗策略计划书）
    # 过滤器 override 已改为每游戏（games.clean_filter_override），不再全局配置
    "clean": {
        "ai_assist_enabled": False,  # AI 兜底清洗总开关（过滤器链无法确定的脏文本走 AI）
        "ai_assist_threshold": "dirty",  # 触发阈值：off / dirty(仅脏文本) / always(每条都洗)
    },
    # 元数据多源检索（可在设置页勾选哪些源参与"混合"检索）
    "metadata_sources": {
        "single": "vndb",
        "mixed": ["vndb", "bangumi"],
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
        """递归合并：旧配置缺失的新嵌套字段（如 textractor.codepage）补默认值"""
        out = dict(base)
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = Config._deep_merge(out[k], v)
            else:
                out[k] = v
        return out

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
                # 深合并默认值：旧配置缺失的嵌套新字段自动补默认
                self._data = self._deep_merge(DEFAULT_CONFIG, loaded)
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
