"""WinHost 的 Backend 端消息循环与异步文件对话框等待。

本模块只依赖 port 抽象，不直接创建命名管道或窗口，便于离线测试。
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from host_protocol import ProtocolError, build_result_messages
from ui.host_dispatch import DispatchError, dispatch


PROTOCOL_VERSION = 1
MAX_PENDING_CALLS = 128
DEFAULT_DIALOG_TIMEOUT = 120.0


class TransportError(Exception):
    """传输层不可继续运行。"""


class SessionClosed(TransportError):
    """会话已经关闭，等待中的请求无法完成。"""


class DialogTimeout(TransportError):
    """文件对话框在期限内没有返回。"""


@dataclass
class _DialogWait:
    event: threading.Event = field(default_factory=threading.Event)
    paths: list[str] | None = None
    error: str | None = None


class HostSession:
    """处理 Host 帧的 Backend 会话。"""

    def __init__(
        self,
        port: Any,
        bridge: Any,
        *,
        dispatch_fn: Callable[[Any, str, list], Any] = dispatch,
        worker_count: int = 4,
        dialog_timeout: float = DEFAULT_DIALOG_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        ready_payload: dict | None = None,
    ):
        if worker_count < 1:
            raise ValueError("worker_count must be positive")
        self.port = port
        self.bridge = bridge
        self.dispatch_fn = dispatch_fn
        self.worker_count = worker_count
        self.dialog_timeout = dialog_timeout
        self.clock = clock
        self.ready_payload = dict(ready_payload or {})

        self._queue: queue.Queue[tuple[int, str, list] | None] = queue.Queue(
            maxsize=MAX_PENDING_CALLS)
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = threading.Event()
        self._stop = threading.Event()
        self._stopping = False
        self._shutdown_called = False
        self._dialog_seq = 0
        self._dialogs: dict[int, _DialogWait] = {}
        self._reader: threading.Thread | None = None
        self._workers: list[threading.Thread] = []

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    # ---------- 生命周期 ----------

    def start(self) -> None:
        with self._state_lock:
            if self._reader is not None:
                return
            self._reader = threading.Thread(
                target=self._read_loop, name="winhost-reader", daemon=True)
            self._workers = [
                threading.Thread(
                    target=self._worker_loop,
                    name=f"winhost-worker-{index}",
                    daemon=True,
                )
                for index in range(self.worker_count)
            ]
            for worker in self._workers:
                worker.start()
            self._reader.start()
        ready = {"type": "ready", "protocol": PROTOCOL_VERSION}
        ready.update(self.ready_payload)
        self._write(ready)

    def run(self) -> None:
        self.start()
        self._closed.wait()
        self._join_threads()

    def close(self) -> None:
        self._request_stop(SessionClosed("session closed"))

    def _join_threads(self) -> None:
        current = threading.current_thread()
        for worker in self._workers:
            if worker is not current:
                worker.join(timeout=2.0)
        if self._reader is not None and self._reader is not current:
            self._reader.join(timeout=2.0)

    def _request_stop(self, error: Exception) -> None:
        with self._state_lock:
            if self._closed.is_set():
                return
            self._stop.set()
            dialogs = list(self._dialogs.values())
            self._dialogs.clear()
        for wait in dialogs:
            wait.error = str(error)
            wait.event.set()
        self._call_host_shutdown()
        self._closed.set()
        try:
            self.port.close()
        except Exception:
            pass
        for _ in self._workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break

    def _call_host_shutdown(self) -> None:
        with self._state_lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
        try:
            self.bridge.on_host_shutdown()
        except AttributeError:
            pass
        except Exception:
            pass

    # ---------- 写出 ----------

    def _write(self, message: dict) -> None:
        with self._write_lock:
            self.port.write_frame(message)

    def _write_result(self, message: dict) -> None:
        try:
            messages = build_result_messages(message)
        except ProtocolError:
            messages = [{
                "type": "result",
                "id": message.get("id"),
                "ok": False,
                "error": {"code": "result_too_large", "message": "结果超过传输上限"},
            }]
        for item in messages:
            self._write(item)

    # ---------- 读取与调度 ----------

    def _read_loop(self) -> None:
        try:
            while not self._stop.is_set():
                message = self.port.read_frame()
                if message is None:
                    break
                if not isinstance(message, dict):
                    raise TransportError("frame must be an object")
                kind = message.get("type")
                if kind == "call":
                    self._accept_call(message)
                elif kind == "dialog_result":
                    self._resolve_dialog(message)
                elif kind == "shutdown":
                    self._on_shutdown()
                    return
                elif kind in ("hello", "dialog_cancel"):
                    continue
                else:
                    raise TransportError(f"unknown message type: {kind!r}")
        except Exception as exc:
            self._request_stop(TransportError(str(exc)))
        finally:
            if not self._closed.is_set():
                self._request_stop(SessionClosed("host disconnected"))

    def _accept_call(self, message: dict) -> None:
        call_id = message.get("id")
        method = message.get("method")
        args = message.get("args")
        if (not isinstance(call_id, int) or isinstance(call_id, bool)
                or not isinstance(method, str) or not isinstance(args, list)):
            self._write({
                "type": "result",
                "id": 0,
                "ok": False,
                "error": {"code": "invalid_call", "message": "调用字段无效"},
            })
            return
        try:
            self._queue.put_nowait((call_id, method, args))
        except queue.Full:
            self._write_result({
                "type": "result",
                "id": call_id,
                "ok": False,
                "error": {"code": "busy", "message": "后端请求过多"},
            })

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                call_id, method, args = item
                try:
                    result = self.dispatch_fn(self.bridge, method, args)
                    response = {
                        "type": "result",
                        "id": call_id,
                        "ok": True,
                        "result": result,
                    }
                except DispatchError as exc:
                    response = {
                        "type": "result",
                        "id": call_id,
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message},
                    }
                except Exception as exc:
                    response = {
                        "type": "result",
                        "id": call_id,
                        "ok": False,
                        "error": {
                            "code": "method_failed",
                            "message": f"{type(exc).__name__}: {exc}",
                        },
                    }
                self._write_result(response)
            finally:
                self._queue.task_done()

    def _on_shutdown(self) -> None:
        with self._state_lock:
            if self._stopping:
                return
            self._stopping = True
            self._stop.set()
            dialogs = list(self._dialogs.values())
            self._dialogs.clear()
        for wait in dialogs:
            wait.error = "host shutdown"
            wait.event.set()
        self._call_host_shutdown()
        self._queue.join()
        for _ in self._workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break
        try:
            self._write({"type": "shutdown_complete"})
        finally:
            self._closed.set()
            try:
                self.port.close()
            except Exception:
                pass

    # ---------- 文件对话框 ----------

    def request_dialog(
        self,
        kind: str,
        title: str,
        filters: list[dict] | None = None,
        allow_multiple: bool = False,
    ) -> list[str] | None:
        if kind not in ("folder", "file"):
            raise ValueError("kind must be folder or file")
        with self._state_lock:
            if self._closed.is_set():
                raise SessionClosed("session closed")
            self._dialog_seq += 1
            dialog_id = self._dialog_seq
            wait = _DialogWait()
            self._dialogs[dialog_id] = wait
        try:
            self._write({
                "type": "dialog",
                "id": dialog_id,
                "kind": kind,
                "title": title,
                "allow_multiple": bool(allow_multiple),
                "filters": filters or [],
            })
        except Exception:
            with self._state_lock:
                self._dialogs.pop(dialog_id, None)
            raise
        if not wait.event.wait(self.dialog_timeout):
            with self._state_lock:
                self._dialogs.pop(dialog_id, None)
            try:
                self._write({"type": "dialog_cancel", "id": dialog_id})
            except Exception:
                pass
            raise DialogTimeout("file dialog timed out")
        if wait.error is not None:
            raise SessionClosed(wait.error)
        return wait.paths

    def _resolve_dialog(self, message: dict) -> None:
        dialog_id = message.get("id")
        if not isinstance(dialog_id, int) or isinstance(dialog_id, bool):
            return
        with self._state_lock:
            wait = self._dialogs.pop(dialog_id, None)
        if wait is None:
            return
        if not message.get("ok"):
            wait.paths = []
        else:
            paths = message.get("paths")
            if (not isinstance(paths, list)
                    or not paths
                    or any(not isinstance(path, str) for path in paths)):
                wait.error = "invalid dialog result"
            else:
                wait.paths = paths
        wait.event.set()


def serve(port: Any, bridge: Any, **kwargs: Any) -> None:
    """运行会话，直到 shutdown、EOF 或传输错误。"""
    HostSession(port, bridge, **kwargs).run()
