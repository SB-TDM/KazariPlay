# KazariPlay → C++ 全栈重写方案书

> **文档状态：未实施的历史方案。** 本仓库没有对应的 C++ 主程序工程；当前项目仍使用 Python + pywebview，C++ 仅负责独立 Overlay。本文保留为架构评估记录，不是当前构建入口。文档分类见 [docs/README.md](README.md)。

> 版本：V1.1 · 2026-08-19（含 M0–M6 实施路线图）
> 决策：**后端全部重写为 C++**，一步到位单原生 exe，取代「pywebview + Python 后端」；
> 前端（HTML/CSS/JS）~100% 复用，C++ overlay（截图 toast / 实时翻译）原样保留。
> 约束：重写期间**保留原项目 KazariPlay_V1.0 不动**，新代码独立成工程。

---

## 一、目标与核心判断

**一句话**：把现在 `python main.py` 启动的 pywebview 应用，替换为一个 **单一 C++ 原生进程（WebView2 渲染前端 + C++ 全量后端）**。

**与先前路线 B（Tauri/Rust 壳）的差异**：
| | 路线 B（Tauri 壳） | 本次（C++ 全栈） |
|---|---|---|
| 后端语言 | Python（保留） | **C++（全量重写）** |
| 壳 | Rust | 无（C++ 进程即壳） |
| 前端桥 | invoke→HTTP→Python | **WebView2 HostObject 直连 C++**（无需 HTTP 服务） |
| 运行时体积 | 中（Python sidecar） | 纯原生 |

**优劣判断（诚实版）**：
- 优点：**只守 C++ 一门语言**；单 exe；WebView2 即现有依赖；与已写好的 C++ overlay 无缝；工作量 ≈ Rust 路线，但避开学 Rust。
- 缺点：**~25 个 Python 后端模块需全部重写**（元数据客户端/扫描/匹配/监控/截图等），行为漂移风险高；C++ 迭代速度慢，单人长期维护后续加功能更累。

> 本方案按用户决策「立即全量重写」编制。全文在模块映射、桥接、数据兼容上给出可直接照做的技术路线。

---

## 二、目标架构

```
┌─────────────────────────────────────────────┐
│                  kazariplay.exe              │  （单一原生进程，C++）
│  ┌─────────────────────────────────────────┐ │
│  │  WebView2 (Edge WebView2 Runtime)       │ │
│  │   - frontend/html 静态资源              │ │
│  │   - JS bridge 代理 (core.js 单点)       │ │
│  └───────────────┬─────────────────────────┘ │
│                  │ HostObject / PostWebMessage│
│  ┌───────────────▼─────────────────────────┐ │
│  │  C++ Backend                            │ │
│  │  GameManager 门面（重写）               │ │
│  │  ├─ db/      SQLite                     │ │
│  │  ├─ net/     VNDB/Bangumi/YMGal 客户端  │ │
│  │  ├─ scan/    扫描+引擎识别+ID           │ │
│  │  ├─ launch/  启动+监控+耗时             │ │
│  │  ├─ shot/    截图+封面缩略图            │ │
│  │  └─ ipc/     与 overlay.exe 命名管道    │ │
│  └───────────────┬─────────────────────────┘ │
│                  │ 命名管道 (FILE_FLAG_OVERLAPPED)
│            ┌─────▼──────┐   ┌───────────────┐
│            │ overlay.exe │   │ texthook.dll │
│            │ (截图toast/ │   │ (注入游戏)    │
│            │  实时翻译)  │   │              │
│            └────────────┘   └───────────────┘
└─────────────────────────────────────────────┘
```

**关键设计选择**：用 **WebView2 HostObject（`AddHostObjectToScript`）或 `PostWebMessageAsJson`** 做前后端桥，因此**完全不需要本地方 HTTP/WebSocket 服务**——C++ 后端与 JS 经 WebView2 原生通道直连，比 Tauri/HTTP 路线更简洁。

---

## 三、工程目录结构

```
C++/  (新目录，独立于 KazariPlay_V1.0)
├── CMakeLists.txt                # 或 MSBuild .sln
├── kazariplay/
│   ├── main.cpp                  # WinMain：窗口 + WebView2 初始化 + 事件循环
│   ├── app.h/cpp                 # 应用上下文：GameManager 持有 + 生命周期
│   ├── bridge.h/cpp              # WebView2 桥（HostObject / WebMessage）
│   ├── window.h/cpp              # 无边框窗口 / 缩放 / 最小化 / 图标（沿用 V1.0 CSS 语义）
│   ├── db/
│   │   ├── db_manager.h/cpp      # SQLite 连接/建表/迁移
│   │   ├── game_repo.h/cpp
│   │   ├── collection_repo.h/cpp
│   │   └── tag_repo.h/cpp
│   ├── core/
│   │   ├── game_model.h          # Game 结构体（对齐 game_model.py）
│   │   ├── game_manager.h/cpp    # 门面，对齐 GameManager 暴露方法
│   │   ├── game_scanner.h/cpp
│   │   ├── game_launcher.h/cpp
│   │   └── game_monitor.h/cpp
│   ├── net/
│   │   ├── vndb_client.h/cpp
│   │   ├── bangumi_client.h/cpp
│   │   ├── ymgal_client.h/cpp
│   │   └── multi_source.h/cpp    # 混合源搜索 + 封面下载
│   ├── shot/
│   │   ├── screenshot.h/cpp      # BitBlt → WIC PNG
│   │   └── cover.h/cpp           # 缩略图生成（替代 PIL）
│   ├── ipc/
│   │   └── overlay_client.h/cpp  # 命名管道客户端（重叠 I/O），对齐 overlay_client.py
│   ├── util/
│   │   ├── config.h/cpp          # config.json 深合并
│   │   ├── hotkeys.h/cpp         # RegisterHotKey / 低层钩子
│   │   ├── path.h/cpp time.h/cpp log.h/cpp singletons
│   └── engine_policy.h/cpp
├── frontend/                     # 从原 KazariPlay_V1.0/kazari_play/ui/web_assets 拷贝
│   └── (index.html + css/ + js/ + partials/)
├── third_party/
│   ├── json.hpp                  # 已有（overlay 带）
│   ├── sqlite3.c/.h              # SQLite amalgamation
│   └── webview2/                 # Microsoft.Web.WebView2 NuGet
├── scripts/
│   ├── build.bat / build32.bat   # MSVC 编译
│   └── run.bat
└── tests/
```

---

## 四、Python → C++ 模块映射表

| Python（V1.0） | C++ 落点 | 要点 / 库 |
|---|---|---|
| `database/db_manager.py` | `db/db_manager` | SQLite C API（sqlite3），沿用同一 schema，数据零迁移 |
| `database/game_repository.py` | `db/game_repo` | sqlite3 封装；`_row_to_game` 用列名访问（避免列序漂移） |
| `database/collection_repository.py` | `db/collection_repo` | 树形/多对多 |
| `database/tag_repository.py` | `db/tag_repo` | |
| `core/game_model.py` | `core/game_model.h` | 转为 `Game` POD 结构体 |
| `core/game_manager.py` | `core/game_manager` | 门面，方法名与 WebBridge 对齐，便于桥接 |
| `core/game_scanner.py` | `core/game_scanner` | 目录扫描 + 引擎识别 + `_generate_id`/`_generate_title` |
| `core/game_launcher.py` | `core/game_launcher` | `CreateProcess` + 参数/工作目录 + `_is_process_x64` |
| `core/game_monitor.py` | `core/game_monitor` | 进程存活轮询 + 耗时累加 + on_exit 回调 |
| `core/metadata_matcher.py` | `net/` + 匹配逻辑 | VNDB 匹配启发式 + 限流 |
| `core/multi_source.py` | `net/multi_source` | 多源搜索 + 封面下载 |
| `utils/vndb_client.py` | `net/vndb_client` | WinHTTP + json |
| `utils/bangumi_client.py` | `net/bangumi_client` | |
| `utils/ymgal_client.py` | `net/ymgal_client` | |
| `core/screenshot_service.py` | `shot/screenshot` | BitBlt → WIC 编码 PNG；`find_main_window_by_pid` |
| `core/overlay_client.py` | `ipc/overlay_client` | 命名管道重叠 I/O（复用 overlay 的 pipe 思路） |
| `core/subtitle_coordinator.py` | 并入 C++（薄） | 翻译已在 overlay 内，本层透传配置 |
| `utils/config.py` | `util/config` | JSON 深合并（对齐 `_deep_merge`） |
| `utils/hotkeys.py` | `util/hotkeys` | RegisterHotKey / 低层键盘钩子 |
| `utils/path_utils.py` | `util/path` | `%APPDATA%\KazariPlay` 定位 |
| `utils/logger.py` / `singleton.py` / `proxy_utils.py` / `engine_policy.py` | `util/*` / `engine_policy` | 平移实现 |
| `ui/sync.py`（UISync 推送总线） | `bridge` 内推送通道 | HostObject 事件 / ExecuteScript（替代 evaluate_js） |
| `ui/web_bridge.py`（WebBridge，60+ 方法） | `bridge` | 桥接层：方法名保持 camelCase，JS 透明 |

**结论**：全部有明确落点和对应库，无不可移项；量级为「一整层重写」，非「不可行」。

---

## 五、前端桥设计（WebView2）

**原桥（pywebview）**：
- 请求：JS `pywebview.api.X(...args)`
- 推送：Python `window.evaluate_js(cmd)`

**新桥（WebView2）**：
- 用 `ICoreWebView2::AddHostObjectToScript` 暴露一个 COM HostObject `backend`，方法 `api(method, argsJson) -> (回调返回 result)`；
- 在 `core.js` 的 bridge 代理处统一改：`pywebview.api.X` → `backend.api('X', ...args)`（**单点改动**，其余 16 个 JS 模块不变；实现方式可与前端约定的 `window.__api` 封装对齐）；
- 推送：C++ 调 `ICoreWebView2::ExecuteScript(cmd)` 直接改写 `window.evaluate_js` 对应语义，`ui/sync.py` 的推送逻辑在 C++ 侧等价复刻；
- 文件对话框：`scanFolder/selectExe/pickCover` 由 `create_file_dialog` 改为 C++ `IFileDialog`（Common Item Dialog），桥方法返回值不变。

**可删除的兼容逻辑**：`main.py` 的 `_load_html()` 内联注入（css/js/partial 拼接、@import 展开、data-uri icon）不再需要——WebView2 用 `SetVirtualHostNameToFolderMapping` 静态映射本地 frontend 目录即可，天然规避 python webview 中文路径 `file://` 问题。

---

## 六、数据 / 配置兼容

- 沿用 `%APPDATA%\KazariPlay\games.db` 与 `config.json`，**schema 与路径完全一致 → 用户数据零迁移**。
- 截图目录 `/screenshots/{game_id}/` 与封面缩略图路径规则保持一致。
- config 深合并逻辑重写时逐项对齐 `_deep_merge`，避免老 config 缺嵌套字段丢失。

---

## 七、overlay（截图 toast / 实时翻译）保留

- `overlay.exe`（x64/x86）与 `texthook.dll` 原样作为独立进程使用，不并入主进程；
- 主程序 `ipc::OverlayClient` 用命名管道（`FILE_FLAG_OVERLAPPED` 重叠 I/O）连接，**注意进程内单例**（对齐 V1.0 修复记录 #9，避免截图 toast 与翻译会话抢占）；
- 因此**实时翻译 / 清洗 / 字幕 / 截图 toast 全保留**，只有「配置透传」从 Python 变 C++。

---

## 八、工具链与前置

| 项 | 状态 | 动作 |
|---|---|---|
| MSVC Build Tools 14.44 + C++ | ✅ 已装 | 直接用于主程序编译 |
| WebView2 Runtime | ✅ 已装 | WebView2 运行依赖 |
| Microsoft.Web.WebView2 NuGet | 待 | 项目引用 |
| SQLite amalgamation | 待 | 下载 sqlite3.c/.h 入 third_party |
| CMake 或 MSBuild | 按需 | 沿用 overlay 的 build.bat 风格亦可 |

---

## 九、实施路线图（M0 – M6）

### 9.1 总体思路

**一个理论先行的风险桥接 + 五条主工作流 + 七个里程碑。**

- **先做 M0（技术验证）**：把最容易出错的 WebView2 桥 + 目标架构先跑通。若 HostObject / `SetVirtualHostNameToFolderMapping` 桥走不通，立即回退到「本地 HTTP」桥，避免雕刻完成后才发现桥不可行。
- **按自底向上的依赖序推进**：数据 → 浏览 → 管理 → 游戏运行 → 元数据 → 截图/覆盖层 → 打包。
- **每条主工作流用 V1.0 做对拍基准**防行为漂移。

**必须保住的优势**：C++ overlay 管线原样复用；SQLite schema 与 `%APPDATA%` 路径不变 → 用户数据零迁移；前端 ~100% 复用，仅 `core.js` 单点改动。

**必须修掉的痛点**：双层语言 → 单 C++ 进程；拆掉超大门面（按 scan/play/metadata/shot 分域）；**先写核心逻辑测试再写实现**（尤其元数据匹配、扫描启发式）。

### 9.2 里程碑总表

| 里程碑 | 交付物 | 关键任务 | 验证方式 |
|---|---|---|---|
| **M0 技术验证** | 原生无边框窗 + WebView2 加载前端 + 桥跑通 | 建 `main.cpp` 窗、`SetVirtualHostNameToFolderMapping` 挂 frontend、HostObject 暴露 `backend.api`、`core.js` 接桥 | 空窗显示库骨架页，`invoke` 往返 + `ExecuteScript` 推送各验一次 |
| **M1 数据层 + 只读** | DB 封装 + Game 模型 + 门面雏形 | SQLite 建表/迁移（沿用 schema）、core 拆分 Domain、bridge 接 `getGames/getGame/getTags/getConfig` | 用 V1.0 的 `games.db` 打开，前端能完整展示库 |
| **M2 管理操作** | 写路径闭环 | 增删改、收藏/评分/标签/分类、批量、批量 VNDB 匹配 | 前端 CRUD 全流程对拍 V1.0，行为一致 |
| **M3 扫描/启动/监控** | 能玩、能计时 | 目录扫描+引擎识别（移植 `game_scanner`）、`CreateProcess` 启动、进程存活+耗时、退出回调 | 扫描一个真实目录出的库 == V1.0 扫描结果 |
| **M4 元数据多源** | 网络客户端 | VNDB/Bangumi/YMGal 客户端 + 多源搜索 + 封面下载 | 对拍 `multi_source.py` 返回结构 |
| **M5 截图 + 覆盖层** | 图片与 IPC | BitBlt→WIC 截图、PIL→WIC 缩略图、命名管道接 overlay | 截图 toast + 翻译透传可用（对齐 V1.0 #9 单例保护） |
| **M6 交互打磨 + 打包** | 成品 | 无边框拖拽/缩放、全局热键、伪装/全屏、主题一致性、安装包 | 对照 V1.0 全量 UI 文案与行为回归 |

### 9.3 里程碑 / 阶段映射

| 里程碑 | 对应「九节」原阶段 | 说明 |
|---|---|---|
| M0 | 阶段 0 | 骨架 + WebView2 桥验证（前置闸门） |
| M1 | 阶段 1 | DB + 只读桥 |
| M2 | 阶段 2 | 写操作 |
| M3 | 阶段 3 | 扫描/启动/监控 |
| M4 | 阶段 4 | 元数据多源 |
| M5 | 阶段 5 | 截图 + 覆盖层 |
| M6 | 阶段 6 + 7 | 交互 + 打包回归 |

### 9.4 依赖与并行工作流

- **依赖链**：M1 是 M2/M3/M4 共同地基（都要读库）；M3 依赖「能看库」（M2）；M4 网络层与 M3 互不阻塞，可后置；M5 依赖 M1（要有 Game 结构）；M6 收尾。
- **三轨并行（单人按序串可合并）**：
  - Track-A 壳/桥：M0 → M6 的窗口交互；
  - Track-B 数据/业务：M1 → M2 → M3 → M5；
  - Track-C 网络/元数据：M4（可与 B 并行）。

### 9.5 关键执行要点

1. **M0 是整条路的闸门**：HostObject 桥 + 静态资源映射不通则回退「本地 HTTP」桥，先验证再深做。
2. **防漂移的金样例**：重写前先把 `metadata_matcher`、`game_scanner` 用 V1.0 现有逻辑跑一遍，产出**一组黄金样例输入/输出**；C++ 移植后用同一组数据回归——这是把行为漂移风险压到最小的关键动作。
3. **对拍基线**：每个里程碑结束都跑一遍 V1.0 对比功能；**master 上保留 V1.0 可运行**，直到 M6 回归全部通过。
4. **测试先行**：为元数据匹配、扫描启发式等核心逻辑先写测试用例，再写 C++ 实现。

---

## 十、工作量与风险（诚实评估）

- **总工作量**：≈ 用 Rust 重写，但因语言熟 + 复用 WebView2，实际可控性更高。
- **主要风险**：
  1. **行为漂移**：元数据匹配、多源合并、扫描启发式的细节最容易重写出差异 → 靠阶段化 + 逐步对拍 V1.0 缓解。
  2. **WebView2 桥接学习成本**：HostObject/ExecuteScript/SetVirtualHostNameToFolderMapping 需上手，比 pywebview 略繁。
  3. **C++ 迭代慢**：单人长期维护，后续加元数据源/特性投入更大。
  4. **功能对拍缺失**：建议阶段化迁移期间保留 V1.0 可运行作基准。

---

## 十一、待决策

- 工程用 **CMake** 还是 **MSBuild(.sln)**？（建议 CMake，便于 CI 与后续扩展）
- frontend 从 V1.0 **拷贝独立副本** 还是链接引用？（建议独立拷贝，避免互相影响）
- 切入点：从 **M0（骨架 + WebView2 技术验证）** 开始，还是直接跳到 **M1（DB + 只读桥，先看见库能打开）**？建议 M0 先行。

---

*本文档随开发推进更新。*
