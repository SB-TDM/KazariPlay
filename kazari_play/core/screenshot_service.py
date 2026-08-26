"""截图服务 - Steam 式游戏截图（仅截游戏画面 + 按游戏分文件夹管理）

- 截图目标：游戏窗口（通过进程 PID → 主窗口 → WGC/PrintWindow 截取），非全屏
- 捕获内核：优先 Windows Graphics Capture（WGC，兼容 D3D/Vulkan 独占渲染），
  失败/不可用时回退 PrintWindow（GDI），再失败回退全屏 ImageGrab
- 存储：项目目录 screenshots/{game_id}/shot_{时间戳}.png
- 归属：截屏时若检测到运行中的游戏，归入该游戏子文件夹；否则存 _unsorted/
- 触发：由 main.py 全局热键监听调用（webview 不提供全局热键）
"""
import os
import ctypes
from ctypes import wintypes
from datetime import datetime
from typing import List, Optional, Dict

from utils.path_utils import get_game_screenshots_dir, get_screenshots_dir
from utils.logger import get_logger

logger = get_logger()

# WGC 抓帧等待超时（秒）：创建 GraphicsCaptureItem/会话可能较慢，超时即回退
_WGC_TIMEOUT = 8.0


# ---------- Windows Graphics Capture（WGC）窗口截图 ----------
def _process_dpi_aware() -> bool:
    """进程是否 DPI-aware（决定 ClientToScreen 返回逻辑还是物理像素）"""
    try:
        awareness = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
        return awareness.value != 0   # 0=unaware, 1=system, 2=per-monitor
    except Exception:
        return False


def _client_physical_offset(hwnd: int) -> tuple:
    """计算客户区相对窗口左上角的物理像素偏移（标题栏+边框高度/宽度）。

    用于把 WGC 整窗帧裁剪到客户区，使输出尺寸与 PrintWindow 客户区路径对齐。
    WGC 帧是物理像素；偏移计算需与进程 DPI 感知状态一致：
      - DPI-aware：ClientToScreen 返回物理像素，直接与 DWM 扩展边框相减
      - DPI-unaware：ClientToScreen 返回逻辑像素，按 GetDpiForWindow 换算物理
    错误地双重缩放会导致低分辨率下裁剪过多（已实测踩坑）。

    返回 (top_off, left_off)，物理像素；查询失败返回 (0, 0)（不裁剪）。
    """
    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        # 客户区左上角屏幕坐标
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        # 真实窗口边框（DWM 扩展边框，物理像素，不含阴影）
        er = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(er), ctypes.sizeof(er))  # DWMWA_EXTENDED_FRAME_BOUNDS=9
        if hr != 0:
            return (0, 0)   # 查询失败不裁剪
        scale = user32.GetDpiForWindow(hwnd) / 96.0
        if _process_dpi_aware():
            top_off = pt.y - er.top
            left_off = pt.x - er.left
        else:
            top_off = pt.y * scale - er.top
            left_off = pt.x * scale - er.left
        return (max(0, int(round(top_off))), max(0, int(round(left_off))))
    except Exception:
        return (0, 0)


def _capture_via_wgc(pid: int) -> Optional["Image.Image"]:
    """用 WGC 按窗口捕获单帧（兼容 D3D/Vulkan 独占渲染的全屏游戏）

    依赖 windows-capture 库（可选）：缺失/失败返回 None，由调用方回退 PrintWindow。
    每次截图新建 capture 实例（抓一帧即 stop，实例不可复用）；
    在独立线程跑消息循环，主线程等帧到达或超时。
    捕获后按客户区偏移裁剪（去掉标题栏/边框），输出与 PrintWindow 客户区尺寸对齐。
    """
    try:
        import threading
        from PIL import Image
        from windows_capture import WindowsCapture
    except ImportError:
        logger.warning("windows-capture 未安装，WGC 捕获不可用，回退 PrintWindow")
        return None

    hwnd = find_main_window_by_pid(pid)
    if not hwnd:
        return None

    result: Dict[str, object] = {"img": None, "err": ""}
    got = threading.Event()

    try:
        capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False)

        @capture.event
        def on_frame_arrived(frame, control):
            try:
                bgra = frame.frame_buffer   # BGRA numpy (h, w, 4)，物理像素
                # BGRA -> RGB：取 BGR 三通道反转，丢弃 alpha。
                # 注意不能整体 [:, :, ::-1]（会得到 ARGB 通道错位 → 反相色调）
                img = Image.fromarray(bgra[:, :, [2, 1, 0]])
                # 裁剪到客户区（去掉标题栏/边框），与 PrintWindow 客户区路径对齐
                top_off, left_off = _client_physical_offset(hwnd)
                if (top_off or left_off) and top_off < img.height and left_off < img.width:
                    img = img.crop((left_off, top_off, img.width, img.height))
                result["img"] = img
            except Exception as e:
                result["err"] = str(e)
            control.stop()
            got.set()

        @capture.event
        def on_closed():
            pass

        def _run():
            try:
                capture.start()   # 阻塞消息循环，单独线程
            except Exception as e:
                result["err"] = str(e)
                got.set()

        threading.Thread(target=_run, daemon=True).start()
        if not got.wait(_WGC_TIMEOUT):
            logger.warning("WGC 抓帧超时 (pid=%s)，回退 PrintWindow", pid)
            return None
    except Exception as e:
        logger.warning("WGC 捕获失败 (pid=%s): %s，回退 PrintWindow", pid, e)
        return None

    if result["err"]:
        logger.warning("WGC 抓帧异常 (pid=%s): %s，回退 PrintWindow", pid, result["err"])
        return None
    return result["img"] if result["img"] is not None else None


# ---------- Win32 窗口截图（只截游戏画面）----------
def capture_game_window(pid: int) -> Optional["Image.Image"]:
    """通过进程 PID 找到主窗口并用 PrintWindow 截取画面，返回 PIL Image"""
    try:
        from PIL import Image
    except ImportError:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 找该进程的主窗口（EnumWindows 遍历）
    hwnd = find_main_window_by_pid(pid)
    if not hwnd:
        logger.warning("未找到游戏窗口 (pid=%s)，回退全屏截图", pid)
        return None
    # 用客户区尺寸（游戏画面实际大小）。GetWindowRect 会包含边框/阴影，
    # 与 PrintWindow 的 PW_CLIENTONLY 渲染范围不匹配，导致底部黑边
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    w = client.right - client.left
    h = client.bottom - client.top
    if w <= 0 or h <= 0:
        logger.warning("游戏窗口矩形无效，回退全屏截图")
        return None

    # PrintWindow 截取窗口内容（即使被遮挡也能捕获）
    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, 3)  # PW_RENDERFULLCONTENT
    except Exception:
        ok = user32.PrintWindow(hwnd, hdc_mem, 0)
    gdi32.SelectObject(hdc_mem, old)

    # 从 DIB 读取像素到 PIL Image
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # 负值表示自顶向下
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)

    if not ok:
        return None
    # 转 PIL Image（BGRA → RGB）
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    return img


def find_main_window_by_pid(pid: int) -> int:
    """枚举窗口找到指定 PID 的主窗口（优先非子窗口、可见、有标题的）"""
    user32 = ctypes.windll.user32
    result = [0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, lparam):
        # 检查窗口归属进程
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value != pid:
            return True
        # 跳过子窗口，只要顶层窗口
        if user32.GetParent(hwnd):
            return True
        # 优先可见且有标题的窗口
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        result[0] = hwnd
        return False

    user32.EnumWindows(callback, 0)
    return result[0]


def take_screenshot(game_id: Optional[str] = None, pid: Optional[int] = None) -> Optional[str]:
    """截取游戏画面（三级回退：WGC → PrintWindow → 全屏），保存到游戏子文件夹。

    捕获内核：
      ① WGC（windows-capture，按窗口捕获，兼容 D3D/Vulkan 独占渲染）
      ② PrintWindow（GDI，窗口被遮挡/最小化时仍能取到 GDI 内容）
      ③ ImageGrab.grab()（全屏兜底）

    Args:
        game_id: 归属游戏 id（None 时存 _unsorted）
        pid: 游戏进程 PID，用于定位窗口（仅截该窗口画面）

    Returns:
        保存的文件绝对路径（失败返回 None）
    """
    img = None
    if pid:
        img = _capture_via_wgc(pid)   # ① WGC（兼容独占渲染，黑屏问题主修）
    if img is None and pid:
        img = capture_game_window(pid)   # ② PrintWindow（GDI 兜底，被遮挡窗口可用）
    if img is None:
        # ③ 全屏兜底
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
        except Exception as e:
            logger.error("全屏截屏失败: %s", e)
            return None

    folder = get_game_screenshots_dir(game_id) if game_id else os.path.join(
        get_screenshots_dir(), "_unsorted")
    os.makedirs(folder, exist_ok=True)
    filename = f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(folder, filename)
    try:
        img.save(path, "PNG")
        logger.info("截图已保存: %s", path)
        return path
    except Exception as e:
        logger.error("保存截图失败: %s", e)
        return None


def get_screenshots(game_id: str) -> List[Dict]:
    """列出某游戏的全部截图（按时间倒序）"""
    folder = get_game_screenshots_dir(game_id)
    shots = []
    try:
        for f in sorted(os.listdir(folder), reverse=True):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and f.lower().endswith((".png", ".jpg", ".jpeg")):
                shots.append({
                    "file": f,
                    "path": p,
                    "created": _extract_time(f),
                })
    except OSError as e:
        logger.error("读取截图目录失败: %s", e)
    return shots


def _extract_time(filename: str) -> str:
    """从文件名 shot_20260811_201530.png 提取时间；失败返回空"""
    try:
        s = filename.replace("shot_", "").replace(".png", "")
        dt = datetime.strptime(s, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def rename_screenshot(game_id: str, filename: str, new_name: str) -> bool:
    """重命名截图文件（保留扩展名）"""
    folder = get_game_screenshots_dir(game_id)
    src = os.path.normpath(os.path.join(folder, filename))
    if not src.startswith(os.path.normpath(folder) + os.sep) or not os.path.isfile(src):
        return False
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    ext = os.path.splitext(src)[1] or ".png"
    if not new_name.lower().endswith((".png", ".jpg", ".jpeg")):
        new_name += ext
    dst = os.path.normpath(os.path.join(folder, new_name))
    if not dst.startswith(os.path.normpath(folder) + os.sep):
        return False
    try:
        os.rename(src, dst)
        return True
    except OSError as e:
        logger.error("重命名截图失败: %s", e)
        return False


def delete_screenshot(game_id: str, filename: str) -> bool:
    """删除指定截图（仅允许删除 screenshots 目录内的文件，防路径穿越）"""
    folder = get_game_screenshots_dir(game_id)
    path = os.path.normpath(os.path.join(folder, filename))
    if not path.startswith(os.path.normpath(folder) + os.sep):
        logger.warning("拒绝删除越界文件: %s", filename)
        return False
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info("已删除截图: %s", path)
            return True
    except OSError as e:
        logger.error("删除截图失败: %s", e)
    return False
