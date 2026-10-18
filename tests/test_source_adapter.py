"""Adapter 详情补全回归。"""
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))
import utils.infra.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("source-adapter")
logger_module._logger.addHandler(logging.NullHandler())

from core.metadata import multi_source  # noqa: E402
from core.metadata.source_adapter import enrich_candidates  # noqa: E402


class FakeClient:
    def search(self, keyword, count=5):
        return []

    def detail(self, source_id):
        return {"source": "fixture", "source_id": source_id,
                "description": "detail desc", "developer": "Dev",
                "vndb_id": "v42"}


class SourceAdapterTests(unittest.TestCase):
    def test_enrich_candidates_merges_detail(self):
        multi_source.SOURCES["fixture"] = {
            "name": "Fixture", "icon": "", "status": "experimental",
            "client": FakeClient(),
        }
        self.addCleanup(multi_source.SOURCES.pop, "fixture", None)
        group = {"fixture": {"source": "fixture", "source_id": "9", "title": "Game"}}
        enrich_candidates(group)
        self.assertEqual(group["fixture"]["description"], "detail desc")
        self.assertEqual(group["fixture"]["developer"], "Dev")
        self.assertEqual(group["fixture"]["vndb_id"], "v42")


if __name__ == "__main__":
    unittest.main()
