"""标题判断策略：副标题、数字编号和精确同名判断。"""
import re
from typing import Iterable, List

_SEPARATORS = r"\s*[-–—:：～~]\s*"
_CIRCLED = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
            "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10"}


def full_title_key(text: str) -> str:
    return re.sub(r"[\s\*＊]+", "", (text or "").lower())


def exact_title_match(title: str, titles: Iterable[str]) -> bool:
    key = full_title_key(title)
    return bool(key) and any(full_title_key(t) == key for t in titles)


def title_tokens(text: str) -> set:
    return set(re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2,}", (text or "").lower()))


def subtitle_tokens(queries: Iterable[str]) -> List[str]:
    out: List[str] = []
    for query in queries:
        for part in re.split(_SEPARATORS, query or "")[1:]:
            for token in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}", part):
                value = token.lower()
                if value not in out:
                    out.append(value)
    return out


def extra_subtitle_hits(queries: Iterable[str], titles: Iterable[str]) -> int:
    query_tokens = set()
    for query in queries:
        query_tokens |= title_tokens(query)
    extra = 0
    for title in titles:
        for part in re.split(_SEPARATORS, title or "")[1:]:
            for token in title_tokens(part):
                if token not in query_tokens:
                    extra += 1
    return extra


def trailing_part(title: str) -> str:
    """返回末尾部数编号；支持 1、2、2.1 和 ①-⑩。"""
    text = (title or "").strip()
    if not text:
        return ""
    if text[-1] in _CIRCLED:
        return _CIRCLED[text[-1]]
    match = re.search(r"(?<!\d)([1-9])(?:\.(\d+))?$", text)
    if not match:
        return ""
    return match.group(1) + (f".{match.group(2)}" if match.group(2) else "")


def part_score(local_part: str, candidate_part: str) -> int:
    """数字编号兼容度：冲突返回负分，兼容返回高分。"""
    if not local_part:
        if not candidate_part:
            return 2
        return 1 if candidate_part == "1" else -10
    if not candidate_part:
        return 2 if local_part == "1" else 0
    return 3 if local_part == candidate_part else -10


def release_language_hints(text: str) -> List[str]:
    """根据标题文字选择可接受的 release 语言。"""
    value = text or ""
    if re.search(r"[\u3040-\u30ff]", value):
        return ["ja"]
    if re.search(r"[\u4e00-\u9fff]", value):
        return ["ja", "zh-Hans", "zh-Hant"]
    return ["ja", "en"]
