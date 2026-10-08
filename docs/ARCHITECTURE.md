# KazariPlay 架构总览

> 本文是项目**总览**：分层、核心对象、主要数据流、生命周期与前端内联机制。
> 各板块的逐模块细节见 [`backend/`](backend/README.md)、[`frontend/`](frontend/README.md)、[`overlay.md`](overlay.md)。
> 适用：无翻译原版 `develop`（Python + pywebview + 独立 C++ overlay）。

## 1. 定位与分层

KazariPlay 是视觉小说/Galgame 本地库启动器：扫描与管理本地游戏、VNDB/Bangumi 等元数据匹配、封面管理、WGC 截图（含游戏内 toast）。翻译实验能力已从原版移除，保留在 `feature/hook-translation` 分支。

```
┌─────────────────────────────────────────────────────────────┐
│  前端（WebView2 渲染，运行时内联的单个 HTML）                    │
│  TypeScript 源 ts/  ──tsc──▶  js/  ──main.py 按清单内联──▶ HTML   │
│  css/（@import 展开）  partials/（分块 HTML）                    │
└───────────────▲───────────────────────────┬─────────────────┘
                │ window.pywebview.api.*     │ window.__app.*（UISync 推送）
                │ （Promise/回调）            │
┌───────────────┴───────────────────────────▼─────────────────┐
│  桥接层 ui/                                                    │
│  web_bridge.WebBridge（js_api，全部前后端能力入口）             │
│  ui.sync.UISync（「数据变化 → 前端刷新」事件域总线，合并推送）    │
└───────────────▲───────────────────────────┬─────────────────┘
                │                            │
┌───────────────┴───────────────────────────▼─────────────────┐
│  业务层 core/                                                  │
│  GameManager（门面）→ scanner / launcher / monitor /          │
│                       metadata_matcher / multi_source /      │
│                       screenshot_service / overlay_client    │
│  Game（数据类）                                                │
└───────────────▲───────────────────────────┬─────────────────┘
                │                            │
┌───────────────┴───────────────────────────▼─────────────────┐
│  数据层 database/ + 工具层 utils/                              │
│  db_manager（SQLite 单例）+ game/collection/tag repository    │
│  config / logger / path_utils / vndb/bangumi/ymgal client …  │
└──────────────────────────────────────────────────────────────┘

          独立进程：overlay/overlay.exe（C++，命名管道 IPC）
          ← OverlayClient（Python 侧）      截图 toast / 字幕（实验）
```

## 2. 核心对象

| 对象 | 文件 | 职责 |
|---|---|---|
| `Game` | `core/game_model.py` | 游戏数据类（dataclass），字段含 `id/title/exe_path/folder/engine/identity/vndb_id/...`；与 DB 行互转 |
| `GameScanner` | `core/game_scanner.py` | 目录扫描 + 引擎识别 + 主 exe 选择 + `identity` 生成 |
| `GameLauncher` | `core/game_launcher.py` | 启动/关闭游戏进程、子进程树追踪、自定义启动路径 |
| `GameMonitor` | `core/game_monitor.py` | 运行中游戏的生命周期监控（存活检测、退出回调、计时） |
| `GameManager` | `core/game_manager.py` | **门面**：聚合上面各子模块，对桥暴露统一接口 |
| `metadata_matcher` | `core/metadata_matcher.py` | VNDB 单/批量匹配（标题归一化、搜索回退、字段保守合并、封面回调） |
| `multi_source` | `core/multi_source.py` | 多源（VNDB/Bangumi/YMGal）搜索、合并去重、整体超时 |
| `screenshot_service` | `core/screenshot_service.py` | 截图内核（WGC → PrintWindow → 全屏回退）+ 原图/缩略图双保存 |
| `OverlayClient` | `core/overlay_client.py` | C++ overlay 进程的单例客户端（命名管道长连接，懒启动） |
| `WebBridge` | `ui/web_bridge.py` | pywebview `js_api`：前端可调用的全部方法 |
| `UISync` | `ui/sync.py` | 事件域总线：后端变化 → 合并后推 `window.__app.*` |
| `DatabaseManager` | `database/db_manager.py` | SQLite 单例：建表/迁移/连接/事务 |
| `*Repository` | `database/*.py` | games / collections / tags 的数据访问 |

## 3. 主要数据流

### 3.1 启动
```
main.py
 → Config()（读 %APPDATA%\KazariPlay\config.json）
 → GameManager()（迁移 DB、回填 identity）
 → WebBridge(manager)
 → 注册全局截图热键
 → 设置 WebView2 启动参数（内存优化）
 → webview.create_window(html=_load_html())  # css/js/partials 内联
 → webview.start()（之后前端 init → 拉数据）
```

### 3.2 扫描（用户主动触发）
```
前端「扫描游戏文件夹」→ bridge.scanFolder()
 → 弹目录选择 → 后台线程 _do_scan
 → GameManager.scan_and_add(folder)
   → GameScanner.scan()（os.walk；含 exe 的目录识别为游戏根并剪枝子树）
   → 判重：exe_path 命中 或 identity 命中 → 跳过（skipped）
   → repository.add()（新的入库）
 → 进度：UISync scan_progress 域
 → 完成后：自动触发 VNDB 批量匹配（后台）
```

### 3.3 元数据匹配
```
扫描后自动 / 右键单游戏 / 批量
 → GameManager.match_vndb_*()
   → metadata_matcher.match_batch()（逐游戏，每游戏多关键词回退）
     → vndb_client.search_first_vn()（api.vndb.org，~1s/次）
     → 命中 → 保守更新字段 → 封面通过 cover_cb 交给调用方异步下载
 → 写回 DB → UISync games_delta 刷新卡片
 → 封面：WebBridge 线程池后台下载（可配超时/并发）→ 完成 reloadCover + cover_progress 进度
```

### 3.4 启动游戏 / 截图
```
前端 launch → bridge.launch(id) → GameLauncher 启进程 → GameMonitor 计时
 → 截图热键 → screenshot_service（WGC 等）
 → overlay.exe：截图 toast（命名管道，OverlayClient 懒拉起）
```

### 3.5 前端刷新（UISync）
```
后端某线程：ui.invalidate("games_delta", [ids])
 → UISync 合并（50ms）→ evaluate_js("window.__app.applyGamesDelta([...])")
 → 前端对应模块局部更新（不重建整个网格）
```
事件域映射见 `ui/sync.py` 的 `_DOMAIN_JS`：`games / games_delta / covers / cover / screenshots / scan_progress / batch_progress / cover_progress / toast / running`。

## 4. 前端内联机制

- `ts/` 是**唯一真相**，`tsc` 编译到 `js/`（gitignore）；`main.py` 的 `_JS_MANIFEST` 按依赖顺序把 `js/*.js` 内联为多个 `<script>`。
- `partials/*.html` 由 `_PARTIAL_MANIFEST` 注入到 `index.html` 的 `<!-- PARTIALS -->`（顺序即 DOM 层叠顺序，设置窗口最后）。
- `css/style.css` 是 `@import` 入口；`main.py` 启动时**递归展开 @import** 内联为单个 `<style>`。
- 桥调用统一走 `core.ts` 的 `bridge` Proxy（`window.pywebview.api.*`，支持 `bridge.xxx(args, cb)` 回调风格）。

## 5. 数据与文件位置

| 数据 | 位置 |
|---|---|
| 数据库 `games.db` | `%APPDATA%\KazariPlay\games.db`（不可写时降级项目 `data/`） |
| 配置 `config.json` | `%APPDATA%\KazariPlay\config.json` |
| 封面 | `%APPDATA%\KazariPlay\covers\`（VNDB：`{id}_vndb.jpg`；多源：`{id}_ms.*`） |
| 日志 | `%APPDATA%\KazariPlay\logs\` |
| 截图（原版） | 项目根 `screenshots\{game_id}\`（原图 + `thumbs/` 缩略图） |
| 试用包数据 | 包旁 `data/`（`KAZARIPLAY_DATA_DIR` 指定，隔离正式库） |

## 6. 生命周期与线程

- **单任务门禁**：扫描 / 单匹配 / 批匹配共用 `_start_task` 门禁，一次只跑一个；各自独立取消事件。
- **后台线程**：扫描 `_do_scan`、匹配 `_run_vndb_match`、封面池 `_cover_pool`（`ThreadPoolExecutor`，可配并发）。
- **UISync**：`threading.Timer`（50ms 合并）+ `evaluate_js` 串行化，任意线程可调用。
- **overlay 进程**：懒启动（首次需要时），窗口关闭时退出。
- **关闭窗口**：`closing` 事件 → 停 overlay。

## 7. 目录与约定（速查）

- `core|database|ui|utils`：后端；`ui/web_bridge.py`=桥，`ui/sync.py`=刷新总线。
- `overlay/`：C++ 注入层（原版仅截图 toast；翻译链路在实验分支）。
- `scripts/`：`package_develop.py`（隔离试用包）、`develop.spec`、`runtime_portable.py`。
- `tests/`：`test_*`（单测/回归）、`smoke_*`（冒烟）、`verify_frontend.py`（前端组装校验）。

## 8. 关键约束（来自工作约束）

- 用户数据不能因打包/更新丢失（`docs/DEV_RULES.md`）。
- 前端只改 `ts/` 源，`js/` 为编译产物；新增模块登记 `_JS_MANIFEST`。
- 联动点需同步：`identity` 判重 ↔ `title_utils`；UISync 域 ↔ 前端 `__app`；DB schema ↔ `db_manager` 建表迁移。
