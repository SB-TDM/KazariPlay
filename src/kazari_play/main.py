"""KazariPlay - 视觉小说启动器 GUI 入口（pywebview）

Copyright (C) 2026 KazariPlay 贡献者

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

用法:
    python src/kazari_play/main.py            （在项目根目录下）

窗口为无边框（frameless）+ 系统 WebView（Edge WebView2）渲染 HTML UI，
前后端通过 pywebview js_api（WebBridge）桥接。

注意：index.html 的 css/js 在启动时内联注入（html= 模式），
彻底规避中文路径下 file:// 加载 404 / "未找到文件" 的问题。
"""
import os
import re
import sys
import ctypes
import threading
import time
from html import escape

import webview

from core.games.game_manager import GameManager
from ui.web_bridge import WebBridge
from utils.infra.config import Config
from utils.infra.logger import get_logger, set_level
from version import DISPLAY_VERSION, PRODUCT_LINE, WINDOW_TITLE

logger = get_logger()

# 进程内入口时刻（不含 PyInstaller bootloader；用于「入口→窗口就绪/前端就绪」埋点）
_PROCESS_T0 = time.monotonic()


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


# JS 模块加载清单（按依赖顺序，勿随意调整；每项对应 ui/web_assets/js/ 下的文件）
# 顶部 let/const/function 在多个经典 <script> 块间共享，等价于"按文件拆分的单文件脚本"。
_JS_MANIFEST = [
    "state.js",        # 全局共享状态（无依赖，最先加载）
    "icons.js",        # 内联 SVG 图标库（无依赖）
    "core.js",         # bridge 代理 + 通用工具（esc/toast/loadCoverTo）
    "ui.js",           # Sheet / 通用对话框 / 右键菜单基础设施
    "window.js",       # 标题栏拖拽 / 缩放 / 最大化
    "games.js",        # 游戏数据 / 筛选 / 整体渲染调度 + 卡片状态
    "cards.js",        # 卡片 DOM 构建 / 增量渲染（懒加载）/ 右键菜单
    "detail.js",       # 详情底部抽屉
    "screenshots.js",  # 截图卡片 / 预览 / 右键管理
    "collections.js",  # 收藏夹树 / 收藏夹管理抽屉
    "manage_games.js", # 管理游戏对话框（批量勾选收藏夹内游戏）
    "batch.js",        # 批量选择模式
    "form.js",         # 编辑 / 添加表单 + 元数据候选
    "settings-model.js", # 设置配置模型 / 默认值
    "settings-theme.js", # 设置主题状态与预览
    "settings-hotkeys.js", # 设置快捷键录制与键帽
    "settings-sources.js", # 设置元数据源列表
    "settings-fields.js", # 设置表单字段与代理测试
    "settings.js",     # 设置窗口外壳（暴露 window.Settings）
    "updater.js",      # 应用内更新（关于页接线 / 更新弹层 / 启动检查）
    "home.js",         # 主页视图（问候/继续游玩/统计/收藏夹快捷，默认视图）
    "app.js",          # 启动引导（最后加载，负责粘合各模块与全局事件）
]

# HTML 分块清单（各窗口/对话框独立文件，注入到 index.html 的 <!-- PARTIALS --> 标记处；
# 顺序即 DOM 顺序，全部 .overlay 同为 z-index:100，靠 DOM 顺序决定层叠）
_PARTIAL_MANIFEST = [
    "detail.html",      # 详情抽屉 + 截图预览 + 截图右键菜单
    "collections.html", # 收藏夹管理 + 管理游戏对话框
    "form.html",        # 编辑 / 添加表单
    "settings.html",    # 设置窗口
    "update.html",      # 应用内更新弹层
    "relocate.html",    # 批量重新定位预览对话框
    "meta_apply.html",  # 元数据候选字段选择对话框
    "common.html",      # 通用输入 / 确认 / 选择器对话框（放最后，确保盖在其它 overlay 之上）
]


def _load_html(initial_theme: str = "light") -> str:
    """读取 index.html 并把 css / js 模块 / 分块 html 内联，避免外部相对资源加载问题"""
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ui", "web_assets")

    def read(rel: str) -> str:
        with open(os.path.join(assets, rel), encoding="utf-8") as f:
            return f.read()

    html = read("index.html")
    theme = initial_theme if initial_theme in ("light", "dark") else "light"
    html = html.replace("{{THEME}}", theme)

    # 1) 注入分块 HTML（各窗口/对话框独立文件，便于维护）
    partials = "\n".join(
        read(os.path.join("partials", name)) for name in _PARTIAL_MANIFEST)
    html = html.replace("<!-- PARTIALS -->", partials)

    # 2) 注入 JS 模块（按清单顺序内联为多个 <script> 块）
    scripts = "\n".join(
        f"<script>\n{read(os.path.join('js', name))}\n</script>"
        for name in _JS_MANIFEST)
    html = html.replace("<!-- SCRIPTS -->", scripts)

    # 3) css 内联（递归展开 @import：style.css 作为 @import 入口时，
    #    pywebview html= 模式无 base URL，浏览器无法解析 @import 相对路径，
    #    故在此把所有 @import 替换为对应文件内容，最终单 <style> 内联）
    #    支持 @import url("x.css") layer(name)，展开为 @layer name { ... }
    def _expand_imports(css_text: str) -> str:
        pat = re.compile(
            r'@import\s+url\(\s*["\']?([^"\')]+)["\']?\s*\)\s*'
            r'(?:layer\(\s*([^)]+?)\s*\))?\s*;')
        def repl(m):
            rel = m.group(1)
            try:
                expanded = _expand_imports(read(os.path.join("css", rel)))
            except FileNotFoundError:
                return m.group(0)  # 找不到则保留原 @import，让浏览器报错便于排查
            layer = (m.group(2) or "").strip()
            return f"@layer {layer}{{\n{expanded}\n}}" if layer else expanded
        return pat.sub(repl, css_text)
    css = _expand_imports(read(os.path.join("css", "style.css")))
    html = html.replace('<link rel="stylesheet" href="css/style.css">',
                        "<style>" + css + "</style>")

    # 4) 笑脸占位符 → 真实图标（data URI，保留圆角）
    icon = _icon_data_uri()
    if icon:
        img = f'<img class="logo-img" src="{icon}" alt="">'
        html = html.replace('<div class="logo">☺</div>',
                            f'<div class="logo">{img}</div>')
        html = html.replace('<div class="a-logo">☺</div>',
                            f'<div class="a-logo">{img}</div>')
    html = html.replace("{{APP_VERSION}}", escape(DISPLAY_VERSION))
    html = html.replace("{{PRODUCT_LINE}}", escape(PRODUCT_LINE))
    html = html.replace("{{APP_TITLE}}", escape(WINDOW_TITLE))
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
        logger.info("启动耗时：入口→窗口就绪=%.2fs", time.monotonic() - _PROCESS_T0)
        if hwnd:
            _ensure_minimize_style(hwnd)
            _apply_icon_win32(hwnd)
            logger.info("窗口样式/图标已设置, hwnd=%s", hwnd)
        else:
            logger.warning("未找到窗口句柄，跳过样式/图标设置")

    threading.Timer(1.0, _do).start()


def _start_screenshot_hotkey(bridge):
    """注册全局截图热键（默认 F12），失败静默降级。

    注册逻辑在 utils/system/hotkeys.py（keyboard 库自带钩子线程，无需额外 wait）；
    用户在设置里修改热键后，经 WebBridge.updateScreenshotHotkey 重新注册，立即生效。
    """
    from utils.system.hotkeys import register_screenshot_hotkey
    register_screenshot_hotkey(lambda: bridge.takeScreenshotRunning())


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
    logger.info("启动 KazariPlay %s (%s, pywebview)", DISPLAY_VERSION, PRODUCT_LINE)

    # WebView2 依赖显式检测（缺失时给明确指引，避免 pywebview 原始报错）
    from utils.infra.path_utils import get_app_data_dir
    from utils.update.update_apply import (cleanup_stale_new_files, cleanup_update_cache,
                                    current_install_dir, ensure_webview2,
                                    has_pending_update_state, startup_self_heal)
    if not ensure_webview2():
        return

    # 更新残留自愈：替换中断回滚 / 新版确认计数 / 回滚提示（见 docs/dev/AUTO_UPDATE_DESIGN.md §6）
    update_notice, update_exit = startup_self_heal(get_app_data_dir())
    if update_exit:
        # 回滚助手已拉起：本进程立即退出，由助手等待退出后恢复旧版并重新启动
        os._exit(0)
    # 清理中断现场可能残留的根级 *.new（无状态时也兜底一次）
    cleanup_stale_new_files(current_install_dir())
    # 待回滚/待确认期间保留解压缓存（回滚助手需要）；其余情况照常清理（就绪缓存 zip 保留）
    cleanup_update_cache(get_app_data_dir(),
                         keep_extract=has_pending_update_state(get_app_data_dir()))

    manager = GameManager()
    from core.media.cover_store import CoverStore
    from ui.services.cover_service import CoverService
    cover_store = CoverStore()
    cover_service = CoverService(cover_store)
    cover_service.start()   # 失败/禁用时 bridge 自动回退 base64
    bridge = WebBridge(manager, cover_store=cover_store,
                       cover_service=cover_service if cover_service.started else None)
    # 后台迁移旧封面路径并清理未引用文件（不阻塞启动）
    try:
        import threading as _threading
        _threading.Thread(target=bridge.cleanup_unused_covers, daemon=True).start()
    except Exception:
        pass
    bridge._start_ts = _PROCESS_T0   # 供「入口→前端就绪」埋点
    if update_notice:
        try:
            bridge.set_update_notice(update_notice)
        except Exception:
            pass

    _start_screenshot_hotkey(bridge)

    sw, sh = _screen_size()
    w, h = int(sw * 0.75), int(sh * 0.75)
    win = webview.create_window(
        WINDOW_TITLE,
        html=_load_html(str(cfg.get("theme", "light") or "light")),
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

    # 窗口关闭（任意路径：✕ / Alt+F4 / 任务管理器 / 系统关闭）时退出 overlay.exe，
    # 避免独立 overlay 进程残留
    def _on_window_closing():
        try:
            cover_service.stop()
        except Exception:
            pass
        try:
            overlay = getattr(bridge, "_overlay_client", None)
            if overlay is not None:
                overlay.quit()
        except Exception:
            pass
    try:
        win.events.closing += _on_window_closing
    except Exception:
        pass

    # 设置窗口/任务栏图标（.ico 优先，Windows 任务栏需 ICO 格式）
    res = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
    icon_path = os.path.join(res, "app_icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(res, "app_icon.png")
    if os.path.exists(icon_path):
        win.icon = icon_path

    # 截图 toast 由独立 C++ overlay.exe 进程接管（首次截图时惰性拉起）

    webview.start(func=lambda: _apply_window_extras(bridge), debug=False)


if __name__ == "__main__":
    if "--apply-update" in sys.argv:
        # 替换助手模式（由更新流程拉起；无窗口、不进入常规启动）
        from utils.update.update_apply import run_apply_update
        sys.exit(run_apply_update(sys.argv))
    if "--apply-rollback" in sys.argv:
        # 回滚助手模式（由启动自愈拉起；等待当前进程退出后恢复旧版并重启）
        from utils.update.update_apply import run_apply_rollback
        sys.exit(run_apply_rollback(sys.argv))
    main()
