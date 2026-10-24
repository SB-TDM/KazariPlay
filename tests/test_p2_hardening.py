"""P2 桥接输入校验回归：非法 JSON / 未知字段 / 数组元素类型不得抛异常或部分写入。"""
import json
import unittest

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


if __name__ == '__main__':
    unittest.main()
