"""自动更新核心单测（0 网络：桩网络与假配置，临时目录缓存）

覆盖：版本比较 / 平台映射 / 镜像候选 / SHA256SUMS 解析 / 可信摘要 /
检查更新状态机（缓存命中 / 无新版 / 有新版 / 跳过 / 资产缺失 / 网络失败退回过期缓存）/
下载（元数据摘要校验 / 官方源校验文件回退 / 镜像自报校验值拒绝 / 校验失败 /
包结构预检与规范化 / 全失败）。
用法：python tests/test_updater.py
"""
import hashlib
import io
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
    assert U.is_update_available("1.10.0", "1.9.0")          # 字符串比较会误判的反例
    assert U.is_update_available("1.0.0", "1.0.0-beta.1")    # 预发布 → 正式版
    assert not U.is_update_available("1.0.0", "1.0.0")
    assert not U.is_update_available("0.9.9", "1.0.0")
    assert not U.is_update_available("1.0.1-beta.1", "1.0.0")  # latest 是预发布不算
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
    assert U.build_download_candidates(url, []) == [url]   # direct_only 场景：只留官方源
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
    assert U.trusted_digest({"digest": "sha256:" + "A" * 64}) == h.upper().lower()
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
        assert "KazariPlay-win64.zip" in st["asset_url"]
        assert cfg.data.get("update.last_check")
        assert os.path.isfile(os.path.join(tmp, "latest.json"))
        # 摘要随缓存持久化（下载阶段用可信摘要校验）
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
        rel = make_release(assets=[SUMS_ASSET])   # 没有 win64 资产
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
            st = up.check(force=True)   # force 绕过新鲜度；网络失败退回过期缓存
        assert st["state"] == "available", st
        # 无缓存且网络失败 → failed
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
    """发布元数据带可信摘要：直连被墙时经镜像下载 ZIP，摘要校验通过"""
    payload = make_zip_bytes({"KazariPlay.exe": b"NEW-EXE", "_internal/x.dll": b"dll"})
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        if url.startswith("https://github.com/"):
            raise OSError("direct blocked（模拟直连失败）")
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[win_asset(digest), SUMS_ASSET])
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert st["percent"] == 100.0
        path = st["downloaded_path"]
        assert os.path.isfile(path)
        assert U.sha256_file(path) == hashlib.sha256(payload).hexdigest()
        extract = st["extract_dir"]
        assert extract and os.path.isfile(os.path.join(extract, "KazariPlay.exe"))
        assert any(u.startswith("https://gh-proxy.com/") for u in calls)
        assert not any(u.endswith("SHA256SUMS.txt") for u in calls), calls   # 有摘要不取校验文件
        leftovers = [n for n in os.listdir(tmp) if n.endswith(".part")]
        assert not leftovers, leftovers
    print("[下载-元数据摘要+镜像传输+校验+解压成功] OK")


def test_download_direct_sums_fallback():
    """发布元数据无摘要：仅接受官方源直连的 SHA256SUMS；ZIP 仍可走镜像"""
    payload = make_zip_bytes({"KazariPlay.exe": b"NEW-EXE", "_internal/x.dll": b"dll"})
    digest = hashlib.sha256(payload).hexdigest()
    sums_text = f"{digest}  KazariPlay-win64.zip\n".encode()
    calls = []

    def fake(url, opener=None, timeout=None):
        calls.append(url)
        if url.endswith("SHA256SUMS.txt"):
            if url.startswith("https://github.com/"):
                return FakeResponse(sums_text)          # 官方直连可用
            raise OSError("镜像不得提供校验文件")
        if url.startswith("https://github.com/"):
            raise OSError("direct zip blocked")
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])   # 无 digest
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        with mock.patch.object(U, "DOWNLOAD_RETRIES", 0):
            st = _run_download(up, fake)
        assert st["state"] == "ready", st
        assert any(u == SUMS_ASSET[1] for u in calls), calls   # 校验文件只走官方直连
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
            return FakeResponse(sums_text)              # 镜像自报（与实际包匹配）
        return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

    with tempfile.TemporaryDirectory() as tmp:
        up = new_updater(tmp)
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])   # 无 digest
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        with mock.patch.object(U, "DOWNLOAD_RETRIES", 0):
            st = _run_download(up, fake)
        assert st["state"] == "failed", st
        assert "官方源" in st["error"] or "可信" in st["error"], st
        assert not os.path.isfile(os.path.join(tmp, "KazariPlay-win64.zip"))
    print("[下载-镜像自报校验值拒绝] OK")


def test_download_checksum_mismatch():
    payload = b"corrupted" * 100
    digest = "sha256:" + "0" * 64   # 与包不符的元数据摘要

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
        rel = make_release(assets=[WIN_ASSET, SUMS_ASSET])   # 无摘要：取校验文件也失败
        with mock.patch.object(U, "_http_get_json", return_value=rel):
            up.check(force=True)
        with mock.patch.object(U, "_open_stream", side_effect=fake), \
             mock.patch.object(U, "DOWNLOAD_RETRIES", 0):
            assert up.download() is True
            deadline = time.time() + 10
            while time.time() < deadline and up.state()["state"] not in ("ready", "failed"):
                time.sleep(0.02)
        st = up.state()
        assert st["state"] == "failed", st
    print("[下载-全候选失败] OK")


def test_resolve_package_root():
    with tempfile.TemporaryDirectory() as tmp:
        # 正常包：程序根在包根
        ok = os.path.join(tmp, "ok")
        os.makedirs(os.path.join(ok, "_internal"))
        open(os.path.join(ok, "KazariPlay.exe"), "wb").close()
        assert U.resolve_package_root(ok) == ok
        # 单层包裹目录：规范化到唯一程序根
        wrapped_root = os.path.join(tmp, "wrapped")
        wrapped = os.path.join(wrapped_root, "KazariPlay")
        os.makedirs(os.path.join(wrapped, "_internal"))
        open(os.path.join(wrapped, "KazariPlay.exe"), "wb").close()
        assert U.resolve_package_root(wrapped_root) == wrapped
        # 缺少 _internal 运行资源
        bare = os.path.join(tmp, "bare")
        os.makedirs(bare)
        open(os.path.join(bare, "KazariPlay.exe"), "wb").close()
        try:
            U.resolve_package_root(bare)
            raise AssertionError("缺少 _internal 应被拒绝")
        except RuntimeError as e:
            assert "运行资源" in str(e)
        # 多入口 / 多层嵌套：拒绝
        multi = os.path.join(tmp, "multi")
        os.makedirs(os.path.join(multi, "a"))
        os.makedirs(os.path.join(multi, "b"))
        open(os.path.join(multi, "a", "KazariPlay.exe"), "wb").close()
        try:
            U.resolve_package_root(multi)
            raise AssertionError("多入口应被拒绝")
        except RuntimeError:
            pass
        # 包内含用户数据目录：拒绝
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
    """兼容旧资产布局：zip 多一层包裹目录时规范化为唯一程序根后进入 ready"""
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
    """结构不符（缺运行资源）的包不得进入 ready"""
    payload = make_zip_bytes({"KazariPlay.exe": b"NEW-EXE"})   # 缺 _internal
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
    test_resolve_package_root()
    test_download_nested_package_normalized()
    test_download_invalid_structure_fails()
    test_extract_package_guard()
    test_cleanup()
    print("UPDATER TEST PASS")
