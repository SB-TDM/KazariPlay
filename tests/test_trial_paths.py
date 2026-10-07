"""Trial data override does not fall through to the installed user library."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kazari_play"))
from utils import path_utils


class TrialPathTests(unittest.TestCase):
    def test_override_controls_database_config_screenshots_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"KAZARIPLAY_DATA_DIR": tmp}), \
                patch.object(path_utils, "_writable_cache", None):
            self.assertEqual(path_utils.get_default_db_path(), str(Path(tmp) / "games.db"))
            self.assertEqual(path_utils.get_default_config_path(), str(Path(tmp) / "config.json"))
            self.assertEqual(path_utils.get_default_log_dir(), str(Path(tmp) / "logs"))
            self.assertEqual(path_utils.get_game_screenshots_dir("fixture"), str(Path(tmp) / "screenshots/fixture"))
            with patch.object(path_utils, "_get_project_data_dir") as fallback:
                self.assertTrue(path_utils.migrate_data_if_needed())
                fallback.assert_not_called()

    def test_unwritable_override_never_uses_appdata(self):
        with patch.dict(os.environ, {"KAZARIPLAY_DATA_DIR": "C:/fixture/unwritable"}), \
                patch.object(path_utils, "_writable_cache", None), \
                patch.object(path_utils, "_is_writable", return_value=False), \
                patch.object(path_utils, "_get_project_data_dir") as fallback:
            with self.assertRaises(OSError):
                path_utils.get_app_data_dir()
            fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
