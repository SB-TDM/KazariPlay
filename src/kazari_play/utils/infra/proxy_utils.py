"""网络代理工具 - 让 urllib 使用系统代理或应用内配置的 HTTP 代理

Python 的 urllib 默认只读环境变量代理（http_proxy/https_proxy），不读 Windows
系统代理（IE/注册表）。本模块支持三种模式：
- system：读取 Windows 系统代理，未配置时退回环境变量/直连
- direct：明确禁用代理
- custom：使用设置页填写的 HTTP/HTTPS 代理

配置保存在 ``network.proxy_mode`` / ``network.proxy_url``。
"""
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

from utils.infra.logger import get_logger

logger = get_logger()

_PROXY_MODES = ("system", "direct", "custom")


class ProxyConfigError(ValueError):
    """代理配置无效。"""


def get_system_proxies() -> dict:
    """读取 Windows 系统代理（HKCU\\Internet Settings），返回 {scheme: proxy}"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enable = 0
        server = ""
        try:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        except OSError:
            pass
        try:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        except OSError:
            pass
        winreg.CloseKey(key)
        if not enable or not server:
            return {}
        server = server.strip()
        if not server:
            return {}
        if "://" not in server:
            server = "http://" + server
        return {"http": server, "https": server}
    except Exception:
        return {}


def get_proxy_config() -> Tuple[str, str]:
    """返回应用配置中的 (模式, 代理地址)。"""
    try:
        from utils.infra.config import Config
        cfg = Config()
        mode = str(cfg.get("network.proxy_mode", "system") or "system").strip().lower()
        proxy_url = str(cfg.get("network.proxy_url", "") or "").strip()
    except Exception:
        return "system", ""
    if mode not in _PROXY_MODES:
        mode = "system"
    return mode, proxy_url


def normalize_proxy_url(proxy_url: str) -> str:
    """校验并规范化 HTTP/HTTPS 代理地址；空串返回空串。"""
    url = str(proxy_url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    try:
        parsed = urllib.parse.urlsplit(url)
        parsed.port
    except ValueError as e:
        raise ProxyConfigError(f"代理地址无效：{e}") from None
    if parsed.scheme not in ("http", "https"):
        raise ProxyConfigError("仅支持 HTTP/HTTPS 代理；SOCKS5 请使用代理软件的混合端口")
    if not parsed.hostname:
        raise ProxyConfigError("代理地址缺少主机名")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ProxyConfigError("代理地址只填写主机和端口，例如 http://127.0.0.1:7897")
    return url


def resolve_proxies(mode: str = "system", proxy_url: str = "",
                    system_proxies: Optional[Dict[str, str]] = None) -> dict:
    """按模式返回 urllib ProxyHandler 使用的代理字典。"""
    mode = (mode or "system").strip().lower()
    if mode not in _PROXY_MODES:
        raise ProxyConfigError(f"未知代理模式：{mode}")
    if mode == "direct":
        return {}
    if mode == "custom":
        url = normalize_proxy_url(proxy_url)
        if not url:
            raise ProxyConfigError("自定义代理模式需要填写代理地址")
        return {"http": url, "https": url}
    proxies = get_system_proxies() if system_proxies is None else system_proxies
    return dict(proxies or {})


def build_opener(mode: Optional[str] = None, proxy_url: Optional[str] = None,
                 system_proxies: Optional[Dict[str, str]] = None):
    """按指定模式构建 opener；不传模式时读取应用配置。"""
    if mode is None:
        mode, proxy_url = get_proxy_config()
    elif proxy_url is None:
        proxy_url = ""
    proxies = resolve_proxies(mode, proxy_url or "", system_proxies)
    if (mode or "").strip().lower() == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if proxies:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener()


def get_opener():
    """返回按当前应用配置构建的 opener；配置无效时退回系统代理。"""
    try:
        return build_opener()
    except ProxyConfigError as e:
        logger.warning("代理配置无效，已退回系统代理：%s", e)
        return build_opener("system")
