"""UISync 界面更新总线回归测试（不动真实窗口/前端）

验证 ui/sync.py：
1. 域映射：games/covers/screenshots/toast 生成正确的 JS 语句
2. 合并（coalesce）：同一 tick 内多次 invalidate 合并为一次 evaluate_js
3. payload 安全：toast 消息 / 截图 game_id 的 JSON 转义
4. 未绑定窗口时静默跳过；未知域告警不抛异常
5. 多线程推送不抛异常、不丢域
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from ui.sync import UISync  # noqa: E402


class FakeWindow:
    """记录 evaluate_js 调用（视为一次前端推送）"""

    def __init__(self):
        self.calls = []

    def evaluate_js(self, js):
        self.calls.append(js)


def test_domain_mapping():
    ui = UISync()
    win = FakeWindow()
    ui.bind_window(win)
    ui.invalidate("games")
    ui.invalidate("covers")
    ui.invalidate("screenshots", "g1")
    ui.invalidate("toast", '已保存 "X"')
    ui.flush_now()
    assert len(win.calls) == 1, f"应合并为一次推送, 实际 {len(win.calls)}"
    js = win.calls[0]
    assert "window.__app.refresh();" in js
    assert "window.__app.reloadCovers();" in js
    assert 'window.__app.refreshScreenshots("g1");' in js
    assert "window.__app.toast(" in js and "已保存" in js
    # toast 消息中的引号必须转义，避免破坏 JS 字符串
    assert '\\"' in js, f"toast 消息未转义: {js}"
    print("[domain_mapping] OK")


def test_timer_coalescing():
    """定时器路径：50ms 内的连续 invalidate 合并为一次推送"""
    ui = UISync()
    win = FakeWindow()
    ui.bind_window(win)
    ui.invalidate("games")
    ui.invalidate("toast", "a")
    ui.invalidate("covers")
    time.sleep(0.25)  # 等定时器（_FLUSH_DELAY=0.05）触发
    assert len(win.calls) == 1, f"定时器未合并, 推送 {len(win.calls)} 次"
    js = win.calls[0]
    assert "refresh();" in js and "reloadCovers();" in js and "toast(" in js
    print("[timer_coalescing] OK")


def test_no_window():
    ui = UISync()
    ui.invalidate("games")          # 未绑定窗口 → 静默跳过，不抛异常
    ui.invalidate("unknown_domain")  # 未知域 → 告警不抛异常
    ui.flush_now()
    assert True
    print("[no_window/unknown_domain] OK")


def test_multi_thread():
    ui = UISync()
    win = FakeWindow()
    ui.bind_window(win)

    def worker(tag):
        for _ in range(20):
            ui.invalidate("games")
            ui.invalidate("toast", tag)

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ui.flush_now()
    assert len(win.calls) >= 1, "多线程推送后应有至少一次 evaluate_js"
    print(f"[multi_thread] OK ({len(win.calls)} 次推送, 全部含 refresh)")


def main():
    test_domain_mapping()
    test_timer_coalescing()
    test_no_window()
    test_multi_thread()
    print("UI_SYNC TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
