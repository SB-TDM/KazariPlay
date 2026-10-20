"""自动采用前的安全校验。"""
from typing import Dict

from core.games.game_model import Game
from utils.domain.title_utils import normalize_title
from core.metadata.candidates.candidates import _candidate_titles
from core.metadata.candidates.queries import _edition_tokens, _soft_edition, _strip_edition
from core.metadata.candidates.title_policy import exact_title_match, trailing_part

def _has_external_bridge(group: Dict[str, dict]) -> bool:
    for source_id, cand in group.items():
        if source_id == "vndb":
            continue
        if str(cand.get("vndb_id") or "").strip():
            return True
        if str(cand.get("bangumi_id") or "").strip():
            return True
    return False


def _auto_match_guard(game: Game, group: Dict[str, dict]) -> str:
    """拦截缺少 ID 关联、精确同名或部数编号冲突的候选。"""
    local_part = trailing_part(normalize_title(game.title))
    for cand in group.values():
        candidate_part = trailing_part(cand.get("title") or "")
        if local_part and candidate_part and candidate_part != local_part:
            return (f"部数编号不一致（本地 {local_part}，候选 "
                    f"{candidate_part}），请手动确认")
        if not local_part and candidate_part and candidate_part != "1":
            return f"候选带续作编号（{candidate_part}），请手动确认"
    if _has_external_bridge(group):
        return ""
    if len(group) == 1:
        source_id, cand = next(iter(group.items()))
        if source_id == "kungal" and not str(cand.get("vndb_id") or "").strip():
            return "Kungal 条目缺少 VNDB 关联，请手动确认"
        if source_id == "bangumi":
            return ""
        if _soft_edition(_edition_tokens(game.title)):
            base = _strip_edition(normalize_title(game.title))
            if exact_title_match(base, _candidate_titles(cand)):
                return ""
        if not exact_title_match(game.title, _candidate_titles(cand)):
            return "候选标题不是精确匹配，请手动确认是否为同名作品"
    return ""

