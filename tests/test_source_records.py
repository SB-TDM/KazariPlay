"""game_sources 表/仓库与迁移回归。"""
import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))
import utils.infra.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("source-records")
logger_module._logger.addHandler(logging.NullHandler())

from database.db_manager import DatabaseManager  # noqa: E402
from database.repositories.source_repository import GameSourceRepository  # noqa: E402


class SourceRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kazari-sources-")
        self.addCleanup(self.tmp.cleanup)
        DatabaseManager._instance = None
        self.addCleanup(setattr, DatabaseManager, "_instance", None)
        self.db = DatabaseManager(str(Path(self.tmp.name) / "games.db"))
        self.db.execute(
            "INSERT INTO games(id,title,exe_path,folder) VALUES(?,?,?,?)",
            ("g1", "Game", "C:/Game/game.exe", "C:/Game"))
        self.repo = GameSourceRepository(self.db)

    def test_upsert_and_id_map(self):
        self.assertTrue(self.repo.upsert("g1", "vndb", "v123"))
        self.assertTrue(self.repo.upsert_many("g1", [
            {"source": "hikarinagi", "external_id": "599"},
            {"source": "kungal", "external_id": "4", "data": {"title": "Game"}},
        ]))
        records = self.repo.list_for_game("g1")
        self.assertEqual({r["source"] for r in records}, {"vndb", "hikarinagi", "kungal"})
        self.assertEqual(self.repo.get_id_map("g1")["vndb"], "v123")
        self.assertEqual(self.repo.get("g1", "kungal")["data"]["title"], "Game")

    def test_legacy_ids_are_migrated(self):
        self.db.execute("UPDATE games SET vndb_id='v9', bangumi_id='42' WHERE id='g1'")
        DatabaseManager._instance = None
        db2 = DatabaseManager(str(Path(self.tmp.name) / "games.db"))
        rows = db2.query("SELECT source, external_id FROM game_sources WHERE game_id='g1' ORDER BY source")
        self.assertEqual([(r["source"], r["external_id"]) for r in rows],
                         [("bangumi", "42"), ("vndb", "v9")])

    def test_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO game_sources(game_id,source,external_id) VALUES('g1','vndb','v1')")
                raise RuntimeError("rollback")
        self.assertIsNone(self.repo.get("g1", "vndb"))


if __name__ == "__main__":
    unittest.main()
