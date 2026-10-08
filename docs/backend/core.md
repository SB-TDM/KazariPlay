# core/ — 业务层

> 业务核心。由 `GameManager` 门面聚合：扫描、启动、监控、元数据匹配、多源搜索、截图、overlay。
> 数据用 `Game` 对象在 core↔database 间传递；所有前端刷新经 `ui/sync.py`（见 [ui-bridge.md](ui-bridge.md)）。

---

## game_model.py — 数据模型

**对象**：`@dataclass Game`

**定位**：一款游戏的完整元信息，是与数据库行互转的载体（`to_dict`/`from_dict`）。

**关键字段分组**
- 标识：`id`（exe 路径 MD5 前 16）、`title`、`exe_path`、`folder`、`engine`、`identity`
- 资产：`cover_path`、`logo_path`
- 状态：`is_favorite`、`play_count`、`play_time`（分钟）、`last_played`、`date_added`、`rating`
- 展示：`description`
- 启动：`launch_exe_path`（自定义启动 exe，空则回退 `exe_path`）
- VNDB 元数据：`vndb_id`、`released`、`developer`、`length_minutes`
- 归类：`tags`（兼容旧字段）、`collections`（`[{id,name,color,icon}]`）、`category_id`
- 实验版兼容字段（原版不启用）：`hook_code`、`hook_code_custom`、`translate_enabled`、`clean_filter_override`

**方法**
- `to_dict()`：序列化（`tags` 列表 → 逗号串；bool → 0/1），供 repository 写库
- `from_dict(data)`：反序列化（逗号串 → 列表；空值归一）
- `add_tag/remove_tag`：内存内标签增删（去重）
- `format_play_time()`：分钟 → 「N 分钟 / N 小时 M 分钟 / N 天 M 小时」

**注意**：`identity` 由 scanner 生成，不用 `title`（title 会被 VNDB 覆盖）。

---

## game_scanner.py — 扫描器

**对象**：`GameScanner`

**定位**：给定目录树，识别出游戏（**一个文件夹 = 一个游戏**）。

**核心规则**
- **整棵树规则**：某目录含合法游戏 exe → 视为游戏根，`dirs.clear()` 剪枝其所有子孙目录（同一游戏只识别 1 个，避免 eden* 这类多子目录被拆成多个）。
- **exe 过滤**：扩展名 `.exe`；命中 `ignore_patterns`（安装/卸载/补丁/存档工具/查看器/汉化补丁/UnityCrashHandler 等）剔除；`whitelist_exact` 白名单优先保留。
- **目录过滤**：`_is_ignored_folder` 跳过 `补丁/备份/patch/backup/副本/smartsteamemu/...`。
- **主 exe 选择** `_pick_primary_exe`：① 汉化启动器优先（`CHS_KEYWORDS`）② 同池体积降序 ③ 文件名排序。
- **标题** `_generate_title`/`_clean_title`：用 exe 父文件夹名，保守清洗（去开头 `PC`/`【来源】`、结尾 `_汉化版/官方中文/全年龄` 等），清空则回退原名。
- **引擎识别** `_detect_engine`（可靠性降序）：
  1. 特征文件（最可靠）：`renpy`/`.rpyc`→renpy；`UnityPlayer.dll`/`managed`→unity；`www/data`→rpg_maker；`.xp3`→kirikiri；`sysgrp.arc+sysprg.arc+BGI.exe`→bgi；`tyrano`→tyrano
  2. exe 完整名匹配（`ENGINE_PATTERNS[*].exact`，如 `Game.exe`→rpg_maker）
  3. exe 子串匹配（`substr`）
  4. 都不中 → `"其他"`

**方法**
- `scan(folder_path, recursive=True, progress_cb=None, cancel_event=None) -> List[Game]`：`os.walk` 收集每目录合法 exe（缓存 `files` 供引擎检测复用）→ 逐目录选主 exe → `_check_file` 建 `Game`。`progress_cb(dirs_scanned, games_found)`。
- `_make_identity(engine, folder_name) -> str`：`f"{engine.lower()}|{normalize_title(folder_name, for_identity=True).lower()}"`。**identity 的规范来源**。
- `_generate_id(exe_path)`：`md5(exe_path)[:16]`。

**依赖**：`core.game_model.Game`、`utils.title_utils.normalize_title(for_identity=True)`。

**注意**：identity 用文件夹名（稳定），不能用 title（会被 VNDB 覆盖导致重扫对不上）。改归一化须同步 `_backfill_identity`。

---

## game_launcher.py — 启动器

**对象**：`GameLauncher` + 一组 Win32 辅助函数

**定位**：启动/关闭游戏进程；处理「启动器拉起真游戏」的进程树追踪。

**关键机制**
- **子进程树追踪** `_trace_loop`（后台线程 `GameTrace`）：部分游戏经 SmartSteamEmu/安装器拉起真 exe，启动器随后退出 → 追踪其整棵后代（BFS `_collect_descendants`），优先选**有可见顶层窗口**者（`_has_visible_window`，排除 `_NON_GAME_EXES` 控制台进程），填入 `current_game_pid`。超时 `_GAME_SPAWN_TIMEOUT=10s`，轮询 `0.3s`。
- **关闭** `close()`：收集追踪到的进程 + 后代，用**创建时间**校验身份（`_process_creation_time`），避免误杀 PID 复用的无关进程；逐个 `_terminate_pid`。无法确认身份则保留运行状态并返回 False。
- **启动** `launch(game, extra_args)`：`cwd=game.folder`，`CREATE_NEW_CONSOLE`（krkr/Ren'Py 相对路径定位必需）；先 `close()` 已有游戏。

**关键字段**：`current_process`（Popen）、`current_game_id`、`current_game_pid`（真游戏 pid）、`_game_creation_time`、`_tracked_processes`、`_target_ready`。

**方法**：`launch` / `close` / `is_running` / `get_game_pid` / `wait_for_game_pid`（等目标就绪，防返回旧目标）/ `get_runtime`（分钟）。

**注意**：截图/存活检测都应基于 `current_game_pid`，不是 `current_process.pid`。

---

## game_monitor.py — 监控器

**对象**：`GameMonitor`

**定位**：后台线程监控运行中游戏，累计游玩时长，触发事件。

**构造**：`GameMonitor(repository, launcher, tick_interval=2)`；`EVENTS = ("on_start","on_tick","on_exit")`。

**逻辑** `_monitor_loop`：每 `tick_interval` 秒（默认 2s）检测 `launcher.is_running()`；结束 → `on_exit`。运行时长按**实际秒数**累积，每满 60s 调 `repository.increment_play_time(game_id, minutes)` 写库，并 `on_tick`。

**方法**：`register_callback(event, cb)` / `start(game_id)` / `stop()`（显式停止也触发 `on_exit`，幂等）/ `is_monitoring` / `get_runtime_seconds`。

**依赖**：由 `GameManager` 注入 repository + launcher；`on_exit` → `repository.record_play`。

---

## game_manager.py — 门面

**对象**：`GameManager`

**定位**：聚合 scanner/launcher/monitor/repository/tag_repo/collection_repo，对桥暴露统一接口。

**构造**：先 `DatabaseManager(db_path)`（单例固定用户目录），再建各 repo；`repository.set_process_checker(launcher.is_running)`；注册 `on_exit → record_play`；最后 `_backfill_identity()`（按文件夹名重算历史 identity，幂等）。

**方法分组**
- 查询：`get_all_games` / `get_game` / `get_favorites` / `search` / `get_count` / `get_statistics`（总时长、收藏数、按引擎分布）
- 扫描：`scan_and_add(folder, progress_cb, cancel_event) -> (added, new_games, skipped)`
  - 判重① `repository.get_by_path(exe_path)` ② `repository.get_by_identity(identity)` → 命中即 `skipped`
- 增删改：`add_game` / `delete_game`（→ `batch_delete([id])==1`）/ `update_game`（保留 play_count/play_time/last_played/date_added/is_favorite/rating，标签同步关联表）
- 状态：`set_favorite/toggle_favorite/set_rating/rename_game`
- 标签/分类：委托 `tag_repo`
- 批量：`batch_add_tag/batch_remove_tag/batch_set_category/batch_set_favorite`（`db.execute_many` 单事务）、`batch_delete`（运行中先 `close_game`）
- 收藏夹：委托 `collection_repo`（`get_collections_tree/create/update/delete/reorder/...`）
- 启动：`launch`（先关已有 → launcher.launch → monitor.start）/ `close_game`（先关进程再停监控，保证 `on_exit` 时进程已结束）/ `is_game_running` / `get_running_game` / `get_running_runtime`
- 匹配：`match_vndb_metadata(game_id,...)` / `match_all_vndb_metadata(...)` / `match_vndb_for_games(games,...)` — 均委托 `metadata_matcher`，成功后按 `vndb_id` 存在则 `update_game` 写回

**注意**：`delete_game` 只删记录与关联（保留磁盘文件），重扫可加回。

---

## metadata_matcher.py — 元数据匹配

**模块级函数**（非类）

**定位**：VNDB 标题归一化搜索 → 多关键词回退 → **保守合并**字段 → 封面回调。

**`match_single(game, force=False, cancel_event=None, cover_cb=None) -> (status, msg)`**
- 有 `vndb_id` 且非 force → `("skip", ...)`
- 关键词策略（依次尝试）：`normalize_title(title)` → `_extract_japanese(title)`（提取最长 CJK 片段，排除汉化/版本词）→ 原标题
- 命中后**保守更新**：`title` 无条件用 VNDB 正式名覆盖；其余字段仅在本地为空时填（`description/rating/released/developer/length_minutes`）
- 封面：本地空且有 `cover_url` → 有 `cover_cb` 则异步 `cover_cb(game_id, url, dest)`（不阻塞匹配）；否则同步 `vndb_client.download_cover`
- `status ∈ {"skip","match","fail","cancelled"}`

**`match_batch(games, force, progress_cb, cancel_event, cover_cb) -> (matched, skipped, failed)`**
- 逐游戏 `match_single`；`progress_cb(game_id, title, status, msg)`（"start" 与结果各一次）；`cancelled` 不计入且停止

**`_cover_dest_path(game_id, cover_url)`**：`covers/{game_id}_vndb.{jpg|png|webp}`。

**进度回调签名**：`callback(game_id, game_title, status, message)`。

---

## multi_source.py — 多源搜索

**模块级函数 + `SOURCES` 注册表**

**定位**：统一 VNDB/Bangumi/YMGal 等源，混合检索、合并去重、整体超时。

**注册表 `SOURCES`**：`{id: {name, icon, status, client}}`；`status ∈ ready/experimental/pending`（pending 无 client，占位）。新增源在此登记，设置页自动出现。

**配置**：`metadata_sources.mixed`（用户勾选），`get_mixed_sources()` 自动剔除未注册/无 client 的源。

**统一候选字段**：`source / source_id / title / alt_title / cover_url / description / developer / released / rating(0-5) / length_minutes / tags / source_icon / source_name`。

**`search_metadata(keyword, sources=None, limit_per_source=5) -> List[dict]`**
- 单源：顺序调用
- 多源：`ThreadPoolExecutor` 并发发起；`as_completed(timeout=_SEARCH_DEADLINE=30s)`，超时返回已完成部分；`shutdown(wait=False)` 不等慢源；完成后按源配置顺序还原
- 去重 `_dedupe`：先 `(source, source_id)` 精确，再标题归一化模糊；保留先到源顺序

**`download_cover(candidate, dest_path)`**：按 `candidate.source` 找对应 client 下载。

**配置读取**：`Config().get("metadata_sources")`。

---

## screenshot_service.py — 截图服务

**模块级函数**

**定位**：Steam 式截图——按游戏窗口捕获（非全屏），三级回退，原图 + 缩略图双保存。

**捕获内核**（`take_screenshot`）
1. `_capture_via_wgc(pid)`：Windows Graphics Capture（`windows-capture`），兼容 D3D/Vulkan 独占渲染；独立线程跑消息循环，`_WGC_TIMEOUT=8s`；BGRA→RGB 注意通道（`[:, :, [2,1,0]]`，不能整块反转）；按 `_client_physical_offset` 裁剪掉标题栏/边框（DPI 感知分支处理）
2. `capture_game_window(pid)`：GDI `PrintWindow`（`PW_RENDERFULLCONTENT`），客户区尺寸
3. `ImageGrab.grab()`：全屏兜底

**保存**：原图 `screenshots/{game_id}/shot_{时间戳}.png`；缩略图 `thumbs/{名}_thumb.jpg`（`_make_letterbox_thumb`：512px 宽 + 屏幕同比例画布，等比缩放居中，留黑边不拉伸，JPEG q85）。`_unsorted/` 兜底。

**其它**：`get_screenshots`（只列原图，时间倒序）、`rename_screenshot`/`delete_screenshot`（路径穿越校验，连带缩略图）、`find_main_window_by_pid`（EnumWindows，顶层/可见/有标题）。

**触发**：`main.py` 全局热键（webview 不提供全局热键）。

---

## overlay_client.py — Overlay 客户端

**对象**：`OverlayClient`（单例，`__new__` + 类锁）

**定位**：C++ `overlay.exe` 的命名管道长连接客户端；懒启动、常驻，截图 toast 用；失败静默降级不影响截图保存。

**管道**：`\\.\pipe\KazariPlayOverlay_{os.getpid()}`；双向长连接 + 读线程 `_read_loop`（重叠 ReadFile，检测服务端断开）。

**进程**：`_resolve_exe(is_x64)` → `overlay/bin/overlay.exe`（x64）或 `bin32/`（x86），支持 `overlay.exe_path` 覆盖与打包 `_MEIPASS`；`_ensure_process` 位数不符时先停旧进程；`CREATE_NO_WINDOW`。

**方法**：`enabled`（`overlay.enabled`）/ `ensure_bidirectional(is_x64)` / `show(game_hwnd, png_path, title)`（读 `overlay.toast_duration`）/ `hide()` / `quit()`；`_send_long(payload)` 线程安全写 JSON。

**注意**：`FILE_FLAG_OVERLAPPED` 与 `GENERIC_WRITE` 同值（`0x40000000`），必须放在 `dwFlagsAndAttributes`（第 6 参），放 `dwDesiredAccess` 会被吸收。原版无字幕回传命令。

---

## 依赖速查

```
game_manager ─▶ scanner / launcher / monitor / repository / tag_repo / collection_repo
             └▶ metadata_matcher ─▶ vndb_client
launcher ◀── monitor（读进程状态）   launcher ─▶ repository.record_play（经 monitor 回调）
overlay_client ◀── web_bridge（截图 toast）
screenshot_service ◀── main.py（热键）/ web_bridge
```
