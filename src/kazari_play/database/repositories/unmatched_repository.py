"""未匹配区仓储：只保存需要人工判断的游戏，不保存网络错误。"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.db_manager import DatabaseManager


class UnmatchedRepository:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()

    @staticmethod
    def _json_text(value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        return json.dumps(value, ensure_ascii=False)

    def upsert(self, game_id: str, reason: str,
               candidates: Any = None, code: str = "") -> bool:
        if not game_id:
            return False
        return self.db.execute(
            """INSERT INTO unmatched_games
                   (game_id, code, reason, candidates_json, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(game_id) DO UPDATE SET
                   code = excluded.code,
                   reason = excluded.reason,
                   candidates_json = excluded.candidates_json,
                   updated_at = excluded.updated_at""",
            (game_id, str(code or ""), str(reason or "unmatched"),
             self._json_text(candidates), datetime.now().isoformat()))

    def get(self, game_id: str) -> Optional[dict]:
        if not game_id:
            return None
        rows = self.db.query(
            "SELECT game_id, code, reason, candidates_json, updated_at "
            "FROM unmatched_games WHERE game_id = ?", (game_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, game_id: str) -> bool:
        return self.db.execute("DELETE FROM unmatched_games WHERE game_id = ?",
                               (game_id,))

    _CHUNK = 500

    def delete_many(self, game_ids: List[str]) -> bool:
        if not game_ids:
            return False
        for i in range(0, len(game_ids), self._CHUNK):
            chunk = game_ids[i:i + self._CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            if not self.db.execute(
                    f"DELETE FROM unmatched_games WHERE game_id IN ({placeholders})",
                    tuple(chunk)):
                return False
        return True

    def list_for_games(self, game_ids: List[str]) -> Dict[str, dict]:
        if not game_ids:
            return {}
        out = {}
        for i in range(0, len(game_ids), self._CHUNK):
            chunk = game_ids[i:i + self._CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.db.query(
                f"""SELECT game_id, code, reason, candidates_json, updated_at
                    FROM unmatched_games WHERE game_id IN ({placeholders})""",
                tuple(chunk))
            for row in (rows or []):
                out[row["game_id"]] = self._row(row)
        return out

    def list_all(self) -> List[dict]:
        rows = self.db.query(
            "SELECT game_id, code, reason, candidates_json, updated_at "
            "FROM unmatched_games ORDER BY updated_at DESC")
        return [self._row(row) for row in (rows or [])]

    def _row(self, row) -> dict:
        candidates = None
        try:
            candidates = json.loads(row["candidates_json"]) if row["candidates_json"] else None
        except (TypeError, ValueError):
            candidates = None
        return {
            "game_id": row["game_id"],
            "code": row["code"] or "",
            "reason": row["reason"],
            "candidates": candidates,
            "updated_at": row["updated_at"],
        }
