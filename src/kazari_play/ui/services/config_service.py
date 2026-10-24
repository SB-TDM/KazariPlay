"""WebBridge 的配置用例层。"""
from typing import Any, Dict, Optional

from utils.infra.config import Config
from utils.infra.logger import get_logger
from utils.infra.proxy_utils import ProxyConfigError, normalize_proxy_url

logger = get_logger()


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
        if not isinstance(data, dict):
            return {"ok": False, "msg": "配置参数格式错误"}
        # 白名单：只接受已有顶层键；字典值只接受已有子键，防止注入任意配置项
        current = self.cfg.get_all()
        unknown = [k for k in data if k not in current]
        for key in unknown:
            data.pop(key)
        for key, value in list(data.items()):
            if not isinstance(value, dict):
                continue
            old = current.get(key)
            if not isinstance(old, dict):
                data.pop(key)
                continue
            dropped = [k for k in value if k not in old]
            for sub in dropped:
                value.pop(sub)
            unknown.extend(f"{key}.{sub}" for sub in dropped)
        if unknown:
            logger.warning("忽略未知配置项: %s", ", ".join(sorted(unknown)))
        net = data.get("network")
        if isinstance(net, dict):
            mode = str(net.get("proxy_mode") or "system").strip().lower()
            if mode not in ("system", "direct", "custom"):
                return {"ok": False, "msg": "代理模式无效"}
            if mode == "custom":
                try:
                    net["proxy_url"] = normalize_proxy_url(
                        net.get("proxy_url") or "")
                except ProxyConfigError as e:
                    return {"ok": False, "msg": str(e)}
                if not net["proxy_url"]:
                    return {"ok": False, "msg": "自定义代理模式需要填写代理地址"}
            else:
                net["proxy_url"] = str(net.get("proxy_url") or "").strip()
            net["proxy_mode"] = mode
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
