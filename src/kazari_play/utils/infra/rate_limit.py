"""按数据源限速的全局请求节流器。"""
import threading
import time
from typing import Dict, Optional

# 与 ReinaManager 的节奏保持一致；1000 个游戏时由这里控制总速率。
_POLICIES: Dict[str, float] = {
    "vndb": 1.6,
    "bgm": 0.25,
    "bangumi": 0.25,
    "kungal": 0.5,
    "ymgal": 0.5,
    "hikarinagi": 0.5,
    "shionlib": 0.5,
}


class SourceRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._next: Dict[str, float] = {}
        self._backoff_until: Dict[str, float] = {}

    def wait(self, source: str) -> None:
        interval = _POLICIES.get(source, 0.5)
        while True:
            with self._lock:
                now = time.monotonic()
                until = max(self._next.get(source, 0.0),
                            self._backoff_until.get(source, 0.0))
                if now >= until:
                    self._next[source] = now + interval
                    return
                delay = min(until - now, 0.25)
            time.sleep(max(delay, 0.01))

    def backoff(self, source: str, seconds: float) -> None:
        with self._lock:
            until = time.monotonic() + max(float(seconds or 0), 0.0)
            self._backoff_until[source] = max(
                self._backoff_until.get(source, 0.0), until)


def retry_after_seconds(error, default: float = 30.0) -> float:
    headers = getattr(error, "headers", None)
    if headers is not None:
        value = headers.get("Retry-After") if hasattr(headers, "get") else None
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            pass
    return max(float(default), 0.0)


rate_limiter = SourceRateLimiter()
