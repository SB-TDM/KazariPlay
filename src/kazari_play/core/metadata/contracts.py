"""元数据匹配的回调类型。"""
from typing import Callable, Dict

ProgressCallback = Callable[[str, str, str, str], None]
SourceCallback = Callable[[str, Dict[str, dict]], None]
