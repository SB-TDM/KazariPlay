"""通用元数据来源记录仓库。"""
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from database.db_manager import DatabaseManager
from utils.infra.logger import get_logger

logger = get_logger()


class GameSourceRepository:
    """持久化 game_sources；data 为来源原始 JSON，ID-only 记录 data=None。"""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()

    @staticmethod
    def _json_text(data: Any) -> Optional[str]:
        if data is None:
            return None
        if isinstance(data, str):
            return data
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _json_value(data: Optional[str]) -> Any:
        if data is None or data == "":
            return None
        try:
            return json.loads(data)
        except (TypeError, ValueError):
            return None

    def upsert(self, game_id: str, source: str, external_id: Optional[str],
               data: Any = None) -> bool:
        return self.upsert_many(game_id, [{
            "source": source, "external_id": external_id, "data": data,
        }])

    def upsert_many(self, game_id: str, records: Iterable[dict],
                    remove_missing: bool = False) -> bool:
        rows = []
        for record in records:
            source = str(record.get("source") or "").strip()
            external_id = record.get("external_id")
            external_id = str(external_id).strip() if external_id is not None else None
            data_text = self._json_text(record.get("data"))
            if not source or (not external_id and data_text is None):
                continue
            rows.append((game_id, source, external_id, data_text,
                         datetime.now().isoformat()))
        if not rows:
            return False
        keep = {row[1] for row in rows}
        try:
            with self.db.transaction() as conn:
                if remove_missing:
                    placeholders = ",".join("?" for _ in keep)
                    conn.execute(
                        f"DELETE FROM game_sources WHERE game_id = ? AND source NOT IN ({placeholders})",
                        (game_id, *sorted(keep)))
                for row in rows:
                    conn.execute(
                        """INSERT INTO game_sources(game_id, source, external_id, data, fetched_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(game_id, source) DO UPDATE SET
                               external_id = COALESCE(excluded.external_id, game_sources.external_id),
                               data = COALESCE(excluded.data, game_sources.data),
                               fetched_at = excluded.fetched_at""",
                        row)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("写入来源记录失败: game=%s, %s", game_id, e)
            return False

    def get(self, game_id: str, source: str) -> Optional[dict]:
        rows = self.db.query(
            "SELECT game_id, source, external_id, data, fetched_at "
            "FROM game_sources WHERE game_id = ? AND source = ?",
            (game_id, source))
        return self._row(rows[0]) if rows else None

    def list_for_game(self, game_id: str) -> List[dict]:
        rows = self.db.query(
            "SELECT game_id, source, external_id, data, fetched_at "
            "FROM game_sources WHERE game_id = ? ORDER BY source",
            (game_id,))
        return [self._row(row) for row in (rows or [])]

    def get_id_map(self, game_id: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for record in self.list_for_game(game_id):
            if record["external_id"]:
                result[record["source"]] = record["external_id"]
        return result

    def _row(self, row) -> dict:
        return {
            "game_id": row["game_id"],
            "source": row["source"],
            "external_id": row["external_id"],
            "data": self._json_value(row["data"]),
            "fetched_at": row["fetched_at"],
        }
