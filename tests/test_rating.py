"""评分规范化单测（0-5 半星制，0.5 步进）

覆盖：用户评分规范化（合法/半星对齐/拒绝非法）与 0-100 分制来源换算。
用法：python tests/test_rating.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "kazari_play"))

from utils.domain.rating_utils import normalize_rating, rating_from_100


def test_normalize_valid():
    """合法值原样通过；0 表示未评分"""
    assert normalize_rating(4.5) == 4.5
    assert normalize_rating(3) == 3.0
    assert normalize_rating("3.5") == 3.5
    assert normalize_rating(0) == 0.0
    assert normalize_rating(5) == 5.0
    print("[评分规范化-合法值] OK")


def test_normalize_align():
    """非 0.5 步进输入对齐到最近半星"""
    assert normalize_rating(2.3) == 2.5
    assert normalize_rating(2.2) == 2.0
    assert normalize_rating("4.26") == 4.5
    print("[评分规范化-半星对齐] OK")


def test_normalize_reject():
    """非法输入（越界/NaN/非数字）返回 None"""
    for bad in (-1, 5.5, 100, float("nan"), None, "abc", ""):
        assert normalize_rating(bad) is None, f"应拒绝: {bad!r}"
    print("[评分规范化-非法输入] OK")


def test_rating_from_100():
    """0-100 分制 → 0-5 半星（半星四舍五入，低于 1 星视为未评分）"""
    assert rating_from_100(100) == 5.0
    assert rating_from_100(94) == 4.5
    assert rating_from_100(85) == 4.5
    assert rating_from_100(84) == 4.0
    assert rating_from_100(78) == 4.0
    assert rating_from_100(60) == 3.0
    assert rating_from_100(19) == 1.0
    assert rating_from_100(15) == 1.0
    assert rating_from_100(14) == 0.0
    assert rating_from_100(10) == 0.0
    assert rating_from_100(0) == 0.0
    assert rating_from_100("91") == 4.5
    assert rating_from_100(None) == 0.0
    print("[来源评分换算] OK")


if __name__ == "__main__":
    test_normalize_valid()
    test_normalize_align()
    test_normalize_reject()
    test_rating_from_100()
    print("RATING TEST PASS")
