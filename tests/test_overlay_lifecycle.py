"""Windows 真实管道连接、退出、断连重连和架构切换；无 Hook/AI 请求。"""
import ctypes
import gc
import logging
import os
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kazari_play'))
import utils.logger as logger_module
logger_module._initialized = True
logger_module._logger = logging.getLogger('overlay-lifecycle')
logger_module._logger.addHandler(logging.NullHandler())
from utils.config import Config
from core.overlay_client import OverlayClient


@unittest.skipUnless(os.name == 'nt', 'Windows pipe tests')
class OverlayLifecycleTests(unittest.TestCase):
    def test_reconnect_switch_and_shutdown_release_reader(self):
        with tempfile.TemporaryDirectory(prefix='kazari-pipe-') as tmp:
            Config._instances.clear()
            cfg = Config(str(Path(tmp) / 'config.json'))
            OverlayClient._instance = None
            client = OverlayClient()
            verification = os.environ.get('KAZARI_TEST_OVERLAY_DIR')
            if verification:
                client._resolve_exe = lambda arch=True: str(Path(verification) / ('experiment_x64' if arch else 'experiment_x86') / 'overlay.exe')
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            def count():
                n = wintypes.DWORD()
                kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(n))
                return n.value
            self.assertTrue(client.ensure_bidirectional())
            client.quit()
            gc.collect()
            before = count()
            try:
                for arch in (True, False, True):
                    self.assertTrue(client.ensure_bidirectional(arch))
                    reader, process = client._read_thread, client._proc
                    self.assertTrue(client.hide())
                    self.assertTrue(client.quit())
                    self.assertFalse(reader.is_alive())
                    self.assertIsNotNone(process.poll())
                    self.assertIsNone(client._pipe_handle)
                self.assertTrue(client.ensure_bidirectional())
                process = client._proc
                process.kill()
                process.wait(5)
                client._read_thread.join(3)
                self.assertTrue(client.ensure_bidirectional())
                self.assertNotEqual(client._proc.pid, process.pid)
                client.quit()
                del process, reader
                gc.collect()
                self.assertLessEqual(count(), before + 2)
            finally:
                client.quit()
                OverlayClient._instance = None
                Config._instances.clear()


if __name__ == '__main__':
    unittest.main()
