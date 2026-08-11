"""KazariPlay V1.01 - 视觉小说启动器 GUI 入口（pywebview）

用法:
    python main.py            （在 KazariPlay_V1.0 目录下）

窗口为无边框（frameless）+ 系统 WebView（Edge WebView2）渲染 HTML UI，
前后端通过 pywebview js_api（WebBridge）桥接。

注意：index.html 的 css/js 在启动时内联注入（html= 模式），
彻底规避中文路径下 file:// 加载 404 / "未找到文件" 的问题。
"""
import os
import sys
import ctypes

import webview

from core.game_manager import GameManager
from ui.web_bridge import WebBridge
from utils.config import Config
from utils.logger import get_logger, set_level

logger = get_logger()


def _icon_data_uri() -> str:
    """读取 app 图标为 data URI（html= 模式下 img 无法用 file://）"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "resources", "app_icon.png")
    if not os.path.exists(p):
        return ""
    import base64
    try:
        with open(p, "rb") as f:
            data = f.read()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


def _load_html() -> str:
    """读取 index.html 并把 css/js 内联，避免外部相对资源加载问题"""
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ui", "web_assets")

    def read(name: str) -> str:
        with open(os.path.join(assets, name), encoding="utf-8") as f:
            return f.read()

    html = read("index.html")
    css = read(os.path.join("css", "style.css"))
    setjs = read(os.path.join("js", "settings.js"))
    appjs = read(os.path.join("js", "app.js"))
    html = html.replace('<link rel="stylesheet" href="css/style.css">',
                        "<style>" + css + "</style>")
    html = html.replace('<script src="js/settings.js"></script>',
                        "<script>" + setjs + "</script>")
    html = html.replace('<script src="js/app.js"></script>',
                        "<script>" + appjs + "</script>")
    # 笑脸占位符 → 真实图标（data URI，保留圆角）
    icon = _icon_data_uri()
    if icon:
        img = f'<img class="logo-img" src="{icon}" alt="">'
        html = html.replace('<div class="logo">☺</div>',
                            f'<div class="logo">{img}</div>')
        html = html.replace('<div class="a-logo">☺</div>',
                            f'<div class="a-logo">{img}</div>')
    return html


def _screen_size() -> tuple:
    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def _hide_console():
    """按配置隐藏控制台窗口（启动时不显示命令提示符）"""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _ensure_minimize_style(hwnd):
    """确保窗口含 WS_MINIMIZEBOX，支持点击任务栏按钮最小化"""
    if os.name != "nt" or not hwnd:
        return
    try:
        import ctypes
        GWL_STYLE = -16
        WS_MINIMIZEBOX = 0x00020000
        fn = getattr(ctypes.windll.user32, "GetWindowLongPtrW",
                     ctypes.windll.user32.GetWindowLongW)
        set_fn = getattr(ctypes.windll.user32, "SetWindowLongPtrW",
                         ctypes.windll.user32.SetWindowLongW)
        style = fn(hwnd, GWL_STYLE)
        if style and not (style & WS_MINIMIZEBOX):
            set_fn(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX)
    except Exception:
        pass


def _apply_icon_win32(hwnd):
    """Win32 直接设置窗口图标（任务栏/Alt+Tab/标题栏）"""
    if os.name != "nt" or not hwnd:
        return
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "resources", "app_icon.ico")
    if not os.path.exists(ico):
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x10
        WM_SETICON = 0x80
        h_big = user32.LoadImageW(None, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        h_small = user32.LoadImageW(None, ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, h_big)   # ICON_BIG
        if h_small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, h_small)  # ICON_SMALL（任务栏）
    except Exception as e:
        logger.warning("设置窗口图标失败: %s", e)


def _apply_window_extras(bridge):
    """窗口显示后延迟确保任务栏最小化样式与窗口图标（等 hwnd 就绪）"""
    import threading

    def _do():
        hwnd = bridge._win32_hwnd()
        if hwnd:
            _ensure_minimize_style(hwnd)
            _apply_icon_win32(hwnd)
            logger.info("窗口样式/图标已设置, hwnd=%s", hwnd)
        else:
            logger.warning("未找到窗口句柄，跳过样式/图标设置")

    threading.Timer(1.0, _do).start()


def main():
    cfg = Config()
    set_level(cfg.get("log_level", "INFO"))
    # 关闭日志窗口时隐藏控制台
    if not cfg.get("show_console", True):
        _hide_console()
    # 降低 WebView2 内存占用：单页应用限制渲染进程数、关闭 GPU 合成与无关特性
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        "--disable-gpu-compositing "
        "--renderer-process-limit=1 "
        "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreen"
    )
    logger.info("启动 KazariPlay (pywebview)")

    manager = GameManager()
    bridge = WebBridge(manager)

    sw, sh = _screen_size()
    w, h = int(sw * 0.82), int(sh * 0.82)
    win = webview.create_window(
        "KazariPlay",
        html=_load_html(),
        js_api=bridge,
        frameless=True,
        easy_drag=False,
        width=w,
        height=h,
        x=(sw - w) // 2,          # 屏幕居中
        y=(sh - h) // 2,
        min_size=(900, 620),
    )
    bridge.bind_window(win)
    # 设置窗口/任务栏图标（.ico 优先，Windows 任务栏需 ICO 格式）
    res = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
    icon_path = os.path.join(res, "app_icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(res, "app_icon.png")
    if os.path.exists(icon_path):
        win.icon = icon_path
    bridge.startAutoScan()          # 启动时自动扫描 library_paths
    webview.start(func=lambda: _apply_window_extras(bridge), debug=False)


if __name__ == "__main__":
    main()
