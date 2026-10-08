# overlay/ — 游戏内提示（C++）

> 独立 C++ 进程，经**命名管道**接收 Python 主程序消息，在游戏窗口右下角绘制截图成功提示。
> 原版（`main`/`develop`）**仅编译截图 toast**；字幕 / Hook / AI / Textractor 在 `feature/hook-translation`，原版无需对应 DLL/LIB。
> 形态：Direct2D + DirectWrite 绘制的**置顶透明分层窗口**；仅覆盖窗口化/无边框全屏游戏，独占全屏不在目标内。

## 目录

```
overlay/
├── src/
│   ├── main.cpp            # WinMain：DPI 感知、消息循环、装配 PipeServer ↔ ToastWindow
│   ├── protocol.h          # 消息解析（show/hide/quit/ping）
│   ├── pipe_server.h/.cpp  # 命名管道服务端（双工长连接）
│   └── toast_window.h/.cpp # 分层窗口 + D2D 绘制 + 动画
├── build.bat / build32.bat # x64 → bin/；x86 → bin32/
├── CMakeLists.txt
├── third_party/json.hpp    # nlohmann/json 单头
└── README.md
```

## 构建与产物

需 VS2022 Build Tools（含 C++ 工作负载）。
```bat
cd overlay
build.bat      :: x64 -> bin/overlay.exe
build32.bat    :: x86 -> bin32/overlay.exe
```
- `build.bat` / `build32.bat` **共用当前目录 OBJ，必须顺序运行**（避免架构混编/文件占用）。
- 依赖系统库：`d2d1 dwrite windowscodecs ole32 user32 gdi32`。
- 打包要求：`package_develop.py` 前需先完成 x64/x86 两个 overlay 构建（`bin/` + `bin32/`）。

## 运行

```
overlay.exe <管道名>
```
`<管道名>` 省略默认 `KazariPlayOverlay`。Python 侧传 `KazariPlayOverlay_{os.getpid()}`（`OverlayClient`）避免多实例冲突。

## 通信协议（命名管道，`PIPE_TYPE_MESSAGE` 单消息 JSON，UTF-8）

| type | 字段 | 说明 |
|---|---|---|
| `show` | `hwnd`(u64), `path`(png utf-8), `title`, `duration`(秒) | 显示 toast；`duration` 转 `duration_ms`（默认 3000） |
| `hide` | — | 隐藏 |
| `quit` | — | 退出进程 |
| `ping` | — | 存活检测（预留） |

`protocol::parseCommand` 容错解析（非法 JSON → `Unknown`）。字段映射见 `protocol.h::ShowMessage`。

## 组件

### main.cpp
- `EnableDpiAwareness()`：`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`
- `PipeNameFromArg(lpCmdLine)`：去除首尾空白
- `WinMain`：建 `ToastWindow` → 建 `PipeServer`（消息回调 → `PostMessageW` `WM_APP_SHOW/HIDE/QUIT` 到 toast 窗口）→ `setOnDisconnect`（管道断开 → `WM_APP_QUIT`，**防进程残留**）→ 标准 `GetMessage` 循环
- `WM_APP_SHOW` 的 `ShowMessage*` 由 toast 处理并 `new/delete`（`PostMessage` 失败则立即 delete）

### pipe_server.cpp（服务端）
- 单实例管道：`\\.\pipe\<name>`，`PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED`，`PIPE_TYPE_MESSAGE | READMODE_MESSAGE | PIPE_WAIT`，缓冲 64KB。
- 独立线程 `loop()`：`CreateNamedPipeW` → `ConnectNamedPipe`（重叠，处理 `ERROR_PIPE_CONNECTED / ERROR_IO_PENDING`）→ 重叠 `ReadFile` 循环把整条消息交 `m_handler` → 断开后 `DisconnectNamedPipe`+`CloseHandle` 并触发 `m_onDisconnect`，回到 accept 循环。
- **关键**：取消后**不立即释放** `OVERLAPPED`/缓冲，必须等内核完成（`finish` 内轮询 event，`m_stopping` 时 `CancelIoEx` 再 `GetOverlappedResult`）。
- `sendToClient`（反向写，预留双工）：`WriteFile` 重叠 + 2s 超时；无连接返回 false。

### toast_window.cpp（分层窗口 + 绘制）
- 窗口样式：`WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` + `WS_POPUP`（点击穿透、不抢焦点、不进 Alt+Tab）。
- 绘制：WIC 位图渲染目标 + D2D。尺寸 256×64，圆角卡片（背景 `#FFF8F5@0.96`、粉色描边）、左侧 72×48 圆角缩略图（WIC 解码 PNG，`PAD=8`）、右侧「截图已保存」标题 + 游戏名（Microsoft YaHei UI，标题 14pt bold / 副文本 11pt，超 22 字截断加省略号）。
- 输出：`paintLayered` 把 WIC 像素拷入 DIB（`CreateDIBSection`）再用 `UpdateLayeredWindow(ULW_ALPHA)` 呈现（alpha 混合）。
- 定位：目标 = 游戏窗口客户区右下 `hwnd.GetWindowRect`，`MARGIN=8`。
- 动画状态机 `AnimState`：`Hidden → SlideIn → Shown →（TIMER_HIDE 到期）SlideOut → Hidden`；滑动 250ms，帧 16ms；进入 `EaseOutCubic`、退出 `EaseInQuad`。
- 生命周期：`show` 重置计时器与位置并启动 SlideIn；`requestQuit` 停计时器 + `DestroyWindow`（`WM_DESTROY` → `PostQuitMessage`）。

## Python 侧对接（`core/overlay_client.py`）

- 单例；管道名 `KazariPlayOverlay_{os.getpid()}`；懒启动 `_resolve_exe`（x64 `overlay/bin/`，x86 `bin32/`，支持 `overlay.exe_path` 覆盖 + 打包 `_MEIPASS`）。
- `show(hwnd, path, title)` 读取 `overlay.toast_duration` → JSON → 长连接写入。
- 双工：读线程检测服务端断开；`quit()` 停进程。
- **失败静默降级**：overlay 缺失/连接失败不影响截图保存与前端提示。

## 触发链（原版）

```
全局热键（main.py 注册）→ WebBridge.takeScreenshotRunning()
 → screenshot_service 截游戏窗口 → 保存原图+缩略图
 → _push_screenshot_toast：全屏则先提示「建议窗口化」
 → OverlayClient.show(hwnd, path, title) → 管道 → overlay.exe 绘制 toast
```
