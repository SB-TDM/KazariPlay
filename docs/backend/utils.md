# utils/ — 工具层

> 最底层，不依赖业务模块。核心：路径、配置、网络客户端（VNDB/Bangumi/YMGal）、标题归一化、热键、日志。

---

## path_utils.py — 路径与数据目录

**定位**：应用数据目录、DB、配置、日志、截图目录；含不可写降级与旧数据迁移。

- `get_app_data_dir(app)`：优先 `%APPDATA%\KazariPlay`（非 Windows `~/.kazariplay`）；**写测试**（`_is_writable`：建+写+删）失败则降级项目 `data/`。结果缓存 `_writable_cache`。
- 环境变量 **`KAZARIPLAY_DATA_DIR`** 覆盖数据根（试用包隔离用）：设置了则强制用该目录（不可写直接抛错，不降级）。
- `get_default_db_path` → `<data>/games.db`；`get_default_config_path` → `<data>/config.json`；`get_default_log_dir` → `<data>/logs`。
- `get_screenshots_dir()`：`KAZARIPLAY_DATA_DIR` 下 `screenshots/`，否则**项目根** `screenshots/`（`utils/path_utils.py` 上三级）。
- `get_game_screenshots_dir(game_id)`：`screenshots/{game_id}/`。
- `migrate_data_if_needed()`：仅当降级到项目目录时，把旧 `%APPDATA%\MinatoLauncher` 数据拷入（不覆盖）。

---

## config.py — 配置

**对象**：`Config`（`@singleton`）；`self._path`、`self._data`。

- `DEFAULT_CONFIG`：`theme`(light)、`hotkeys{screenshot=f12,...}`、`disguise_scene`、`show_console`、`cover_size`、`language`、`log_level`、`overlay{enabled,exe_path,toast_duration=3.0,position}`、`metadata_sources{single,mixed[vndb,bangumi]}`、`cover_download{timeout=90,max_concurrent=4}`。
- `load()`：存在则读，**深合并默认值**（`_deep_merge`，旧配置缺的新嵌套字段自动补默认）；不存在则写默认。损坏（JSON 错）回退默认。
- `get(key, default)` / `set(key, value)`：**支持点号嵌套键**（如 `hotkeys.screenshot`）。
- `get_all()`（浅拷贝）/ `save()` / `reset()`（保留实验版遗留段）/ `path`。

**注意**：改设置后需显式 `save()`；`setTheme` 在桥内即时保存。

---

## logger.py — 日志

`get_logger(name="KazariPlay", level="INFO")` → 文件 + 控制台 handler（`_setup_handlers`，日志目录 `get_default_log_dir()`）；`set_level(level)` 全局调级（读 `log_level` 配置）。各模块顶部 `logger = get_logger()` 复用。

---

## singleton.py — 单例装饰器

`@singleton` → `get_instance(*args, **kwargs)`：按类缓存实例，`__new__` 复用。用于 `Config`。

---

## proxy_utils.py — 网络 opener

`get_system_proxies()`：读系统代理；`get_opener()`：构建 `urllib` opener（各网络客户端统一走它，支持代理）。

---

## time_utils.py — 时间

- `format_play_time(minutes)`：分钟 → 可读文本。
- `format_relative_time(iso_str, now=None)`：ISO → 「刚刚/N 分钟前/N 小时前/N 天前/日期」。（`_game_dict` 用它生成 `last_text`。）

---

## title_utils.py — 标题归一化（联动核心）

`normalize_title(title, *, for_identity=False) -> str`

**两种模式**
- **搜索模式**（`for_identity=False`，供 `metadata_matcher` 清洗 VNDB 查询词）：按序去掉——开头平台前缀 `PC/PC+krkr`、开头 `[...]/(...)` 来源标签、`_xxx` 后缀、版本号（`v1.02/Ver1.02/(1.02)`）、语言/汉化后缀（`DL版/简体/繁体/汉化版/中文版`）、副标题 `～…～`、`第X章/Chapter X`。
- **identity 模式**（`for_identity=True`，供 `game_scanner._make_identity`）：**保守**——只去掉明确的汉化组/语言噪声，**保留章节、副标题、未知下划线后缀**（避免把「系列 第一章/第二章」归一成同一键）。

**常量**：`_LANG_SUFFIX = (?:DL版|简体版|繁体版|汉化版|中文版|完结版|官方中文|民间汉化)`。

**示例**：`PC+krkr[ぱれっとクリア]少女领域_默示汉化组` → 搜索模式 `少女领域`。

**联动**：改归一化规则会同时影响 VNDB 搜索与判重，须同步验证 `_backfill_identity`。

---

## image_safe_loader.py — 安全图片加载

`safe_load_pixmap(path, max_dimension)` / `safe_load_pixmap_scaled(...)` → `QPixmap | None`：带尺寸上限的安全加载（历史 Qt 残留；原版主要用 PIL，此模块保留兼容）。

---

## hotkeys.py — 全局热键

**仅截图热键**（默认 `f12`，`keyboard` 库；缺失/失败静默降级，截图仍可由前端按钮触发）。
- `register_screenshot_hotkey(callback)`：可重复调用（先 `remove_hotkey` 旧的再注册）；`_normalize`（小写去空格，兼容 `Ctrl + Shift + P`）。
- `reconfigure_screenshot_hotkey()`：设置改热键后调用，**立即生效无需重启**（`WebBridge.updateScreenshotHotkey` 触发）。

---

## vndb_client.py — VNDB 客户端

**端点**：`POST https://api.vndb.org/kana/vn`（搜索）、`https://t.vndb.org`（封面 CDN）。`User-Agent: KazariPlay/1.0`。

**常量**：`_REQUEST_TIMEOUT=15`、**`_COVER_TIMEOUT=90`**（CDN 单张 15~35s，余量给足）、`_MAX_RETRIES=2`、`_RETRY_BACKOFF=2`。

**异常**：`VndbError`。`_should_retry(exc)`：仅超时/连接重置/DNS 等临时网络错误可重试；**HTTPError(4xx/5xx) 不重试**。
`_request_with_retry(send, cancel_event, retries)`：退避 `2*(attempt+1)` 秒（可唤醒 `wait`，取消立即抛）；`retries=0`（封面默认）不重试。

**搜索**
- `search_vn(title, count=5, cancel_event=None) -> List[dict]`：`filters=["search","=",title]`，`sort="searchrank"`，fields 含 `id,title,alttitle,image.url,rating,description,released,length_minutes,developers.name`；失败返回 `[]`（不抛）。
- `search_first_vn(title, cancel)`：取第一条（自动选策略）。
- `search = search_vn`：**multi_source 统一入口**（`client.search(keyword, count=...)`）。
- `_parse_vn_item(item)`：`vndb_id`（补 `v` 前缀）、`title`（**优先 alttitle 日文原名**）、`cover_url`、`rating`（0-100 → round/20 → 0-5，<1 归 0）、`description`（`_clean_html` 去 BBCode/HTML 实体）、`developer`（developers 名字拼接）、`released`、`length_minutes`。

**封面**
- `download_cover(cover_url, dest_path, cancel_event=None, timeout=None, retries=0, progress_cb=None) -> bool`：`timeout` 缺省读 `cover_download.timeout`（**改设置即时生效**）；`_http_get` 按 `Content-Length` 分块上报 `progress_cb(read/total)`（0.0~1.0）；写入后校验非空。
- `rate_limit_sleep(seconds=1.0)`：VNDB 推荐间隔（本模块不做限速，节奏由调用方控制）。

---

## bangumi_client.py — Bangumi 客户端

`BangumiError`；`search(keyword, count=5)` / `search_subjects(keyword, limit=5)` → 统一候选（`_parse_subject`）；`download_cover(url, dest) -> bool`；`_http_get_json`/`_http_get`。状态 `ready`。

---

## ymgal_client.py — 月幕客户端

`YmgalError`；`search(keyword, count=5)` → 统一候选（`_parse_game`）；`download_cover`；`_request` / `_get_token` / `_auth_headers`（需 token）。状态 `experimental`（受地区/IP 影响）。

---

## 依赖速查

```
config ◀── 所有需要配置的模块（config/path/logger/hotkeys/multi_source/overlay_client/vndb_client）
path_utils ◀── db_manager / config / logger / screenshot_service / web_bridge
vndb_client ◀── metadata_matcher / multi_source
title_utils ◀── game_scanner / metadata_matcher
proxy_utils ◀── vndb/bangumi/ymgal client
hotkeys ◀── main.py（注册）/ web_bridge（重配）
```
