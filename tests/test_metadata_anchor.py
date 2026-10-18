"""Kungal anchor + VNDB ID bridge regression."""
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))
import utils.infra.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("metadata-anchor")
logger_module._logger.addHandler(logging.NullHandler())

from core.metadata import metadata_matcher as mm  # noqa: E402
from core.metadata import multi_source as ms  # noqa: E402
from core.metadata import search as metadata_search  # noqa: E402
from core.games.game_model import Game  # noqa: E402


class FakeAdapter:
    def __init__(self, detail):
        self.detail = detail


class AnchorTests(unittest.TestCase):
    def test_kungal_id_bridges_vndb_without_title_similarity(self):
        kungal = {
            "source": "kungal", "source_id": "127",
            "title": "纸上的魔法使", "alt_title": "紙の上の魔法使い",
        }
        vndb = {
            "source": "vndb", "source_id": "v15871", "vndb_id": "v15871",
            "title": "紙の上の魔法使い", "released": "2014-12-19",
        }
        with mock.patch.object(ms, "get_mixed_sources", return_value=["vndb", "kungal"]), \
                mock.patch.object(ms, "source_available", return_value=True), \
                mock.patch.object(metadata_search, "_search_source", return_value=kungal), \
                mock.patch.object(metadata_search, "get_adapter", return_value=FakeAdapter(
                    lambda _id: {"vndb_id": "v15871"})), \
                mock.patch.object(metadata_search.vndb_client, "detail", return_value=vndb):
            group = mm._resolve_anchor(["纸上的魔法使"])
        self.assertEqual(group["kungal"]["source_id"], "127")
        self.assertEqual(group["vndb"]["vndb_id"], "v15871")

    def test_anchor_rejects_weak_kungal_title(self):
        with mock.patch.object(ms, "get_mixed_sources", return_value=["kungal"]), \
                mock.patch.object(ms, "source_available", return_value=True), \
                mock.patch.object(metadata_search, "_search_source", return_value={
                    "source": "kungal", "source_id": "1",
                    "title": "完全不同的游戏",
                }):
            self.assertEqual(mm._resolve_anchor(["纸上的魔法使"]), {})

    def test_prefetch_attaches_batch_vndb_details(self):
        game = Game(id="g1", title="纸上的魔法使")
        group = {"kungal": {"source": "kungal", "source_id": "127",
                            "title": "纸上的魔法使", "vndb_id": "v15871"}}
        with mock.patch.object(ms, "get_mixed_sources", return_value=["kungal"]), \
                mock.patch.object(ms, "source_available", return_value=True), \
                mock.patch.object(metadata_search, "_resolve_kungal_anchor", return_value=group), \
                mock.patch.object(metadata_search.vndb_client, "details", return_value={
                    "v15871": {"vndb_id": "v15871", "title": "紙の上の魔法使い"}}):
            groups, enabled = mm._prefetch_anchors([game], False)
        self.assertTrue(enabled)
        self.assertEqual(groups["g1"]["vndb"]["vndb_id"], "v15871")

    def test_guard_rejects_unlinked_kungal_and_non_exact_vndb(self):
        game = Game(id="g1", title="纸上的魔法使")
        kungal = {"source": "kungal", "source_id": "127",
                  "title": "纸上的魔法使", "vndb_id": ""}
        self.assertTrue(mm._auto_match_guard(game, {"kungal": kungal}))
        vndb = {"source": "vndb", "source_id": "v1", "vndb_id": "v1",
                "title": "另一个同名小游戏"}
        self.assertTrue(mm._auto_match_guard(game, {"vndb": vndb}))
        exact = {"source": "vndb", "source_id": "v2", "vndb_id": "v2",
                 "title": "纸上的魔法使"}
        self.assertEqual(mm._auto_match_guard(game, {"vndb": exact}), "")
        game = Game(id="g2", title="近月少女的礼仪1")
        sequel = {"source": "kungal", "source_id": "40",
                  "title": "近月少女的礼仪2", "vndb_id": "v15293"}
        self.assertIn("部数编号不一致",
                      mm._auto_match_guard(game, {"kungal": sequel}))
        game = Game(id="g3", title="近月少女的礼仪")
        self.assertIn("续作编号",
                      mm._auto_match_guard(game, {"kungal": sequel}))
        game = Game(id="g4", title="CLANNAD HD")
        base = {"source": "vndb", "source_id": "v4", "vndb_id": "v4",
                "title": "CLANNAD"}
        self.assertEqual(mm._auto_match_guard(game, {"vndb": base}), "")

    def test_edition_release_preserves_local_title_and_release_date(self):
        game = Game(id="g1", title="Summer Pockets REFLECTION BLUE")
        group = {
            "kungal": {
                "source": "kungal", "source_id": "4", "vndb_id": "v20424",
                "title": "夏日口袋",
                "edition_release": {
                    "release_title": "Summer Pockets REFLECTION BLUE",
                    "vndb_id": "v20424", "released": "2020-06-26",
                },
            },
            "vndb": {
                "source": "vndb", "source_id": "v20424",
                "vndb_id": "v20424", "title": "Summer Pockets",
                "released": "2018-06-29",
            },
        }
        status, msg = mm.match_single(
            game, anchor_group=group, cover_cb=lambda *args: None)
        self.assertEqual(status, "match", msg)
        self.assertEqual(game.title, "Summer Pockets REFLECTION BLUE")
        self.assertEqual(game.released, "2020-06-26")
        self.assertEqual(game.vndb_id, "v20424")

    def test_disabled_kungal_skips_anchor(self):
        with mock.patch.object(ms, "get_mixed_sources", return_value=["vndb"]):
            self.assertEqual(mm._resolve_anchor(["纸上的魔法使"]), {})


if __name__ == "__main__":
    unittest.main()
