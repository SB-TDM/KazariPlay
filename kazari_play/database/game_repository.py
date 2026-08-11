from typing import List, Optional
from core.game_model import Game
from database.db_manager import DatabaseManager

class GameRepository:
    """游戏数据仓库 - 负责数据库 CRUD"""
    
    def __init__(self):
        self.db = DatabaseManager()
    
    def add(self, game: Game) -> bool:
        """添加或更新游戏

        时间字段统一由 Python 端填 ISO 格式，不再依赖数据库 CURRENT_TIMESTAMP，
        保证全库时间格式一致，便于读取/序列化/跨平台。
        标签不写入 games.tags 列（由 GameManager 联动 TagRepository 写关联表）。
        """
        # 保险：若调用方没填 date_added，这里补上当前 ISO 时间
        if not game.date_added:
            from datetime import datetime
            game.date_added = datetime.now().isoformat()

        data = game.to_dict()
        sql = """
            INSERT OR REPLACE INTO games
            (id, title, exe_path, folder, cover_path, engine, tags,
             is_favorite, play_count, play_time, last_played, date_added, rating,
             logo_path, description, launch_exe_path,
             vndb_id, released, developer, length_minutes, category_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.db.execute(sql, (
            data["id"], data["title"], data["exe_path"], data["folder"],
            data["cover_path"], data["engine"], "",   # tags 列保持空（关联表唯一源）
            data["is_favorite"], data["play_count"], data["play_time"],
            data["last_played"], data["date_added"], data["rating"],
            data["logo_path"], data["description"], data["launch_exe_path"],
            data["vndb_id"], data["released"], data["developer"], data["length_minutes"],
            data["category_id"]
        ))

    def get_by_id(self, game_id: str) -> Optional[Game]:
        """根据 ID 获取"""
        rows = self.db.query("SELECT * FROM games WHERE id = ?", (game_id,))
        row = rows[0] if rows else None
        return self._row_to_game(row) if row else None
    
    def get_by_path(self, exe_path: str) -> Optional[Game]:
        """根据 exe 路径获取"""
        rows = self.db.query("SELECT * FROM games WHERE exe_path = ?", (exe_path,))
        row = rows[0] if rows else None
        return self._row_to_game(row) if row else None
    
    def get_all(self) -> List[Game]:
        """获取所有游戏"""
        rows = self.db.query("SELECT * FROM games ORDER BY title")
        if not rows:
            return []
        return [self._row_to_game(row) for row in rows]
    
    def get_favorites(self) -> List[Game]:
        """获取收藏的游戏"""
        rows = self.db.query("SELECT * FROM games WHERE is_favorite = 1 ORDER BY title")
        if not rows:
            return []
        return [self._row_to_game(row) for row in rows]
    
    def search(self, keyword: str) -> List[Game]:
        """搜索游戏"""
        rows = self.db.query(
            "SELECT * FROM games WHERE title LIKE ? OR engine LIKE ? OR tags LIKE ?",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
        )
        if not rows:
            return []
        return [self._row_to_game(row) for row in rows]
    
    def delete(self, game_id: str) -> bool:
        """删除游戏"""
        return self.db.execute("DELETE FROM games WHERE id = ?", (game_id,))

    def update_favorite(self, game_id: str, is_favorite: bool) -> bool:
        """更新收藏状态"""
        return self.db.execute(
            "UPDATE games SET is_favorite = ? WHERE id = ?",
            (1 if is_favorite else 0, game_id)
        )
    
    def update_rating(self, game_id: str, rating: int) -> bool:
        """更新评分"""
        return self.db.execute(
            "UPDATE games SET rating = ? WHERE id = ?",
            (rating, game_id)
        )

    def update_title(self, game_id: str, new_title: str) -> bool:
        """更新游戏标题（支持用户手动改名）"""
        if not new_title or not new_title.strip():
            return False
        return self.db.execute(
            "UPDATE games SET title = ? WHERE id = ?",
            (new_title.strip(), game_id)
        )

    def update_game(self, game: Game) -> bool:
        """更新游戏的全部可编辑字段（标题/引擎/标签/Logo/封面/描述/启动路径/VNDB元数据/分类）

        play_count/play_time/last_played/date_added/is_favorite/rating 不变。
        标签不写 games.tags 列（由 GameManager 联动 TagRepository 写关联表）。
        """
        return self.db.execute(
            """UPDATE games SET
               title = ?, engine = ?, tags = ?,
               cover_path = ?, logo_path = ?, description = ?,
               launch_exe_path = ?,
               vndb_id = ?, released = ?, developer = ?, length_minutes = ?,
               category_id = ?
               WHERE id = ?""",
            (game.title, game.engine or "", "",
             game.cover_path or "", game.logo_path or "",
             game.description or "", game.launch_exe_path or "",
             game.vndb_id or "", game.released or "",
             game.developer or "", game.length_minutes or 0,
             game.category_id or 0, game.id)
        )
    
    def record_play(self, game_id: str):
        """记录游玩时间（更新 last_played，不再递增 play_count）"""
        from datetime import datetime
        self.db.execute(
            "UPDATE games SET last_played = ? WHERE id = ?",
            (datetime.now().isoformat(), game_id)
        )
    
    def increment_play_time(self, game_id: str, minutes: int = 1):
        """增加游玩时长"""
        self.db.execute(
            "UPDATE games SET play_time = play_time + ? WHERE id = ?",
            (minutes, game_id)
        )
    
    def get_count(self) -> int:
        """获取游戏总数"""
        rows = self.db.query("SELECT COUNT(*) FROM games")
        return rows[0][0] if rows else 0
    
    def _row_to_game(self, row) -> Game:
        """将数据库行转换为 Game 对象（标签从关联表加载）"""
        return Game(
            id=row[0],
            title=row[1],
            exe_path=row[2],
            folder=row[3],
            cover_path=row[4],
            engine=row[5] or "",
            tags=self._load_tags(row[0]),
            collections=self._load_collections(row[0]),
            is_favorite=bool(row[7]),
            play_count=row[8],
            play_time=row[9],
            last_played=row[10],
            date_added=row[11] or "",
            rating=row[12] or 0,
            logo_path=row[13] if len(row) > 13 else "",
            description=row[14] if len(row) > 14 else "",
            launch_exe_path=row[15] if len(row) > 15 else "",
            vndb_id=row[16] if len(row) > 16 else "",
            released=row[17] if len(row) > 17 else "",
            developer=row[18] if len(row) > 18 else "",
            length_minutes=row[19] if len(row) > 19 else 0,
            category_id=row[20] if len(row) > 20 else 0,
        )

    def _load_tags(self, game_id: str) -> List[str]:
        """从 game_tags 关联表加载标签名（唯一数据源）"""
        rows = self.db.query(
            """SELECT t.name FROM tags t
               JOIN game_tags gt ON t.id = gt.tag_id
               WHERE gt.game_id = ? ORDER BY t.sort_order, t.name""",
            (game_id,)
        )
        return [r[0] for r in rows] if rows else []

    def _load_collections(self, game_id: str) -> list:
        """从 game_collection_link 加载游戏所属的收藏夹列表"""
        rows = self.db.query(
            """SELECT c.id, c.name, c.color, c.icon FROM collections c
               JOIN game_collection_link l ON c.id = l.collection_id
               WHERE l.game_id = ? ORDER BY l.sort_order""",
            (game_id,)
        )
        return [{"id": r[0], "name": r[1], "color": r[2] or "", "icon": r[3] or ""}
                for r in rows] if rows else []