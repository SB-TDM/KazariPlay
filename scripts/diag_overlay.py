"""overlay 显示自检脚本 —— 一键定位"overlay 没显示"问题（V1.1）

用法：
    python scripts/diag_overlay.py "<游戏exe路径>"

流程：启动游戏 → 检测游戏窗口模式（是否全屏）→ 启动 overlay 并发 toast+字幕 →
枚举 overlay 进程与窗口（vis/rect）→ 输出诊断结论。

常见结论：
- 游戏为全屏（尤其独占全屏）→ layered overlay 无法覆盖，请切窗口化/无边框全屏
- overlay 未启动 → 检查 overlay/bin(32)/overlay.exe 是否存在
- toast/字幕窗口 vis=False 或 rect 异常 → 反馈 debug.log 的 [sub] 行
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kazari_play"))

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _find_window_by_class(pid, class_name):
    user32 = ctypes.windll.user32
    found = []

    def cb(hwnd, lp):
        wp = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if pid and wp.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if class_name in cls.value and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False   # 只要可见的第一个
        return True

    user32.EnumWindows(_EnumWindowsProc(cb), 0)
    return found[0] if found else None


def _rect(hwnd):
    user32 = ctypes.windll.user32
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", help="游戏 exe 路径")
    ap.add_argument("--seconds", type=int, default=12, help="游戏启动等待秒数")
    args = ap.parse_args()

    game = subprocess.Popen([args.game], cwd=os.path.dirname(args.game))
    print(f"[diag] 游戏已启动 pid={game.pid}", flush=True)
    time.sleep(args.seconds)

    user32 = ctypes.windll.user32
    game_hwnd = _find_window_by_class(game.pid, "Main window") or \
        _find_window_by_class(game.pid, "Window")
    if not game_hwnd:
        print("[diag] FAIL: 未找到游戏主窗口（可能未显示或类名特殊）", flush=True)
        game.kill()
        return 1
    gr = _rect(game_hwnd)
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    gw, gh = gr[2] - gr[0], gr[3] - gr[1]
    fullscreen = gw >= sw - 2 and gh >= sh - 2
    print(f"[diag] 游戏窗口 {gw}x{gh} @ {gr} | 屏幕 {sw}x{sh} | 全屏: {fullscreen}", flush=True)
    if fullscreen:
        print("[diag] ⚠ 游戏为全屏模式：独占全屏下 overlay 无法覆盖，请切换窗口化/无边框全屏后重试", flush=True)

    from core.overlay_client import OverlayClient
    oc = OverlayClient()
    oc.on_error = lambda m: print(f"[diag] hook_error: {m}", flush=True)
    if not oc.ensure_bidirectional(False):
        print("[diag] FAIL: overlay 启动/连接失败（检查 overlay/bin32/overlay.exe）", flush=True)
        game.kill()
        return 1
    print("[diag] overlay 已启动并连接", flush=True)
    # 发 toast 与字幕
    shot_png = os.path.join(ROOT, "kazari_play", "resources", "app_icon.png")
    print("[diag] 发 toast:", oc.show(game_hwnd, shot_png, "自检 toast"), flush=True)
    print("[diag] 发字幕:", oc.send_subtitle("おはようございます、世界", "早上好，世界"), flush=True)
    time.sleep(2)

    # ---- 自动像素验证：字幕是否真的上屏（不依赖肉眼） ----
    try:
        from PIL import ImageGrab
        import statistics
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        sub_w = _find_window_by_class(None, "KazariPlaySubtitle")
        if sub_w:
            sr_ = _rect(sub_w)
            box = (sr_[0], sr_[1], sr_[2], sr_[3])
            # 隐藏字幕后再抓一次作为基准
            oc.send_hide_subtitle()
            time.sleep(0.8)
            base = statistics.mean(list(ImageGrab.grab().crop(box).convert("L").getdata()))
            # 重新发字幕
            oc.send_subtitle("おはようございます、世界", "早上好，世界")
            time.sleep(1.0)
            after = statistics.mean(list(ImageGrab.grab().crop(box).convert("L").getdata()))
            ratio = after / base if base else 1.0
            print(f"[diag] 字幕区域亮度: 隐藏={base:.1f} 显示={after:.1f} 比值={ratio:.2f}", flush=True)
            if ratio < 0.75:
                print("[diag] ✅ 字幕已上屏（半透明黑条使区域亮度显著下降）", flush=True)
            else:
                print("[diag] ❌ 字幕未上屏（亮度无明显变化；即便窗口 vis=True 也可能是合成/驱动问题）",
                      flush=True)
    except Exception as e:
        print(f"[diag] 像素验证跳过: {e}", flush=True)

    # 枚举 overlay 窗口
    out = subprocess.check_output(
        'tasklist /FI "IMAGENAME eq overlay.exe" /FO CSV', shell=True
    ).decode("utf-8", "replace")
    pids = [l.split(",")[1].strip('"') for l in out.splitlines()[1:] if "overlay" in l]
    print(f"[diag] overlay 进程: {pids}", flush=True)
    toast = _find_window_by_class(None, "KazariPlayOverlayToast")
    sub = _find_window_by_class(None, "KazariPlaySubtitle")
    for name, h in (("toast", toast), ("字幕", sub)):
        if h:
            print(f"[diag] {name} 窗口 vis={bool(user32.IsWindowVisible(h))} rect={_rect(h)}", flush=True)
        else:
            print(f"[diag] {name} 窗口未找到", flush=True)

    # debug.log 的 [sub] 渲染日志
    for sub_dir in ("bin", "bin32"):
        log = os.path.join(ROOT, "overlay", sub_dir, "debug.log")
        if os.path.exists(log):
            txt = open(log, encoding="utf-8", errors="replace").read()
            sub_logs = [l for l in txt.splitlines() if "[sub]" in l]
            if sub_logs:
                print(f"[diag] {sub_dir}/debug.log 最近渲染日志: {sub_logs[-3:]}", flush=True)

    print("[diag] quit:", oc.quit(), flush=True)
    if game.poll() is None:
        game.kill()
    print("[diag] 完成。若 toast/字幕窗口 vis=True 且 rect 在游戏窗口内，则 overlay 显示正常；"
          "问题多半是全屏模式。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
