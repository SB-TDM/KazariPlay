"""迁移旧 Launcher games.db 数据到 KazariPlay V1.0

- 清空新库现有 games/tags/game_tags/categories/settings 数据（先备份新库为 .bak）
- 按新结构插入 games（tags 列置空，category_id=0）
- 旧 games.tags 逗号串 → 新 tags 表 + game_tags 关联表
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))
from utils.path_utils import get_default_db_path
from database.db_manager import DatabaseManager

OLD_DB = r"E:\文件夹\Launcher\Launcher\data\games.db"

INSERT_SQL = """INSERT INTO games
  (id,title,exe_path,folder,cover_path,engine,tags,is_favorite,play_count,play_time,
   last_played,date_added,rating,logo_path,description,launch_exe_path,
   vndb_id,released,developer,length_minutes,category_id)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def main():
    if not os.path.exists(OLD_DB):
        print("旧库不存在:", OLD_DB)
        return
    new_db = get_default_db_path()
    print("旧库:", OLD_DB)
    print("新库:", new_db)

    DatabaseManager()  # 确保新库表结构

    oc = sqlite3.connect(OLD_DB)
    ocols = [r[1] for r in oc.execute("PRAGMA table_info(games)").fetchall()]
    ogames = oc.execute("SELECT * FROM games").fetchall()
    osettings = oc.execute("SELECT key,value FROM settings").fetchall()
    oc.close()
    print(f"旧库 games 行数: {len(ogames)}，列: {ocols}")

    bak = new_db + ".bak"
    if os.path.exists(new_db):
        shutil.copy2(new_db, bak)
        print("已备份当前新库 ->", bak)

    nc = sqlite3.connect(new_db)
    for t in ("game_tags", "games", "tags", "categories", "settings"):
        nc.execute(f"DELETE FROM {t}")
    nc.commit()

    now = datetime.now().isoformat()
    for row in ogames:
        d = dict(zip(ocols, row))
        nc.execute(INSERT_SQL, (
            d.get("id", ""), d.get("title", ""), d.get("exe_path", ""),
            d.get("folder", ""), d.get("cover_path", "") or "",
            d.get("engine", "") or "", "",
            int(d.get("is_favorite", 0) or 0), int(d.get("play_count", 0) or 0),
            int(d.get("play_time", 0) or 0), d.get("last_played", "") or "",
            d.get("date_added", "") or "", int(d.get("rating", 0) or 0),
            d.get("logo_path", "") or "", d.get("description", "") or "",
            d.get("launch_exe_path", "") or "",
            d.get("vndb_id", "") or "", d.get("released", "") or "",
            d.get("developer", "") or "", int(d.get("length_minutes", 0) or 0),
            0))

    for row in ogames:
        d = dict(zip(ocols, row))
        gid = d.get("id", "")
        for t in (d.get("tags", "") or "").split(","):
            t = t.strip()
            if not t:
                continue
            nc.execute("INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                       (t, now))
            tid = nc.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()
            if tid:
                nc.execute("INSERT OR IGNORE INTO game_tags (game_id, tag_id) VALUES (?, ?)",
                           (gid, tid[0]))

    for k, v in osettings:
        nc.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    nc.commit()

    ngames = nc.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    ntags = nc.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    ngame_tags = nc.execute("SELECT COUNT(*) FROM game_tags").fetchone()[0]
    sample = nc.execute("SELECT title, category_id FROM games LIMIT 3").fetchall()
    tagged = nc.execute(
        "SELECT g.title, COUNT(gt.tag_id) FROM games g LEFT JOIN game_tags gt"
        " ON g.id=gt.game_id GROUP BY g.id LIMIT 3").fetchall()
    nc.close()
    print(f"迁移完成: games={ngames} tags={ntags} game_tags={ngame_tags}")
    print("示例 games:", sample)
    print("示例标签:", tagged)
    print("MIGRATE DONE")


if __name__ == "__main__":
    main()
