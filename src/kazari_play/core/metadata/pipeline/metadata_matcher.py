"""元数据匹配编排：单游戏/批量、锚点、版本守卫、字段写回。

搜索、候选评分、合并和安全校验分别由 search/candidates/merge/guard 负责。
"""
import copy
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Tuple, Dict, Callable

from core.games.game_model import Game
from core.games.game_scanner import GameScanner
from core.metadata.search import multi_source
from core.metadata.contracts import ProgressCallback, SourceCallback
from core.metadata.validation.guard import _auto_match_guard
from core.metadata.merge.merge import _merge_candidates
from core.metadata.merge.writeback import apply_merged
from core.metadata.candidates.queries import (
    _build_queries,
    _edition_tokens,
    _soft_edition,
)
from core.metadata.candidates.candidates import (
    _candidate_titles,
    _external_id_conflict,
    _pick_group,
)
from core.metadata.search.search import (
    _prefetch_anchors,
    _resolve_anchor,
    _search_all,
)
from core.metadata.search.source_adapter import enrich_candidates
from utils.domain.title_utils import normalize_title
from utils.infra.config import Config
from utils.infra.win_version import read_version_info
from utils.infra.logger import get_logger

logger = get_logger()


def _is_meaningful_local(value: str) -> bool:
    low = value.casefold()
    if low in GameScanner.TITLE_GENERIC_EXACT:
        return False
    return not any(pattern in low for pattern in GameScanner.TITLE_ENGINE_PATTERNS)


def _local_titles(game: Game) -> List[str]:
    """运行时收集本地标题线索，不持久化。"""
    values = [game.title]
    if game.folder:
        values.append(os.path.basename(os.path.normpath(game.folder)))
    if game.exe_path:
        info = read_version_info(game.exe_path)
        for value in (os.path.splitext(os.path.basename(game.exe_path))[0],
                      info.get("FileDescription", ""),
                      info.get("ProductName", "")):
            if _is_meaningful_local(str(value or "")):
                values.append(value)
    out = []
    for value in values:
        value = str(value or "").strip()
        if value.casefold() in GameScanner.TITLE_GENERIC_EXACT:
            continue
        if value and value not in out:
            out.append(value)
        normalized = normalize_title(value)
        if normalized.casefold() in GameScanner.TITLE_GENERIC_EXACT:
            continue
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _queries_for_titles(titles: List[str]) -> List[str]:
    queries = []
    for title in titles:
        for query in _build_queries(title):
            if query not in queries:
                queries.append(query)
    return queries


def _sources_unavailable() -> bool:
    return any(not multi_source.source_available(source_id)
               for source_id in multi_source.get_mixed_sources())


def _candidate_hints(candidates: Optional[Dict[str, dict]],
                     limit: int = 8) -> List[dict]:
    """把搜索候选压缩成未匹配详情可展示/应用的字段。"""
    out = []
    for source_id, cand in (candidates or {}).items():
        if not isinstance(cand, dict) or not cand:
            continue
        out.append({
            "source": source_id,
            "source_name": multi_source.SOURCES.get(source_id, {}).get("name", source_id),
            "source_id": str(cand.get("source_id") or ""),
            "title": str(cand.get("title") or ""),
            "alt_title": str(cand.get("alt_title") or ""),
            "developer": str(cand.get("developer") or ""),
            "released": str(cand.get("released") or ""),
            "rating": cand.get("rating") or 0,
            "description": str(cand.get("description") or "")[:800],
            "length_minutes": cand.get("length_minutes") or 0,
            "cover_url": str(cand.get("cover_url") or ""),
            "vndb_id": str(cand.get("vndb_id") or ""),
            "bangumi_id": str(cand.get("bangumi_id") or ""),
            "all_titles": list(cand.get("all_titles") or []),
            "aliases": list(cand.get("aliases") or []),
        })
        if len(out) >= limit:
            break
    return out


def _set_unmatched(game: Game, code: str, reason: str,
                   candidates: Optional[Dict[str, dict]] = None) -> Tuple[str, str]:
    game.unmatched_code = code
    game.unmatched_candidates = _candidate_hints(candidates)
    return "unmatched", reason


def match_single(game: Game, force: bool = False, cancel_event=None, cover_cb=None,
                 source_cb: Optional[SourceCallback] = None,
                 anchor_group: Optional[Dict[str, dict]] = None,
                 search_cache: Optional[dict] = None) -> Tuple[str, str]:
    """为单个游戏匹配多源元数据并保守更新

    Args:
        game: 要匹配的游戏（会被原地修改）
        force: True 时即使已有匹配 ID 也重新匹配，并覆盖已有非空元数据字段
        cancel_event: threading.Event，置位时尽快终止
        cover_cb: 封面回调 (game_id, cover_url, dest)；提供时封面异步下载、
                  不阻塞匹配；为 None 时回退同步下载

    Returns:
        (status, message)
        status ∈ {"skip", "match", "unmatched", "retryable", "cancelled"}
        message 是人类可读的说明
    """
    if not game:
        return "unmatched", "游戏对象为空"
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled", "已取消"

    ids = " / ".join(x for x in (game.vndb_id, game.bangumi_id) if x)
    if ids and not force:
        return "skip", f"已匹配过（{ids}）"

    titles = _local_titles(game)
    queries = _queries_for_titles(titles)
    if not queries:
        return _set_unmatched(game, "no_candidate", "标题为空，无法搜索")

    logger.info("元数据匹配开始: game_id=%s, title='%s', queries=%s",
                game.id, game.title, queries)

    tokens = _edition_tokens(" / ".join(titles))
    if anchor_group is None:
        group = _resolve_anchor(queries, cancel_event,
                                edition_tokens=tokens, cache=search_cache)
    else:
        group = anchor_group
    enriched = bool(group)
    candidates: Dict[str, dict] = {}
    if not group:
        candidates = _search_all(queries, cancel_event,
                                 edition_tokens=tokens, cache=search_cache)
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled", "已取消"
        group, reason = _pick_group(candidates, queries, tokens)

    if not group:
        logger.info("元数据未匹配: %s (%s)", game.title, reason)
        if _sources_unavailable():
            return "retryable", reason
        code = "no_candidate" if not candidates else "ambiguous"
        return _set_unmatched(game, code, reason, candidates)

    guard_reason = _auto_match_guard(game, group)
    if guard_reason:
        logger.info("元数据未匹配: %s (%s)", game.title, guard_reason)
        return _set_unmatched(game, "conflict", guard_reason, group)

    if not enriched:
        enrich_candidates(group)

    conflict = _external_id_conflict(group)
    if conflict:
        logger.info("元数据未匹配: %s (%s)", game.title, conflict)
        return _set_unmatched(game, "conflict", conflict, group)

    # 版本标记守卫：候选缺少 FHD/HD/Remake 等标记时，进入未匹配等待手动确认
    edition_release = next(
        (c.get("edition_release") for c in group.values()
         if isinstance(c.get("edition_release"), dict)), None)
    soft_edition = _soft_edition(tokens)
    if tokens and not edition_release and not soft_edition:
        cand_titles = " ".join(
            t for c in group.values() for t in _candidate_titles(c)).lower()
        missing_tokens = [t for t in tokens if t not in cand_titles]
        if missing_tokens:
            reason = f"候选缺少版本标记（{', '.join(missing_tokens)}），请手动确认"
            logger.info("元数据未匹配: %s (%s)", game.title, reason)
            return _set_unmatched(game, "conflict", reason, group)

    if source_cb is not None:
        try:
            source_cb(game.id, group)
        except Exception as e:  # noqa: BLE001
            logger.warning("保存元数据来源失败: %s, %s", game.id, e)

    merged = _merge_candidates(group)
    if edition_release or soft_edition:
        merged["title"] = game.title
        if edition_release and edition_release.get("released"):
            merged["released"] = edition_release["released"]
    sources = "+".join(multi_source.SOURCES.get(s, {}).get("name", s)
                       for s in group)
    updated_fields, cover_queued = apply_merged(
        game, merged, force, cover_cb, cancel_event)

    if not updated_fields and not cover_queued:
        return "skip", "所有字段已存在，未更新"

    msg = f"已更新 {len(updated_fields)} 项（{sources}）"
    logger.info("元数据匹配成功: %s -> %s / %s, %s",
                game.title, merged["vndb_id"], merged["bangumi_id"], msg)
    return "match", msg


def _match_workers(total: int) -> int:
    try:
        workers = int(Config().get("metadata_sources.match_concurrency", 4) or 4)
    except Exception:  # noqa: BLE001
        workers = 4
    return max(1, min(workers, 8, total))


def match_batch(
    games: List[Game],
    force: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event=None,
    cover_cb=None,
    source_cb: Optional[SourceCallback] = None,
    result_cb: Optional[Callable[[Game, str, str], None]] = None,
) -> Tuple[int, int, int, int]:
    """批量匹配多源元数据，返回 (matched, skipped, unmatched, retryable)。"""
    matched = skipped = unmatched = retryable = 0
    games = sorted(
        games, key=lambda g: (g.date_added or "9999-12-31T23:59:59", g.id))
    total = len(games)
    if not games:
        return 0, 0, 0, 0

    search_cache = {}
    anchor_groups, anchor_enabled = _prefetch_anchors(
        games, force, cancel_event, progress_cb, cache=search_cache)
    originals = {game.id: copy.deepcopy(game) for game in games}
    pending_sources: Dict[str, dict] = {}
    pending_covers: Dict[str, List[Tuple[str, str]]] = {}

    def capture_source(game_id: str, group: dict) -> None:
        pending_sources[game_id] = group

    def capture_cover(game_id: str, cover_url: str, dest: str) -> None:
        pending_covers.setdefault(game_id, []).append((cover_url, dest))

    def run(game: Game) -> Tuple[str, str]:
        return match_single(
            game, force=force, cancel_event=cancel_event,
            cover_cb=capture_cover if cover_cb is not None else None,
            source_cb=capture_source if source_cb is not None else None,
            anchor_group=anchor_groups.get(game.id, {}) if anchor_enabled else None,
            search_cache=search_cache)

    results: Dict[int, Tuple[str, str]] = {}
    futures = {}
    workers = _match_workers(total)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="match") as ex:
        for i, game in enumerate(games):
            if cancel_event is not None and cancel_event.is_set():
                logger.info("元数据批量匹配已取消（已处理 %d/%d）", i, total)
                break
            if progress_cb:
                try:
                    progress_cb(game.id, game.title, "start",
                                f"[{i + 1}/{total}] 匹配中: {game.title}")
                except Exception:
                    pass
            futures[ex.submit(run, game)] = (i, game)
        for fut in as_completed(futures):
            i, game = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("元数据匹配异常: %s, %s", game.title, e)
                original = originals[game.id]
                game.__dict__.clear()
                game.__dict__.update(original.__dict__)
                results[i] = ("retryable", f"匹配异常: {e}")

    claimed: Dict[Tuple[str, str], str] = {}

    def _ids(game: Game) -> List[Tuple[str, str]]:
        out = []
        if game.vndb_id:
            out.append(("vndb", str(game.vndb_id)))
        if game.bangumi_id:
            out.append(("bangumi", str(game.bangumi_id)))
        return out

    def _duplicate(game: Game) -> bool:
        return any(claimed.get(key) not in (None, game.id)
                   for key in _ids(game))

    def _persist_pending(game: Game) -> None:
        if source_cb is not None and game.id in pending_sources:
            try:
                source_cb(game.id, pending_sources[game.id])
            except Exception as e:  # noqa: BLE001
                logger.warning("保存元数据来源失败: %s, %s", game.id, e)
        if cover_cb is not None:
            for cover_url, dest in pending_covers.get(game.id, []):
                try:
                    cover_cb(game.id, cover_url, dest)
                except Exception as e:  # noqa: BLE001
                    logger.warning("提交封面下载失败: %s, %s", game.id, e)

    for i, game in enumerate(games):
        if i not in results:
            continue
        status, msg = results[i]
        if status in ("match", "skip"):
            if _duplicate(game):
                original = originals[game.id]
                game.__dict__.clear()
                game.__dict__.update(original.__dict__)
                game.unmatched_code = "duplicate_version"
                game.unmatched_candidates = _candidate_hints(
                    pending_sources.get(game.id, {}))
                status, msg = "unmatched", "同版本重复卡片，按最早入库保留另一张"
            else:
                for key in _ids(game):
                    claimed.setdefault(key, game.id)
                _persist_pending(game)

        if status != "cancelled":
            for key in _ids(originals[game.id]):
                claimed.setdefault(key, game.id)

        if progress_cb:
            try:
                progress_cb(game.id, game.title, status, msg)
            except Exception:
                pass
        if result_cb:
            try:
                result_cb(game, status, msg)
            except Exception as e:  # noqa: BLE001
                logger.warning("保存匹配结果失败: %s, %s", game.id, e)

        if status == "cancelled":
            logger.info("元数据批量匹配在取消处停止")
            break
        if status == "match":
            matched += 1
        elif status == "skip":
            skipped += 1
        elif status == "retryable":
            retryable += 1
        else:
            unmatched += 1

    logger.info("元数据批量匹配完成: 共 %d, 成功 %d, 跳过 %d, 未匹配 %d, 待重试 %d",
                total, matched, skipped, unmatched, retryable)
    return matched, skipped, unmatched, retryable
