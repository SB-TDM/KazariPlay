"""单源/多源搜索与 Kungal 锚点解析。"""
import concurrent.futures
import copy
import time
from typing import Dict, List, Optional, Tuple

from core.games.game_model import Game
from core.metadata.search import multi_source
from core.metadata.candidates.candidates import (
    _candidate_titles, _pick_result, _query_sim,
)
from core.metadata.candidates.constants import (
    _SEARCH_DEADLINE, _SINGLE_QUERY_RATIO, _SLOW_SOURCE_SECONDS,
)
from core.metadata.candidates.queries import (
    _build_queries, _edition_tokens, _match_key, _strip_edition,
)
from core.metadata.search.source_adapter import enrich_candidates, get_adapter
from core.metadata.candidates.title_policy import (
    part_score, release_language_hints, trailing_part,
)
from utils.clients import vndb_client
from utils.infra.config import Config
from utils.infra.logger import get_logger

logger = get_logger()

def _search_source(source_id: str, queries: List[str], cancel_event=None,
                   trust_rank: bool = False,
                   edition_tokens: Optional[List[str]] = None,
                   cache: Optional[dict] = None,
                   reject_ambiguous: bool = False) -> Optional[dict]:
    """在单个源上按关键词策略搜索，返回最合适的候选

    - edition_tokens：目录带 FHD/HD/Remake 等标记时，优先带标记的候选
    - trust_rank=True 时直接取搜索排名第一条（用于跨语言桥接）
    """
    meta = multi_source.SOURCES.get(source_id) or {}
    client = meta.get("client")
    if client is None or not multi_source.source_available(source_id):
        return None
    fallback: Optional[dict] = None

    def part_ok(cand: dict) -> bool:
        local_part = trailing_part(queries[0] if queries else "")
        return part_score(local_part,
                          trailing_part(cand.get("title") or "")) >= 0

    for q in queries:
        if cancel_event is not None and cancel_event.is_set():
            return None
        if not multi_source.source_available(source_id):
            return None
        cache_key = (source_id, q.casefold())
        if cache is not None and cache_key in cache:
            results = copy.deepcopy(cache[cache_key])
        else:
            try:
                started = time.monotonic()
                results = client.search(q, count=5)
                elapsed = time.monotonic() - started
                if elapsed >= _SLOW_SOURCE_SECONDS:
                    multi_source.mark_source_failure(source_id)
                else:
                    multi_source.mark_source_success(source_id)
            except Exception as e:  # noqa: BLE001
                multi_source.mark_source_failure(source_id)
                logger.warning("元数据源 %s 搜索失败: q='%s', %s", source_id, q, e)
                continue
            if cache is not None:
                cache[cache_key] = copy.deepcopy(results)
        if not results:
            continue
        if reject_ambiguous:
            qkeys = {_match_key(q) for q in queries if _match_key(q)}
            exact = [r for r in results
                     if any(_match_key(t) in qkeys
                            for t in _candidate_titles(r))]
            if len(exact) > 1:
                logger.info("源 %s 同名候选过多，跳过自动锚点: q='%s', n=%d",
                            source_id, q, len(exact))
                return None

        pool = results

        if edition_tokens and not trust_rank:
            hits = [r for r in pool
                    if all(t in " ".join(_candidate_titles(r)).lower()
                           for t in edition_tokens)]
            if hits:
                cand = _pick_result(hits, queries, edition_tokens, trust_rank)
                if part_ok(cand):
                    return cand
            best = _pick_result(pool, queries, edition_tokens, trust_rank)
            if part_ok(best) and (fallback is None or
                                  _query_sim(best, queries) > _query_sim(fallback, queries)):
                fallback = best
            continue

        cand = _pick_result(pool, queries, edition_tokens, trust_rank)
        if part_ok(cand):
            return cand
    return fallback


def _search_all(queries: List[str], cancel_event=None,
                edition_tokens: Optional[List[str]] = None,
                cache: Optional[dict] = None) -> Dict[str, dict]:
    """并行查询各源，返回 {source_id: 候选}；失败的源忽略"""
    sources = [s for s in multi_source.get_mixed_sources()
               if (multi_source.SOURCES.get(s) or {}).get("client") is not None
               and multi_source.source_available(s)]
    if not sources:
        return {}
    candidates: Dict[str, dict] = {}
    if len(sources) == 1:
        cand = _search_source(sources[0], queries, cancel_event, False,
                              edition_tokens, cache)
        return {sources[0]: cand} if cand else {}
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(sources))
    futs = {ex.submit(_search_source, sid, queries, cancel_event, False,
                      edition_tokens, cache): sid for sid in sources}
    try:
        for fut in concurrent.futures.as_completed(futs, timeout=_SEARCH_DEADLINE):
            sid = futs[fut]
            try:
                cand = fut.result()
            except Exception as e:  # noqa: BLE001
                multi_source.mark_source_failure(sid)
                logger.warning("元数据源 %s 搜索异常: %s", sid, e)
                continue
            if cand:
                candidates[sid] = cand
    except concurrent.futures.TimeoutError:
        for fut, sid in futs.items():
            if not fut.done():
                multi_source.mark_source_failure(sid)
        logger.warning("多源匹配超时(%.0fs)，使用已完成结果", _SEARCH_DEADLINE)
    finally:
        ex.shutdown(wait=False)

    # 跨语言桥接：某源无结果时，用已命中源（优先 VNDB/Bangumi）的标题再查一次，
    # 解决“罗马音/日文标题在 Bangumi 搜不到”的漏配
    missing = [s for s in sources if s not in candidates]
    if candidates and missing:
        bridge: List[str] = []
        for sid in ("vndb", "bangumi"):
            cand = candidates.get(sid)
            if cand:
                for t in _candidate_titles(cand):
                    if t not in bridge:
                        bridge.append(t)
        if not bridge:
            for cand in candidates.values():
                for t in _candidate_titles(cand):
                    if t not in bridge:
                        bridge.append(t)
        for sid in missing:
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                cand = _search_source(sid, bridge[:2], cancel_event, True,
                                      edition_tokens, cache)
            except Exception as e:  # noqa: BLE001
                logger.warning("元数据源 %s 桥接搜索失败: %s", sid, e)
                continue
            if cand:
                candidates[sid] = cand

    # 版本标记补搜：目录带 HD/FHD/Reflection Blue 等标记但当前候选都没有时，
    # 用已命中源的标题再查（例如 VNDB 只有原版、Bangumi 才有 HD 条目）
    if edition_tokens and candidates:
        has_token = any(
            all(t in " ".join(_candidate_titles(c)).lower() for t in edition_tokens)
            for c in candidates.values())
        if not has_token:
            titles: List[str] = []
            for sid in ("vndb", "bangumi"):
                cand = candidates.get(sid)
                if cand:
                    for t in _candidate_titles(cand):
                        if t not in titles:
                            titles.append(t)
            if not titles:
                for cand in candidates.values():
                    for t in _candidate_titles(cand):
                        if t not in titles:
                            titles.append(t)
            for sid in list(candidates):
                if cancel_event is not None and cancel_event.is_set():
                    break
                try:
                    cand = _search_source(sid, titles[:2], cancel_event, False,
                                          edition_tokens, cache)
                except Exception as e:  # noqa: BLE001
                    logger.warning("元数据源 %s 版本标记补搜失败: %s", sid, e)
                    continue
                if cand:
                    cand_titles = " ".join(_candidate_titles(cand)).lower()
                    if all(t in cand_titles for t in edition_tokens):
                        candidates[sid] = cand
    return candidates


def _resolve_kungal_anchor(queries: List[str], cancel_event=None,
                           edition_tokens: Optional[List[str]] = None,
                           cache: Optional[dict] = None) -> Dict[str, dict]:
    """只解析 Kungal 锚点及详情，不拉取 VNDB（批量阶段用）。"""
    if "kungal" not in multi_source.get_mixed_sources():
        return {}
    if not multi_source.source_available("kungal"):
        return {}
    cand = _search_source("kungal", queries, cancel_event, False,
                          edition_tokens, cache, reject_ambiguous=True)
    if not cand:
        return {}
    sim = _query_sim(cand, queries)
    if sim < _SINGLE_QUERY_RATIO:
        logger.info("Kungal 锚点标题相似度不足: %.2f, candidate=%s",
                    sim, cand.get("title"))
        return {}

    adapter = get_adapter("kungal")
    if adapter and adapter.detail:
        try:
            detail = adapter.detail(str(cand.get("source_id") or ""))
            if isinstance(detail, dict):
                for key, value in detail.items():
                    if value not in (None, "", [], {}):
                        cand[key] = value
        except Exception as e:  # noqa: BLE001
            logger.warning("Kungal 锚点详情失败: %s", e)

    if edition_tokens:
        titles = " ".join(_candidate_titles(cand)).lower()
        if not all(t in titles for t in edition_tokens):
            release = vndb_client.find_release(
                _strip_edition(queries[0]) if queries else "",
                edition_tokens,
                release_language_hints(queries[0] if queries else ""),
                cancel_event)
            if release:
                cand["edition_release"] = release
                if release.get("vndb_id"):
                    cand["vndb_id"] = release["vndb_id"]
                logger.info("VNDB 版本命中: %s -> %s (%s)",
                            release.get("release_title"),
                            release.get("vndb_id"),
                            release.get("released"))

    logger.info("Kungal 锚点采用: %s (sim=%.2f)", cand.get("title"), sim)
    return {"kungal": cand}


def _resolve_anchor(queries: List[str], cancel_event=None,
                    edition_tokens: Optional[List[str]] = None,
                    cache: Optional[dict] = None) -> Dict[str, dict]:
    """Kungal 锚点 + vndb_id 直接补 VNDB 详情（单游戏路径）。"""
    group = _resolve_kungal_anchor(queries, cancel_event,
                                   edition_tokens, cache)
    if not group:
        return {}
    cand = group["kungal"]
    vndb_id = str(cand.get("vndb_id") or "").strip()
    if vndb_id:
        vndb = vndb_client.detail(vndb_id, cancel_event=cancel_event)
        if vndb:
            group["vndb"] = vndb
            logger.info("Kungal 锚点命中: %s -> %s", cand.get("title"), vndb_id)
        else:
            logger.warning("Kungal 锚点指向的 VNDB 条目不可用: %s", vndb_id)
    return group


def _prefetch_anchors(games: List[Game], force: bool,
                      cancel_event=None, progress_cb=None,
                      cache: Optional[dict] = None) -> Tuple[Dict[str, Dict[str, dict]], bool]:
    """并发预取 Kungal 锚点，再一次性批量拉 VNDB 详情。"""
    sources = multi_source.get_mixed_sources()
    if "kungal" not in sources or not multi_source.source_available("kungal"):
        return {}, False

    pending = [g for g in games
               if force or not (g.vndb_id or g.bangumi_id)]
    if not pending:
        return {}, True

    try:
        from utils.infra.config import Config
        workers = int(Config().get("metadata_sources.kungal_concurrency", 4) or 4)
    except Exception:
        workers = 4
    workers = max(1, min(workers, 8))

    groups: Dict[str, Dict[str, dict]] = {}
    vndb_ids: List[str] = []
    ex = concurrent.futures.ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="kungal-anchor")
    futures = {
        ex.submit(_resolve_kungal_anchor, _build_queries(game.title),
                  cancel_event, _edition_tokens(game.title), cache): game
        for game in pending
    }
    completed = 0
    try:
        for fut in concurrent.futures.as_completed(futures):
            game = futures[fut]
            if cancel_event is not None and cancel_event.is_set():
                break
            completed += 1
            try:
                group = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("Kungal 锚点异常: %s, %s", game.title, e)
                continue
            if group:
                groups[game.id] = group
                vndb_id = str((group.get("kungal") or {}).get("vndb_id") or "").strip()
                if vndb_id:
                    vndb_ids.append(vndb_id)
            if progress_cb and completed % 5 == 0:
                try:
                    progress_cb(game.id, game.title, "anchor",
                                f"Kungal 锚点 {completed}/{len(pending)}")
                except Exception:
                    pass
    finally:
        cancelled = cancel_event is not None and cancel_event.is_set()
        ex.shutdown(wait=not cancelled, cancel_futures=True)

    if vndb_ids and not (cancel_event is not None and cancel_event.is_set()):
        details = vndb_client.details(vndb_ids, cancel_event=cancel_event)
        for group in groups.values():
            vndb_id = str((group.get("kungal") or {}).get("vndb_id") or "").lower()
            candidate = details.get(vndb_id)
            if candidate:
                group["vndb"] = candidate

    logger.info("Kungal 锚点预取完成: %d/%d, VNDB 批量详情 %d 条, 并发 %d",
                len(groups), len(games), len(vndb_ids), workers)
    return groups, True

