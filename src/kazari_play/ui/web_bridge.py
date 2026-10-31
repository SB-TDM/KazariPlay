"""WebBridge - pywebview js_api 桥，把后端 GameManager 能力暴露给前端 HTML/JS

- 通过 pywebview.create_window(js_api=WebBridge(...)) 注入，
  JS 侧用 `pywebview.api.method(...)`（Promise）调用
- 数据变化（monitor 退出、扫描完成、封面/截图更新等）统一经 UISync
  （ui/sync.py）合并推送前端，不在本类内直接拼 evaluate_js
- 窗口控制（最小化/最大化/拖拽）也由此桥接
"""
import base64
import concurrent.futures
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import webview

from core.games.game_manager import GameManager
from core.games.game_merge_service import GameMergeService
from core.games.game_model import Game
from core.media.cover_store import CoverStore
from ui.sync import UISync
from ui.services.config_service import ConfigService
from ui.services.metadata_source_service import MetadataSourceService
from ui.services.game_library_service import GameLibraryService
from ui.services.game_edit_service import GameEditService
from ui.services.collection_service import CollectionService
from ui.services.update_service import UpdateService
from ui.services.screenshot_service import ScreenshotService
from utils.infra.config import Config
from utils.infra.path_utils import get_app_data_dir
from utils.infra.logger import get_logger
from utils.update.updater import GITHUB_REPO, get_updater
from version import WINDOW_TITLE

logger = get_logger()


def _write_result(ok: bool, msg: str = "") -> str:
    """写接口统一返回 {ok, msg} JSON：业务失败与桥接失败（Promise reject）分开"""
    return json.dumps({"ok": bool(ok), "msg": "" if ok else msg}, ensure_ascii=False)


_COLLECTION_FIELDS = frozenset({"name", "parent_id", "icon", "color", "sort_order"})
_COLLECTION_TEXT_FIELDS = ("name", "icon", "color")
_COLLECTION_INT_FIELDS = ("parent_id", "sort_order")


def _load_json(raw, expected_type):
    """解析前端传入的 JSON；非法或顶层类型不符时返回 None"""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, expected_type) else None


def _load_str_ids(raw):
    """解析 game_id 数组；非数组或元素不是字符串时返回 None"""
    value = _load_json(raw, list)
    if value is None or not all(isinstance(i, str) for i in value):
        return None
    return value


def _load_int_ids(raw):
    """解析收藏夹 id 数组；非数组或元素不是整数时返回 None"""
    value = _load_json(raw, list)
    if value is None or not all(isinstance(i, int) and not isinstance(i, bool) for i in value):
        return None
    return value


def _is_safe_cover_url(url: str) -> bool:
    """只允许 http(s) 绝对地址：候选数据不得把本地文件或自定义协议交给下载器"""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "resources")

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif"}

# 更新后快速退出（D5）：助手拉起成功后最多 1s 宽限即 os._exit(0)。
# 默认关闭；当 D4 埋点证实 wait_exit 是应用窗口大头后再启用。
UPDATE_FAST_EXIT = False

# ---------- 封面 base64 缓存（LRU，防长期会话内存无界增长）----------
# 封面以 data URI 形式常驻内存（原图 base64 再膨胀 ~33%），无上限缓存
# 会在千库规模下累积数百 MB。这里按「条目数 + 总字节」双上限，超限时
# 淘汰最久未使用的条目（OrderedDict.popitem(last=False)）。
# 线程安全：缓存被桥线程 / UISync / monitor 线程并发读写，_cover_cache_lock 保护。
_MAX_COVER_CACHE_ENTRIES = 128
_MAX_COVER_CACHE_BYTES = 48 * 1024 * 1024   # 总字节上限（base64 字符串长度）
_cover_cache: "OrderedDict[str, str]" = OrderedDict()
_cover_cache_bytes = 0
_cover_cache_lock = threading.Lock()
# 封面读取去重：path -> threading.Event，同一路径同时只算一次（并发读取时合并等待）
_cover_inflight: Dict[str, threading.Event] = {}
_cover_inflight_lock = threading.Lock()
_COVER_INFLIGHT_TIMEOUT = 5.0   # 等待超时（秒），超时后自身重算，防死等
# 封面缩略图生成去重：path -> threading.Lock，同一路径同时只生成一次
_thumb_locks: Dict[str, threading.Lock] = {}
_thumb_locks_guard = threading.Lock()


def _cover_cache_get(path: str) -> Optional[str]:
    """读取封面缓存；命中时标记为最近使用，未命中返回 None"""
    with _cover_cache_lock:
        uri = _cover_cache.get(path)
        if uri is not None:
            _cover_cache.move_to_end(path)
        return uri


def _cover_cache_put(path: str, uri: str) -> None:
    """写入封面缓存并做 LRU 淘汰（超上限时移除最久未用条目）"""
    global _cover_cache_bytes
    with _cover_cache_lock:
        old = _cover_cache.pop(path, None)
        if old is not None:
            _cover_cache_bytes -= len(old)
        _cover_cache[path] = uri
        _cover_cache_bytes += len(uri)
        while (_cover_cache_bytes > _MAX_COVER_CACHE_BYTES
               or len(_cover_cache) > _MAX_COVER_CACHE_ENTRIES) and _cover_cache:
            _, old = _cover_cache.popitem(last=False)
            _cover_cache_bytes -= len(old)


def _cover_cache_invalidate(path: str) -> None:
    """定向失效单条封面缓存（封面变化后只清对应条目，保留其余缓存）"""
    global _cover_cache_bytes
    if not path:
        return
    with _cover_cache_lock:
        old = _cover_cache.pop(path, None)
        if old is not None:
            _cover_cache_bytes -= len(old)


def _cover_cache_clear() -> None:
    """清空缓存（封面更新后调用）"""
    global _cover_cache_bytes
    with _cover_cache_lock:
        _cover_cache.clear()
        _cover_cache_bytes = 0


def _default_cover_path() -> str:
    p = os.path.join(_RESOURCE_DIR, "default_cover.jpg")
    return p if os.path.exists(p) else ""


def _cover_version(g: Game) -> int:
    """封面文件修改时间作为版本号（VNDB 匹配/手动更换后 mtime 变化，
    前端据此判断是否需要重新懒加载封面）。无封面或文件缺失返回 0。"""
    if g.cover_path and os.path.exists(g.cover_path):
        try:
            return int(os.path.getmtime(g.cover_path))
        except Exception:
            return 0
    return 0


# 封面缩略图参数：512px 宽在 200% 高分屏缩放（卡片 154→308、详情封面 240→480 设备像素）
# 下仍清晰；JPEG q85 体积约 60~120KB，base64 后仍远小于原图（VNDB 数百 KB~数 MB）。
_THUMB_WIDTH = 512
_THUMB_QUALITY = 85

# 未使用封面/缩略图清理宽限期（秒）：避免误删正在下载的文件
_COVER_CLEANUP_GRACE = 600


def _cover_thumb_path(path: str) -> str:
    """封面缩略图路径（文件名含 尺寸版本 + 原图 mtime：
    封面更换或缩略图参数调整后自动失效重建，旧文件自然弃用）"""
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        mtime = 0
    digest = hashlib.md5(f"{path}|{mtime}".encode("utf-8")).hexdigest()[:16]
    return os.path.join(get_app_data_dir(), "covers", "thumbs",
                        f"{digest}_w{_THUMB_WIDTH}.jpg")


def _ensure_cover_thumb(path: str) -> str:
    """确保封面缩略图存在并返回其路径；生成失败回退原图路径

    getCover 返回缩略图（512px 宽 JPEG，约 60~120KB）而非原图（VNDB 数百 KB、
    手动封面上限 6MB）：既保证高分屏下的清晰度，又大幅降低 base64 体积与
    桥线程 I/O，消除滚动时封面逐个加载的卡顿与弹入感。
    按 原图路径+mtime 命名落盘，封面更换后自动重建（幂等）。
    并发去重：同一路径首次生成时加锁 + 二次检查，确保只缩放/落盘一次。
    """
    thumb = _cover_thumb_path(path)
    if os.path.exists(thumb):
        return thumb
    # double-checked locking：先取该路径的专用锁，锁内二次检查避免并发重复生成
    with _thumb_locks_guard:
        lock = _thumb_locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _thumb_locks[path] = lock
    with lock:
        if os.path.exists(thumb):
            return thumb
        try:
            from PIL import Image
        except Exception:
            return path
        try:
            os.makedirs(os.path.dirname(thumb), exist_ok=True)
            with Image.open(path) as im:
                im = im.convert("RGB")
                # 按宽度等比缩放（LANCZOS 高质量）；原图已 ≤512 宽则不放大
                w, h = im.size
                if w > _THUMB_WIDTH:
                    im = im.resize(
                        (_THUMB_WIDTH, max(1, int(h * _THUMB_WIDTH / w))),
                        Image.LANCZOS)
                im.save(thumb, "JPEG", quality=_THUMB_QUALITY)
            if os.path.exists(thumb) and os.path.getsize(thumb) > 0:
                return thumb
        except Exception:
            pass
        return path


def _cover_data_uri(path: str, ensure_thumb: bool = True) -> str:
    """封面图 → base64 data URI（服务不可用时的回退通道）

    ensure_thumb=True 时沿用旧的 mtime 缩略图；传 False 时由调用方提供已确定的缩略图/原图。
    """
    if not path or not os.path.exists(path):
        path = _default_cover_path()
    if not path:
        return ""
    src = _ensure_cover_thumb(path) if ensure_thumb else path
    cached = _cover_cache_get(src)
    if cached is not None:
        return cached

    # ---- 去重：登记 in-flight 或等待已有计算 ----
    # 返回 (is_owner, event)：is_owner=True 表示本线程负责计算
    def _claim():
        with _cover_inflight_lock:
            ev = _cover_inflight.get(src)
            if ev is not None:
                return False, ev
            ev = threading.Event()
            _cover_inflight[src] = ev
            return True, ev
    is_owner, inflight_ev = _claim()
    if not is_owner:
        # 已有并发计算：等待其完成，然后读缓存（或超时后自身重算）
        inflight_ev.wait(_COVER_INFLIGHT_TIMEOUT)
        cached = _cover_cache_get(src)
        if cached is not None:
            return cached
        # 等待超时且缓存仍空：尝试接管为计算者（原计算者可能异常/超时）
        is_owner, inflight_ev = _claim()
        if not is_owner:
            # 仍被占用（新一轮计算中），再等一次后放弃
            inflight_ev.wait(_COVER_INFLIGHT_TIMEOUT)
            cached = _cover_cache_get(src)
            return cached or ""

    # ---- 计算（owner）----
    uri = ""
    try:
        with open(src, "rb") as f:
            raw = f.read()
        if len(raw) > 6 * 1024 * 1024:
            uri = ""
        else:
            ext = os.path.splitext(src)[1].lower().lstrip(".")
            mime = _MIME.get(ext, "image/jpeg")
            uri = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        if uri:
            _cover_cache_put(src, uri)
    except Exception:
        uri = ""
    finally:
        # owner 释放 in-flight 并通知等待者
        if is_owner:
            with _cover_inflight_lock:
                _cover_inflight.pop(src, None)
            inflight_ev.set()
    return uri


def _game_dict(g: Game, cover_url: str = "", has_cover: Optional[bool] = None) -> Dict[str, Any]:
    from utils.domain.time_utils import format_play_time, format_relative_time
    return {
        "id": g.id,
        "title": g.title,
        "exe_path": g.exe_path or "",
        "dev": g.developer or "",
        "engine": g.engine or "",
        "rating": g.rating or 0,
        "fav": g.is_favorite,
        "tags": list(g.tags),
        "cat_id": g.category_id or 0,
        "unmatched_reason": getattr(g, "unmatched_reason", "") or "",
        "unmatched_code": getattr(g, "unmatched_code", "") or "",
        "collections": [
            {"id": c.get("id"), "name": c.get("name", ""), "color": c.get("color", "") or "",
             "icon": c.get("icon", "") or ""}
            for c in (g.collections or [])
        ],
        "play_time": g.play_time,
        "last_played": g.last_played or "",
        "released": g.released or "",
        "description": g.description or "",
        "play_time_text": format_play_time(g.play_time),
        "last_text": format_relative_time(g.last_played),
        # 封面走本地 HTTP 服务；服务不可用时为空，前端回退 getCover(base64)
        "cover_url": cover_url,
        "has_cover": bool(g.cover_path and os.path.exists(g.cover_path)) if has_cover is None else bool(has_cover),
        "cover_version": _cover_version(g),
    }


class WebBridge:
    """pywebview js_api 桥（前端通过 pywebview.api.* 调用）"""

    def __init__(self, manager: GameManager, cover_store: Optional[CoverStore] = None,
                 cover_service=None):
        self.manager = manager
        self._cfg = Config()
        self._config_service = ConfigService(self._cfg)
        self._metadata_source_service = MetadataSourceService()
        self._library_service = GameLibraryService(self.manager)
        self._game_edit_service = GameEditService(self.manager)
        self._merge_service = GameMergeService(repository=self.manager.repository)
        self._collection_service = CollectionService(self.manager)
        self._screenshot_service = ScreenshotService()
        self._cover_store = cover_store or CoverStore()
        self._cover_service = cover_service
        self._window = None          # 由 create_window 后绑定
        self._ui = UISync()          # 界面更新总线（全部前端推送经它合并发出）
        self._overlay_client = None  # C++ 游戏内 toast 客户端（懒加载）
        self._drag_anchor = None
        self._maximized = False      # 本地跟踪最大化状态（pywebview 判断可能失效）
        self._hwnd = 0               # 主窗口句柄缓存（_win32_hwnd 命中复用）
        self._batch_ctx = None       # 批量任务进度上下文（matchVndbBatch 设置，getBatchProgress 读取）
        self._scan_cancel = threading.Event()   # 扫描取消信号（cancelScan 置位，scan 循环检查）
        self._vndb_cancel = threading.Event()   # VNDB 匹配取消信号（cancelMatch 置位，match_batch 循环检查）
        self._task_lock = threading.Lock()
        self._task_thread = None
        self._relocate_cancel = None            # 重新定位预览扫描的取消事件
        self._relocate_lock = threading.Lock()  # 同一时间只允许一个预览扫描
        self._scan_preview_lock = threading.Lock()
        self._scan_preview = None               # {"token": int, "items": [{"game", "duplicate"}]}
        self._scan_preview_seq = 0
        # 更新任务占用：重复点击/重试的原子防护（见 AUTO_UPDATE_CODE_REVIEW UPD-REV-04）
        self._update_apply_lock = threading.Lock()
        self._update_apply_claimed = False
        # 封面下载线程池：与匹配解耦，短超时不重试（见 COVER_DOWNLOAD_OPTIMIZATION）
        _cover_workers = max(1, int(self._cfg.get("cover_download.max_concurrent", 4) or 4))
        self._cover_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=_cover_workers, thread_name_prefix="cover")
        self._cover_states = {}          # game_id -> 封面下载进度 0.0~1.0（下载中的）
        self._cover_state_lock = threading.Lock()
        self._cover_generation = {}      # game_id -> 手动换封面代次
        self._cover_cancel = {}          # game_id -> 后台下载取消事件
        try:
            self.manager.monitor.register_callback("on_exit", self._on_game_exit)
            self.manager.monitor.register_callback("on_start", self._on_game_start)
        except Exception as e:
            logger.warning("注册 monitor 回调失败: %s", e)

    def bind_window(self, window):
        self._window = window
        self._ui.bind_window(window)

    def shutdown(self) -> None:
        """窗口关闭前释放后台资源：取消封面下载、关闭线程池、解绑前端推送"""
        try:
            with self._cover_state_lock:
                cancels = list(self._cover_cancel.values())
                self._cover_cancel.clear()
            for cancel in cancels:
                cancel.set()
            self._cover_pool.shutdown(wait=False, cancel_futures=True)
        except Exception as e:
            logger.warning("关闭封面线程池失败: %s", e)
        self._ui.unbind_window()

    # ---------- 数据 ----------
    def _cover_url(self, g: Game) -> str:
        if self._cover_service is None:
            return ""
        path = self._cover_store.find_cover(g.id)
        if not path:
            return ""
        return self._cover_service.cover_url(g.id, self._cover_store.version(path))

    def getGames(self) -> str:
        games = self._library_service.list_games()
        return json.dumps([
            _game_dict(g, self._cover_url(g), bool(self._cover_store.find_cover(g.id)))
            for g in games
        ], ensure_ascii=False)

    def getGame(self, game_id: str) -> str:
        g = self._library_service.get_game(game_id)
        if not g:
            return "{}"
        return json.dumps(
            _game_dict(g, self._cover_url(g), bool(self._cover_store.find_cover(g.id))),
            ensure_ascii=False)

    def getCoverUrl(self, game_id: str) -> str:
        """本地封面服务 URL；服务未启动/无封面时返回空串（前端回退 getCover）"""
        g = self.manager.get_game(game_id)
        return self._cover_url(g) if g else ""

    def getCover(self, game_id: str) -> str:
        """base64 回退通道（封面服务不可用时使用）"""
        g = self.manager.get_game(game_id)
        if not g:
            return ""
        path = self._cover_store.find_cover(g.id)
        if not path:
            return _cover_data_uri("")
        thumb = self._cover_store.ensure_thumb(g.id)
        return _cover_data_uri(thumb or path, ensure_thumb=False)

    def getTags(self) -> str:
        return json.dumps(self.manager.get_all_tags(), ensure_ascii=False)

    def getCategories(self) -> str:
        return json.dumps(self.manager.get_all_categories(), ensure_ascii=False)

    # ---------- 配置 ----------
    def getConfig(self) -> str:
        return json.dumps(self._config_service.get_public_config(), ensure_ascii=False)

    def saveConfigs(self, data_json: str) -> str:
        data = _load_json(data_json, dict)
        if data is None:
            return json.dumps({"ok": False, "msg": "配置参数格式错误"}, ensure_ascii=False)
        result = self._config_service.save(data)
        return json.dumps(result, ensure_ascii=False)

    def resetConfig(self):
        self._config_service.reset()

    def setTheme(self, theme: str):
        """即时持久化主题（主题切换无需点「保存」）。"""
        self._config_service.set_theme(theme)

    def getConfigPath(self) -> str:
        return self._cfg.path

    # ---------- 写操作 ----------
    def toggleFav(self, game_id: str):
        self._library_service.toggle_favorite(game_id)
        self.refresh_delta([game_id])

    def launch(self, game_id: str) -> str:
        ok = self._library_service.launch(game_id)
        logger.info("启动游戏 %s: %s", game_id, ok)
        self.refresh_delta([game_id])
        return json.dumps({"ok": ok}, ensure_ascii=False)

    def openFolder(self, game_id: str):
        game = self.manager.get_game(game_id)
        if not game or not game.exe_path:
            return
        try:
            if os.name == "nt":
                import subprocess
                exe = os.path.normpath(game.exe_path)
                if os.path.exists(exe):
                    subprocess.Popen(["explorer", "/select," + exe])
                else:
                    folder = os.path.dirname(exe)
                    if folder and os.path.isdir(folder):
                        subprocess.Popen(["explorer", folder])
            else:
                import webbrowser
                webbrowser.open(game.folder)
        except Exception as e:
            logger.error("打开目录失败: %s", e)

    def deleteGame(self, game_id: str):
        g = self.manager.get_game(game_id)
        self._library_service.delete_game(game_id)
        if g:
            self._purge_cover_cache(game_id, g.cover_path)
        self._cover_store.delete(game_id)
        self.refresh_delta([game_id])

    def saveGame(self, game_id: str, data_json: str) -> str:
        """前端编辑/添加保存。game_id 为空视为手动添加。"""
        data = json.loads(data_json)
        if self._batch_ctx and self._batch_ctx.get("running"):
            return json.dumps({"ok": False, "msg": "元数据匹配进行中，请完成后再保存"}, ensure_ascii=False)
        result = self._game_edit_service.save(game_id, data)
        if not result["ok"]:
            return json.dumps({"ok": False, "msg": result["msg"]}, ensure_ascii=False)
        added = result.get("added")
        if added is not None:
            if not self._start_task(self._run_vndb_match, ([added],)):
                self.notify('游戏已添加；当前任务结束后可手动匹配元数据')
            self.refresh()
        else:
            logger.info("保存游戏: id=%s", game_id)
            self.refresh_delta([game_id])
        return json.dumps({"ok": True, "msg": ""}, ensure_ascii=False)

    # ---------- 标签 / 分类 ----------
    def addTag(self, name: str, color: str) -> str:
        tag_id = self.manager.add_tag(name, color)
        self.refresh()
        return json.dumps({"id": tag_id, "name": name})

    def deleteTag(self, tag_id: int):
        self.manager.delete_tag(tag_id)
        self.refresh()

    def setGameTags(self, game_id: str, tags_json: str):
        self.manager.set_game_tags(game_id, json.loads(tags_json))
        self.refresh_delta([game_id])

    def addCategory(self, name: str) -> str:
        cat_id = self.manager.add_category(name)
        self.refresh()
        return json.dumps({"id": cat_id, "name": name})

    def deleteCategory(self, cat_id: int):
        self.manager.delete_category(cat_id)
        self.refresh()

    def setGameCategory(self, game_id: str, cat_id: int):
        self.manager.set_game_category(game_id, cat_id)
        self.refresh_delta([game_id])

    # ---------- 批量操作 ----------
    def batchAddTag(self, ids_json: str, tag_id: int):
        self.manager.batch_add_tag(json.loads(ids_json), tag_id)
        self.refresh()

    def batchRemoveTag(self, ids_json: str, tag_id: int):
        self.manager.batch_remove_tag(json.loads(ids_json), tag_id)
        self.refresh()

    def batchMoveCategory(self, ids_json: str, cat_id: int):
        self.manager.batch_set_category(json.loads(ids_json), cat_id)
        self.refresh()

    def batchDelete(self, ids_json: str):
        ids = json.loads(ids_json)
        covers = {gid: self.manager.get_game(gid) for gid in ids}
        if self._library_service.batch_delete(ids):
            for gid in ids:
                game = covers.get(gid)
                self._purge_cover_cache(gid, game.cover_path if game else "")
                self._cover_store.delete(gid)
        self.refresh()

    def _purge_cover_cache(self, game_id: str, cover_path: str) -> None:
        """删除游戏后失效 base64/缩略图缓存，避免残留文件被再次命中"""
        if cover_path:
            _cover_cache_invalidate(cover_path)
        _cover_cache_invalidate(self._cover_store.thumb_path(game_id))

    # ---------- 批量重新定位（路径修正，不重算 id）----------
    def previewRelocate(self, ids_json: str) -> str:
        """选目标根目录，扫描并按 identity 匹配选中游戏，返回预览（不写库）

        返回 {"ok": bool, "msg": str, "items": [{id,title,old_exe,new_exe,status}]}
        status: matched(将更新) / missing(未找到) / conflict(新路径已被其他卡片占用)
        """
        ids = json.loads(ids_json)
        games = [g for g in (self.manager.get_game(i) for i in ids) if g]
        if not games:
            return json.dumps({"ok": False, "msg": "没有可定位的游戏"}, ensure_ascii=False)
        if self._window is None:
            return json.dumps({"ok": False, "msg": ""}, ensure_ascii=False)
        folders = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if isinstance(folders, str):
            folders = [folders]
        folders = [f for f in (folders or []) if f]
        if not folders:
            return json.dumps({"ok": False, "msg": ""}, ensure_ascii=False)
        if not self._relocate_lock.acquire(blocking=False):
            return json.dumps({"ok": False, "msg": "重新定位扫描进行中"}, ensure_ascii=False)
        cancel = threading.Event()
        self._relocate_cancel = cancel
        try:
            # 扫描目标目录，按 identity 建索引（可经 cancelRelocate 取消）
            scanned = self.manager.scanner.scan(folders[0], cancel_event=cancel)
        finally:
            self._relocate_cancel = None
            self._relocate_lock.release()
        if cancel.is_set():
            return json.dumps({"ok": False, "msg": "已取消重新定位扫描"}, ensure_ascii=False)
        by_identity = {}
        for g in scanned:
            if g.identity:
                by_identity.setdefault(g.identity, []).append(g)
        items = []
        for game in games:
            new_exe, status = "", "missing"
            candidates = by_identity.get(game.identity, [])
            matched = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                status = "conflict"
            elif matched:
                occupied = self.manager.repository.get_by_path(matched.exe_path)
                if occupied and occupied.id != game.id:
                    status = "conflict"
                else:
                    status = "matched"
                    new_exe = matched.exe_path
            items.append({
                "id": game.id, "title": game.title,
                "old_exe": game.exe_path, "new_exe": new_exe, "status": status,
            })
        return json.dumps({"ok": True, "items": items}, ensure_ascii=False)

    def cancelRelocate(self) -> bool:
        """取消正在进行的重新定位预览扫描（无进行中任务时返回 False）"""
        cancel = self._relocate_cancel
        if cancel is None:
            return False
        cancel.set()
        return True

    def applyRelocate(self, mapping_json: str) -> str:
        """应用重新定位：mapping=[{id,new_exe}]，仅更新匹配项，id 保持不变"""
        mapping = json.loads(mapping_json)
        updated = 0
        failures = []
        for m in mapping:
            gid = str(m.get("id") or "")
            new_exe = (m.get("new_exe") or "").strip()
            if not gid or not new_exe:
                failures.append({"id": gid, "msg": "路径为空"})
                continue
            game = self.manager.get_game(gid)
            if not game:
                failures.append({"id": gid, "msg": "游戏不存在"})
                continue
            new_exe = os.path.normpath(os.path.abspath(new_exe))
            if not os.path.isfile(new_exe):
                failures.append({"id": gid, "msg": "目标文件不存在"})
                continue
            occupied = self.manager.repository.get_by_path(new_exe)
            if occupied and occupied.id != gid:
                failures.append({"id": gid, "msg": "目标路径已被占用"})
                continue   # 冲突：新路径已被占用，跳过
            if game.launch_exe_path:
                old_folder = os.path.abspath(game.folder)
                override = os.path.abspath(game.launch_exe_path)
                try:
                    internal = os.path.normcase(os.path.commonpath([old_folder, override])) == os.path.normcase(old_folder)
                except ValueError:
                    internal = False
                if internal:
                    override = os.path.join(os.path.dirname(new_exe), os.path.relpath(override, old_folder))
                if not os.path.isfile(override):
                    failures.append({"id": gid, "msg": "自定义启动文件不存在，请先处理启动路径"})
                    continue
                game.launch_exe_path = override
            game.exe_path = os.path.normpath(new_exe)
            game.folder = os.path.dirname(game.exe_path)
            game.identity = self.manager.scanner._make_identity(game.engine, os.path.basename(game.folder))
            if not self.manager.repository.update_game(game):
                failures.append({"id": gid, "msg": "数据库更新失败"})
                continue
            updated += 1
        if updated:
            self.refresh()
        self.notify(f"已重新定位 {updated} 个游戏，失败 {len(failures)} 个")
        return json.dumps({"ok": not failures, "updated": updated, "failures": failures}, ensure_ascii=False)

    # ---------- 收藏夹（V1.0 collections）----------
    def getCollectionsTree(self) -> str:
        """返回树形收藏夹 JSON: [{id,name,icon,color,sort_order,game_count,children:[...]}]"""
        return json.dumps(self._collection_service.tree(), ensure_ascii=False)

    def createCollection(self, name: str, parent_id: int, icon: str, color: str) -> str:
        """新建收藏夹。parent_id=0 表示根节点(分组)"""
        result = self._collection_service.create(name, parent_id, icon, color)
        self.refresh()
        return json.dumps(result, ensure_ascii=False) if result else "{}"

    def updateCollection(self, collection_id: int, data_json: str) -> str:
        """更新收藏夹（name/parent_id/icon/color/sort_order）；返回 {ok, msg}"""
        data = _load_json(data_json, dict)
        if data is None:
            return _write_result(False, "收藏夹参数格式错误")
        unknown = set(data) - _COLLECTION_FIELDS
        if unknown:
            return _write_result(False, "不支持的字段: " + "、".join(sorted(unknown)))
        wrong = [f for f in _COLLECTION_TEXT_FIELDS
                 if data.get(f) is not None and not isinstance(data[f], str)]
        wrong += [f for f in _COLLECTION_INT_FIELDS
                  if data.get(f) is not None and not isinstance(data[f], int)]
        if wrong:
            return _write_result(False, "字段类型错误: " + "、".join(wrong))
        result = self._collection_service.update(collection_id, data)
        self.refresh()
        return _write_result(bool(result), "收藏夹更新失败")

    def deleteCollection(self, collection_id: int) -> str:
        """删除收藏夹（级联删除子分类 + 关联）；返回 {ok, msg}"""
        ok = self._collection_service.delete(collection_id)
        self.refresh()
        return _write_result(ok, "删除收藏夹失败")

    def reorderCollection(self, collection_id: int, new_sort_order: int) -> str:
        """调整收藏夹排序；返回 {ok, msg}"""
        ok = self._collection_service.reorder(collection_id, new_sort_order)
        self.refresh()
        return _write_result(ok, "调整收藏夹排序失败")

    def addGamesToCollection(self, ids_json: str, collection_id: int) -> str:
        """批量添加游戏到收藏夹；返回 {ok, msg}"""
        ids = _load_str_ids(ids_json)
        if ids is None:
            return _write_result(False, "游戏 ID 参数格式错误")
        ok = self._collection_service.add_games(ids, collection_id)
        self.refresh()
        return _write_result(ok, "加入收藏夹失败")

    def removeGamesFromCollection(self, ids_json: str, collection_id: int) -> str:
        """从收藏夹批量移除游戏；返回 {ok, msg}"""
        ids = _load_str_ids(ids_json)
        if ids is None:
            return _write_result(False, "游戏 ID 参数格式错误")
        ok = self._collection_service.remove_games(ids, collection_id)
        self.refresh()
        return _write_result(ok, "移出收藏夹失败")

    def setGameCollections(self, game_id: str, collection_ids_json: str) -> str:
        """设置游戏所属的收藏夹列表（整体替换）；返回 {ok, msg}"""
        ids = _load_int_ids(collection_ids_json)
        if ids is None:
            return _write_result(False, "收藏夹 ID 参数格式错误")
        ok = self._collection_service.set_game_collections(game_id, ids)
        self.refresh_delta([game_id])
        return _write_result(ok, "更新收藏夹归属失败")

    def setCollectionGames(self, collection_id: int, ids_json: str) -> bool:
        """整体替换某收藏夹的游戏列表 + 排序（管理游戏对话框用）"""
        ids = _load_str_ids(ids_json)
        if ids is None:
            return False
        ok = self._collection_service.set_games(collection_id, ids)
        self.refresh()
        return ok

    def getGamesInCollection(self, collection_id: int) -> str:
        """获取收藏夹内的游戏 ID 列表（按 sort_order 排序）"""
        return json.dumps(self._collection_service.game_ids(collection_id),
                          ensure_ascii=False)

    def moveGameInCollection(self, collection_id: int, game_id: str, new_sort_order: int) -> str:
        """调整游戏在收藏夹内的排序；返回 {ok, msg}"""
        ok = self._collection_service.move_game(collection_id, game_id, new_sort_order)
        self.refresh_delta([game_id])
        return _write_result(ok, "调整收藏夹内排序失败")

    def batchMoveToCollection(self, ids_json: str, collection_id: int) -> str:
        """批量移动游戏到收藏夹（替代原 batchMoveCategory）；返回 {ok, msg}"""
        ids = _load_str_ids(ids_json)
        if ids is None:
            return _write_result(False, "游戏 ID 参数格式错误")
        ok = self._collection_service.batch_add(ids, collection_id)
        self.refresh()
        return _write_result(ok, "移动到收藏夹失败")

    def batchRemoveFromCollection(self, ids_json: str, collection_id: int) -> str:
        """批量从收藏夹移除游戏（替代原 batchRemoveTag 的收藏夹用法）；返回 {ok, msg}"""
        ids = _load_str_ids(ids_json)
        if ids is None:
            return _write_result(False, "游戏 ID 参数格式错误")
        ok = self._collection_service.batch_remove(ids, collection_id)
        self.refresh()
        return _write_result(ok, "移出收藏夹失败")

    # ---------- 文件对话框 ----------
    def _start_task(self, target, args=()) -> bool:
        if not self._task_lock.acquire(blocking=False):
            return False
        self._scan_cancel = threading.Event()
        self._vndb_cancel = threading.Event()
        self._batch_ctx = None

        def run():
            try:
                target(*args)
            except Exception as e:
                logger.error('后台任务失败: %s', e)
                self.notify('后台任务失败，请查看日志')
            finally:
                try:
                    retryable = 0
                    if self._batch_ctx is not None:
                        self._batch_ctx['running'] = False
                        retryable = int(self._batch_ctx.get('retryable', 0) or 0)
                    self._ui.invalidate('scan_progress', {'running': False})
                    self._ui.invalidate('batch_progress',
                                        {'running': False, 'retryable': retryable})
                finally:
                    self._task_lock.release()
        try:
            self._task_thread = threading.Thread(target=run, daemon=True)
            self._task_thread.start()
            return True
        except Exception:
            self._task_lock.release()
            raise

    def scanFolder(self) -> str:
        """选择游戏文件夹（支持多选）并后台扫描"""
        if self._window is None:
            return json.dumps({"ok": False, "msg": ""})
        folders = self._window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=True)
        if isinstance(folders, str):
            folders = [folders]
        folders = [f for f in (folders or []) if f]
        if not folders:
            return json.dumps({"ok": False, "msg": ""})
        if not self._start_task(self._do_scan_preview, (folders,)):
            return json.dumps({'ok': False, 'msg': '已有扫描或匹配任务正在运行'}, ensure_ascii=False)
        return json.dumps({"ok": True, "msg": "扫描中..."})

    def cancelScan(self):
        """取消正在进行的扫描（已找到的部分随后在预览弹窗中展示，尚未入库）"""
        self._scan_cancel.set()

    def cancelMatch(self):
        """取消正在进行的 VNDB 批量匹配（已匹配的部分已写回）"""
        self._vndb_cancel.set()

    def _do_scan_preview(self, folders: list):
        """后台扫描多个文件夹，只生成预览，不写库；结果经 UISync 推送确认弹窗"""
        with self._scan_preview_lock:
            self._scan_preview = None
        items = []
        seen_paths = set()
        seen_identities = set()
        duplicates = 0
        cancelled = False
        total_folders = len(folders)
        for idx, folder in enumerate(folders):
            if self._scan_cancel.is_set():
                cancelled = True
                break
            base = os.path.basename(os.path.normpath(folder))

            def _progress(dirs, games, _idx=idx, _base=base):
                self._ui.invalidate("scan_progress", {
                    "running": True,
                    "dirs": dirs, "games": games,
                    "folder": _base,
                    "index": _idx + 1, "total": total_folders,
                })

            scanned = self.manager.scanner.scan(
                folder, progress_cb=_progress, cancel_event=self._scan_cancel)
            for game in scanned:
                path_key = os.path.normcase(os.path.normpath(game.exe_path or ""))
                duplicate = bool(
                    (path_key and path_key in seen_paths)
                    or (game.identity and game.identity in seen_identities)
                    or (game.exe_path and self.manager.repository.get_by_path(game.exe_path))
                    or (game.identity and self.manager.repository.get_by_identity(game.identity))
                )
                if path_key:
                    seen_paths.add(path_key)
                if game.identity:
                    seen_identities.add(game.identity)
                if duplicate:
                    duplicates += 1
                items.append({"game": game, "duplicate": duplicate})
            if self._scan_cancel.is_set():
                cancelled = True
                break

        self._ui.invalidate("scan_progress", {"running": False})
        logger.info("扫描预览完成：%d 个（重复 %d）%s",
                    len(items), duplicates, "（已取消）" if cancelled else "")
        if not items:
            self.notify("扫描已取消，未找到游戏" if cancelled else "扫描完成，未找到游戏")
            if cancelled:
                self.refresh()
            return
        with self._scan_preview_lock:
            self._scan_preview_seq += 1
            token = self._scan_preview_seq
            self._scan_preview = {"token": token, "items": items}
        payload = {
            "token": token,
            "cancelled": cancelled,
            "duplicates": duplicates,
            "items": [{
                "key": i,
                "title": entry["game"].title,
                "exe_path": entry["game"].exe_path,
                "duplicate": entry["duplicate"],
            } for i, entry in enumerate(items)],
        }
        self._ui.invalidate("scan_preview", payload)

    def applyScanPreview(self, token: int, keys_json: str) -> str:
        """导入扫描预览中勾选的游戏（重复项跳过），随后自动开始元数据匹配"""
        keys = _load_int_ids(keys_json)
        if keys is None:
            return json.dumps({"ok": False, "msg": "选择参数格式错误"}, ensure_ascii=False)
        with self._scan_preview_lock:
            preview = self._scan_preview
            if not preview:
                return json.dumps({"ok": False, "msg": "扫描结果已过期，请重新扫描"},
                                  ensure_ascii=False)
            entries = preview["items"]
            if any(k < 0 or k >= len(entries) for k in keys):
                return json.dumps({"ok": False, "msg": "选择参数超出范围"}, ensure_ascii=False)
            if preview["token"] != token:
                return json.dumps({"ok": False, "msg": "扫描结果已过期，请重新扫描"},
                                  ensure_ascii=False)
            self._scan_preview = None
            chosen = []
            seen = set()
            for k in keys:
                if k in seen:
                    continue
                seen.add(k)
                if not entries[k]["duplicate"]:
                    chosen.append(entries[k]["game"])
        added = [game for game in chosen if self.manager.add_game(game)]
        self.refresh()
        if added:
            self.notify(f"已导入 {len(added)} 个游戏，开始元数据匹配…")
            if not self._start_task(lambda: self._run_vndb_match(added)):
                self.notify("当前任务结束后可手动匹配元数据")
        else:
            self.notify("未导入任何游戏")
        return json.dumps({"ok": True, "added": len(added)}, ensure_ascii=False)

    def _run_vndb_match(self, games: list, cancel_event=None):
        """后台批量 VNDB 匹配 + 节流进度提示（在调用线程内执行）"""
        retryable = 0
        cancel_event = cancel_event if cancel_event is not None else self._vndb_cancel
        if games:
            self._batch_ctx = {"type": "vndb", "total": len(games), "done": 0,
                               "phase_done": 0, "phase_total": 0, "running": True}
            # 通知前端启动批量进度条轮询（扫描后自动匹配同样可见）
            self._ui.invalidate("batch_progress", {"running": True, "title": "元数据匹配中"})
        try:
            # 批量重匹配：force=True 刷新旧数据；match_single 内部不覆盖用户评分
            matched, skipped, unmatched, retryable = self.manager.match_vndb_for_games(
                games, force=True, progress_cb=self._vndb_progress,
                cancel_event=cancel_event, cover_cb=self._queue_cover)
            if self._batch_ctx is not None:
                self._batch_ctx["retryable"] = retryable
            # 只增量更新本次匹配的卡片（避免全量重建导致所有封面重新加载/淡入闪烁）；
            # 封面由异步下载完成后各自 reloadCover
            self.refresh_delta([g.id for g in games])
            if cancel_event is not None and cancel_event.is_set():
                self.notify(f"元数据匹配已取消（成功 {matched} / 跳过 {skipped} / 未匹配 {unmatched}）")
            else:
                self.notify(
                    f"元数据匹配完成：成功 {matched} / 跳过 {skipped} / 未匹配 {unmatched}"
                    f" / 待重试 {retryable}")
        except Exception as e:
            logger.error("VNDB 批量匹配异常: %s", e)
        finally:
            if self._batch_ctx is not None:
                self._batch_ctx["running"] = False
            self._ui.invalidate("batch_progress",
                                {"running": False, "retryable": retryable})

    def _vndb_progress(self, game_id: str, title: str, status: str, msg: str):
        ctx = self._batch_ctx
        if ctx is None:
            return
        if status == "anchor":
            ctx["phase"] = msg
            try:
                done, total = msg.rsplit(" ", 1)[-1].split("/", 1)
                ctx["phase_done"] = int(done)
                ctx["phase_total"] = int(total)
            except (TypeError, ValueError):
                pass
            return
        if status == "start":
            ctx["phase"] = ""
            return
        counted = ctx.setdefault("_counted", set())
        if game_id and game_id not in counted:
            counted.add(game_id)
            ctx["done"] = min(ctx.get("done", 0) + 1, ctx.get("total", 1))
        if status == "progress":
            ctx["phase"] = f"已完成 {ctx.get('done', 0)}/{ctx.get('total', 0)}"

    def getBatchProgress(self) -> str:
        """返回当前批量任务进度 JSON（无任务返回 running=false）"""
        ctx = self._batch_ctx
        if not ctx:
            return json.dumps({"running": False, "type": "", "total": 0, "done": 0,
                               "phase_done": 0, "phase_total": 0,
                               "retryable": 0}, ensure_ascii=False)
        return json.dumps({
            "running": bool(ctx.get("running")),
            "type": ctx.get("type", ""),
            "total": ctx.get("total", 0),
            "done": ctx.get("done", 0),
            "phase": ctx.get("phase", ""),
            "phase_done": ctx.get("phase_done", 0),
            "phase_total": ctx.get("phase_total", 0),
            "retryable": ctx.get("retryable", 0),
        }, ensure_ascii=False)

    def selectExe(self) -> str:
        if self._window is None:
            return ""
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("可执行文件 (*.exe)", "所有文件 (*.*)"))
        if isinstance(files, (list, tuple)) and files:
            return files[0]
        return files if isinstance(files, str) else ""

    # ---------- VNDB 匹配（后台线程，VNDB 有限速） ----------
    def matchVndb(self, game_id: str) -> str:
        if not self._start_task(self._do_match, (game_id,)):
            return json.dumps({'ok': False, 'msg': '已有扫描或匹配任务正在运行'}, ensure_ascii=False)
        return json.dumps({"ok": True, "msg": "开始匹配元数据..."})

    def _do_match(self, game_id: str):
        # 单游戏匹配复用批量同款进度条（标题 + 取消），与批量体验一致
        self._vndb_cancel.clear()
        self._batch_ctx = {"type": "vndb", "total": 1, "done": 0, "running": True}
        self._ui.invalidate("batch_progress", {"running": True, "title": "元数据匹配中"})
        try:
            status, msg = self.manager.match_vndb_metadata(
                game_id, force=True, cover_cb=self._queue_cover,
                cancel_event=self._vndb_cancel)
            logger.info("VNDB 匹配 %s: %s %s", game_id, status, msg)
            self._batch_ctx["done"] = 1
            if status == "retryable":
                self._batch_ctx["retryable"] = 1
            if status == "cancelled":
                self.notify(f"元数据匹配已取消：{msg}")
            else:
                self.notify(f"元数据匹配完成：{msg}")
        except Exception as e:
            logger.error("VNDB 匹配异常: %s", e)
        finally:
            if self._batch_ctx is not None:
                self._batch_ctx["running"] = False
            self._ui.invalidate("batch_progress", {"running": False})
        self.refresh_delta([game_id])

    def matchVndbBatch(self, ids_json: str) -> str:
        ids = set(json.loads(ids_json))
        games = [g for g in self.manager.get_all_games() if g.id in ids]
        if not games:
            return json.dumps({'ok': False, 'msg': '没有需要匹配的游戏'}, ensure_ascii=False)
        if not self._start_task(self._do_match_batch, (games,)):
            return json.dumps({'ok': False, 'msg': '已有扫描或匹配任务正在运行'}, ensure_ascii=False)
        return json.dumps({"ok": True, "msg": "开始批量匹配..."})

    def _do_match_batch(self, games: list):
        self._run_vndb_match(games, self._vndb_cancel)
        self.refresh()

    def getUnmatchedInfo(self, game_id: str) -> str:
        record = self.manager.unmatched_repo.get(game_id) or {}
        return json.dumps({
            "reason": record.get("reason") or "",
            "code": record.get("code") or "",
            "candidates": record.get("candidates") or [],
        }, ensure_ascii=False)

    def mergeGames(self, source_id: str, target_id: str) -> str:
        running = self.manager.launcher.current_game_id
        if self.manager.launcher.is_running() and running in (source_id, target_id):
            return json.dumps({"ok": False, "msg": "运行中的游戏不能合并"},
                              ensure_ascii=False)
        result = self._merge_service.merge(source_id, target_id)
        if result.get("ok"):
            self.refresh()
        return json.dumps(result, ensure_ascii=False)

    def dismissUnmatched(self, game_id: str) -> str:
        if not game_id:
            return json.dumps({"ok": False, "msg": "缺少游戏 ID"}, ensure_ascii=False)
        self.manager.unmatched_repo.delete(game_id)
        game = self.manager.get_game(game_id)
        if game:
            game.unmatched_reason = ""
        self.refresh_delta([game_id])
        return json.dumps({"ok": True, "msg": "已移出未匹配区"}, ensure_ascii=False)

    def retryFailedMatches(self) -> str:
        games = self.manager.get_retryable_games()
        if not games:
            return json.dumps({"ok": False, "msg": "没有待重试的游戏"}, ensure_ascii=False)
        if not self._start_task(self._do_match_batch, (games,)):
            return json.dumps({"ok": False, "msg": "当前有扫描或匹配任务正在进行"},
                              ensure_ascii=False)
        return json.dumps({"ok": True, "msg": "开始重试..."}, ensure_ascii=False)

    # ---------- 评分 / 运行状态 ----------
    def setRating(self, game_id: str, rating: float) -> bool:
        if not self._library_service.set_rating(game_id, rating):
            return False
        self.refresh_delta([game_id])
        return True

    def getRunning(self) -> str:
        return self._library_service.running_game_id()

    # ---------- 应用内更新（见 docs/dev/AUTO_UPDATE_DESIGN.md；替换与数据保护在 utils/update/update_apply.py）----------

    def _update_payload(self, payload: dict) -> str:
        """统一更新响应；附带一次性的启动自愈提示（回滚/中断恢复）"""
        notice = getattr(self, "_update_notice", "") or ""
        if notice:
            self._update_notice = ""
            payload["notice"] = notice
        return json.dumps(payload, ensure_ascii=False)

    def set_update_notice(self, text: str) -> None:
        """启动自愈提示（main 在窗口创建前写入，前端首次状态请求时消费）"""
        self._update_notice = text or ""

    def _claim_update_apply(self) -> bool:
        """原子占用更新任务（两个入口共用；检查与置位间无窗口）"""
        with self._update_apply_lock:
            if getattr(self, "_update_applied", False) or self._update_apply_claimed:
                return False
            self._update_apply_claimed = True
            return True

    def _release_update_apply(self) -> None:
        """发起失败时释放占用（成功发起不释放，由进程退出收场）"""
        with self._update_apply_lock:
            self._update_apply_claimed = False

    def updateFrontendReady(self) -> str:
        """前端首屏数据加载成功后的就绪握手（新版首启确认的唯一入口）

        main 侧不再按定时器认定"启动成功"；慢加载 / JS 异常 / 桥未就绪都不会
        触发确认，回滚资源因此保留至真正就绪。
        返回完成提示（如「已更新到 vX」）；无更新时返回空串。
        """
        msg = UpdateService().frontend_ready(get_app_data_dir())
        started = getattr(self, "_start_ts", None)
        if started is not None:
            logger.info("启动耗时：入口→前端就绪=%.2fs", time.monotonic() - started)
        return msg

    def getUpdateState(self) -> str:
        return self._update_payload(UpdateService().state(get_updater()))

    def checkUpdate(self, force: bool = False) -> str:
        return self._update_payload(UpdateService().check(get_updater(), bool(force)))

    def probeReadyUpdate(self) -> str:
        """本地探测就绪缓存（不联网）；启动时用于自动提示「更新包已就绪」"""
        return self._update_payload(
            UpdateService().probe_ready(get_updater(), get_app_data_dir()))

    def downloadUpdate(self) -> str:
        return self._update_payload(UpdateService().download(get_updater()))

    def skipUpdate(self) -> str:
        return self._update_payload(UpdateService().skip(get_updater()))

    def applyUpdate(self) -> str:
        """应用更新：拉起替换助手并退出（唯一入口；不做退出时更新）"""
        try:
            from utils.update import update_apply
            if getattr(self, "_update_applied", False):
                return self._update_payload({"ok": True, "msg": "更新已在进行中…"})
            st = get_updater().state()
            if st.get("state") != "ready":
                return self._update_payload({"ok": False, "msg": "更新包未就绪"})
            extract_dir = st.get("extract_dir") or ""
            if not extract_dir or not os.path.isdir(extract_dir):
                return self._update_payload({"ok": False, "msg": "更新包解压目录缺失，请重新下载"})
            target = update_apply.current_install_dir()
            if not target:
                return self._update_payload({"ok": False, "msg": "当前运行方式不支持自动更新"})
            if not self._claim_update_apply():
                return self._update_payload({"ok": True, "msg": "更新已在进行中…"})
            ok, msg = update_apply.begin_apply(extract_dir, target, get_app_data_dir(), os.getpid())
            if not ok:
                self._release_update_apply()
                return self._update_payload({"ok": False, "msg": msg})
            self._update_applied = True
            win = getattr(self, "_window", None)
            if win is not None:
                win.destroy()
            # D5：快速退出机制（默认关闭；埋点证实 wait_exit 为大头后再启用）
            if UPDATE_FAST_EXIT:
                threading.Timer(1.0, lambda: os._exit(0)).start()
            return self._update_payload({"ok": True, "msg": "正在更新…"})
        except Exception as e:
            self._release_update_apply()
            logger.error("applyUpdate 失败: %s", e)
            return self._update_payload({"ok": False, "msg": str(e)})

    def openReleasePage(self) -> bool:
        try:
            os.startfile(f"https://github.com/{GITHUB_REPO}/releases")
            return True
        except Exception as e:
            logger.warning("打开发布页失败: %s", e)
            return False

    # ---------- 游戏截图（Steam 式）----------
    def updateScreenshotHotkey(self, hotkey: str = "") -> bool:
        """设置里修改截图热键后：写入配置并立即重新注册（无需重启）

        同时写配置保证前后端一致（saveConfigs 是整包保存，这里幂等兜底）。
        注册失败（keyboard 不可用/被拒）返回 False，不影响配置保存。
        """
        hotkey = (hotkey or "").strip()
        if hotkey:
            self._cfg.set("hotkeys.screenshot", hotkey)
            self._cfg.save()
        from utils.system.hotkeys import reconfigure_screenshot_hotkey
        return reconfigure_screenshot_hotkey()

    def takeScreenshot(self, game_id: str) -> str:
        """为指定游戏截图（仅游戏画面）。game_id 为空时归入 _unsorted。返回 JSON。"""
        from core.media import screenshot_service
        pid = self._running_pid()
        path = screenshot_service.take_screenshot(game_id or None, pid=pid)
        if path:
            self.notify("截图已保存")
            self._ui.invalidate("screenshots", game_id or None)
            return json.dumps({"ok": True, "path": path}, ensure_ascii=False)
        return json.dumps({"ok": False, "path": ""}, ensure_ascii=False)

    def takeScreenshotRunning(self) -> str:
        """为当前运行中的游戏截图（热键触发用）。无运行游戏则存 _unsorted。"""
        g = self.manager.get_running_game()
        game_id = g.id if g else None
        from core.media import screenshot_service
        pid = self._running_pid()
        path = screenshot_service.take_screenshot(game_id, pid=pid)
        if path:
            self._push_screenshot_toast(game_id, path, g.title if g else "")
            self._ui.invalidate("screenshots", game_id)
            return json.dumps({"ok": True, "path": path, "game_id": game_id or ""},
                              ensure_ascii=False)
        return json.dumps({"ok": False, "path": "", "game_id": game_id or ""},
                          ensure_ascii=False)

    def _running_pid(self) -> Optional[int]:
        """当前运行游戏进程 PID（无则 None）。

        优先用追踪到的真游戏 pid（launcher.get_game_pid），
        兼容经启动器（SmartSteamEmu 等）拉起的真游戏进程。
        """
        launcher = getattr(self.manager, "launcher", None)
        if launcher:
            return launcher.get_game_pid()
        return None

    def _running_game_hwnd(self) -> int:
        """当前运行游戏主窗口句柄（无则 0）"""
        pid = self._running_pid()
        if not pid:
            return 0
        from core.media import screenshot_service
        return screenshot_service.find_main_window_by_pid(pid)

    def _get_overlay_client(self):
        if self._overlay_client is None:
            from core.platform.overlay_client import OverlayClient
            self._overlay_client = OverlayClient()
        return self._overlay_client

    def _game_window_fullscreen(self, hwnd: int) -> bool:
        """检测游戏窗口是否全屏（rect 覆盖整个屏幕，含无边框全屏）

        独占全屏（exclusive fullscreen）下 Windows 不允许 layered 置顶窗口
        （overlay）覆盖，toast/字幕会不可见；此检测用于提示用户切换窗口化。
        """
        if not hwnd:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            gw = r.right - r.left
            gh = r.bottom - r.top
            return gw >= sw - 2 and gh >= sh - 2   # 允许 2px 容差
        except Exception:
            return False

    def _push_screenshot_toast(self, game_id: str, path: str, title: str):
        """截图成功后：驱动 C++ overlay 在游戏画面内弹 toast（仅游戏窗口，失败静默降级）"""
        hwnd = self._running_game_hwnd()
        if not hwnd:
            return
        try:
            if self._game_window_fullscreen(hwnd):
                # 全屏（尤其独占全屏）下游戏内提示不可见，前端先提示用户
                self.notify("提示：游戏为全屏模式，游戏内截图提示可能不可见，建议切换窗口化")
            client = self._get_overlay_client()
            client.show(hwnd, path or "", title or "")
        except Exception as e:
            logger.warning("游戏内 toast 发送失败: %s", e)

    def getScreenshots(self, game_id: str) -> str:
        """返回某游戏截图列表 JSON（含时间，不含图片内容）"""
        return json.dumps(self._screenshot_service.list(game_id),
                          ensure_ascii=False)

    def getScreenshotThumb(self, game_id: str, filename: str) -> str:
        """返回单张截图的缩略图 base64 data URI。

        截图时已随原图保存缩略图（thumbs/{原图名}_thumb.jpg，统一屏幕分辨率留边）。
        旧截图（无预生成缩略图）按需生成兜底。
        """
        from core.media import screenshot_service
        shots = screenshot_service.get_screenshots(game_id)
        p = ""
        for s in shots:
            if s["file"] == filename:
                p = s["path"]
                break
        if not p or not os.path.exists(p):
            return ""
        thumb = screenshot_service._screenshot_thumb_path(p)
        if not os.path.exists(thumb):
            # 旧截图兜底：按需生成（统一小画布 + 屏幕同比例留边）
            try:
                from PIL import Image
                tw, th = screenshot_service._thumb_canvas_size()
                if tw > 0 and th > 0:
                    with Image.open(p) as im:
                        t = screenshot_service._make_letterbox_thumb(im, tw, th)
                    if t:
                        os.makedirs(os.path.dirname(thumb), exist_ok=True)
                        t.save(thumb, "JPEG", quality=85)
                if not os.path.exists(thumb):
                    return ""
            except Exception:
                return ""
        cached = _cover_cache_get(thumb)
        if cached is not None:
            return cached
        try:
            with open(thumb, "rb") as f:
                raw = f.read()
            if len(raw) > 6 * 1024 * 1024:
                return ""
            uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
            _cover_cache_put(thumb, uri)
            return uri
        except Exception:
            return ""

    def getScreenshotOriginal(self, game_id: str, filename: str) -> str:
        """返回单张截图的原图 base64 data URI（预览占满窗口时显示原图）"""
        return self._screenshot_service.original(game_id, filename)

    def deleteScreenshot(self, game_id: str, filename: str) -> bool:
        ok = self._screenshot_service.delete(game_id, filename)
        if game_id:
            self.refresh_delta([game_id])
        else:
            self.refresh()
        return ok

    def renameScreenshot(self, game_id: str, filename: str, new_name: str) -> bool:
        ok = self._screenshot_service.rename(game_id, filename, new_name)
        if game_id:
            self.refresh_delta([game_id])
        else:
            self.refresh()
        return ok

    def openScreenshotFolder(self, game_id: str, filename: str) -> bool:
        """在资源管理器中定位到截图文件（explorer /select）"""
        return self._screenshot_service.open_folder(game_id, filename)

    def copyScreenshotToClipboard(self, game_id: str, filename: str) -> bool:
        """把截图复制到系统剪贴板"""
        return self._screenshot_service.copy_to_clipboard(game_id, filename)

    # ---------- 封面更换 ----------
    def pickCover(self) -> str:
        if self._window is None:
            return ""
        files = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("图片 (*.jpg;*.jpeg;*.png;*.webp)", "所有文件 (*.*)"))
        path = ""
        if isinstance(files, (list, tuple)) and files:
            path = files[0]
        elif isinstance(files, str):
            path = files
        if not path or not os.path.exists(path):
            return ""
        return json.dumps({"path": path, "preview": _cover_data_uri(path)},
                          ensure_ascii=False)

    def setCover(self, game_id: str, path: str) -> str:
        g = self.manager.get_game(game_id)
        if not g or not path or not os.path.exists(path):
            return json.dumps({"ok": False, "msg": "封面文件不存在"}, ensure_ascii=False)
        try:
            self._invalidate_cover_download(game_id)
            dest = self._cover_store.save_file(game_id, path)
            if not dest:
                return json.dumps({"ok": False, "msg": "封面格式不支持或读取失败"},
                                  ensure_ascii=False)
            if not self.manager.repository.update_cover_path(game_id, dest):
                logger.warning("封面路径写入失败: %s", game_id)
                return json.dumps({"ok": False, "msg": "封面写入失败"}, ensure_ascii=False)
            g.cover_path = dest
            try:
                self._cover_pool.submit(self._cover_store.ensure_thumb, game_id)
            except Exception:
                pass
            self.reloadCover(game_id)   # 只失效该游戏封面缓存并重载该卡
            self.refresh_delta([game_id])
            return json.dumps({"ok": True, "msg": "封面已更新"}, ensure_ascii=False)
        except Exception as e:
            logger.error("更换封面失败: %s", e)
            self.refresh_delta([game_id])
            return json.dumps({"ok": False, "msg": "封面更新失败"}, ensure_ascii=False)

    # ---------- 多源搜索手动匹配（源可自行配置，见 core/metadata/search/multi_source.py）----------
    def searchMetadata(self, keyword: str, sources_json: str = "") -> str:
        """多源搜索元数据；sources_json 为源 id 列表，空则用用户配置的混合源"""
        from core.metadata.search import multi_source
        try:
            sources = None
            if sources_json and sources_json.strip():
                sources = json.loads(sources_json)
            cands = multi_source.search_metadata(keyword, sources=sources,
                                                 limit_per_source=5)
            return json.dumps(cands, ensure_ascii=False)
        except Exception as e:
            logger.error("多源搜索失败: %s", e)
            return json.dumps({"__error": "搜索失败，请稍后重试"}, ensure_ascii=False)

    def getGameSources(self, game_id: str) -> str:
        """返回某游戏的持久化来源记录列表"""
        return json.dumps(self._library_service.source_records(game_id),
                          ensure_ascii=False)

    def getMetadataSources(self) -> str:
        """返回全部元数据源（id/名称/favicon/状态/是否启用），供设置页与工具栏展示"""
        return json.dumps(self._metadata_source_service.list_sources(), ensure_ascii=False)

    def testMetadataConnection(self, payload_json: str = "") -> str:
        """测试 VNDB/Bangumi/Kungal 在当前代理配置下是否可访问。"""
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        mode = str(payload.get("mode") or "system").strip().lower()
        proxy_url = str(payload.get("proxy_url") or "").strip()
        result = self._metadata_source_service.test_connection(mode, proxy_url)
        return json.dumps(result, ensure_ascii=False)

    def saveMetadataSources(self, sources_json: str):
        """保存用户勾选的混合检索源（写 config，即时生效）。
        保存提示统一由前端 settings.save() 弹出（“设置已保存”），避免双 toast 互相覆盖。
        """
        self._metadata_source_service.save_mixed(json.loads(sources_json))

    def applyCandidate(self, game_id: str, candidate_json: str, fields_json: str = ""):
        """应用多源候选元数据。

        fields_json：勾选要应用的字段 JSON 数组（如 ["title","cover"]）；
          仅这些字段被覆盖。为空字符串时退回旧行为（仅填充空白字段）。
        封面改为入队后台下载，不阻塞本次桥接请求；下载完成后定向刷新该卡。
        """
        cand = _load_json(candidate_json, dict)
        g = self.manager.get_game(game_id)
        if not g or not cand:
            return json.dumps({"ok": False, "msg": "找不到游戏或候选数据", "changed": False}, ensure_ascii=False)
        selected = None
        if fields_json and fields_json.strip():
            raw_fields = _load_json(fields_json, list)
            if raw_fields is None:
                return json.dumps({"ok": False, "msg": "字段参数格式错误", "changed": False},
                                  ensure_ascii=False)
            selected = {f for f in raw_fields if isinstance(f, str)}

        def want(field: str) -> bool:
            # 旧调用（未传 fields）：仅填空白；新调用：只应用被勾选的字段
            return (field in selected) if selected is not None else not getattr(g, field, None)

        changed = False
        for field in ("title", "description", "developer", "released"):
            value = cand.get(field)
            if isinstance(value, str) and value and want(field):
                setattr(g, field, value)
                changed = True
        if cand.get("rating") and want("rating"):
            from utils.domain.rating_utils import normalize_rating
            try:
                raw = float(cand["rating"])
            except (TypeError, ValueError):
                raw = 0
            if raw > 0:
                g.rating = normalize_rating(raw if raw <= 5 else raw / 20) or 0
                changed = True
        if cand.get("length_minutes") and want("length_minutes"):
            try:
                minutes = int(cand["length_minutes"])
            except (TypeError, ValueError):
                minutes = 0
            if minutes > 0:
                g.length_minutes = minutes
                changed = True

        cover_queued = False
        cover_failed = False
        cover_url = str(cand.get("cover_url") or "")
        has_cover = bool(g.cover_path and os.path.isfile(g.cover_path))
        if cover_url and ((selected is None and not has_cover) or "cover" in (selected or ())):
            if _is_safe_cover_url(cover_url):
                self._queue_cover(game_id, cover_url, "", force=True)
                cover_queued = True
                changed = True
            else:
                cover_failed = True

        # 记录候选来源 ID，后续批量匹配据此跳过已匹配项
        src = str(cand.get("source") or "").strip().lower()
        sid = str(cand.get("source_id") or "").strip()
        if src == "vndb" and sid and g.vndb_id != sid:
            g.vndb_id = sid
            changed = True
        elif src == "bangumi" and sid and g.bangumi_id != sid:
            g.bangumi_id = sid
            changed = True

        if changed:
            self.manager.unmatched_repo.delete(game_id)
            g.unmatched_reason = ""
            if not self.manager.update_game(g):
                self.refresh_delta([game_id])
                return json.dumps({"ok": False, "msg": "保存元数据失败", "changed": False},
                                  ensure_ascii=False)
            if g.cover_path and not self.manager.repository.update_cover_path(game_id, g.cover_path):
                logger.warning("封面路径写入失败: %s", game_id)
            if not cover_queued:
                try:
                    self._cover_pool.submit(self._cover_store.ensure_thumb, game_id)
                except Exception:
                    pass
            self.reloadCover(game_id)   # 单游戏元数据应用，只定向重载该卡封面
        if src and sid:
            self.manager.source_repo.upsert(game_id, src, sid, cand)
        self.refresh_delta([game_id])
        if cover_failed:
            return json.dumps({"ok": True, "changed": changed, "msg": "部分字段已应用，封面地址无效"},
                              ensure_ascii=False)
        if cover_queued:
            return json.dumps({"ok": True, "changed": True, "msg": "已应用所选字段，封面下载中"},
                              ensure_ascii=False)
        if not changed:
            return json.dumps({"ok": True, "changed": False, "msg": "没有可应用的字段"}, ensure_ascii=False)
        return json.dumps({"ok": True, "changed": True}, ensure_ascii=False)

    # ---------- 启动时自动扫描 ----------
    # ---------- 前端刷新（统一经 UISync 合并推送，见 ui/sync.py）----------
    def refresh(self):
        """数据变化后通知前端刷新（可在任意线程调用，微延迟合并）"""
        self._ui.invalidate("games")

    def refresh_delta(self, game_ids):
        """增量刷新：只通知前端更新指定的游戏（单对象写操作用，减少全量重建）"""
        self._ui.invalidate("games_delta", list(game_ids))

    def notify(self, msg: str):
        """向前端弹 toast 提示（可在任意线程调用，微延迟合并）"""
        self._ui.invalidate("toast", msg)

    def reloadCovers(self):
        """封面更新后强制前端重新加载所有卡片封面（清缓存后定向推送）

        仅用于「批量」封面变化场景（批量 VNDB 匹配结束、扫描导入多游戏等）；
        单张封面变化请用 reloadCover(game_id) 定向失效，避免全量重载。
        """
        _cover_cache_clear()
        self._ui.invalidate("covers")

    def reloadCover(self, game_id):
        """封面发生变化：只失效该游戏封面缓存并重新加载对应卡片"""
        g = self.manager.get_game(game_id)
        if g:
            _cover_cache_invalidate(g.cover_path)
            _cover_cache_invalidate(self._cover_store.thumb_path(game_id))
        self._ui.invalidate("cover", str(game_id))

    def cleanup_unused_covers(self) -> int:
        """启动后台迁移旧封面并清理未引用文件/过期缩略图"""
        try:
            self._cover_store.migrate(self.manager.repository)
        except Exception as e:  # noqa: BLE001
            logger.warning("封面迁移失败: %s", e)
        try:
            return self._cover_store.cleanup(self.manager.repository)
        except Exception as e:  # noqa: BLE001
            logger.warning("封面清理失败: %s", e)
            return 0

    # ---------- 封面异步下载（与匹配解耦，见 docs/archive/COVER_DOWNLOAD_OPTIMIZATION.md）----------
    def _queue_cover(self, game_id: str, cover_url: str, dest: str, force: bool = False):
        """match_single 的封面回调：入队后台下载，不阻塞匹配流程

        force=True 时即使已有封面也重新下载（手动应用候选时用户已明确选择封面）。
        """
        try:
            self._cover_pool.submit(self._download_cover_bg, game_id, cover_url, dest, force)
        except Exception as e:
            logger.warning("封面入队失败: %s, %s", cover_url, e)

    def _set_cover_progress(self, game_id: str, pct):
        """更新某游戏封面下载进度并推送（pct=None 表示结束、移除）。

        UISync 按「域」去重，故 payload 用「当前全部下载中状态」快照（dict），
        避免多游戏各自的进度互相覆盖。
        """
        with self._cover_state_lock:
            if pct is None:
                self._cover_states.pop(game_id, None)
            else:
                self._cover_states[game_id] = round(float(pct), 4)
            snapshot = dict(self._cover_states)
        self._ui.invalidate("cover_progress", snapshot)

    def _invalidate_cover_download(self, game_id: str) -> None:
        """手动换封面时使后台下载失效，避免晚到的下载覆盖用户选择。"""
        with self._cover_state_lock:
            self._cover_generation[game_id] = self._cover_generation.get(game_id, 0) + 1
            cancel = self._cover_cancel.pop(game_id, None)
        if cancel is not None:
            cancel.set()

    def _download_cover_bg(self, game_id: str, cover_url: str, dest: str, force: bool = False):
        """后台下载封面（可配超时、不重试），上报进度；成功写库并定向刷新该卡"""
        self._set_cover_progress(game_id, 0.0)
        cancel = None
        try:
            game = self.manager.get_game(game_id)
            if not force and game and game.cover_path and os.path.isfile(game.cover_path):
                return
            with self._cover_state_lock:
                generation = self._cover_generation.get(game_id, 0)
                cancel = threading.Event()
                self._cover_cancel[game_id] = cancel

            def _pc(pct, _gid=game_id):
                self._set_cover_progress(_gid, pct)

            path = self._cover_store.download(
                game_id, cover_url, cancel_event=cancel, progress_cb=_pc)
            with self._cover_state_lock:
                current = self._cover_generation.get(game_id, 0) == generation
                if self._cover_cancel.get(game_id) is cancel:
                    self._cover_cancel.pop(game_id, None)
            if not path or not current:
                if force and not path and not (cancel and cancel.is_set()):
                    self.notify("封面下载失败")
                return
            latest = self.manager.get_game(game_id)
            if not force and latest and latest.cover_path and os.path.isfile(latest.cover_path):
                return
            if not self.manager.repository.update_cover_path(game_id, path):
                logger.warning("封面路径写入失败: %s", game_id)
                return
            self._cover_store.ensure_thumb(game_id)
            self.reloadCover(game_id)
            if force:
                self.notify("封面已更新")
        except Exception as e:
            logger.warning("封面后台下载失败: %s, %s", cover_url, e)
        finally:
            with self._cover_state_lock:
                if cancel is not None and self._cover_cancel.get(game_id) is cancel \
                        and not cancel.is_set():
                    self._cover_cancel.pop(game_id, None)
            self._set_cover_progress(game_id, None)

    def _on_game_exit(self, game_id: str, runtime_seconds: int):
        # 游戏退出：即时清除"运行中"状态 + 增量刷新该游戏数据（时长/最后游玩）
        self._ui.invalidate("running", "")
        self.refresh_delta([game_id])

    def _on_game_start(self, game_id: str, *extra):
        # 游戏启动：即时标记"运行中" + 刷新该游戏数据
        self._ui.invalidate("running", game_id)
        self.refresh_delta([game_id])

    # ---------- 窗口控制 ----------
    def windowMinimize(self):
        if self._window:
            self._window.minimize()

    def windowToggleMaximize(self):
        if not self._window:
            return
        if self._maximized:
            # pywebview 在 frameless 下 restore() 失效，改用 Win32 SW_RESTORE
            if not self._restore_win32():
                try:
                    self._window.restore()
                except Exception as e:
                    logger.warning("还原窗口失败: %s", e)
            self._maximized = False
        else:
            try:
                self._window.maximize()
                self._maximized = True
            except Exception as e:
                logger.warning("最大化失败: %s", e)

    def _win32_hwnd(self):
        """查找本进程主窗口句柄（pywebview 不直接暴露 hwnd），结果缓存复用。

        不能用 FindWindowW 按标题直接取：Windows 11 的 Shell 内部窗口
        （Windows.Internal.Shell.TabProxyWindow）会以同名标题先被命中，
        导致 ShowWindow 作用到错误窗口——最大化/还原看似无效。
        改为枚举本进程、标题匹配的 WindowsForms 顶层窗口。
        """
        if os.name != "nt":
            return 0
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            if self._hwnd and user32.IsWindow(self._hwnd):
                return self._hwnd
            found = 0
            own_pid = os.getpid()
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _cb(hwnd, _lparam):
                nonlocal found
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != own_pid:
                    return True
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if not cls.value.startswith("WindowsForms10"):
                    return True
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                found = hwnd
                return title.value != WINDOW_TITLE   # 精确命中即停止枚举

            user32.EnumWindows(enum_proc(_cb), 0)
            if not found:
                found = user32.FindWindowW(None, WINDOW_TITLE)
            self._hwnd = found
            return found
        except Exception:
            return 0

    def _restore_win32(self) -> bool:
        hwnd = self._win32_hwnd()
        if not hwnd:
            return False
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            return True
        except Exception:
            return False

    def windowMaximize(self):
        if self._window:
            self._window.maximize()
            self._maximized = True

    def windowRestore(self):
        if self._window:
            self._window.restore()
            self._maximized = False

    def windowClose(self):
        if self._overlay_client is not None:
            try:
                self._overlay_client.quit()
            except Exception:
                pass
        if self._window:
            self._window.destroy()

    def windowStartDrag(self, gx: int, gy: int):
        if self._window:
            self._drag_anchor = (self._window.x - gx, self._window.y - gy)

    def windowMoveDrag(self, gx: int, gy: int):
        if self._window and self._drag_anchor is not None:
            self._window.move(gx + self._drag_anchor[0],
                              gy + self._drag_anchor[1])

    def windowEndDrag(self):
        self._drag_anchor = None

    # ---------- 窗口缩放（四边/四角自由拉伸，常规逻辑：起始几何 + 累计位移） ----------
    def windowResizeStart(self, direction: str):
        try:
            self._rs_start = (int(self._window.x), int(self._window.y),
                              int(self._window.width), int(self._window.height))
        except Exception:
            self._rs_start = None

    def windowResize(self, direction: str, dx: int, dy: int):
        if not self._window or not self._rs_start:
            return
        try:
            if self._window.maximized:
                return
            sx, sy, sw, sh = self._rs_start
            x, y, w, h = sx, sy, sw, sh
            if 'e' in direction:
                w = sw + dx
            if 's' in direction:
                h = sh + dy
            if 'w' in direction:
                w = sw - dx
                x = sx + dx
            if 'n' in direction:
                h = sh - dy
                y = sy + dy
            # 最小尺寸约束
            min_w, min_h = 900, 620
            if w < min_w:
                if 'w' in direction:
                    x += (w - min_w)
                w = min_w
            if h < min_h:
                if 'n' in direction:
                    y += (h - min_h)
                h = min_h
            if w != sw or h != sh:
                self._window.resize(w, h)
            if x != sx or y != sy:
                self._window.move(x, y)
        except Exception as e:
            logger.warning("调整窗口大小失败: %s", e)
