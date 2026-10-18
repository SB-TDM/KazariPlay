"""元数据源 Adapter 的最小实现：搜索/详情分离。"""
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from core.metadata import multi_source
from utils.infra.logger import get_logger

logger = get_logger()


@dataclass(frozen=True)
class SourceAdapter:
    key: str
    label: str
    icon: str
    search: Callable
    detail: Optional[Callable] = None


def get_adapter(source_id: str) -> Optional[SourceAdapter]:
    meta = multi_source.SOURCES.get(source_id)
    if not meta or meta.get("client") is None:
        return None
    client = meta["client"]
    return SourceAdapter(
        key=source_id,
        label=str(meta.get("name") or source_id),
        icon=str(meta.get("icon") or ""),
        search=getattr(client, "search", None),
        detail=getattr(client, "detail", None),
    )


def enrich_candidates(group: Dict[str, dict]) -> None:
    """对已选中的来源按 ID 补详情；失败保留搜索候选。"""
    for source_id, candidate in group.items():
        source_key = str(candidate.get("source") or source_id)
        external_id = str(candidate.get("source_id") or "").strip()
        # VNDB 搜索结果已包含锚点所需字段；详情只由 ID 桥接显式调用，
        # 避免普通批量路径每个候选都多一次 VNDB 请求。
        if source_key == "vndb":
            continue
        adapter = get_adapter(source_key)
        if not adapter or not adapter.detail or not external_id:
            continue
        try:
            detail = adapter.detail(external_id)
            if not isinstance(detail, dict):
                continue
            for key, value in detail.items():
                if value not in (None, "", [], {}):
                    candidate[key] = value
        except Exception as e:  # noqa: BLE001
            logger.warning("元数据详情补全失败: source=%s id=%s, %s",
                           source_key, external_id, e)
