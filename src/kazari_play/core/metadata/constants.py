"""元数据匹配的共享常量。"""

_SEARCH_DEADLINE = 30.0
_SLOW_SOURCE_SECONDS = 12.0
_CONSENSUS_RATIO = 0.7
_SINGLE_QUERY_RATIO = 0.8
_PICK_BY_TITLE_RATIO = 0.6

_TITLE_DESC_ORDER = ("bangumi", "kungal", "ymgal", "vndb")
_DETAIL_ORDER = ("vndb", "kungal", "ymgal", "bangumi")
_COVER_ORDER = ("vndb", "kungal", "bangumi", "ymgal")
