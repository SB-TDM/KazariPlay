"""启动目标和关闭回归：模拟竞态及 Windows 真实父子进程。"""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kazari_play"))
import utils.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("process-regression")
logger_module._logger.addHandler(logging.NullHandler())
from core import game_launcher as module
from core.game_model import Game
from utils.config import Config


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.config_tmp = tempfile.TemporaryDirectory(prefix="kazari-process-config-")
        self.addCleanup(self.config_tmp.cleanup)
        Config._instances.clear()
        self.addCleanup(Config._instances.clear)
        Config(str(Path(self.config_tmp.name) / "config.json"))

    def fixture_launcher(self):
        launcher = module.GameLauncher()
        parent = Mock(pid=100)
        parent.poll.return_value = None
        launcher.current_process = parent
        launcher.current_game_id = "fixture"
        launcher.current_game_pid = 200
        launcher._game_creation_time = 123
        return launcher, parent

    def test_close_confirms_child_identity(self):
        launcher, parent = self.fixture_launcher()
        with patch.object(module, "_is_process_alive", return_value=True), \
             patch.object(module, "_process_creation_time", return_value=123), \
             patch.object(module, "_collect_descendants", return_value=[]), \
             patch.object(module, "_terminate_pid", return_value=True) as terminate:
            self.assertTrue(launcher.close())
        terminate.assert_called_once_with(200, 123)
        parent.terminate.assert_called_once()
        self.assertIsNone(launcher.current_game_pid)

    def test_close_does_not_terminate_reused_pid(self):
        launcher, parent = self.fixture_launcher()
        with patch.object(module, "_is_process_alive", return_value=True), \
             patch.object(module, "_process_creation_time", return_value=999), \
             patch.object(module, "_collect_descendants", return_value=[]), \
             patch.object(module, "_terminate_pid") as terminate:
            self.assertTrue(launcher.close())
        terminate.assert_not_called()

    def test_missing_child_identity_does_not_report_closed(self):
        launcher, parent = self.fixture_launcher()
        launcher._game_creation_time = None
        with patch.object(module, "_is_process_alive", return_value=True), \
             patch.object(module, "_process_creation_time", return_value=None), \
             patch.object(module, "_collect_descendants", return_value=[]), \
             patch.object(module, "_terminate_pid") as terminate:
            self.assertFalse(launcher.close())
        terminate.assert_not_called()
        self.assertEqual(launcher.current_game_pid, 200)
        parent.terminate.assert_not_called()

    def test_failed_trace_cannot_become_hook_target(self):
        launcher, _ = self.fixture_launcher()
        self.assertIsNone(launcher.wait_for_game_pid())

    def test_close_failure_retains_game_state(self):
        launcher, parent = self.fixture_launcher()
        with patch.object(module, "_is_process_alive", return_value=True), \
             patch.object(module, "_process_creation_time", return_value=123), \
             patch.object(module, "_collect_descendants", return_value=[]), \
             patch.object(module, "_terminate_pid", return_value=False):
            self.assertFalse(launcher.close())
        self.assertEqual(launcher.current_game_pid, 200)
        parent.terminate.assert_not_called()

    def test_wait_for_target_returns_none_when_closed(self):
        launcher, _ = self.fixture_launcher()
        launcher._trace_stop.set()
        self.assertIsNone(launcher.wait_for_game_pid())

    def test_close_before_child_window_is_ready(self):
        launcher, parent = self.fixture_launcher()
        launcher.current_game_pid = parent.pid
        launcher._tracked_processes = {200: 123}
        with patch.object(module, "_is_process_alive", return_value=True), \
             patch.object(module, "_process_creation_time", return_value=123), \
             patch.object(module, "_collect_descendants", return_value=[]), \
             patch.object(module, "_terminate_pid", return_value=True) as terminate:
            self.assertTrue(launcher.close())
        terminate.assert_called_once_with(200, 123)

    @unittest.skipUnless(os.name == "nt", "Windows process fixture")
    def test_real_launcher_exit_and_child_close(self):
        self.real_process_chain("parent")

    @unittest.skipUnless(os.name == "nt", "Windows process fixture")
    def test_visible_launcher_is_not_selected_before_delayed_child(self):
        self.real_process_chain("parent-window")

    def real_process_chain(self, mode):
        with tempfile.TemporaryDirectory(prefix="kazari-process-") as tmp:
            pidfile = Path(tmp) / "game.pid"
            launcher = module.GameLauncher()
            game = Game(id="fixture", exe_path=sys.executable, folder=tmp)
            self.assertTrue(launcher.launch(game, [str(ROOT / "tests/_process_fixture.py"),
                                                mode, str(pidfile)]))
            parent = launcher.current_process
            try:
                pid = launcher.wait_for_game_pid()
                self.assertIsNotNone(pid)
                self.assertTrue(pidfile.exists())
                self.assertEqual(pid, int(pidfile.read_text(encoding="ascii")))
                self.assertNotEqual(pid, parent.pid)
                parent.wait(timeout=4)
                self.assertTrue(launcher.is_running())
                self.assertTrue(launcher.close())
                self.assertFalse(module._is_process_alive(pid))
                self.assertFalse(launcher.is_running())
            finally:
                launcher.close()
                if pidfile.exists():
                    pid = int(pidfile.read_text(encoding="ascii"))
                    module._terminate_pid(pid, module._process_creation_time(pid))


if __name__ == "__main__":
    unittest.main()
