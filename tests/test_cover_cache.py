"""封面 base64 缓存（LRU）回归测试（不动真实数据）

验证 web_bridge 的 _cover_cache_* ：
1. 命中时 move_to_end（LRU 顺序维护）
2. 条目数上限：淘汰最久未用的条目
3. 总字节上限：按字节淘汰
4. clear 后条目数与字节计数归零
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from ui import web_bridge as wb  # noqa: E402

# 测试用的小上限（不污染真实上限：恢复原值）
_SAVED_ENTRIES = wb._MAX_COVER_CACHE_ENTRIES
_SAVED_BYTES = wb._MAX_COVER_CACHE_BYTES


def reset(entries=100, bytes_limit=1024 * 1024):
    wb._cover_cache_clear()
    wb._MAX_COVER_CACHE_ENTRIES = entries
    wb._MAX_COVER_CACHE_BYTES = bytes_limit


def test_entry_limit():
    reset(entries=3)
    wb._cover_cache_put("a", "u-a")
    wb._cover_cache_put("b", "u-b")
    wb._cover_cache_put("c", "u-c")
    wb._cover_cache_get("a")           # a 变为最近使用
    wb._cover_cache_put("d", "u-d")    # 超上限 → 淘汰最久未用的 b
    assert "b" not in wb._cover_cache, "最久未用的 b 应被淘汰"
    assert list(wb._cover_cache) == ["c", "a", "d"], \
        f"LRU 顺序错误: {list(wb._cover_cache)}"
    # 命中后顺序更新
    wb._cover_cache_get("c")
    assert list(wb._cover_cache) == ["a", "d", "c"], \
        f"命中后未移到末尾: {list(wb._cover_cache)}"
    print("[entry_limit] OK")


def test_byte_limit():
    reset(entries=100, bytes_limit=20)
    wb._cover_cache_put("x", "0123456789")   # 10 字节
    wb._cover_cache_put("y", "0123456789")   # 累计 20，未超
    assert wb._cover_cache_bytes == 20
    wb._cover_cache_put("z", "0123456789")   # 累计 30 > 20 → 淘汰 x
    assert "x" not in wb._cover_cache, "超字节上限应淘汰最旧条目"
    assert wb._cover_cache_bytes == 20, f"字节计数错误: {wb._cover_cache_bytes}"
    assert wb._cover_cache_get("z") == "0123456789"
    print("[byte_limit] OK")


def test_clear():
    reset()
    wb._cover_cache_put("a", "u-a")
    wb._cover_cache_put("b", "u-b")
    wb._cover_cache_clear()
    assert len(wb._cover_cache) == 0 and wb._cover_cache_bytes == 0
    print("[clear] OK")


def main():
    try:
        test_entry_limit()
        test_byte_limit()
        test_clear()
        print("COVER CACHE TEST PASS")
        return 0
    finally:
        # 恢复真实上限
        wb._cover_cache_clear()
        wb._MAX_COVER_CACHE_ENTRIES = _SAVED_ENTRIES
        wb._MAX_COVER_CACHE_BYTES = _SAVED_BYTES


if __name__ == "__main__":
    sys.exit(main())
