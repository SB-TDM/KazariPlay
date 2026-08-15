"""Bangumi API 客户端 - 搜索并获取游戏（Galgame）元数据

使用 Bangumi 公开 API（无需授权）：
    - GET /search/subject/{keywords}?type=4&responseGroup=large   搜索游戏条目
    - GET /v0/subjects/{id}                                       详情（暂未使用）

注意：
    - Bangumi 要求请求头携带 User-Agent，缺失可能被拒。
    - 新版 /v0/search/subjects 需要登录授权，这里用旧版公开搜索接口。
    - 搜索无认证但有限速（约 1 次/秒），本模块由调用方控制节奏。

统一候选字段（与 multi_source 对齐）：
    source, source_id, title, alt_title, cover_url, description,
    developer, released, rating(0-5), length_minutes, tags
"""
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from typing import List

from utils.logger import get_logger
from utils.proxy_utils import get_opener

logger = get_logger()

_API_BASE = "https://api.bgm.tv"
_USER_AGENT = "KazariPlay/1.0 (https://github.com/KazariPlay)"
_REQUEST_TIMEOUT = 15


class BangumiError(Exception):
    """Bangumi API 调用异常"""


def _http_get_json(url: str) -> dict:
    """GET 请求并返回 JSON 响应"""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with get_opener().open(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise BangumiError(f"Bangumi HTTP {e.code}: {body}") from None
    except urllib.error.URLError as e:
        raise BangumiError(f"Bangumi 网络错误: {e.reason}") from None


def _http_get(url: str) -> bytes:
    """GET 二进制内容（用于下载封面）"""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "image/*",
        },
    )
    try:
        with get_opener().open(req, timeout=_REQUEST_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise BangumiError(f"下载封面 HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise BangumiError(f"下载封面网络错误: {e.reason}") from None


def _parse_subject(item: dict) -> dict:
    """将 Bangumi 搜索返回的单个 subject 解析为统一候选字段字典"""
    images = item.get("images") or {}
    rating = item.get("rating") or {}
    score = rating.get("score") or 0

    name = item.get("name") or ""
    name_cn = item.get("name_cn") or ""
    tags = [t.get("name", "") for t in (item.get("tags") or []) if t.get("name")]

    return {
        "source": "Bangumi",
        "source_id": str(item.get("id", "")),
        "title": name_cn or name,
        "alt_title": name,
        "cover_url": images.get("large") or images.get("common") or "",
        "description": (item.get("summary") or "").strip(),
        "developer": "",
        "released": item.get("air_date") or "",
        "rating": round(score / 2) if score else 0,
        "length_minutes": 0,
        "tags": tags,
    }


def search_subjects(keyword: str, limit: int = 5) -> List[dict]:
    """搜索游戏条目（type=4 = 游戏），返回统一候选列表

    Args:
        keyword: 搜索关键词
        limit: 返回结果数上限

    Returns:
        候选列表（按 Bangumi 相关度排序），失败时返回空列表。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    url = f"{_API_BASE}/search/subject/{urllib.parse.quote(keyword)}" \
          f"?type=4&responseGroup=large&max_results={min(max(limit, 1), 50)}"

    try:
        resp = _http_get_json(url)
    except BangumiError as e:
        logger.warning("Bangumi 搜索失败: keyword=%s, err=%s", keyword, e)
        return []

    items = resp.get("list")
    if not items:
        # 兼容旧结构：results 直接是列表
        _r = resp.get("results")
        items = _r if isinstance(_r, list) else []
    parsed = []
    for item in items:
        try:
            parsed.append(_parse_subject(item))
        except Exception as e:
            logger.warning("Bangumi 解析条目失败: %s, %s", item, e)
            continue
    logger.info("Bangumi 搜索 '%s' 返回 %d 条结果", keyword, len(parsed))
    return parsed[:limit]


def search(keyword: str, count: int = 5) -> List[dict]:
    """multi_source 统一调用入口（参数名对齐 count）"""
    return search_subjects(keyword, limit=count)


def download_cover(cover_url: str, dest_path: str) -> bool:
    """下载封面图到指定路径

    Args:
        cover_url: Bangumi 图片 URL
        dest_path: 本地保存路径（含扩展名）

    Returns:
        True 下载成功，False 失败（网络错误或写入失败）
    """
    if not cover_url or not dest_path:
        return False

    try:
        data = _http_get(cover_url)
    except BangumiError as e:
        logger.warning("下载封面失败: %s, %s", cover_url, e)
        return False

    if not data:
        return False

    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    except Exception as e:
        logger.warning("创建封面目录失败: %s, %s", dest_path, e)
        return False

    try:
        with open(dest_path, "wb") as f:
            f.write(data)
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            return False
        logger.info("封面下载成功: %s -> %s (%d bytes)",
                    cover_url, dest_path, len(data))
        return True
    except Exception as e:
        logger.warning("写入封面失败: %s, %s", dest_path, e)
        return False
