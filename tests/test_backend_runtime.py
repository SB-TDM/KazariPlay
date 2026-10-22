"""BackendRuntime 的异步对话框和 HostPush 推送。"""
import os
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from backend_main import BackendRuntime, HostPush  # noqa: E402


class FakePort:
    def __init__(self):
        self.reads = queue.Queue()
        self.writes = []
        self.writes_lock = threading.Lock()
        self.closed = False

    def read_frame(self):
        message = self.reads.get()
        if message is None:
            return None
        return message

    def write_frame(self, message):
        with self.writes_lock:
            self.writes.append(message)

    def close(self):
        self.closed = True
        self.reads.put(None)

    def wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.writes_lock:
                for message in reversed(self.writes):
                    if predicate(message):
                        return message
            time.sleep(0.01)
        raise AssertionError(self.writes)


class BackendRuntimeTests(unittest.TestCase):
    def test_dialog_is_resolved_by_reader(self):
        port = FakePort()
        runtime = BackendRuntime(port, object(), {"type": "ready"}, lambda: None)
        runtime.reader.start()
        result = {}

        def ask():
            result["paths"] = runtime.request_dialog(
                "folder", "选择目录", [], allow_multiple=True)

        worker = threading.Thread(target=ask)
        worker.start()
        dialog = port.wait_for(lambda message: message.get("type") == "dialog")
        self.assertTrue(dialog["allow_multiple"])
        port.reads.put({"type": "dialog_result", "id": dialog["id"],
                        "ok": True, "paths": ["D:\\games", "E:\\games"]})
        worker.join(timeout=2)
        self.assertEqual(result.get("paths"), ["D:\\games", "E:\\games"])
        runtime.stop_event.set()
        port.close()
        runtime.reader.join(timeout=2)

    def test_host_push_writes_eval(self):
        port = FakePort()
        HostPush(port).evaluate_js("window.__app.refresh();")
        self.assertEqual(port.writes[-1],
                         {"type": "eval", "code": "window.__app.refresh();"})


if __name__ == "__main__":
    unittest.main()
