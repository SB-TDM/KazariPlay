"""WinHost 常驻 Backend 入口。

真实 IPC 使用命名管道；业务对象仍由现有 WebBridge 提供。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_protocol import ProtocolError, decode_frame, encode_frame
from ui.host_dispatch import DispatchError, dispatch
from ui.web_asset_stager import AssetIdentity, stage_assets
from utils.infra.config import Config
from utils.infra.logger import get_logger, set_level
from version import DISPLAY_VERSION, PRODUCT_LINE, VERSION, WINDOW_TITLE


class PipePort:
    """pywin32 命名管道字节流；Host 负责创建服务端。"""

    def __init__(self, handle):
        self.handle = int(handle)
        self._buffer = bytearray()
        self._write_lock = threading.Lock()
        self._closed = False

    @staticmethod
    def _kernel32():
        kernel32 = ctypes.windll.kernel32
        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.PeekNamedPipe.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID]
        kernel32.PeekNamedPipe.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    def read_frame(self):
        kernel32 = self._kernel32()
        while True:
            message = decode_frame(self._buffer)
            if message is not None:
                return message
            if self._closed:
                return None
            available = wintypes.DWORD()
            if not kernel32.PeekNamedPipe(
                    wintypes.HANDLE(self.handle), None, 0, None,
                    ctypes.byref(available), None):
                return None
            if available.value == 0:
                time.sleep(0.01)
                continue
            buf = ctypes.create_string_buffer(65536)
            read = wintypes.DWORD()
            ok = kernel32.ReadFile(
                wintypes.HANDLE(self.handle), buf,
                min(65536, available.value),
                ctypes.byref(read), None)
            if not ok or not read.value:
                return None
            self._buffer.extend(buf.raw[:read.value])

    def write_frame(self, message):
        data = encode_frame(message)
        kernel32 = self._kernel32()
        with self._write_lock:
            if self._closed:
                raise RuntimeError("pipe closed")
            offset = 0
            while offset < len(data):
                chunk = data[offset:]
                buf = ctypes.create_string_buffer(chunk)
                written = wintypes.DWORD()
                ok = kernel32.WriteFile(
                    wintypes.HANDLE(self.handle), buf, len(chunk),
                    ctypes.byref(written), None)
                if not ok or not written.value:
                    raise RuntimeError("short pipe write")
                offset += written.value

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._kernel32().CloseHandle(wintypes.HANDLE(self.handle))
        except Exception:
            pass


def connect_pipe(name: str, timeout: float = 15.0):
    import win32file
    import pywintypes
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            raw = int(handle)
            handle.Detach()
            return PipePort(raw)
        except (pywintypes.error, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"could not connect to WinHost pipe: {name}")


class HostPush:
    """把 UISync 的 EvaluateScript 请求写回 Host。"""

    def __init__(self, port):
        self.port = port

    def evaluate_js(self, code):
        try:
            self.port.write_frame({"type": "eval", "code": str(code)})
        except Exception:
            pass


class BackendRuntime:
    """单读者 + 顺序 dispatch；读线程负责对话框回包。"""

    def __init__(self, port, bridge, ready, on_shutdown):
        self.port = port
        self.bridge = bridge
        self.ready = ready
        self.on_shutdown = on_shutdown
        self.messages = queue.Queue()
        self.dialogs = {}
        self.dialog_seq = 0
        self.dialog_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.push = HostPush(port)

    def run(self):
        self.port.write_frame(self.ready)
        self.reader.start()
        try:
            while True:
                message = self.messages.get()
                if message is None:
                    break
                if message.get("type") != "call":
                    continue
                self._handle_call(message)
        finally:
            self.stop_event.set()
            try:
                self.on_shutdown()
            except Exception:
                pass
            try:
                self.port.write_frame({"type": "shutdown_complete"})
            except Exception:
                pass
            try:
                self.port.close()
            except Exception:
                pass
            self.reader.join(timeout=2)

    def _read_loop(self):
        try:
            while not self.stop_event.is_set():
                message = self.port.read_frame()
                if message is None:
                    break
                kind = message.get("type")
                if kind == "dialog_result":
                    self._resolve_dialog(message)
                elif kind == "shutdown":
                    self.messages.put(None)
                    return
                elif kind == "call":
                    self.messages.put(message)
        finally:
            self.messages.put(None)

    def _handle_call(self, message):
        call_id = message.get("id")
        try:
            result = dispatch(self.bridge, message.get("method"), message.get("args"))
            response = {"type": "result", "id": call_id, "ok": True, "result": result}
        except DispatchError as exc:
            response = {
                "type": "result", "id": call_id, "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
        except ProtocolError as exc:
            response = {
                "type": "result", "id": call_id, "ok": False,
                "error": {"code": "protocol", "message": str(exc)},
            }
        except Exception as exc:
            response = {
                "type": "result", "id": call_id, "ok": False,
                "error": {"code": "method_failed",
                          "message": f"{type(exc).__name__}: {exc}"},
            }
        try:
            self.port.write_frame(response)
        except Exception:
            pass

    def request_dialog(self, kind, title, filters=None, allow_multiple=False):
        if self.stop_event.is_set():
            raise RuntimeError("backend is stopping")
        with self.dialog_lock:
            self.dialog_seq += 1
            dialog_id = self.dialog_seq
            wait = {"event": threading.Event(), "paths": None, "error": None}
            self.dialogs[dialog_id] = wait
        try:
            self.port.write_frame({
                "type": "dialog",
                "id": dialog_id,
                "kind": kind,
                "title": title,
                "allow_multiple": bool(allow_multiple),
                "filters": filters or [],
            })
        except Exception:
            with self.dialog_lock:
                self.dialogs.pop(dialog_id, None)
            raise
        if not wait["event"].wait(120.0):
            with self.dialog_lock:
                self.dialogs.pop(dialog_id, None)
            try:
                self.port.write_frame({"type": "dialog_cancel", "id": dialog_id})
            except Exception:
                pass
            raise TimeoutError("file dialog timed out")
        if wait["error"] is not None:
            raise RuntimeError(wait["error"])
        return wait["paths"]

    def _resolve_dialog(self, message):
        dialog_id = message.get("id")
        with self.dialog_lock:
            wait = self.dialogs.pop(dialog_id, None)
        if wait is None:
            return
        if not message.get("ok"):
            wait["paths"] = []
        else:
            paths = message.get("paths")
            if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                wait["error"] = "invalid dialog result"
            else:
                wait["paths"] = paths
        wait["event"].set()


def build_bridge(data_dir: Path, preview: bool = False):
    from core.games.game_manager import GameManager
    from core.media.cover_store import CoverStore
    from ui.services.cover_service import CoverService
    from ui.web_bridge import WebBridge

    manager = GameManager()
    cover_store = CoverStore()
    cover_service = CoverService(cover_store)
    cover_service.start()
    bridge = WebBridge(
        manager,
        cover_store=cover_store,
        cover_service=cover_service if cover_service.started else None,
    )
    bridge._preview = preview
    return bridge, cover_service


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pipe")
    parser.add_argument("--host-pid", type=int, default=0)
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args(argv)

    cfg = Config()
    set_level(cfg.get("log_level", "INFO"))
    logger = get_logger()
    if args.host_pid:
        logger.info("WinHost Backend 连接 host pid=%s pipe=%s", args.host_pid, args.pipe)

    data_dir = Path(os.environ.get("KAZARIPLAY_DATA_DIR") or "").resolve() if os.environ.get(
        "KAZARIPLAY_DATA_DIR") else Path.home() / "AppData" / "Roaming" / "KazariPlay"
    data_dir.mkdir(parents=True, exist_ok=True)
    stage_root = args.asset_root
    if stage_root is None:
        theme = str(cfg.get("theme", "light") or "light")
        stage_root = data_dir / "cache" / "winhost" / f"run-{os.getpid()}" / "web"
        stage_assets(
            Path(__file__).resolve().parent / "ui" / "web_assets",
            stage_root,
            AssetIdentity(DISPLAY_VERSION, PRODUCT_LINE, WINDOW_TITLE),
            theme,
        )

    port = connect_pipe(args.pipe)
    bridge, cover_service = build_bridge(data_dir)
    bridge._start_ts = time.monotonic()

    def shutdown():
        try:
            cover_service.stop()
        except Exception:
            pass
        overlay = getattr(bridge, "_overlay_client", None)
        if overlay is not None:
            try:
                overlay.quit()
            except Exception:
                pass

    bridge.on_host_shutdown = shutdown
    ready = {
        "type": "ready",
        "protocol": 1,
        "version": VERSION,
        "display_version": DISPLAY_VERSION,
        "theme": str(cfg.get("theme", "light") or "light"),
        "asset_root": str(stage_root),
    }
    runtime = BackendRuntime(port, bridge, ready, shutdown)
    bridge._ui.bind_window(runtime.push)
    bridge._dialog_provider = runtime.request_dialog

    try:
        runtime.run()
    except Exception as exc:
        logger.error("WinHost Backend 失败: %s", exc)
        try:
            port.write_frame({
                "type": "startup_error",
                "code": "backend_init",
                "message": str(exc),
            })
        except Exception:
            pass
        return 1
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
