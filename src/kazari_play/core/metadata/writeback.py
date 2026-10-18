"""把合并后的元数据写回 Game，并处理封面下载/回调。"""
import os
from typing import List, Tuple

from core.games.game_model import Game
from core.metadata.merge import _lang_rank
from utils.infra.logger import get_logger
from utils.infra.path_utils import get_app_data_dir

logger = get_logger()


def cover_dest_path(game_id: str, cover_url: str) -> str:
    ext = ".jpg"
    if cover_url:
        url_lower = cover_url.lower().split("?")[0]
        if url_lower.endswith(".png"):
            ext = ".png"
        elif url_lower.endswith(".webp"):
            ext = ".webp"
    return os.path.join(get_app_data_dir(), "covers", f"{game_id}_vndb{ext}")


def apply_merged(game: Game, merged: dict, force: bool, cover_cb=None,
                 cancel_event=None) -> Tuple[List[str], bool]:
    """写入字段，返回 (更新字段列表, 是否已排队异步封面)。"""
    overwrite = bool(force)
    updated: List[str] = []

    if merged["vndb_id"] and game.vndb_id != merged["vndb_id"]:
        game.vndb_id = merged["vndb_id"]
        updated.append("vndb_id")
    if merged["bangumi_id"] and game.bangumi_id != merged["bangumi_id"]:
        game.bangumi_id = merged["bangumi_id"]
        updated.append("bangumi_id")

    if merged["title"] and game.title != merged["title"]:
        game.title = merged["title"]
        updated.append("title")

    if merged["description"]:
        old_rank = _lang_rank(game.description) if game.description else 99
        if (overwrite or _lang_rank(merged["description"]) <= old_rank) \
                and game.description != merged["description"]:
            game.description = merged["description"]
            updated.append("description")

    if merged["rating"] and not game.rating:
        game.rating = merged["rating"]
        updated.append("rating")

    if merged["released"] and (overwrite or not game.released):
        game.released = merged["released"]
        updated.append("released")

    if merged["developer"] and (overwrite or not game.developer):
        game.developer = merged["developer"]
        updated.append("developer")

    if merged["length_minutes"] and (overwrite or not game.length_minutes):
        game.length_minutes = merged["length_minutes"]
        updated.append("length_minutes")

    cover_queued = False
    if not game.cover_path or not os.path.exists(game.cover_path):
        if merged["cover_url"]:
            dest = cover_dest_path(game.id, merged["cover_url"])
            if cover_cb is not None:
                cover_cb(game.id, merged["cover_url"], dest)
                cover_queued = True
            else:
                from core.media.cover_store import CoverStore
                path = CoverStore().download(game.id, merged["cover_url"],
                                             cancel_event=cancel_event)
                if path:
                    game.cover_path = path
                    updated.append("cover_path")
                else:
                    logger.warning("封面下载失败，跳过: %s", merged["cover_url"])

    return updated, cover_queued
