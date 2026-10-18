"""Hikarinagi（ひかりなぎ）公开 API 客户端。

搜索：GET https://www.hikarinagi.org/api/v3/search?q=...&types=galgame
详情：GET https://www.hikarinagi.org/api/v3/galgames/{id}
无需登录；只读取公开数据，失败静默返回空列表。
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from utils.infra.logger import get_logger
from utils.infra.proxy_utils import get_opener
from utils.infra.rate_limit import rate_limiter, retry_after_seconds

logger = get_logger()

_BASE = "https://www.hikarinagi.org"
_UA = "KazariPlay/1.0 (+https://github.com/SB-TDM/KazariPlay)"
_TIMEOUT = 15


class HikarinagiError(Exception):
    """Hikarinagi API 调用异常"""


def _get_json(url: str) -> dict:
    rate_limiter.wait("hikarinagi")
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with get_opener().open(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            rate_limiter.backoff("hikarinagi", retry_after_seconds(e, 30))
        raise HikarinagiError(f"Hikarinagi HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise HikarinagiError(f"Hikarinagi 网络错误: {e.reason}") from None


def _detail(game_id: str) -> dict:
    try:
        data = _get_json(f"{_BASE}/api/v3/galgames/{urllib.parse.quote(game_id)}")
        item = data.get("data") if isinstance(data, dict) else None
        return item if isinstance(item, dict) else {}
    except Exception:
        return {}


def _parse(item: dict, detail: dict) -> dict:
    title = (detail.get("trans_title") or detail.get("origin_title")
             or item.get("title") or "")
    alt = (detail.get("origin_title") or detail.get("en_title")
           or item.get("title") or "")
    desc = (detail.get("trans_intro") or detail.get("origin_intro")
            or detail.get("en_intro") or "")
    released = detail.get("release_date") or item.get("subtitle") or ""
    developer = item.get("developer") or ""
    vndb = detail.get("vndb_id")
    vndb_id = f"v{vndb}" if vndb else ""
    bangumi_id = detail.get("bangumi_game_id")
    return {
        "source": "hikarinagi",
        "source_id": str(item.get("id") or detail.get("id") or ""),
        "title": str(title).strip(),
        "alt_title": str(alt).strip(),
        "cover_url": "",
        "description": str(desc).strip(),
        "developer": str(developer).strip(),
        "released": str(released).strip(),
        "rating": 0.0,
        "length_minutes": 0,
        "tags": [],
        "vndb_id": vndb_id,
        "bangumi_id": str(bangumi_id or ""),
    }


def detail(game_id: str) -> dict:
    """按 Hikarinagi id 补全详情。"""
    gid = str(game_id or "").strip()
    if not gid:
        return {}
    return _parse({"id": gid}, _detail(gid))


def search(keyword: str, count: int = 5) -> List[dict]:
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    url = (f"{_BASE}/api/v3/search?q={urllib.parse.quote(keyword)}"
           "&types=galgame")
    try:
        data = _get_json(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("Hikarinagi 搜索失败: keyword=%s, %s", keyword, e)
        return []
    items = ((data.get("data") or {}).get("items")
             if isinstance(data, dict) else None)
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:count]:
        try:
            parsed = _parse(item, {})
            if parsed["source_id"] and parsed["title"]:
                out.append(parsed)
        except Exception as e:  # noqa: BLE001
            logger.warning("Hikarinagi 解析条目失败: %s", e)
    return out
