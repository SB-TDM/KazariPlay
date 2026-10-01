"""扫描器单测（临时目录，不动真实数据）

覆盖：中文启动器过滤 / 体积优先选主 exe / 标题清洗 / 进度回调 / 取消。
用法：python tests/test_scanner.py
"""
import os
import sys
import tempfile
import shutil
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from core.game_scanner import GameScanner


def test_chs_launcher_filter():
    """A1：中文启动器被过滤，真游戏 exe 保留"""
    s = GameScanner()
    for name in ("启动游戏.exe", "开始游戏.exe", "游戏启动.exe", "启动器.exe"):
        assert not s._is_valid_game_exe(name), f"中文启动器应被过滤: {name}"
    for name in ("nine_kokoiro.exe", "游戏.exe", "Game.exe"):
        assert s._is_valid_game_exe(name), f"真游戏 exe 应保留: {name}"
    print("[A1 中文启动器过滤] OK")


def test_clean_title():
    """A5：标题保守清洗"""
    s = GameScanner()
    assert s._clean_title("PC[ぱれっと]9nine①-九次九日九重色_官方中文") == "9nine①-九次九日九重色"
    assert s._clean_title("【PC】某游戏_汉化版") == "某游戏"
    assert s._clean_title("[汉化组]游戏名") == "游戏名"
    assert s._clean_title("纯游戏名") == "纯游戏名"
    assert s._clean_title("PC98游戏") == "PC98游戏"   # 不误伤 PC98
    print("[A5 标题清洗] OK")


def test_pick_primary_by_size():
    """A2：同目录多 exe 时体积优先（无汉化关键词）"""
    s = GameScanner()
    tmp = tempfile.mkdtemp(prefix="kp_scan_")
    try:
        folder = os.path.join(tmp, "g1")
        os.makedirs(folder)
        with open(os.path.join(folder, "aaa.exe"), "wb") as f:
            f.write(b"0" * 100)          # 小
        with open(os.path.join(folder, "zzz.exe"), "wb") as f:
            f.write(b"0" * 5000)         # 大（应被选为主）
        primary = s._pick_primary_exe(folder, ["aaa.exe", "zzz.exe"])
        assert primary == "zzz.exe", f"应选体积最大的 zzz.exe，实际 {primary}"

        # 有汉化版时汉化优先（即使体积小）
        with open(os.path.join(folder, "game_chs.exe"), "wb") as f:
            f.write(b"0" * 50)
        primary2 = s._pick_primary_exe(folder, ["aaa.exe", "zzz.exe", "game_chs.exe"])
        assert primary2 == "game_chs.exe", f"汉化版优先，实际 {primary2}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[A2 体积优先选主 exe] OK")


def test_scan_progress_and_cancel():
    """B2 进度回调 / B3 取消"""
    s = GameScanner()
    tmp = tempfile.mkdtemp(prefix="kp_scan_")
    try:
        # 造 3 个游戏文件夹
        for i in range(1, 4):
            d = os.path.join(tmp, f"游戏{i}")
            os.makedirs(d)
            with open(os.path.join(d, f"game{i}.exe"), "wb") as f:
                f.write(b"0" * 200)

        # B2：进度回调被调用，且 games 递增到 3
        calls = []
        games = s.scan(tmp, progress_cb=lambda dirs, g: calls.append((dirs, g)))
        assert len(games) == 3, f"应扫描到 3 个游戏，实际 {len(games)}"
        assert calls, "进度回调应被调用"
        assert calls[-1][1] == 3, f"最终 games 应为 3，实际 {calls[-1][1]}"
        print(f"[B2 进度回调] OK: 回调 {len(calls)} 次, 最终发现 {calls[-1][1]} 个")

        # B3：取消（预先置位）→ 提前结束，扫描不到游戏
        ev = threading.Event()
        ev.set()
        games2 = s.scan(tmp, cancel_event=ev)
        assert games2 == [], f"取消后应无结果，实际 {len(games2)}"
        print("[B3 取消扫描] OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scan_ignore_folder_and_assist():
    """A4：跳过辅助目录；且整体扫描入库路径通畅"""
    s = GameScanner()
    tmp = tempfile.mkdtemp(prefix="kp_scan_")
    try:
        # 正常游戏目录
        d1 = os.path.join(tmp, "正常游戏")
        os.makedirs(d1)
        with open(os.path.join(d1, "game.exe"), "wb") as f:
            f.write(b"0" * 200)
        # 辅助目录（应被跳过）
        d2 = os.path.join(tmp, "SmartSteamEmu")
        os.makedirs(d2)
        with open(os.path.join(d2, "helper.exe"), "wb") as f:
            f.write(b"0" * 200)
        # 补丁目录（应被跳过）
        d3 = os.path.join(tmp, "补丁")
        os.makedirs(d3)
        with open(os.path.join(d3, "patch.exe"), "wb") as f:
            f.write(b"0" * 200)

        games = s.scan(tmp)
        titles = {g.title for g in games}
        assert "正常游戏" in titles, f"应扫描到正常游戏，实际 {titles}"
        assert not any("SmartSteamEmu" in t for t in titles), "辅助目录应被跳过"
        assert "补丁" not in titles, "补丁目录应被跳过"
        print("[A4 跳过辅助目录] OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_chs_launcher_filter()
    test_clean_title()
    test_pick_primary_by_size()
    test_scan_progress_and_cancel()
    test_scan_ignore_folder_and_assist()
    print("SCANNER TEST PASS")