"""Build an isolated onedir trial package for the local develop branch.

The output contains no user database/configuration. Use run_develop.cmd so all
runtime data and screenshots stay below the package's data/ directory.
"""
import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "kazari_play" / "ui" / "web_assets"
OVERLAY = ROOT / "overlay"


def run(command, cwd=None):
    print(">>>", " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def installed_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True,
                        help="new build directory; it must not already exist")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing output: " + str(output))
    if not (OVERLAY / "bin" / "overlay.exe").is_file():
        raise SystemExit("Missing develop x64 overlay/bin/overlay.exe")
    if not (OVERLAY / "bin32" / "overlay.exe").is_file():
        raise SystemExit("Missing develop x86 overlay/bin32/overlay.exe")

    if not output.parent.is_dir():
        raise SystemExit("Build parent directory must exist: " + str(output.parent))
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "develop":
        raise SystemExit("This trial build requires the develop worktree")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise SystemExit("npm is required")
    run([npm, "run", "typecheck"], cwd=ASSETS)
    run([npm, "run", "build"], cwd=ASSETS)
    run([sys.executable, "-B", "tests/verify_frontend.py"], cwd=ROOT)
    run([sys.executable, "-B", "tests/test_classic_boundary.py"], cwd=ROOT)
    output.mkdir()
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(output / "pyinstaller-cache")
    run([sys.executable, "-m", "PyInstaller",
         "--distpath", str(output / "dist"), "--workpath", str(output / "build"),
         str(ROOT / "scripts" / "develop.spec")], cwd=ROOT)

    package = output / "dist" / "KazariPlay"
    (package / "run_develop.cmd").write_text(
        "@echo off\r\n"
        "set \"KAZARIPLAY_DATA_DIR=%~dp0data\"\r\n"
        "start \"KazariPlay develop\" \"%~dp0KazariPlay.exe\"\r\n",
        encoding="ascii", newline="")
    (package / "TRIAL_README.txt").write_text(
        "KazariPlay develop 试用包\r\n\r\n"
        "请双击 KazariPlay.exe 或 run_develop.cmd 启动。数据库、配置、日志和截图\r\n"
        "隔离在本目录 data\\ 下，不会读取现有 %APPDATA%\\KazariPlay。\r\n"
        "这是本地 develop 试用构建，尚未发布；不含翻译/Hook/AI/字幕功能。\r\n"
        "需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime，无需安装 Python/Node。\r\n"
        "请将整个 KazariPlay 文件夹保留在可写位置；不要单独移动 EXE。\r\n",
        encoding="utf-8", newline="")
    for name in ("LICENSE", "THIRD_PARTY.md", "RELEASE_NOTES.md"):
        shutil.copy2(ROOT / name, package / name)
    metadata = {
        "branch": branch,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "worktree_changes": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "version": runpy.run_path(str(ROOT / "kazari_play/version.py"))["VERSION"],
        "python": sys.version,
        "dependencies": {name: installed_version(name) for name in (
            "pyinstaller", "pywebview", "pythonnet", "clr-loader", "Pillow",
            "windows-capture", "pywin32", "keyboard", "numpy", "opencv-python")},
    }
    (package / "BUILD_INFO.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE READY:", package)


if __name__ == "__main__":
    main()
