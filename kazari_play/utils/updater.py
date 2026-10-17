"""应用内自动更新核心 — 检查 / 下载（通道切换）/ SHA256 校验 / 状态机 / 就绪缓存

- 更新源：GitHub releases/latest（公开仓库，未认证 API；结果缓存 24h 到 update_cache/latest.json）
- 资产契约：`KazariPlay-<平台标签>.zip` + `SHA256SUMS.txt`（固定命名，见 docs/dev/AUTO_UPDATE_DESIGN.md）
- 校验信任：优先使用发布元数据（API）中的 sha256 摘要；否则仅接受官方源直连的
  SHA256SUMS（镜像只承担文件传输）；可信校验值不可得时不降级为信任镜像自报值。
- 下载通道：记忆通道 → 直连 → 镜像；单通道 10s 超时、15s 单次低速检查、1 轮候选链；
  切换静默从零重传（见 docs/dev/AUTO_UPDATE_SPEEDUP_PLAN.md D1/D2）。
- 就绪缓存：校验通过后写 `update_cache/ready.json` 并保留 zip；再次检查命中摘要时可跳过
  下载直接进入 ready；离线（检查失败）时也允许命中并标注（D3）。
- 包结构：进入 ready 前校验解压内容的安装结构（唯一程序根 + `_internal` 运行资源）。
- 本模块保持平台无关；替换助手（--apply-update）与桥接层在其它模块接线。
- 不新增第三方依赖：HTTP 走 utils.proxy_utils.get_opener（系统代理）；测试注入桩网络。
"""
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from typing import Dict, List, Optional, Tuple

from utils.config import Config
from utils.logger import get_logger
from utils.path_utils import get_app_data_dir
from utils.proxy_utils import get_opener
from version import VERSION as CURRENT_VERSION

logger = get_logger()

GITHUB_REPO = "SB-TDM/KazariPlay"
API_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_SUMS_NAME = "SHA256SUMS.txt"
READY_FILE = "ready.json"
CHECK_INTERVAL_SECONDS = 24 * 3600
REQUEST_TIMEOUT = 15
LANE_TIMEOUT = 10                    # 单通道 socket 连接/读超时（秒）
LANE_LOW_SPEED_AFTER = 15.0          # 下载开始后第 N 秒做一次低速检查
LANE_LOW_SPEED_BYTES = 5 * 1024 * 1024   # 该检查点已收字节不足则切换通道
DOWNLOAD_SPACE_REQUIRED = 260 * 1024 * 1024   # 下载前可用空间预检（包 + 解压）
CHUNK_SIZE = 64 * 1024
USER_AGENT = "KazariPlay-Updater"

# 镜像前缀候选（best-effort，仅对 github.com 资产 URL 生效）。
# 可用 config `update.mirror_prefixes` 覆盖，避免失效域名锁死旧客户端。
DEFAULT_MIRROR_PREFIXES = ["https://gh-proxy.com/", "https://ghfast.top/", "https://ghproxy.net/"]

# 更新包禁用区（预检）：程序根目录出现这些条目即拒绝
PACKAGE_FORBIDDEN_DIRS = {"data", "screenshots", "logs"}

_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?(?:\+[0-9A-Za-z.\-]+)?$")

_DIGEST_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class _LaneSwitch(Exception):
    """当前下载通道被主动放弃（低速检查未达标）"""


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


def trusted_digest(asset: dict) -> str:
    """发布元数据（GitHub API）中资产的 sha256 摘要；不可用时返回空串

    摘要来自检查更新时的 API 响应，属可信来源；镜像只承担文件传输，
    不得用镜像自报的校验文本充当校验信任。
    """
    m = _DIGEST_RE.match(str((asset or {}).get("digest") or ""))
    return m.group(1).lower() if m else ""


def resolve_package_root(extract_dir: str) -> str:
    """校验解压内容的安装结构并定位程序根目录（进入 ready 前的结构预检）

    - 根目录直接含 `KazariPlay.exe`，或恰有一层包裹目录（兼容旧资产布局）时
      定位到唯一程序根目录；
    - 程序根必须含 `_internal` 运行资源；含 data/screenshots/logs 的包直接拒绝。
    """
    def _has_app(path: str) -> bool:
        return os.path.isfile(os.path.join(path, "KazariPlay.exe"))

    root = ""
    if _has_app(extract_dir):
        root = extract_dir
    else:
        entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])) \
                and _has_app(os.path.join(extract_dir, entries[0])):
            root = os.path.join(extract_dir, entries[0])
    if not root:
        raise RuntimeError("更新包结构不符（未找到唯一的程序根目录 KazariPlay.exe）")
    if not os.path.isdir(os.path.join(root, "_internal")):
        raise RuntimeError("更新包缺少 _internal 运行资源")
    for name in os.listdir(root):
        if name.lower() in PACKAGE_FORBIDDEN_DIRS:
            raise RuntimeError(f"更新包包含用户数据目录，已拒绝：{name}")
    return root


def extract_package(zip_path: str, dest: str) -> None:
    """解压更新包到 dest（清空重建；拒绝路径穿越条目）"""
    dest_abs = os.path.abspath(dest)
    if os.path.isdir(dest_abs):
        shutil.rmtree(dest_abs, ignore_errors=True)
    os.makedirs(dest_abs, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = os.path.abspath(os.path.join(dest_abs, info.filename))
            if target != dest_abs and not target.startswith(dest_abs + os.sep):
                raise RuntimeError("更新包内路径越界：" + info.filename)
        zf.extractall(dest_abs)


def ensure_free_space(path: str, required: int, action: str) -> None:
    """磁盘空间预检；不足时抛出带明确数字的异常"""
    try:
        free = shutil.disk_usage(path).free
    except Exception:
        return
    if free < required:
        raise RuntimeError(
            f"磁盘空间不足：{action}需要约 {required // (1024 * 1024)} MB，"
            f"当前可用 {free // (1024 * 1024)} MB")


def _http_get_json(url: str, opener=None, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """GET JSON；404（仓库尚无 Release）返回空 dict；其他失败返回 None 并记日志"""
    try:
        op = opener or get_opener()
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        with op.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if getattr(e, "code", 0) == 404:
            return {}
        logger.warning("检查更新请求失败：%s", e)
        return None
    except Exception as e:
        logger.warning("检查更新请求失败：%s", e)
        return None


def _open_stream(url: str, opener=None, timeout: int = LANE_TIMEOUT):
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
                assets[name] = {"url": url, "size": int(a.get("size") or 0),
                                "digest": str(a.get("digest") or "")}
        self.assets = assets

    def to_cache(self) -> dict:
        return {
            "tag_name": self.tag, "body": self.notes,
            "published_at": self.published_at,
            "assets": [{"name": n, "browser_download_url": v["url"], "size": v["size"],
                        "digest": v.get("digest", "")}
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
        self._extract_dir = ""
        self._demoted: set = set()           # 本次会话降权的通道标签
        self._state = {
            "state": "idle", "error": "",
            "latest_version": "", "notes": "", "published_at": "",
            "asset_name": "", "asset_url": "", "size": 0,
            "percent": 0.0, "downloaded": 0.0, "total": 0.0,
            "speed_mb": 0.0, "eta_seconds": 0, "offline": False,
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

    # ---------- 就绪缓存 ----------

    def _ready_path(self) -> str:
        return os.path.join(self.cache_root(), READY_FILE)

    def _read_ready(self) -> Optional[dict]:
        try:
            with open(self._ready_path(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_ready(self, rel: ReleaseInfo, asset_name: str, digest: str, zip_name: str) -> None:
        try:
            path = self._ready_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"tag": rel.tag, "version": rel.version,
                           "asset_name": asset_name, "digest": digest,
                           "zip": zip_name, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logger.warning("就绪缓存写入失败：%s", e)

    def _delete_ready(self) -> None:
        try:
            os.remove(self._ready_path())
        except OSError:
            pass

    def _invalidate_ready(self, remove_zip: bool = True) -> None:
        """丢弃就绪缓存；delete_zip 时同时删除其引用的完整包"""
        ready = self._read_ready() or {}
        if remove_zip:
            name = os.path.basename(str(ready.get("zip") or ""))
            if name:
                try:
                    os.remove(os.path.join(self.cache_root(), name))
                except OSError:
                    pass
        self._delete_ready()

    def _materialize_ready(self, zip_path: str) -> bool:
        """从缓存 zip 重建解压目录并做结构预检；失败返回 False（不误报就绪）"""
        extract_dir = os.path.join(self.cache_root(), "extract")
        try:
            extract_package(zip_path, extract_dir)
            extract_dir = resolve_package_root(extract_dir)
        except Exception as e:
            logger.warning("就绪缓存重水化失败：%s", e)
            shutil.rmtree(os.path.join(self.cache_root(), "extract"), ignore_errors=True)
            return False
        self._downloaded_path = zip_path
        self._extract_dir = extract_dir
        return True

    def _rehydrate_ready(self, rel: ReleaseInfo, asset: dict, network_ok: bool) -> bool:
        """检查更新命中本地就绪缓存：tag/digest 一致且 zip 完好 → 直接 ready"""
        ready = self._read_ready()
        if not ready:
            return False
        tag = str(ready.get("tag") or "")
        version = str(ready.get("version") or "")
        digest = str(ready.get("digest") or "")
        zip_name = os.path.basename(str(ready.get("zip") or ""))
        expected = trusted_digest(asset)
        if not digest or not zip_name or tag != rel.tag or digest != expected:
            self._invalidate_ready(remove_zip=True)
            return False
        if not is_update_available(version, CURRENT_VERSION):
            self._invalidate_ready(remove_zip=True)
            return False
        zip_path = os.path.join(self.cache_root(), zip_name)
        if not os.path.isfile(zip_path):
            self._invalidate_ready()
            return False
        if sha256_file(zip_path) != digest:
            self._invalidate_ready(remove_zip=True)
            return False
        if not self._materialize_ready(zip_path):
            return False
        self._release = rel
        size = int(asset.get("size") or 0)
        self._set(state="ready", error="", latest_version=rel.version, notes=rel.notes,
                  published_at=rel.published_at, asset_name=os.path.basename(zip_name),
                  asset_url=str(asset.get("url") or ""), size=size,
                  percent=100.0, downloaded=size / 1048576.0, total=size / 1048576.0,
                  offline=not network_ok)
        logger.info("命中就绪缓存（%s，offline=%s），跳过下载", rel.tag, not network_ok)
        return True

    def _rehydrate_offline(self) -> bool:
        """检查请求失败且无发布缓存：本地 ready.json 有效则仍可就绪（标注离线）"""
        ready = self._read_ready()
        if not ready:
            return False
        version = str(ready.get("version") or "")
        digest = str(ready.get("digest") or "")
        zip_name = os.path.basename(str(ready.get("zip") or ""))
        if not version or not digest or not zip_name:
            self._invalidate_ready(remove_zip=True)
            return False
        if not is_update_available(version, CURRENT_VERSION):
            self._invalidate_ready(remove_zip=True)
            return False
        zip_path = os.path.join(self.cache_root(), zip_name)
        if not os.path.isfile(zip_path):
            self._invalidate_ready()
            return False
        if sha256_file(zip_path) != digest:
            self._invalidate_ready(remove_zip=True)
            return False
        if not self._materialize_ready(zip_path):
            return False
        size = os.path.getsize(zip_path)
        self._release = None
        self._set(state="ready", error="", latest_version=version, notes="",
                  published_at="", asset_name=os.path.basename(zip_name),
                  asset_url="", size=size, percent=100.0,
                  downloaded=size / 1048576.0, total=size / 1048576.0, offline=True)
        logger.info("离线就绪命中（%s），跳过检查与下载", version)
        return True

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
        snap["extract_dir"] = self._extract_dir
        snap["skipped_version"] = self._cfg_get("update.skipped_version", "") or ""
        snap["last_check"] = self._cfg_get("update.last_check", "") or ""
        return snap

    # ---------- 检查更新 ----------

    def check(self, force: bool = False, opener=None) -> dict:
        """检查更新（同步，秒级）。24h 内命中缓存且非 force 时不打网络。"""
        with self._lock:
            if self._state["state"] in ("downloading", "ready"):
                return self.state()
            self._set(state="checking", error="", offline=False)

        rel: Optional[ReleaseInfo] = None if force else self._load_cache()
        network_ok = rel is not None
        if rel is None:
            data = _http_get_json(API_LATEST_URL, opener=opener)
            if data is not None and not data.get("tag_name"):
                # 仓库尚无 Release（404）：视为已是最新
                self._set(state="up_to_date", error="", latest_version="")
                return self.state()
            if data:
                network_ok = True
                rel = ReleaseInfo(data)
                self._save_cache(rel)
                self._cfg_set("update.last_check", time.strftime("%Y-%m-%dT%H:%M:%S"))
            else:
                rel = self._load_cache(max_age=None)   # 网络失败时退回过期缓存
                if rel is None:
                    # 发布信息不可得：尝试用本地就绪缓存（离线就绪）
                    if self._rehydrate_offline():
                        return self.state()
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
        if self._rehydrate_ready(rel, asset, network_ok):
            return self.state()
        self._set(state="available", latest_version=latest, notes=rel.notes,
                  published_at=rel.published_at, asset_name=asset_name,
                  asset_url=asset["url"], size=asset["size"],
                  percent=0.0, downloaded=0.0, total=asset["size"] / 1048576.0,
                  offline=False)
        return self.state()

    def skip_current(self) -> dict:
        """跳过当前已知的新版本（记入 config，不再提示；同时清掉就绪缓存）"""
        with self._lock:
            latest = self._state.get("latest_version", "")
        if latest:
            self._cfg_set("update.skipped_version", latest)
            self._invalidate_ready(remove_zip=True)
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
            self._extract_dir = ""
            self._set(state="downloading", error="", percent=0.0,
                      downloaded=0.0, speed_mb=0.0, eta_seconds=0, offline=False)
        threading.Thread(target=self._download_worker, args=(opener,),
                         daemon=True, name="update-download").start()
        return True

    def _download_worker(self, opener) -> None:
        try:
            rel = self._release
            tag = platform_tag()
            asset_name = f"KazariPlay-{tag}.zip"
            asset = rel.assets.get(asset_name) or {}
            zip_url = asset.get("url", "")
            sums_url = (rel.assets.get(ASSET_SUMS_NAME) or {}).get("url", "")
            if not zip_url:
                raise RuntimeError("缺少更新包资产")

            # 可信校验值：优先取发布元数据（API）中的 sha256 摘要；不可用时仅接受
            # 官方源直连获取的 SHA256SUMS（镜像只承担文件传输，不参与校验信任）
            expected = trusted_digest(asset)
            if not expected:
                if not sums_url:
                    raise RuntimeError("缺少可信校验值（发布元数据无摘要且无校验文件）")
                sums = self._download_bytes(sums_url, opener, direct_only=True)
                if sums is None:
                    raise RuntimeError("无法从官方源获取校验文件（不接受镜像自报校验值）")
                expected = parse_sha256sums(sums.decode("utf-8", errors="replace"), asset_name)
                if not expected:
                    raise RuntimeError("校验文件中缺少更新包记录")

            ensure_free_space(self.cache_root(), DOWNLOAD_SPACE_REQUIRED, "下载与解压更新包")

            dest = os.path.join(self.cache_root(), asset_name)
            part = dest + ".part"
            if os.path.exists(part):
                os.remove(part)
            lane = self._download_with_lanes(zip_url, part, opener)
            if lane is None:
                raise RuntimeError("下载失败，请重试")

            if sha256_file(part) != expected:
                try:
                    os.remove(part)
                except OSError:
                    pass
                # 校验失败不换通道（fail-closed）；本次会话对该通道降权，但不清记忆
                self._demoted.add(lane)
                raise RuntimeError("更新包 SHA256 校验失败（可能下载损坏或被篡改）")

            os.replace(part, dest)
            extract_dir = os.path.join(self.cache_root(), "extract")
            extract_package(dest, extract_dir)
            extract_dir = resolve_package_root(extract_dir)   # 安装结构预检 + 规范化
            self._downloaded_path = dest
            self._extract_dir = extract_dir
            self._write_ready(rel, asset_name, expected, os.path.basename(dest))
            self._set(state="ready", percent=100.0, offline=False)
            logger.info("更新包已下载、通过校验并解压：%s", dest)
        except Exception as e:
            logger.warning("更新下载失败：%s", e)
            self._set(state="failed", error=str(e))

    def _lanes(self, url: str) -> List[Tuple[str, str]]:
        """候选通道（标签, URL）：记忆通道优先，降权通道置后"""
        lanes: List[Tuple[str, str]] = [("direct", url)]
        if url.startswith("https://github.com/"):
            for prefix in self.mirror_prefixes():
                p = (prefix or "").strip()
                if not p:
                    continue
                if not p.endswith("/"):
                    p += "/"
                lanes.append((p, p + url))
        seen = set()
        unique = []
        for label, lane_url in lanes:
            if label in seen:
                continue
            seen.add(label)
            unique.append((label, lane_url))
        last = str(self._cfg_get("update.last_good_lane", "") or "").strip()

        def rank(item: Tuple[str, str]) -> int:
            label = item[0]
            if label in self._demoted:
                return 2
            if last and label == last:
                return 0
            return 1

        return sorted(unique, key=rank)

    def _download_bytes(self, url: str, opener, direct_only: bool = False) -> Optional[bytes]:
        """小文件整体下载（校验文件）；direct_only=True 时只走官方源直连（不经镜像）"""
        candidates = build_download_candidates(
            url, [] if direct_only else self.mirror_prefixes())
        for candidate in candidates:
            try:
                with _open_stream(candidate, opener=opener) as resp:
                    return resp.read()
            except Exception:
                continue
        return None

    def _download_with_lanes(self, url: str, dest: str, opener) -> Optional[str]:
        """按候选链下载到 dest；成功返回通道标签，全部失败返回 None（1 轮，不整体重试）"""
        started = time.monotonic()
        for label, candidate in self._lanes(url):
            ok, _reason = self._download_lane(label, candidate, dest, opener)
            if not ok:
                self._demoted.add(label)
                try:
                    os.remove(dest)
                except OSError:
                    pass
                continue
            self._cfg_set("update.last_good_lane", label)
            elapsed = time.monotonic() - started
            size = os.path.getsize(dest) if os.path.isfile(dest) else 0
            speed = (size / 1048576.0 / elapsed) if elapsed > 0 else 0.0
            logger.info("下载完成：通道=%s 总耗时=%.1fs 均速=%.2fMB/s 字节=%d",
                        label, elapsed, speed, size)
            return label
        return None

    def _download_lane(self, label: str, url: str, dest: str, opener) -> Tuple[bool, str]:
        """单通道下载：10s 超时、15s 单次低速检查（不足 5MiB 即切）；从零重传"""
        logger.info("下载通道开始：%s", label)
        start = time.monotonic()
        got = 0
        total = 0
        first_byte = 0.0
        checked = False
        last_emit = 0.0
        try:
            with _open_stream(url, opener=opener) as resp:
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                self._emit_progress(0, total, 0.0)
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        if not first_byte:
                            first_byte = time.monotonic() - start
                        f.write(chunk)
                        got += len(chunk)
                        now = time.monotonic()
                        if not checked and now - start >= LANE_LOW_SPEED_AFTER:
                            checked = True
                            if got < LANE_LOW_SPEED_BYTES:
                                raise _LaneSwitch()
                        if now - last_emit >= 0.2:
                            last_emit = now
                            self._emit_progress(got, total, now - start)
                self._emit_progress(got, total, time.monotonic() - start)
            if got <= 0:
                raise RuntimeError("空响应")
            elapsed = time.monotonic() - start
            speed = got / 1048576.0 / elapsed if elapsed > 0 else 0.0
            logger.info("下载通道结束：%s 结果=成功 首字节=%.2fs 耗时=%.1fs 均速=%.2fMB/s 字节=%d",
                        label, first_byte, elapsed, speed, got)
            return True, "ok"
        except _LaneSwitch:
            elapsed = time.monotonic() - start
            logger.info("下载通道结束：%s 结果=低速切换 耗时=%.1fs 字节=%d", label, elapsed, got)
            return False, "low-speed"
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.info("下载通道结束：%s 结果=%s 耗时=%.1fs 字节=%d",
                        label, type(e).__name__, elapsed, got)
            return False, "error"

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
