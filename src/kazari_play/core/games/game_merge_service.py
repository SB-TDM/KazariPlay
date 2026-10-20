"""手动合并两张本地游戏卡片。

合并是显式高风险操作：调用方必须已经做过用户确认。服务负责在数据库事务中
合并关联数据，并尽量保留目标卡已有字段；截图先移动，数据库失败时回滚文件。
"""
import os
import shutil
from typing import List, Tuple

from core.games.game_model import Game
from database.db_manager import DatabaseManager
from database.repositories.game_repository import GameRepository
from utils.infra.logger import get_logger
from utils.infra.path_utils import get_game_screenshots_dir

logger = get_logger()


class GameMergeService:
    def __init__(self, db: DatabaseManager = None,
                 repository: GameRepository = None):
        self.db = db or DatabaseManager()
        self.repository = repository or GameRepository()

    @staticmethod
    def _first(target: str, source: str) -> str:
        return target or source

    @staticmethod
    def _max_text(a: str, b: str) -> str:
        return max(a or "", b or "")

    @staticmethod
    def _min_text(a: str, b: str) -> str:
        values = [v for v in (a, b) if v]
        return min(values) if values else ""

    def merge(self, source_id: str, target_id: str) -> dict:
        if not source_id or not target_id:
            return {"ok": False, "msg": "缺少卡片 ID"}
        if source_id == target_id:
            return {"ok": False, "msg": "不能合并到自身"}
        source = self.repository.get_by_id(source_id)
        target = self.repository.get_by_id(target_id)
        if not source or not target:
            return {"ok": False, "msg": "卡片不存在"}

        moved: List[Tuple[str, str]] = []
        try:
            moved = self._move_screenshots(source_id, target_id)
        except Exception as e:  # noqa: BLE001
            logger.error("合并截图失败: %s", e)
            return {"ok": False, "msg": f"合并截图失败: {e}"}

        try:
            with self.db.transaction() as conn:
                self._merge_tags(conn, source_id, target_id)
                self._merge_collections(conn, source_id, target_id)
                self._merge_sources(conn, source_id, target_id)
                self._update_target(conn, target, source)
                self._delete_source(conn, source_id, target_id)
        except Exception as e:  # noqa: BLE001
            self._rollback_screenshots(moved)
            logger.error("合并卡片失败: %s -> %s, %s", source_id, target_id, e)
            return {"ok": False, "msg": f"合并失败: {e}"}

        self._remove_empty_screenshot_dir(source_id)
        logger.info("合并卡片完成: %s -> %s", source_id, target_id)
        return {
            "ok": True,
            "msg": f"已将「{source.title}」合并到「{target.title}」",
            "source_id": source_id,
            "target_id": target_id,
        }

    def _move_screenshots(self, source_id: str, target_id: str) -> List[Tuple[str, str]]:
        source_dir = get_game_screenshots_dir(source_id)
        target_dir = get_game_screenshots_dir(target_id)
        moved = []
        try:
            for name in os.listdir(source_dir):
                src = os.path.join(source_dir, name)
                if not os.path.isfile(src):
                    continue
                dest_name = name
                dest = os.path.join(target_dir, dest_name)
                if os.path.exists(dest):
                    stem, ext = os.path.splitext(name)
                    index = 1
                    while os.path.exists(dest):
                        dest_name = f"{stem}_merged_{index}{ext}"
                        dest = os.path.join(target_dir, dest_name)
                        index += 1
                shutil.move(src, dest)
                moved.append((dest, src))
        except Exception:
            self._rollback_screenshots(moved)
            raise
        return moved

    def _rollback_screenshots(self, moved: List[Tuple[str, str]]) -> None:
        for dest, src in reversed(moved):
            try:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                if os.path.exists(dest):
                    shutil.move(dest, src)
            except Exception as e:  # noqa: BLE001
                logger.error("回滚截图失败: %s -> %s, %s", dest, src, e)

    def _remove_empty_screenshot_dir(self, game_id: str) -> None:
        try:
            source_dir = get_game_screenshots_dir(game_id)
            if os.path.isdir(source_dir) and not os.listdir(source_dir):
                os.rmdir(source_dir)
        except Exception:
            pass

    @staticmethod
    def _merge_tags(conn, source_id: str, target_id: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO game_tags (game_id, tag_id) "
            "SELECT ?, tag_id FROM game_tags WHERE game_id = ?",
            (target_id, source_id))
        conn.execute("DELETE FROM game_tags WHERE game_id = ?", (source_id,))

    @staticmethod
    def _merge_collections(conn, source_id: str, target_id: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO game_collection_link "
            "(game_id, collection_id, sort_order, created_at) "
            "SELECT ?, collection_id, sort_order, created_at "
            "FROM game_collection_link WHERE game_id = ?",
            (target_id, source_id))
        conn.execute("DELETE FROM game_collection_link WHERE game_id = ?", (source_id,))

    @staticmethod
    def _merge_sources(conn, source_id: str, target_id: str) -> None:
        rows = conn.execute(
            "SELECT source, external_id, data, fetched_at "
            "FROM game_sources WHERE game_id = ?", (source_id,)).fetchall()
        for source, external_id, data, fetched_at in rows:
            conn.execute(
                """INSERT INTO game_sources
                       (game_id, source, external_id, data, fetched_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(game_id, source) DO UPDATE SET
                       external_id = COALESCE(game_sources.external_id, excluded.external_id),
                       data = COALESCE(game_sources.data, excluded.data),
                       fetched_at = CASE WHEN game_sources.fetched_at = ''
                                         THEN excluded.fetched_at
                                         ELSE game_sources.fetched_at END""",
                (target_id, source, external_id, data, fetched_at))
        conn.execute("DELETE FROM game_sources WHERE game_id = ?", (source_id,))

    def _update_target(self, conn, target: Game, source: Game) -> None:
        conn.execute(
            """UPDATE games SET
                   title = ?, engine = ?, description = ?, cover_path = ?,
                   logo_path = ?, launch_exe_path = ?, vndb_id = ?, bangumi_id = ?,
                   released = ?, developer = ?, length_minutes = ?, rating = ?,
                   is_favorite = ?, play_count = ?, play_time = ?, last_played = ?,
                   date_added = ?
               WHERE id = ?""",
            (
                self._first(target.title, source.title),
                self._first(target.engine, source.engine),
                self._first(target.description, source.description),
                self._first(target.cover_path, source.cover_path),
                self._first(target.logo_path, source.logo_path),
                self._first(target.launch_exe_path, source.launch_exe_path),
                self._first(target.vndb_id, source.vndb_id),
                self._first(target.bangumi_id, source.bangumi_id),
                self._first(target.released, source.released),
                self._first(target.developer, source.developer),
                int(target.length_minutes or source.length_minutes or 0),
                float(target.rating or source.rating or 0),
                1 if target.is_favorite or source.is_favorite else 0,
                int(target.play_count or 0) + int(source.play_count or 0),
                int(target.play_time or 0) + int(source.play_time or 0),
                self._max_text(target.last_played, source.last_played),
                self._min_text(target.date_added, source.date_added),
                target.id,
            ))

    @staticmethod
    def _delete_source(conn, source_id: str, target_id: str) -> None:
        conn.execute("DELETE FROM unmatched_games WHERE game_id IN (?, ?)",
                     (source_id, target_id))
        conn.execute("DELETE FROM game_tags WHERE game_id = ?", (source_id,))
        conn.execute("DELETE FROM game_collection_link WHERE game_id = ?", (source_id,))
        conn.execute("DELETE FROM game_sources WHERE game_id = ?", (source_id,))
        conn.execute("DELETE FROM games WHERE id = ?", (source_id,))
