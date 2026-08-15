"""真机 Hook 冒烟脚本 —— 注入真实游戏并观察文本采集（V1.1）

用法：
    python scripts/real_hook_smoke.py "<游戏exe路径>" [--engine krkr] [--seconds 30]

流程：启动游戏 → 启动对应位数 overlay → start_hook（候选模式）→
观察 host console（注入/引擎识别）与 STABLE 文本回传 → 结束后发送
一条测试字幕验证渲染链路 → quit。

已验证：素晴らしき日々HD版 BGI.exe（x86）→ BGI2 引擎 hook 插入成功。
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kazari_play"))


def pe_is_x64(path: str) -> bool:
    import struct
    with open(path, "rb") as f:
        head = f.read(0x40)
        if head[:2] != b"MZ":
            return True
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        f.seek(pe)
        if f.read(4) != b"PE\0\0":
            return True
        machine = struct.unpack_from("<H", f.read(2))[0]
        return machine == 0x8664


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", help="游戏 exe 路径")
    ap.add_argument("--engine", default="", help="引擎标识（驱动稳定器策略）")
    ap.add_argument("--seconds", type=int, default=30, help="观察时长（秒）")
    args = ap.parse_args()

    game = subprocess.Popen([args.game], cwd=os.path.dirname(args.game))
    print(f"[smoke] 游戏已启动 pid={game.pid} is_x64={pe_is_x64(args.game)}", flush=True)
    time.sleep(4)

    from core.overlay_client import OverlayClient
    oc = OverlayClient()
    oc.on_stable_text = lambda h, t: print(f"[smoke] STABLE handle={h} text={t[:60]!r}", flush=True)
    oc.on_candidates = lambda lst: print(f"[smoke] CANDIDATES={len(lst)}", flush=True)
    oc.on_error = lambda m: print(f"[smoke] ERROR: {m}", flush=True)

    is_x64 = pe_is_x64(args.game)
    if not oc.ensure_bidirectional(is_x64):
        print("[smoke] FAIL: overlay 启动/连接失败", flush=True)
        game.kill()
        return 1
    if not oc.send_start_hook(game.pid, is_x64, "", args.engine):
        print("[smoke] FAIL: start_hook 发送失败", flush=True)
        game.kill()
        return 1

    end = time.time() + args.seconds
    while time.time() < end:
        time.sleep(2)
        if game.poll() is not None:
            print("[smoke] 游戏已退出", flush=True)
            break

    # 验证字幕渲染链路（不依赖翻译 API）
    print("[smoke] 发送测试字幕（原文+译文）验证渲染链路...", flush=True)
    oc.send_subtitle("おはようございます、世界", "早上好，世界")
    time.sleep(1.5)
    print("[smoke] quit:", oc.quit(), flush=True)
    if game.poll() is None:
        game.kill()
    print("[smoke] 完成。检查 overlay/bin(32)/debug.log 的 host console 确认注入结果。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
