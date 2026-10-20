"""跨源字段合并。"""
import re
from typing import Dict, Tuple

from core.metadata.candidates.constants import (
    _COVER_ORDER,
    _DETAIL_ORDER,
    _TITLE_DESC_ORDER,
)
from utils.infra.config import Config

def _cover_order() -> Tuple[str, ...]:
    preferred = str(Config().get("cover_download.preferred_source", "auto") or "auto").lower()
    if preferred in _COVER_ORDER:
        return (preferred,) + tuple(s for s in _COVER_ORDER if s != preferred)
    return _COVER_ORDER


def _pick_field(group: Dict[str, dict], field: str, order: Tuple[str, ...]):
    """按源优先级取第一个非空字段值"""
    for sid in order:
        cand = group.get(sid)
        if cand and cand.get(field):
            return cand[field]
    for cand in group.values():
        if cand.get(field):
            return cand[field]
    return ""


def _preferred_description(group: Dict[str, dict]) -> str:
    """按 中文 → 日语 → 英文 选简介；同语言按源优先级（Bangumi→月幕→VNDB）"""
    order = {sid: i for i, sid in enumerate(_TITLE_DESC_ORDER)}
    cands = []
    for sid, cand in group.items():
        d = (cand.get("description") or "").strip()
        if d:
            cands.append((_lang_rank(d), order.get(sid, 99), d))
    return min(cands)[2] if cands else ""


def _merge_candidates(group: Dict[str, dict]) -> dict:
    """按字段优先级合并多源候选"""
    return {
        "vndb_id": str(_pick_field(
            group, "vndb_id",
            ("vndb", "hikarinagi", "kungal", "shionlib", "bangumi")) or "").strip(),
        "bangumi_id": str(_pick_field(
            group, "bangumi_id",
            ("bangumi", "hikarinagi", "shionlib", "kungal", "vndb"))
            or (group.get("bangumi") or {}).get("source_id") or "").strip(),
        "title": _pick_field(group, "title", _TITLE_DESC_ORDER),
        "description": _preferred_description(group),
        "developer": _pick_field(group, "developer", _DETAIL_ORDER),
        "released": _pick_field(group, "released", _DETAIL_ORDER),
        "rating": (_pick_field(group, "rating", _DETAIL_ORDER) or 0),
        "length_minutes": (_pick_field(group, "length_minutes", _DETAIL_ORDER) or 0),
        "cover_url": _pick_field(group, "cover_url", _cover_order()),
    }


def _lang_rank(text: str) -> int:
    """简介语言优先级：中文 0 < 日语 1 < 英文/其他 2"""
    kana = len(re.findall(r"[\u3040-\u30ff]", text or ""))
    han = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    if han and han >= kana:
        return 0
    if kana:
        return 1
    return 2

