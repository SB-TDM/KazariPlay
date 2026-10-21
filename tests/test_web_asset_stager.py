"""WinHost 页面 staging 的离线回归。"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from ui.web_asset_stager import AssetIdentity, stage_assets  # noqa: E402
from ui.web_assets_manifest import JS_MANIFEST, PARTIAL_MANIFEST  # noqa: E402

SOURCE = ROOT / "src" / "kazari_play" / "ui" / "web_assets"
IDENTITY = AssetIdentity("v1.2.0", "原版", "KazariPlay v1.2.0 (原版)")


class WebAssetStagerTests(unittest.TestCase):
    def stage(self, theme="light"):
        temp = tempfile.TemporaryDirectory(prefix="kazariplay-stage-test-")
        self.addCleanup(temp.cleanup)
        destination = Path(temp.name) / "web"
        stage_assets(SOURCE, destination, IDENTITY, theme)
        return destination

    def test_page_is_complete_and_has_no_markers(self):
        output = self.stage()
        page = (output / "index.html").read_text(encoding="utf-8")
        for marker in ("<!-- PARTIALS -->", "<!-- SCRIPTS -->", "{{"):
            self.assertNotIn(marker, page)
        for name in PARTIAL_MANIFEST:
            content = (SOURCE / "partials" / name).read_text(encoding="utf-8")
            ids = set(re.findall(r'id="([^"]+)"', content))
            self.assertTrue(ids, f"partial has no ids: {name}")
            missing = ids - set(re.findall(r'id="([^"]+)"', page))
            self.assertFalse(missing, f"partial {name} missing ids: {sorted(missing)}")
        for name in JS_MANIFEST:
            self.assertIn(f'src="js/{name}"', page)
        self.assertIn('href="css/style.css"', page)
        self.assertTrue((output / "app_icon.png").is_file())
        self.assertTrue((output / "css" / "style.css").is_file())
        self.assertTrue((output / "js" / "app.js").is_file())

    def test_scripts_keep_manifest_order(self):
        output = self.stage()
        page = (output / "index.html").read_text(encoding="utf-8")
        positions = [page.index(f'src="js/{name}"') for name in JS_MANIFEST]
        self.assertEqual(positions, sorted(positions))

    def test_dark_theme_is_first_paint(self):
        output = self.stage("dark")
        page = (output / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN" data-theme="dark">', page)
        self.assertIn("v1.2.0", page)
        self.assertIn("原版", page)

    def test_refuses_non_empty_destination(self):
        output = self.stage()
        with self.assertRaises(FileExistsError):
            stage_assets(SOURCE, output, IDENTITY)

    def test_rejects_unknown_theme(self):
        with tempfile.TemporaryDirectory(prefix="kazariplay-stage-test-") as temp:
            with self.assertRaises(ValueError):
                stage_assets(SOURCE, Path(temp) / "web", IDENTITY, "sepia")

    def test_destination_with_chinese_and_space(self):
        with tempfile.TemporaryDirectory(prefix="kazariplay-stage-test-") as temp:
            destination = Path(temp) / "运行 目录" / "web"
            stage_assets(SOURCE, destination, IDENTITY)
            self.assertTrue((destination / "index.html").is_file())

    def test_missing_source_fails(self):
        with tempfile.TemporaryDirectory(prefix="kazariplay-stage-test-") as temp:
            with self.assertRaises(FileNotFoundError):
                stage_assets(Path(temp) / "missing", Path(temp) / "web", IDENTITY)


if __name__ == "__main__":
    unittest.main()
