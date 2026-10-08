"""P0 写入与取消回归，配置、数据库和网络均隔离。"""
import json
import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kazari_play"))
import utils.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("p0-data-flow")
logger_module._logger.addHandler(logging.NullHandler())

from core.game_manager import GameManager
from core.game_model import Game
from database.db_manager import DatabaseManager
from ui.web_bridge import WebBridge
from utils.config import Config


class DataFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kazari-p0-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        Config._instances.clear()
        self.addCleanup(Config._instances.clear)
        Config(str(self.root / "config.json"))
        DatabaseManager._instance = None
        self.addCleanup(setattr, DatabaseManager, "_instance", None)
        self.manager = GameManager(str(self.root / "games.db"))
        self.bridge = WebBridge(self.manager)
        self.bridge.refresh = lambda: None
        self.bridge.refresh_delta = lambda *a: None
        self.bridge.reloadCovers = lambda: None
        self.bridge._ui.invalidate = lambda *a: None
        self.messages = []
        self.bridge.notify = self.messages.append

    def fixture(self, name="Game"):
        folder = self.root / name
        folder.mkdir()
        exe = folder / "game.exe"
        exe.write_bytes(b"fixture")
        game = self.manager.scanner._check_file(str(folder), exe.name, [exe.name])
        game.vndb_id = "v123"
        game.released = "2020-01-01"
        game.length_minutes = 100
        game.launch_exe_path = str(folder / "custom.exe")
        game.logo_path = "fixture-logo"
        game.hook_code = "saved-hook"
        game.hook_code_custom = "saved-custom-hook"
        game.translate_enabled = True
        game.clean_filter_override = '[{"id":"furigana","enabled":true}]'
        game.play_time = 45
        game.play_count = 2
        game.is_favorite = True
        self.assertTrue(self.manager.add_game(game))
        return game

    def test_edit_preserves_fields_not_on_form(self):
        game = self.fixture()
        payload = {"title": "New title", "engine": game.engine, "developer": "New dev",
                   "rating": 4, "description": "New desc", "exe_path": game.exe_path}
        reply = json.loads(self.bridge.saveGame(game.id, json.dumps(payload)))
        self.assertTrue(reply["ok"])
        edited = self.manager.get_game(game.id)
        self.assertEqual(edited.title, payload["title"])
        self.assertEqual(edited.developer, payload["developer"])
        for key in ("vndb_id", "released", "length_minutes", "launch_exe_path", "logo_path",
                    "hook_code", "hook_code_custom", "translate_enabled", "clean_filter_override",
                    "play_time", "play_count", "is_favorite", "date_added"):
            self.assertEqual(getattr(edited, key), getattr(game, key), key)

    def test_partial_edit_and_failed_edit_do_not_report_success(self):
        game = self.fixture()
        with patch.object(self.manager, "update_game", return_value=False):
            reply = json.loads(self.bridge.saveGame(game.id, '{"title":"Failure"}'))
        self.assertFalse(reply["ok"])
        self.assertEqual(self.manager.get_game(game.id).title, game.title)
        self.assertTrue(json.loads(self.bridge.saveGame(game.id, '{"title":"Partial"}'))["ok"])
        self.assertEqual(self.manager.get_game(game.id).developer, game.developer)

    def test_add_empty_id_and_validate_file(self):
        folder = self.root / "New game"
        folder.mkdir()
        exe = folder / "new.exe"
        exe.write_bytes(b"fixture")
        with patch.object(self.bridge, "_run_vndb_match") as match:
            reply = json.loads(self.bridge.saveGame("", json.dumps({"exe_path": str(exe)})))
        self.assertTrue(reply["ok"])
        self.assertEqual(self.manager.get_count(), 1)
        added = self.manager.repository.get_by_path(str(exe))
        self.assertEqual(added.title, folder.name)
        bad = json.loads(self.bridge.saveGame("", json.dumps({"exe_path": str(exe) + ".missing"})))
        self.assertFalse(bad["ok"])
        self.assertEqual(self.manager.get_count(), 1)

    def test_missing_edit_id_is_not_an_add(self):
        reply = json.loads(self.bridge.saveGame("missing-game", '{"title":"Missing"}'))
        self.assertFalse(reply["ok"])
        self.assertEqual(self.manager.get_count(), 0)

    def test_add_existing_exe_does_not_replace_user_data(self):
        game = self.fixture()
        reply = json.loads(self.bridge.saveGame("", json.dumps({"exe_path": game.exe_path})))
        self.assertFalse(reply["ok"])
        self.assertEqual(self.manager.get_game(game.id).to_dict(), game.to_dict())

    def test_batch_remove_ignores_games_and_cleans_links(self):
        a, b = self.fixture("Game A"), self.fixture("Game B")
        collection = self.manager.create_collection("Group")
        self.manager.set_game_collections(a.id, [collection["id"]])
        self.assertEqual(self.manager.batch_delete([a.id, a.id, b.id]), 2)
        self.assertEqual(self.manager.get_count(), 0)
        self.assertEqual(self.manager.get_games_in_collection(collection["id"]), [])
        # 忽略清单已移除：删除后重新扫描会把游戏重新加回
        added, _, skipped = self.manager.scan_and_add(str(self.root))
        self.assertEqual((added, skipped), (2, 0))

    def test_remove_transaction_failure_rolls_back(self):
        game = self.fixture()
        self.assertTrue(self.manager.repository.db.execute(
            "CREATE TRIGGER prevent_remove BEFORE DELETE ON games "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"))
        self.assertEqual(self.manager.batch_delete([game.id]), 0)
        self.assertIsNotNone(self.manager.get_game(game.id))

    def test_single_remove_deletes_game(self):
        game = self.fixture()
        self.assertTrue(self.manager.delete_game(game.id))
        self.assertIsNone(self.manager.get_game(game.id))

    def test_manual_batch_cancel_stops_next_item_and_resets_for_retry(self):
        games = [self.fixture("Game A"), self.fixture("Game B")]
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []
        events = []
        def match(selected, **kw):
            event = kw["cancel_event"]
            events.append(event)
            for game in selected:
                if event.is_set():
                    break
                calls.append(game.id)
                started.set()
                if not release.wait(3):
                    raise AssertionError("cancel fixture timed out")
                kw["progress_cb"](game.id, game.title, "match", "done")
            finished.set()
            return len(calls), 0, 0
        self.bridge._vndb_cancel.set()
        with patch.object(self.manager, "match_vndb_for_games", side_effect=match):
            reply = json.loads(self.bridge.matchVndbBatch(json.dumps([g.id for g in games])))
            self.assertTrue(reply["ok"])
            self.assertTrue(started.wait(3))
            self.bridge.cancelMatch()
            release.set()
            self.assertTrue(finished.wait(3))
        self.assertEqual(calls, [games[0].id])
        self.assertIsNotNone(events[0])


if __name__ == "__main__":
    unittest.main()
