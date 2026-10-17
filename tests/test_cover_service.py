"""本地封面服务回归：token、GET/HEAD、缓存头、404、缩略图"""
import io
import os
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from PIL import Image  # noqa: E402
from core.cover_store import CoverStore  # noqa: E402
from ui.cover_service import CoverService  # noqa: E402


class FakeCfg:
    def __init__(self):
        self.d = {}

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value

    def save(self):
        pass


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (10, 120, 220)).save(buf, "JPEG")
    return buf.getvalue()


def main():
    tmp = tempfile.mkdtemp(prefix="kp_cover_service_")
    store = CoverStore(base_dir=os.path.join(tmp, "covers"))
    store.save_bytes("g1", jpeg_bytes())
    service = CoverService(store, token="test-token", port=0, config=FakeCfg())
    assert service.start(), "服务启动失败"
    url = service.cover_url("g1", "1-2")
    assert url and url.startswith("http://127.0.0.1:"), url

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read()
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "image/jpeg"
        assert "immutable" in (resp.headers.get("Cache-Control") or "")
        assert body[:3] == b"\xff\xd8\xff"

    head = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(head, timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b""
        assert resp.headers.get("Content-Type") == "image/jpeg"

    bad_token = url.replace("test-token", "wrong")
    for bad in (bad_token, url.replace("g1", "nosuch")):
        try:
            urllib.request.urlopen(bad, timeout=5)
            raise AssertionError("应返回 404: " + bad)
        except urllib.error.HTTPError as e:
            assert e.code == 404, e.code

    # 缩略图应已生成
    assert os.path.isfile(store.thumb_path("g1"))
    service.stop()
    assert not service.started

    disabled = CoverService(store, token="t", port=0, enabled=False, config=FakeCfg())
    assert not disabled.start()
    cfg = FakeCfg()
    cfg.d["cover_service"] = {"enabled": False}
    cfg_disabled = CoverService(store, token="t", port=0, config=cfg)
    assert not cfg_disabled.start()
    print("COVER SERVICE TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
