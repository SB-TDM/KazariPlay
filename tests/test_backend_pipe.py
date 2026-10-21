"""真实命名管道上的 Backend 握手与一次业务调用。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from host_protocol import decode_frame, encode_frame  # noqa: E402


class PipeServer:
    def __init__(self, name):
        import win32pipe
        import win32file
        self._win32file = win32file
        self.handle = win32pipe.CreateNamedPipe(
            name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
            1, 65536, 65536, 0, None,
        )
        self.buffer = bytearray()
        self.error = None
        self.thread = threading.Thread(target=self._connect, daemon=True)
        self.thread.start()

    def _connect(self):
        try:
            import win32pipe
            win32pipe.ConnectNamedPipe(self.handle, None)
        except Exception as exc:
            self.error = exc

    def read(self):
        while True:
            message = decode_frame(self.buffer)
            if message is not None:
                return message
            _, data = self._win32file.ReadFile(self.handle, 65536)
            if not data:
                return None
            self.buffer.extend(data)

    def write(self, message):
        data = encode_frame(message)
        offset = 0
        while offset < len(data):
            _, written = self._win32file.WriteFile(self.handle, data[offset:])
            if not written:
                raise RuntimeError("short pipe write")
            offset += written

    def close(self):
        try:
            self._win32file.CloseHandle(self.handle)
        except Exception:
            pass


@unittest.skipUnless(os.name == "nt", "named pipes require Windows")
class BackendPipeTests(unittest.TestCase):
    def test_ready_call_and_shutdown(self):
        try:
            import win32file  # noqa: F401
        except ImportError:
            self.skipTest("pywin32 is not installed")

        with tempfile.TemporaryDirectory(prefix="kazariplay-pipe-test-") as temp:
            pipe_name = rf"\\.\pipe\KazariPlayTest_{os.getpid()}_{int(time.time() * 1000)}"
            server = PipeServer(pipe_name)
            env = os.environ.copy()
            env["KAZARIPLAY_DATA_DIR"] = str(Path(temp) / "data")
            proc = subprocess.Popen(
                [sys.executable, "-B", str(ROOT / "src" / "kazari_play" / "backend_main.py"),
                 pipe_name, "--host-pid", str(os.getpid())],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            killer = threading.Timer(30.0, lambda: proc.kill())
            killer.daemon = True
            killer.start()
            try:
                server.thread.join(timeout=15)
                if server.error:
                    self.fail(f"pipe connection failed: {server.error}")
                ready = server.read()
                self.assertEqual(ready.get("type"), "ready")
                self.assertEqual(ready.get("version"), "1.2.0")
                self.assertTrue(Path(ready["asset_root"]).is_dir())

                server.write({"type": "call", "id": 1, "method": "getGames", "args": []})
                result = server.read()
                self.assertEqual(result["id"], 1)
                self.assertTrue(result["ok"])
                self.assertEqual(json.loads(result["result"]), [])

                server.write({"type": "shutdown"})
                self.assertEqual(server.read()["type"], "shutdown_complete")
                self.assertEqual(proc.wait(timeout=10), 0)
            finally:
                killer.cancel()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                server.close()


if __name__ == "__main__":
    unittest.main()
