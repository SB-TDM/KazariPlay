"""元数据匹配服务 - 多源（VNDB / Bangumi）自动匹配并保守合并到本地 Game

策略（参考 PotatoVN 的 MixedPhraser）：
- 按配置的混合源并行搜索；每个源依次尝试 归一化标题 → 纯 CJK 提取 → 原标题
- 跨源标题一致性校验（相似度 ≥ 0.7 视为同一游戏），一致才合并；
  仅单源命中时要求候选与标题相似度 ≥ 0.8，否则不采用，避免误匹配
- 字段合并：标题/简介优先 Bangumi（中文），开发商/时长优先 VNDB；
  简介按 中文 → 日语 → 英文 选择，常规匹配会替换为更优语言版本
- 常规匹配只覆盖标题/简介/ID，其余字段仅填空；force=True 时覆盖非空元数据字段（用户评分除外）
- 已匹配（vndb_id 或 bangumi_id）的游戏跳过，强制覆盖需 force=True
- 文件夹带 FHD/Remake/SANA 等版本标记时，优先按已有发售年份选择重制版

封面下载：
- 下载到 AppData/covers/{game_id}_vndb.jpg
- 已有本地封面则不覆盖（保守策略）

速率限制：
- VNDB 官方限制约 200 次/小时；本模块不做本地请求记账，触发 429 时稍后再试。
"""
import os
import re
import difflib
import concurrent.futures
from typing import Optional, Callable, List, Tuple, Dict

from core.game_model import Game
from core import multi_source
from utils import vndb_client
from utils.path_utils import get_app_data_dir
from utils.logger import get_logger
from utils.title_utils import normalize_title

logger = get_logger()

# 进度回调签名：callback(game_id, game_title, status, message)
#   status: "skip" | "match" | "fail"
ProgressCallback = Callable[[str, str, str, str], None]

# 多源搜索整体超时（秒）：超时返回已完成的部分
_SEARCH_DEADLINE = 30.0
# 跨源标题一致阈值（Levenshtein 距离 ≤ 30% 长度，等价于相似度 ≥ 0.7）
_CONSENSUS_RATIO = 0.7
# 单源命中时，候选与查询标题的最低相似度
_SINGLE_QUERY_RATIO = 0.8
# 单源多结果中，优先选择与标题更接近的候选（低于此值仍按搜索排名取第一条）
_PICK_BY_TITLE_RATIO = 0.6

# 字段合并优先级
_TITLE_DESC_ORDER = ("bangumi", "ymgal", "vndb")
_DETAIL_ORDER = ("vndb", "ymgal", "bangumi")
_COVER_ORDER = ("vndb", "bangumi", "ymgal")


def _extract_japanese(title: str) -> str:
    """提取标题中的中文/日文字符部分（用于归一化失败时的回退搜索）

    当归一化后仍搜不到时，用这个提取纯 CJK 字符作为第二次搜索关键词。
    会排除常见的汉化组/版本后缀词，避免把"汉化版"当主标题。
    """
    if not title:
        return ""
    # 先去掉 [] 包裹的公司名（避免把公司名当主标题）
    cleaned = re.sub(r"\[[^\]]*\]", "", title)
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


def _cover_dest_path(game_id: str, cover_url: str) -> str:
    """根据游戏 ID 和 URL 推断封面本地保存路径"""
    # 从 URL 取扩展名
    ext = ".jpg"
    if cover_url:
        url_lower = cover_url.lower().split("?")[0]
        if url_lower.endswith(".png"):
            ext = ".png"
        elif url_lower.endswith(".webp"):
            ext = ".webp"
    covers_dir = os.path.join(get_app_data_dir(), "covers")
    return os.path.join(covers_dir, f"{game_id}_vndb{ext}")


def _match_key(text: str) -> str:
    """标题归一化键：去括号内容、标点、空白，仅保留字母/数字/CJK"""
    s = (text or "").lower()
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", s)
    s = re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]+", "", s)
    # Bangumi 备用名常带 "Episode.1 Miyako Kujo" 等章节后缀，比较时剔除
    s = re.sub(r"episode\d*.*$", "", s)
    return s


def _split_camel(text: str) -> str:
    """拆分无空格驼峰标题（MashiroiroSymphonyFHD → Mashiroiro Symphony FHD）"""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "").strip()


# 文件夹标题中的版本标记；候选标题全部缺失时拒绝，避免把重制版/完整版匹配到原版


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
    return out


def _strip_edition(text: str) -> str:
    """去掉版本标记，用于补搜原版/重制版条目"""
    s = _split_camel(text)
    s = re.sub(r"(?i)\s*(?:fhd|remake|sana(?:\s+edition)?)\b", "", s)
    s = re.sub(r"(?i)\s*hd\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _year_hint(game: Game) -> str:
    """已有发售日或标题中的年份，作为重制版选择线索"""
    y = _release_year({"released": game.released})
    if y:
        return y
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", game.title or "")
    return m.group(1) if m else ""


def _lang_rank(text: str) -> int:
    """简介语言优先级：中文 0 < 日语 1 < 英文/其他 2"""
    kana = len(re.findall(r"[\u3040-\u30ff]", text or ""))
    han = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    if han and han >= kana:
        return 0
    if kana:
        return 1
    return 2


def _similarity(a: str, b: str) -> float:
    """归一化标题相似度（0~1）"""
    ka, kb = _match_key(a), _match_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def _candidate_titles(cand: dict) -> List[str]:
    """候选的全部标题变体（title / alt_title）"""
    out = []
    for key in ("title", "alt_title"):
        t = (cand.get(key) or "").strip()
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


def _release_year(cand: dict) -> str:
    m = re.match(r"(\d{4})", (cand.get("released") or "").strip())
    return m.group(1) if m else ""


def _year_compatible(a: dict, b: dict) -> bool:
    """发行年份一致（任一侧缺失时放行），防止同名不同版本/系列作被并组"""
    ya, yb = _release_year(a), _release_year(b)
    return not ya or not yb or ya == yb


def _build_queries(title: str) -> List[str]:
    """按策略构造搜索关键词：归一化 → 纯 CJK → 原标题（含驼峰拆分，去重）"""
    out: List[str] = []
    seen = set()
    bases = [normalize_title(title), _extract_japanese(title), title, _split_camel(title),
             _strip_edition(title), _strip_edition(_split_camel(title))]
    for base in bases:
        for q in (base, _split_camel(base), _strip_edition(base)):
            q = (q or "").strip()
            key = q.lower()
            if q and key not in seen:
                seen.add(key)
                out.append(q)
    return out


def _pick_result(results: List[dict], queries: List[str],
                 edition_tokens: Optional[List[str]], trust_rank: bool) -> dict:
    """在结果集中选最佳候选：版本标记匹配优先，其次标题相似度"""
    if trust_rank:
        return results[0]
    tokens = edition_tokens or []

    def score(r: dict) -> tuple:
        titles = " ".join(_candidate_titles(r)).lower()
        token_ok = 1 if tokens and all(t in titles for t in tokens) else 0
        return (token_ok, _query_sim(r, queries))

    best = max(results, key=score)
    if score(best)[1] >= _PICK_BY_TITLE_RATIO:
        return best
    return results[0]


def _search_source(source_id: str, queries: List[str], cancel_event=None,
                   trust_rank: bool = False, year_hint: str = "",
                   edition_tokens: Optional[List[str]] = None) -> Optional[dict]:
    """在单个源上按关键词策略搜索，返回最合适的候选

    - year_hint：优先选发行年份一致的候选（用于按年份选重制版）；当前关键词
      没有同年结果时继续尝试后续关键词，全部失败才回退到首个结果
    - trust_rank=True 时直接取搜索排名第一条（用于跨语言桥接）
    """
    meta = multi_source.SOURCES.get(source_id) or {}
    client = meta.get("client")
    if client is None:
        return None
    fallback: Optional[dict] = None
    for q in queries:
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            results = client.search(q, count=5)
        except Exception as e:  # noqa: BLE001
            logger.warning("元数据源 %s 搜索失败: q='%s', %s", source_id, q, e)
            continue
        if not results:
            continue
        if year_hint:
            same_year = [r for r in results if _release_year(r) == year_hint]
            if not same_year:
                if fallback is None:
                    fallback = _pick_result(results, queries, edition_tokens, trust_rank)
                continue
            return _pick_result(same_year, queries, edition_tokens, trust_rank)
        return _pick_result(results, queries, edition_tokens, trust_rank)
    return fallback


def _search_all(queries: List[str], cancel_event=None, year_hint: str = "",
                edition_tokens: Optional[List[str]] = None) -> Dict[str, dict]:
    """并行查询各源，返回 {source_id: 候选}；失败的源忽略"""
    sources = [s for s in multi_source.get_mixed_sources()
               if (multi_source.SOURCES.get(s) or {}).get("client") is not None]
    if not sources:
        return {}
    candidates: Dict[str, dict] = {}
    if len(sources) == 1:
        cand = _search_source(sources[0], queries, cancel_event, False,
                              year_hint, edition_tokens)
        return {sources[0]: cand} if cand else {}
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(sources))
    futs = {ex.submit(_search_source, sid, queries, cancel_event, False,
                      year_hint, edition_tokens): sid for sid in sources}
    try:
        for fut in concurrent.futures.as_completed(futs, timeout=_SEARCH_DEADLINE):
            sid = futs[fut]
            try:
                cand = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("元数据源 %s 搜索异常: %s", sid, e)
                continue
            if cand:
                candidates[sid] = cand
    except concurrent.futures.TimeoutError:
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
                                      year_hint, edition_tokens)
            except Exception as e:  # noqa: BLE001
                logger.warning("元数据源 %s 桥接搜索失败: %s", sid, e)
                continue
            if cand:
                candidates[sid] = cand
    return candidates


def _pick_group(candidates: Dict[str, dict], queries: List[str]) -> Tuple[Optional[Dict[str, dict]], str]:
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
    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            if _year_compatible(candidates[a], candidates[b]):
                edges.append((_title_sim(candidates[a], candidates[b]), a, b))
    if not edges:
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
            if any(_title_sim(candidates[sid], candidates[g]) >= _CONSENSUS_RATIO
                   and _year_compatible(candidates[sid], candidates[g])
                   for g in group):
                group.add(sid)
                changed = True
    return {sid: candidates[sid] for sid in group}, ""


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
    vndb = group.get("vndb") or {}
    bangumi = group.get("bangumi") or {}
    return {
        "vndb_id": (vndb.get("vndb_id") or "").strip(),
        "bangumi_id": str(bangumi.get("source_id") or "").strip(),
        "title": _pick_field(group, "title", _TITLE_DESC_ORDER),
        "description": _preferred_description(group),
        "developer": _pick_field(group, "developer", _DETAIL_ORDER),
        "released": _pick_field(group, "released", _DETAIL_ORDER),
        "rating": (_pick_field(group, "rating", _DETAIL_ORDER) or 0),
        "length_minutes": (_pick_field(group, "length_minutes", _DETAIL_ORDER) or 0),
        "cover_url": _pick_field(group, "cover_url", _COVER_ORDER),
    }


def match_single(game: Game, force: bool = False, cancel_event=None, cover_cb=None) -> Tuple[str, str]:
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
    candidates = _search_all(queries, cancel_event, year_hint=year_hint,
                             edition_tokens=tokens)
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled", "已取消"
    group, reason = _pick_group(candidates, queries)

    if not group:
        logger.info("元数据未匹配: %s (%s)", game.title, reason)
        return "fail", reason

    # 版本标记守卫：文件夹带 FHD/Remake/SANA 等标记而候选标题全部缺失时，
    # 仅当候选发行年份与线索年份一致才按重制版采用，否则交给用户手动确认
    if tokens:
        cand_titles = " ".join(
            t for c in group.values() for t in _candidate_titles(c)).lower()
        missing_tokens = [t for t in tokens if t not in cand_titles]
        if missing_tokens:
            group_years = {_release_year(c) for c in group.values()} - {""}
            if not (year_hint and group_years == {year_hint}):
                reason = f"候选缺少版本标记（{', '.join(missing_tokens)}），请手动确认"
                logger.info("元数据未匹配: %s (%s)", game.title, reason)
                return "fail", reason

    merged = _merge_candidates(group)
    sources = "+".join(multi_source.SOURCES.get(s, {}).get("name", s)
                       for s in group)
    overwrite = bool(force)
    updated_fields: List[str] = []

    if merged["vndb_id"] and game.vndb_id != merged["vndb_id"]:
        game.vndb_id = merged["vndb_id"]
        updated_fields.append("vndb_id")
    if merged["bangumi_id"] and game.bangumi_id != merged["bangumi_id"]:
        game.bangumi_id = merged["bangumi_id"]
        updated_fields.append("bangumi_id")

    # 标题：匹配成功后用元数据标题覆盖（Bangumi 有中文名时优先中文）
    if merged["title"] and game.title != merged["title"]:
        game.title = merged["title"]
        updated_fields.append("title")

    # 简介：按 中文→日语→英文 选出的结果替换；force 时无条件覆盖
    if merged["description"]:
        old_rank = _lang_rank(game.description) if game.description else 99
        if (overwrite or _lang_rank(merged["description"]) <= old_rank) \
                and game.description != merged["description"]:
            game.description = merged["description"]
            updated_fields.append("description")

    # 评分属于用户自己的评分，force 也不覆盖，仅在未评分时填元数据评分
    if merged["rating"] and not game.rating:
        game.rating = merged["rating"]
        updated_fields.append("rating")

    if merged["released"] and (overwrite or not game.released):
        game.released = merged["released"]
        updated_fields.append("released")

    if merged["developer"] and (overwrite or not game.developer):
        game.developer = merged["developer"]
        updated_fields.append("developer")

    if merged["length_minutes"] and (overwrite or not game.length_minutes):
        game.length_minutes = merged["length_minutes"]
        updated_fields.append("length_minutes")

    # 封面：优先交给 cover_cb 异步下载（不阻塞匹配）；无 cover_cb 时回退同步下载
    cover_queued = False
    if not game.cover_path and merged["cover_url"]:
        dest = _cover_dest_path(game.id, merged["cover_url"])
        if cover_cb is not None:
            cover_cb(game.id, merged["cover_url"], dest)
            cover_queued = True
        elif vndb_client.download_cover(merged["cover_url"], dest,
                                        cancel_event=cancel_event):
            game.cover_path = dest
            updated_fields.append("cover_path")
        else:
            logger.warning("封面下载失败，跳过: %s", merged["cover_url"])

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

        status, msg = match_single(game, force=force, cancel_event=cancel_event, cover_cb=cover_cb)

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
