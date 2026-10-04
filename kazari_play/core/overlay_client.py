"""截图 toast 的 C++ Overlay 客户端，命名管道失败时不影响截图保存。"""
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

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_FLAG_OVERLAPPED = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

_READ_BUF = 131072          # 单条消息读取上限（C++ 侧缓冲 64KB）
_CONNECT_RETRY = 10         # 连接重试次数
_CONNECT_RETRY_DELAY = 0.1  # 秒


class _OVERLAPPED(ctypes.Structure):
    """ctypes OVERLAPPED（用于重叠 ReadFile，避免阻塞读卡住同句柄的写）"""
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class OverlayClient:
    """命名管道客户端（统一长连接，overlay.exe 进程常驻）

    单实例管道由一个客户端持有，截图提示复用同一进程与连接。
    """
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._cfg = Config()
        self._pipe_name = f"KazariPlayOverlay_{os.getpid()}"
        self._proc = None
        self._proc_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pipe_handle = None
        self._read_thread = None
        self._stop_read = threading.Event()
        self._exe_is_x64 = True   # 当前 overlay 进程位数（x64=bin/，x86=bin32/）

    @property
    def pipe_path(self) -> str:
        return rf"\\.\pipe\{self._pipe_name}"

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("overlay.enabled", True))

    # ---------- 进程 ----------

    def _resolve_exe(self, is_x64: bool = True) -> str:
        """按位数解析 overlay.exe：x64 → overlay/bin/，x86 → overlay/bin32/"""
        override = self._cfg.get("overlay.exe_path", "") or ""
        if override and os.path.exists(override):
            return override
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        sub = "bin" if is_x64 else "bin32"
        candidates = [os.path.join(root, "overlay", sub, "overlay.exe")]
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidates.insert(0, os.path.join(base, "overlay", sub, "overlay.exe"))
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def _quit_current(self):
        """停止当前 overlay 进程（位数切换/退出时；调用方须已持有 _proc_lock）"""
        self._stop_read.set()
        if self._pipe_handle:
            try:
                self._raw_write(json.dumps({"type": "quit"}).encode("utf-8"))
            except Exception:
                pass
        if self._proc:
            try:
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._pipe_handle = None

    def _ensure_process(self, is_x64: bool = True) -> bool:
        with self._proc_lock:
            if self._proc and self._proc.poll() is None and self._exe_is_x64 == is_x64:
                return True
            # 位数不符或未启动：先停旧进程（已持锁，_quit_current 内部不再加锁）
            if self._proc and self._proc.poll() is None:
                self._quit_current()
            exe = self._resolve_exe(is_x64)
            if not exe:
                logger.debug("overlay.exe(%s) 不存在，静默降级", "x64" if is_x64 else "x86")
                return False
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self._proc = subprocess.Popen(
                    [exe, self._pipe_name], creationflags=flags)
                self._exe_is_x64 = is_x64
                time.sleep(0.3)
                return True
            except Exception as e:
                logger.warning("overlay.exe 启动失败: %s", e)
                self._proc = None
                return False

    # ---------- 统一长连接 ----------

    def ensure_bidirectional(self, is_x64=None) -> bool:
        """启动 overlay.exe 并建立唯一长连接（含读线程）

        is_x64=None 时保持当前进程位数；否则按位数选择 overlay 版本。
        """
        if is_x64 is None:
            is_x64 = self._exe_is_x64
        if not self._ensure_process(is_x64):
            logger.warning("ensure_bidirectional: _ensure_process(%s) 失败", is_x64)
            return False
        if self._pipe_handle:
            return True
        handle = self._open_pipe_long()
        if not handle:
            logger.warning("ensure_bidirectional: 管道连接失败 pipe=%s", self.pipe_path)
            return False
        logger.info("ensure_bidirectional: 已连接 pipe=%s", self.pipe_path)
        self._pipe_handle = handle
        self._stop_read.clear()
        self._read_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="overlay-reader")
        self._read_thread.start()
        return True

    def _open_pipe_long(self):
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        # 重试：等待 overlay.exe 的 ConnectNamedPipe 就绪
        # ⚠️ FILE_FLAG_OVERLAPPED(0x40000000) 与 GENERIC_WRITE 同值，必须放在
        # dwFlagsAndAttributes（第 6 参），放 dwDesiredAccess 会被吸收掉。
        for _ in range(_CONNECT_RETRY):
            handle = kernel32.CreateFileW(
                self.pipe_path,
                _GENERIC_READ | _GENERIC_WRITE,   # dwDesiredAccess
                0, None, _OPEN_EXISTING,
                _FILE_FLAG_OVERLAPPED,            # dwFlagsAndAttributes
                None)
            if handle and handle != _INVALID_HANDLE_VALUE:
                return handle
            time.sleep(_CONNECT_RETRY_DELAY)
        return None

    def _read_loop(self):
        """保持双工连接并检测服务端断开；原版没有字幕回传命令。"""
        kernel32 = ctypes.windll.kernel32
        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED)]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
        kernel32.ResetEvent.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED),
            ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        kernel32.GetOverlappedResult.restype = wintypes.BOOL

        ov = _OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        while not self._stop_read.is_set() and self._pipe_handle:
            kernel32.ResetEvent(ov.hEvent)
            buf = ctypes.create_string_buffer(_READ_BUF)
            read = wintypes.DWORD(0)
            ok = kernel32.ReadFile(self._pipe_handle, buf, _READ_BUF - 1,
                                   ctypes.byref(read), ctypes.byref(ov))
            if not ok:
                err = kernel32.GetLastError()
                if err == _ERROR_IO_PENDING:
                    wr = kernel32.WaitForSingleObject(ov.hEvent, _INFINITE)
                    if wr != _WAIT_OBJECT_0:
                        break
                    if not kernel32.GetOverlappedResult(
                            self._pipe_handle, ctypes.byref(ov),
                            ctypes.byref(read), False) or read.value == 0:
                        break   # 管道断开（overlay 退出/崩溃）
                else:
                    break
            elif read.value == 0:
                break
        # 清理句柄
        if self._pipe_handle:
            kernel32.CloseHandle(self._pipe_handle)
            self._pipe_handle = None

    def _raw_write(self, data: bytes) -> bool:
        """重叠写（不自启动进程、不加锁；供 _send_long 与 _quit_current 复用）"""
        if not self._pipe_handle:
            return False
        kernel32 = ctypes.windll.kernel32
        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED)]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
        kernel32.ResetEvent.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED),
            ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        kernel32.GetOverlappedResult.restype = wintypes.BOOL
        buf = ctypes.create_string_buffer(data)
        written = wintypes.DWORD(0)
        ov = _OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        ok = kernel32.WriteFile(self._pipe_handle, buf, len(data),
                                ctypes.byref(written), ctypes.byref(ov))
        if not ok:
            err = kernel32.GetLastError()
            if err == _ERROR_IO_PENDING:
                wr = kernel32.WaitForSingleObject(ov.hEvent, 10000)
                if wr == _WAIT_OBJECT_0:
                    ok = kernel32.GetOverlappedResult(
                        self._pipe_handle, ctypes.byref(ov),
                        ctypes.byref(written), False)
                else:
                    ok = False
            else:
                ok = False
        kernel32.CloseHandle(ov.hEvent)
        return bool(ok)

    def _send_long(self, payload: dict, is_x64=None) -> bool:
        """经长连接发送命令（线程安全；is_x64 指定 overlay 位数，None=保持当前）"""
        if not self.enabled:
            return False
        with self._send_lock:
            if is_x64 is None:
                is_x64 = self._exe_is_x64
            if not self.ensure_bidirectional(is_x64):
                return False
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            ok = self._raw_write(data)
            if not ok:
                logger.warning("_send_long: 写入失败 type=%s", payload.get("type"))
            return ok

    # ---------- 命令（统一走长连接） ----------

    def show(self, game_hwnd: int, png_path: str, title: str) -> bool:
        duration = self._cfg.get("overlay.toast_duration", 3.0)
        return self._send_long({
            "type": "show",
            "hwnd": game_hwnd or 0,
            "path": png_path or "",
            "title": title or "",
            "duration": duration,
        })

    def hide(self) -> bool:
        return self._send_long({"type": "hide"})

    def quit(self) -> bool:
        with self._proc_lock:
            if not self._proc or self._proc.poll() is not None:
                return False
            self._quit_current()
            return True
