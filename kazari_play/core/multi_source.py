"""多源元数据搜索 - 统一 VNDB / Bangumi 搜索与封面下载

简化版设计：仅提供 search_metadata / download_cover 两个函数，
不引入抽象基类和聚合器。等出现更多消费者再抽接口。

统一候选字段格式：
    source: "VNDB" | "Bangumi"
    source_id: 数据源中的 ID
    title: 主标题
    alt_title: 别名/原文名
    cover_url: 封面图 URL
    description: 描述
    developer: 开发商
    released: 发售日
    rating: 评分（0-5）
    length_minutes: 预计时长（分钟）
    tags: 标签列表
"""
from typing import List, Optional

from utils import vndb_client, bangumi_client
from utils.logger import get_logger

logger = get_logger()

_SOURCES = ("VNDB", "Bangumi")


def _wrap_vndb(result: dict) -> dict:
    """把 vndb_client._parse_vn_item 的返回包装为统一候选格式"""
    return {
        "source": "VNDB",
        "source_id": result.get("vndb_id", ""),
        "title": result.get("title", ""),
        "alt_title": "",
        "cover_url": result.get("cover_url", ""),
        "description": result.get("description", ""),
        "developer": result.get("developer", ""),
        "released": result.get("released", ""),
        "rating": result.get("rating", 0) or 0,
        "length_minutes": result.get("length_minutes", 0) or 0,
        "tags": [],
    }


def search_metadata(
    keyword: str,
    sources: Optional[List[str]] = None,
    limit_per_source: int = 5,
) -> List[dict]:
    """多源搜索元数据，返回统一候选列表

    Args:
        keyword: 搜索关键词
        sources: 指定数据源列表（None 表示所有已注册源）
        limit_per_source: 每个源返回的最大结果数

    Returns:
        合并后的候选列表（按数据源顺序拼接）
    """
    target = [s for s in (sources or list(_SOURCES)) if s in _SOURCES]
    if not keyword or not keyword.strip():
        return []

    all_candidates: List[dict] = []
    keyword = keyword.strip()

    for source_name in target:
        if source_name == "VNDB":
            try:
                all_candidates.extend(
                    _wrap_vndb(r) for r in vndb_client.search_vn(keyword, count=limit_per_source)
                )
            except Exception as e:
                logger.warning("数据源 VNDB 搜索失败: %s", e)
        elif source_name == "Bangumi":
            try:
                all_candidates.extend(
                    bangumi_client.search_subjects(keyword, limit=limit_per_source)
                )
            except Exception as e:
                logger.warning("数据源 Bangumi 搜索失败: %s", e)

    return all_candidates


def download_cover(candidate: dict, dest_path: str) -> bool:
    """按候选的来源下载封面图到本地

    Args:
        candidate: 统一候选格式字典
        dest_path: 本地保存路径（含扩展名）

    Returns:
        True 下载成功，False 失败
    """
    cover_url = (candidate or {}).get("cover_url", "")
    if not cover_url:
        return False

    source = (candidate or {}).get("source", "")
    if source == "VNDB":
        return vndb_client.download_cover(cover_url, dest_path)
    if source == "Bangumi":
        return bangumi_client.download_cover(cover_url, dest_path)

    # 未知来源：兜底走 Bangumi 的通用下载（仅简单 HTTP GET）
    return bangumi_client.download_cover(cover_url, dest_path)
