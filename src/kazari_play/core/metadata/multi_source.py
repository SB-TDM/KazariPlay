"""多源元数据搜索 - 统一各元数据源（可自行配置启用哪些源）

设计：
- 源注册表 SOURCES：每个源 = {name, icon(favicon), status, client}
    status: "ready"        已实测可用（VNDB / Bangumi）
            "experimental" 按官方文档实现，但可能受地区/IP 影响（Ymgal）
            "pending"      未确认公开 API，先占位待接入（Kungal / Hikarinagi / Shionlib）
- 用户通过配置 metadata_sources.mixed 自行选择启用哪些源参与"混合"检索；
  未启用的源即使注册也不会被遍历。
- 混合检索（mixed）：按配置的源顺序逐个查询 → 合并 → 去重
  （先按 source_id 精确去重，再做标题归一化模糊去重），每候选带 source_icon。
- 统一候选字段：
    source / source_id / title / alt_title / cover_url / description /
    developer / released / rating(0-5) / length_minutes / tags / source_icon / source_name
"""
import concurrent.futures
import threading
import time
from typing import List, Optional

from utils.clients import vndb_client, bangumi_client, ymgal_client
from utils.clients import kungal_client, hikarinagi_client, shionlib_client
from utils.infra.config import Config
from utils.infra.logger import get_logger

# 多源搜索整体超时（秒）：并发发起各源，超过此时间返回已完成的部分，避免界面久等
_SEARCH_DEADLINE = 30.0

logger = get_logger()

# 源注册表（新增数据源在这里登记即可，前端设置页/工具栏自动出现）
SOURCES = {
    "vndb": {
        "name": "VNDB",
        "icon": "https://vndb.org/favicon.ico",
        "status": "ready",
        "client": vndb_client,
    },
    "bangumi": {
        "name": "Bangumi",
        "icon": "https://bgm.tv/favicon.ico",
        "status": "ready",
        "client": bangumi_client,
    },
    "ymgal": {
        "name": "月幕Galgame",
        "icon": "https://www.ymgal.games/favicon.ico",
        "status": "experimental",
        "client": ymgal_client,
    },
    "kungal": {
        "name": "Kungal",
        "icon": "https://www.kungal.com/favicon.ico",
        "status": "ready",
        "client": kungal_client,
    },
    "hikarinagi": {
        "name": "Hikarinagi",
        "icon": "https://www.hikarinagi.org/favicon.ico",
        "status": "ready",
        "client": hikarinagi_client,
    },
    "shionlib": {
        "name": "Shionlib",
        "icon": "https://shionlib.com/favicon.ico",
        "status": "experimental",
        "client": shionlib_client,
    },
}

# 默认参与混合检索的源（可在设置页勾选修改）
_DEFAULT_MIXED = ["vndb", "bangumi", "kungal"]

# 来源熔断：连续失败后短时间不再拖累整批匹配。
_SOURCE_FAILURE_LIMIT = 2
_SOURCE_COOLDOWN_SECONDS = 300.0
_source_health_lock = threading.Lock()
_source_failures: dict[str, int] = {}
_source_cooldown_until: dict[str, float] = {}


def source_available(source_id: str) -> bool:
    with _source_health_lock:
        until = _source_cooldown_until.get(source_id, 0.0)
        if until and time.time() >= until:
            _source_cooldown_until.pop(source_id, None)
            _source_failures.pop(source_id, None)
            return True
        return until <= time.time()


def mark_source_success(source_id: str) -> None:
    with _source_health_lock:
        _source_failures.pop(source_id, None)
        _source_cooldown_until.pop(source_id, None)


def mark_source_failure(source_id: str) -> None:
    with _source_health_lock:
        failures = _source_failures.get(source_id, 0) + 1
        _source_failures[source_id] = failures
        if failures >= _SOURCE_FAILURE_LIMIT:
            _source_cooldown_until[source_id] = time.time() + _SOURCE_COOLDOWN_SECONDS
            logger.warning("元数据源 %s 连续失败 %d 次，暂停 %.0f 秒",
                           source_id, failures, _SOURCE_COOLDOWN_SECONDS)



def get_all_sources() -> List[dict]:
    """返回全部源的元信息（设置页展示用）"""
    enabled = set(get_mixed_sources())
    return [{
        "id": sid,
        "name": meta["name"],
        "icon": meta["icon"],
        "status": meta["status"],
        "enabled": sid in enabled,
    } for sid, meta in SOURCES.items()]


def get_mixed_sources() -> List[str]:
    """返回用户配置的混合检索源列表（自动剔除未注册/未实现 client 的源）"""
    cfg = (Config().get("metadata_sources") or {}).get("mixed")
    if not isinstance(cfg, list):
        return list(_DEFAULT_MIXED)
    out = []
    for sid in cfg:
        meta = SOURCES.get(sid)
        if meta and meta.get("client") is not None:
            out.append(sid)
    return out or list(_DEFAULT_MIXED)


def set_mixed_sources(source_ids: List[str]) -> None:
    """保存用户勾选的混合检索源（写 config）"""
    valid = [s for s in (source_ids or []) if s in SOURCES]
    cfg = Config()
    data = dict(cfg.get("metadata_sources") or {})
    data["mixed"] = valid
    cfg.set("metadata_sources", data)
    cfg.save()


def _wrap(result: dict, source_id: str) -> dict:
    """给统一候选补 favicon 与显示名（并统一 source_id 字段）"""
    out = dict(result)
    out["source"] = source_id
    out["source_icon"] = SOURCES[source_id]["icon"]
    out["source_name"] = SOURCES[source_id]["name"]
    if not out.get("source_id") and out.get("vndb_id"):
        out["source_id"] = out["vndb_id"]
    return out


def _norm_title(t: str) -> str:
    """标题归一化（去空白/大小写，用于跨源模糊去重）"""
    import re
    return re.sub(r"\s+", "", (t or "").lower())


def _dedupe(candidates: List[dict]) -> List[dict]:
    """合并去重：先 source_id 精确，再标题归一化模糊（保留先到源的顺序）"""
    seen_ids = set()
    seen_titles = set()
    out = []
    for c in candidates:
        sid = str(c.get("source_id") or "")
        key = (c.get("source") or "", sid)
        title_key = _norm_title(c.get("title"))
        if sid and key in seen_ids:
            continue
        if title_key and title_key in seen_titles:
            continue
        if sid:
            seen_ids.add(key)
        if title_key:
            seen_titles.add(title_key)
        out.append(c)
    return out


def search_metadata(
    keyword: str,
    sources: Optional[List[str]] = None,
    limit_per_source: int = 5,
) -> List[dict]:
    """多源搜索元数据，返回统一候选列表（合并 + 去重 + 带 favicon）

    Args:
        keyword: 搜索关键词
        sources: 要检索的源 id 列表；None 时使用用户配置的混合源
        limit_per_source: 每个源返回的最大结果数

    Returns:
        合并后的候选列表（按源顺序，各源内按相关度）
    """
    target = sources if sources is not None else get_mixed_sources()
    target = [s for s in target
              if s in SOURCES and SOURCES[s].get("client") is not None]
    if not keyword or not keyword.strip():
        return []

    keyword = keyword.strip()
    all_candidates: List[dict] = []

    def _search_one(source_id: str) -> List[dict]:
        client = SOURCES[source_id]["client"]
        return [_wrap(r, source_id) for r in client.search(keyword, count=limit_per_source)]

    if len(target) <= 1:
        for source_id in target:
            try:
                all_candidates.extend(_search_one(source_id))
            except Exception as e:  # noqa: BLE001
                logger.warning("数据源 %s 搜索失败: %s", source_id, e)
    else:
        # 并发发起各源；整次搜索总超时，超时即返回已完成的部分（不再等慢源）
        order = {sid: i for i, sid in enumerate(target)}
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(target))
        futs = {ex.submit(_search_one, sid): sid for sid in target}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=_SEARCH_DEADLINE):
                sid = futs[fut]
                try:
                    all_candidates.extend(fut.result())
                except Exception as e:  # noqa: BLE001
                    logger.warning("数据源 %s 搜索失败: %s", sid, e)
        except concurrent.futures.TimeoutError:
            logger.warning("多源搜索整体超时(%.0fs)，返回已完成结果", _SEARCH_DEADLINE)
        finally:
            # wait=False：不等待未完成的慢源，否则会阻塞整个调用、令超时失效
            ex.shutdown(wait=False)
        # 并发完成顺序不定，按源配置顺序还原
        all_candidates.sort(key=lambda c: order.get(c.get("source"), len(order)))
    return _dedupe(all_candidates)
