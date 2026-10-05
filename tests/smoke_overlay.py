"""原版截图 toast 冒烟；使用临时配置、测试窗口，不操作用户游戏。"""
import argparse
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kazari_play"))


def wait_for(check, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    return None


def run(arch):
    if os.name != "nt":
        raise RuntimeError("Windows desktop required")
    from utils.config import Config
    from core.overlay_client import OverlayClient
    from PIL import Image, ImageGrab

    exe = ROOT / "overlay" / ("bin32" if arch == "x86" else "bin") / "overlay.exe"
    if not exe.exists():
        raise RuntimeError("Build Overlay first: " + str(exe))
    user32 = ctypes.windll.user32
    user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                     wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    hwnd = user32.CreateWindowExW(0, "STATIC", "KazariPlay screenshot test", 0x10CF0000,
                                 120, 120, 640, 480, None, None, None, None)
    if not hwnd:
        raise RuntimeError("Unable to create test window")
    client = None
    try:
        with tempfile.TemporaryDirectory(prefix="kazari-toast-") as tmp:
            cfg = Config(str(Path(tmp) / "config.json"))
            cfg.set("overlay.exe_path", str(exe))
            cfg.set("overlay.toast_duration", 10)
            image_path = Path(tmp) / "fixture.png"
            Image.new("RGB", (160, 90), (255, 70, 90)).save(image_path)
            client = OverlayClient()
            assert client.show(hwnd, str(image_path), "KazariPlay test"), "show send failed"
            proc = client._proc

            def toast_window():
                found = []
                @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def callback(window, _):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    name = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(window, name, len(name))
                    if pid.value == proc.pid and name.value == "KazariPlayOverlayToast":
                        found.append(window)
                    return True
                user32.EnumWindows(callback, 0)
                return found[0] if found else None

            toast = wait_for(toast_window)
            assert toast and wait_for(lambda: user32.IsWindowVisible(toast)), "toast not visible"
            time.sleep(0.4)
            rect = wintypes.RECT()
            assert user32.GetWindowRect(toast, ctypes.byref(rect))
            pixels = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom),
                                    include_layered_windows=True)
            assert pixels.width > 0 and pixels.height > 0
            assert len(pixels.getcolors(pixels.width * pixels.height) or []) > 1, "blank toast pixels"
            assert client.hide(), "hide send failed"
            assert wait_for(lambda: not user32.IsWindowVisible(toast)), "toast did not hide"
            assert client.quit(), "quit send failed"
            proc.wait(timeout=5)
            assert proc.returncode == 0, "overlay exited abnormally"
            print("OVERLAY SMOKE PASS:", arch, "show/pixels/hide/quit")
    finally:
        if client is not None:
            client.quit()
        user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=("x64", "x86"), default="x64")
    run(parser.parse_args().arch)
