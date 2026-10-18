"""元数据源配置迁移回归。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from utils.infra.config import Config  # noqa: E402


class MetadataConfigMigrationTests(unittest.TestCase):
    def setUp(self):
        Config._instances.clear()

    def tearDown(self):
        Config._instances.clear()

    def test_legacy_mixed_sources_gain_kungal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "metadata_sources": {"mixed": ["vndb", "bangumi"]},
            }), encoding="utf-8")
            cfg = Config(str(path))
            self.assertEqual(cfg.get("metadata_sources.mixed"),
                             ["vndb", "bangumi", "kungal"])
            self.assertEqual(cfg.get("metadata_sources.defaults_version"), 2)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("kungal", saved["metadata_sources"]["mixed"])

    def test_explicit_post_migration_choice_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "metadata_sources": {
                    "mixed": ["vndb", "bangumi"],
                    "defaults_version": 2,
                },
            }), encoding="utf-8")
            cfg = Config(str(path))
            self.assertEqual(cfg.get("metadata_sources.mixed"),
                             ["vndb", "bangumi"])


if __name__ == "__main__":
    unittest.main()
