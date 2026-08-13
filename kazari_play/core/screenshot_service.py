"""截图服务 - Steam 式游戏截图（仅截游戏画面 + 按游戏分文件夹管理）

- 截图目标：游戏窗口（通过进程 PID → 主窗口 → PrintWindow 截取），非全屏
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


# ---------- Win32 窗口截图（只截游戏画面）----------
def _window_rect(hwnd: int):
    """获取窗口矩形 (left, top, right, bottom)"""
    try:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return None


def capture_game_window(pid: int) -> Optional[str]:
    """通过进程 PID 找到主窗口并用 PrintWindow 截取画面，返回临时文件路径"""
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
    rect = _window_rect(hwnd)
    if not rect or rect[2] <= rect[0] or rect[3] <= rect[1]:
        logger.warning("游戏窗口矩形无效，回退全屏截图")
        return None
    left, top, right, bottom = rect
    w, h = right - left, bottom - top

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
    """截取游戏画面（优先窗口截图，失败回退全屏），保存到游戏子文件夹。

    Args:
        game_id: 归属游戏 id（None 时存 _unsorted）
        pid: 游戏进程 PID，用于定位窗口（仅截该窗口画面）

    Returns:
        保存的文件绝对路径（失败返回 None）
    """
    img = None
    if pid:
        img = capture_game_window(pid)
    if img is None:
        # 回退全屏截图
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
