"""C++ overlay 命名管道客户端 - 驱动游戏内截图成功提示

overlay.exe 为独立进程，通过命名管道接收 show/hide/quit 消息。
任何失败（exe 缺失/启动失败/管道写入失败）均静默降级，不影响截图主功能。
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from utils.config import Config
from utils.logger import get_logger

logger = get_logger()

_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class OverlayClient:
    """命名管道客户端（短连接写消息，进程常驻）"""

    def __init__(self):
        self._cfg = Config()
        self._pipe_name = f"KazariPlayOverlay_{os.getpid()}"
        self._proc = None
        self._proc_lock = threading.Lock()
        self._send_lock = threading.Lock()

    @property
    def pipe_path(self) -> str:
        return rf"\\.\pipe\{self._pipe_name}"

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("overlay.enabled", True))

    def _resolve_exe(self) -> str:
        override = self._cfg.get("overlay.exe_path", "") or ""
        if override and os.path.exists(override):
            return override
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        candidates = [os.path.join(root, "overlay", "bin", "overlay.exe")]
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidates.insert(0, os.path.join(base, "overlay", "overlay.exe"))
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def _ensure_process(self) -> bool:
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                return True
            exe = self._resolve_exe()
            if not exe:
                logger.debug("overlay.exe 不存在，静默降级")
                return False
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self._proc = subprocess.Popen(
                    [exe, self._pipe_name], creationflags=flags)
                time.sleep(0.3)
                return True
            except Exception as e:
                logger.warning("overlay.exe 启动失败: %s", e)
                self._proc = None
                return False

    def _send(self, text: str) -> bool:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.CreateFileW(
            self.pipe_path, _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            return False
        try:
            data = text.encode("utf-8")
            buf = ctypes.create_string_buffer(data)
            written = wintypes.DWORD(0)
            return bool(kernel32.WriteFile(
                handle, buf, len(data), ctypes.byref(written), None))
        finally:
            kernel32.CloseHandle(handle)

    def _send_or_retry(self, payload: dict) -> bool:
        if not self.enabled:
            return False
        with self._send_lock:
            if not self._ensure_process():
                return False
            text = json.dumps(payload, ensure_ascii=False)
            if self._send(text):
                return True
            time.sleep(0.2)
            return self._send(text)

    def show(self, game_hwnd: int, png_path: str, title: str) -> bool:
        duration = self._cfg.get("overlay.toast_duration", 3.0)
        return self._send_or_retry({
            "type": "show",
            "hwnd": game_hwnd or 0,
            "path": png_path or "",
            "title": title or "",
            "duration": duration,
        })

    def hide(self) -> bool:
        return self._send_or_retry({"type": "hide"})

    def quit(self) -> bool:
        with self._proc_lock:
            if not self._proc or self._proc.poll() is not None:
                return False
        ok = self._send_or_retry({"type": "quit"})
        try:
            self._proc.wait(timeout=2)
        except Exception:
            pass
        with self._proc_lock:
            self._proc = None
        return ok
