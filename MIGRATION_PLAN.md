# KazariPlay：Python → C# + WebView2 迁移规划

## 0. 目标与原则

- **前端零改动**：`web_assets/`（index.html / css / js）原样复用
- **数据零迁移**：`games.db`（SQLite）表结构与封面目录直接沿用
- **后端直译**：`core/database/utils` 逻辑逐模块移植，SQL 原样保留
- 目标运行时：**.NET 8**，WPF + `Microsoft.Web.WebView2`

## 1. 关键架构决策：桥接层用 JSON-RPC，不用 AddHostObjectToScript

现有前端 `app.js` 用 `bridge.xxx(args, cb)` 的 Proxy 兼容层（底层 `pywebview.api.xxx().then(cb)`）。最贴近的 C# 方案是 **WebMessageReceived + JSON-RPC**：

- JS 端：把 `bridge` Proxy 的底层从 `pywebview.api` 换成 `window.chrome.webview.postMessage`，**`app.js` 其余逻辑不用动**
- C# 端：接收 `{id, method, args[]}`，反射/字典分发到桥方法，返回 `{id, result}`

```jsonc
// JS → C#
{ "id": 1, "method": "getGames", "args": [] }
// C# → JS
{ "id": 1, "result": "[{...}]" }
```

对比 `AddHostObjectToScript`：后者只支持同步返回，且 WinRT 对象互操作有类型限制，对现有异步 `cb` 风格改造大，故弃用。

## 2. 项目结构

```
KazariPlay.CSharp/
├── KazariPlay.sln
├── src/
│   └── KazariPlay/
│       ├── KazariPlay.csproj          (net8.0-windows, UseWPF, WebView2包)
│       ├── App.xaml / MainWindow.xaml (WPF 宿主 + WebView2 控件)
│       ├── Bridge/
│       │   ├── RpcBridge.cs           (JSON-RPC 分发核心)
│       │   └── WebBridge.cs           (对应 py 的 WebBridge，方法直译)
│       ├── Core/
│       │   ├── GameManager.cs         (门面)
│       │   ├── GameScanner.cs
│       │   ├── GameLauncher.cs
│       │   ├── GameMonitor.cs
│       │   ├── GameModel.cs           (Game DTO)
│       │   ├── MetadataMatcher.cs
│       │   └── MultiSource.cs
│       ├── Database/
│       │   ├── DatabaseManager.cs     (SQLite + 锁)
│       │   ├── GameRepository.cs
│       │   └── TagRepository.cs
│       ├── Utils/
│       │   ├── Config.cs              (config.json)
│       │   ├── Logger.cs
│       │   ├── PathUtils.cs
│       │   ├── TimeUtils.cs
│       │   ├── VndbClient.cs
│       │   ├── BangumiClient.cs
│       │   └── Win32Window.cs         (frameless/图标/拖拽 P/Invoke)
│       └── Resources/
│           └── web_assets/            (从现有项目复制)
```

## 3. 分阶段实施计划

### Phase 0：环境与骨架（0.5 天）
- 安装 .NET 8 SDK、`dotnet new` WPF 模板
- 添加 NuGet：`Microsoft.Web.WebView2`、`Microsoft.Data.Sqlite`
- 建空 WPF 项目，`WebView2.CoreWebView2` 初始化成功，加载一个 Hello HTML
- **验收**：窗口显示，`webview.CoreWebView2` 非 null

### Phase 1：桥接层打通（1-2 天，最高风险）
- 实现 `RpcBridge`：`WebMessageReceived` 解析 → 分发 → `PostWebMessageAsJson` 回传
- 写一个前端 Proxy 适配层（新 `bridge.js` 替换 `app.js` 里的 Proxy 实现，方法名不变）
- 先只通 `getGames` / `getConfig` / `getRunning`
- **验收**：前端卡片能渲染出真实库数据；此阶段决定整个方案可行性

### Phase 2：数据层移植（1-2 天）
- `DatabaseManager.cs`：`Microsoft.Data.Sqlite` + 单例 + `SemaphoreSlim` 串行化（替代 `_DB_LOCK`）
- `GameRepository` / `TagRepository`：SQL 原样复制，`_row_to_game` → 手动列映射
- `PathUtils`：`%APPDATA%\KazariPlay` 定位 + 旧 MinatoLauncher 迁移逻辑
- **验收**：用现有 `games.db` 读出 18 个游戏，字段与 Python 版一致

### Phase 3：核心逻辑移植（3-4 天）
| Python | C# | 要点 |
|---|---|---|
| `GameScanner` | 同名 | 目录遍历 + 规则，`async` |
| `GameLauncher` | `Process.Start` | `CREATE_NEW_CONSOLE` 等价：`UseShellExecute=true` + `CreateNoWindow` |
| `GameMonitor` | `Task` 循环 | `Process.HasExited` 轮询，`ConcurrentQueue`/回调 |
| `GameManager` | 同名 | 门面直译 |
| `MetadataMatcher` + `VndbClient` | `HttpClient` | 超时重试逻辑移植 |
| `BangumiClient` | `HttpClient` | 直译 |
| `Config`/`Logger`/`TimeUtils` | 同名 | 直译 |
| `image_safe_loader` | 不移植 | PyQt5 遗留，删除 |

- **验收**：`verify_bridge` 等价测试通过（增删改查、标签、分类、批量）

### Phase 4：窗口集成（1-2 天）
- frameless：`WindowStyle=None` + `WindowChrome`
- 窗口/任务栏图标：P/Invoke `LoadImageW`/`SendMessageW`
- HTML 标题栏拖拽/缩放：桥方法 → Win32 `ReleaseCapture`/`SendMessage(WM_NCLBUTTONDOWN)`
- 隐藏控制台、`min_size`、屏幕居中
- WebView2 降内存参数：`CoreWebView2EnvironmentOptions.AdditionalBrowserArguments`（替换 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`）
- **验收**：无边框、图标、拖拽、缩放与当前一致

### Phase 5：资源与打包（1 天）
- `web_assets` 作为 Content 随发布；启动时 `NavigateToString` 内联 css/js（对应 `_load_html` 思路，规避 file:// 中文路径问题）
- `dotnet publish -r win-x64 --self-contained`（或 NativeAOT 试跑，若体积/启动达标）
- **验收**：单文件夹可分发，与 PyInstaller 产物结构等价

### Phase 6：回归验证（1 天）
- 用真实库完整走一遍：启动游戏、计时、VNDB 匹配、懒加载、批量操作
- 前端 `last_text`/`play_time_text` 刷新链路回归
- 内存对比：C# vs Python，验证降内存目标

## 4. 工作量与里程碑总览

| Phase | 内容 | 估时 | 产出 |
|---|---|---|---|
| 0 | 骨架 | 0.5 天 | 空窗口 + WebView2 |
| 1 | 桥接层 | 1-2 天 | 前端渲染真实数据（**关键 POC**）|
| 2 | 数据层 | 1-2 天 | 读写现有 db |
| 3 | 核心逻辑 | 3-4 天 | 功能等价 |
| 4 | 窗口 | 1-2 天 | UI 体验一致 |
| 5 | 打包 | 1 天 | 可分发产物 |
| 6 | 回归 | 1 天 | 全功能验收 |

**合计约 8-12 个工作日**，核心风险集中在 Phase 1（桥接）。

## 5. 主要风险与对策

| 风险 | 对策 |
|---|---|
| 前端 Proxy 改造成本超出预期 | Phase 1 先做 POC，验证 3 个方法后再铺开 |
| frameless 拖拽/缩放细节 | Phase 4 单独留 2 天，参照现有 JS 逐方法对齐 |
| SQLite 并发写 | `SemaphoreSlim` + 短连接（沿用 Python 版"每次开连接+提交"模式） |
| VNDB 限速/超时行为差异 | 移植已写好的重试逻辑，Phase 3 单独测 |
| `getCover` 懒加载 base64 | 数据流不变，仅传输层换，风险低 |
