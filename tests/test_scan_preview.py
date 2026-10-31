"""扫描预览回归：扫描不入库、重复项标记、确认导入与过期 token。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_p0_data_flow as base
from core.games.game_model import Game


class ScanPreviewTests(base.DataFlowTests):
    def setUp(self):
        super().setUp()
        self.captured = []
        self.bridge._ui.invalidate = lambda domain, payload=None: self.captured.append((domain, payload))
        self.bridge._window = SimpleNamespace(
            create_file_dialog=lambda *a, **k: [str(self.root)])

    def _game(self, name, exe):
        return Game(id=name, title=name, exe_path=exe, folder=str(self.root),
                    engine="renpy", identity="renpy|" + name.lower())

    def _scan(self, games):
        with patch.object(self.manager.scanner, "scan", return_value=games):
            reply = json.loads(self.bridge.scanFolder())
            self.assertTrue(reply["ok"], reply)
            self.bridge._task_thread.join(5)
        previews = [payload for domain, payload in self.captured if domain == "scan_preview"]
        self.assertTrue(previews, self.captured)
        return previews[-1]

    def test_scan_preview_marks_duplicates_without_importing(self):
        existing = self.fixture("ExistingGame")
        new = self._game("NewGame", str(self.root / "NewGame" / "game.exe"))
        dup_in_scan = self._game("NewGameCopy", new.exe_path)
        payload = self._scan([existing, new, dup_in_scan])
        self.assertEqual(payload["duplicates"], 2)
        self.assertEqual([it["duplicate"] for it in payload["items"]], [True, False, True])
        self.assertIsNone(self.manager.get_game("NewGame"), "扫描阶段不应入库")

    def test_apply_imports_selected_and_starts_match(self):
        existing = self.fixture("ExistingGame")
        alpha = self._game("Alpha", str(self.root / "Alpha" / "game.exe"))
        beta = self._game("Beta", str(self.root / "Beta" / "game.exe"))
        payload = self._scan([existing, alpha, beta])
        matched = []
        with patch.object(self.bridge, "_run_vndb_match",
                          side_effect=lambda games: matched.extend(g.id for g in games)):
            reply = json.loads(self.bridge.applyScanPreview(
                payload["token"], json.dumps([0, 1])))
            self.bridge._task_thread.join(5)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["added"], 1)
        self.assertIsNotNone(self.manager.get_game("Alpha"))
        self.assertIsNone(self.manager.get_game("Beta"), "未勾选的游戏不应导入")
        self.assertEqual(matched, ["Alpha"])
        again = json.loads(self.bridge.applyScanPreview(payload["token"], json.dumps([1])))
        self.assertFalse(again["ok"], "预览被消费后 token 应失效")

    def test_apply_rejects_bad_or_stale_selection(self):
        alpha = self._game("Alpha", str(self.root / "Alpha" / "game.exe"))
        payload = self._scan([alpha])
        with patch.object(self.bridge, "_run_vndb_match", return_value=None):
            self.assertFalse(json.loads(self.bridge.applyScanPreview(
                payload["token"] + 1, json.dumps([0])))["ok"])
            self.assertFalse(json.loads(self.bridge.applyScanPreview(
                payload["token"], "not json"))["ok"])
            self.assertFalse(json.loads(self.bridge.applyScanPreview(
                payload["token"], json.dumps([99])))["ok"])
            self.assertTrue(json.loads(self.bridge.applyScanPreview(
                payload["token"], json.dumps([0])))["ok"])
            self.bridge._task_thread.join(5)


if __name__ == '__main__':
    unittest.main()
