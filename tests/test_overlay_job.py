"""Overlay 专属 Job：关闭 Job 后进程应被系统回收。"""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from core.platform.overlay_client import OverlayClient  # noqa: E402


@unittest.skipUnless(os.name == "nt", "overlay Job requires Windows")
class OverlayJobTests(unittest.TestCase):
    def test_closing_job_kills_overlay(self):
        if not (ROOT / "overlay" / "bin" / "overlay.exe").is_file():
            self.skipTest("overlay x64 is not built")
        client = OverlayClient()
        self.assertTrue(client.ensure_bidirectional(True))
        process = client._proc
        self.assertIsNotNone(process)
        self.assertIsNotNone(client._job)

        client._close_job()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.05)
        self.assertIsNotNone(process.poll(), "overlay survived Job close")
        try:
            client._quit_current()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
