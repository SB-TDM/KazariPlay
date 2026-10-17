"""自动更新核心单测（0 网络：桩网络与假配置，临时目录缓存）

覆盖：版本比较 / 平台映射 / 镜像候选 / SHA256SUMS 解析 / 可信摘要 / 包结构预检 /
检查更新状态机 / 通道切换（超时、低速、记忆通道）/ 就绪缓存（命中、失效、离线、跳过）/
磁盘空间预检 / 下载校验失败。
用法：python tests/test_updater.py
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from utils import updater as U  # noqa: E402


class FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        pass


class FakeResponse:
    def __init__(self, payload: bytes, headers=None):
        self._buf = io.BytesIO(payload)
        self.headers = headers or {}

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


class SlowResponse(FakeResponse):
    """每读一次先延迟，用来触发低速检查"""

    def __init__(self, payload: bytes, delay: float = 0.05, chunk: int = 1024):
        super().__init__(payload)
        self._delay = delay
        self._chunk = chunk

    def read(self, size=-1):
        time.sleep(self._delay)
        n = self._chunk if size in (-1, None) else min(size, self._chunk)
        return self._buf.read(n)


WIN_ASSET = ("KazariPlay-win64.zip",
             "https://github.com/SB-TDM/KazariPlay/releases/download/v1.0.1/KazariPlay-win64.zip",
             1234)
SUMS_ASSET = ("SHA256SUMS.txt",
              "https://github.com/SB-TDM/KazariPlay/releases/download/v1.0.1/SHA256SUMS.txt",
              100)


def win_asset(digest=""):
    name, url, size = WIN_ASSET
    return (name, url, size, digest)


def make_release(tag="v1.0.1", notes="修复若干问题", assets=None):
    items = []
    for spec in (assets or []):
        name, url, size = spec[:3]
        item = {"name": name, "browser_download_url": url, "size": size}
        if len(spec) > 3 and spec[3]:
            item["digest"] = spec[3]
        items.append(item)
    return {
        "tag_name": tag, "body": notes, "published_at": "2026-10-13T00:00:00Z",
        "assets": items,
    }


def make_zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def new_updater(tmp, cfg=None):
    return U.Updater(cfg=cfg if cfg is not None else FakeConfig(), cache_dir=tmp)


def write_ready(cache_dir, payload, tag="v1.0.1", version="1.0.1",
                digest=None, zip_name="KazariPlay-win64.zip"):
    digest = digest or hashlib.sha256(payload).hexdigest()
    with open(os.path.join(cache_dir, zip_name), "wb") as f:
        f.write(payload)
    with open(os.path.join(cache_dir, "ready.json"), "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "version": version, "asset_name": zip_name,
                   "digest": digest, "zip": zip_name, "ts": "2026-10-14T00:00:00"},
                  f, ensure_ascii=False)
    return digest


def zip_payload():
    return make_zip_bytes({"KazariPlay.exe": b"NEW-EXE",
                           "_internal/x.dll": b"dll"})


def test_parse_version():
    assert U.parse_version("1.2.3") == (1, 2, 3, "")
    assert U.parse_version("v1.2.3") == (1, 2, 3, "")
    assert U.parse_version("1.0.0-beta.1") == (1, 0, 0, "beta.1")
    assert U.parse_version("v2.0.0-rc.2+build.5") == (2, 0, 0, "rc.2")
    assert U.parse_version("1.2") is None
    assert U.parse_version("abc") is None
    assert U.parse_version("") is None
    assert U.is_prerelease("1.0.0-beta.1") and not U.is_prerelease("1.0.0")
    print("[版本解析] OK")


def test_is_update_available():
    assert U.is_update_available("1.0.1", "1.0.0")
    assert U.is_update_available("1.1.0", "1.0.9")
    assert U.is_update_available("2.0.0", "1.9.9")
    assert U.is_update_available("1.10.0", "1.9.0")
    assert U.is_update_available("1.0.0", "1.0.0-beta.1")
    assert not U.is_update_available("1.0.0", "1.0.0")
    assert not U.is_update_available("0.9.9", "1.0.0")
    assert not U.is_update_available("1.0.1-beta.1", "1.0.0")
    assert not U.is_update_available("garbage", "1.0.0")
    print("[更新判定] OK")


def test_platform_tag():
    with mock.patch.object(U._platform, "system", return_value="Windows"), \
         mock.patch.object(U._platform, "machine", return_value="AMD64"):
        assert U.platform_tag() == "win64"
    with mock.patch.object(U._platform, "system", return_value="Darwin"), \
         mock.patch.object(U._platform, "machine", return_value="arm64"):
        assert U.platform_tag() == "macos-arm64"
    with mock.patch.object(U._platform, "system", return_value="Haiku"), \
         mock.patch.object(U._platform, "machine", return_value="x"):
        assert U.platform_tag() == ""
    print("[平台映射] OK")


def test_download_candidates():
    url = "https://github.com/a/b/releases/download/v1/x.zip"
    got = U.build_download_candidates(url, ["https://m1.example", "https://m2.example/"])
    assert got == [url, "https://m1.example/" + url, "https://m2.example/" + url]
    other = "https://example.com/x.zip"
    assert U.build_download_candidates(other, ["https://m1.example/"]) == [other]
    assert U.build_download_candidates("", ["https://m1.example/"]) == []
    print("[镜像候选] OK")


def test_sha256sums():
    target = "KazariPlay-win64.zip"
    h = "a" * 64
    text = f"{h}  {target}\r\n{'b' * 64} *other.zip\nbadline\n{'c' * 63}  {target}\n"
    assert U.parse_sha256sums(text, target) == h
    assert U.parse_sha256sums(text, "missing.zip") is None
    assert U.parse_sha256sums(f"{h} *{target}\n", target) == h
    print("[SHA256SUMS 解析] OK")


def test_trusted_digest():
    h = "a" * 64
    assert U.trusted_digest({"digest": f"sha256:{h}"}) == h
    assert U.trusted_digest({"digest": "sha256:" + "A" * 64}) == h
    assert U.trusted_digest({"digest": "md5:" + h}) == ""
    assert U.trusted_digest({"digest": "sha256:123"}) == ""
    assert U.trusted_digest({}) == ""
    assert U.trusted_digest(None) == ""
    print("[可信摘要解析] OK")


def test_sha256_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.bin")
        payload = b"hello-kazari"
        with open(path, "wb") as f:
            f.write(payload)
        assert U.sha256_file(path) == hashlib.sha256(payload).hexdigest()
    print("[文件哈希] OK")


def test_check_available_and_cache():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = FakeConfig()
        up = new_updater(tmp, cfg)
        digest = "sha256:" + "a" * 64
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel) as m:
            st = up.check(force=True)
        assert st["state"] == "available", st
        assert st["latest_version"] == "1.0.1"
        assert st["asset_name"] == "KazariPlay-win64.zip"
        assert cfg.data.get("update.last_check")
        assert os.path.isfile(os.path.join(tmp, "latest.json"))
        cached = up._load_cache(max_age=None)
        assert cached and U.trusted_digest(cached.assets["KazariPlay-win64.zip"]) == "a" * 64
        with mock.patch.object(U, "_http_get_json", side_effect=AssertionError("缓存命中不应请求网络")):
            st2 = up.check(force=False)
        assert st2["state"] == "available"
        print("[检查-有新版+24h缓存+摘要持久化] OK")


def test_check_up_to_date():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(tag="v0.1.0", assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            st = up.check(force=True)
        assert st["state"] == "up_to_date", st
    print("[检查-已是最新] OK")


def test_check_skipped_and_skip_current():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = FakeConfig({"update.skipped_version": "1.0.1"})
        up = new_updater(tmp, cfg)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            st = up.check(force=True)
        assert st["state"] == "skipped", st
        cfg2 = FakeConfig()
        up2 = new_updater(tmp + "-2", cfg2)
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up2.check(force=True)
        st2 = up2.skip_current()
        assert st2["state"] == "skipped"
        assert cfg2.data.get("update.skipped_version") == "1.0.1"
    print("[检查-跳过此版本] OK")


def test_check_asset_missing():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            st = up.check(force=True)
        assert st["state"] == "failed" and "win64" in st["error"], st
    print("[检查-资产缺失] OK")


def test_check_no_releases():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        with mock.patch.object(U, "_http_get_json", return_value={}):
            st = up.check(force=True)
        assert st["state"] == "up_to_date", st
    print("[检查-仓库尚无 Release 视为最新] OK")


def test_check_network_fail_stale_cache():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        cache = os.path.join(tmp, "latest.json")
        old = time.time() - U.CHECK_INTERVAL_SECONDS * 10
        os.utime(cache, (old, old))
        with mock.patch.object(U, "_http_get_json", return_value=None):
            st = up.check(force=True)
        assert st["state"] == "available", st
        up2 = new_updater(tmp + "-2")
        with mock.patch.object(U, "_http_get_json", return_value=None):
            st2 = up2.check(force=True)
        assert st2["state"] == "failed", st2
    print("[检查-网络失败退回过期缓存] OK")


def _run_download(up, fake):
    with mock.patch.object(U, "_open_stream", side_effect=fake):
        assert up.download() is True
        deadline = time.time() + 10
        while time.time() < deadline and up.state()["state"] not in ("ready", "failed"):
            time.sleep(0.02)
    return up.state()


def test_download_success_with_mirror():
    """发布元数据带可信摘要：直连失败 → 切镜像；摘要校验通过并记录记忆通道"""
    payload = zip_payload()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        if url.startswith("https://github.com/"):
            raise OSError("direct blocked（模拟直连失败）")
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        cfg = FakeConfig()
        up = new_updater(tmp, cfg)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert st["offline"] is False
        path = st["downloaded_path"]
        assert os.path.isfile(path)
        assert U.sha256_file(path) == hashlib.sha256(payload).hexdigest()
        assert st["extract_dir"] and os.path.isfile(
            os.path.join(st["extract_dir"], "KazariPlay.exe"))
        assert calls[0].startswith("https://github.com/")
        assert any(u.startswith("https://gh-proxy.com/") for u in calls)
        assert cfg.data.get("update.last_good_lane") == "https://gh-proxy.com/"
        assert os.path.isfile(os.path.join(tmp, "ready.json"))
        leftovers = [n for n in os.listdir(tmp) if n.endswith(".part")]
        assert not leftovers, leftovers
    print("[下载-通道切换+元数据摘要+就绪缓存] OK")


def test_download_direct_sums_fallback():
    """发布元数据无摘要：仅接受官方源直连的 SHA256SUMS；ZIP 仍可走镜像"""
    payload = zip_payload()
    digest = hashlib.sha256(payload).hexdigest()
    sums_text = f"{digest}  KazariPlay-win64.zip\n".encode()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        if url.endswith("SHA256SUMS.txt"):
            if url.startswith("https://github.com/"):
                return FakeResponse(sums_text)
            raise OSError("镜像不得提供校验文件")
        if url.startswith("https://github.com/"):
            raise OSError("direct zip blocked")
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert any(u == SUMS_ASSET[1] for u in calls), calls
    print("[下载-官方源校验文件回退] OK")


def test_download_mirror_sums_not_trusted():
    """无可信摘要且官方源不可达：镜像自报的校验值（即使与包匹配）一律不采信"""
    payload = make_zip_bytes({"KazariPlay.exe": b"EVIL-EXE", "_internal/x.dll": b"evil"})
    digest = hashlib.sha256(payload).hexdigest()
    sums_text = f"{digest}  KazariPlay-win64.zip\n".encode()

    def fake(url, opener=None, timeout=None):
        if url.startswith("https://github.com/"):
            raise OSError("direct blocked")
        if url.endswith("SHA256SUMS.txt"):
            return FakeResponse(sums_text)
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "failed", st
        assert "官方源" in st["error"] or "可信" in st["error"], st
        assert not os.path.isfile(os.path.join(tmp, "KazariPlay-win64.zip"))
    print("[下载-镜像自报校验值拒绝] OK")


def test_download_checksum_mismatch():
    payload = b"corrupted" * 100
    digest = "sha256:" + "0" * 64

    def fake(url, opener=None, timeout=None):
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "failed" and "SHA256" in st["error"], st
        leftovers = [n for n in os.listdir(tmp) if n.endswith(".part")]
        assert not leftovers, leftovers
    print("[下载-校验失败终止] OK")


def test_download_all_candidates_fail():
    def fake(url, opener=None, timeout=None):
        raise OSError("blocked")

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "failed", st
    print("[下载-全候选失败] OK")


def test_low_speed_switch():
    """15s 检查点前已收 <5MiB → 切下一候选（用缩短的常量模拟）"""
    payload = zip_payload()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        if url.startswith("https://github.com/"):
            return SlowResponse(payload, delay=0.03, chunk=1024)
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        with mock.patch.object(U, "LANE_LOW_SPEED_AFTER", 0.02):
            st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert any(u.startswith("https://gh-proxy.com/") for u in calls), calls
    print("[下载-低速切换] OK")


def test_last_good_lane_priority():
    """记忆通道优先于直连"""
    payload = zip_payload()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        cfg = FakeConfig({"update.last_good_lane": "https://gh-proxy.com/"})
        up = new_updater(tmp, cfg)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert calls[0].startswith("https://gh-proxy.com/"), calls
    print("[下载-记忆通道优先] OK")


def test_ready_cache_hit():
    """就绪缓存命中：不联网下载，直接 ready 并重建解压目录"""
    payload = zip_payload()
    digest = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload)
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset("sha256:" + digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel), \
             mock.patch.object(U, "_open_stream", side_effect=AssertionError("不应下载")):
            st = up.check(force=True)
        assert st["state"] == "ready", st
        assert st["offline"] is False
        assert st["extract_dir"] and os.path.isfile(
            os.path.join(st["extract_dir"], "KazariPlay.exe"))
        assert os.path.isfile(os.path.join(tmp, "ready.json"))
    print("[就绪缓存-命中（0 下载）] OK")


def test_ready_cache_digest_change_invalidates():
    payload = zip_payload()
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload, digest="0" * 64)
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset("sha256:" + hashlib.sha256(payload).hexdigest()),
                                   SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            st = up.check(force=True)
        assert st["state"] == "available", st
        assert not os.path.exists(os.path.join(tmp, "ready.json"))
        assert not os.path.isfile(os.path.join(tmp, "KazariPlay-win64.zip"))
    print("[就绪缓存-摘要变化失效] OK")


def test_ready_cache_old_version_invalidates():
    payload = zip_payload()
    digest = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload, version="0.1.0", digest=digest)
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset("sha256:" + digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            st = up.check(force=True)
        assert st["state"] == "available", st
        assert not os.path.exists(os.path.join(tmp, "ready.json"))
    print("[就绪缓存-旧版本残留失效] OK")


def test_offline_ready():
    """检查请求失败且无发布缓存：本地就绪缓存有效时仍可就绪（离线标注）"""
    payload = zip_payload()
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload)
        up = new_updater(tmp)
        with mock.patch.object(U, "_http_get_json", return_value=None):
            st = up.check(force=True)
        assert st["state"] == "ready", st
        assert st["offline"] is True
        assert st["latest_version"] == "1.0.1"
    print("[就绪缓存-离线就绪] OK")


def test_probe_ready():
    """启动本地探测：就绪缓存有效 → ready(offline)；旧版本残留失效"""
    payload = zip_payload()
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        assert up.probe_ready()["state"] == "idle"
        write_ready(tmp, payload)
        with mock.patch.object(U, "_http_get_json", side_effect=AssertionError("不应联网")):
            st = up.probe_ready()
        assert st["state"] == "ready" and st["offline"] is True, st
        assert st["extract_dir"] and os.path.isfile(
            os.path.join(st["extract_dir"], "KazariPlay.exe"))
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload, version="0.1.0")
        up = new_updater(tmp)
        assert up.probe_ready()["state"] == "idle"
        assert not os.path.exists(os.path.join(tmp, "ready.json"))
    print("[就绪缓存-启动本地探测] OK")


def test_skip_deletes_ready():
    payload = zip_payload()
    digest = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        write_ready(tmp, payload, digest=digest)
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset("sha256:" + digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = up.skip_current()
        assert st["state"] == "skipped"
        assert not os.path.exists(os.path.join(tmp, "ready.json"))
        assert not os.path.isfile(os.path.join(tmp, "KazariPlay-win64.zip"))
    print("[就绪缓存-跳过即清理] OK")


def test_download_space_precheck():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        payload = zip_payload()
        rel = make_release(assets=[win_asset("sha256:" + hashlib.sha256(payload).hexdigest()),
                                   SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        with mock.patch.object(U, "ensure_free_space",
                               side_effect=RuntimeError("磁盘空间不足：需要约 260 MB")), \
             mock.patch.object(U, "_open_stream", side_effect=AssertionError("不应开始下载")):
            st = _run_download(up, lambda *a, **k: None)
        assert st["state"] == "failed" and "磁盘空间不足" in st["error"], st
    print("[下载-磁盘空间预检] OK")


def test_resolve_package_root():
    with tempfile.TemporaryDirectory() as tmp:
        ok = os.path.join(tmp, "ok")
        os.makedirs(os.path.join(ok, "_internal"))
        open(os.path.join(ok, "KazariPlay.exe"), "wb").close()
        assert U.resolve_package_root(ok) == ok
        wrapped_root = os.path.join(tmp, "wrapped")
        wrapped = os.path.join(wrapped_root, "KazariPlay")
        os.makedirs(os.path.join(wrapped, "_internal"))
        open(os.path.join(wrapped, "KazariPlay.exe"), "wb").close()
        assert U.resolve_package_root(wrapped_root) == wrapped
        bare = os.path.join(tmp, "bare")
        os.makedirs(bare)
        open(os.path.join(bare, "KazariPlay.exe"), "wb").close()
        try:
            U.resolve_package_root(bare)
            raise AssertionError("缺少 _internal 应被拒绝")
        except RuntimeError as e:
            assert "运行资源" in str(e)
        multi = os.path.join(tmp, "multi")
        os.makedirs(os.path.join(multi, "a"))
        os.makedirs(os.path.join(multi, "b"))
        open(os.path.join(multi, "a", "KazariPlay.exe"), "wb").close()
        try:
            U.resolve_package_root(multi)
            raise AssertionError("多入口应被拒绝")
        except RuntimeError:
            pass
        evil = os.path.join(tmp, "evil")
        os.makedirs(os.path.join(evil, "_internal"))
        os.makedirs(os.path.join(evil, "data"))
        open(os.path.join(evil, "KazariPlay.exe"), "wb").close()
        try:
            U.resolve_package_root(evil)
            raise AssertionError("包内 data 目录应被拒绝")
        except RuntimeError as e:
            assert "用户数据" in str(e)
    print("[包结构-预检与规范化] OK")


def test_download_nested_package_normalized():
    payload = make_zip_bytes({"KazariPlay/KazariPlay.exe": b"NEW-EXE",
                              "KazariPlay/_internal/x.dll": b"dll"})
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    def fake(url, opener=None, timeout=None):
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "ready", st
        extract = st["extract_dir"]
        assert extract.endswith("KazariPlay"), extract
        assert os.path.isfile(os.path.join(extract, "KazariPlay.exe"))
        assert os.path.isdir(os.path.join(extract, "_internal"))
    print("[下载-嵌套包规范化] OK")


def test_download_invalid_structure_fails():
    payload = make_zip_bytes({"KazariPlay.exe": b"NEW-EXE"})
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    def fake(url, opener=None, timeout=None):
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "failed" and "运行资源" in st["error"], st
        assert not st["extract_dir"]
    print("[下载-无效结构拒绝] OK")


def test_extract_package_guard():
    with tempfile.TemporaryDirectory() as tmp:
        evil = os.path.join(tmp, "evil.zip")
        with open(evil, "wb") as f:
            f.write(make_zip_bytes({"../evil.txt": b"x"}))
        try:
            U.extract_package(evil, os.path.join(tmp, "out"))
            raise AssertionError("应拒绝路径穿越条目")
        except RuntimeError:
            pass
        good = os.path.join(tmp, "good.zip")
        with open(good, "wb") as f:
            f.write(make_zip_bytes({"KazariPlay.exe": b"x", "_internal/a.dll": b"y"}))
        dest = os.path.join(tmp, "out2")
        U.extract_package(good, dest)
        assert os.path.isfile(os.path.join(dest, "KazariPlay.exe"))
        assert os.path.isfile(os.path.join(dest, "_internal", "a.dll"))
    print("[解压-路径穿越防护] OK")


def test_cleanup():
    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        part = os.path.join(tmp, "KazariPlay-win64.zip.part")
        with open(part, "wb") as f:
            f.write(b"x")
        up.cleanup()
        assert not os.path.exists(part)
    print("[清理残留] OK")


if __name__ == "__main__":
    test_parse_version()
    test_is_update_available()
    test_platform_tag()
    test_download_candidates()
    test_sha256sums()
    test_trusted_digest()
    test_sha256_file()
    test_check_available_and_cache()
    test_check_up_to_date()
    test_check_skipped_and_skip_current()
    test_check_asset_missing()
    test_check_no_releases()
    test_check_network_fail_stale_cache()
    test_download_success_with_mirror()
    test_download_direct_sums_fallback()
    test_download_mirror_sums_not_trusted()
    test_download_checksum_mismatch()
    test_download_all_candidates_fail()
    test_low_speed_switch()
    test_last_good_lane_priority()
    test_ready_cache_hit()
    test_ready_cache_digest_change_invalidates()
    test_ready_cache_old_version_invalidates()
    test_offline_ready()
    test_probe_ready()
    test_skip_deletes_ready()
    test_download_space_precheck()
    test_resolve_package_root()
    test_download_nested_package_normalized()
    test_download_invalid_structure_fails()
    test_extract_package_guard()
    test_cleanup()
    print("UPDATER TEST PASS")
