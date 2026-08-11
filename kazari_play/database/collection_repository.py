"""收藏夹数据仓库（V1.0 collections）

树形收藏夹（分组→分类）+ 游戏多对多归类，参考 ReinaManager 的
CollectionsRepository，核心为 diff 差异算法 + 单事务（execute_many）。
"""
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from database.db_manager import DatabaseManager
from utils.logger import get_logger

logger = get_logger()


class CollectionRepository:
    """收藏夹数据仓库（树形 CRUD + 多对多关联 + diff 算法）"""

    def __init__(self):
        self.db = DatabaseManager()

    # ========== 收藏夹 CRUD ==========

    def get_tree(self) -> list:
        """返回树形结构：[{id,name,icon,color,sort_order,game_count,children:[...]}]"""
        rows = self.db.query("""
            SELECT c.id, c.name, c.parent_id, c.sort_order, c.icon, c.color,
                   (SELECT COUNT(*) FROM game_collection_link l WHERE l.collection_id = c.id) AS game_count
            FROM collections c
            ORDER BY c.sort_order, c.id
        """)
        if not rows:
            return []
        nodes = {}
        for r in rows:
            nodes[r[0]] = {
                "id": r[0], "name": r[1], "parent_id": r[2],
                "sort_order": r[3], "icon": r[4] or "", "color": r[5] or "",
                "game_count": r[6], "children": [],
            }
        roots = []
        for node in nodes.values():
            pid = node["parent_id"]
            if pid in nodes:
                nodes[pid]["children"].append(node)
            else:
                roots.append(node)
        return roots

    def get_root_collections(self) -> list:
        """parent_id IS NULL 的根节点（分组）"""
        rows = self.db.query(
            "SELECT id, name, icon, color, sort_order FROM collections WHERE parent_id IS NULL ORDER BY sort_order, id")
        return [{"id": r[0], "name": r[1], "icon": r[2] or "", "color": r[3] or "", "sort_order": r[4]}
                for r in rows] if rows else []

    def get_children(self, parent_id: int) -> list:
        """指定分组的子分类"""
        rows = self.db.query(
            "SELECT id, name, icon, color, sort_order FROM collections WHERE parent_id = ? ORDER BY sort_order, id",
            (parent_id,))
        return [{"id": r[0], "name": r[1], "icon": r[2] or "", "color": r[3] or "", "sort_order": r[4]}
                for r in rows] if rows else []

    def get_by_id(self, collection_id: int) -> Optional[dict]:
        rows = self.db.query(
            "SELECT id, name, parent_id, sort_order, icon, color FROM collections WHERE id = ?",
            (collection_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "name": r[1], "parent_id": r[2], "sort_order": r[3],
                "icon": r[4] or "", "color": r[5] or ""}

    def create(self, name: str, parent_id: Optional[int] = None, icon: str = "",
               color: str = "", sort_order: Optional[int] = None) -> Optional[dict]:
        """新建收藏夹。parent_id=None 表示根节点（分组）。返回新建记录。"""
        name = (name or "").strip()
        if not name:
            return None
        now = datetime.now().isoformat()
        if sort_order is None:
            rows = self.db.query(
                "SELECT COALESCE(MAX(sort_order), 0) FROM collections WHERE parent_id IS ?",
                (parent_id,))
            sort_order = (rows[0][0] if rows else 0) + 1
        new_id = self.db.execute_return_id(
            "INSERT INTO collections (name, parent_id, sort_order, icon, color, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, parent_id, sort_order, icon or "", color or "", now, now))
        return self.get_by_id(new_id) if new_id else None

    def update(self, collection_id: int, name: Optional[str] = None, parent_id: Optional[int] = None,
               icon: Optional[str] = None, color: Optional[str] = None,
               sort_order: Optional[int] = None) -> Optional[dict]:
        """更新收藏夹（仅更新非 None 字段）"""
        sets, params = [], []
        if name is not None:
            sets.append("name = ?"); params.append((name or "").strip())
        if parent_id is not None:
            sets.append("parent_id = ?"); params.append(parent_id)
        if icon is not None:
            sets.append("icon = ?"); params.append(icon or "")
        if color is not None:
            sets.append("color = ?"); params.append(color or "")
        if sort_order is not None:
            sets.append("sort_order = ?"); params.append(sort_order)
        if not sets:
            return self.get_by_id(collection_id)
        sets.append("updated_at = ?"); params.append(datetime.now().isoformat())
        params.append(collection_id)
        ok = self.db.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id = ?", tuple(params))
        return self.get_by_id(collection_id) if ok else None

    def delete(self, collection_id: int) -> bool:
        """删除收藏夹（级联删除子分类 + 关联）"""
        # ON DELETE CASCADE 处理 game_collection_link 与子分类（parent_id 自引用）
        # 但 SQLite 需要 PRAGMA foreign_keys=ON；同时显式清理保证可靠
        self.db.execute("DELETE FROM game_collection_link WHERE collection_id = ?", (collection_id,))
        children = self.db.query("SELECT id FROM collections WHERE parent_id = ?", (collection_id,))
        if children:
            for (cid,) in children:
                self.db.execute("DELETE FROM game_collection_link WHERE collection_id = ?", (cid,))
            self.db.execute("DELETE FROM collections WHERE parent_id = ?", (collection_id,))
        return self.db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))

    def reorder(self, collection_id: int, new_sort_order: int) -> bool:
        return self.db.execute(
            "UPDATE collections SET sort_order = ?, updated_at = ? WHERE id = ?",
            (new_sort_order, datetime.now().isoformat(), collection_id))

    # ========== 游戏-收藏夹关联（核心 diff 算法）==========

    def _current_links(self) -> List[Tuple[str, int, int]]:
        """返回 (game_id, collection_id, id) 列表"""
        rows = self.db.query("SELECT game_id, collection_id, id FROM game_collection_link")
        return [(r[0], r[1], r[2]) for r in rows] if rows else []

    def _max_sort_order(self, collection_id: int) -> int:
        rows = self.db.query(
            "SELECT COALESCE(MAX(sort_order), 0) FROM game_collection_link WHERE collection_id = ?",
            (collection_id,))
        return rows[0][0] if rows else 0

    def add_games_to_collections(self, game_ids: list, collection_ids: list) -> bool:
        """批量添加游戏到多个收藏夹（笛卡尔积，已存在的跳过，追加到末尾）"""
        game_ids = [g for g in game_ids if g]
        collection_ids = [c for c in collection_ids if c]
        if not game_ids or not collection_ids:
            return False
        current_map = {(gid, cid) for gid, cid, _ in self._current_links()}
        statements = []
        now = datetime.now().isoformat()
        for cid in collection_ids:
            so = self._max_sort_order(cid)
            for gid in game_ids:
                if (gid, cid) in current_map:
                    continue
                so += 1
                statements.append((
                    "INSERT INTO game_collection_link (game_id, collection_id, sort_order, created_at) "
                    "VALUES (?, ?, ?, ?)", (gid, cid, so, now)))
        return self.db.execute_many(statements)

    def set_game_collections(self, game_id: str, collection_ids: list) -> bool:
        """整体替换某游戏的收藏夹列表：删多余 + 插缺失"""
        collection_ids = [c for c in collection_ids if c]
        current = {cid: lid for gid, cid, lid in self._current_links()
                   if gid == game_id}
        target_set = set(collection_ids)
        statements = []
        now = datetime.now().isoformat()
        for cid in current:
            if cid not in target_set:
                statements.append(("DELETE FROM game_collection_link WHERE game_id = ? AND collection_id = ?",
                                   (game_id, cid)))
        for cid in collection_ids:
            if cid not in current:
                so = self._max_sort_order(cid) + 1
                statements.append((
                    "INSERT INTO game_collection_link (game_id, collection_id, sort_order, created_at) "
                    "VALUES (?, ?, ?, ?)", (game_id, cid, so, now)))
        return self.db.execute_many(statements)

    def set_collection_games(self, collection_id: int, game_ids: list) -> bool:
        """整体替换某收藏夹的游戏列表 + 排序：三类变更(删/插/改序)"""
        game_ids = [g for g in game_ids if g]
        current = {gid: lid for gid, cid, lid in self._current_links()
                   if cid == collection_id}
        target_set = set(game_ids)
        statements = []
        now = datetime.now().isoformat()
        for gid in current:
            if gid not in target_set:
                statements.append(("DELETE FROM game_collection_link WHERE id = ?", (current[gid],)))
        for order, gid in enumerate(game_ids):
            if gid in current:
                # 改序
                statements.append((
                    "UPDATE game_collection_link SET sort_order = ? WHERE id = ?",
                    (order, current[gid])))
            else:
                statements.append((
                    "INSERT INTO game_collection_link (game_id, collection_id, sort_order, created_at) "
                    "VALUES (?, ?, ?, ?)", (gid, collection_id, order, now)))
        return self.db.execute_many(statements)

    def remove_games_from_collection(self, game_ids: list, collection_id: int) -> bool:
        statements = [
            ("DELETE FROM game_collection_link WHERE game_id = ? AND collection_id = ?", (gid, collection_id))
            for gid in game_ids if gid
        ]
        return self.db.execute_many(statements) if statements else True

    def get_games_in_collection(self, collection_id: int) -> list:
        """获取收藏夹内的游戏 ID 列表（按 sort_order 排序）"""
        rows = self.db.query(
            "SELECT game_id FROM game_collection_link WHERE collection_id = ? ORDER BY sort_order, id",
            (collection_id,))
        return [r[0] for r in rows] if rows else []

    def get_game_collections(self, game_id: str) -> list:
        """获取游戏所在的收藏夹列表"""
        rows = self.db.query("""
            SELECT c.id, c.name, c.color, c.icon FROM collections c
            JOIN game_collection_link l ON c.id = l.collection_id
            WHERE l.game_id = ? ORDER BY l.sort_order
        """, (game_id,))
        return [{"id": r[0], "name": r[1], "color": r[2] or "", "icon": r[3] or ""}
                for r in rows] if rows else []

    def move_game_order(self, collection_id: int, game_id: str, new_sort_order: int) -> bool:
        return self.db.execute(
            "UPDATE game_collection_link SET sort_order = ? WHERE game_id = ? AND collection_id = ?",
            (new_sort_order, game_id, collection_id))

    def count_collections(self) -> int:
        rows = self.db.query("SELECT COUNT(*) FROM collections")
        return rows[0][0] if rows else 0
