"""WebBridge - pywebview js_api 桥，把后端 GameManager 能力暴露给前端 HTML/JS

- 通过 pywebview.create_window(js_api=WebBridge(...)) 注入，
  JS 侧用 `pywebview.api.method(...)`（Promise）调用
- 数据变化（monitor 退出、扫描完成、封面/截图更新等）统一经 UISync
  （ui/sync.py）合并推送前端，不在本类内直接拼 evaluate_js
- 窗口控制（最小化/最大化/拖拽）也由此桥接
"""
import base64
import hashlib
import json
import os
import shutil
import threading
from collections import OrderedDict
from typing import Optional, Dict, Any

import webview

from core.game_manager import GameManager
from core.game_model import Game
from ui.sync import UISync
from utils.config import Config
from utils.path_utils import get_app_data_dir
from utils.logger import get_logger

logger = get_logger()

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "resources")

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif"}

# ---------- 封面 base64 缓存（LRU，防长期会话内存无界增长）----------
# 封面以 data URI 形式常驻内存（原图 base64 再膨胀 ~33%），无上限缓存
# 会在千库规模下累积数百 MB。这里按「条目数 + 总字节」双上限，超限时
# 淘汰最久未使用的条目（OrderedDict.popitem(last=False)）。
_MAX_COVER_CACHE_ENTRIES = 128
_MAX_COVER_CACHE_BYTES = 48 * 1024 * 1024   # 总字节上限（base64 字符串长度）
_cover_cache: "OrderedDict[str, str]" = OrderedDict()
_cover_cache_bytes = 0


def _cover_cache_get(path: str) -> Optional[str]:
    """读取封面缓存；命中时标记为最近使用，未命中返回 None"""
    uri = _cover_cache.get(path)
    if uri is not None:
        _cover_cache.move_to_end(path)
    return uri


def _cover_cache_put(path: str, uri: str) -> None:
    """写入封面缓存并做 LRU 淘汰（超上限时移除最久未用条目）"""
    global _cover_cache_bytes
    _cover_cache[path] = uri          # 已存在时 OrderedDict 自动移到末尾
    _cover_cache_bytes += len(uri)
    while (_cover_cache_bytes > _MAX_COVER_CACHE_BYTES
           or len(_cover_cache) > _MAX_COVER_CACHE_ENTRIES) and _cover_cache:
        _, old = _cover_cache.popitem(last=False)
        _cover_cache_bytes -= len(old)


def _cover_cache_clear() -> None:
    """清空缓存（封面更新后调用）"""
    global _cover_cache_bytes
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
    """
    thumb = _cover_thumb_path(path)
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


def _cover_data_uri(path: str) -> str:
    """封面图 → base64 data URI（优先缩略图；html= 模式下 file:// 会被 WebView2 拦截）"""
    if not path or not os.path.exists(path):
        path = _default_cover_path()
    if not path:
        return ""
    src = _ensure_cover_thumb(path)   # 缩略图或原图（生成失败回退）
    cached = _cover_cache_get(src)
    if cached is not None:
        return cached
    try:
        with open(src, "rb") as f:
            raw = f.read()
        if len(raw) > 6 * 1024 * 1024:
            return ""
        ext = os.path.splitext(src)[1].lower().lstrip(".")
        mime = _MIME.get(ext, "image/jpeg")
        uri = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        _cover_cache_put(src, uri)
        return uri
    except Exception:
        return ""


def _game_dict(g: Game) -> Dict[str, Any]:
    from utils.time_utils import format_play_time, format_relative_time
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
        # 封面改为按需懒加载：getGames 不再内联 base64，前端滚动到卡片附近再取
        "cover_url": "",
        "has_cover": bool(g.cover_path and os.path.exists(g.cover_path)),
        "cover_version": _cover_version(g),
        # Hook 实时翻译（V1.1）
        "translate_enabled": bool(g.translate_enabled),
        "has_hook_code": bool(g.hook_code),
    }


def _set_clipboard_dib(data: bytes) -> bool:
    """把 CF_DIB 位图数据写入系统剪贴板（DIB = BMP 去掉 14 字节文件头）"""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        size = len(data)
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not hmem:
            return False
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            kernel32.GlobalFree(hmem)
            return False
        ctypes.memmove(ptr, data, size)
        kernel32.GlobalUnlock(hmem)
        if not user32.SetClipboardData(CF_DIB, hmem):
            kernel32.GlobalFree(hmem)
            return False
        return True
    finally:
        user32.CloseClipboard()


class WebBridge:
    """pywebview js_api 桥（前端通过 pywebview.api.* 调用）"""

    def __init__(self, manager: GameManager):
        self.manager = manager
        self._cfg = Config()
        self._window = None          # 由 create_window 后绑定
        self._ui = UISync()          # 界面更新总线（全部前端推送经它合并发出）
        self._overlay_client = None  # C++ 游戏内 toast 客户端（懒加载）
        self._sub_pos_bound = False  # 字幕位置回传转发是否已绑定
        self._drag_anchor = None
        self._maximized = False      # 本地跟踪最大化状态（pywebview 判断可能失效）
        self._vndb_counter = 0       # VNDB 进度节流计数
        self._batch_ctx = None       # 批量任务进度上下文（matchVndbBatch 设置，getBatchProgress 读取）
        try:
            self.manager.monitor.register_callback("on_exit", self._on_game_exit)
        except Exception as e:
            logger.warning("注册 monitor 回调失败: %s", e)

    def bind_window(self, window):
        self._window = window
        self._ui.bind_window(window)

    # ---------- 数据 ----------
    def getGames(self) -> str:
        games = self.manager.get_all_games()
        return json.dumps([_game_dict(g) for g in games], ensure_ascii=False)

    def getGame(self, game_id: str) -> str:
        g = self.manager.get_game(game_id)
        return json.dumps(_game_dict(g), ensure_ascii=False) if g else "{}"

    def getCover(self, game_id: str) -> str:
        """按需返回单个游戏封面的 base64 data URI（懒加载用，缓存命中直接返回）"""
        g = self.manager.get_game(game_id)
        if not g:
            return ""
        return _cover_data_uri(g.cover_path)

    def getTags(self) -> str:
        return json.dumps(self.manager.get_all_tags(), ensure_ascii=False)

    def getCategories(self) -> str:
        return json.dumps(self.manager.get_all_categories(), ensure_ascii=False)

    # ---------- 配置 ----------
    def getConfig(self) -> str:
        data = self._cfg.get_all()
        data["path"] = self._cfg.path
        return json.dumps(data, ensure_ascii=False)

    def saveConfigs(self, data_json: str):
        data = json.loads(data_json)
        for k, v in data.items():
            # dict 值做浅合并：保留该键下未涉及的子字段（如 subtitle.style 不被 enabled 覆盖）
            if isinstance(v, dict):
                old = self._cfg.get(k)
                if isinstance(old, dict):
                    merged = dict(old)
                    merged.update(v)
                    v = merged
            self._cfg.set(k, v)
        self._cfg.save()

    def resetConfig(self):
        self._cfg.reset()

    def getConfigPath(self) -> str:
        return self._cfg.path

    # ---------- 写操作 ----------
    def toggleFav(self, game_id: str):
        self.manager.toggle_favorite(game_id)
        self.refresh()

    def launch(self, game_id: str) -> str:
        ok = self.manager.launch(game_id)
        logger.info("启动游戏 %s: %s", game_id, ok)
        self.refresh()
        # 返回 JSON：need_hook_select=True 时前端弹 Hook 点选择窗
        need = False
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        if ok and coord is not None:
            need = bool(getattr(coord, "_awaiting_selection", False))
        return json.dumps({"ok": ok, "need_hook_select": need}, ensure_ascii=False)

    # ---------- Hook 实时翻译（V1.1） ----------

    def getHookCandidates(self) -> str:
        """返回 C++ 收集的 Hook 候选列表（+ 最近错误），供 Hook 选择弹窗轮询"""
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        if not coord:
            return json.dumps({"list": [], "error": ""}, ensure_ascii=False)
        return json.dumps({
            "list": getattr(coord, "_last_candidates", []) or [],
            "error": getattr(coord, "_last_error", "") or "",
        }, ensure_ascii=False)

    def selectHook(self, game_id: str, handle: int, hook_code: str) -> bool:
        """用户选定 Hook 点：通知 C++ + 持久化 hook_code"""
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        if coord:
            coord.select_hook(int(handle), hook_code or "")
        if game_id:
            self.manager.repository.update_hook_code(game_id, hook_code or "")
        self.refresh()
        return True

    def clearHookCode(self, game_id: str) -> bool:
        """清除已保存的 Hook 点（重新选择入口）"""
        if game_id:
            self.manager.repository.update_hook_code(game_id, "")
        self.refresh()
        return True

    def toggleGameTranslation(self, game_id: str, enabled: bool) -> bool:
        """设置游戏翻译开关（游戏运行中联动字幕窗口显示/隐藏）"""
        if game_id:
            self.manager.repository.set_translate_enabled(game_id, bool(enabled))
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        if coord and getattr(coord, "_running", False):
            self._get_overlay_client().send_set_subtitle_enabled(bool(enabled))
        # 不触发全量刷新：开关仅影响详情页开关态（前端已本地同步）与 C++ 字幕，
        # 卡片网格不展示翻译状态，刷新无可见收益反而重建网格+详情
        return True

    def testTranslation(self, text: str = "こんにちは、世界") -> str:
        """测试翻译是否通：调 C++ AI 翻译（用已保存配置），同步等待结果"""
        import threading
        from core.overlay_client import OverlayClient
        ai = {
            "base_url": self._cfg.get("translate.ai.base_url", "") or "",
            "api_key": self._cfg.get("translate.ai.api_key", "") or "",
            "model": self._cfg.get("translate.ai.model", "") or "",
            "source_lang": self._cfg.get("translate.source_lang", "ja") or "ja",
            "target_lang": self._cfg.get("translate.target_lang", "zh") or "zh",
        }
        overlay = self._get_overlay_client()
        result = {"ok": False, "msg": "等待超时"}
        evt = threading.Event()

        def on_result(ok, result_text, err):
            result["ok"] = ok
            result["msg"] = result_text if ok else (err or "翻译失败")
            evt.set()

        overlay.on_test_translate_result = on_result
        if not overlay.send_test_translate(text, ai):
            return json.dumps({"ok": False, "msg": "overlay 不可用，请先启动一次游戏"},
                              ensure_ascii=False)
        evt.wait(timeout=30)
        return json.dumps(result, ensure_ascii=False)

    # ---------- 文本清洗配置（每游戏，V1.1） ----------

    def getCleanFilterConfig(self, game_id: str) -> str:
        """获取某游戏的清洗过滤器配置：
        - 游戏运行中：查 C++ 当前生效（含引擎默认）
        - 未运行：返回该游戏 override（非空）或引擎默认（空）
        返回带 source 标记（runtime/override/engine）供前端提示来源。"""
        import threading
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        running = bool(coord and getattr(coord, "_running", False))
        if running:
            overlay = self._get_overlay_client()
            result = {}
            evt = threading.Event()

            def on_cfg(filters):
                result["filters"] = filters or []
                evt.set()

            overlay.on_filter_config = on_cfg
            if overlay.send_query_filter_config():
                evt.wait(timeout=3)
            overlay.on_filter_config = None
            # 仅当 C++ 确实回传了有效过滤器（注入成功）才采用 runtime；
            # 否则（注入失败/无配置）回退到数据库 override，避免用户已保存配置"丢失"
            if result and result.get("filters"):
                return json.dumps({"filters": result["filters"], "source": "runtime"},
                                  ensure_ascii=False)
        game = self.manager.get_game(game_id) if game_id else None
        ov = (game.clean_filter_override if game else "") or ""
        try:
            filters = json.loads(ov) or []
        except (ValueError, TypeError):
            filters = []
        if filters:
            return json.dumps({"filters": filters, "source": "override"},
                              ensure_ascii=False)
        # 无 override：返回引擎默认勾选，方便用户看到当前生效的策略
        from utils.engine_policy import default_filter_config
        engine = (game.engine if game else "") or ""
        return json.dumps({"filters": default_filter_config(engine), "source": "engine"},
                          ensure_ascii=False)

    def setCleanFilterConfig(self, game_id: str, filters_json) -> bool:
        """保存某游戏的清洗过滤器配置（override），该游戏运行中实时下发 C++"""
        logger.info("setCleanFilterConfig: game=%s filters_len=%s", game_id,
                    len(filters_json or ""))
        if game_id:
            self.manager.repository.update_clean_filter_override(
                game_id, filters_json or "")
        launcher = getattr(self.manager, "launcher", None)
        coord = getattr(launcher, "subtitle_coordinator", None) if launcher else None
        if coord and getattr(coord, "_running", False):
            try:
                filters = json.loads(filters_json or "[]") or []
            except (ValueError, TypeError):
                filters = []
            self._get_overlay_client().send_update_filter_config(filters)
        # 不触发全量刷新：勾选状态前端已本地维护，卡片网格不展示清洗配置，
        # 刷新仅重建网格+详情，无可见收益
        return True

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
        self.manager.delete_game(game_id)
        self.refresh()

    def saveGame(self, game_id: str, data_json: str):
        """前端编辑/添加保存。game_id 为空视为手动添加。

        收藏夹归属与标签不在此处理（编辑表单已移除收藏夹/标签管理，
        归属经由 addGamesToCollection / removeGamesFromCollection 独立维护）。
        """
        data = json.loads(data_json)
        g = Game(
            id=game_id,
            title=data.get("title", ""),
            engine=data.get("engine", ""),
            developer=data.get("developer", ""),
            description=data.get("description", ""),
            rating=int(data.get("rating", 0) or 0),
        )
        if game_id:
            old = self.manager.get_game(game_id)
            if old:
                g.exe_path = old.exe_path
                g.folder = old.folder
                g.cover_path = old.cover_path
                g.tags = list(old.tags)   # 保留已有标签（编辑表单不再提供）
                g.collections = list(old.collections)
                g.category_id = int(data.get("cat_id", old.category_id) or 0)
                # 启动文件：若前端提供了新路径则更新 exe 与所在目录
                new_exe = (data.get("exe_path") or "").strip()
                if new_exe and os.path.exists(new_exe):
                    g.exe_path = os.path.normpath(new_exe)
                    g.folder = os.path.dirname(g.exe_path)
                self.manager.update_game(g)
        else:
            # 手动添加单个 exe：exe 必填；标题自动推导（exe 所在文件夹名，兜底文件名），
            # 添加前不强制取名；引擎/开发商/简介留空，可进详情后编辑
            exe_path = (data.get("exe_path") or "").strip()
            if not exe_path:
                self.notify("请先选择要添加的 exe 文件")
                return
            exe_path = os.path.normpath(exe_path)
            title = (data.get("title") or "").strip()
            if not title:
                title = self.manager.scanner._generate_title(
                    os.path.dirname(exe_path), os.path.basename(exe_path))
            g.title = title
            g.id = self.manager.scanner._generate_id(exe_path)
            g.exe_path = exe_path
            g.folder = os.path.dirname(exe_path)
            g.category_id = int(data.get("cat_id", 0) or 0)
            self.manager.add_game(g)
            # 手动添加后自动触发元数据匹配（后台线程，避免阻塞 GUI）
            threading.Thread(target=self._run_vndb_match, args=([g],),
                             daemon=True).start()
        self.refresh()

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
        self.refresh()

    def addCategory(self, name: str) -> str:
        cat_id = self.manager.add_category(name)
        self.refresh()
        return json.dumps({"id": cat_id, "name": name})

    def deleteCategory(self, cat_id: int):
        self.manager.delete_category(cat_id)
        self.refresh()

    def setGameCategory(self, game_id: str, cat_id: int):
        self.manager.set_game_category(game_id, cat_id)
        self.refresh()

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
        self.manager.batch_delete(json.loads(ids_json))
        self.refresh()

    # ---------- 收藏夹（V1.0 collections）----------
    def getCollectionsTree(self) -> str:
        """返回树形收藏夹 JSON: [{id,name,icon,color,sort_order,game_count,children:[...]}]"""
        return json.dumps(self.manager.get_collections_tree(), ensure_ascii=False)

    def createCollection(self, name: str, parent_id: int, icon: str, color: str) -> str:
        """新建收藏夹。parent_id=0 表示根节点(分组)"""
        result = self.manager.create_collection(name, parent_id or None, icon, color)
        self.refresh()
        return json.dumps(result, ensure_ascii=False) if result else "{}"

    def updateCollection(self, collection_id: int, data_json: str):
        """更新收藏夹（name/parent_id/icon/color/sort_order）"""
        data = json.loads(data_json)
        self.manager.update_collection(collection_id, **data)
        self.refresh()

    def deleteCollection(self, collection_id: int):
        """删除收藏夹（级联删除子分类 + 关联）"""
        self.manager.delete_collection(collection_id)
        self.refresh()

    def reorderCollection(self, collection_id: int, new_sort_order: int):
        """调整收藏夹排序"""
        self.manager.reorder_collection(collection_id, new_sort_order)
        self.refresh()

    def addGamesToCollection(self, ids_json: str, collection_id: int):
        """批量添加游戏到收藏夹"""
        self.manager.add_games_to_collections(json.loads(ids_json), [collection_id])
        self.refresh()

    def removeGamesFromCollection(self, ids_json: str, collection_id: int):
        """从收藏夹批量移除游戏"""
        self.manager.remove_games_from_collection(json.loads(ids_json), collection_id)
        self.refresh()

    def setGameCollections(self, game_id: str, collection_ids_json: str):
        """设置游戏所属的收藏夹列表（整体替换）"""
        self.manager.set_game_collections(game_id, json.loads(collection_ids_json))
        self.refresh()

    def setCollectionGames(self, collection_id: int, ids_json: str) -> bool:
        """整体替换某收藏夹的游戏列表 + 排序（管理游戏对话框用）"""
        ok = self.manager.set_collection_games(collection_id, json.loads(ids_json))
        self.refresh()
        return ok

    def getGamesInCollection(self, collection_id: int) -> str:
        """获取收藏夹内的游戏 ID 列表（按 sort_order 排序）"""
        return json.dumps(self.manager.get_games_in_collection(collection_id),
                          ensure_ascii=False)

    def moveGameInCollection(self, collection_id: int, game_id: str, new_sort_order: int):
        """调整游戏在收藏夹内的排序"""
        self.manager.move_game_in_collection(collection_id, game_id, new_sort_order)
        self.refresh()

    def batchMoveToCollection(self, ids_json: str, collection_id: int):
        """批量移动游戏到收藏夹（替代原 batchMoveCategory）"""
        self.manager.batch_add_to_collection(json.loads(ids_json), collection_id)
        self.refresh()

    def batchRemoveFromCollection(self, ids_json: str, collection_id: int):
        """批量从收藏夹移除游戏（替代原 batchRemoveTag 的收藏夹用法）"""
        self.manager.batch_remove_from_collection(json.loads(ids_json), collection_id)
        self.refresh()

    # ---------- 文件对话框 ----------
    def scanFolder(self) -> str:
        if self._window is None:
            return json.dumps({"ok": False, "msg": ""})
        folder = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if isinstance(folder, (list, tuple)):
            folder = folder[0] if folder else ""
        if not folder:
            return json.dumps({"ok": False, "msg": ""})
        threading.Thread(target=self._do_scan, args=(folder,), daemon=True).start()
        return json.dumps({"ok": True, "msg": "扫描中..."})

    def _do_scan(self, folder: str):
        added, new_games = self.manager.scan_and_add(folder)
        logger.info("扫描完成，新增 %d 个", added)
        if added:
            self._add_library_path(folder)
        self.refresh()
        if added and new_games:
            self.notify(f"扫描完成，新增 {added} 个游戏，开始 VNDB 匹配…")
            self._run_vndb_match(new_games)

    def _add_library_path(self, folder: str):
        paths = list(self._cfg.get("library_paths", []) or [])
        folder = os.path.normpath(folder)
        if folder not in paths:
            paths.append(folder)
            self._cfg.set("library_paths", paths)
            self._cfg.save()

    def _run_vndb_match(self, games: list):
        """后台批量 VNDB 匹配 + 节流进度提示（在调用线程内执行）"""
        self._vndb_counter = 0
        if games:
            self._batch_ctx = {"type": "vndb", "total": len(games), "done": 0, "running": True}
        try:
            matched, skipped, failed = self.manager.match_vndb_for_games(
                games, force=False, progress_cb=self._vndb_progress)
            self.reloadCovers()   # 封面可能已更新，清缓存并强制前端重载
            self.notify(
                f"VNDB 匹配完成：成功 {matched} / 跳过 {skipped} / 失败 {failed}")
        except Exception as e:
            logger.error("VNDB 批量匹配异常: %s", e)
        finally:
            if self._batch_ctx is not None:
                self._batch_ctx["running"] = False

    def _vndb_progress(self, game_id: str, title: str, status: str, msg: str):
        if status == "start":
            return
        if self._batch_ctx is not None:
            self._batch_ctx["done"] = min(self._batch_ctx.get("done", 0) + 1,
                                          self._batch_ctx.get("total", 1))
        self._vndb_counter += 1
        if self._vndb_counter % 3 == 0:
            self.notify(f"VNDB 匹配中：{title[:24]}")

    def getBatchProgress(self) -> str:
        """返回当前批量任务进度 JSON（无任务返回 running=false）"""
        ctx = self._batch_ctx
        if not ctx:
            return json.dumps({"running": False, "type": "", "total": 0, "done": 0},
                              ensure_ascii=False)
        return json.dumps({
            "running": bool(ctx.get("running")),
            "type": ctx.get("type", ""),
            "total": ctx.get("total", 0),
            "done": ctx.get("done", 0),
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
        threading.Thread(target=self._do_match, args=(game_id,),
                         daemon=True).start()
        return json.dumps({"ok": True, "msg": "开始匹配 VNDB..."})

    def _do_match(self, game_id: str):
        try:
            status, msg = self.manager.match_vndb_metadata(game_id, force=True)
            logger.info("VNDB 匹配 %s: %s %s", game_id, status, msg)
            self.reloadCovers()   # 封面可能已更新
            self.notify(f"VNDB 匹配完成：{msg}")
        except Exception as e:
            logger.error("VNDB 匹配异常: %s", e)
        self.refresh()

    def matchVndbBatch(self, ids_json: str) -> str:
        ids = set(json.loads(ids_json))
        games = [g for g in self.manager.get_all_games() if g.id in ids]
        threading.Thread(target=self._do_match_batch, args=(games,),
                         daemon=True).start()
        return json.dumps({"ok": True, "msg": "开始批量匹配..."})

    def _do_match_batch(self, games: list):
        self._run_vndb_match(games)
        self.refresh()

    # ---------- 评分 / 运行状态 ----------
    def setRating(self, game_id: str, rating: int):
        self.manager.set_rating(game_id, int(rating))
        self.refresh()

    def getRunning(self) -> str:
        g = self.manager.get_running_game()
        return g.id if g else ""

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
        from utils.hotkeys import reconfigure_screenshot_hotkey
        return reconfigure_screenshot_hotkey()

    def takeScreenshot(self, game_id: str) -> str:
        """为指定游戏截图（仅游戏画面）。game_id 为空时归入 _unsorted。返回 JSON。"""
        from core import screenshot_service
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
        from core import screenshot_service
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
        """当前运行游戏进程 PID（无则 None）"""
        launcher = getattr(self.manager, "launcher", None)
        proc = getattr(launcher, "current_process", None) if launcher else None
        return proc.pid if proc and proc.poll() is None else None

    def _running_game_hwnd(self) -> int:
        """当前运行游戏主窗口句柄（无则 0）"""
        pid = self._running_pid()
        if not pid:
            return 0
        from core import screenshot_service
        return screenshot_service.find_main_window_by_pid(pid)

    def _get_overlay_client(self):
        if self._overlay_client is None:
            from core.overlay_client import OverlayClient
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
                self.notify("提示：游戏为全屏模式，游戏内截图提示/字幕可能不可见，建议切换窗口化")
            client = self._get_overlay_client()
            client.show(hwnd, path or "", title or "")
        except Exception as e:
            logger.warning("游戏内 toast 发送失败: %s", e)

    def getScreenshots(self, game_id: str) -> str:
        """返回某游戏截图列表 JSON（含时间，不含图片内容）"""
        from core import screenshot_service
        return json.dumps(screenshot_service.get_screenshots(game_id),
                          ensure_ascii=False)

    def getScreenshotThumb(self, game_id: str, filename: str) -> str:
        """返回单张截图的 base64 data URI（缩略图懒加载用）"""
        from core import screenshot_service
        shots = screenshot_service.get_screenshots(game_id)
        p = ""
        for s in shots:
            if s["file"] == filename:
                p = s["path"]
                break
        if not p or not os.path.exists(p):
            return ""
        try:
            with open(p, "rb") as f:
                raw = f.read()
            if len(raw) > 8 * 1024 * 1024:
                return ""
            uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
            return uri
        except Exception:
            return ""

    def deleteScreenshot(self, game_id: str, filename: str) -> bool:
        from core import screenshot_service
        ok = screenshot_service.delete_screenshot(game_id, filename)
        self.refresh()
        return ok

    def renameScreenshot(self, game_id: str, filename: str, new_name: str) -> bool:
        from core import screenshot_service
        ok = screenshot_service.rename_screenshot(game_id, filename, new_name)
        self.refresh()
        return ok

    def openScreenshotFolder(self, game_id: str, filename: str) -> bool:
        """在资源管理器中定位到截图文件（explorer /select）"""
        from core import screenshot_service
        shots = screenshot_service.get_screenshots(game_id)
        p = ""
        for s in shots:
            if s["file"] == filename:
                p = s["path"]
                break
        if not p or not os.path.exists(p):
            return False
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select," + p])
            else:
                import webbrowser
                webbrowser.open(os.path.dirname(p))
            return True
        except Exception as e:
            logger.error("定位截图失败: %s", e)
            return False

    def copyScreenshotToClipboard(self, game_id: str, filename: str) -> bool:
        """把截图复制到系统剪贴板"""
        from core import screenshot_service
        shots = screenshot_service.get_screenshots(game_id)
        p = ""
        for s in shots:
            if s["file"] == filename:
                p = s["path"]
                break
        if not p or not os.path.exists(p):
            return False
        try:
            from PIL import Image
            import io
            img = Image.open(p).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "BMP")
            dib = buf.getvalue()[14:]
        except Exception as e:
            logger.error("读取截图失败: %s", e)
            return False
        return _set_clipboard_dib(dib)

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

    def setCover(self, game_id: str, path: str):
        g = self.manager.get_game(game_id)
        if not g or not path or not os.path.exists(path):
            return
        try:
            covers_dir = os.path.join(get_app_data_dir(), "covers")
            os.makedirs(covers_dir, exist_ok=True)
            ext = os.path.splitext(path)[1] or ".jpg"
            dest = os.path.join(covers_dir, f"{game_id}_manual{ext.lower()}")
            shutil.copy2(path, dest)
            g.cover_path = dest
            self.manager.update_game(g)
            self.reloadCovers()
        except Exception as e:
            logger.error("更换封面失败: %s", e)
        self.refresh()

    # ---------- 多源搜索手动匹配（源可自行配置，见 core/multi_source.py）----------
    def searchMetadata(self, keyword: str, sources_json: str = "") -> str:
        """多源搜索元数据；sources_json 为源 id 列表，空则用用户配置的混合源"""
        from core import multi_source
        try:
            sources = None
            if sources_json and sources_json.strip():
                sources = json.loads(sources_json)
            cands = multi_source.search_metadata(keyword, sources=sources,
                                                 limit_per_source=5)
            return json.dumps(cands, ensure_ascii=False)
        except Exception as e:
            logger.error("多源搜索失败: %s", e)
            return "[]"

    def getMetadataSources(self) -> str:
        """返回全部元数据源（id/名称/favicon/状态/是否启用），供设置页与工具栏展示"""
        from core import multi_source
        return json.dumps(multi_source.get_all_sources(), ensure_ascii=False)

    def saveMetadataSources(self, sources_json: str):
        """保存用户勾选的混合检索源（写 config，即时生效）。
        保存提示统一由前端 settings.save() 弹出（'设置已保存'），避免双 toast 互相覆盖。"""
        from core import multi_source
        multi_source.set_mixed_sources(json.loads(sources_json))

    def applyCandidate(self, game_id: str, candidate_json: str):
        from core import multi_source
        cand = json.loads(candidate_json)
        g = self.manager.get_game(game_id)
        if not g or not cand:
            return
        changed = False
        if cand.get("title") and not g.title:
            g.title = cand["title"]
            changed = True
        if cand.get("description") and not g.description:
            g.description = cand["description"]
            changed = True
        if cand.get("developer") and not g.developer:
            g.developer = cand["developer"]
            changed = True
        if cand.get("released") and not g.released:
            g.released = cand["released"]
            changed = True
        if cand.get("rating") and not g.rating:
            g.rating = int(cand["rating"]) if cand["rating"] <= 5 else round(cand["rating"] / 20)
            changed = True
        if cand.get("length_minutes") and not g.length_minutes:
            g.length_minutes = int(cand["length_minutes"])
            changed = True
        if cand.get("cover_url"):
            try:
                covers_dir = os.path.join(get_app_data_dir(), "covers")
                os.makedirs(covers_dir, exist_ok=True)
                ext = ".jpg"
                url = (cand["cover_url"] or "").split("?")[0].lower()
                if url.endswith(".png"):
                    ext = ".png"
                elif url.endswith(".webp"):
                    ext = ".webp"
                dest = os.path.join(covers_dir, f"{game_id}_ms{ext}")
                if multi_source.download_cover(cand, dest):
                    g.cover_path = dest
                    changed = True
            except Exception as e:
                logger.error("下载封面失败: %s", e)
        if changed:
            self.manager.update_game(g)
            self.reloadCovers()
        self.refresh()

    # ---------- 启动时自动扫描 ----------
    def startAutoScan(self):
        if not (self._cfg.get("auto_scan_on_startup", True)
                and self._cfg.get("library_paths")):
            return
        for p in self._cfg.get("library_paths"):
            if p and os.path.isdir(p):
                threading.Thread(target=self._do_scan, args=(p,), daemon=True).start()

    # ---------- 前端刷新（统一经 UISync 合并推送，见 ui/sync.py）----------
    def refresh(self):
        """数据变化后通知前端刷新（可在任意线程调用，微延迟合并）"""
        self._ui.invalidate("games")

    def notify(self, msg: str):
        """向前端弹 toast 提示（可在任意线程调用，微延迟合并）"""
        self._ui.invalidate("toast", msg)

    # ---------- 字幕样式桥接口（控制面板并入主设置页）----------

    def _ensure_subtitle_pos_handler(self):
        """把 C++ 字幕拖拽结束回传转发给主窗口设置页滑块（仅绑定一次）"""
        client = self._get_overlay_client()
        if getattr(self, "_sub_pos_bound", False):
            return
        self._sub_pos_bound = True

        def _forward(x, y):
            # 转发给主窗口（设置页「字幕样式」区的滑块）
            if self._window is not None:
                try:
                    self._window.evaluate_js(
                        "window.updateSubtitlePos && window.updateSubtitlePos(%s,%s)" % (x, y))
                except Exception:
                    pass
            # 同时写回配置，保证下次启动位置一致
            try:
                st = dict(self._cfg.get("subtitle.style", {}) or {})
                st["pos_x"] = x
                st["pos_y"] = y
                self._cfg.set("subtitle.style", st)
                self._cfg.save()
            except Exception:
                pass
        client.on_subtitle_pos = _forward

    def getSubtitleStyle(self) -> str:
        """返回当前字幕样式 JSON（设置页初始化用）"""
        return json.dumps(self._cfg.get("subtitle.style", {}), ensure_ascii=False)

    def setSubtitleStyle(self, style_json: str):
        """保存字幕样式并下发到 C++ overlay（游戏运行中实时重绘字幕）"""
        try:
            style = json.loads(style_json or "{}")
            if not isinstance(style, dict):
                style = {}
            self._cfg.set("subtitle.style", style)
            self._cfg.save()
            self._get_overlay_client().send_subtitle_style(style)
        except Exception as e:
            logger.error("setSubtitleStyle 失败: %s", e)

    def previewSubtitle(self):
        """显示示例字幕（不依赖游戏运行，便于实时预览样式）"""
        self._get_overlay_client().send_preview_subtitle()

    def setSubtitleDrag(self, drag: bool):
        """进入/退出字幕拖拽定位模式"""
        self._ensure_subtitle_pos_handler()
        self._get_overlay_client().send_subtitle_drag(bool(drag))

    def hideSubtitle(self):
        """临时隐藏当前字幕"""
        self._get_overlay_client().send_hide_subtitle()

    def setSubtitleEnabled(self, enabled: bool):
        """字幕总开关（关闭后不再显示新字幕）"""
        try:
            self._cfg.set("subtitle.enabled", bool(enabled))
            self._cfg.save()
        except Exception:
            pass
        self._get_overlay_client().send_set_subtitle_enabled(bool(enabled))

    def getSubtitleStylePresets(self) -> str:
        """返回字幕样式预设：内置 3 套（原作/极简/半透黑底）+ 用户自命名预设（config.subtitle.presets）"""
        builtin = {
            "original": {
                "bg_mode": 0, "bg_r": 0.0, "bg_g": 0.0, "bg_b": 0.0, "bg_a": 0.72,
                "corner": 10, "padding": 14, "gradient": False,
                "border": False, "font_size": 22, "font_weight": 700,
                "text_r": 1.0, "text_g": 1.0, "text_b": 1.0, "text_a": 1.0,
                "outline": False, "shadow": False, "align": 0, "line_gap": 4,
                "max_width": 0.9, "pos_x": 0.5, "pos_y": 0.82,
                "avoid_bottom": True, "avoid_bottom_px": 60, "show_source": True,
            },
            "minimal": {
                "bg_mode": 2, "bg_r": 0.0, "bg_g": 0.0, "bg_b": 0.0, "bg_a": 0.0,
                "corner": 0, "padding": 6, "gradient": False,
                "border": False, "font_size": 20, "font_weight": 600,
                "text_r": 1.0, "text_g": 1.0, "text_b": 1.0, "text_a": 1.0,
                "outline": True, "outline_w": 1.5, "outline_a": 0.8,
                "shadow": False, "align": 0, "line_gap": 3,
                "max_width": 0.9, "pos_x": 0.5, "pos_y": 0.82,
                "avoid_bottom": True, "avoid_bottom_px": 60, "show_source": True,
            },
            "darkglass": {
                "bg_mode": 1, "bg_r": 0.05, "bg_g": 0.05, "bg_b": 0.08, "bg_a": 0.55,
                "corner": 8, "padding": 12, "gradient": True,
                "grad_r": 0.15, "grad_g": 0.13, "grad_b": 0.2, "grad_a": 0.7,
                "border": True, "border_w": 1.0, "border_r": 0.3, "border_g": 0.3,
                "border_b": 0.4, "border_a": 0.4,
                "font_size": 22, "font_weight": 700,
                "text_r": 1.0, "text_g": 1.0, "text_b": 1.0, "text_a": 1.0,
                "outline": False, "shadow": True, "shadow_off": 2, "shadow_a": 0.5,
                "align": 0, "line_gap": 4, "max_width": 0.92,
                "pos_x": 0.5, "pos_y": 0.85, "avoid_bottom": True, "avoid_bottom_px": 60,
                "show_source": True,
            },
        }
        user = dict(self._cfg.get("subtitle.presets", {}) or {})
        presets = dict(builtin)
        presets.update(user)   # 用户预设覆盖同名内置（用于改名/复写）
        return json.dumps(presets, ensure_ascii=False)

    def saveSubtitlePreset(self, name: str, style_json: str) -> str:
        """把当前字幕样式保存为用户命名预设（config.subtitle.presets[name]）"""
        try:
            name = (name or "").strip()
            if not name:
                return json.dumps({"ok": False, "msg": "预设名称不能为空"})
            style = json.loads(style_json or "{}")
            if not isinstance(style, dict):
                style = {}
            presets = dict(self._cfg.get("subtitle.presets", {}) or {})
            presets[name] = style
            self._cfg.set("subtitle.presets", presets)
            self._cfg.save()
            return json.dumps({"ok": True, "name": name}, ensure_ascii=False)
        except Exception as e:
            logger.error("saveSubtitlePreset 失败: %s", e)
            return json.dumps({"ok": False, "msg": str(e)}, ensure_ascii=False)

    def deleteSubtitlePreset(self, name: str) -> str:
        """删除用户命名预设（内置预设不可删）"""
        try:
            name = (name or "").strip()
            if name in ("original", "minimal", "darkglass"):
                return json.dumps({"ok": False, "msg": "内置预设不可删除"}, ensure_ascii=False)
            presets = dict(self._cfg.get("subtitle.presets", {}) or {})
            if name in presets:
                del presets[name]
                self._cfg.set("subtitle.presets", presets)
                self._cfg.save()
            return json.dumps({"ok": True}, ensure_ascii=False)
        except Exception as e:
            logger.error("deleteSubtitlePreset 失败: %s", e)
            return json.dumps({"ok": False, "msg": str(e)}, ensure_ascii=False)

    def reloadCovers(self):
        """封面更新后强制前端重新加载所有卡片封面（清缓存后定向推送）"""
        _cover_cache_clear()
        self._ui.invalidate("covers")

    def _on_game_exit(self, game_id: str, runtime_seconds: int):
        self.refresh()

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
        """通过标题查找窗口句柄（pywebview 不直接暴露 hwnd）"""
        if os.name != "nt":
            return 0
        try:
            import ctypes
            return ctypes.windll.user32.FindWindowW(None, "KazariPlay")
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
