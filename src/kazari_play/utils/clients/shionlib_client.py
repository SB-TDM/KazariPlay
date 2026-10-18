"""Shionlib 开放接口客户端（需要用户 API Key）。

Shionlib 开放接口按编号查询，不提供关键词搜索；这里先用 Hikarinagi 的公开搜索
取得 hid，再调用 Shionlib /api/open/v1/games?hid=... 获取游戏与资源信息。
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from utils.clients import hikarinagi_client
from utils.infra.config import Config
from utils.infra.logger import get_logger
from utils.infra.proxy_utils import get_opener
from utils.infra.rate_limit import rate_limiter, retry_after_seconds

logger = get_logger()

_BASE = "https://shionlib.com/api/open/v1/games"
_UA = "KazariPlay/1.0 (+https://github.com/SB-TDM/KazariPlay)"
_TIMEOUT = 15


class ShionlibError(Exception):
    """Shionlib API 调用异常"""


def _api_key() -> str:
    try:
        return str(Config().get("metadata_sources.shionlib_api_key", "") or "").strip()
    except Exception:
        return ""


def _get_json(url: str, key: str) -> dict:
    rate_limiter.wait("shionlib")
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
    })
    try:
        with get_opener().open(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            rate_limiter.backoff("shionlib", retry_after_seconds(e, 30))
        raise ShionlibError(f"Shionlib HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise ShionlibError(f"Shionlib 网络错误: {e.reason}") from None


def _parse_game(game: dict) -> dict:
    title = (game.get("title_zh") or game.get("title_jp")
             or game.get("title_en") or "")
    alt = game.get("title_jp") or game.get("title_en") or ""
    return {
        "source": "shionlib",
        "source_id": str(game.get("hid") or game.get("id") or ""),
        "title": str(title).strip(),
        "alt_title": str(alt).strip(),
        "cover_url": "",
        "description": "",
        "developer": "",
        "released": "",
        "rating": 0.0,
        "length_minutes": 0,
        "tags": [],
        "vndb_id": str(game.get("vid") or "").strip(),
        "bangumi_id": str(game.get("bid") or "").strip(),
    }


def detail(source_id: str) -> dict:
    """按 Hikarinagi/Shionlib id 查询详情。"""
    key = _api_key()
    sid = str(source_id or "").strip()
    if not key or not sid:
        return {}
    url = f"{_BASE}?hid={urllib.parse.quote(sid)}"
    try:
        data = _get_json(url, key)
    except Exception as e:  # noqa: BLE001
        logger.warning("Shionlib 详情查询失败: id=%s, %s", sid, e)
        return {}
    games = ((data.get("data") or {}).get("games")
             if isinstance(data, dict) else None)
    if not isinstance(games, list) or not games:
        return {}
    try:
        return _parse_game(games[0])
    except Exception:
        return {}


def search(keyword: str, count: int = 5) -> List[dict]:
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    key = _api_key()
    if not key:
        return []
    # 开放接口不支持关键词，先用公开的 Hikarinagi 搜索拿到 hid。
    hikari = hikarinagi_client.search(keyword, count=min(max(count, 1), 10))
    hids = []
    for item in hikari:
        sid = str(item.get("source_id") or "").strip()
        if sid and sid not in hids:
            hids.append(sid)
    if not hids:
        return []
    url = f"{_BASE}?hid={urllib.parse.quote(','.join(hids[:50]))}"
    try:
        data = _get_json(url, key)
    except Exception as e:  # noqa: BLE001
        logger.warning("Shionlib 查询失败: keyword=%s, %s", keyword, e)
        return []
    games = ((data.get("data") or {}).get("games")
             if isinstance(data, dict) else None)
    if not isinstance(games, list):
        return []
    out = []
    for game in games:
        try:
            parsed = _parse_game(game)
            if parsed["source_id"] and parsed["title"]:
                out.append(parsed)
        except Exception as e:  # noqa: BLE001
            logger.warning("Shionlib 解析条目失败: %s", e)
    return out[:count]
