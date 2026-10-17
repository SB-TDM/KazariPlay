"""多源元数据自动匹配的离线回归（不访问真实网络）

覆盖 core/metadata_matcher.py：
1. VNDB + Bangumi 标题一致 → 合并，标题优先中文，字段按优先级取
2. Bangumi 单源命中（中文文件夹名）→ 采用并记录 bangumi_id
3. 单源候选与标题差异过大 → 拒绝（避免误匹配）
4. 多源结果不一致 → 拒绝并提示手动确认
5. 已有 bangumi_id → 跳过；相似度函数边界
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

import utils.logger as logger_module  # noqa: E402

logger_module._initialized = True

from core.game_model import Game  # noqa: E402
from core import multi_source as ms  # noqa: E402
from core import metadata_matcher as mm  # noqa: E402


class FakeClient:
    """固定返回结果的元数据客户端"""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search(self, keyword, count=5):
        self.calls.append(keyword)
        return list(self.results)


def _install(vndb_results, bangumi_results):
    """安装假客户端并固定混合源为 vndb+bangumi"""
    ms.get_mixed_sources = lambda: ["vndb", "bangumi"]
    ms.SOURCES["vndb"]["client"] = FakeClient(vndb_results)
    ms.SOURCES["bangumi"]["client"] = FakeClient(bangumi_results)


def _game(title, **kw):
    g = Game(id="g1", title=title, exe_path="E:/games/g1/game.exe",
             folder="E:/games/g1")
    for k, v in kw.items():
        setattr(g, k, v)
    return g


VNDB_SUMMER = {
    "vndb_id": "v123",
    "title": "サマーポケッツ",
    "alt_title": "Summer Pockets",
    "cover_url": "",
    "rating": 4.2,
    "description": "English description",
    "developer": "Key",
    "released": "2018-06-29",
    "length_minutes": 1800,
}

BGM_SUMMER = {
    "source": "Bangumi",
    "source_id": "12345",
    "title": "夏日口袋",
    "alt_title": "サマーポケッツ",
    "cover_url": "",
    "description": "中文简介",
    "developer": "",
    "released": "",
    "rating": 4.5,
    "length_minutes": 0,
    "tags": [],
}


def test_consensus_merge():
    _install([VNDB_SUMMER], [BGM_SUMMER])
    g = _game("Summer Pockets")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.vndb_id == "v123", g.vndb_id
    assert g.bangumi_id == "12345", g.bangumi_id
    assert g.title == "夏日口袋", g.title
    assert g.description == "中文简介", g.description
    assert g.developer == "Key", g.developer
    assert g.released == "2018-06-29", g.released
    assert g.length_minutes == 1800, g.length_minutes
    assert abs(g.rating - 4.2) < 1e-6, g.rating
    print("[consensus merge] OK")


def test_bangumi_only_chinese_folder():
    _install([], [{
        "source": "Bangumi", "source_id": "99", "title": "千恋万花",
        "alt_title": "千恋＊万花", "cover_url": "", "description": "",
        "developer": "", "released": "", "rating": 0, "length_minutes": 0,
        "tags": [],
    }])
    g = _game("千恋万花 汉化版")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.bangumi_id == "99", g.bangumi_id
    assert g.vndb_id == "", g.vndb_id
    assert g.title == "千恋万花", g.title
    print("[bangumi-only] OK")


def test_single_source_weak_rejected():
    _install([], [{
        "source": "Bangumi", "source_id": "5", "title": "完全不同的游戏",
        "alt_title": "", "cover_url": "", "description": "",
        "developer": "", "released": "", "rating": 0, "length_minutes": 0,
        "tags": [],
    }])
    g = _game("千恋万花")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "fail", (status, msg)
    assert g.bangumi_id == "" and g.vndb_id == ""
    assert "相似度不足" in msg, msg
    print("[single-source weak rejected] OK")


def test_sources_disagree_rejected():
    vndb = dict(VNDB_SUMMER, title="サクラノ詩", alt_title="Sakura no Uta")
    _install([vndb], [{
        "source": "Bangumi", "source_id": "7", "title": "千恋万花",
        "alt_title": "千恋＊万花", "cover_url": "", "description": "",
        "developer": "", "released": "", "rating": 0, "length_minutes": 0,
        "tags": [],
    }])
    g = _game("Sakura no Uta")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "fail", (status, msg)
    assert "不一致" in msg, msg
    assert g.vndb_id == "" and g.bangumi_id == ""
    print("[sources disagree rejected] OK")


def test_skip_when_matched():
    _install([VNDB_SUMMER], [BGM_SUMMER])
    g = _game("Summer Pockets", bangumi_id="12345")
    status, msg = mm.match_single(g)
    assert status == "skip", (status, msg)
    assert "12345" in msg, msg
    print("[skip matched] OK")


def test_year_remake_selection():
    old = {"vndb_id": "v1", "title": "Foo", "alt_title": "Foo",
           "cover_url": "", "rating": 3, "description": "old",
           "developer": "OldDev", "released": "2009-01-01",
           "length_minutes": 100}
    new = {"vndb_id": "v2", "title": "Foo Remake", "alt_title": "Foo Remake",
           "cover_url": "", "rating": 4, "description": "new",
           "developer": "NewDev", "released": "2023-06-23",
           "length_minutes": 2000}
    bgm = {"source": "Bangumi", "source_id": "b2", "title": "Foo 中文",
           "alt_title": "Foo Remake", "cover_url": "",
           "description": "中文简介", "developer": "",
           "released": "2023-06-23", "rating": 4, "length_minutes": 0,
           "tags": []}
    _install([old, new], [bgm])
    g = _game("Foo FHD", released="2023-06-23")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.vndb_id == "v2", g.vndb_id
    assert g.bangumi_id == "b2", g.bangumi_id
    assert g.title == "Foo 中文", g.title
    assert g.released == "2023-06-23", g.released
    assert g.developer == "NewDev", g.developer
    assert "Foo" in mm._build_queries("Foo FHD"), mm._build_queries("Foo FHD")
    print("[year remake selection] OK")


def test_force_overwrites_fields():
    _install([VNDB_SUMMER], [BGM_SUMMER])
    g = _game("Summer Pockets", vndb_id="v_old", bangumi_id="b_old",
              description="old english text", developer="WrongDev",
              released="1999-01-01", rating=1, length_minutes=1)
    status, msg = mm.match_single(g, force=True, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.vndb_id == "v123" and g.bangumi_id == "12345"
    assert g.description == "中文简介", g.description
    assert g.developer == "Key", g.developer
    assert g.released == "2018-06-29", g.released
    assert g.rating == 1, g.rating  # 用户评分不被覆盖
    assert g.length_minutes == 1800, g.length_minutes
    print("[force overwrite] OK")


def test_description_language_priority():
    _install([VNDB_SUMMER], [BGM_SUMMER])
    g = _game("Summer Pockets", description="English old text")
    status, _ = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", status
    assert g.description == "中文简介", g.description

    _install([VNDB_SUMMER], [])
    g2 = _game("Summer Pockets", description="中文旧简介")
    status, _ = mm.match_single(g2, cover_cb=lambda *a: None)
    assert status == "match", status
    assert g2.description == "中文旧简介", g2.description

    _install([VNDB_SUMMER], [])
    g3 = _game("Summer Pockets", description="中文旧简介")
    status, _ = mm.match_single(g3, force=True, cover_cb=lambda *a: None)
    assert status == "match", status
    assert g3.description == "English description", g3.description
    print("[description priority] OK")


def test_edition_without_year_rejected():
    old = {"vndb_id": "v1", "title": "Foo", "alt_title": "Foo",
           "cover_url": "", "rating": 3, "description": "old",
           "developer": "OldDev", "released": "2009-01-01",
           "length_minutes": 100}
    new = {"vndb_id": "v2", "title": "Foo Remake", "alt_title": "Foo Remake",
           "cover_url": "", "rating": 4, "description": "new",
           "developer": "NewDev", "released": "2023-06-23",
           "length_minutes": 2000}
    bgm = {"source": "Bangumi", "source_id": "b2", "title": "Foo 中文",
           "alt_title": "Foo", "cover_url": "",
           "description": "中文简介", "developer": "",
           "released": "2009-01-01", "rating": 4, "length_minutes": 0,
           "tags": []}
    _install([old, new], [bgm])
    g = _game("Foo FHD")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "fail", (status, msg)
    assert "版本标记" in msg, msg
    print("[edition without year rejected] OK")


def test_year_conflict_exact_vndb():
    v = {"vndb_id": "v1", "title": "Foo", "alt_title": "Foo",
         "cover_url": "", "rating": 3, "description": "",
         "developer": "", "released": "2009-01-01", "length_minutes": 100}
    b = {"source": "Bangumi", "source_id": "b1", "title": "Foo",
         "alt_title": "Foo 新版", "cover_url": "", "description": "中文",
         "developer": "", "released": "2020-01-01", "rating": 4,
         "length_minutes": 0, "tags": []}
    _install([v], [b])
    g = _game("Foo")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.vndb_id == "v1", g.vndb_id
    assert g.bangumi_id == "", g.bangumi_id
    print("[year conflict -> exact VNDB] OK")


def test_reflection_blue_token():
    v = {"vndb_id": "v20424", "title": "Summer Pockets",
         "alt_title": "", "cover_url": "", "rating": 4,
         "description": "", "developer": "Key",
         "released": "2018-06-29", "length_minutes": 3200}
    b = {"source": "Bangumi", "source_id": "295957",
         "title": "夏日口袋 REFLECTION BLUE",
         "alt_title": "Summer Pockets REFLECTION BLUE",
         "cover_url": "", "description": "中文简介", "developer": "",
         "released": "2020-06-26", "rating": 4, "length_minutes": 0,
         "tags": []}
    _install([v], [b])
    g = _game("Summer Pockets REFLECTION BLUE")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.bangumi_id == "295957", g.bangumi_id
    assert g.title == "夏日口袋 REFLECTION BLUE", g.title
    print("[reflection blue token] OK")


def test_edition_token_single_accept():
    v = {"vndb_id": "v1", "title": "Foo", "alt_title": "Foo",
         "cover_url": "", "rating": 3, "description": "",
         "developer": "", "released": "2010-01-01", "length_minutes": 100}
    b = {"source": "Bangumi", "source_id": "b1", "title": "Foo HD",
         "alt_title": "Foo HD", "cover_url": "", "description": "中文",
         "developer": "", "released": "2018-01-01", "rating": 4,
         "length_minutes": 0, "tags": []}
    _install([v], [b])
    g = _game("Foo HD")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.bangumi_id == "b1", g.bangumi_id
    assert g.title == "Foo HD", g.title
    print("[edition token single accept] OK")


def test_dash_subtitle_agreement():
    v = {"vndb_id": "v1552", "title": "ましろ色シンフォニー",
         "alt_title": "Mashiro-iro Symphony", "cover_url": "",
         "rating": 4, "description": "", "developer": "Palette",
         "released": "2009-10-30", "length_minutes": 100}
    b = {"source": "Bangumi", "source_id": "3306", "title": "纯白交响曲",
         "alt_title": "ましろ色シンフォニー -Love is Pure White-",
         "cover_url": "", "description": "中文简介", "developer": "",
         "released": "2009-10-30", "rating": 4, "length_minutes": 0,
         "tags": []}
    _install([v], [b])
    g = _game("纯白交响曲")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.title == "纯白交响曲", g.title
    assert g.vndb_id == "v1552" and g.bangumi_id == "3306"
    print("[dash subtitle agreement] OK")


def test_token_pair_merge():
    v = {"vndb_id": "v24717", "title": "金色ラブリッチェ-Golden Time-",
         "alt_title": "Kin'iro Loveriche -Golden Time-", "cover_url": "",
         "rating": 4, "description": "", "developer": "SAGA PLANETS",
         "released": "2019-02-22", "length_minutes": 600}
    b = {"source": "Bangumi", "source_id": "30226",
         "title": "金辉恋曲四重奏 -Golden Time-", "alt_title": "",
         "cover_url": "", "description": "中文简介", "developer": "",
         "released": "2019-02-22", "rating": 4, "length_minutes": 0,
         "tags": []}
    _install([v], [b])
    g = _game("金辉恋曲四重奏-Golden Time")
    status, msg = mm.match_single(g, cover_cb=lambda *a: None)
    assert status == "match", msg
    assert g.vndb_id == "v24717" and g.bangumi_id == "30226"
    assert g.title == "金辉恋曲四重奏 -Golden Time-", g.title
    print("[token pair merge] OK")


def test_parenthesized_suffix_query():
    assert mm._extract_japanese("9nine⑤-新章(最终章)") == "新章"
    print("[parenthesized suffix query] OK")


def test_similarity():
    assert mm._similarity("Summer Pockets", "summer-pockets") == 1.0
    assert mm._similarity("千恋万花", "千恋＊万花") > 0.9
    assert mm._similarity("", "abc") == 0.0
    print("[similarity] OK")


def test_title_variants_and_edition_strip():
    q1 = [q.lower() for q in mm._build_queries("9nine-九次九日九重色")]
    q2 = [q.lower() for q in mm._build_queries("9-nine-ここのつ")]
    assert "9nine" in q1, q1
    assert any("9-nine" in q for q in q2), q2
    assert mm._strip_edition("Foo Reflection Blue HD") == "Foo"
    assert mm._strip_edition("Foo Golden Time") == "Foo"
    print("[title variants / edition strip] OK")


def test_cross_source_series_affinity():
    v = {"title": "9-nine-ここのつ", "released": "2019-04-26"}
    b = {"title": "9-nine-九次九日九重色", "released": "2019-04-26"}
    group, reason = mm._pick_group({"vndb": v, "ymgal": b}, ["9nine-九次九日九重色"])
    assert group is not None, reason
    assert set(group) == {"vndb", "ymgal"}
    print("[cross-source series affinity] OK")


def main():
    test_title_variants_and_edition_strip()
    test_cross_source_series_affinity()
    test_similarity()
    test_consensus_merge()
    test_bangumi_only_chinese_folder()
    test_single_source_weak_rejected()
    test_sources_disagree_rejected()
    test_skip_when_matched()
    test_year_remake_selection()
    test_force_overwrites_fields()
    test_description_language_priority()
    test_edition_without_year_rejected()
    test_year_conflict_exact_vndb()
    test_reflection_blue_token()
    test_edition_token_single_accept()
    test_dash_subtitle_agreement()
    test_token_pair_merge()
    test_parenthesized_suffix_query()
    print("METADATA MATCH TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
