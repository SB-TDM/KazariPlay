"""元数据源连通性探测（设置页「测试连接」使用）。"""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request

from utils.infra import proxy_utils

_TIMEOUT = 8
_UA = "KazariPlay/1.0 (+https://github.com/SB-TDM/KazariPlay)"

_TESTS = {
    "vndb": {
        "name": "VNDB",
        "url": "https://api.vndb.org/kana/vn",
        "method": "POST",
        "body": {"filters": ["id", "=", "v17"],
                 "fields": "id,title", "results": 1},
    },
    "bangumi": {
        "name": "Bangumi",
        "url": "https://api.bgm.tv/search/subject/CLANNAD"
               "?type=4&responseGroup=small&max_results=1",
        "method": "GET",
        "body": None,
    },
    "kungal": {
        "name": "Kungal",
        "url": "https://www.kungal.com/api/v1/search/works"
               "?q=CLANNAD&limit=1",
        "method": "GET",
        "body": None,
    },
}


def _probe(opener, source_id: str, spec: dict) -> dict:
    data = None
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    if spec["body"] is not None:
        data = json.dumps(spec["body"]).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        spec["url"], data=data, headers=headers, method=spec["method"])
    started = time.monotonic()
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            resp.read(512)
            code = getattr(resp, "status", 200)
        return {
            "source": source_id,
            "name": spec["name"],
            "ok": True,
            "status": code,
            "ms": int((time.monotonic() - started) * 1000),
            "msg": f"HTTP {code}",
        }
    except urllib.error.HTTPError as e:
        return {
            "source": source_id,
            "name": spec["name"],
            "ok": False,
            "status": e.code,
            "ms": int((time.monotonic() - started) * 1000),
            "msg": f"HTTP {e.code}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "source": source_id,
            "name": spec["name"],
            "ok": False,
            "status": 0,
            "ms": int((time.monotonic() - started) * 1000),
            "msg": str(e)[:160],
        }


def check_metadata_sources(mode: str = "system", proxy_url: str = "") -> dict:
    """并发测试 VNDB / Bangumi / Kungal，返回逐源结果。"""
    try:
        opener = proxy_utils.build_opener(mode, proxy_url)
    except proxy_utils.ProxyConfigError as e:
        return {"ok": False, "msg": str(e), "results": []}

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(_TESTS)) as ex:
        futs = {
            ex.submit(_probe, opener, sid, spec): sid
            for sid, spec in _TESTS.items()
        }
        results = [fut.result() for fut in concurrent.futures.as_completed(futs)]
        order = {sid: i for i, sid in enumerate(_TESTS)}
        results.sort(key=lambda r: order.get(r["source"], 99))
    return {
        "ok": all(r["ok"] for r in results),
        "mode": mode,
        "results": results,
    }
