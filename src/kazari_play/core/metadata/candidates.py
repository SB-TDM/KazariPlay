"""候选标题比较、评分与分组。"""
import difflib
import re
from typing import Dict, List, Optional, Tuple

from utils.domain.title_utils import normalize_title
from core.metadata.constants import (
    _CONSENSUS_RATIO,
    _PICK_BY_TITLE_RATIO,
    _SINGLE_QUERY_RATIO,
)
from core.metadata.queries import _match_key, _release_year, _series_key, _soft_edition
from core.metadata.title_policy import (
    extra_subtitle_hits,
    part_score,
    subtitle_tokens,
    trailing_part,
)

def _title_affinity(a: dict, b: dict, queries: List[str]) -> float:
    """跨源标题亲和度：整标题相似度，或同系列 + 同年份。"""
    sim = _title_sim(a, b)
    if sim >= _CONSENSUS_RATIO:
        return sim
    ka, kb = _series_key(" / ".join(_candidate_titles(a))), _series_key(" / ".join(_candidate_titles(b)))
    da = (a.get("released") or "").strip()
    db = (b.get("released") or "").strip()
    if ka and ka == kb and len(ka) >= 3 and da and db and da == db:
        return 1.0
    return sim


def _similarity(a: str, b: str) -> float:
    """归一化标题相似度（0~1）"""
    ka, kb = _match_key(a), _match_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def _candidate_titles(cand: dict) -> List[str]:
    """候选的全部标题（title / alt_title / all_titles / aliases）"""
    out = []
    for key in ("title", "alt_title"):
        t = (cand.get(key) or "").strip()
        if t and t not in out:
            out.append(t)
    for key in ("all_titles", "aliases"):
        for value in cand.get(key) or []:
            t = str(value or "").strip()
            if t and t not in out:
                out.append(t)
    return out


def _query_sim(cand: dict, queries: List[str]) -> float:
    """候选与查询关键词的最大相似度"""
    return max((_similarity(q, t) for q in queries
                for t in _candidate_titles(cand)), default=0.0)


def _title_sim(a: dict, b: dict) -> float:
    """两个候选之间的最大标题相似度（跨源一致性校验用）"""
    return max((_similarity(ta, tb) for ta in _candidate_titles(a)
                for tb in _candidate_titles(b)), default=0.0)


def _year_compatible(a: dict, b: dict) -> bool:
    """发行年份一致（任一侧缺失时放行），防止同名不同版本/系列作被并组"""
    ya, yb = _release_year(a), _release_year(b)
    return not ya or not yb or ya == yb


def _pick_result(results: List[dict], queries: List[str],
                 edition_tokens: Optional[List[str]], trust_rank: bool) -> dict:
    """在结果集中选最佳候选：版本标记匹配优先，其次标题相似度；
    无标记命中时（重制版目录）取发行年份最新的条目"""
    if trust_rank:
        return results[0]
    tokens = edition_tokens or []
    if tokens and not _soft_edition(tokens):
        hits = [r for r in results
                if all(t in " ".join(_candidate_titles(r)).lower() for t in tokens)]
        pool = hits or results
        best = max(pool, key=lambda r: _query_sim(r, queries))
        if _query_sim(best, queries) >= _PICK_BY_TITLE_RATIO:
            return best
        return pool[0]

    subtitles = subtitle_tokens(queries)
    local_part = trailing_part(queries[0] if queries else "")

    def score(r: dict) -> tuple:
        sim = _query_sim(r, queries)
        qkeys = {_match_key(q) for q in queries}
        qraw = {normalize_title(q).lower() for q in queries}
        qfull = {re.sub(r"[\s\*＊]+", "", q.lower()) for q in queries}
        primary = _match_key(r.get("title") or "")
        raw_primary = normalize_title(r.get("title") or "").lower()
        full_primary = re.sub(r"[\s\*＊]+", "", (r.get("title") or "").lower())
        exact = 1 if primary and primary in qkeys else 0
        raw_exact = 1 if raw_primary and raw_primary in qraw else 0
        full_exact = 1 if full_primary and full_primary in qfull else 0
        titles_text = " ".join(_candidate_titles(r)).lower()
        subtitle_hits = sum(1 for token in subtitles if token in titles_text)
        part = part_score(local_part, trailing_part(r.get("title") or ""))
        return (part, subtitle_hits,
                -extra_subtitle_hits(queries, _candidate_titles(r)),
                full_exact, raw_exact, sim, exact, -len(primary),
                int(_release_year(r) or 0))

    best = max(results, key=score)
    if _query_sim(best, queries) >= _PICK_BY_TITLE_RATIO:
        return best
    return results[0]


def _pick_group(candidates: Dict[str, dict], queries: List[str],
                edition_tokens: Optional[List[str]] = None) -> Tuple[Optional[Dict[str, dict]], str]:
    """跨源一致性校验，返回可合并的源组；失败时返回原因"""
    if not candidates:
        return None, "未找到匹配"
    if len(candidates) == 1:
        sid, cand = next(iter(candidates.items()))
        sim = _query_sim(cand, queries)
        if sim < _SINGLE_QUERY_RATIO:
            title = cand.get("title") or ""
            return None, f"单源候选「{title}」与标题相似度不足（{sim:.2f}），未采用"
        return {sid: cand}, ""

    edges = []
    sids = list(candidates)

    def _has_tokens(cand: dict) -> bool:
        if not edition_tokens:
            return False
        titles = " ".join(_candidate_titles(cand)).lower()
        return all(t in titles for t in edition_tokens)

    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            if _year_compatible(candidates[a], candidates[b]):
                sim = _title_affinity(candidates[a], candidates[b], queries)
                # 两个源都带同一版本标记（如 Golden Time）→ 即使跨语言也视为同一版本
                if _has_tokens(candidates[a]) and _has_tokens(candidates[b]):
                    sim = 1.0
                edges.append((sim, a, b))
    if not edges:
        # 先接受“带目录版本标记”的候选（如 HD 版 / REFLECTION BLUE / FHD）
        tokens = edition_tokens or []
        if tokens:
            token_cands = []
            for sid, cand in candidates.items():
                titles = " ".join(_candidate_titles(cand)).lower()
                if all(t in titles for t in tokens):
                    token_cands.append((sid, cand))
            if token_cands:
                sid, cand = max(token_cands, key=lambda kv: _query_sim(kv[1], queries))
                if _query_sim(cand, queries) >= _SINGLE_QUERY_RATIO:
                    return {sid: cand}, ""
        # 否则年份冲突时，VNDB 标题与查询完全一致则以 VNDB 为准
        vndb = candidates.get("vndb")
        if vndb and _release_year(vndb):
            qkeys = {_match_key(q) for q in queries}
            tkeys = {_match_key(t) for t in _candidate_titles(vndb)}
            if qkeys & tkeys:
                return {"vndb": vndb}, ""
        detail = " / ".join(f"{sid}:{candidates[sid].get('title', '')}"
                            for sid in sids)
        return None, f"各源发行年份不一致（{detail}），请手动确认"
    best_sim, best_a, best_b = max(edges, key=lambda e: e[0])
    if best_sim < _CONSENSUS_RATIO:
        detail = " / ".join(f"{sid}:{candidates[sid].get('title', '')}"
                            for sid in sids)
        return None, f"多源结果不一致（{detail}），请手动确认"

    group = {best_a, best_b}
    changed = True
    while changed:
        changed = False
        for sid in sids:
            if sid in group:
                continue
            if any(_title_affinity(candidates[sid], candidates[g], queries) >= _CONSENSUS_RATIO
                   and _year_compatible(candidates[sid], candidates[g])
                   for g in group):
                group.add(sid)
                changed = True
    return {sid: candidates[sid] for sid in group}, ""

