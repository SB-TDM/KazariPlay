"""元数据来源配置用例。"""
from typing import List

from core.metadata import multi_source


class MetadataSourceService:
    def list_sources(self) -> List[dict]:
        return multi_source.get_all_sources()

    def save_mixed(self, source_ids: List[str]) -> None:
        multi_source.set_mixed_sources(source_ids)

    def test_connection(self, mode: str = "system",
                        proxy_url: str = "") -> dict:
        from utils.infra.connectivity import check_metadata_sources
        return check_metadata_sources(mode, proxy_url)
