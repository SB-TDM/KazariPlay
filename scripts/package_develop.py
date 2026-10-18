"""Build an isolated onedir trial package for the local develop branch.

The output contains no user database/configuration. Use run_develop.cmd so all
runtime data and screenshots stay below the package's data/ directory.

--release additionally emits the fixed-name release asset (KazariPlay-<tag>.zip)
and SHA256SUMS.txt for GitHub Releases; it requires a clean worktree.
"""
import argparse
import hashlib
import json
import os
import platform
import runpy
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "kazari_play" / "ui" / "web_assets"
OVERLAY = ROOT / "overlay"


def run(command, cwd=None):
    print(">>>", " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def installed_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def platform_tag():
    """运行时 → 资产平台标签（与 utils/update/updater.py 的接缝一致；当前发布仅 win64）"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "win64" if machine in ("amd64", "x86_64") else "win32"
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    if system == "linux":
        return "linux-x64"
    return f"{system}-{machine}"


def make_release_assets(output, package, tag):
    """产出发布资产：干净包 zip（固定名，不带版本）+ SHA256SUMS.txt

    包内布局约定：zip 根 = 程序目录内容（KazariPlay.exe / _internal/ 直接位于根），
    更新替换器按 `<解压目录>/KazariPlay.exe` 校验，勿再套一层包目录。"""
    asset = output / f"KazariPlay-{tag}.zip"
    with zipfile.ZipFile(asset, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(package)
            if rel.parts and rel.parts[0] == "data":
                continue
            zf.write(path, rel.as_posix())
    with zipfile.ZipFile(asset) as zf:
        names = set(zf.namelist())
    if "KazariPlay.exe" not in names or not any(n.startswith("_internal/") for n in names):
        raise SystemExit("Release zip layout invalid: KazariPlay.exe / _internal must be at zip root")
    if any(n == "data" or n.startswith("data/") for n in names):
        raise SystemExit("Release zip must not contain data/")
    digest = hashlib.sha256()
    with open(asset, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    (output / "SHA256SUMS.txt").write_text(
        f"{digest.hexdigest()}  {asset.name}\n", encoding="ascii", newline="")
    print("RELEASE ASSET:", asset)
    print("RELEASE SHA256:", digest.hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True,
                        help="new build directory; it must not already exist")
    parser.add_argument("--release", action="store_true",
                        help="also emit release assets (clean zip + SHA256SUMS); requires a clean worktree")
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
    if branch not in ("develop", "main") and not branch.startswith("feature/"):
        raise SystemExit(f"Build must run from the develop/main line (got: {branch})")
    if args.release:
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        if dirty:
            raise SystemExit("Release build requires a clean worktree (git status must be empty)")
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
    app_version = runpy.run_path(str(ROOT / "src" / "kazari_play" / "version.py"))["VERSION"]
    tag = platform_tag()
    (package / "run_develop.cmd").write_text(
        "@echo off\r\n"
        "set \"KAZARIPLAY_DATA_DIR=%~dp0data\"\r\n"
        "start \"KazariPlay develop\" \"%~dp0KazariPlay.exe\"\r\n",
        encoding="ascii", newline="")
    if args.release:
        readme_text = (
            f"KazariPlay {app_version}（原版）\r\n\r\n"
            "请双击 KazariPlay.exe 启动；建议将整个文件夹解压到非系统盘的用户可写目录。\r\n"
            "数据库、配置、封面、日志与截图保存在本目录 data\\ 下，升级与更新不会改动它们。\r\n"
            "应用内更新：正式版发布后，启动时或设置-关于页可检查并更新（自动备份数据、失败自动回滚）。\r\n"
            "需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime，无需安装 Python/Node。\r\n"
            "请勿把本文件夹放在 Program Files 等需要管理员权限的位置；不要单独移动 EXE。\r\n")
    else:
        readme_text = (
            "KazariPlay develop 自测包\r\n\r\n"
            "请双击 KazariPlay.exe 或 run_develop.cmd 启动。数据库、配置、日志和截图\r\n"
            "隔离在本目录 data\\ 下，不会读取现有 %APPDATA%\\KazariPlay。\r\n"
            "这是本地 develop 自测构建，仅限本机测试、不对外发布；不含翻译/Hook/AI/字幕功能。\r\n"
            "需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime，无需安装 Python/Node。\r\n"
            "请将整个 KazariPlay 文件夹保留在可写位置；不要单独移动 EXE。\r\n")
    (package / "TRIAL_README.txt").write_text(readme_text, encoding="utf-8", newline="")
    for name in ("LICENSE", "THIRD_PARTY.md", "RELEASE_NOTES.md"):
        shutil.copy2(ROOT / name, package / name)
    metadata = {
        "branch": branch,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "worktree_changes": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
        "version": app_version,
        "platform": tag,
        "arch": platform.machine(),
        "python": sys.version,
        "dependencies": {name: installed_version(name) for name in (
            "pyinstaller", "pywebview", "pythonnet", "clr-loader", "Pillow",
            "windows-capture", "pywin32", "keyboard", "numpy", "opencv-python")},
    }
    (package / "BUILD_INFO.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE READY:", package)
    if args.release:
        make_release_assets(output, package, tag)


if __name__ == "__main__":
    main()
