"""原版分离回归：无翻译能力，旧库与旧配置保持可读写兼容。"""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kazari_play"))

import utils.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("classic-boundary-test")
logger_module._logger.addHandler(logging.NullHandler())

from core.game_model import Game
from core.game_launcher import GameLauncher
from core.overlay_client import OverlayClient
from database.db_manager import DatabaseManager
from database.game_repository import GameRepository
from ui.web_bridge import WebBridge
from utils.config import Config, DEFAULT_CONFIG


class ClassicBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kazari-classic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        DatabaseManager._instance = None
        self.addCleanup(setattr, DatabaseManager, "_instance", None)
        Config._instances.clear()
        self.addCleanup(Config._instances.clear)

    def test_legacy_database_fields_survive_normal_writes(self):
        DatabaseManager(str(self.root / "games.db"))
        repo = GameRepository()
        game = Game(id="legacy", title="Game", exe_path="C:/fixture/game.exe", folder="C:/fixture")
        self.assertTrue(repo.add(game))
        legacy = ("saved-hook", "custom-hook", 1, '[{"id":"furigana","enabled":true}]')
        self.assertTrue(repo.db.execute(
            "UPDATE games SET hook_code=?, hook_code_custom=?, translate_enabled=?, clean_filter_override=? WHERE id=?",
            legacy + (game.id,)))
        group_id = repo.db.execute_return_id("INSERT INTO collections (name) VALUES (?)", ("Group",))
        self.assertTrue(repo.db.execute(
            "INSERT INTO game_collection_link (game_id, collection_id) VALUES (?, ?)",
            (game.id, group_id)))
        current = repo.get_by_id(game.id)
        self.assertTrue(current.translate_enabled)
        current.title = "Edited"
        current.hook_code = ""
        current.translate_enabled = False
        self.assertTrue(repo.update_game(current))
        self.assertTrue(repo.add(Game(id=game.id, title="Readded", exe_path=game.exe_path, folder=game.folder)))
        row = repo.db.query(
            "SELECT hook_code, hook_code_custom, translate_enabled, clean_filter_override FROM games WHERE id=?",
            (game.id,))[0]
        self.assertEqual(tuple(row), legacy)
        self.assertEqual(len(repo.get_by_id(game.id).collections), 1)

    def test_old_config_remains_private_and_survives_reset(self):
        config_path = self.root / "config.json"
        legacy = {
            "theme": "dark",
            "translate": {"ai": {"api_key": "test-only-not-a-secret"}},
            "textractor": {"codepage": 936},
            "clean": {"ai_assist_enabled": True},
            "subtitle": {"style": {"font_size": 24}},
            "overlay": {"enabled": True, "subtitle_enabled": False},
        }
        config_path.write_text(json.dumps(legacy), encoding="utf-8")
        cfg = Config(str(config_path))
        bridge = WebBridge.__new__(WebBridge)
        bridge._cfg = cfg
        exported = json.loads(bridge.getConfig())
        for key in ("translate", "textractor", "clean", "subtitle"):
            self.assertNotIn(key, exported)
        self.assertNotIn("subtitle_enabled", exported["overlay"])
        self.assertEqual(cfg.get("translate"), legacy["translate"])
        bridge.saveConfigs('{"theme":"light"}')
        bridge.resetConfig()
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        for key in ("translate", "textractor", "clean", "subtitle"):
            self.assertEqual(saved[key], legacy[key])
        self.assertFalse(saved["overlay"]["subtitle_enabled"])
        self.assertEqual(saved["theme"], DEFAULT_CONFIG["theme"])

    def test_no_translation_api_or_launch_dependency(self):
        for name in ("getHookCandidates", "selectHook", "testTranslation", "toggleGameTranslation",
                     "getCleanFilterConfig", "setSubtitleStyle", "previewSubtitle"):
            self.assertFalse(hasattr(WebBridge, name), name)
        for name in ("send_start_hook", "send_test_translate", "send_subtitle_style"):
            self.assertFalse(hasattr(OverlayClient, name), name)
        self.assertFalse(hasattr(GameLauncher, "_start_translation"))
        self.assertFalse(hasattr(GameLauncher, "stop_translation"))
        for key in ("translate", "textractor", "clean", "subtitle"):
            self.assertNotIn(key, DEFAULT_CONFIG)
        exe = self.root / "fixture.exe"
        exe.write_bytes(b"test")
        launcher = GameLauncher()
        game = Game(id="legacy", exe_path=str(exe), folder=str(self.root), translate_enabled=True)
        with patch("core.game_launcher.subprocess.Popen") as popen, patch.object(launcher, "_start_trace"):
            self.assertTrue(launcher.launch(game))
            popen.assert_called_once()
            launcher.close()

    def test_assembled_frontend_and_overlay_have_no_translation(self):
        import main

        html = main._load_html()
        for marker in ("set-translate", "set-subtitle", "hookSelectOverlay", "dlgTransRow",
                       "need_hook_select", "testTranslation", "renderTransRow"):
            self.assertNotIn(marker, html)
        self.assertIn('id="shotsGrid"', html)
        self.assertIn('id="relocateOverlay"', html)
        self.assertIn("getScreenshotOriginal", html)
        self.assertEqual(len(main._JS_MANIFEST), 14)
        for name in ("CMakeLists.txt", "build.bat", "build32.bat", "src/main.cpp", "src/protocol.h"):
            text = (ROOT / "overlay" / name).read_text(encoding="utf-8")
            for marker in ("hostlib", "textractor", "texthook", "ai_translator", "WinHttp", "start_hook"):
                self.assertNotIn(marker, text, name)
        self.assertFalse((ROOT / "overlay/third_party/textractor").exists())


if __name__ == "__main__":
    unittest.main()
