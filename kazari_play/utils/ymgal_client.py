"""Ymgal（月幕Galgame）API 客户端 - 官方开放接口实现

官方文档：https://www.ymgal.games/developer（github.com/ymgal/docs）
- 认证：OAuth2.0 Client Credentials，公共 client_id=ymgal / client_secret=luna0327
        GET /oauth/token 获取 access_token（1h 有效，重复请求返回同一 token）
- 搜索：GET /open/archive/search-game?keyword=...&pageNum=&pageSize=（version: 1）
- 请求头：Accept: application/json;charset=utf-8 / Authorization: Bearer <token> / version: 1

注意：该 API 的可用性受地区/IP 影响（文档已声明 DNS 污染与地区可达性风险），
本模块全部失败静默降级（返回空列表），调用方按源状态展示"实验性"。
"""
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import List, Optional

from utils.logger import get_logger
from utils.proxy_utils import get_opener

logger = get_logger()

_BASE = "https://www.ymgal.games"
_CLIENT_ID = "ymgal"
_CLIENT_SECRET = "luna0327"          # 官方公开的公共凭证
_TOKEN_URL = f"{_BASE}/oauth/token"
_SEARCH_URL = f"{_BASE}/open/archive/search-game"
_UA = "Mozilla/5.0 KazariPlay/1.0"
_TIMEOUT = 15

_token: Optional[str] = None
_token_expire: float = 0


class YmgalError(Exception):
    """Ymgal API 调用异常"""


def _request(url: str, headers: Optional[dict] = None, timeout: int = _TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": _UA})
    try:
        with get_opener().open(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise YmgalError(f"Ymgal HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise YmgalError(f"Ymgal 网络错误: {e.reason}") from None


def _get_token() -> Optional[str]:
    """获取 access_token（1h 有效，进程内缓存；失败返回 None）"""
    global _token, _token_expire
    if _token and time.time() < _token_expire:
        return _token
    try:
        url = f"{_TOKEN_URL}?client_id={_CLIENT_ID}&client_secret={_CLIENT_SECRET}" \
              f"&grant_type=client_credentials"
        data = json.loads(_request(url, {"User-Agent": _UA}).decode("utf-8"))
        token = data.get("access_token") or ""
        if token:
            _token = token
            _token_expire = time.time() + int(data.get("expires_in", 3600)) - 60
            return token
    except Exception as e:  # noqa: BLE001
        logger.warning("Ymgal 获取 token 失败: %s", e)
    return None


def _auth_headers() -> Optional[dict]:
    token = _get_token()
    if not token:
        return None
    return {
        "Accept": "application/json;charset=utf-8",
        "Authorization": f"Bearer {token}",
        "version": "1",
        "User-Agent": _UA,
    }


def _parse_game(item: dict) -> dict:
    """解析单个 game 档案为统一候选格式（字段名做防御式兼容）"""
    # 列表接口返回：id(=gid) / name(原名) / chineseName(中文名) / mainImg / releaseDate / score
    title = (item.get("chineseName") or item.get("name")
             or item.get("originalName") or item.get("title") or "")
    cover = (item.get("mainImg") or item.get("cover")
             or item.get("coverUrl") or "")
    released = item.get("releaseDate") or item.get("release_date") or ""
    description = item.get("introduction") or item.get("description") or ""
    # score 可能是数字字符串（文档示例为 ""），防御式转换
    score = item.get("score") or item.get("rating") or 0
    try:
        rating_5 = round(float(score) / 20)
    except (ValueError, TypeError):
        rating_5 = 0
    if rating_5 < 1:
        rating_5 = 0
    return {
        "source": "ymgal",
        "source_id": str(item.get("id") or item.get("gid") or ""),
        "title": title,
        "alt_title": "",
        "cover_url": cover,
        "description": (description or "").strip(),
        "developer": "",
        "released": str(released or ""),
        "rating": rating_5,
        "length_minutes": 0,
        "tags": [],
    }


def search(keyword: str, count: int = 5) -> List[dict]:
    """搜索游戏列表（mode=list），失败返回空列表（静默降级）"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    headers = _auth_headers()
    if not headers:
        return []
    url = (f"{_SEARCH_URL}?mode=list&keyword={urllib.parse.quote(keyword)}"
           f"&pageNum=1&pageSize={min(max(count, 1), 20)}")
    try:
        raw = _request(url, headers)
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("Ymgal 搜索失败: keyword=%s, %s", keyword, e)
        return []
    if not data.get("success"):
        logger.warning("Ymgal 搜索未命中: keyword=%s, code=%s, msg=%s",
                       keyword, data.get("code"), data.get("msg"))
        return []
    # 分页接口：列表在 data.result（防御式兼容 list / records / game 单对象）
    payload = data.get("data") or {}
    items = (payload.get("result")
             or payload.get("list")
             or payload.get("records")
             or (payload.get("game") and [payload["game"]])
             or [])
    parsed = []
    for it in items:
        try:
            parsed.append(_parse_game(it))
        except Exception as e:  # noqa: BLE001
            logger.warning("Ymgal 解析条目失败: %s", e)
            continue
    return parsed


def download_cover(cover_url: str, dest_path: str) -> bool:
    """下载封面图到本地"""
    if not cover_url or not dest_path:
        return False
    try:
        data = _request(cover_url, {"User-Agent": _UA})
    except Exception as e:  # noqa: BLE001
        logger.warning("Ymgal 下载封面失败: %s, %s", cover_url, e)
        return False
    if not data:
        return False
    try:
        import os
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
    except Exception as e:  # noqa: BLE001
        logger.warning("Ymgal 写入封面失败: %s", e)
        return False
