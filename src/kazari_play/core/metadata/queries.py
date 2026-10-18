"""搜索关键词与标题归一化。"""
import re
from typing import List

from core.games.game_model import Game
from utils.domain.title_utils import normalize_title

def _extract_japanese(title: str) -> str:
    """提取标题中的中文/日文字符部分（用于归一化失败时的回退搜索）

    当归一化后仍搜不到时，用这个提取纯 CJK 字符作为第二次搜索关键词。
    会排除常见的汉化组/版本后缀词，避免把"汉化版"当主标题。
    """
    if not title:
        return ""
    # 先去掉 [] / () / （） / 【】 包裹的公司名或章节名（避免把后缀当主标题）
    cleaned = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】", "", title)
    # 匹配 CJK 统一表意文字 + 平假名 + 片假名
    m = re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+", cleaned)
    if not m:
        return ""
    # 排除汉化组/版本词（包含判断，避免"默示汉化组"漏网）
    blacklist = ("汉化", "中文版", "简体", "繁体",
                 "官方中文", "民间", "完结", "DL版")
    filtered = [s for s in m if not any(kw in s for kw in blacklist)]
    if not filtered:
        return ""
    # 取最长的 CJK 片段（通常是主标题）
    return max(filtered, key=len)


def _match_key(text: str) -> str:
    """标题归一化键：去子标题/括号内容、标点、空白，仅保留字母/数字/CJK"""
    s = (text or "").lower()
    # 子标题分隔：" -Love is Pure White-"、"～不連続存在～"、"* tagline"
    for pattern in (r"\s+[-–—]\s*", r"\s*[～〜]\s*", r"\s+\*\s*|\s*\*\s+"):
        parts = re.split(pattern, s, maxsplit=1)
        if parts[0].strip():
            s = parts[0]
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", s)
    s = re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]+", "", s)
    # Bangumi 备用名常带 "Episode.1 Miyako Kujo" 等章节后缀，比较时剔除
    s = re.sub(r"episode\d*.*$", "", s)
    return s


def _split_camel(text: str) -> str:
    """拆分无空格驼峰标题（MashiroiroSymphonyFHD → Mashiroiro Symphony FHD）"""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "").strip()


def _edition_tokens(title: str) -> List[str]:
    """提取文件夹标题里的版本标记（支持无空格驼峰）"""
    low = (title or "").lower()
    out: List[str] = []
    if "fhd" in low:
        out.append("fhd")
    elif re.search(r"(?<!f)hd(?![a-z])", low):
        out.append("hd")
    if "remake" in low:
        out.append("remake")
    if "sana" in low:
        out.append("sana")
    if "reflection blue" in low:
        out.append("reflection blue")
    if "golden time" in low:
        out.append("golden time")
    return out


def _strip_edition(text: str) -> str:
    """去掉版本标记，用于补搜原版/重制版条目"""
    s = _split_camel(text)
    s = re.sub(r"(?i)\s*(?:fhd|hd)版\s*", "", s)
    tokens = _edition_tokens(text) + _edition_tokens(s)
    for token in tokens:
        s = re.sub(r"(?i)\s*" + re.escape(token) + r"\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _soft_edition(tokens: List[str]) -> bool:
    """HD/FHD 是画质/移植标记，不强制候选标题带版本词。"""
    return bool(tokens) and all(t in ("hd", "fhd") for t in tokens)


def _prefix_variants(text: str) -> List[str]:
    """生成无空格连字符/冒号副标题的系列前缀候选。"""
    parts = [p.strip() for p in re.split(r"\s*[-–—:：]\s*", _split_camel(text)) if p.strip()]
    out: List[str] = []
    for i in range(1, len(parts)):
        prefix = "-".join(parts[:i])
        compact = re.sub(r"[-_]", "", prefix)
        for value in (prefix, compact):
            if len(value) >= 3 and value.lower() not in {x.lower() for x in out}:
                out.append(value)
    return out


def _series_key(text: str) -> str:
    """提取标题开头的 ASCII 系列键（9-nine / 9nine / Mashiro-iro）。"""
    m = re.match(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", _split_camel(text or ""))
    return re.sub(r"[-_]", "", m.group(0).lower()) if m else ""


def _release_year(cand: dict) -> str:
    m = re.match(r"(\d{4})", (cand.get("released") or "").strip())
    return m.group(1) if m else ""


def _year_hint(game: Game) -> str:
    """已有发售日或标题中的年份，作为重制版选择线索"""
    y = _release_year({"released": game.released})
    if y:
        return y
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", game.title or "")
    return m.group(1) if m else ""


def _build_queries(title: str) -> List[str]:
    """按策略构造搜索关键词：归一化 → 纯 CJK → 原标题（含驼峰拆分，去重）"""
    out: List[str] = []
    seen = set()
    bare = re.sub(r"[*＊]", "", title)
    bases = [normalize_title(title), _extract_japanese(title), title, bare,
             _split_camel(title), _strip_edition(title),
             _strip_edition(_split_camel(title)), _strip_edition(bare)]
    for base in bases:
        for q in (base, _split_camel(base), _strip_edition(base)):
            q = (q or "").strip()
            key = q.lower()
            if q and key not in seen:
                seen.add(key)
                out.append(q)
            for prefix in _prefix_variants(q):
                if prefix.lower() not in seen:
                    seen.add(prefix.lower())
                    out.append(prefix)
    return out

