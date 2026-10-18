"""WebBridge 的配置用例层。"""
from typing import Any, Dict, Optional

from utils.infra.config import Config


class ConfigService:
    """封装配置读取/写入，WebBridge 只做协议转换。"""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config()

    def get_public_config(self) -> Dict[str, Any]:
        data = self.cfg.get_all()
        for key in ("translate", "textractor", "clean", "subtitle"):
            data.pop(key, None)
        data["overlay"] = dict(data.get("overlay", {}))
        data["overlay"].pop("subtitle_enabled", None)
        data["path"] = self.cfg.path
        return data

    def save(self, data: dict) -> Dict[str, Any]:
        for key, value in data.items():
            if isinstance(value, dict):
                old = self.cfg.get(key)
                if isinstance(old, dict):
                    merged = dict(old)
                    merged.update(value)
                    value = merged
            self.cfg.set(key, value)
        if not self.cfg.save():
            return {"ok": False, "msg": "配置保存失败，请检查磁盘权限"}
        return {"ok": True}

    def reset(self) -> None:
        self.cfg.reset()

    def set_theme(self, theme: str) -> None:
        if theme:
            self.cfg.set("theme", theme)
            self.cfg.save()
