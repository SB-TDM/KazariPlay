# KazariPlay WinHost 实施计划

> **状态：Task 0–7 已完成端到端 `getConfig/getGames`；Task 8 已接入 IFileDialog、对话框 broker、UISync HostPush（2026-10-22）。Task 5 实机交互、双 PID/hello、分片 UI 验证、真实文件对话框验收和 Task 9–11 未完成。** 工作分支为 `feature/winhost`；核对基线为 `35b6574`（1.2.0 代码）和 `ad25100`（原计划归档）。下文是目标设计与实施任务，不代表当前构建已采用 WinHost；实机验收项保持未勾选。

**目标：** 用薄 C++ 窗口宿主替换 pywebview，保留现有粉色标题栏外观，把拖拽、缩放、贴靠和最大化交还 Windows；Python 继续承载业务。

**技术栈：** C++17、Win32/DWM、WebView2 Evergreen Runtime、命名管道、Python 3.11、现有 TypeScript 前端。

**执行约定：** 按 Task 0–11 的依赖推进，每项都有可验证的完成条件。关键协议与生命周期先写失败用例，再实现。实施启动、提交和发布遵循用户当次授权；计划中的步骤不自动授权这些动作。执行时读取 [工作约束](../dev/DEV_RULES.md) 和 [测试说明](../dev/testing.md)，不依赖未安装的 agent skill。

## 1. 范围与不变量

- 用户正常启动的唯一入口为 `KazariPlay.exe`（C++ WinHost）。常驻业务进程为 `KazariPlayBackend.exe`；用户不需要安装 Python/Node。
- 最终源码、前端运行路径、打包及自检不再依赖 pywebview；不引入 Qt、CEF、Tauri、Rust 或另一套 Python 网页壳。
- 使用系统 WebView2 Evergreen Runtime，不分发 Chromium/Fixed Version Runtime；SDK 与 Runtime 分开管理。
- Host ↔ Backend 的 RPC、push、对话框和生命周期消息共用一条命名管道。现有封面 HTTP 服务继续服务图片，不承担 RPC。
- GameManager、扫描算法、元数据匹配、SQLite schema、overlay 消息协议不变。允许修改入口、UI 适配层、更新器及 overlay **进程生命周期**代码以接通新边界。
- 保留文件夹多选、取消扫描/匹配、热键截图、用户评分、现有数据目录、封面回退及自动更新/回滚能力。
- 粉色标题栏仍由现有页面绘制；Host 负责命中测试和系统窗口行为。最终删除 JS 拖拽/缩放和八个 `.resizer`，最大化图标由真实窗口状态驱动。
- 单帧最多 8 MiB；后端握手期限 15 秒；关闭宽限期总计 5 秒。大业务返回值采用分片，不能因 base64 膨胀误判为后端崩溃。
- 不增加安装器、签名、开始菜单/卸载项、Mica、跳转列表、托盘、任务栏进度、系统主题跟随或热键库替换。
- Task 7 切换前，旧入口用于基线对照；切换后仅测试 Host 路径。最终移除旧路径，不新增长期双桥兼容或运行时退回 pywebview 的机制。

## 2. 审查发现与处理位置

| 现有事实或原稿缺口 | 修订决定 | 实施位置 |
|---|---|---|
| `main.py::_load_html()` 组装 partials、脚本、CSS、图标与版本；原始 HTML 不可直接导航 | 提取资源清单，生成完整 HTML，JS/CSS 通过虚拟主机外部加载 | Task 6 |
| `app.ts` 等待 `pywebviewready`，且调用 `bindDrag/bindResize` | 同时迁移 core/app/window/type 声明及启动测试 | Task 7 |
| `ICON` 是全局词法 `const`，不是 `window.ICON` | 图标逻辑只放在 `window.ts` 的 `setMaximized()` | Task 7 |
| 文件对话框在调用线程等待；单线程 serve 会阻塞回包读取 | 独立 reader、受控 worker、统一 writer；取消/关闭有独立控制路径 | Task 4、8 |
| `scanFolder()` 已支持多选；原协议只含单个 path | `allow_multiple` + `paths[]`，保留四种现有选择用途 | Task 8 |
| 原稿 ready 黄金向量长度写成 17 | UTF-8 紧凑 JSON 实际为 **16** 字节；固定正确向量 | Task 1、2 |
| 截图原图可达 8 MiB，base64 后超过单帧上限 | 传输层拆分大 result，前端返回类型不变 | Task 1、2、4、7 |
| WebView2 子窗口可能截获鼠标，单测 HTMAXBUTTON 不等于系统收到 | 采用 composition hosting，先实测命中链路和输入 | Task 5 |
| `main.py` 还承担热键、封面服务、自愈和 helper 参数 | 迁移启动清单；helper 模式在单实例逻辑之前分流 | Task 7、9 |
| `applyUpdate()` 当前传本进程 PID 并销毁 pywebview 窗口 | 改为 Host/Backend 协调退出，helper 等待两个明确进程 | Task 9 |
| 冻结包与 smoke 依赖单 Python exe/pywebview | 双 exe 合包，重做 Host smoke，演练 1.2.0 升级与回滚 | Task 10、11 |

**已确认的工具事实：** 本机有 VS 2022 Build Tools、其自带 CMake，以及 NuGet 缓存中的 WebView2 SDK `1.0.4129.50`（含头文件和 x64 静态 loader）；普通 PowerShell 的 PATH 没有 CMake。构建脚本应可定位/恢复固定依赖，不能据本机缓存存在就宣称另一台机器可构建。

## 3. 目标设计

### 3.1 模块职责

| 模块 | 职责 |
|---|---|
| `host/` | HWND、DPI、系统非客户区行为、WebView2、单实例、管道传输、IFileDialog、Backend 监控、helper 参数转发 |
| `backend_main.py` / `host_transport.py` | 入口参数、业务启动/关闭、管道 reader/writer、请求调度、对话框等待、更新退出协调 |
| `ui/host_dispatch.py` | 显式业务 API allowlist 与参数检查；调用现有 WebBridge |
| `ui/web_bridge.py` / `ui/sync.py` | 业务 API、原有 JSON 返回值、数据刷新；通过 HostPort 请求对话框和推送 |
| `ui/web_assets_manifest.py` / `ui/web_asset_stager.py` | 唯一资源清单、HTML partial 组装、资源复制、首帧主题/版本/图标 |
| `ts/core.ts` / `app.ts` / `window.ts` | 桥兼容语义、一次性页面初始化、标题栏绘制和几何上报 |
| `scripts/` | 工具链定位、Host 构建、Backend 冻结、组合包检查、冻结自检和更新演练 |

### 3.2 构建与运行目录

SDK 固定为 `Microsoft.Web.WebView2 1.0.4129.50`，Host 使用 x64 `WebView2LoaderStatic.lib`。脚本通过 `vswhere` 定位 VS/CMake/CTest，显式使用 VS 2022 x64 generator、Release 配置、C++17、UTF-8。协议/几何测试目标不链接 WebView2。配置阶段可只构建这些测试，SDK 检查推迟到 Host 目标启用时。

`host/packages.config` 固定 NuGet 包版本；`build_host.ps1` 从指定缓存或 `nuget.org` 恢复到忽略的构建目录，核对包版本与恢复校验信息并记录包摘要；不得静默采用其它版本。SDK/obj/build 目录不入库。使用仓库已有 `overlay/third_party/json.hpp`。

发布包布局固定如下；WebView2 loader 静态链接，无单独 loader DLL：

```text
KazariPlay/
  KazariPlay.exe                 # C++ Host，唯一用户入口
  KazariPlayBackend.exe          # PyInstaller onedir，console=False
  _internal/                    # Python/DLL、原始模板、编译 JS/CSS、图标、overlay x64/x86
  BUILD_INFO.json
  LICENSE / THIRD_PARTY.md / RELEASE_NOTES.md / TRIAL_README.txt
  run_develop.cmd
```

- 两个 exe 均位于根目录，保持 Backend 的 `current_install_dir()` 与 `sys.executable` 推导一致；资源目录使用 `_MEIPASS`，不能依赖工作目录碰巧正确。
- Host 的图标、manifest 和版本资源通过 `.rc` 编译嵌入一次，版本由构建时读取 `version.py` 生成；不要把 `DISPLAY_VERSION` 当可直接解析的常量赋值。
- Backend 使用 `console=False`，Host 使用 Windows subsystem；这两个配置分别属于 PyInstaller 和 CMake，均不弹控制台。保留诊断日志与退出码。
- 开发期 Host 接受 `--dev-root <仓库绝对路径> --python <解释器路径>`；解析后用明确的 application path/正确 Windows 引号启动 Python，不能通过 `cmd /c` 拼接。
- 常驻 Backend 第一个位置参数仍为管道名；另传 `--host-pid`、`--asset-root`。冻结模式改为调用同目录 Backend exe，保持相同参数协议。
- 显式 `KAZARIPLAY_DATA_DIR` 优先；冻结包默认根目录 `data/`，源码默认沿用现有 AppData 路径。Host 在启动 Backend 前确定同一个绝对数据目录，并通过环境传入；helper 的 `--data-dir` 优先于默认值。
- Host 为本次运行分配 `<data-dir>/cache/winhost/<run-id>/web/` 作为 staging 根；WebView2 user data folder 单独放在 `<data-dir>/cache/webview2/`。原始程序资源、用户数据、staging 和浏览器缓存各有明确所有者。
- 正常退出只清理本次 staging，且在 WebView 控制器关闭后执行；异常退出遗留目录仅在能确认其所有进程已退出时清理。发布 ZIP 不包含 data、staging、浏览器缓存、日志和 smoke 产物。

### 3.3 页面装配与首次导航

`stage_assets(source_root, destination, identity, theme) -> Path` 是纯文件装配函数：

1. 将现有 `_JS_MANIFEST` / `_PARTIAL_MANIFEST` 移到无 GUI 依赖的清单模块；维护一个权威顺序，旧入口临时引用同一清单。
2. 注入全部 partial HTML，替换版本/产品线/标题/主题，将 logo 改成相对图片资源。
3. 为编译 JS 生成有序的经典 `<script src="js/...">`；保留 CSS `<link>` 和原有 `@import ... layer(...)`，复制其相对依赖。不开启 module/async，不再整页内联 JS/CSS。
4. 用 Backend Config 的初始主题生成 HTML。明暗首帧、WebView 默认背景色一致；禁用“先 light 再修正”的路径。
5. 无占位符、脚本顺序正确、partial/id 完整、资源均存在才发送 `ready`。Host 只映射它自己指定的 staging 根，拒绝 Backend 返回不同根或重解析点越界。

Host 使用 `https://kazariplay.local/index.html` 和 `SetVirtualHostNameToFolderMapping`。页面加载该目录的 JS/CSS/图片；既有 `127.0.0.1` 封面 URL、base64 回退均要实测，不能假设新 HTTPS origin 下图片行为与内联 HTML 相同。

`tests/verify_frontend.py` 改为验证 staging 产物，保留版本、脚本顺序、CSS layer、HTML id、图标和暗色首帧检查；去掉“必须内联 CSS/JS”的旧断言。`scripts/build_web_assets.py` 只创建临时装配产物用于构建校验；最终包仍携带模板/资源，由 Backend 按用户主题生成运行目录。

### 3.4 帧、消息与大响应

字节流格式为小端 `uint32` body 长度 + UTF-8 JSON 对象。长度不含前缀，最大 `8 * 1024 * 1024`。编解码层只处理帧和 JSON；协议版本/消息字段由连接状态机校验。

- 不完整的前缀或 body 返回 `None` / `std::nullopt` 且不消耗缓冲；完整帧只消费一个对象，余下字节留给下次。
- 拒绝零长度、超长前缀、非法 UTF-8、非法 JSON、非对象根节点和非标准 NaN/Infinity。错误统一为协议错误；接收端关闭连接并释放等待者。
- `encode_frame()` 发送前发现业务结果超长时走大响应路径；不能先写前缀再报错，也不能因一个超长 result 把整个会话断开。
- 不要求不同语言按相同 key 顺序编码所有对象；固定向量检验确定的字节，双向测试检验消息语义。

黄金向量（仅测 codec，不是完整握手）：

```text
JSON: {"type":"ready"}
UTF-8 body: 16 bytes
Frame hex: 100000007b2274797065223a227265616479227d
```

Host → Backend 示例（每行独立帧）：

```json
{"type":"hello","protocol":1}
{"type":"call","id":1,"method":"getGames","args":[]}
{"type":"dialog_result","id":7,"ok":true,"paths":["D:\\games","E:\\games"]}
{"type":"dialog_result","id":8,"ok":false,"paths":[]}
{"type":"shutdown","reason":"user"}
```

Backend → Host 示例（版本仅示意，实际来自 version.py）：

```json
{"type":"ready","protocol":1,"version":"1.2.0","display_version":"v1.2.0","theme":"dark","asset_root":"D:\\KazariPlay\\data\\cache\\winhost\\run-123\\web"}
{"type":"startup_error","code":"backend_init","message":"初始化失败"}
{"type":"result","id":1,"ok":true,"result":"[]"}
{"type":"result","id":2,"ok":false,"error":{"code":"unknown_method","message":"未知方法"}}
{"type":"eval","code":"window.__app && window.__app.refresh();"}
{"type":"dialog","id":7,"kind":"folder","title":"选择游戏文件夹","allow_multiple":true,"filters":[]}
{"type":"dialog","id":8,"kind":"file","title":"选择可执行文件","allow_multiple":false,"filters":[{"label":"可执行文件","patterns":["*.exe"]},{"label":"所有文件","patterns":["*.*"]}]}
{"type":"dialog_cancel","id":8}
{"type":"exit_requested","reason":"update"}
{"type":"shutdown_complete"}
```

`call.id` 来自 Host 对浏览器请求的分配；`dialog.id` 来自 Backend，二者独立、正整数且不超过 JS 安全整数范围。同一连接内不复用 ID。Host 保留 RPC id 与 `{document_id, JS id}` 的映射：给 Backend 的 id 跨导航递增，回给页面时在消息外层附上 document_id/request_id，保留原帧及分片内容的 RPC id。重组后核对 result.id 与分片 RPC id，再按外层 request_id 完成 Promise。上一页迟到的 id 不能完成新调用。重复回复、未知等待者、错误字段类型按消息校验处理；超时后迟到的合法回复丢弃并记录。

`getGames()` 当前返回 JSON **字符串**；dispatch/result 保持原值类型，不在 C++ 中擅自转换为数组。生命周期消息不可作为业务 dispatch 方法调用。

**大响应分片：** `ScreenshotService.original()` 允许 8 MiB 原图，其 base64 返回会超过单帧上限；因此 transport 支持如下包装，前端仍获得完整原返回值：

```json
{"type":"result_chunk","id":3,"index":0,"count":2,"total_bytes":300000,"data":"<base64 of a UTF-8 JSON result fragment>"}
```

- 先序列化完整 `result` JSON，再按最多 256 KiB 原始字节切块；每块 base64 编码后作为一个合法帧。`count`、`total_bytes` 必须相互一致，index 从 0 连续递增；禁止嵌套分片。
- 每个逻辑 result 上限 128 MiB，覆盖现有截图以及 64 MiB 封面原图回退膨胀；超过上限返回 `result_too_large`，不截断成功数据。业务列表超过该上限须作为独立分页需求处理。
- Host 校验 chunk 与待处理请求后用 WebView2 `PostWebMessageAsJson` 转发；注入脚本按 id 重组 UTF-8 JSON，校验 result.id 后调用 `_settle`。普通 result 走同一 message listener。无需把大字符串插进 `ExecuteScript`。
- 聚合缓冲受总预算限制（128 MiB），完成、超时、断管、导航后立即释放；不足时明确失败并丢弃该 id 的后续分片。对等端需限制并发大响应，不让 UI 或 I/O 线程等整条大消息。
- `eval` 仍是单帧脚本，由 Host UI 线程 `ExecuteScript`；超大 push 是可诊断错误。现有 UISync 发送 ID/进度，不应用 push 传原图。

### 3.5 管道、dispatch 与等待模型

管道名为 `\\.\pipe\KazariPlay.<Host PID>`。Host 使用单实例双工字节流、`FILE_FLAG_FIRST_PIPE_INSTANCE`、拒绝远程客户端和当前用户 SID 的 DACL；记录 Backend 实际进程身份，校验客户端 PID。Backend 校验服务端 PID 与 `--host-pid`，开发期解释器和冻结期 Backend exe 分别验证。

- 两端 read/write 使用独立 OVERLAPPED 状态，正确处理短读/短写、`ERROR_IO_PENDING`、`ERROR_PIPE_CONNECTED` 和 `CancelIoEx`。同步 read 持有写锁会破坏双工，禁止这样实现。
- Backend reader 持续读帧，只做校验和路由；普通 call 放入有界队列，由 4 个受控 worker 执行。保留 WebBridge/Repository 现有锁，不假设以前所有方法串行。
- `cancelScan`、`cancelMatch` 的快速置位与 shutdown 走控制路径，不排在长搜索/对话框之后；控制路径只做这些已知操作，不任意执行业务代码。
- 所有写入共享完整帧的 write lock，writer 在锁内写完前缀和 body；分片之间可以穿插其它完整消息，以便关闭/取消及时送达。
- `request_dialog()` 先登记等待对象，再发 dialog；reader 收到对应结果后唤醒 worker。超时 120 秒时发送 `dialog_cancel`；Host 关闭相应 IFileDialog，后到回复无效。
- `serve(port, bridge, session)` 在校验 Host hello 且 session 初始化完成后发 ready；EOF、协议错误、初始化异常、shutdown 都进入同一个幂等清理出口。FakePort 必须模拟双向队列，不能预塞一个未知 id 的结果就宣称对话框通过。
- 普通队列最多 128 个待处理 call，超出返回 `busy`；普通 invoke 客户端超时 180 秒，文件对话框有上述独立期限。客户端超时不代表后台操作已撤销，不能自动重试写入操作。
- `HostPush.evaluate_js(code)` 是注入 UISync 的 transport 适配器。UISync 保留域映射/合并，不拥有 win32 管道、COM 或窗口生命周期。

`dispatch(bridge, method, args)` 只允许 `HOST_DISPATCH_METHODS` 中的业务 API；method 必须为字符串、args 必须为 list。参数绑定失败为 `invalid_args`，方法异常为 `method_failed`；日志记录 traceback，响应仅返回简短说明。测试从 HTML/TS 调用和类型契约核对清单，动态方法调用显式登记，不能只用正则漏掉调用方。

以下窗口 API 由 Host 本地处理，禁止进入 Backend；`windowMaximize/windowRestore` 也必须覆盖：

```text
windowMinimize, windowToggleMaximize, windowMaximize, windowRestore, windowClose
windowStartDrag, windowMoveDrag, windowEndDrag, windowResize, windowResizeStart
```

前五项映射系统窗口命令。后五项在最终前端中无调用，若仍收到返回 `unsupported_window_method`，不重新引入 JS 拖拽。`bind_window`、`refresh`、`notify`、`cleanup_unused_covers`、`on_host_shutdown` 等内部钩子不在业务 allowlist。

### 3.6 JS 桥与两种就绪状态

Host 在导航前等待 `AddScriptToExecuteOnDocumentCreated` 完成，注入 `window.__host`：

| 成员/消息 | 契约 |
|---|---|
| `ready` | Backend 握手和桥消息处理器已就绪，可调用 invoke；不是更新成功确认 |
| `invoke(name, args)` | 分配 id、登记 Promise、发送 call，调用失败 reject |
| `_settle(id, ok, value)` | 最多完成一次等待；JSON 序列化处理转义，不拼接未转义字符串 |
| `setMaximized(on)` | 转给 `window.ts` 的绘制函数；DOM 尚未就绪则暂存最后状态 |
| `ui_ready`（JS → Host） | app 已绑定事件、安装 `window.__app`，可以接收 push |
| `caption`（JS → Host） | 当前标题栏/按钮矩形、DPR 与布局代次；Host 校验后换算 |

注入脚本为每次文档创建分配新的 `document_id`，随 ui_ready/call/caption 发送；Host 在该次 NavigationStarting 后只接纳当前顶层文档的 ui_ready，之后所有消息须匹配此文档。浏览器侧消息示例（`min/max/close` 的数值仅示意）：

```json
{"type":"ui_ready","document_id":"document-1"}
{"type":"call","document_id":"document-1","id":1,"method":"getGames","args":[]}
{"type":"caption","document_id":"document-1","revision":1,"dpr":1.5,"titlebar":{"x":0,"y":0,"w":1200,"h":40},"min":{"x":1062,"y":0,"w":46,"h":40},"max":{"x":1108,"y":0,"w":46,"h":40},"close":{"x":1154,"y":0,"w":46,"h":40}}
```

Host 返回 WebView2 message 的统一外层示例：`{"document_id":"document-1","request_id":1,"message":{"type":"result","id":42,"ok":true,"result":"[]"}}`。`result_chunk` 采用相同外层，不修改分片内部序列化数据；前端在完成或废弃 request_id 时同时释放分片缓存。

- `app.ts` 保留一次性初始化保护，改用 `__host.ready`；移除 `pywebviewready` 事件和旧轮询。先完成 DOM/事件绑定，再上报 ui_ready 和 caption，再获取配置、游戏列表。
- `updateFrontendReady()` 仍由首屏数据加载成功回调触发，且只触发一次。Backend ready、NavigationCompleted、窗口 Show 都不能清除更新回滚标记。
- 首次 ui_ready 前的 push 暂存于有限队列；进度/刷新可合并，队列溢出触发一次完整刷新，不能无界堆积脚本。首次库加载提供状态兜底。
- `core.ts` 保留末尾回调风格，失败回调 `('[]', true)` 最多一次；业务回调自身抛错不得再次通知失败。
- **现有 Promise 行为要保留：** 桥缺失或同步抛错返回已解析 `'[]'`；异步拒绝会通知失败回调，但原返回 Promise 仍拒绝。不能未经调用方迁移就把所有异步错误吞成成功 `'[]'`；新增桥契约测试固定此行为。
- 本地顶层页面之外的消息不接受。阻止内嵌跳转/新窗口将桥带到外部网站；合法外链经已有系统打开方法处理。页面重载/崩溃使旧请求失效，旧 document 的响应不能完成新页面请求。

### 3.7 原生窗口、WebView2 输入与 DPI

实际窗口使用 `WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU`，由页面绘制标题栏；保留 `WS_THICKFRAME` 的缩放/贴靠能力，不使用会显示系统标题栏的 `WS_CAPTION`。`WM_NCCALCSIZE` 去掉系统标题栏占用，最大化时按当前显示器 work area 修正；`DwmExtendFrameIntoClientArea` 扩展的是 DWM frame，不代替客户区尺寸计算。

**输入承载决定：** 使用 `ICoreWebView2CompositionController` + DirectComposition，让顶层 HWND 拥有鼠标命中路径；仅在 Host 返回 `HTCLIENT` 的区域把输入通过官方 `SendMouseInput/SendPointerInput` 交给 WebView。这样不依赖 Chromium 私有 child HWND subclass，也不假设普通 windowed WebView 会把命中消息透传到父窗口。Task 5 必须用真实控件先验证，失败不得靠 JS 拖拽绕过。

- UI 主线程 `CoInitializeEx(COINIT_APARTMENTTHREADED)` 并持续运行消息循环；WebView2 创建/回调/脚本、窗口和 IFileDialog 均在该线程。I/O 线程投递消息，不直接调 COM UI。
- 普通页面区域转发鼠标、滚轮、离开、capture、触摸/笔，接入 CursorChanged、MoveFocus、Tab、IME 和焦点恢复。防止 pointer/mouse 重复转发；退出时解除事件、RootVisualTarget 和 COM 引用。
- 非客户区边角优先命中缩放区域；窗口最大化时禁用这些缩放命中。有效按钮区域再返回 `HTMINBUTTON/HTMAXBUTTON/HTCLOSE`，其余标题栏空白返回 `HTCAPTION`，正文返回 `HTCLIENT`。
- 鼠标非客户区动作由 `DefWindowProc`/系统命令路径处理；最大化按钮 hover 必须实际返回 `HTMAXBUTTON`，保留 Snap flyout。对应鼠标点击不再发 DOM onclick，避免一次点击执行两次。
- 三个 DOM button 保留可访问性标签和键盘激活 handler；仅 `click.detail == 0` 的键盘/辅助技术激活走 Host 本地窗口命令。非客户区 hover/pressed 由 Host 单向同步为 CSS 状态，保留粉色按钮视觉。
- `window.ts` 唯一的状态绘制函数 `setMaximized(on)` 使用词法 `ICON`；注入层只缓存/转发，禁止出现两份图标选择实现。
- DOM ready、resize、ResizeObserver 和 DPI 变化后上报标题栏及三个按钮矩形；Host 记录布局代次、裁剪区域、拒绝 NaN/负数。首次矩形未到可按 40 DIP 高、3×46 DIP 按钮估算，但显示可交互页面前需拿到首组有效矩形。
- Host 固定 WebView ZoomFactor=1，关闭用户页面 zoom；按实际 RasterizationScale 转换 CSS/DIP 到 HWND 物理坐标，不重复乘 DPR 与 DPI。`WM_DPICHANGED` 使用建议窗口矩形、更新 WebView bounds/缩放，再请求重新测量。全屏幕坐标使用有符号数，支持负坐标显示器。
- 使用 `WM_GETMINMAXINFO`、当前显示器 `rcWork`、DPI 对应系统边框指标处理最大化和任务栏；初始窗口为主显示器工作区约 82%，最小值 **900×620 DIP（96 DPI 基准）**。
- **已知尺寸边界：** 900 DIP 最小宽度会限制小屏/高 DPI 下的半屏或三列贴靠。验收分开检查 flyout 能出现和窗口能装进某个区域；只承诺不小于最小尺寸的区域。若产品要求所有常见区域都可贴靠，应先另行调整最小宽度和布局要求，不能把超出最小尺寸约束的场景记为通过。

### 3.8 启动、关闭和 overlay

正常启动状态机：`Starting → BackendReady → Navigating → Running → Closing → Exited`；任何初始化失败进入有界清理后返回非零。

1. **首先解析 helper 模式**（见 3.9），正常启动才获取 `Local\KazariPlay.WinHost` 互斥量。旧窗口存在时仅在最小化状态使用 SW_RESTORE，已最大化窗口保持状态；激活失败可闪烁任务栏。
2. 尽早创建类名 `KazariPlayHost` 的隐藏 HWND/激活事件。第二实例在第一实例初始化窗口前启动时，通过事件请求其就绪后激活；在 15 秒启动预算内等待。超时说明启动中/失败，退出而不再拉第二个 Backend。
3. 创建管道、确定隔离目录，启动 Backend。Backend 在导入会初始化 Config/logger 的业务模块之前设置数据目录和 `sys.path`；先处理 startup_self_heal，再初始化业务。
4. 迁移 main.py 的日志级别、更新残留清理/提示、GameManager、CoverStore/CoverService、封面后台清理、WebBridge 绑定、截图热键和启动计时。热键/封面服务允许沿用原有降级；致命错误返回 startup_error。
5. Backend 完成 hello 校验、资源 staging 和桥绑定后发 ready。Host 校验协议/版本/asset_root、检查 Runtime 后创建 WebView2；初始化异步失败也清理 Backend。15 秒指 Backend 握手预算，WebView 初始化/导航另设 15 秒失败期限，不阻塞消息泵。
6. 页面资源和首组 caption 就绪后显示窗口。ui_ready 后允许 push，真实首屏加载后调用 updateFrontendReady。

正常关闭：Host 立即进入 Closing，停止新调用、关闭打开的 IFileDialog、发送 shutdown 并继续泵消息；不能在 WndProc 中 `WaitForSingleObject(5000)`。

Backend cleanup 幂等：拒绝排队调用并唤醒 dialog 等待 → 置 scan/match 取消事件 → 注销自己的热键/停止推送 → 停封面服务/退出 overlay → 等工作线程在剩余预算内结束。只在写入任务结束后关闭拥有的数据库连接；无法正常收尾由 Host 超时终止 Backend，不能先 close DB 再让 worker 写库。`shutdown_complete` 只是清理完成消息，Host 仍观察进程真正退出；总宽限期 5 秒不能被各子步骤各等 5 秒放大。

意外 EOF、协议错、Backend 崩溃或 Host 消失都走清理。正常用户/更新退出不弹崩溃对话框；意外退出只提示一次，拒绝 pending invoke，关闭窗口。启动失败、Runtime 缺失也不能留下 Backend。Host 已崩溃时不能再依赖 Host 的超时终止：Backend 发现 EOF/Host handle 已结束后启动本地 5 秒清理 watchdog，预算用尽后退出进程，避免 worker 卡住留下常驻 Backend。

**overlay 收尾事实与补齐：** 现有 `overlay/src/main.cpp` 在已建立管道断开时会 QUIT，因此 Backend 崩溃后的常规场景无需改协议。但进程已启动、连接尚未建立时存在空档。仅在 `OverlayClient` 的进程创建/持有层加入 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 保护：通过 Windows 10/11 的 STARTUPINFOEX Job list 在创建时就关联专用 Job，避免“创建 suspended 进程后、加入 Job 前”仍有孤儿进程窗口；Job handle 不继承，Backend 退出会释放它。沿用现有 quit/限时等待路径，连接前崩溃也要测试。这个 Job 只包含 overlay，**不能把 Backend 或用户启动的游戏整个进程树放入其中**。

### 3.9 自动更新和回滚

本节必须保持 `1.2.0 → WinHost` 的真实可升级性。更新不是实现完成后的可选补丁。

- `KazariPlay.exe --apply-update/--apply-rollback ...` 在互斥量、常驻管道、WebView 初始化**之前**分流，启动同目录 `KazariPlayBackend.exe` 的 helper 模式，转发完整原参数并返回其退出码。helper 不创建 GameManager/页面/常驻桥。
- 保留旧参数 `--pid/--target/--data-dir`。新版本传 `--pid <旧 Host PID>` 及 `--backend-pid <旧 Backend PID>`；旧 1.2.0 只传一个 PID，仍须接受。启动失败前的自愈回滚同样携带两个待退出进程。
- `applyUpdate()` 成功创建更新 helper 后，先写出该调用 result，再发 `exit_requested(reason=update)`；Host 将其视为预期退出，进入正常 shutdown。`startup_self_heal()` 决定退出让回滚接管时，可在 ready 前发 `exit_requested(reason=rollback)`，不能当成握手崩溃。
- helper 等 Host 和 Backend 明确退出后才备份/替换；Host 提前退出而 Backend 未退也不能继续。核对目标 exe 路径和可取得的创建时间，防 PID 重用；新路径不得用 `taskkill /T` 杀掉用户游戏。
- `PROGRAM_WHITELIST` 增加根目录 Backend exe；程序资源全部放 `_internal/`，保持旧下载预检认可的根 `KazariPlay.exe + _internal/` 结构。新包 BUILD_INFO 标记 `layout=winhost-v1`，新预检验证两个 exe 的版本/架构/资源。
- 1.2.0 启动的是**解压后新包的** KazariPlay.exe helper，因此新白名单可处理第二个 exe；仍须真实旧包演练，不能仅根据这段推断勾选验收。
- 回滚旧单进程版时，新添加且旧备份不存在的 `KazariPlayBackend.exe` 必须按受控程序清单移除；镜像恢复 `_internal/`，不留混合架构产物，也不触碰 data/screenshots/logs。程序备份记录原有条目集合，重复恢复仍幂等。
- helper 从更新解压缓存运行，不能在将被替换的目标 `_internal/` 中执行。自愈、热键、清理仅由正常 Backend 执行一次；helper 不能递归启动另一 helper。
- 更新成功后的启动目标始终是 Host。成功标志仍由首屏 updateFrontendReady 清除；Backend ready 不够。Host 必须观察 Backend 退出而结束自身，方便现有早退观察发现失败；异常早退、前端未确认、握手失败均保留回滚资源。
- 冻结更新观察需适配两段启动预算：最多 45 秒等待首屏确认，正常确认后立即结束；不能沿用“观察 8 秒、进程还活着即放行”来宣称新链路成功。到期未确认时，helper 先结束新 Host/Backend、确认文件释放，再回滚；若进程无法结束则保留备份与错误状态，不覆盖仍被占用的文件。
- `scripts/verify_frozen_update.py` 增加旧单 exe → 双 exe、双 exe → 双 exe、失败回滚到旧单 exe、两进程文件锁和 helper 不受单实例阻挡的用例。真实 Release 上传不属于这些离线演练。

## 4. 实施任务

新增 Python 测试统一采用 `unittest.TestCase` 并沿用 `src/kazari_play` 加入 `sys.path` 的习惯；不额外引入 pytest 依赖。既有函数式测试仍执行其脚本入口，不能只报 unittest discover 的数量就宣称全部门禁通过。

每个 Task 先完成对应验证再勾选；若有授权，可单独形成中文提交。下面的文件名是待创建目标，不能在 Task 尚未创建它们时运行测试并把“找不到文件”记为通过。

任务中的 Python `ui/`、`core/`、`utils/`、入口文件和 `host_transport.py` 路径均相对 `src/kazari_play/`；`ts/` 相对 `src/kazari_play/ui/web_assets/`；C++ 简写文件相对 `host/src/`。`tests/`、`scripts/`、`host/` 为仓库根目录路径。

### Task 0：固定工具链与构建入口

**依赖：** 无。**文件：** 新增 `host/CMakeLists.txt`、`host/packages.config`、`scripts/build_host.ps1`、`host/README.md`；按需更新 `.gitignore`。

- [x] 实现 VS/CMake/CTest 定位、固定 SDK restore/校验以及 x64 Release 生成目录；失败输出依赖缺失位置与修复指引，不改系统 PATH。
- [x] 定义脚本参数：`-ConfigureOnly`、`-ProtocolOnly`、`-Target <name>`、`-Test`；调用 native 命令后检查退出码，任何失败立即失败返回。协议模式不依赖 WebView2。
- [ ] 记录 manifest/图标/版本 `.rc` 和静态 loader 的接入位置；不编译或覆盖既有 overlay 产物。
- [x] 在普通 PowerShell 中运行 `powershell -NoProfile -File scripts/build_host.ps1 -ConfigureOnly -ProtocolOnly`；证明不依赖 PATH 中的 cmake。

**完成条件：** SDK 版本/摘要与工具路径可重现，构建目录均被忽略；Task 2 可以从同一入口添加并运行协议目标。不提前要求尚未实现的 staging 测试通过。

### Task 1：Python 帧与分片协议

**依赖：** Task 0 的目录约定。**文件：** 新增 `src/kazari_play/host_protocol.py`、`tests/test_host_protocol.py`。

- [x] 实现 `ProtocolError`、`encode_frame(obj)`、`decode_frame(bytearray)` 和 result 分片编码；握手语义校验放在 transport 层。
- [x] 先测试 partial 前缀/body 不消耗、连续帧、中文/emoji、零长度、8 MiB 边界、超长前缀、非法 UTF-8/JSON、非对象、NaN/Infinity、正确黄金向量。
- [x] 测试完整 result 超过 8 MiB 时拆片，每片满足限制；正常分片可重组为原消息，128 MiB 上限失败。乱序/重复/缺片与缓存释放由 Task 2/7 的 Host/transport 重组测试覆盖。
- [x] 用 `python -m unittest discover -s tests -p "test_host_protocol.py" -v` 验证。

**完成条件：** 正常、部分、组合和错误输入均有断言；codec 不依赖 UI/网络，也不改变业务返回类型。

### Task 2：C++ 帧与跨语言向量

**依赖：** Task 0、1。**文件：** 新增 `host/src/protocol.hpp`、`host/src/protocol_test.cpp`、`tests/test_host_protocol_cpp.py`；修改 CMake。

- [x] 实现 `host::encodeFrame(json)`、`host::decodeFrame(std::string&) -> optional<json>`，使用现有 json.hpp；不足一帧不消耗。
- [x] 使用 Task 1 的黄金向量和分段/Unicode/连续帧向量，校验异常与上限；C++ 发送内容由 Python 解码，Python 发送内容由 C++ 解码。
- [x] 测试用显式失败返回或测试框架断言，不能仅靠 Release 下被 `NDEBUG` 禁用的 `assert`。
- [x] 运行 `powershell -NoProfile -File scripts/build_host.ps1 -ProtocolOnly -Target host_protocol_test -Test`。脚本内部使用 `ctest --test-dir host/build -C Release --output-on-failure`，不假设 exe 在 build 根目录。

**完成条件：** 两端向量语义一致、测试失败会返回非零；不需要启动 WebView2。

### Task 3：显式 dispatch 契约

**依赖：** Task 1。**文件：** 新增 `ui/host_dispatch.py`、`tests/test_host_dispatch.py`。

- [x] 提取前端实际调用清单与动态调用点，定义 `HOST_DISPATCH_METHODS`、`HOST_LOCAL_METHODS`；核对 `.d.ts` 的方法/参数/返回值。
- [x] 实现 `dispatch(bridge, method, args)`，分类处理 unknown_method/invalid_args/method_failed；内部生命周期 API 不暴露。
- [x] Fake API 使用已登记的 `getGames()` 等名称测试成功，不向生产 allowlist 加测试专用 ping。
- [x] 测试私有方法、未登记的 public helper、全部窗口方法、非 callable、参数类型/个数错误和业务异常；确认原 JSON 字符串不被二次解析。
- [x] 运行 `python -m unittest discover -s tests -p "test_host_dispatch.py" -v`。

**完成条件：** 所有前端业务调用均有登记，内部 helper 和窗口方法不可经 Backend dispatch 到达。

### Task 4：可退出的 Backend transport

**依赖：** Task 1、3。**文件：** 新增 `host_transport.py`、`backend_main.py` 的可测试循环、`tests/test_backend_loop.py`。

- [x] 实现 `serve(port, bridge, session)`、持续 reader、有界 worker 队列、writer lock、ready 状态和分片发送；此阶段用 FakePort，不创建真实业务对象。
- [x] 实现 `request_dialog(kind, title, filters, allow_multiple) -> list[str] | None`。采用双向队列 FakePort，测试线程先读实际 dialog.id 再回包。
- [x] 验证 dialog 等待期间 result/push 能交错、shutdown 仍可读；普通长 call 占用 worker 不会饿死控制路径。
- [ ] 覆盖 120 秒 dialog 超时（已用可注入短期限验证）、dialog_cancel、EOF、协议错、初始化失败、重复/迟到 ID、队列满和同时写 result/eval/chunk；与真实命名管道相关的剩余项在 Task 7 补齐。
- [x] 用一次性清理计数断言 shutdown/EOF/错误竞态不会重复关资源；普通方法异常回 result 后服务仍可处理下一 call。
- [x] 运行 `python -m unittest discover -s tests -p "test_backend_loop.py" -v`。

**完成条件：** 等待对话框不阻塞读循环，任一退出路径唤醒所有等待者，短写/并发写不会损坏后续帧。

### Task 5：原生窗口与真实 WebView 输入验证

**依赖：** Task 0、2。**文件：** 新增 `host/src/window.hpp/.cpp`、`webview.hpp/.cpp`、`main.cpp`、`window_geometry_test.cpp`、`host/app.manifest`、`host/host.manifest.rc`、测试用本地页面。

- [x] 实现可独立测试的 `regionAt(point, captionRects, bounds, dpi, maximized)`；覆盖边角优先、按钮、标题栏、正文、负屏幕坐标和最大化禁用缩放。
- [x] 创建带系统粗边框的隐藏/可显示 HWND，嵌入 manifest/图标；实现 NCCALCSIZE、GETMINMAXINFO、SIZE、DPICHANGED 和系统命令。版本资源随合包构建在 Task 10 接入。
- [x] 初始化 COM STA、DirectComposition 与 CompositionController；接入正文输入、焦点、滚轮、capture、光标和基础键盘焦点路径。
- [x] 用真实 WebView 页面完成初始化并实际拉起 `msedgewebview2.exe`；页面按钮/矩形上报和 HTMAXBUTTON 的实机命中验证待完成。
- [x] 运行 `powershell -NoProfile -File scripts/build_host.ps1 -Target host_window_geometry_test -Test` 和完整 Host 构建。
- [ ] Windows 11 实测拖拽、边角缩放、双击、Win+Left/Right、Win+Z、hover flyout、任务栏边界、100%/150% DPI、文字输入/Tab/中文 IME；记录能容纳 900 DIP 最小宽度的测试区域。

**完成条件：** 接入真实 WebView 后仍能触发系统行为，正文输入正常。仅纯函数通过或只有空白 Win32 窗口可拖动不算完成；未通过时修订本层设计，不能继续用 JS 拖拽掩盖。

### Task 6：页面 staging 与虚拟主机

**依赖：** Task 5。**文件：** 新增 `ui/web_assets_manifest.py`、`ui/web_asset_stager.py`、`tests/test_web_asset_stager.py`、`scripts/build_web_assets.py`；修改 `main.py` 清单引用、`tests/verify_frontend.py`、Host webview 模块。

- [x] 从 main.py 提取唯一清单，实现 3.3 的完整装配；stager 不 import main.py/webview。
- [x] 生成有序外部 script、保留 CSS import/layer、复制相对图片；测试浅色/暗色/版本/中文路径/带空格路径/资源缺失；只读源目录未单独模拟。
- [x] Host 映射测试生成目录并实际加载现有静态 UI；真实桥接和动态业务数据留到 Task 7。
- [x] 迁移前端组装门禁，浏览器实际加载 CSS/JS、图标和深色首帧；已用真实 Host 截图确认页面结构。
- [x] 运行 stager 单测、前端 typecheck/build 和 `python tests/verify_frontend.py`。

**完成条件：** 完整 UI 能由虚拟主机加载，无残留模板/丢失 partial/脚本顺序错误，首帧主题符合配置。

### Task 7：真实 Backend、前端启动与一次完整业务调用

**依赖：** Task 2–6。**文件：** 新增 `host/src/backend.hpp/.cpp`、`tests/test_host_startup.py`、`tests/test_host_frontend.cjs`；修改 `backend_main.py`、`ui/web_bridge.py`、`ts/core.ts/app.ts/window.ts`、将 `ts/pywebview.d.ts` 迁移为 `ts/host.d.ts`。

- [x] 真实管道实现 ready/部分读写及启动超时；Host 用进程 handle 监控 Backend，并通过独立 Backend 进程测试 ready/call/shutdown。双方 PID/hello 校验仍未完成。
- [ ] 从 main.py 迁移 3.8 的业务初始化顺序和降级行为；staging/theme/identity 来自同一 Config/version。开发和冻结模式参数逻辑分别可测。
- [x] 注入 host bridge、消息 listener；迁移 core/app 初始化与类型。窗口事件切换到系统路径、删除 bindDrag/bindResize 仍待 Task 9/10。
- [x] 保留回调与 Promise 契约、一次初始化、ui_ready/首屏确认的区分；`test_host_frontend.cjs` 覆盖成功/失败回调。
- [ ] 单向同步窗口状态、DOM 首次 caption、DPI 重新测量及键盘按钮激活；测试不要读取 aria-label 推断下一状态。
- [x] 通过隔离库真实调用 getConfig/getGames，完成“网页 → 管道 → WebBridge → 原类型 result → 首屏”全链路。
- [x] 运行启动单测、`node tests/test_host_frontend.cjs`、既有 bridge contract/P0/P1 前端测试以及 typecheck/build。

**完成条件：** 库能加载，异步失败可见、回调最多一次，后台握手不会提前清理更新状态，窗口方法在 Backend 侧被拒绝。

### Task 8：文件对话框、UISync 与媒体兼容

**依赖：** Task 4、7。**文件：** 修改 `ui/web_bridge.py`、`ui/sync.py`、Host backend/webview、`tests/test_backend_loop.py`、`tests/test_ui_sync.py`、`tests/test_p1_reliability.py`。

- [x] 将四处选择方法接入 request_dialog：scanFolder 多选目录、previewRelocate 单目录、selectExe 单文件、pickCover 单图片；旧 pywebview 路径保留。
- [x] Host UI 线程用 IFileOpenDialog、FOS_PICKFOLDERS/FOS_ALLOWMULTISELECT、结构化 filters、GetResults；取消返回空 paths；真实交互尚未验收。
- [x] 在 WebView 回调之外通过投递消息打开模态框，避免 WebView2 同步重入；后端等待与取消已有；真实对话框的 timeout/shutdown 交互待验。
- [x] WebBridge 绑定 HostPush，UISync 保留合并与 payload 转义；新增 `test_backend_runtime.py` 验证对话框回包与 eval 推送。
- [ ] 验证一次评分/收藏/扫描会刷新页面；取消选择不改库，多个目录实际扫描都执行，取消扫描能响应。
- [ ] 验证虚拟主机页面下封面 HTTP、失败 base64、接近 8 MiB 截图原图、大于单帧的 JSON 返回；不得通过降低现有媒体限制让测试变小。

**完成条件：** 对话框等待时 RPC/push/关闭均可进行，UISync 线程不调用 COM，原功能无单选/媒体大小回退。

### Task 9：单实例、有界退出与更新交接

**依赖：** Task 7、8。**文件：** 修改 Host main/backend、`backend_main.py`、`ui/web_bridge.py`、`core/platform/overlay_client.py`、`utils/update/update_apply.py`、`ui/services/update_service.py`（按接线需要）；新增 `tests/test_host_lifecycle.py`，扩展 overlay/update 测试。

- [ ] 实现 helper 优先分流，正常单实例窗口激活和启动竞态；第二次启动不创建 Backend，也不把已最大化的旧窗口还原。
- [ ] 所有退出原因统一状态机；用户关闭/更新关闭/自愈退出是预期路径，错误提示只针对意外退出。IFileDialog 和 pending invoke 都结束。
- [ ] 实现 5 秒总预算及 reader I/O 取消，正常退出完成清理；超时只终止明确拥有的 Backend，保留用户游戏。
- [ ] overlay 专用 Job 覆盖已连接/连接前崩溃；不修改 overlay 消息协议。测试正常 quit、强制 Backend 退出和用户游戏存活。
- [ ] 更新 applyUpdate、启动自愈和 helper 参数：新调用传 Host+Backend 身份，旧 --pid 入口继续工作；等待两进程释放文件，结果/exit_requested 顺序明确。
- [ ] 加入双 exe 白名单和备份集合，回滚时删除仅新包拥有的程序文件；路径保护和幂等恢复测试继续通过。
- [ ] 注入时钟/进程替身覆盖超时、早退、正常关闭不误报；再用真实 Backend/overlay 进程验证一次。

**完成条件：** helper 可在应用运行时启动，不被单实例吞掉；退出不会留 Backend/overlay，不会杀游戏；更新前真正等待两个旧进程。

### Task 10：组合包、冻结验证与移除 pywebview

**依赖：** Task 0–9。**文件：** 修改 `scripts/develop.spec`、`scripts/package_develop.py`、`scripts/runtime_portable.py`、`scripts/frozen_smoke.py`、`scripts/verify_frozen_update.py`、`utils/update/updater.py`、`requirements.txt`、`main.py`；新增 `scripts/verify_frozen_host.py`；同步既有测试与当前架构/构建文档。

- [ ] PyInstaller 入口改为 backend_main.py、输出名 KazariPlayBackend、console=False，删除 webview/pythonnet/clr 相关 hidden import；仅删除已确认没有其它消费者的依赖。
- [ ] package_develop 构建前端 → 校验 staging → 构建 Backend → 构建 Host → 合包；原有 overlay x64/x86 构建仍按项目要求单独顺序完成，不能混入其它分支产物。
- [ ] 隔离开发包允许当前 `feature/winhost`；`--release` 仍只允许 develop/main、干净 worktree。不为分支测试放宽正式发布门槛，不覆盖已有 output。
- [ ] 更新 BUILD_INFO 的 `layout=winhost-v1`、两 exe 的版本/架构、SDK 版本/摘要及 commit；普通正式版本由版本策略另行定号，本任务不虚构新 Release。
- [ ] runtime_portable 继续在业务导入前设置数据目录，移除对旧 frozen_smoke.install 的 pywebview monkeypatch；main.py 普通运行仅提示运行 KazariPlay.exe，若保留 helper 兼容入口则直接分流至 Backend helper。
- [ ] 新冻结 smoke 由宿主侧 `verify_frozen_host.py --package <目录> --output <新目录>` 拉起实际 Host，以显式测试参数、隔离目录和离线数据验证。Host 内测试执行器使用真实 WebView2/桥；测试代码不能 import webview，也不能仅用假 JS 通过。
- [ ] smoke 覆盖版本/主题、无翻译 API、UI 新增编辑删除、数据库持久化、推送、原图/缩略图、overlay x64/x86、退出；报告同时记录 Host/Backend PID、版本、资源路径、检查项和错误。
- [ ] 用 verify_frozen_update 执行 3.9 的双进程更新矩阵，再移除旧窗口代码、旧类型/事件、resizer CSS/DOM 和全部运行期 pywebview 依赖。
- [ ] 在不安装 pywebview 的干净 Python 构建环境复跑测试与冻结包；检查源码/脚本/测试无 `import webview`、无 `window.pywebview`，历史文档提及允许保留。
- [ ] 同步 README、AGENTS、当前架构/前后端/测试/打包文档；记录实际完成状态，不把本计划全部自动勾选。

**完成条件：** 一个新目录中可双击 Host 启动真实库，Python 无安装依赖、无控制台/空白窗口；冻结 smoke 和更新演练报告通过。仅改 spec 文件或只打出两个 exe 不算完成。

### Task 11：实机验收记录与交付

**依赖：** Task 10。**文件：** 新增 `host/ACCEPTANCE.md`，回填本计划状态及文档索引。

- [ ] 使用第 5 节矩阵记录每项 PASS/FAIL/未验证、日期、commit、包摘要、Windows build、Runtime/SDK 版本、显示器分辨率和 DPI。
- [ ] 记录源码与冻结包各自证据，必须测试真实 WebView 输入/贴靠和文件对话框；不能由 mock 结果代替实机结论。
- [ ] 在未安装 Python/Node 的 Windows 环境验证发布目录；清楚区分 Windows 10 普通窗口行为和 Windows 11 Snap flyout。
- [ ] 任何必验项失败或无法验证时保留未勾选状态和具体阻塞，不以“已知问题”替代通过；发布需另有用户授权。

**完成条件：** 全部必验项有可追溯证据。方案修订、编码完成、源码验证、冻结验证和正式发布是不同状态。

## 5. 验证矩阵

| 层/场景 | 必须覆盖 | 证据/工具 |
|---|---|---|
| 帧与分片 | 长度边界、Unicode、部分读写、连续帧、非法数据、分片乱序/释放 | Python unittest + CTest + 双向向量 |
| dispatch | allowlist、窗口方法拒绝、内部钩子不可调用、参数错误、原返回类型 | host_dispatch 单测、前端 API 清单核对 |
| 并发与取消 | 对话框等待中读回包、并发 result/push、队列满、控制请求不饿死 | 双向 FakePort + 真实命名管道 |
| 前端启动 | 一次 init、一次首屏确认、异步拒绝语义、回调一次、reload 旧响应失效 | host_frontend/bridge contract/P0/P1 |
| 装配与路径 | 全 partial/script、CSS layer、暗色首帧、中文空格路径、只读安装源 | stager 单测、verify_frontend、浏览器实测 |
| 窗口 | 原生拖拽/边角/双击/Alt+F4、任务栏最小化、hover flyout/Win+Z、无重复点击 | Windows 11 实机，记录命中值 |
| DPI/显示器 | 100/125/150/200%、跨屏/负坐标、任务栏四侧及自动隐藏、最大化不遮挡 | 实机；区域不足 900×620 DIP 单独注明限制 |
| 页面输入 | 搜索/表单/中文 IME、Tab/辅助技术激活、滚轮/右键/选择/capture、触摸（设备可用时） | 真实 CompositionController |
| 对话框 | 多目录、exe/图片过滤、取消不写库、超时/关闭、焦点恢复 | 真实 IFileDialog + 隔离库 |
| 数据/媒体 | 原库副本加载、评分/收藏/扫描、封面 HTTP 与 base64、大截图返回 | P0/P1、媒体测试、冻结 smoke |
| 生命周期 | 双启动竞态、已最大化激活、握手失败/Runtime 缺失、EOF、Host/Backend 崩溃 | PID/handle 记录和退出时间 |
| 关闭 | 5 秒总预算、扫描/网络中关闭、对话框中关闭、overlay 连接前/后异常 | 真实子进程；用户游戏保持运行 |
| 安全边界 | 错客户端 PID、未知协议、非顶层/外站消息、越界资源根、超长帧 | transport/Host 隔离探针 |
| 更新旧 → 新 | 1.2.0 真实旧包启动新 helper、两 exe 落盘、数据保留、首屏确认 | verify_frozen_update 离线演练 |
| 更新新 → 新/回滚 | helper 绕过单实例、Host/Backend 文件锁、未确认早退、回滚不留新 Backend | 更新单测 + 冻结进程演练 |
| 分发 | 无 Python/Node 的 Windows、Evergreen 缺失提示、ZIP 无 data/cache | 清洁环境验收、包布局与摘要检查 |

### 门禁运行约定

以下命令在对应 Task 创建目标后从仓库根执行；PowerShell 按行检查 `$LASTEXITCODE`，失败时停止后续依赖项。build_host.ps1 应内部完成同样的错误传播。

```powershell
npm --prefix src/kazari_play/ui/web_assets run typecheck
npm --prefix src/kazari_play/ui/web_assets run build
python -m unittest discover -s tests -p "test_host*.py" -v
python -m unittest discover -s tests -p "test_backend_loop.py" -v
python -m unittest discover -s tests -p "test_web_asset_stager.py" -v
powershell -NoProfile -File scripts/build_host.ps1 -Test
python tests/verify_frontend.py
node tests/test_host_frontend.cjs
node tests/test_bridge_contract.cjs
node tests/test_p0_frontend.cjs
node tests/test_p1_frontend.cjs
node tests/test_update_ui.cjs
python tests/test_ui_sync.py
python -B tests/test_p0_data_flow.py
python -B tests/test_p1_reliability.py
python tests/test_classic_boundary.py
python tests/test_updater.py
python -B tests/test_update_apply.py
python -m compileall -q src/kazari_play scripts
```

上述不是删除既有测试的许可；每次按实际改动补跑 [testing.md](../dev/testing.md) 的对应套件。overlay 生命周期改动还需 `test_overlay_lifecycle.py` / `smoke_overlay.py`；打包后另跑 Host smoke 和 frozen update。数据库/配置均使用临时目录或显式副本，不用真实库作为失败测试目标。

## 6. 官方参考与修订规则

- [WebView2 threading model](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/threading-model)：STA、持续消息泵、回调内模态重入限制。
- [WebView2 CompositionController](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2compositioncontroller?view=webview2-1.0.4129.50)：visual hosting、输入转发、光标和焦点职责。
- [Windows 11 Snap layouts](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu)：HTMAXBUTTON 与最小窗口尺寸的限制。
- [现有打包约定](../dev/PACKAGING.md) 和 [版本策略](../dev/VERSIONING.md)：实施时同步现役文档，保留旧版升级所需契约。

实机证据若要求更改 controller、进程布局、消息字段或最小尺寸，先更新本文件对应的**唯一设计定义**及关联任务/测试，再继续实现。不要在任务末尾追加一套与前文冲突的接口，也不要因文档中的计划步骤存在就把它视为已完成。
