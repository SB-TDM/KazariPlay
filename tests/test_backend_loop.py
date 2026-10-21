"""Backend 消息循环、异步对话框和关闭路径回归。"""
import os
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from host_transport import (  # noqa: E402
    DialogTimeout,
    HostSession,
    SessionClosed,
)


class FakePort:
    def __init__(self):
        self.read_queue = queue.Queue()
        self.writes = []
        self.write_lock = threading.Lock()
        self.closed = False

    def feed(self, message):
        self.read_queue.put(message)

    def read_frame(self):
        return self.read_queue.get()

    def write_frame(self, message):
        with self.write_lock:
            self.writes.append(message)

    def close(self):
        if not self.closed:
            self.closed = True
            self.read_queue.put(None)

    def wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.write_lock:
                for message in reversed(self.writes):
                    if predicate(message):
                        return message
            time.sleep(0.01)
        raise AssertionError(f"message not written: {self.writes!r}")


class Api:
    def __init__(self):
        self.closed = 0
        self.large_value = ""

    def getGames(self):
        return '[{"id":"1"}]'

    def searchMetadata(self, keyword, sources_json=""):
        return self.large_value

    def on_host_shutdown(self):
        self.closed += 1


def start_session(api=None, **kwargs):
    port = FakePort()
    api = api or Api()
    session = HostSession(port, api, **kwargs)
    thread = threading.Thread(target=session.run, daemon=True)
    thread.start()
    port.wait_for(lambda message: message.get("type") == "ready")
    return port, api, session, thread


def stop_session(port, thread, api):
    port.feed({"type": "shutdown"})
    thread.join(timeout=3)
    if thread.is_alive():
        raise AssertionError("session did not stop")
    if api.closed != 1:
        raise AssertionError(f"shutdown called {api.closed} times")


class BackendLoopTests(unittest.TestCase):
    def test_call_roundtrip_then_shutdown(self):
        port, api, _session, thread = start_session()
        port.feed({"type": "call", "id": 3, "method": "getGames", "args": []})
        result = port.wait_for(lambda message: message.get("type") == "result")
        self.assertEqual(result, {"type": "result", "id": 3, "ok": True,
                                  "result": '[{"id":"1"}]'})
        stop_session(port, thread, api)

    def test_unknown_method_returns_error_and_keeps_running(self):
        port, api, _session, thread = start_session()
        port.feed({"type": "call", "id": 4, "method": "missing", "args": []})
        error = port.wait_for(lambda message: message.get("type") == "result")
        self.assertFalse(error["ok"])
        self.assertEqual(error["error"]["code"], "unknown_method")
        port.feed({"type": "call", "id": 5, "method": "getGames", "args": []})
        ok = port.wait_for(
            lambda message: message.get("type") == "result" and message.get("ok"))
        self.assertEqual(ok["id"], 5)
        stop_session(port, thread, api)

    def test_dialog_wait_is_resolved_by_reader(self):
        port, api, session, thread = start_session()
        holder = {}

        def ask():
            holder["paths"] = session.request_dialog(
                "folder", "选择游戏文件夹", allow_multiple=True)

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        dialog = port.wait_for(lambda message: message.get("type") == "dialog")
        self.assertTrue(dialog["allow_multiple"])
        port.feed({"type": "dialog_result", "id": dialog["id"],
                   "ok": True, "paths": ["D:\\games", "E:\\games"]})
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(holder["paths"], ["D:\\games", "E:\\games"])
        stop_session(port, thread, api)

    def test_dialog_cancel_and_timeout(self):
        port, api, session, thread = start_session(dialog_timeout=0.01)
        holder = {}

        def ask():
            try:
                session.request_dialog("file", "选择文件")
            except DialogTimeout as exc:
                holder["error"] = exc

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        port.wait_for(lambda message: message.get("type") == "dialog")
        worker.join(timeout=2)
        self.assertIsInstance(holder.get("error"), DialogTimeout)
        self.assertTrue(port.wait_for(lambda message: message.get("type") == "dialog_cancel"))
        stop_session(port, thread, api)

    def test_eof_closes_session_and_wakes_dialog(self):
        port, api, session, thread = start_session()
        holder = {}

        def ask():
            try:
                session.request_dialog("folder", "选择文件夹")
            except SessionClosed as exc:
                holder["error"] = exc

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        port.wait_for(lambda message: message.get("type") == "dialog")
        port.feed(None)
        worker.join(timeout=2)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(holder.get("error"), SessionClosed)
        self.assertEqual(api.closed, 1)

    def test_shutdown_is_idempotent_for_dialog_waiter(self):
        port, api, session, thread = start_session()
        holder = {}

        def ask():
            try:
                session.request_dialog("folder", "选择文件夹")
            except SessionClosed as exc:
                holder["error"] = exc

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        dialog = port.wait_for(lambda message: message.get("type") == "dialog")
        port.feed({"type": "shutdown"})
        worker.join(timeout=2)
        thread.join(timeout=3)
        self.assertIsInstance(holder.get("error"), SessionClosed)
        self.assertEqual(api.closed, 1)
        self.assertEqual(port.wait_for(lambda m: m.get("type") == "shutdown_complete")["type"],
                         "shutdown_complete")
        self.assertGreater(dialog["id"], 0)

    def test_invalid_call_fields_return_error(self):
        port, api, _session, thread = start_session()
        port.feed({"type": "call", "id": True, "method": "getGames", "args": []})
        error = port.wait_for(lambda message: message.get("type") == "result")
        self.assertEqual(error["error"]["code"], "invalid_call")
        stop_session(port, thread, api)

    def test_reader_keeps_serving_calls_while_dialog_waits(self):
        port, api, session, thread = start_session()
        holder = {}

        def ask():
            holder["paths"] = session.request_dialog("folder", "选择文件夹")

        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        port.wait_for(lambda message: message.get("type") == "dialog")
        port.feed({"type": "call", "id": 8, "method": "getGames", "args": []})
        result = port.wait_for(
            lambda message: message.get("type") == "result" and message.get("id") == 8)
        self.assertTrue(result["ok"])
        port.feed({"type": "dialog_result", "id": 1, "ok": False, "paths": []})
        worker.join(timeout=2)
        self.assertEqual(holder.get("paths"), [])
        stop_session(port, thread, api)

    def test_large_result_is_split_into_chunks(self):
        port, api, _session, thread = start_session()
        api.large_value = "x" * (9 * 1024 * 1024)
        port.feed({"type": "call", "id": 9, "method": "searchMetadata",
                   "args": ["keyword"]})
        chunk = port.wait_for(lambda message: message.get("type") == "result_chunk")
        self.assertGreater(chunk["count"], 1)
        stop_session(port, thread, api)


if __name__ == "__main__":
    unittest.main()
