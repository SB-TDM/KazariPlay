"""元数据源熔断状态回归。"""
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))
import utils.infra.logger as logger_module

logger_module._initialized = True
logger_module._logger = logging.getLogger("source-health")
logger_module._logger.addHandler(logging.NullHandler())

from core.metadata import multi_source  # noqa: E402


class SourceHealthTests(unittest.TestCase):
    def test_failure_cooldown_and_success_reset(self):
        sid = "health-fixture"
        multi_source.mark_source_success(sid)
        self.assertTrue(multi_source.source_available(sid))
        multi_source.mark_source_failure(sid)
        self.assertTrue(multi_source.source_available(sid))
        multi_source.mark_source_failure(sid)
        self.assertFalse(multi_source.source_available(sid))
        multi_source.mark_source_success(sid)
        self.assertTrue(multi_source.source_available(sid))


if __name__ == "__main__":
    unittest.main()
