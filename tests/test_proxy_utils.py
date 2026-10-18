"""网络代理配置与连通性探测回归（不发起真实网络请求）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from ui.services.config_service import ConfigService  # noqa: E402
from utils.infra import connectivity, proxy_utils  # noqa: E402


class FakeConfig:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):
        return True


class ProxyUtilsTests(unittest.TestCase):
    def test_normalize_proxy_url(self):
        self.assertEqual(proxy_utils.normalize_proxy_url("127.0.0.1:7897"),
                         "http://127.0.0.1:7897")
        self.assertEqual(proxy_utils.normalize_proxy_url("http://127.0.0.1:7897"),
                         "http://127.0.0.1:7897")
        self.assertEqual(proxy_utils.normalize_proxy_url(""), "")

    def test_reject_unsupported_proxy(self):
        with self.assertRaises(proxy_utils.ProxyConfigError):
            proxy_utils.normalize_proxy_url("socks5://127.0.0.1:7897")
        with self.assertRaises(proxy_utils.ProxyConfigError):
            proxy_utils.normalize_proxy_url("http://")
        with self.assertRaises(proxy_utils.ProxyConfigError):
            proxy_utils.normalize_proxy_url("http://127.0.0.1:7897/path")

    def test_resolve_modes(self):
        self.assertEqual(proxy_utils.resolve_proxies("direct"), {})
        self.assertEqual(
            proxy_utils.resolve_proxies("system", system_proxies={
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            }),
            {"http": "http://127.0.0.1:7890",
             "https": "http://127.0.0.1:7890"},
        )
        self.assertEqual(
            proxy_utils.resolve_proxies(
                "custom", "127.0.0.1:7897", system_proxies={}),
            {"http": "http://127.0.0.1:7897",
             "https": "http://127.0.0.1:7897"},
        )
        with self.assertRaises(proxy_utils.ProxyConfigError):
            proxy_utils.resolve_proxies("custom", "", system_proxies={})

    def test_config_service_validates_custom_proxy(self):
        cfg = FakeConfig()
        service = ConfigService(cfg)
        result = service.save({"network": {
            "proxy_mode": "custom", "proxy_url": "127.0.0.1:7897"}})
        self.assertTrue(result["ok"])
        self.assertEqual(cfg.data["network"]["proxy_url"],
                         "http://127.0.0.1:7897")
        result = service.save({"network": {
            "proxy_mode": "custom", "proxy_url": "socks5://127.0.0.1:7897"}})
        self.assertFalse(result["ok"])

    def test_probe_success(self):
        class Response:
            status = 200

            def read(self, _n=0):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, _req, timeout=0):
                return Response()

        result = connectivity._probe(
            Opener(), "kungal", connectivity._TESTS["kungal"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 200)


if __name__ == "__main__":
    unittest.main()
