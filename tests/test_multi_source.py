"""多源元数据注册表 / 混合检索回归测试（不发起真实网络请求）

验证 core/multi_source.py：
1. 注册表完整性：6 源齐全，ready/experimental 有 client，pending 无 client
2. 默认混合源 = ['vndb','bangumi']；配置中含 pending 源会被剔除
3. _wrap 补充 source_icon / source_name
4. _dedupe：source_id 精确去重 + 标题归一化跨源去重，顺序保留
5. set_mixed_sources 写配置（fake Config，不碰真实 config.json）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from core import multi_source as ms  # noqa: E402


class FakeCfg:
    """最小 Config 替身（get/set 支持点号嵌套）"""

    def __init__(self):
        self.d = {"metadata_sources": {"mixed": ["vndb", "bangumi"]}}

    def get(self, key, default=None):
        cur = self.d
        for p in key.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur

    def set(self, key, value):
        cur = self.d
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def save(self):
        pass


def test_registry():
    assert set(ms.SOURCES) == {"vndb", "bangumi", "ymgal", "kungal",
                               "hikarinagi", "shionlib"}
    for sid, meta in ms.SOURCES.items():
        assert meta["name"] and meta["icon"].startswith("http"), sid
        assert meta["status"] in ("ready", "experimental", "pending"), sid
    assert ms.SOURCES["vndb"]["client"] is not None
    assert ms.SOURCES["ymgal"]["client"] is not None
    assert ms.SOURCES["kungal"]["client"] is None
    print("[registry] OK")


def test_mixed_default():
    ms.Config = lambda: FakeCfg()
    assert ms.get_mixed_sources() == ["vndb", "bangumi"], ms.get_mixed_sources()
    # 配置里混入 pending 源 → 读取时剔除
    fc = FakeCfg()
    fc.d["metadata_sources"]["mixed"] = ["vndb", "ymgal", "kungal", "shionlib"]
    ms.Config = lambda: fc
    assert ms.get_mixed_sources() == ["vndb", "ymgal"], ms.get_mixed_sources()
    print("[mixed default/filter] OK")


def test_wrap_and_dedupe():
    c1 = ms._wrap({"source_id": "v1234", "title": "近月少女的礼仪"}, "vndb")
    assert c1["source"] == "vndb" and c1["source_name"] == "VNDB"
    assert c1["source_icon"].startswith("http")
    c2 = ms._wrap({"source_id": "s1234", "title": "Rewrite"}, "bangumi")  # 不同标题
    c3 = ms._wrap({"source_id": "v1234", "title": "近月少女的礼仪"}, "vndb")  # 同源同 id → 精确去重
    c4 = ms._wrap({"source_id": "", "title": "某标题"}, "bangumi")             # 无 id
    out = ms._dedupe([c1, c2, c3, c4])
    assert len(out) == 3, [x["source_id"] for x in out]
    assert [x["source_id"] for x in out] == ["v1234", "s1234", ""]
    # 跨源标题模糊去重（大小写/空格归一化）
    out2 = ms._dedupe([
        ms._wrap({"source_id": "a", "title": "CLANNAD"}, "vndb"),
        ms._wrap({"source_id": "b", "title": " clannad "}, "bangumi"),
    ])
    assert len(out2) == 1, out2
    print("[wrap/dedupe] OK")


def test_set_mixed():
    fc = FakeCfg()
    ms.Config = lambda: fc
    ms.set_mixed_sources(["vndb", "ymgal", "kungal", "nosuch"])
    assert fc.d["metadata_sources"]["mixed"] == ["vndb", "ymgal", "kungal"], fc.d
    print("[set_mixed] OK")


def main():
    test_registry()
    test_mixed_default()
    test_wrap_and_dedupe()
    test_set_mixed()
    print("MULTI_SOURCE TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
