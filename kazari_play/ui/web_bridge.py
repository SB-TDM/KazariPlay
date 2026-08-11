"""WebBridge - pywebview js_api 桥，把后端 GameManager 能力暴露给前端 HTML/JS

- 通过 pywebview.create_window(js_api=WebBridge(...)) 注入，
  JS 侧用 `pywebview.api.method(...)`（Promise）调用
- 数据变化（monitor 退出、扫描完成）经 evaluate_js 通知前端刷新
- 窗口控制（最小化/最大化/拖拽）也由此桥接
"""
import base64
import json
import os
import shutil
import threading
from typing import Optional, Dict, Any

import webview

from core.game_manager import GameManager
from core.game_model import Game
from utils.config import Config
from utils.path_utils import get_app_data_dir
from utils.logger import get_logger

logger = get_logger()

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "resources")

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif"}
_cover_cache: Dict[str, str] = {}


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


def _cover_data_uri(path: str) -> str:
    """封面图 → base64 data URI（html= 模式下 file:// 会被 WebView2 拦截）"""
    if not path or not os.path.exists(path):
        path = _default_cover_path()
    if not path:
        return ""
    if path in _cover_cache:
        return _cover_cache[path]
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if len(raw) > 6 * 1024 * 1024:
            return ""
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = _MIME.get(ext, "image/jpeg")
        uri = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        _cover_cache[path] = uri
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
    }


class WebBridge:
    """pywebview js_api 桥（前端通过 pywebview.api.* 调用）"""

    def __init__(self, manager: GameManager):
        self.manager = manager
        self._cfg = Config()
        self._window = None          # 由 create_window 后绑定
        self._drag_anchor = None
        self._maximized = False      # 本地跟踪最大化状态（pywebview 判断可能失效）
        self._vndb_counter = 0       # VNDB 进度节流计数
        try:
            self.manager.monitor.register_callback("on_exit", self._on_game_exit)
        except Exception as e:
            logger.warning("注册 monitor 回调失败: %s", e)

    def bind_window(self, window):
        self._window = window

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

    def launch(self, game_id: str):
        ok = self.manager.launch(game_id)
        logger.info("启动游戏 %s: %s", game_id, ok)
        self.refresh()

    def openFolder(self, game_id: str):
        game = self.manager.get_game(game_id)
        if not game or not game.folder or not os.path.exists(game.folder):
            return
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(f'explorer /select,"{game.exe_path}"')
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
                    g.exe_path = new_exe
                    g.folder = os.path.dirname(new_exe)
                self.manager.update_game(g)
        else:
            g.id = self.manager.scanner._generate_id(
                data.get("exe_path", "") or data.get("title", ""))
            g.exe_path = data.get("exe_path", "")
            g.folder = data.get("folder", "")
            g.category_id = int(data.get("cat_id", 0) or 0)
            self.manager.add_game(g)
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
        try:
            matched, skipped, failed = self.manager.match_vndb_for_games(
                games, force=False, progress_cb=self._vndb_progress)
            self.reloadCovers()   # 封面可能已更新，清缓存并强制前端重载
            self.notify(
                f"VNDB 匹配完成：成功 {matched} / 跳过 {skipped} / 失败 {failed}")
        except Exception as e:
            logger.error("VNDB 批量匹配异常: %s", e)

    def _vndb_progress(self, game_id: str, title: str, status: str, msg: str):
        if status == "start":
            return
        self._vndb_counter += 1
        if self._vndb_counter % 3 == 0:
            self.notify(f"VNDB 匹配中：{title[:24]}")

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

    # ---------- 多源搜索手动匹配（VNDB + Bangumi） ----------
    def searchMetadata(self, keyword: str) -> str:
        from core import multi_source
        try:
            cands = multi_source.search_metadata(keyword, limit_per_source=5)
            return json.dumps(cands, ensure_ascii=False)
        except Exception as e:
            logger.error("多源搜索失败: %s", e)
            return "[]"

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

    # ---------- 前端刷新 ----------
    def refresh(self):
        """数据变化后通知前端刷新（可在任意线程调用）"""
        try:
            if self._window is not None:
                self._window.evaluate_js("window.__app && window.__app.refresh();")
        except Exception as e:
            logger.warning("刷新前端失败: %s", e)

    def notify(self, msg: str):
        """向前端弹 toast 提示（可在任意线程调用）"""
        try:
            if self._window is not None:
                self._window.evaluate_js(
                    f"window.__app && window.__app.toast({json.dumps(msg)});")
        except Exception as e:
            logger.warning("前端提示失败: %s", e)

    def reloadCovers(self):
        """封面更新后强制前端重新加载所有卡片封面（清缓存后调用）"""
        _cover_cache.clear()
        try:
            if self._window is not None:
                self._window.evaluate_js(
                    "window.__app && window.__app.reloadCovers();")
        except Exception as e:
            logger.warning("前端封面重载失败: %s", e)

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
