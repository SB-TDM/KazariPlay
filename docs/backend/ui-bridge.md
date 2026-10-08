# ui/ — 桥接与刷新总线

> `web_bridge.WebBridge` 是前端可调用的**全部后端方法**（pywebview `js_api`）。
> `sync.UISync` 是「后端数据变化 → 前端刷新」的**唯一推送通道**（合并、线程安全）。
> 约定：**桥内不直接 `evaluate_js`**，一律经 `UISync.invalidate(domain, payload)`。

---

## sync.py — UISync 更新总线

**对象**：`UISync`（每桥一个实例）

**为什么存在**：此前散落 35+ 处 `refresh()`、多处 `evaluate_js`；本模块把「事件域 → 前端刷新策略」收敛为注册表 + 微延迟合并。

**机制**
- `invalidate(domain, payload)`：任意线程可调；`_pending[domain] = payload`（**同域覆盖**，保留插入序），首条启动 `threading.Timer(_FLUSH_DELAY=50ms)`。
- `_flush_scheduled` → `_emit(pending)`：把一批 pending 拼成**单个 IIFE** `(function(){...})()`，经 `_flush_lock` 串行 `window.evaluate_js(js)`。窗口未绑定/已关闭则静默跳过。
- `bind_window(window)`：窗口创建后绑定。`flush_now()`：测试/退出前立即推送。

**事件域 → 前端入口 `window.__app.*`**（`_DOMAIN_JS`）
| domain | 前端方法 | payload |
|---|---|---|
| `games` | `refresh()` | — |
| `games_delta` | `applyGamesDelta(ids)` | game_id 数组 |
| `covers` | `reloadCovers()` | — |
| `cover` | `reloadCover(gid)` | game_id |
| `screenshots` | `refreshScreenshots(gid)` | game_id |
| `scan_progress` | `updateScanProgress(obj)` | `{running,dirs,games,folder,index,total}` |
| `batch_progress` | `updateBatchProgress(obj)` | `{running,title,...}` |
| `cover_progress` | `updateCoverProgress(obj)` | **全量快照 dict** `{game_id: pct}` |
| `toast` | `toast(msg)` | 消息文本 |
| `running` | `setRunning(gid)` | game_id（空=无运行） |

**关键约束**：域内 payload **覆盖**语义 → `cover_progress` 必须传「当前所有下载中状态快照」（见 web_bridge `_set_cover_progress`），否则多游戏进度互相覆盖，只剩最后一个。

---

## web_bridge.py — js_api 桥

**对象**：`WebBridge(manager: GameManager)`；`bind_window(window)` 后由 pywebview 注入，前端 `pywebview.api.method()`（Promise）。

**实例状态**：`_ui`(UISync)、`_cfg`(Config)、`_window`、`_overlay_client`(懒加载)、`_maximized`、`_batch_ctx`(批量进度上下文)、`_scan_cancel`/`_vndb_cancel`(取消事件)、`_task_lock`/`_task_thread`(单任务门禁)、`_cover_pool`(封面线程池)、`_cover_states`(封面进度)。

### 封面 base64 缓存（模块级）
- `_cover_cache`：`OrderedDict` LRU，**条目上限 128 + 总字节上限 48MB**（base64 膨胀），`_cover_cache_lock` 保护；`_cover_cache_get/put/invalidate/clear`。
- `_cover_data_uri(path)`：优先**缩略图**（`_ensure_cover_thumb`，512px 宽 JPEG q85，按 原图路径+mtime 命名落盘、幂等重建、并发加锁去重）；**in-flight 去重**（同路径同时只算一次，等待者读缓存，超时 `5s` 接管重算）；>6MB 拒载 → 回退 `default_cover.jpg`。
- 封面懒加载：`getGames` **不内联** base64，返回 `has_cover` + `cover_version`（cover 文件 mtime），前端滚动到卡片再 `getCover(id)`。

### 数据 / 配置
- `getGames()`（JSON 数组）/ `getGame(id)` / `getCover(id)`（data URI）/ `getTags()` / `getCategories()`
- `getConfig()`：剔除实验版键（translate/textractor/clean/subtitle/overlay.subtitle_enabled），附 `path`
- `saveConfigs(data_json)`：**深合并**（保留表单未涉及的嵌套字段）后逐项 set + save
- `resetConfig()` / `setTheme(theme)`（**即时持久化**，无需点保存）/ `getConfigPath()`

### 写操作
- `toggleFav` / `launch`（返回 `{ok}`）/ `openFolder`（explorer /select）/ `deleteGame` / `saveGame(id, data_json)`（见下）/ `setRating`
- `saveGame`：
  - `id` 非空：编辑——改 title/engine/developer/description/rating/cat_id；改了 `exe_path` 则校验存在、同步 `folder`；**重算 `identity`**；失败提示「启动路径是否重复」
  - `id` 空：手动添加——校验 exe、查重 `get_by_path`、标题自动推导（文件夹名→文件名）；添加后**后台自动触发匹配**（`_start_task`），`refresh()` 全量

### 标签 / 分类 / 批量
- 标签：`addTag`/`deleteTag`/`setGameTags`；分类：`addCategory`/`deleteCategory`/`setGameCategory`
- 批量：`batchAddTag`/`batchRemoveTag`/`batchMoveCategory`/`batchDelete`

### 批量重新定位（路径修正，不改 id）
- `previewRelocate(ids_json)`：选目录 → `scanner.scan` → 按 `identity` 建索引 → 返回 `items[{id,title,old_exe,new_exe,status}]`，`status ∈ matched/missing/conflict`（多候选或目标 exe 已被别的卡占用 = conflict）
- `applyRelocate(mapping_json)`：仅更新匹配项；处理自定义启动路径（folder 内则相对迁移）；冲突/文件缺失记入 `failures`；成功后 `refresh` + `notify`

### 收藏夹（V1.0）
`getCollectionsTree` / `createCollection(parent_id=0→根)` / `updateCollection` / `deleteCollection` / `reorderCollection` / `addGamesToCollection` / `removeGamesFromCollection` / `setGameCollections` / `setCollectionGames`（管理游戏对话框）/ `getGamesInCollection` / `moveGameInCollection` / `batchMoveToCollection` / `batchRemoveFromCollection`

### 扫描 / 单任务门禁
- `_start_task(target, args)`：`_task_lock.acquire(blocking=False)`，失败即「已有任务在运行」；**每次任务重建 `_scan_cancel`/`_vndb_cancel`**；`finally` 里置 `_batch_ctx.running=False` 并推 `scan_progress/batch_progress {running:false}` 后释放锁。
- `scanFolder()`：多选目录 → `_start_task(_do_scan)`；`cancelScan()`
- `_do_scan(folders)`：逐目录 `scan_and_add`（进度 → `scan_progress` 域，含 index/total）；结束 `refresh`；有新增则 `_run_vndb_match(new, _vndb_cancel)` 自动匹配
- `cancelMatch()`

### 元数据匹配
- `_run_vndb_match(games, cancel_event)`：设 `_batch_ctx` → `manager.match_vndb_for_games(..., cover_cb=self._queue_cover)` → `refresh_delta(ids)`（**增量**，避免全量重建导致封面重新淡入）→ `notify` 结果
- `_vndb_progress`：`start` 忽略；`done+1`；每 3 条 `notify` 一次（节流）
- `getBatchProgress()`：读 `_batch_ctx` 返回 `{running,type,total,done}`
- `matchVndb(id)`（单游戏，force=True，复用批量进度条）/ `matchVndbBatch(ids_json)`
- `selectExe()`

### 多源搜索 / 手动应用
- `searchMetadata(keyword, sources_json="")`（→ `multi_source.search_metadata`）/ `getMetadataSources()` / `saveMetadataSources(sources_json)`（写 config 即时生效）
- `applyCandidate(game_id, candidate_json, fields_json="")`：`fields_json` 非空 → 只应用**勾选字段**；为空 → 旧行为（仅填空字段）。封面下载到 `covers/{id}_ms.ext`。变更则 `update_game` + `reloadCover` + `refresh_delta`

### 截图
- `updateScreenshotHotkey(hotkey)`：写配置 + 立即重注册（`utils.hotkeys`）
- `takeScreenshot(game_id)`（详情页手动）/ `takeScreenshotRunning()`（**热键**，无运行游戏存 `_unsorted`）
- `_running_pid()`：`launcher.get_game_pid()`（真游戏 pid）；`_running_game_hwnd()`：按 pid 找主窗口
- `_push_screenshot_toast`：全屏时先提示「建议窗口化」（独占全屏下 overlay 不可见）；否则 `OverlayClient.show(hwnd, path, title)`
- 查看：`getScreenshots` / `getScreenshotThumb`（缩略图 data URI，旧图按需生成兜底）/ `getScreenshotOriginal`（原图，>8MB 拒载）
- 操作：`deleteScreenshot` / `renameScreenshot` / `openScreenshotFolder`（explorer /select）/ `copyScreenshotToClipboard`（PIL→BMP→去 14 字节头→`CF_DIB`）

### 封面更换
- `pickCover()`：选图，返回 `{path, preview}` / `setCover(game_id, path)`：拷到 `covers/{id}_manual.ext` → `update_game` → `reloadCover`

### 刷新封装（供内部与少数外部调用）
- `refresh()` → `games`；`refresh_delta(ids)` → `games_delta`；`notify(msg)` → `toast`
- `reloadCovers()`（清全部缓存 → `covers`，仅批量封面变化用）；`reloadCover(id)`（定向失效该卡缓存 → `cover`）

### 封面异步下载（与匹配解耦）
- `_queue_cover(game_id, url, dest)`：`_cover_pool.submit(_download_cover_bg, ...)`
- `_set_cover_progress(game_id, pct)`：更新 `_cover_states` 后推送**全量快照**（`pct=None` 表示移除）
- `_download_cover_bg`：`vndb_client.download_cover(progress_cb=_pc)`；成功且库中 `cover_path` 仍空则写库 + `reloadCover`；成功/失败都移除进度；**不重试**
- 线程池 `max_workers = cover_download.max_concurrent`（默认 4，**改后重启生效**）

### 运行状态回调
- `_on_game_start` → `running=id` + `refresh_delta`；`_on_game_exit` → `running=""` + `refresh_delta`

### 窗口控制
- `windowMinimize` / `windowToggleMaximize`（frameless 下 restore 用 Win32 `SW_RESTORE`，按 `WINDOW_TITLE` FindWindow）/ `windowMaximize` / `windowRestore` / `windowClose`（先 `overlay_client.quit()` 再 `destroy`）
- 拖拽：`windowStartDrag`/`windowMoveDrag`/`windowEndDrag`（锚点 + 鼠标全局坐标）
- 缩放：`windowResizeStart` + `windowResize(direction, dx, dy)`（起始几何 + 累计位移；最小 900×620；最大化时忽略）

---

## 前端调用约定（速查）

```js
// ts/core.ts 的 bridge Proxy 封装 window.pywebview.api.*
const games = JSON.parse(await bridge.getGames());
const { ok } = JSON.parse(await bridge.launch(id));
// 后端主动刷新 → window.__app.*（由 UISync 推送）
```

**联动点**：新增前端刷新域 → `sync.py::_DOMAIN_JS` 加一行 + 前端 `window.__app` 实现对应方法；新增桥方法 → 前端 `pywebview.d.ts` 补类型。
