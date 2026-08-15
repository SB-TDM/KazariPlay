"""C++ overlay 命名管道客户端 - 驱动游戏内截图 toast 与 Hook 实时翻译

统一长连接（见计划书 3.4 / 3.8）：
- 所有消息（show/hide/quit + start_hook/stop_hook/subtitle/select_hook）走同一条
  双工管道（\\.\pipe\KazariPlayOverlay_{pid}）；
- 读线程常驻：只解析 + 分发，回调必须快速返回（on_stable_text 只入队，
  翻译由 SubtitleCoordinator 的 worker 消费）；
- 任何失败均静默降级，不影响截图/主功能。
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

    单例：SubtitleCoordinator（翻译）与 WebBridge（截图 toast）必须共用
    同一实例——C++ PipeServer 是单实例管道，两个客户端各自建连会互相
    抢占（第二个连接失败，toast/命令静默丢失）。
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
        # 回调（读线程触发，必须快速返回）
        self.on_candidates = None       # (list)
        self.on_error = None            # (msg)
        self.on_test_translate_result = None   # (ok, result, error)
        self.on_filter_config = None    # (list) 过滤器配置回传

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
        """读线程：持续读 C++ 回传（只解析 + 分发，禁止耗时操作）

        重叠 ReadFile：阻塞读挂起时不会阻塞同一句柄上其他线程的 WriteFile
        （见计划书 3.8 —— 读线程只分发、翻译移出，且句柄为重叠模式）。
        """
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
            try:
                msg = json.loads(buf.raw[:read.value].decode("utf-8", errors="replace"))
            except Exception:
                continue
            self._dispatch(msg)
        # 清理句柄
        if self._pipe_handle:
            kernel32.CloseHandle(self._pipe_handle)
            self._pipe_handle = None

    def _dispatch(self, msg: dict):
        """分发 C++ 回传消息（读线程执行，回调必须快速返回）"""
        t = msg.get("type")
        if t == "hook_candidates" and self.on_candidates:
            self.on_candidates(msg.get("list", []))
        elif t == "hook_error":
            logger.error("Hook 错误: %s", msg.get("msg"))
            if self.on_error:
                self.on_error(msg.get("msg", ""))
        elif t == "test_translate_result" and self.on_test_translate_result:
            self.on_test_translate_result(bool(msg.get("ok")),
                                          msg.get("result", "") or "",
                                          msg.get("error", "") or "")
        elif t == "filter_config_response" and self.on_filter_config:
            self.on_filter_config(msg.get("filters", []) or [])

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

    # ---------- Hook 翻译命令 ----------

    def send_start_hook(self, pid: int, is_x64: bool,
                        hook_code: str = "", engine: str = "",
                        codepage: int = 0, ai_config: dict = None,
                        ai_clean_mode: int = 0) -> bool:
        """启动 Hook 会话，并传 AI 翻译配置（翻译在 C++ 内部执行）"""
        ai = ai_config or {}
        return self._send_long({
            "type": "start_hook",
            "pid": pid,
            "is_x64": is_x64,
            "hook_code": hook_code or "",
            "engine": engine or "",
            "codepage": int(codepage or 0),
            "ai_base_url": ai.get("base_url", "") or "",
            "ai_api_key": ai.get("api_key", "") or "",
            "ai_model": ai.get("model", "") or "",
            "src_lang": ai.get("source_lang", "") or "",
            "dst_lang": ai.get("target_lang", "") or "",
            "ai_clean_mode": int(ai_clean_mode or 0),
        }, is_x64=is_x64)

    def send_stop_hook(self) -> bool:
        return self._send_long({"type": "stop_hook"})

    def send_hide_subtitle(self) -> bool:
        return self._send_long({"type": "hide_subtitle"})

    def send_set_subtitle_enabled(self, enabled: bool) -> bool:
        """设置实时翻译开关（关闭时 C++ 隐藏字幕并停止显示）"""
        return self._send_long({
            "type": "set_subtitle_enabled",
            "enabled": bool(enabled),
        })

    def send_test_translate(self, text: str, ai_config: dict = None) -> bool:
        """设置页测试翻译：C++ 同步调用 AI，结果经 test_translate_result 回传"""
        ai = ai_config or {}
        return self._send_long({
            "type": "test_translate",
            "text": text or "",
            "ai_base_url": ai.get("base_url", "") or "",
            "ai_api_key": ai.get("api_key", "") or "",
            "ai_model": ai.get("model", "") or "",
            "src_lang": ai.get("source_lang", "") or "",
            "dst_lang": ai.get("target_lang", "") or "",
        })

    def send_select_hook(self, handle: int, hook_code: str = "") -> bool:
        return self._send_long({
            "type": "select_hook",
            "handle": handle,
            "hook_code": hook_code or "",
        })

    def send_update_filter_config(self, filters: list) -> bool:
        """下发清洗过滤器配置到 C++（游戏运行中实时生效）"""
        return self._send_long({
            "type": "update_filter_config",
            "filters": filters or [],
        })

    def send_query_filter_config(self) -> bool:
        """查询 C++ 当前清洗过滤器配置（结果经 on_filter_config 回传）"""
        return self._send_long({"type": "query_filter_config"})
