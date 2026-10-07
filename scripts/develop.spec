# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import runpy
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

ROOT = Path(SPECPATH).parent
APP = ROOT / "kazari_play"
ASSETS = APP / "ui" / "web_assets"
identity = runpy.run_path(str(APP / "version.py"))
numeric_version = tuple(map(int, identity["VERSION"].split("-", 1)[0].split("."))) + (0,)
version_resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numeric_version, prodvers=numeric_version,
                      mask=0x3F, flags=0x2, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("FileDescription", identity["WINDOW_TITLE"]),
        StringStruct("FileVersion", identity["VERSION"]),
        StringStruct("ProductName", "KazariPlay"),
        StringStruct("ProductVersion", identity["VERSION"]),
        StringStruct("OriginalFilename", "KazariPlay.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)

hiddenimports = [
    "webview.platforms.edgechromium",
    "webview.platforms.win32",
    "webview.platforms.winforms",
    "frozen_smoke",
]
hiddenimports += collect_submodules("webview.dom")

a = Analysis(
    [str(APP / "main.py")],
    pathex=[str(APP), str(ROOT / "scripts")],
    binaries=[],
    datas=[
        (str(ASSETS / "index.html"), "ui/web_assets"),
        (str(ASSETS / "css"), "ui/web_assets/css"),
        (str(ASSETS / "js"), "ui/web_assets/js"),
        (str(ASSETS / "partials"), "ui/web_assets/partials"),
        (str(APP / "resources"), "resources"),
        (str(ROOT / "overlay" / "bin" / "overlay.exe"), "overlay/bin"),
        (str(ROOT / "overlay" / "bin32" / "overlay.exe"), "overlay/bin32"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "scripts" / "runtime_portable.py")],
    excludes=["PyQt5", "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets",
              "PyQt5.QtNetwork", "PyQt5.QtWebKitWidgets", "PyQt5.QtWebKit",
              "PyQt5.sip", "qtpy", "PyQt6", "PySide2", "PySide6", "matplotlib", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="KazariPlay",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon=str(APP / "resources" / "app_icon.ico"),
    version=version_resource,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="KazariPlay")
