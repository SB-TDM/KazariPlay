"""多源元数据自动匹配的离线回归（不访问真实网络）

覆盖 core/metadata/pipeline/metadata_matcher.py：
1. VNDB + Bangumi 标题一致 → 合并，标题优先中文，字段按优先级取
2. Bangumi 单源命中（中文文件夹名）→ 采用并记录 bangumi_id
3. 单源候选与标题差异过大 → 拒绝（避免误匹配）
4. 多源结果不一致 → 拒绝并提示手动确认
5. 已有 bangumi_id → 跳过；相似度函数边界
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "kazari_play"))

import utils.infra.logger as logger_module  # noqa: E402

logger_module._initialized = True

from core.games.game_model import Game  # noqa: E402
from core.metadata.search import multi_source as ms  # noqa: E402
from core.metadata.merge import merge as merge_mod  # noqa: E402
from core.metadata.pipeline import metadata_matcher as mm  # noqa: E402
from core.metadata.candidates.candidates import (  # noqa: E402
    _pick_group, _pick_result, _similarity,
)
from core.metadata.candidates.queries import _extract_japanese, _strip_edition  # noqa: E402
from core.metadata.search import search as metadata_search  # noqa: E402
from core.metadata.search.search import _search_source  # noqa: E402
from core.metadata.candidates.title_policy import (  # noqa: E402
    exact_title_match, part_score, trailing_part,
)


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
    assert status == "unmatched", (status, msg)
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
    assert status == "unmatched", (status, msg)
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
    assert status == "match", (status, msg)
    assert g.vndb_id == "v1", g.vndb_id
    assert g.title == "Foo FHD", g.title
    print("[edition without year uses base VN] OK")


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
    assert _extract_japanese("9nine⑤-新章(最终章)") == "新章"
    print("[parenthesized suffix query] OK")


def test_similarity():
    assert _similarity("Summer Pockets", "summer-pockets") == 1.0
    assert _similarity("千恋万花", "千恋＊万花") > 0.9
    assert _similarity("", "abc") == 0.0
    print("[similarity] OK")


def test_title_variants_and_edition_strip():
    q1 = [q.lower() for q in mm._build_queries("9nine-九次九日九重色")]
    q2 = [q.lower() for q in mm._build_queries("9-nine-ここのつ")]
    assert "9nine" in q1, q1
    assert any("9-nine" in q for q in q2), q2
    assert _strip_edition("Foo Reflection Blue HD") == "Foo"
    assert _strip_edition("Foo Golden Time") == "Foo"
    assert "eden" in mm._build_queries("eden＊")
    assert exact_title_match("eden＊", ["eden*"])
    qs = mm._build_queries("大图书馆的牧羊人-Dreaming-Sheep")
    picked = _pick_result([
        {"source_id": "base", "title": "大图书馆的牧羊人"},
        {"source_id": "fd", "title": "大图书馆的牧羊人 Dreaming Sheep"},
    ], qs, None, False)
    assert picked["source_id"] == "fd", picked
    qs = mm._build_queries("千之刃涛-桃花染之皇姬_弥生月汉化组")
    picked = _pick_result([
        {"source_id": "base", "title": "千之刃涛、桃花染之皇姬"},
        {"source_id": "extra", "title": "千之刃涛、桃花染之皇姬 -花あかり-"},
    ], qs, None, False)
    assert picked["source_id"] == "base", picked
    qs = mm._build_queries("近月少女的礼仪")
    picked = _pick_result([
        {"source_id": "base", "title": "近月少女的礼仪"},
        {"source_id": "sequel", "title": "近月少女的礼仪2"},
    ], qs, None, False)
    assert picked["source_id"] == "base", picked
    qs = mm._build_queries("近月少女的礼仪1")
    picked = _pick_result([
        {"source_id": "base", "title": "近月少女的礼仪"},
        {"source_id": "sequel", "title": "近月少女的礼仪2"},
    ], qs, None, False)
    assert picked["source_id"] == "base", picked
    assert trailing_part("近月少女的礼仪1") == "1"
    assert part_score("1", "2") < 0
    assert part_score("", "2") < 0
    qs = mm._build_queries("CLANNAD HD")
    picked = _pick_result([
        {"source_id": "base", "title": "CLANNAD"},
        {"source_id": "side", "title": "CLANNAD - 智代アフター"},
    ], qs, ["hd"], False)
    assert picked["source_id"] == "base", picked
    assert mm._soft_edition(["hd"])
    print("[title variants / edition strip] OK")


def test_same_series_without_bridge_is_not_merged():
    v = {"title": "9-nine-Alpha", "released": "2019-04-26"}
    b = {"title": "9-nine-Zeta", "released": "2019-04-26"}
    group, reason = _pick_group({"vndb": v, "ymgal": b}, ["9nine-Zeta"])
    assert group is None, reason
    print("[same series without bridge rejected] OK")




def test_cover_source_priority():
    class FakeConfig:
        def get(self, key, default=None):
            return "kungal" if key == "cover_download.preferred_source" else default

    group = {
        "vndb": {"cover_url": "https://vndb/cover.jpg"},
        "kungal": {"cover_url": "https://kungal/cover.jpg"},
    }
    with patch.object(merge_mod, "Config", FakeConfig):
        merged = merge_mod._merge_candidates(group)
    assert merged["cover_url"] == "https://kungal/cover.jpg", merged["cover_url"]
    print("[cover source priority] OK")


def test_base_before_fd_by_primary_subtitle():
    base = {
        "vndb_id": "v15708",
        "title": "千の刃濤、桃花染の皇姫",
        "alt_title": "Sen no Hatou, Tsukisome no Kouki",
        "all_titles": [
            "Senmomo: Through Billows of Blades, A Peachbloom Princess",
            "千の刃濤、桃花染の皇姫",
            "千之刃涛，桃花染之皇姬",
        ],
    }
    fd = {
        "vndb_id": "v26001",
        "title": "千の刃濤、桃花染の皇姫 -花あかり-",
        "alt_title": "Sen no Hatou, Tsukisome no Kouki -Hana Akari-",
        "all_titles": [
            "千の刃濤、桃花染の皇姫 -花あかり-",
            "千之刃涛，桃花染之皇姬 -柳暗花明-",
        ],
    }
    picked = _pick_result([fd, base], ["千之刃涛-桃花染之皇姬"], None, False)
    assert picked["vndb_id"] == "v15708", picked
    print("[base before fd by primary subtitle] OK")


def test_vndb_alias_exact_preferred():
    correct = {
        "vndb_id": "v21523", "title": "アオイトリ", "alt_title": "Aoi Tori",
        "all_titles": ["Aoi Tori", "アオイトリ", "青鸟"],
        "aliases": ["Blue Bird", "Caged Bird"],
    }
    wrong = {
        "vndb_id": "v64142", "title": "青鸟", "alt_title": "Qing Niao",
        "aliases": ["The Azure One"],
    }
    picked = _pick_result([correct, wrong], ["青鸟"], None, False)
    assert picked["vndb_id"] == "v21523", picked
    print("[vndb alias exact preferred] OK")


def test_kungal_ambiguous_anchor_rejected():
    old = ms.SOURCES["kungal"]["client"]
    ms.SOURCES["kungal"]["client"] = FakeClient([
        {"id": "59620", "title": "青鸟", "developer": "Haoyunfeng"},
        {"id": "324", "title": "青鸟", "developer": "Purple SOFTWARE"},
    ])
    try:
        assert _search_source("kungal", ["青鸟"], reject_ambiguous=True) is None
    finally:
        ms.SOURCES["kungal"]["client"] = old
    print("[kungal ambiguous anchor rejected] OK")




def test_edition_supplement_keeps_cache_dict():
    calls = []

    def fake_search(source_id, queries, cancel_event=None, trust_rank=False,
                    edition_tokens=None, cache=None, reject_ambiguous=False):
        assert cache is None or isinstance(cache, dict), type(cache)
        calls.append(source_id)
        return {"source": source_id, "source_id": source_id,
                "title": queries[0]}

    with patch.object(ms, "get_mixed_sources", return_value=["vndb", "bangumi"]), \
         patch.object(ms, "source_available", return_value=True), \
         patch.object(metadata_search, "_search_source", side_effect=fake_search):
        result = metadata_search._search_all(
            ["Foo FHD"], edition_tokens=["fhd"], cache={})
    assert "vndb" in result and "bangumi" in result
    print("[edition supplement cache dict] OK")


def test_conflicting_external_ids_are_not_merged():
    v = {"title": "Eden", "vndb_id": "v1286"}
    k = {"title": "Eden", "vndb_id": "v2285"}
    group, reason = _pick_group({"vndb": v, "kungal": k}, ["Eden"])
    assert group is None, reason
    assert "外部 ID 冲突" in reason, reason
    b1 = {"title": "青鸟", "bangumi_id": "111"}
    b2 = {"title": "青鸟", "bangumi_id": "222"}
    group, reason = _pick_group({"vndb": b1, "bangumi": b2}, ["青鸟"])
    assert group is None, reason
    assert "外部 ID 冲突" in reason, reason
    print("[conflicting external ids rejected] OK")



def test_retryable_and_unmatched_status():
    game = Game(id="status", title="Status Game")
    with patch.object(ms, "get_mixed_sources", return_value=["vndb"]), \
         patch.object(ms, "source_available", return_value=False), \
         patch.object(mm, "_resolve_anchor", return_value={}), \
         patch.object(mm, "_search_all", return_value={}):
        status, _ = mm.match_single(game)
        assert status == "retryable", status
    with patch.object(ms, "get_mixed_sources", return_value=["vndb"]), \
         patch.object(ms, "source_available", return_value=True), \
         patch.object(mm, "_resolve_anchor", return_value={}), \
         patch.object(mm, "_search_all", return_value={}):
        status, _ = mm.match_single(game)
        assert status == "unmatched", status
        assert game.unmatched_code == "no_candidate", game.unmatched_code
    print("[retryable/unmatched status] OK")


def test_duplicate_version_earliest_wins():
    older = Game(id="older", title="Same", date_added="2020-01-01T00:00:00")
    newer = Game(id="newer", title="Same", date_added="2021-01-01T00:00:00")
    statuses = []

    def fake_match(game, **kwargs):
        game.vndb_id = "v1"
        return "match", "ok"

    def result_cb(game, status, msg):
        statuses.append((game.id, status))

    with patch.object(mm, "_prefetch_anchors", return_value=({}, False)), \
         patch.object(mm, "match_single", side_effect=fake_match):
        summary = mm.match_batch([newer, older], force=True, result_cb=result_cb)
    assert summary == (1, 0, 1, 0), summary
    assert older.vndb_id == "v1"
    assert newer.vndb_id == ""
    assert newer.unmatched_code == "duplicate_version"
    assert statuses == [("older", "match"), ("newer", "unmatched")], statuses
    print("[duplicate version earliest wins] OK")


def test_batch_defers_duplicate_side_effects():
    older = Game(id="older", title="Same", vndb_id="v1",
                 date_added="2020-01-01T00:00:00")
    newer = Game(id="newer", title="Same", vndb_id="v1",
                 date_added="2021-01-01T00:00:00")
    sources, covers = [], []

    def fake_match(game, **kwargs):
        kwargs["source_cb"](game.id, {"vndb": {"source_id": "v1"}})
        kwargs["cover_cb"](game.id, "cover-url", "cover-dest")
        return "match", "ok"

    with patch.object(mm, "_prefetch_anchors", return_value=({}, False)), \
         patch.object(mm, "match_single", side_effect=fake_match):
        summary = mm.match_batch(
            [newer, older], force=True,
            source_cb=lambda gid, group: sources.append(gid),
            cover_cb=lambda gid, url, dest: covers.append(gid))
    assert summary == (1, 0, 1, 0), summary
    assert sources == ["older"], sources
    assert covers == ["older"], covers
    print("[batch defers duplicate side effects] OK")


def test_local_titles_skip_engine_descriptions():
    game = Game(id="filter", title="Musica", folder="E:/games/Musica",
                exe_path="E:/games/Musica/SiglusEngine.exe")
    titles = mm._local_titles(game)
    assert "Musica" in titles
    assert all("siglus" not in t.lower() for t in titles), titles
    print("[local titles skip engine] OK")


def test_search_source_cache_reuses_query():
    class CountingClient(FakeClient):
        def __init__(self, results):
            super().__init__(results)
            self.count = 0

        def search(self, keyword, count=5):
            self.count += 1
            return super().search(keyword, count)

    client = CountingClient([dict(VNDB_SUMMER)])
    ms.SOURCES["vndb"]["client"] = client
    cache = {}
    first = _search_source("vndb", ["Summer Pockets"], cache=cache)
    first["title"] = "mutated"
    second = _search_source("vndb", ["Summer Pockets"], cache=cache)
    assert first and second
    assert second["title"] != "mutated", second
    assert client.count == 1, client.count
    print("[search source cache] OK")


def main():
    test_title_variants_and_edition_strip()
    test_same_series_without_bridge_is_not_merged()
    test_conflicting_external_ids_are_not_merged()
    test_cover_source_priority()
    test_base_before_fd_by_primary_subtitle()
    test_vndb_alias_exact_preferred()
    test_kungal_ambiguous_anchor_rejected()
    test_edition_supplement_keeps_cache_dict()
    test_similarity()
    test_consensus_merge()
    test_bangumi_only_chinese_folder()
    test_single_source_weak_rejected()
    test_sources_disagree_rejected()
    test_skip_when_matched()
    test_force_overwrites_fields()
    test_description_language_priority()
    test_retryable_and_unmatched_status()
    test_duplicate_version_earliest_wins()
    test_batch_defers_duplicate_side_effects()
    test_local_titles_skip_engine_descriptions()
    test_search_source_cache_reuses_query()
    test_edition_without_year_rejected()
    test_reflection_blue_token()
    test_edition_token_single_accept()
    test_dash_subtitle_agreement()
    test_token_pair_merge()
    test_parenthesized_suffix_query()
    print("METADATA MATCH TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
