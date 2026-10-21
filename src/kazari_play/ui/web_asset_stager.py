"""把 web_assets 装配成可交给 WebView2 虚拟主机加载的完整页面。"""
from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ui.web_assets_manifest import JS_MANIFEST, PARTIAL_MANIFEST


@dataclass(frozen=True)
class AssetIdentity:
    display_version: str
    product_line: str
    window_title: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _script_tags() -> str:
    return "\n".join(f'<script src="js/{name}"></script>' for name in JS_MANIFEST)


def stage_assets(
    source_root: Path,
    destination: Path,
    identity: AssetIdentity,
    theme: str = "light",
) -> Path:
    """生成一份运行期页面资源目录。

    目的目录必须是空的；调用方负责使用唯一目录并在退出后清理。
    """
    source_root = Path(source_root)
    destination = Path(destination)
    if theme not in ("light", "dark"):
        raise ValueError("theme must be light or dark")
    if not (source_root / "index.html").is_file():
        raise FileNotFoundError(f"missing index.html under {source_root}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    for dirname in ("css", "js", "partials"):
        source = source_root / dirname
        if not source.is_dir():
            raise FileNotFoundError(f"missing asset directory: {source}")
        shutil.copytree(source, destination / dirname)
    extra = source_root / "images"
    if extra.is_dir():
        shutil.copytree(extra, destination / "images")

    icon = source_root.parents[1] / "resources" / "app_icon.png"
    if icon.is_file():
        shutil.copy2(icon, destination / "app_icon.png")

    page = _read(source_root / "index.html")
    page = page.replace("{{THEME}}", theme)
    page = page.replace("{{APP_VERSION}}", html.escape(identity.display_version))
    page = page.replace("{{PRODUCT_LINE}}", html.escape(identity.product_line))
    page = page.replace("{{APP_TITLE}}", html.escape(identity.window_title))

    partials = "\n".join(
        _read(source_root / "partials" / name) for name in PARTIAL_MANIFEST)
    if "<!-- PARTIALS -->" not in page or "<!-- SCRIPTS -->" not in page:
        raise ValueError("index.html is missing partial/script markers")
    page = page.replace("<!-- PARTIALS -->", partials)
    page = page.replace("<!-- SCRIPTS -->", _script_tags())
    page = page.replace("{{APP_VERSION}}", html.escape(identity.display_version))
    page = page.replace("{{PRODUCT_LINE}}", html.escape(identity.product_line))
    page = page.replace("{{APP_TITLE}}", html.escape(identity.window_title))

    if icon.is_file():
        page = re.sub(
            r'<div class="(logo|a-logo)">.*?</div>',
            lambda match: (
                f'<div class="{match.group(1)}">'
                '<img class="logo-img" src="app_icon.png" alt=""></div>'
            ),
            page,
            flags=re.S,
        )

    if "{{" in page or "<!-- PARTIALS -->" in page or "<!-- SCRIPTS -->" in page:
        raise ValueError("staged page still contains unresolved markers")
    (destination / "index.html").write_text(page, encoding="utf-8", newline="")
    return destination
