"""桥方法验证（无 GUI，直接调用 js_api 方法）"""
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from core.game_manager import GameManager
from core.game_model import Game
from ui.web_bridge import WebBridge


def main():
    tmp = tempfile.mktemp(suffix=".db")
    m = GameManager(db_path=tmp)
    for i in range(3):
        m.add_game(Game(id=f"g{i}", title=f"测试游戏{i}",
                        exe_path=f"C:\\x\\{i}.exe", folder="C:\\x",
                        engine="renpy", developer="Test", rating=4,
                        tags=["恋爱"], description="简介"))
    m.add_tag("恋爱", "#ffb3c1")
    m.add_category("商业作品")

    b = WebBridge(m)
    games = json.loads(b.getGames())
    assert len(games) == 3
    assert games[0]["cover_url"].startswith("data:")
    print("games:", len(games), "| cover: data URI | tags:", games[0]["tags"])
    print("config theme:", json.loads(b.getConfig()).get("theme"))
    print("tags:", json.loads(b.getTags()))
    print("cats:", json.loads(b.getCategories()))

    b.toggleFav("g0")
    assert m.get_game("g0").is_favorite
    print("fav ok")

    tag_id = json.loads(b.addTag("新标签", "#c4b5fd")).get("id")
    b.batchAddTag(json.dumps(["g0", "g1"]), tag_id)
    assert "新标签" in m.get_game("g0").tags
    print("batchAddTag ok")

    b.batchMoveCategory(json.dumps(["g0", "g1", "g2"]), 1)
    assert m.get_game("g0").category_id == 1
    print("batchMoveCategory ok")

    b.saveConfigs(json.dumps({"theme": "dark"}))
    assert json.loads(b.getConfig()).get("theme") == "dark"
    print("saveConfigs ok")

    os.remove(tmp)
    print("BRIDGE VERIFY PASS")


if __name__ == "__main__":
    main()
