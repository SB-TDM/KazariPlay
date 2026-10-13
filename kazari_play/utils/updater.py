"""应用内自动更新核心 — 检查 / 下载（镜像回退）/ SHA256 校验 / 状态机

- 更新源：GitHub releases/latest（公开仓库，未认证 API；结果缓存 24h 到 update_cache/latest.json）
- 资产契约：`KazariPlay-<平台标签>.zip` + `SHA256SUMS.txt`（固定命名，见 docs/dev/AUTO_UPDATE_DESIGN.md）
- 本模块保持平台无关；替换助手（--apply-update）与桥接层在其它模块接线。
- 不新增第三方依赖：HTTP 走 utils.proxy_utils.get_opener（系统代理）；测试注入桩网络。
"""
import hashlib
import json
import os
import platform as _platform
import re
import threading
import time
import urllib.request
from typing import List, Optional

from utils.config import Config
from utils.logger import get_logger
from utils.path_utils import get_app_data_dir
from utils.proxy_utils import get_opener
from version import VERSION as CURRENT_VERSION

logger = get_logger()

GITHUB_REPO = "SB-TDM/KazariPlay"
API_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_SUMS_NAME = "SHA256SUMS.txt"
CHECK_INTERVAL_SECONDS = 24 * 3600
REQUEST_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 64 * 1024
DOWNLOAD_RETRIES = 2          # 候选链整体重试次数（1 次首发 + 2 次重试）
USER_AGENT = "KazariPlay-Updater"

# 镜像前缀候选（best-effort，仅对 github.com 资产 URL 生效）。
# 可用 config `update.mirror_prefixes` 覆盖，避免失效域名锁死旧客户端。
DEFAULT_MIRROR_PREFIXES = ["https://gh-proxy.com/", "https://ghfast.top/"]

_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?(?:\+[0-9A-Za-z.\-]+)?$")


# ---------- 版本比较 ----------

def parse_version(text: str) -> Optional[tuple]:
    """解析版本串 → (major, minor, patch, prerelease)；非法返回 None"""
    m = _VERSION_RE.match((text or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or "")


def is_prerelease(text: str) -> bool:
    """版本串是否带预发布后缀（beta/exp/rc 等）"""
    v = parse_version(text)
    return bool(v and v[3])


def is_update_available(latest: str, current: str) -> bool:
    """latest（正式版）严格新于 current 才视为有更新；latest 带预发布后缀一律不算"""
    lv = parse_version(latest)
    cv = parse_version(current)
    if lv is None or cv is None or lv[3]:
        return False
    if lv[:3] > cv[:3]:
        return True
    if lv[:3] == cv[:3] and cv[3]:
        return True     # 同号：预发布 → 正式版视为可更新
    return False


# ---------- 平台接缝 ----------

def platform_tag() -> str:
    """运行时 → 资产平台标签（当前正式发布仅 win64；其余标签为未来扩展预留）"""
    system = _platform.system().lower()
    machine = _platform.machine().lower()
    if system == "windows":
        return "win64" if machine in ("amd64", "x86_64") else "win32"
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    if system == "linux":
        return "linux-x64"
    return ""


def build_download_candidates(url: str, mirror_prefixes: Optional[List[str]] = None) -> List[str]:
    """直连优先 + 镜像前缀回退（仅 github.com 域名生效；镜像不改变 SHA256 校验）"""
    if not url:
        return []
    out = [url]
    if url.startswith("https://github.com/"):
        for prefix in (mirror_prefixes or []):
            p = (prefix or "").strip()
            if not p:
                continue
            if not p.endswith("/"):
                p += "/"
            out.append(p + url)
    return out


# ---------- 下载辅助 ----------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_sha256sums(text: str, filename: str) -> Optional[str]:
    """从 SHA256SUMS 文本中查文件名对应的 SHA256（兼容 `*filename` 与多空格分隔）"""
    for line in (text or "").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        digest = parts[0].lower()
        name = " ".join(parts[1:]).lstrip("*")
        if len(digest) == 64 and name == filename:
            return digest
    return None


def _http_get_json(url: str, opener=None, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """GET JSON（失败返回 None 并记日志；检查更新走直连，不套镜像）"""
    try:
        op = opener or get_opener()
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        with op.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("检查更新请求失败：%s", e)
        return None


def _open_stream(url: str, opener=None, timeout: int = DOWNLOAD_TIMEOUT):
    """打开流式响应（下载用；调用方负责关闭）"""
    op = opener or get_opener()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return op.open(req, timeout=timeout)


# ---------- 发布信息 ----------

class ReleaseInfo:
    """GitHub Release 的裁剪快照（可序列化进缓存）"""

    __slots__ = ("tag", "version", "notes", "published_at", "assets")

    def __init__(self, data: dict):
        self.tag = str(data.get("tag_name") or "").strip()
        self.version = self.tag[1:] if self.tag.startswith("v") else self.tag
        self.notes = str(data.get("body") or "").strip()
        self.published_at = str(data.get("published_at") or "")
        assets = {}
        for a in data.get("assets") or []:
            name = str(a.get("name") or "")
            url = str(a.get("browser_download_url") or "")
            if name and url:
                assets[name] = {"url": url, "size": int(a.get("size") or 0)}
        self.assets = assets

    def to_cache(self) -> dict:
        return {
            "tag_name": self.tag, "body": self.notes,
            "published_at": self.published_at,
            "assets": [{"name": n, "browser_download_url": v["url"], "size": v["size"]}
                       for n, v in self.assets.items()],
        }

    @classmethod
    def from_cache(cls, data: dict) -> "ReleaseInfo":
        return cls(data if isinstance(data, dict) else {})


# ---------- 状态机 ----------

class Updater:
    """更新状态机（单例由 get_updater() 提供；测试自行实例化）

    状态：idle / checking / up_to_date / available / skipped /
          downloading / ready / failed
    """

    def __init__(self, cfg=None, cache_dir: Optional[str] = None):
        self._cfg = cfg                      # duck-typed：get/set/save；None 时用真实 Config
        self._cache_dir = cache_dir
        self._lock = threading.RLock()
        self._release: Optional[ReleaseInfo] = None
        self._downloaded_path = ""
        self._state = {
            "state": "idle", "error": "",
            "latest_version": "", "notes": "", "published_at": "",
            "asset_name": "", "asset_url": "", "size": 0,
            "percent": 0.0, "downloaded": 0.0, "total": 0.0,
            "speed_mb": 0.0, "eta_seconds": 0,
        }

    # ---------- 配置 / 缓存 ----------

    def _cfg_get(self, key: str, default=None):
        cfg = self._cfg if self._cfg is not None else Config()
        return cfg.get(key, default)

    def _cfg_set(self, key: str, value) -> None:
        try:
            cfg = self._cfg if self._cfg is not None else Config()
            cfg.set(key, value)
            cfg.save()
        except Exception as e:
            logger.debug("更新配置写入失败：%s", e)

    def mirror_prefixes(self) -> List[str]:
        value = self._cfg_get("update.mirror_prefixes", None)
        if isinstance(value, list) and value:
            return [str(v) for v in value if str(v).strip()]
        return list(DEFAULT_MIRROR_PREFIXES)

    def cache_root(self) -> str:
        root = self._cache_dir or os.path.join(get_app_data_dir(), "update_cache")
        os.makedirs(root, exist_ok=True)
        return root

    def _cache_file(self) -> str:
        return os.path.join(self.cache_root(), "latest.json")

    def _load_cache(self, max_age: Optional[int] = CHECK_INTERVAL_SECONDS) -> Optional[ReleaseInfo]:
        try:
            path = self._cache_file()
            if not os.path.isfile(path):
                return None
            if max_age is not None and time.time() - os.path.getmtime(path) > max_age:
                return None
            with open(path, encoding="utf-8") as f:
                return ReleaseInfo.from_cache(json.load(f))
        except Exception:
            return None

    def _save_cache(self, rel: ReleaseInfo) -> None:
        try:
            with open(self._cache_file(), "w", encoding="utf-8") as f:
                json.dump(rel.to_cache(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("更新缓存写入失败：%s", e)

    def cleanup(self, remove_downloaded: bool = False) -> None:
        """清理下载残留（.part 与可选已下载包）；启动自愈调用"""
        try:
            root = self.cache_root()
            for name in os.listdir(root):
                path = os.path.join(root, name)
                if name.endswith(".part") or (remove_downloaded and name == os.path.basename(self._downloaded_path)):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        except Exception:
            pass

    # ---------- 状态 ----------

    def _set(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    def state(self) -> dict:
        with self._lock:
            snap = dict(self._state)
        snap["current_version"] = CURRENT_VERSION
        snap["downloaded_path"] = self._downloaded_path
        snap["skipped_version"] = self._cfg_get("update.skipped_version", "") or ""
        snap["last_check"] = self._cfg_get("update.last_check", "") or ""
        return snap

    # ---------- 检查更新 ----------

    def check(self, force: bool = False, opener=None) -> dict:
        """检查更新（同步，秒级）。24h 内命中缓存且非 force 时不打网络。"""
        with self._lock:
            if self._state["state"] in ("downloading", "ready"):
                return self.state()
            self._set(state="checking", error="")

        rel: Optional[ReleaseInfo] = None if force else self._load_cache()
        if rel is None:
            data = _http_get_json(API_LATEST_URL, opener=opener)
            if data and data.get("tag_name"):
                rel = ReleaseInfo(data)
                self._save_cache(rel)
                self._cfg_set("update.last_check", time.strftime("%Y-%m-%dT%H:%M:%S"))
            else:
                rel = self._load_cache(max_age=None)   # 网络失败时退回过期缓存
                if rel is None:
                    self._set(state="failed", error="无法获取更新信息，请稍后重试")
                    return self.state()

        latest = rel.version
        skipped = str(self._cfg_get("update.skipped_version", "") or "")
        tag = platform_tag()
        asset_name = f"KazariPlay-{tag}.zip" if tag else ""

        if not rel.version or not asset_name:
            self._set(state="failed", error="当前平台不受支持")
            return self.state()
        if not is_update_available(latest, CURRENT_VERSION):
            self._release = rel
            self._set(state="up_to_date", latest_version=latest, notes=rel.notes,
                      published_at=rel.published_at)
            return self.state()
        if skipped == latest:
            self._release = rel
            self._set(state="skipped", latest_version=latest, notes=rel.notes)
            return self.state()
        asset = rel.assets.get(asset_name)
        if not asset:
            self._release = rel
            self._set(state="failed", latest_version=latest,
                      error=f"新版本未提供 {asset_name} 资产")
            return self.state()

        self._release = rel
        self._set(state="available", latest_version=latest, notes=rel.notes,
                  published_at=rel.published_at, asset_name=asset_name,
                  asset_url=asset["url"], size=asset["size"],
                  percent=0.0, downloaded=0.0, total=asset["size"] / 1048576.0)
        return self.state()

    def skip_current(self) -> dict:
        """跳过当前已知的新版本（记入 config，不再提示）"""
        with self._lock:
            latest = self._state.get("latest_version", "")
        if latest:
            self._cfg_set("update.skipped_version", latest)
            self._set(state="skipped")
        return self.state()

    # ---------- 下载 ----------

    def download(self, opener=None) -> bool:
        """启动后台下载（available/failed 且已有发布信息时可调用）；正忙返回 False"""
        with self._lock:
            if self._state["state"] == "downloading":
                return False
            if self._release is None:
                return False
            if self._state["state"] not in ("available", "failed"):
                return False
            self._set(state="downloading", error="", percent=0.0,
                      downloaded=0.0, speed_mb=0.0, eta_seconds=0)
        threading.Thread(target=self._download_worker, args=(opener,),
                         daemon=True, name="update-download").start()
        return True

    def _download_worker(self, opener) -> None:
        try:
            rel = self._release
            tag = platform_tag()
            asset_name = f"KazariPlay-{tag}.zip"
            zip_url = (rel.assets.get(asset_name) or {}).get("url", "")
            sums_url = (rel.assets.get(ASSET_SUMS_NAME) or {}).get("url", "")
            if not zip_url:
                raise RuntimeError("缺少更新包资产")
            if not sums_url:
                raise RuntimeError("缺少校验文件（SHA256SUMS.txt）")

            sums = self._download_bytes(sums_url, opener)
            if sums is None:
                raise RuntimeError("无法获取校验文件")
            expected = parse_sha256sums(sums.decode("utf-8", errors="replace"), asset_name)
            if not expected:
                raise RuntimeError("校验文件中缺少更新包记录")

            dest = os.path.join(self.cache_root(), asset_name)
            part = dest + ".part"
            if os.path.exists(part):
                os.remove(part)
            if not self._download_to_file(zip_url, part, opener):
                raise RuntimeError("下载失败，请重试")

            if sha256_file(part) != expected:
                try:
                    os.remove(part)
                except OSError:
                    pass
                raise RuntimeError("更新包 SHA256 校验失败（可能下载损坏或被篡改）")

            os.replace(part, dest)
            self._downloaded_path = dest
            self._set(state="ready", percent=100.0)
            logger.info("更新包已下载并通过校验：%s", dest)
        except Exception as e:
            logger.warning("更新下载失败：%s", e)
            self._set(state="failed", error=str(e))

    def _download_bytes(self, url: str, opener) -> Optional[bytes]:
        """小文件整体下载（校验文件）；同样走镜像回退链"""
        candidates = build_download_candidates(url, self.mirror_prefixes())
        for attempt in range(DOWNLOAD_RETRIES + 1):
            for candidate in candidates:
                try:
                    with _open_stream(candidate, opener=opener) as resp:
                        return resp.read()
                except Exception:
                    continue
            time.sleep(1.0)
        return None

    def _download_to_file(self, url: str, dest: str, opener) -> bool:
        """带进度的分块下载；直连失败自动尝试镜像候选；整体重试 DOWNLOAD_RETRIES 次"""
        candidates = build_download_candidates(url, self.mirror_prefixes())
        for attempt in range(DOWNLOAD_RETRIES + 1):
            for candidate in candidates:
                if self._download_once(candidate, dest, opener):
                    return True
            time.sleep(1.0)
        return False

    def _download_once(self, url: str, dest: str, opener) -> bool:
        start = time.monotonic()
        try:
            with _open_stream(url, opener=opener) as resp:
                total = 0
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                got = 0
                last_emit = 0.0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        now = time.monotonic()
                        if now - last_emit >= 0.2:
                            last_emit = now
                            self._emit_progress(got, total, now - start)
                self._emit_progress(got, total, time.monotonic() - start)
            return got > 0
        except Exception as e:
            logger.debug("下载候选失败（%s）：%s", url, e)
            return False

    def _emit_progress(self, got: int, total: int, elapsed: float) -> None:
        speed = (got / 1048576.0 / elapsed) if elapsed > 0 else 0.0
        percent = (got * 100.0 / total) if total > 0 else 0.0
        eta = int((total - got) / (got / elapsed)) if (got > 0 and total > got and elapsed > 0) else 0
        self._set(percent=round(percent, 1), downloaded=round(got / 1048576.0, 2),
                  total=round(total / 1048576.0, 2) if total else 0.0,
                  speed_mb=round(speed, 2), eta_seconds=eta)


_updater_instance: Optional[Updater] = None
_updater_lock = threading.Lock()


def get_updater() -> Updater:
    """模块级单例（桥接层使用）"""
    global _updater_instance
    with _updater_lock:
        if _updater_instance is None:
            _updater_instance = Updater()
        return _updater_instance
