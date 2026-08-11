"""collections 系统后端冒烟测试（临时库，不动真实数据）"""
import os
import sys
import json
import tempfile
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from core.game_manager import GameManager
from core.game_model import Game
from ui.web_bridge import WebBridge


def reset_singleton():
    from database.db_manager import DatabaseManager
    DatabaseManager._instance = None


def make_legacy_db(path):
    """构造带旧数据的库，验证迁移"""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE games (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, exe_path TEXT NOT NULL UNIQUE,
            folder TEXT NOT NULL, cover_path TEXT, engine TEXT DEFAULT '',
            tags TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, play_count INTEGER DEFAULT 0,
            play_time INTEGER DEFAULT 0, last_played TEXT, date_added TEXT,
            rating INTEGER DEFAULT 0, logo_path TEXT DEFAULT '', description TEXT DEFAULT '',
            launch_exe_path TEXT DEFAULT '', vndb_id TEXT DEFAULT '', released TEXT DEFAULT '',
            developer TEXT DEFAULT '', length_minutes INTEGER DEFAULT 0, category_id INTEGER DEFAULT 0);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, created_at TEXT DEFAULT '');
        CREATE TABLE game_tags (game_id TEXT NOT NULL, tag_id INTEGER NOT NULL,
            PRIMARY KEY (game_id, tag_id));
        CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0, created_at TEXT DEFAULT '');
        INSERT INTO categories (name, sort_order, created_at) VALUES ('9nine',0,''),('saga',1,''),('八月',2,'');
        INSERT INTO tags (name, color, created_at) VALUES ('测试','#ffb3c1',''),('CSharp','#c4b5fd',''),('新','#b5ead7','');
        INSERT INTO games (id,title,exe_path,folder,category_id) VALUES
            ('g1','游戏一','C:\\a\\g1.exe','C:\\a',1),
            ('g2','游戏二','C:\\a\\g2.exe','C:\\a',2),
            ('g3','游戏三','C:\\a\\g3.exe','C:\\a',3),
            ('g4','游戏四','C:\\a\\g4.exe','C:\\a',0),
            ('g5','游戏五','C:\\a\\g5.exe','C:\\a',3);
        INSERT INTO game_tags (game_id, tag_id) VALUES ('g1', 1);
    """)
    conn.commit()
    conn.close()


def test_migration():
    reset_singleton()
    tmp = tempfile.mktemp(suffix=".db")
    make_legacy_db(tmp)
    m = GameManager(db_path=tmp)
    tree = m.get_collections_tree()
    assert len(tree) == 4, f"根分组应为 4（3分类+标签分组），实际 {len(tree)}: {[t['name'] for t in tree]}"
    tag_grp = [t for t in tree if t["name"] == "标签"][0]
    assert len(tag_grp["children"]) == 3, "标签分组下应有 3 个子分类"
    links = m.get_game_collections("g1")
    assert any(c["name"] == "9nine" for c in links), "g1 应属于 9nine"
    assert any(c["name"] == "测试" for c in links), "g1 应属于 测试(标签迁移)"
    # g2 → saga, g3/g5 → 八月
    assert any(c["name"] == "saga" for c in m.get_game_collections("g2"))
    assert len(m.get_game_collections("g5")) == 1 and m.get_game_collections("g5")[0]["name"] == "八月"
    print("[迁移] OK: collections 树结构正确, g1 双归属验证通过")
    os.remove(tmp)


def test_crud():
    reset_singleton()
    tmp = tempfile.mktemp(suffix=".db")
    m = GameManager(db_path=tmp)
    for i in range(4):
        m.add_game(Game(id=f"g{i}", title=f"游戏{i}", exe_path=f"C:\\x\\{i}.exe",
                        folder="C:\\x", engine="renpy", developer="Test", rating=4))
    grp = m.create_collection("Galgame")
    cat = m.create_collection("剧情作", parent_id=grp["id"], color="#ffb3c1")
    assert m.create_collection("") is None, "空名不应创建"
    # 批量添加（笛卡尔积 + 去重）
    assert m.add_games_to_collections(["g0", "g1", "g2"], [cat["id"]])
    assert m.add_games_to_collections(["g0", "g1"], [cat["id"]])  # 重复添加应跳过
    assert len(m.get_games_in_collection(cat["id"])) == 3
    # 整体替换某游戏收藏夹
    assert m.set_game_collections("g3", [cat["id"]])
    assert len(m.get_game_collections("g3")) == 1
    assert m.set_game_collections("g3", [])
    assert m.get_game_collections("g3") == []
    # 从收藏夹移除
    assert m.remove_games_from_collection(["g0"], cat["id"])
    assert "g0" not in m.get_games_in_collection(cat["id"])
    # 树含 game_count
    tree = m.get_collections_tree()
    gal = [t for t in tree if t["name"] == "Galgame"][0]
    assert gal["children"][0]["game_count"] == 2, f"剧情作应含 2 个游戏, 实际 {gal['children'][0]['game_count']}"
    # 删除分组级联
    assert m.delete_collection(grp["id"])
    tree = m.get_collections_tree()
    assert all(t["name"] != "Galgame" for t in tree)
    print("[CRUD] OK: 创建/笛卡尔积/去重/替换/移除/级联删除 全部通过")
    os.remove(tmp)


def test_bridge():
    reset_singleton()
    tmp = tempfile.mktemp(suffix=".db")
    m = GameManager(db_path=tmp)
    m.add_game(Game(id="g0", title="游戏0", exe_path="C:\\x\\0.exe",
                    folder="C:\\x", engine="renpy", developer="Test", rating=4))
    b = WebBridge(m)
    grp = json.loads(b.createCollection("我的分组", 0, "", ""))
    assert grp["id"] > 0
    cat = json.loads(b.createCollection("百合", grp["id"], "", "#ffb3c1"))
    b.addGamesToCollection(json.dumps(["g0"]), cat["id"])
    tree = json.loads(b.getCollectionsTree())
    assert tree[0]["children"][0]["game_count"] == 1
    g = json.loads(b.getGame("g0"))
    assert g["collections"][0]["name"] == "百合", "getGame 应返回 collections"
    b.setGameCollections("g0", json.dumps([]))
    assert json.loads(b.getGame("g0"))["collections"] == []
    assert json.loads(b.getGamesInCollection(cat["id"])) == []
    # setCollectionGames：整体替换收藏夹游戏列表
    m.add_game(Game(id="g1", title="游戏1", exe_path="C:\\x\\1.exe",
                    folder="C:\\x", engine="renpy", developer="Test", rating=4))
    m.add_game(Game(id="g2", title="游戏2", exe_path="C:\\x\\2.exe",
                    folder="C:\\x", engine="renpy", developer="Test", rating=4))
    assert b.setCollectionGames(cat["id"], json.dumps(["g1", "g2"])) is True
    assert json.loads(b.getGamesInCollection(cat["id"])) == ["g1", "g2"]
    assert b.setCollectionGames(cat["id"], json.dumps(["g2"])) is True
    assert json.loads(b.getGamesInCollection(cat["id"])) == ["g2"]
    print("[Bridge] OK: setCollectionGames 整体替换 + 重排 通过")
    os.remove(tmp)


if __name__ == "__main__":
    test_migration()
    test_crud()
    test_bridge()
    print("ALL PASS")
