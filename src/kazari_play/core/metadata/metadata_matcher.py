"""元数据匹配编排：单游戏/批量、锚点、版本守卫、字段写回。

搜索、候选评分、合并和安全校验分别由 search/candidates/merge/guard 负责。
"""
from typing import Optional, List, Tuple, Dict

from core.games.game_model import Game
from core.metadata import multi_source
from core.metadata.contracts import ProgressCallback, SourceCallback
from core.metadata.guard import _auto_match_guard
from core.metadata.merge import _merge_candidates
from core.metadata.writeback import apply_merged
from core.metadata.queries import (
    _build_queries,
    _edition_tokens,
    _soft_edition,
    _year_hint,
)
from core.metadata.candidates import (
    _candidate_titles,
    _pick_group,
    _release_year,
)
from core.metadata.search import (
    _prefetch_anchors,
    _resolve_anchor,
    _search_all,
)
from core.metadata.source_adapter import enrich_candidates
from utils.infra.logger import get_logger

# 兼容旧测试/调用方的私有导出；业务代码请直接引用对应模块。
from core.metadata.title_policy import (  # noqa: F401
    exact_title_match, part_score, trailing_part,
)
from core.metadata.queries import (  # noqa: F401
    _extract_japanese, _match_key, _series_key, _split_camel, _strip_edition,
)
from core.metadata.candidates import (  # noqa: F401
    _pick_result, _query_sim, _similarity, _title_affinity, _title_sim,
    _year_compatible,
)

logger = get_logger()


def match_single(game: Game, force: bool = False, cancel_event=None, cover_cb=None,
                 source_cb: Optional[SourceCallback] = None,
                 anchor_group: Optional[Dict[str, dict]] = None) -> Tuple[str, str]:
    """为单个游戏匹配多源元数据并保守更新

    Args:
        game: 要匹配的游戏（会被原地修改）
        force: True 时即使已有匹配 ID 也重新匹配，并覆盖已有非空元数据字段
        cancel_event: threading.Event，置位时尽快终止
        cover_cb: 封面回调 (game_id, cover_url, dest)；提供时封面异步下载、
                  不阻塞匹配；为 None 时回退同步下载

    Returns:
        (status, message)
        status ∈ {"skip", "match", "fail", "cancelled"}
        message 是人类可读的说明
    """
    if not game:
        return "fail", "游戏对象为空"
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled", "已取消"

    ids = " / ".join(x for x in (game.vndb_id, game.bangumi_id) if x)
    if ids and not force:
        return "skip", f"已匹配过（{ids}）"

    queries = _build_queries(game.title)
    if not queries:
        return "fail", "标题为空，无法搜索"

    logger.info("元数据匹配开始: game_id=%s, title='%s', queries=%s",
                game.id, game.title, queries)

    tokens = _edition_tokens(game.title)
    year_hint = _year_hint(game)
    if anchor_group is None:
        group = _resolve_anchor(queries, cancel_event, year_hint=year_hint,
                                edition_tokens=tokens)
    else:
        group = anchor_group
    enriched = bool(group)
    if not group:
        candidates = _search_all(queries, cancel_event, year_hint=year_hint,
                                 edition_tokens=tokens)
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled", "已取消"
        group, reason = _pick_group(candidates, queries, tokens)

    if not group:
        logger.info("元数据未匹配: %s (%s)", game.title, reason)
        return "fail", reason

    guard_reason = _auto_match_guard(game, group)
    if guard_reason:
        logger.info("元数据未匹配: %s (%s)", game.title, guard_reason)
        return "fail", guard_reason

    if not enriched:
        enrich_candidates(group)

    # 版本标记守卫：候选缺少 FHD/HD/Remake 等标记时，只有年份线索一致才按重制版采用
    edition_release = next(
        (c.get("edition_release") for c in group.values()
         if isinstance(c.get("edition_release"), dict)), None)
    soft_edition = _soft_edition(tokens)
    if tokens and not edition_release and not soft_edition:
        cand_titles = " ".join(
            t for c in group.values() for t in _candidate_titles(c)).lower()
        missing_tokens = [t for t in tokens if t not in cand_titles]
        if missing_tokens:
            group_years = {_release_year(c) for c in group.values()} - {""}
            if not (year_hint and group_years == {year_hint}):
                reason = f"候选缺少版本标记（{', '.join(missing_tokens)}），请手动确认"
                logger.info("元数据未匹配: %s (%s)", game.title, reason)
                return "fail", reason

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


def match_batch(
    games: List[Game],
    force: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event=None,
    cover_cb=None,
    source_cb: Optional[SourceCallback] = None,
) -> Tuple[int, int, int]:
    """批量匹配多源元数据

    Args:
        games: 要匹配的游戏列表
        force: True 时强制重新匹配已有匹配 ID 的游戏
        progress_cb: 进度回调（每个游戏调用一次）
        cancel_event: threading.Event，置位时提前结束（可选）
        cover_cb: 封面回调 (game_id, cover_url, dest)，转交 match_single 异步下载

    Returns:
        (matched, skipped, failed) 三元组
    """
    matched = skipped = failed = 0
    total = len(games)
    anchor_groups, anchor_enabled = _prefetch_anchors(
        games, force, cancel_event, progress_cb)

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

        status, msg = match_single(
            game, force=force, cancel_event=cancel_event, cover_cb=cover_cb,
            source_cb=source_cb,
            anchor_group=anchor_groups.get(game.id, {}) if anchor_enabled else None)

        if progress_cb:
            try:
                progress_cb(game.id, game.title, status, msg)
            except Exception:
                pass

        if status == "cancelled":
            logger.info("元数据批量匹配在取消处停止")
            break
        if status == "match":
            matched += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1

    logger.info("元数据批量匹配完成: 共 %d, 成功 %d, 跳过 %d, 失败 %d",
                total, matched, skipped, failed)
    return matched, skipped, failed
