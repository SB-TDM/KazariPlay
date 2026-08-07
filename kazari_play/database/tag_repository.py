"""标签与分类数据仓库（v2.4 新增）

设计约定（对齐《批量操作与标签分类计划书》）：
- 关联表 game_tags 是标签的**唯一数据源**；games.tags 列仅作兼容快照。
- 删除标签/分类时外键 CASCADE 或显式清理，避免脏引用。
"""
from typing import List, Optional, Dict
from datetime import datetime

from database.db_manager import DatabaseManager
from utils.logger import get_logger

logger = get_logger()


class TagRepository:
    """标签 CRUD + 游戏-标签关联 + 扁平分类"""

    def __init__(self):
        self.db = DatabaseManager()

    # ---------- 标签管理 ----------
    def get_all_tags(self) -> List[Dict]:
        rows = self.db.query(
            "SELECT id, name, color, sort_order FROM tags ORDER BY sort_order, name"
        )
        return [{"id": r[0], "name": r[1], "color": r[2] or "", "sort_order": r[3]}
                for r in rows] if rows else []

    def add_tag(self, name: str, color: str = "") -> Optional[int]:
        name = name.strip()
        if not name:
            return None
        ok = self.db.execute(
            "INSERT OR IGNORE INTO tags (name, color, created_at) VALUES (?, ?, ?)",
            (name, color, datetime.now().isoformat())
        )
        if not ok:
            return None
        rows = self.db.query("SELECT id FROM tags WHERE name = ?", (name,))
        return rows[0][0] if rows else None

    def rename_tag(self, tag_id: int, new_name: str) -> bool:
        new_name = new_name.strip()
        if not new_name:
            return False
        return self.db.execute(
            "UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id)
        )

    def delete_tag(self, tag_id: int) -> bool:
        return self.db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    def get_tag_usage_count(self, tag_id: int) -> int:
        rows = self.db.query(
            "SELECT COUNT(*) FROM game_tags WHERE tag_id = ?", (tag_id,)
        )
        return rows[0][0] if rows else 0

    # ---------- 游戏-标签关联 ----------
    def get_game_tags(self, game_id: str) -> List[Dict]:
        rows = self.db.query(
            """SELECT t.id, t.name, t.color FROM tags t
               JOIN game_tags gt ON t.id = gt.tag_id
               WHERE gt.game_id = ? ORDER BY t.sort_order, t.name""",
            (game_id,)
        )
        return [{"id": r[0], "name": r[1], "color": r[2] or ""}
                for r in rows] if rows else []

    def set_game_tags(self, game_id: str, tag_names: List[str]) -> bool:
        """按标签名全量设置游戏标签（供编辑保存 / 手动添加用）"""
        statements = [("DELETE FROM game_tags WHERE game_id = ?", (game_id,))]
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            statements.append(
                ("INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                 (name, datetime.now().isoformat()))
            )
            statements.append(
                ("INSERT OR IGNORE INTO game_tags (game_id, tag_id) "
                 "SELECT ?, id FROM tags WHERE name = ?", (game_id, name))
            )
        return self.db.execute_many(statements)

    def add_tag_to_game(self, game_id: str, tag_id: int) -> bool:
        return self.db.execute(
            "INSERT OR IGNORE INTO game_tags (game_id, tag_id) VALUES (?, ?)",
            (game_id, tag_id)
        )

    def remove_tag_from_game(self, game_id: str, tag_id: int) -> bool:
        return self.db.execute(
            "DELETE FROM game_tags WHERE game_id = ? AND tag_id = ?",
            (game_id, tag_id)
        )

    def get_games_by_tag(self, tag_id: int) -> List[str]:
        rows = self.db.query(
            "SELECT game_id FROM game_tags WHERE tag_id = ?", (tag_id,)
        )
        return [r[0] for r in rows] if rows else []

    # ---------- 分类管理（扁平） ----------
    def get_all_categories(self) -> List[Dict]:
        rows = self.db.query(
            "SELECT id, name, sort_order FROM categories ORDER BY sort_order, name"
        )
        return [{"id": r[0], "name": r[1], "sort_order": r[2]}
                for r in rows] if rows else []

    def add_category(self, name: str) -> Optional[int]:
        name = name.strip()
        if not name:
            return None
        self.db.execute(
            "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?)",
            (name, datetime.now().isoformat())
        )
        rows = self.db.query("SELECT id FROM categories WHERE name = ?", (name,))
        return rows[0][0] if rows else None

    def delete_category(self, cat_id: int) -> bool:
        self.db.execute("UPDATE games SET category_id = 0 WHERE category_id = ?", (cat_id,))
        return self.db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))

    def set_game_category(self, game_id: str, cat_id: int) -> bool:
        return self.db.execute(
            "UPDATE games SET category_id = ? WHERE id = ?", (cat_id, game_id)
        )

    def get_games_by_category(self, cat_id: int) -> List[str]:
        rows = self.db.query(
            "SELECT id FROM games WHERE category_id = ?", (cat_id,)
        )
        return [r[0] for r in rows] if rows else []

    def get_game_category(self, game_id: str) -> int:
        rows = self.db.query(
            "SELECT category_id FROM games WHERE id = ?", (game_id,)
        )
        return rows[0][0] if rows else 0
