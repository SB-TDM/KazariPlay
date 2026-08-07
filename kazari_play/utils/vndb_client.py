"""VNDB API 客户端 - 调用 VNDB v2 REST API 获取视觉小说元数据

API 文档：https://api.vndb.org/kana
端点：
    - POST https://api.vndb.org/kana/vn       查询视觉小说
    - GET  https://t.vndb.org/cv/{id}.jpg      封面图（CDN）

速率限制：约 200 次/小时、每秒 1 次（官方推荐间隔 ≥ 1s）。
本模块不做速率限制，由调用方（metadata_matcher）控制批量调用节奏。

返回字段（VNDB → 本地映射）：
    id            -> vndb_id（如 "v1234"）
    title         -> title（罗马音/英文）
    alttitle      -> title（日文原名，优先用）
    image.url     -> cover_path（下载到本地后的路径）
    rating        -> rating（0-100，需转换为 1-5）
    description   -> description（HTML 标签需清理）
    released      -> released（ISO 日期 YYYY-MM-DD）
    length_minutes-> length_minutes（VNDB 直接返回分钟数）
"""
import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Optional
from utils.logger import get_logger

logger = get_logger()

# VNDB API 端点
_VNDB_API_BASE = "https://api.vndb.org/kana"
_VNDB_COVER_BASE = "https://t.vndb.org"

# User-Agent（VNDB 要求提供，避免被拒绝）
_USER_AGENT = "KazariPlay/1.0 (https://github.com/KazariPlay)"

# 请求超时（秒）
_REQUEST_TIMEOUT = 15
# 网络请求重试：超时/临时网络错误时重试次数与间隔
_MAX_RETRIES = 2
_RETRY_BACKOFF = 2  # 每次重试额外等待秒数（1s、3s、5s）


class VndbError(Exception):
    """VNDB API 调用异常"""


def _should_retry(exc: Exception) -> bool:
    """判断异常是否属于可重试的临时网络故障（超时、连接重置、DNS 等）"""
    if isinstance(exc, (VndbError,)):
        msg = str(exc)
        return any(kw in msg for kw in ("timed out", "超时", "timed_out",
                                        "Connection reset", "name or service",
                                        "WinError 10054", "WinError 10060",
                                        "网络错误"))
    return False


def _request_with_retry(send: callable) -> bytes:
    """带重试的 HTTP 请求：send 为返回 bytes 的可调用对象

    对超时/临时网络错误重试 _MAX_RETRIES 次，每次递增间隔。
    HTTPError（4xx/5xx）不重试（VNDB 明确的拒绝），直接抛出。
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return send()
        except VndbError as e:
            if not _should_retry(e) or attempt >= _MAX_RETRIES:
                raise
            last_exc = e
            time.sleep(_RETRY_BACKOFF * (attempt + 1))
            logger.warning("VNDB 请求超时/网络波动，第 %d 次重试: %s",
                           attempt + 1, e)
    raise last_exc


def _http_post_json(url: str, data: dict) -> dict:
    """POST JSON 请求并返回 JSON 响应"""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )

    def send():
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise VndbError(f"VNDB HTTP {e.code}: {body}") from None
        except urllib.error.URLError as e:
            raise VndbError(f"VNDB 网络错误: {e.reason}") from None

    raw = _request_with_retry(send)
    return json.loads(raw.decode("utf-8"))


def _http_get(url: str) -> bytes:
    """GET 二进制内容（用于下载封面），带超时重试"""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "image/*",
        },
    )

    def send():
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise VndbError(f"下载封面 HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise VndbError(f"下载封面网络错误: {e.reason}") from None

    return _request_with_retry(send)


def _clean_html(text: str) -> str:
    """清理 VNDB 描述中的 HTML 标签（VNDB 返回 [url]...[/url] 等 BBCode 风格）"""
    if not text:
        return ""
    # BBCode 风格：[url=xxx]text[/url] -> text
    text = re.sub(r"\[url=[^\]]*\]([^\[]*)\[/url\]", r"\1", text)
    # 普通链接：[url]xxx[/url] -> xxx
    text = re.sub(r"\[url\]([^\[]*)\[/url\]", r"\1", text)
    # 其他 BBCode 标签全部移除
    text = re.sub(r"\[/?\w+[^\]]*\]", "", text)
    # HTML 实体（&amp; 等）
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # 多余空行
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _parse_vn_item(item: dict) -> dict:
    """将 VNDB 返回的单个 VN 项解析为本模块统一的字段字典"""
    vndb_id = item.get("id", "")
    if vndb_id and not vndb_id.startswith("v"):
        vndb_id = f"v{vndb_id}"

    # 标题优先用 alttitle（日文原名），无则用 title（罗马音）
    title = item.get("alttitle") or item.get("title") or ""

    # 封面 URL
    image = item.get("image") or {}
    cover_url = image.get("url") or ""

    # 评分（VNDB 0-100 → 1-5）
    rating_raw = item.get("rating", 0) or 0
    rating_5 = round(rating_raw / 20)
    if rating_5 < 1:
        rating_5 = 0  # 0 表示未评分

    # 描述（清理 BBCode）
    description = _clean_html(item.get("description") or "")

    # 开发商：VN 端点 developers 字段（所有 role=developer 的 producer）
    developers = item.get("developers") or []
    developer = ", ".join(d.get("name", "") for d in developers if d.get("name"))

    # 发售日
    released = item.get("released") or ""

    # 游戏长度（VNDB v2 直接返回 length_minutes 字段，int 分钟数）
    length_minutes = item.get("length_minutes", 0) or 0

    return {
        "vndb_id": vndb_id,
        "title": title,
        "cover_url": cover_url,
        "rating": rating_5,
        "description": description,
        "developer": developer,
        "released": released,
        "length_minutes": length_minutes,
    }


def search_vn(title: str, count: int = 5) -> List[dict]:
    """搜索视觉小说

    Args:
        title: 搜索关键词（标题或罗马音）
        count: 返回结果数（最多 100）

    Returns:
        候选列表，每项是 _parse_vn_item 返回的字典，按 VNDB 相关度排序。
        失败时返回空列表（不抛异常，由调用方决定如何处理）。
    """
    title = (title or "").strip()
    if not title:
        return []

    # VNDB v2 API：POST /kana/vn，body 是 JSON
    # fields 指定要返回的字段，sort 按搜索相关度排序
    payload = {
        "filters": ["search", "=", title],
        "fields": (
            "id,title,alttitle,image.url,rating,description,"
            "released,length_minutes,developers.name"
        ),
        "sort": "searchrank",
        "results": min(max(count, 1), 100),
    }

    try:
        resp = _http_post_json(f"{_VNDB_API_BASE}/vn", payload)
    except VndbError as e:
        logger.warning("VNDB 搜索失败: title=%s, err=%s", title, e)
        return []

    items = resp.get("results", []) or []
    parsed = []
    for item in items:
        try:
            parsed.append(_parse_vn_item(item))
        except Exception as e:
            logger.warning("VNDB 解析条目失败: %s, %s", item, e)
            continue
    logger.info("VNDB 搜索 '%s' 返回 %d 条结果", title, len(parsed))
    return parsed


def search_first_vn(title: str) -> Optional[dict]:
    """搜索并返回第一个匹配结果（自动选策略用）"""
    results = search_vn(title, count=1)
    return results[0] if results else None


def download_cover(cover_url: str, dest_path: str) -> bool:
    """下载封面图到指定路径

    Args:
        cover_url: VNDB CDN URL（如 https://t.vndb.org/cv/12345/12345.jpg）
        dest_path: 本地保存路径（含扩展名）

    Returns:
        True 下载成功，False 失败（网络错误或写入失败）
    """
    if not cover_url or not dest_path:
        return False

    try:
        data = _http_get(cover_url)
    except VndbError as e:
        logger.warning("下载封面失败: %s, %s", cover_url, e)
        return False

    if not data:
        return False

    # 确保父目录存在
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    except Exception as e:
        logger.warning("创建封面目录失败: %s, %s", dest_path, e)
        return False

    try:
        with open(dest_path, "wb") as f:
            f.write(data)
        # 校验文件确实写入成功
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            return False
        logger.info("封面下载成功: %s -> %s (%d bytes)",
                    cover_url, dest_path, len(data))
        return True
    except Exception as e:
        logger.warning("写入封面失败: %s, %s", dest_path, e)
        return False


def rate_limit_sleep(seconds: float = 1.0):
    """速率限制 sleep（VNDB 推荐间隔 ≥ 1s）"""
    time.sleep(seconds)
