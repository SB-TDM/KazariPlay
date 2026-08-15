"""系统代理工具 - 让 urllib 使用 Windows 系统代理

Python 的 urllib 默认只读环境变量代理（http_proxy/https_proxy），不读 Windows
系统代理（IE/注册表）。本机若配置了本地代理（如 Clash 127.0.0.1:7897），
urllib 直连被墙/不可达站点会超时。此模块从注册表读取系统代理并构建 opener。
"""
import urllib.request

from utils.logger import get_logger

logger = get_logger()


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


def get_opener():
    """返回使用系统代理的 opener（无系统代理时退回默认直连）"""
    proxies = get_system_proxies()
    if proxies:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener()
