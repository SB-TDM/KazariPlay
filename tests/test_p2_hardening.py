"""P2 桥接输入校验回归：非法 JSON / 未知字段 / 数组元素类型不得抛异常或部分写入。"""
import json
import unittest
from unittest.mock import patch

import test_p0_data_flow as base


class HardeningTests(base.DataFlowTests):
    def _collections(self):
        grp = json.loads(self.bridge.createCollection("分组", 0, "", ""))
        return json.loads(self.bridge.createCollection("分类", grp["id"], "", ""))

    def test_update_collection_rejects_bad_payload(self):
        cat = self._collections()
        cases = ["not json", "[]", json.dumps({"unknown": 1}),
                 json.dumps({"name": 123}), json.dumps({"sort_order": "x"})]
        for payload in cases:
            with self.subTest(payload=payload):
                result = json.loads(self.bridge.updateCollection(cat["id"], payload))
                self.assertFalse(result["ok"])
                self.assertTrue(result["msg"])

    def test_ids_must_be_arrays_of_expected_type(self):
        cat = self._collections()
        game = self.fixture("Hardening")
        for payload in ["{}", "not json", json.dumps([1]), json.dumps(["ok", 2])]:
            with self.subTest(payload=payload):
                for call in (self.bridge.addGamesToCollection,
                             self.bridge.removeGamesFromCollection,
                             self.bridge.batchMoveToCollection,
                             self.bridge.batchRemoveFromCollection):
                    self.assertFalse(json.loads(call(payload, cat["id"]))["ok"], call.__name__)
                self.assertFalse(self.bridge.setCollectionGames(cat["id"], payload))
        for payload in ["{}", "not json", json.dumps(["1"])]:
            with self.subTest(payload=payload):
                self.assertFalse(
                    json.loads(self.bridge.setGameCollections(game.id, payload))["ok"])

    def test_unknown_field_does_not_partially_write(self):
        cat = self._collections()
        result = json.loads(self.bridge.updateCollection(
            cat["id"], json.dumps({"name": "新名字", "bogus": 1})))
        self.assertFalse(result["ok"])
        tree = json.loads(self.bridge.getCollectionsTree())
        node = [c for c in tree[0]["children"] if c["id"] == cat["id"]][0]
        self.assertEqual(node["name"], "分类")

    # ---------- applyCandidate / setCover ----------

    def test_apply_candidate_rejects_bad_payload(self):
        game = self.fixture("Hardening")
        for cand in ("not json", "[]"):
            with self.subTest(cand=cand):
                self.assertFalse(json.loads(self.bridge.applyCandidate(
                    game.id, cand, json.dumps(["title"])))["ok"])
        self.assertFalse(json.loads(self.bridge.applyCandidate(
            game.id, json.dumps({"title": "x"}), "{}"))["ok"])

    def test_apply_candidate_tolerates_bad_numbers(self):
        game = self.fixture("Hardening")
        cand = {"title": "新标题", "rating": "abc", "length_minutes": "x",
                "source": "vndb", "source_id": "v999"}
        result = json.loads(self.bridge.applyCandidate(
            game.id, json.dumps(cand), json.dumps(["title", "rating", "length_minutes"])))
        self.assertTrue(result["ok"])
        fresh = self.manager.get_game(game.id)
        self.assertEqual(fresh.title, "新标题")
        self.assertEqual(fresh.rating, game.rating)
        self.assertEqual(fresh.length_minutes, game.length_minutes)

    def test_apply_candidate_persists_source_id_without_other_changes(self):
        game = self.fixture("Hardening")
        result = json.loads(self.bridge.applyCandidate(
            game.id, json.dumps({"source": "vndb", "source_id": "v999"})))
        self.assertTrue(result["ok"])
        self.assertEqual(self.manager.get_game(game.id).vndb_id, "v999")

    def test_apply_candidate_save_failure_keeps_source_unrecorded(self):
        game = self.fixture("Hardening")
        cand = {"title": "新标题", "source": "vndb", "source_id": "v999"}
        with patch.object(self.manager, "update_game", return_value=False):
            result = json.loads(self.bridge.applyCandidate(
                game.id, json.dumps(cand), json.dumps(["title"])))
        self.assertFalse(result["ok"])
        self.assertEqual(self.manager.get_game(game.id).title, game.title)
        self.assertEqual(json.loads(self.bridge.getGameSources(game.id)), [])

    def test_apply_candidate_queues_cover_without_blocking(self):
        game = self.fixture("Hardening")
        queued = []
        cand = {"cover_url": "https://example.com/a.jpg",
                "source": "vndb", "source_id": "v999"}
        with patch.object(self.bridge, "_queue_cover",
                          side_effect=lambda *a, **k: queued.append((a, k))):
            result = json.loads(self.bridge.applyCandidate(
                game.id, json.dumps(cand), json.dumps(["cover"])))
        self.assertTrue(queued, "封面应入队后台下载")
        self.assertEqual(queued[0][0][1], "https://example.com/a.jpg")
        self.assertTrue(queued[0][1].get("force"))
        self.assertIn("下载中", result["msg"])

    def test_apply_candidate_rejects_non_http_cover(self):
        game = self.fixture("Hardening")
        queued = []
        cand = {"title": "新标题", "cover_url": "file:///C:/x.jpg",
                "source": "vndb", "source_id": "v999"}
        with patch.object(self.bridge, "_queue_cover",
                          side_effect=lambda *a, **k: queued.append(a)):
            result = json.loads(self.bridge.applyCandidate(
                game.id, json.dumps(cand), json.dumps(["title", "cover"])))
        self.assertTrue(result["ok"])
        self.assertFalse(queued, "非 http(s) 封面地址不得入队")
        self.assertIn("封面", result["msg"])
        self.assertEqual(self.manager.get_game(game.id).title, "新标题")

    def test_set_cover_reports_db_write_failure(self):
        from PIL import Image
        from core.media.cover_store import CoverStore
        game = self.fixture("Hardening")
        self.bridge._cover_store = CoverStore(base_dir=str(self.root / "covers"))
        src = self.root / "cover.png"
        Image.new("RGB", (32, 32), "red").save(src)
        with patch.object(self.manager.repository, "update_cover_path", return_value=False):
            result = json.loads(self.bridge.setCover(game.id, str(src)))
        self.assertFalse(result["ok"])
        self.assertTrue(json.loads(self.bridge.setCover(game.id, str(src)))["ok"])

    def test_shutdown_cancels_cover_pool_and_unbinds_ui(self):
        import threading
        cancel = threading.Event()
        self.bridge._cover_cancel["g1"] = cancel
        calls = {}

        class Pool:
            def shutdown(self, wait=True, cancel_futures=False):
                calls["wait"] = wait
                calls["cancel_futures"] = cancel_futures

        class Window:
            def evaluate_js(self, js):
                calls["js"] = js

        self.bridge._cover_pool = Pool()
        self.bridge.bind_window(Window())
        self.bridge.shutdown()
        self.assertTrue(cancel.is_set(), "退出时应取消进行中的封面下载")
        self.assertEqual(calls.get("wait"), False)
        self.assertTrue(calls.get("cancel_futures"))
        self.assertIsNone(self.bridge._ui._window, "退出后应解绑前端推送")
        self.bridge.refresh()
        self.bridge._ui.flush_now()
        self.assertNotIn("js", calls, "解绑后不应再推送前端")


if __name__ == '__main__':
    unittest.main()
