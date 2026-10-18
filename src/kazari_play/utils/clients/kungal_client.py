"""Kungal（鲲 Galgame）公开目录 API 客户端。

公开搜索接口：GET https://www.kungal.com/api/v1/search/works?q=...
详情接口：GET https://www.kungal.com/api/v1/works/{id}
无需登录；本模块只读取公开数据，失败静默返回空列表。
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from utils.infra.logger import get_logger
from utils.infra.proxy_utils import get_opener
from utils.infra.rate_limit import rate_limiter, retry_after_seconds
from utils.domain.rating_utils import rating_from_100

logger = get_logger()

_BASE = "https://www.kungal.com"
_UA = "KazariPlay/1.0 (+https://github.com/SB-TDM/KazariPlay)"
_TIMEOUT = 15


class KungalError(Exception):
    """Kungal API 调用异常"""


def _get_json(url: str) -> dict:
    rate_limiter.wait("kungal")
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with get_opener().open(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            rate_limiter.backoff("kungal", retry_after_seconds(e, 30))
        raise KungalError(f"Kungal HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise KungalError(f"Kungal 网络错误: {e.reason}") from None


def _localized(item: dict, locale: str) -> str:
    value = ((item.get("localized") or {}).get(locale) or {}).get("value")
    return str(value or "").strip()


def _parse_work(item: dict) -> dict:
    title = (_localized(item, "zh-Hans") or item.get("display_name")
             or _localized(item, "ja") or _localized(item, "en") or "")
    alt = _localized(item, "ja") or _localized(item, "en") or item.get("display_name") or ""
    maker = item.get("maker") or {}
    developer = str(maker.get("display_name") or "").strip()
    score = item.get("rating_score") or 0
    try:
        rating = rating_from_100(float(score) * 10)
    except (TypeError, ValueError):
        rating = 0.0
    cover = (item.get("cover") or {}).get("url") or ""
    released = str(item.get("release_date") or "").strip()
    all_titles = []
    for locale in ("zh-Hans", "zh-Hant", "ja", "en"):
        value = _localized(item, locale)
        if value and value not in all_titles:
            all_titles.append(value)
    aliases = [str(a).strip() for a in (item.get("alias") or [])
               if str(a).strip()]
    return {
        "source": "kungal",
        "source_id": str(item.get("id") or ""),
        "title": title,
        "alt_title": alt,
        "all_titles": all_titles,
        "aliases": aliases,
        "cover_url": cover,
        "description": "",
        "developer": developer,
        "released": released,
        "rating": rating,
        "length_minutes": 0,
        "tags": [],
    }


def detail(work_id: str) -> dict:
    """按 Kungal work id 补全详情。"""
    work_id = str(work_id or "").strip()
    if not work_id:
        return {}
    data = _get_json(f"{_BASE}/api/v1/works/{urllib.parse.quote(work_id)}")
    if not isinstance(data, dict):
        return {}
    out = _parse_work(data)
    intros = data.get("intros") or []
    for locale in ("zh-Hans", "zh-Hant", "ja", "en"):
        for item in intros:
            if item.get("locale") == locale and item.get("value"):
                out["description"] = str(item["value"]).strip()
                break
        if out["description"]:
            break
    companies = data.get("companies") or []
    for company in companies:
        roles = company.get("attribution_roles") or []
        if "developer" in roles and company.get("display_name"):
            out["developer"] = str(company["display_name"]).strip()
            break
    engines = data.get("engines") or []
    if engines:
        out["engine"] = str(engines[0].get("display_name") or "").strip()
    tags = data.get("tags") or []
    out["tags"] = [str(t.get("display_name") or "") for t in tags if t.get("display_name")]
    for ref in data.get("external_refs") or []:
        site = str(ref.get("site") or "").lower()
        ext = str(ref.get("external_id") or "").strip()
        if site == "vndb" and ext.startswith("v"):
            out["vndb_id"] = ext
        elif site == "bangumi" and ext:
            out["bangumi_id"] = ext
    return out


def search(keyword: str, count: int = 5) -> List[dict]:
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    url = (f"{_BASE}/api/v1/search/works?q={urllib.parse.quote(keyword)}"
           f"&limit={min(max(count, 1), 20)}")
    try:
        data = _get_json(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("Kungal 搜索失败: keyword=%s, %s", keyword, e)
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        try:
            parsed = _parse_work(item)
            if parsed["source_id"] and parsed["title"]:
                out.append(parsed)
        except Exception as e:  # noqa: BLE001
            logger.warning("Kungal 解析条目失败: %s", e)
    return out[:count]
