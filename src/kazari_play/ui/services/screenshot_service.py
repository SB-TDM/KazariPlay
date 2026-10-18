"""截图文件用例：列表、原图、删除、重命名、定位、复制。"""
import base64
import io
import os

from core.media import screenshot_service as core_screenshots
from utils.infra.logger import get_logger

logger = get_logger()

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "bmp": "image/bmp"}


class ScreenshotService:
    def list(self, game_id: str) -> list:
        return core_screenshots.get_screenshots(game_id)

    def _path(self, game_id: str, filename: str) -> str:
        for shot in core_screenshots.get_screenshots(game_id):
            if shot["file"] == filename:
                return shot["path"] if os.path.exists(shot["path"]) else ""
        return ""

    def original(self, game_id: str, filename: str) -> str:
        path = self._path(game_id, filename)
        if not path:
            return ""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if len(raw) > 8 * 1024 * 1024:
                return ""
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            mime = _MIME.get(ext, "image/png")
            return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        except Exception:
            return ""

    def delete(self, game_id: str, filename: str) -> bool:
        return core_screenshots.delete_screenshot(game_id, filename)

    def rename(self, game_id: str, filename: str, new_name: str) -> bool:
        return core_screenshots.rename_screenshot(game_id, filename, new_name)

    def open_folder(self, game_id: str, filename: str) -> bool:
        path = self._path(game_id, filename)
        if not path:
            return False
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select," + path])
            else:
                import webbrowser
                webbrowser.open(os.path.dirname(path))
            return True
        except Exception as e:
            logger.error("定位截图失败: %s", e)
            return False

    def copy_to_clipboard(self, game_id: str, filename: str) -> bool:
        path = self._path(game_id, filename)
        if not path:
            return False
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "BMP")
            dib = buf.getvalue()[14:]
        except Exception as e:
            logger.error("读取截图失败: %s", e)
            return False
        return self._set_clipboard_dib(dib)

    @staticmethod
    def _set_clipboard_dib(data: bytes) -> bool:
        """把 CF_DIB 位图数据写入系统剪贴板（DIB = BMP 去掉 14 字节文件头）"""
        try:
            import ctypes
            if os.name != "nt":
                return False
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            CF_DIB = 8
            GMEM_MOVEABLE = 0x0002
            kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_bool
            user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            if not user32.OpenClipboard(None):
                return False
            try:
                user32.EmptyClipboard()
                size = len(data)
                hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                if not hmem:
                    return False
                ptr = kernel32.GlobalLock(hmem)
                if not ptr:
                    kernel32.GlobalFree(hmem)
                    return False
                ctypes.memmove(ptr, data, size)
                kernel32.GlobalUnlock(hmem)
                if not user32.SetClipboardData(CF_DIB, hmem):
                    kernel32.GlobalFree(hmem)
                    return False
                return True
            finally:
                user32.CloseClipboard()
        except Exception as e:
            logger.error("写入剪贴板失败: %s", e)
            return False
