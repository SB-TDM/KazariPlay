"""进程回归的受控启动器/游戏窗口；由测试启动，不操作真实游戏。"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path


def run(mode, pidfile):
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                     wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    if mode in ("parent", "parent-window", "middle"):
        if mode == "parent-window":
            user32.CreateWindowExW(0, "STATIC", "KazariPlay launcher fixture", 0x10CF0000,
                                   250, 250, 300, 150, None, None, None, None)
            time.sleep(0.6)
        next_mode = "middle" if mode.startswith("parent") else "game"
        subprocess.Popen([sys.executable, __file__, next_mode, pidfile],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(0.8)
        return
    Path(pidfile).write_text(str(os.getpid()), encoding="ascii")
    time.sleep(0.5)
    hwnd = user32.CreateWindowExW(0, "STATIC", "KazariPlay process fixture", 0x10CF0000,
                                 200, 200, 320, 200, None, None, None, None)
    if not hwnd:
        raise RuntimeError("Test window creation failed")
    try:
        time.sleep(20)
    finally:
        user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("parent", "parent-window", "middle", "game"))
    parser.add_argument("pidfile")
    args = parser.parse_args()
    run(args.mode, args.pidfile)
