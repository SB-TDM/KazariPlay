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
    rating        -> rating（0-100，转换为 0-5 半星制）
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
from utils.infra.logger import get_logger
from utils.infra.proxy_utils import get_opener
from utils.infra.rate_limit import rate_limiter, retry_after_seconds
from utils.domain.rating_utils import rating_from_100

logger = get_logger()

# VNDB API 端点
_VNDB_API_BASE = "https://api.vndb.org/kana"
_VNDB_COVER_BASE = "https://t.vndb.org"

_VN_FIELDS = (
    "id,title,alttitle,titles{title,lang,main},aliases,image.url,rating,"
    "description,released,length_minutes,developers.name"
)

# User-Agent（VNDB 要求提供，避免被拒绝）
_USER_AGENT = "KazariPlay/1.0 (https://github.com/KazariPlay)"

# 请求超时（秒）
_REQUEST_TIMEOUT = 15
# 封面下载超时（秒）：t.vndb.org CDN 实测单张可达 15~35s，需给足余量；
# 下载已异步化、不阻塞匹配，故放宽到 90s
_COVER_TIMEOUT = 90
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
                                        "429", "网络错误"))
    return False


def _request_with_retry(send: callable, cancel_event=None, retries=None) -> bytes:
    """带重试的 HTTP 请求：send 为返回 bytes 的可调用对象

    对超时/临时网络错误重试（默认 _MAX_RETRIES 次，可用 retries 覆盖；
    封面下载传 0 表示不重试），每次递增间隔。
    HTTPError（4xx/5xx）不重试（VNDB 明确的拒绝），直接抛出。

    cancel_event 置位时：不再发起新请求；退避等待用可唤醒的 wait，
    取消后立即抛出，不空等。已在途的请求仍按其超时返回（不强制中断）。
    """
    max_retries = _MAX_RETRIES if retries is None else max(0, retries)
    last_exc = None
    for attempt in range(max_retries + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise VndbError("已取消")
        try:
            return send()
        except VndbError as e:
            if not _should_retry(e) or attempt >= max_retries:
                raise
            last_exc = e
            wait_s = _RETRY_BACKOFF * (attempt + 1)
            if cancel_event is not None:
                if cancel_event.wait(wait_s):
                    raise VndbError("已取消")
            else:
                time.sleep(wait_s)
            logger.warning("VNDB 请求超时/网络波动，第 %d 次重试: %s",
                           attempt + 1, e)
    raise last_exc


def _http_post_json(url: str, data: dict, cancel_event=None) -> dict:
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
        rate_limiter.wait("vndb")
        try:
            with get_opener().open(req, timeout=_REQUEST_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rate_limiter.backoff("vndb", retry_after_seconds(e, 30))
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise VndbError(f"VNDB HTTP {e.code}: {body}") from None
        except urllib.error.URLError as e:
            raise VndbError(f"VNDB 网络错误: {e.reason}") from None

    raw = _request_with_retry(send, cancel_event=cancel_event)
    return json.loads(raw.decode("utf-8"))


def _http_get(url: str, cancel_event=None, timeout=None, retries=None, progress_cb=None) -> bytes:
    """GET 二进制内容（用于下载封面），超时/重试可配，支持下载进度回调"""
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
            with get_opener().open(req, timeout=timeout or _REQUEST_TIMEOUT) as resp:
                total = 0
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except Exception:
                    total = 0
                if progress_cb is None or total <= 0:
                    return resp.read()
                # 分块读取并上报进度（0.0~1.0）
                chunks = []
                read = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    read += len(chunk)
                    try:
                        progress_cb(read / total)
                    except Exception:
                        pass
                return b"".join(chunks)
        except urllib.error.HTTPError as e:
            raise VndbError(f"下载封面 HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise VndbError(f"下载封面网络错误: {e.reason}") from None
        except (TimeoutError, OSError) as e:
            # socket 读超时/连接错误（之前未捕获会直接抛出）
            raise VndbError(f"下载封面超时/连接错误: {e}") from None

    return _request_with_retry(send, cancel_event=cancel_event, retries=retries)


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
    alt_title = item.get("title") or ""
    if alt_title == title:
        alt_title = ""

    all_titles = []
    for entry in item.get("titles") or []:
        value = str(entry.get("title") or "").strip()
        if value and value not in all_titles:
            all_titles.append(value)
    aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]

    # 封面 URL
    image = item.get("image") or {}
    cover_url = image.get("url") or ""

    # 评分（VNDB 0-100 → 0-5 半星制）
    rating_5 = rating_from_100(item.get("rating", 0) or 0)

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
        "alt_title": alt_title,
        "all_titles": all_titles,
        "aliases": aliases,
        "cover_url": cover_url,
        "rating": rating_5,
        "description": description,
        "developer": developer,
        "released": released,
        "length_minutes": length_minutes,
    }


def search_vn(title: str, count: int = 5, cancel_event=None) -> List[dict]:
    """搜索视觉小说

    Args:
        title: 搜索关键词（标题或罗马音）
        count: 返回结果数（最多 100）
        cancel_event: threading.Event，置位时不再发起请求（可选）

    Returns:
        候选列表，每项是 _parse_vn_item 返回的字典，按 VNDB 相关度排序。
        失败/取消时返回空列表（不抛异常，由调用方决定如何处理）。
    """
    title = (title or "").strip()
    if not title:
        return []

    # VNDB v2 API：POST /kana/vn，body 是 JSON
    # fields 指定要返回的字段，sort 按搜索相关度排序
    payload = {
        "filters": ["search", "=", title],
        "fields": _VN_FIELDS,
        "sort": "searchrank",
        "results": min(max(count, 1), 100),
    }

    try:
        resp = _http_post_json(f"{_VNDB_API_BASE}/vn", payload, cancel_event=cancel_event)
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


def detail(vn_id: str, cancel_event=None) -> Dict:
    """按 VNDB ID 获取单个条目详情。失败返回空字典。"""
    vn_id = str(vn_id or "").strip()
    if not vn_id:
        return {}
    if not vn_id.lower().startswith("v"):
        vn_id = "v" + vn_id
    payload = {
        "filters": ["id", "=", vn_id],
        "fields": _VN_FIELDS,
        "results": 1,
    }
    try:
        resp = _http_post_json(f"{_VNDB_API_BASE}/vn", payload,
                               cancel_event=cancel_event)
        items = resp.get("results", []) or []
        return _parse_vn_item(items[0]) if items else {}
    except Exception as e:  # noqa: BLE001
        logger.warning("VNDB 详情失败: id=%s, %s", vn_id, e)
        return {}


def details(vn_ids: List[str], cancel_event=None,
            batch_size: int = 50) -> Dict[str, Dict]:
    """按 ID 批量获取 VNDB 详情，返回 {vndb_id: 条目}。"""
    unique = []
    seen = set()
    for raw in vn_ids or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if not value.lower().startswith("v"):
            value = "v" + value
        key = value.lower()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    if not unique:
        return {}

    size = min(max(int(batch_size or 50), 1), 100)
    result: Dict[str, Dict] = {}
    for start in range(0, len(unique), size):
        if cancel_event is not None and cancel_event.is_set():
            break
        batch = unique[start:start + size]
        payload = {
            "filters": (
                ["id", "=", batch[0]] if len(batch) == 1
                else ["or", *[["id", "=", value] for value in batch]]
            ),
            "fields": _VN_FIELDS,
            "results": len(batch),
        }
        try:
            resp = _http_post_json(f"{_VNDB_API_BASE}/vn", payload,
                                   cancel_event=cancel_event)
        except Exception as e:  # noqa: BLE001
            logger.warning("VNDB 批量详情失败: %d 条, %s", len(batch), e)
            continue
        for item in resp.get("results", []) or []:
            try:
                parsed = _parse_vn_item(item)
                result[str(parsed.get("vndb_id") or "").lower()] = parsed
            except Exception as e:  # noqa: BLE001
                logger.warning("VNDB 批量详情解析失败: %s", e)
    return {k: v for k, v in result.items() if k}


def find_release(title: str, edition_tokens: List[str],
                 language_hints: Optional[List[str]] = None,
                 cancel_event=None) -> Dict:
    """按标题查找 VNDB release，用于 FHD/Reflection Blue 等版本。"""
    title = (title or "").strip()
    tokens = [str(t).lower() for t in (edition_tokens or []) if str(t).strip()]
    if not title or not tokens:
        return {}
    payload = {
        "filters": ["search", "=", title],
        "fields": "id,title,released,official,languages{lang,title,mtl},vns{id,title}",
        "results": 20,
    }
    try:
        resp = _http_post_json(f"{_VNDB_API_BASE}/release", payload,
                               cancel_event=cancel_event)
    except Exception as e:  # noqa: BLE001
        logger.warning("VNDB release 搜索失败: %s, %s", title, e)
        return {}
    for item in resp.get("results", []) or []:
        if not item.get("official"):
            continue
        release_title = str(item.get("title") or "")
        if not all(token in release_title.lower() for token in tokens):
            continue
        languages = {
            str(lang.get("lang") or "")
            for lang in (item.get("languages") or [])
            if not lang.get("mtl")
        }
        if language_hints and not (languages & set(language_hints)):
            continue
        vns = item.get("vns") or []
        if not vns:
            continue
        vn = vns[0]
        vn_id = str(vn.get("id") or "").strip()
        if not vn_id:
            continue
        return {
            "release_id": str(item.get("id") or ""),
            "release_title": release_title,
            "released": str(item.get("released") or ""),
            "vndb_id": vn_id,
            "vn_title": str(vn.get("title") or ""),
        }
    return {}


# multi_source 统一调用 client.search(keyword, count=...) 的入口
search = search_vn


def download_cover(cover_url: str, dest_path: str, cancel_event=None,
                   timeout: float = None, retries: int = 0, progress_cb=None) -> bool:
    """下载封面图到指定路径

    Args:
        cover_url: VNDB CDN URL（如 https://t.vndb.org/cv/12345/12345.jpg）
        dest_path: 本地保存路径（含扩展名）
        cancel_event: threading.Event，置位时不再下载（可选）
        timeout: 下载超时秒数（默认 _COVER_TIMEOUT，比 API 搜索短）
        retries: 网络失败重试次数（默认 0：封面失败即跳过，不拖累匹配）

    Returns:
        True 下载成功，False 失败/取消（网络错误或写入失败）
    """
    if not cover_url or not dest_path:
        return False
    if cancel_event is not None and cancel_event.is_set():
        return False
    if timeout is None:
        # 从设置读取封面下载超时（改设置即时生效；缺省回退常量）
        try:
            from utils.infra.config import Config
            timeout = float(Config().get("cover_download.timeout", _COVER_TIMEOUT) or _COVER_TIMEOUT)
        except Exception:
            timeout = _COVER_TIMEOUT

    try:
        data = _http_get(cover_url, cancel_event=cancel_event,
                         timeout=timeout, retries=retries, progress_cb=progress_cb)
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
