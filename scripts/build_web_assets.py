"""生成并校验 WinHost 运行期页面资源，不启动窗口或 WebView。"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from ui.web_asset_stager import AssetIdentity, stage_assets  # noqa: E402
from version import DISPLAY_VERSION, PRODUCT_LINE, WINDOW_TITLE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args()

    identity = AssetIdentity(DISPLAY_VERSION, PRODUCT_LINE, WINDOW_TITLE)
    source = ROOT / "src" / "kazari_play" / "ui" / "web_assets"
    if args.output:
        output = args.output.resolve()
        if output.exists() and any(output.iterdir()):
            raise SystemExit(f"refusing to overwrite non-empty output: {output}")
        stage_assets(source, output, identity, args.theme)
        print(output)
        return 0

    with tempfile.TemporaryDirectory(prefix="kazariplay-web-stage-") as temp:
        output = Path(temp) / "web"
        stage_assets(source, output, identity, args.theme)
        text = (output / "index.html").read_text(encoding="utf-8")
        if any(marker in text for marker in ("<!-- PARTIALS -->", "<!-- SCRIPTS -->", "{{")):
            raise SystemExit("staged page still contains markers")
        if not all(marker in text for marker in (
                "js/state.js", "js/app.js", "css/style.css")):
            raise SystemExit("staged page is missing required assets")
        print(f"WEB_STAGE_OK: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
