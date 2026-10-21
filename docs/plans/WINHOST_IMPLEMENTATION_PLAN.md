# KazariPlay WinHost Implementation Plan

> **归档状态：未实施（2026-10-21）。** 本文件是保留的 WinHost 实施方案，不属于当前构建入口；现有实现仍为 Python + pywebview。执行前需先解决前端 `__host` 启动、页面 staging、WebView2 SDK/打包、管道并发与多选文件对话框等审查问题。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用薄 C++ 窗口宿主替换 pywebview，保住现有粉色标题栏外观，把拖拽、缩放、贴靠和最大化交还 Windows，Python 业务层不重写。

**Architecture:** 用户只启动 `KazariPlay.exe`（C++ WinHost）。它创建带系统粗边框的窗口，用 WebView2 系统运行时加载现有前端，经一条命名管道把 `dispatch` / `push` / 文件对话框转给 Python 后端。Python 继续拥有 GameManager、扫描、元数据、SQLite 和 overlay 客户端。

**Tech Stack:** C++17、Win32、DWM、Microsoft Edge WebView2 Evergreen Runtime、命名管道、Python 3.11、现有 TypeScript 前端。不引入 Tauri、Rust、HTTP 或另一套 Python 网页壳。

**Spec:** 本文件「已锁定设计」一节。执行时以该节为准，不要回退到 pywebview，也不要扩成 C++ 全栈重写。

## Global Constraints

- 外观保持现有无边框粉色标题栏；窗口行为必须是系统的。
- 宿主是 C++，不是 pywebview 子类，也不是 Tauri。
- 删除 `pywebview`。不换成 Qt、CEF 或其他 Python 网页壳。
- WebView2 使用系统 Evergreen Runtime，不捆绑 Chromium。
- 桥是一条命名管道，不用 HTTP / WebSocket。
- Python 对外只有 `dispatch(method, args)`、`push(script)`，以及被宿主拉起和关闭。
- 选文件夹 / 选文件仍由现有 WebBridge 方法发起，宿主用 `IFileDialog` 把路径回传。前端业务方法不搬。
- `KazariPlay.exe` 是唯一用户入口。第二次启动只激活已有窗口。
- 后端握手成功后才显示页面。关闭时通知后端停止 overlay，最多等待 5 秒。后端崩溃时宿主弹系统对话框并退出。
- 前端资源用虚拟主机映射，不再用 `main.py` 的 `_load_html()` 内联拼接。
- 删除 `window.ts` 的拖拽和八个 `.resizer`。最大化状态由宿主推送，不读按钮文案。
- 最大化按钮的命中测试必须返回 `HTMAXBUTTON`。
- 不修改 GameManager、扫描、元数据匹配、SQLite schema、overlay 协议。
- 本计划不包含安装器、Authenticode 签名、开始菜单、卸载项、Mica、跳转列表。
- 管道帧最大 8 MiB。握手超时 15 秒。关闭等待 5 秒。

---

## 已锁定设计

### 模块与缝

WinHost 是用户启动的唯一进程。缝只在「窗口与系统」和「业务」之间。

| 模块 | 拥有 | 不拥有 |
|---|---|---|
| `host/` C++ WinHost | 窗口、DPI、自定义边框命中测试、WebView2、单实例、管道、文件对话框、进程生命周期 | 游戏、扫描、元数据、数据库、overlay |
| Python 后端 | 现有 WebBridge 业务方法、UISync 推送、overlay 退出 | 窗口样式、拖拽、贴靠 |
| 现有前端 | 页面外观。只改 `core.ts` 的 bridge 取值，以及标题栏状态接收 | 窗口命中测试 |

### 管道帧

小端 `uint32` 长度，后跟 UTF-8 JSON 对象。长度不含这 4 个字节。超过 8 MiB 的帧视为协议错误并断开。

管道名：`\\.\pipe\KazariPlay.<宿主进程 ID>`。宿主创建管道，再启动后端，并把该名字作为第一个参数传入。

宿主 → Python：

```json
{"type":"call","id":1,"method":"getGames","args":[]}
{"type":"dialog_result","id":7,"ok":true,"path":"D:\\games"}
{"type":"shutdown"}
```

Python → 宿主：

```json
{"type":"ready"}
{"type":"result","id":1,"ok":true,"result":[]}
{"type":"result","id":1,"ok":false,"error":"unknown method"}
{"type":"eval","code":"window.__host.setMaximized(true)"}
{"type":"dialog","id":7,"kind":"folder","title":"选择游戏文件夹"}
{"type":"dialog","id":7,"kind":"file","title":"选择可执行文件","filter":"Programs (*.exe)|*.exe"}
```

`dialog_result.ok == false` 表示用户取消，`path` 为空字符串。`kind` 只允许 `folder` 和 `file`。

### JS 桥

`core.ts` 的 `bridge` Proxy 继续存在，调用方和末尾回调风格不变。取值不再读 `window.pywebview.api`，改为 `window.__host.invoke(name, args)`。

宿主在文档创建时注入：

```javascript
window.__host = {
  invoke(name, args) { /* postMessage，返回 Promise */ },
  _settle(id, ok, result) { /* 完成对应 Promise */ },
  setMaximized(on) { /* 只更新标题栏图标，不调用 windowToggleMaximize */ }
};
```

`windowMinimize`、`windowToggleMaximize`、`windowClose`、`windowStartDrag`、`windowMoveDrag`、`windowEndDrag`、`windowResize`、`windowResizeStart` 由宿主本地处理，不进入 Python `dispatch`。

### 窗口

- 样式包含 `WS_OVERLAPPEDWINDOW`（含 `WS_THICKFRAME`、`WS_CAPTION`、`WS_MINIMIZEBOX`、`WS_MAXIMIZEBOX`）。
- `DwmExtendFrameIntoClientArea` 把客户区扩到整窗。
- `WM_NCCALCSIZE` 在 `wParam == TRUE` 时去掉系统标题栏占用，保留贴靠所需的粗边框。
- `WM_NCHITTEST`：标题栏空白返回 `HTCAPTION`；最小化 / 最大化 / 关闭分别返回 `HTMINBUTTON`、`HTMAXBUTTON`、`HTCLOSE`；四边和四角返回对应 `HT*`。
- 页面在 `resize` 时把这三个按钮的客户区矩形发给宿主。首帧未到之前，按 40 CSS 像素标题栏高、右侧三个 46 CSS 像素按钮估算，DPI 用 `GetDpiForWindow`。
- 进程 manifest 声明 `PerMonitorV2`。不用 `GetSystemMetrics` 决定窗口大小；用主显示器工作区的 82%，最小 900×620 物理像素按 DPI 换算。

### 生命周期

1. 创建命名互斥量 `Local\KazariPlay.WinHost`。已存在则找到窗口类 `KazariPlayHost`，激活后退出，退出码 0。
2. 创建管道并启动后端。
3. 15 秒内收不到 `ready`：`MessageBoxW` 说明后端未就绪，退出码 1。
4. 收到 `ready` 后创建 WebView2 并导航。
5. `WM_CLOSE`：向 Python 发送 `shutdown`，最多等 5 秒，然后结束后端进程并退出。
6. 管道断开或后端进程提前退出：`MessageBoxW` 说明后端已退出，然后关闭窗口。不留空白 WebView 继续运行。

开发期后端命令：

```text
python src/kazari_play/backend_main.py \\.\pipe\KazariPlay.<pid>
```

工作目录是仓库根。`backend_main.py` 把自己所在目录插入 `sys.path`，与当前 `main.py` 能 `import core` / `import ui` 的方式一致。

### 明确不在本计划

- 安装器、代码签名、开始菜单、卸载项、AppUserModelID 持久化。
- `RegisterHotKey` 替换 `keyboard` 库、系统主题跟随、任务栏进度、托盘。这些以后加在 WinHost 上，不在本计划扩 scope。
- C++ 重写业务层。`docs/plans/CPP_REWRITE_PLAN.md` 和 `TAURI_MIGRATION_PLAN.md` 仍是未实施历史方案，不是本计划的入口。

---

## 文件结构

- Create: `host/CMakeLists.txt` — 只编 WinHost，不编 overlay。
- Create: `host/src/protocol.hpp` — 帧编解码。
- Create: `host/src/protocol_test.cpp` — 帧的黄金向量测试。
- Create: `host/src/window.hpp` / `host/src/window.cpp` — 窗口、DPI、命中测试。
- Create: `host/src/webview.hpp` / `host/src/webview.cpp` — WebView2 与虚拟主机。
- Create: `host/src/backend.hpp` / `host/src/backend.cpp` — 管道、拉起 Python、对话框。
- Create: `host/src/main.cpp` — 互斥量、消息循环、崩溃退出。
- Create: `host/app.manifest` — `PerMonitorV2`。
- Create: `src/kazari_play/host_protocol.py` — 与 C++ 相同的帧格式。
- Create: `src/kazari_play/backend_main.py` — 无窗口后端入口。
- Create: `src/kazari_play/ui/host_dispatch.py` — 调用 WebBridge 公开方法。
- Create: `tests/test_host_protocol.py`
- Create: `tests/test_host_dispatch.py`
- Modify: `src/kazari_play/ui/web_assets/ts/core.ts` — bridge 改走 `__host.invoke`。
- Modify: `src/kazari_play/ui/web_assets/ts/window.ts` — 只留 `setMaximized`。
- Modify: `src/kazari_play/ui/web_assets/index.html` — 去掉拖拽 onclick 和 `.resizer`。
- Modify: `src/kazari_play/main.py` — 开发入口改为启动说明，不再 `webview.start`。
- Modify: `requirements.txt` — 删除 `pywebview`。
- Modify: `scripts/develop.spec` — 用户入口改为宿主；Python 改为无窗口 sidecar。这一项只改到能在开发机打出两个 exe，不新增安装器。

---

### Task 1: 管道帧协议

**Files:**
- Create: `src/kazari_play/host_protocol.py`
- Test: `tests/test_host_protocol.py`

**Interfaces:**
- Consumes: 无。
- Produces: `encode_frame(obj: dict) -> bytes`，`decode_frame(buf: bytearray) -> dict | None`。`decode_frame` 在字节不够时返回 `None` 且不消耗缓冲；帧完整时弹出一个对象。长度大于 8388608 抛 `ProtocolError`。

- [ ] **Step 1: Write the failing test**

```python
import json
from kazari_play.host_protocol import ProtocolError, decode_frame, encode_frame


def test_roundtrip_call():
    raw = encode_frame({"type": "call", "id": 1, "method": "getGames", "args": []})
    buf = bytearray(raw)
    msg = decode_frame(buf)
    assert msg == {"type": "call", "id": 1, "method": "getGames", "args": []}
    assert buf == bytearray()


def test_partial_frame_waits():
    raw = encode_frame({"type": "ready"})
    buf = bytearray(raw[:3])
    assert decode_frame(buf) is None
    assert len(buf) == 3


def test_rejects_oversize_length():
    buf = bytearray((8388609).to_bytes(4, "little"))
    try:
        decode_frame(buf)
    except ProtocolError:
        return
    raise AssertionError("expected ProtocolError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_host_protocol.py -v`
Expected: FAIL，`host_protocol` 不存在。

- [ ] **Step 3: Write minimal implementation**

```python
import json
import struct

MAX_FRAME = 8 * 1024 * 1024


class ProtocolError(Exception):
    pass


def encode_frame(obj: dict) -> bytes:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ProtocolError("frame too large")
    return struct.pack("<I", len(body)) + body


def decode_frame(buf: bytearray):
    if len(buf) < 4:
        return None
    size = struct.unpack_from("<I", buf, 0)[0]
    if size > MAX_FRAME:
        raise ProtocolError("frame too large")
    if len(buf) < 4 + size:
        return None
    body = bytes(buf[4:4 + size])
    del buf[:4 + size]
    msg = json.loads(body.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ProtocolError("frame must be an object")
    return msg
```

导入路径按仓库现有测试的 `sys.path` 习惯调整。若测试从仓库根运行且包名不是 `kazari_play`，测试改为把 `src/kazari_play` 插入 `sys.path` 后 `import host_protocol`。两种写法选与现有 `tests/` 一致的一种，不要两套并存。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_host_protocol.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kazari_play/host_protocol.py tests/test_host_protocol.py
git commit -m "feat: add WinHost pipe frame codec"
```

---

### Task 2: C++ 帧编解码与同一组向量

**Files:**
- Create: `host/src/protocol.hpp`
- Create: `host/src/protocol_test.cpp`
- Create: `host/CMakeLists.txt`
- Modify: `tests/test_host_protocol.py`

**Interfaces:**
- Consumes: Task 1 的帧格式。
- Produces: `host::encodeFrame(const nlohmann::json&)`、`host::decodeFrame(std::string&)`。测试可执行文件 `host_protocol_test`。

- [ ] **Step 1: 在 Python 测试里固定一条黄金向量**

```python
def test_golden_ready_frame():
    assert encode_frame({"type": "ready"}) == bytes.fromhex(
        "110000007b2274797065223a227265616479227d"
    )
```

`{"type":"ready"}` 是 17 字节，小端长度 `11 00 00 00`。先跑测试，按 `encode_frame` 的真实输出修正 hex，然后把该 hex 抄进 C++ 测试。不要手写一套不同的 JSON 空白规则。

- [ ] **Step 2: C++ 测试先失败**

`host/src/protocol_test.cpp` 比较同一 hex。CMake 目标 `host_protocol_test` 只链协议文件，不链 WebView2。

Run: `cmake -S host -B host/build && cmake --build host/build --target host_protocol_test && host\build\host_protocol_test.exe`
Expected: 在实现前链接失败或断言失败。

- [ ] **Step 3: 实现与 Python 相同的长度前缀**

使用仓库已有的 `overlay/third_party/json.hpp`，不要再复制一份。`decodeFrame` 在缓冲不足时返回空 `optional`，不丢弃已读字节。超过 8388608 抛异常。

- [ ] **Step 4: 两边测试都通过**

Python 黄金向量测试 PASS。`host_protocol_test.exe` 退出码 0。

- [ ] **Step 5: Commit**

```bash
git add host tests/test_host_protocol.py
git commit -m "feat: match WinHost frame codec in C++"
```

---

### Task 3: Python dispatch

**Files:**
- Create: `src/kazari_play/ui/host_dispatch.py`
- Test: `tests/test_host_dispatch.py`

**Interfaces:**
- Consumes: 现有 `WebBridge` 实例。不要求窗口已创建。
- Produces: `dispatch(bridge, method: str, args: list)`。下划线开头、不存在、或不可调用都抛 `DispatchError`。窗口方法名在 `HOST_LOCAL_METHODS` 中，dispatch 拒绝它们。

`HOST_LOCAL_METHODS` 固定为：

```python
HOST_LOCAL_METHODS = {
    "windowMinimize",
    "windowToggleMaximize",
    "windowClose",
    "windowStartDrag",
    "windowMoveDrag",
    "windowEndDrag",
    "windowResize",
    "windowResizeStart",
}
```

- [ ] **Step 1: Write the failing test**

用一个不继承 WebBridge 的假对象：

```python
def test_dispatch_calls_public_method():
    class Api:
        def getGames(self):
            return [{"id": "1"}]
    assert dispatch(Api(), "getGames", []) == [{"id": "1"}]


def test_dispatch_rejects_private_and_window():
    class Api:
        def _secret(self):
            return 1
        def windowClose(self):
            return 1
    for name in ("_secret", "windowClose", "missing"):
        try:
            dispatch(Api(), name, [])
        except DispatchError:
            continue
        raise AssertionError(name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_host_dispatch.py -v`
Expected: FAIL

- [ ] **Step 3: Implement dispatch**

`getattr` 后检查 `callable` 且 `not method.startswith("_")` 且不在 `HOST_LOCAL_METHODS`。用 `fn(*args)` 调用。不要 `eval`，不要按名字去 `main.py` 找函数。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_host_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kazari_play/ui/host_dispatch.py tests/test_host_dispatch.py
git commit -m "feat: dispatch WebBridge methods for WinHost"
```

---

### Task 4: 无窗口后端循环

**Files:**
- Create: `src/kazari_play/backend_main.py`
- Test: `tests/test_backend_loop.py`

**Interfaces:**
- Consumes: `encode_frame` / `decode_frame`、`dispatch`。
- Produces: `serve(port, bridge) -> None`。`port` 需要 `read_frame()` 和 `write_frame(dict)`。收到 `shutdown` 时调用 `bridge.on_host_shutdown()` 后返回。收到 `call` 时写 `result`。收到 `dialog_result` 时完成对应的等待。`request_dialog(port, kind, title, filter) -> str | None` 写出 `dialog` 并等待结果；取消返回 `None`。

本任务不启动真实管道，也不创建 WebBridge。测试用内存假端口。

- [ ] **Step 1: Write the failing test**

```python
def test_call_roundtrip():
    class Api:
        def ping(self, n):
            return n + 1
        def on_host_shutdown(self):
            self.closed = True
    port = FakePort([
        {"type": "call", "id": 3, "method": "ping", "args": [4]},
        {"type": "shutdown"},
    ])
    api = Api()
    serve(port, api)
    assert port.written[0]["type"] == "ready"
    assert port.written[1] == {"type": "result", "id": 3, "ok": True, "result": 5}
    assert api.closed is True
```

`FakePort.read_frame()` 依次返回列表中的消息，然后返回 `None`。`serve` 在 `read_frame()` 返回 `None` 时也要退出，这覆盖后端被断开的情况。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backend_loop.py -v`
Expected: FAIL

- [ ] **Step 3: Implement serve**

进入循环前先 `write_frame({"type": "ready"})`。`call` 的异常写成 `ok: false`，不要让后端进程退出。`dialog` 的等待用线程安全队列，超时 120 秒后向调用方抛 `TimeoutError`。`on_host_shutdown` 里只做现有关闭逻辑需要的钩子；本任务的假对象没有 overlay。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backend_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kazari_play/backend_main.py tests/test_backend_loop.py
git commit -m "feat: add headless backend loop for WinHost"
```

---

### Task 5: 自定义边框窗口，先不接 WebView2

**Files:**
- Create: `host/src/window.hpp`
- Create: `host/src/window.cpp`
- Create: `host/app.manifest`
- Modify: `host/CMakeLists.txt`
- Create: `host/src/main.cpp`

**Interfaces:**
- Consumes: 无 Python。
- Produces: 窗口类 `KazariPlayHost`。`Window::setCaptionRects(RECT min, RECT max, RECT close)`。`Window::isMaximized()`。

- [ ] **Step 1: 写命中测试的纯函数测试**

把命中测试抽成不依赖 HWND 的函数，方便断言：

```cpp
Hit regionAt(POINT client, CaptionRects caps, RECT windowSize, int dpi);
```

测试：客户区 (10, 10) 在 96 DPI、标题栏高 40 时返回 `HTCAPTION`。最大化按钮矩形内返回 `HTMAXBUTTON`。窗口左边缘 4 物理像素内返回 `HTLEFT`。按钮矩形优先于标题栏。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cmake --build host/build --target host_window_test`
Expected: FAIL

- [ ] **Step 3: 创建真实窗口**

`main.cpp` 注册类、创建 `WS_OVERLAPPEDWINDOW` 窗口、加载 `app.manifest` 的 `PerMonitorV2`。`WM_NCCALCSIZE` 使用 Microsoft 自定义标题栏写法：`wParam` 为 TRUE 时调整 `NCCALCSIZE_PARAMS`，不要简单 `return 0` 丢掉最大化边距，否则最大化会盖住任务栏。`WM_NCHITTEST` 调用 `regionAt`。`WM_SIZE` 记录是否最大化。

初始大小：主显示器工作区的 82%，用 `MonitorFromPoint` + `GetMonitorInfo`，不用 `GetSystemMetrics(0/1)`。最小跟踪尺寸 900×620，按 DPI 缩放。

- [ ] **Step 4: 手工验收这一任务**

运行 `host.exe`。预期：

- 窗口出现，可拖标题栏区域，可拉边框。
- Win+Left / Win+Right 能贴靠。
- 最大化不盖住任务栏。
- 150% 缩放的显示器上边框不抖、不缩成一条。

此任务还没有粉色 UI，也没有贴靠飞出。飞出依赖 `HTMAXBUTTON`，放到 Task 6 按钮矩形接通后验收。

- [ ] **Step 5: Commit**

```bash
git add host
git commit -m "feat: add WinHost custom frame window"
```

---

### Task 6: WebView2 加载现有前端

**Files:**
- Create: `host/src/webview.hpp`
- Create: `host/src/webview.cpp`
- Modify: `host/CMakeLists.txt`
- Modify: `host/src/main.cpp`

**Interfaces:**
- Consumes: Task 5 的 `Window`。
- Produces: `WebView::navigateApp()`。虚拟主机名 `kazariplay.local`。导航 `https://kazariplay.local/index.html`。`WebView::postMaximized(bool)` 执行 `window.__host.setMaximized(true|false)`。

- [ ] **Step 1: 注入引导脚本，而不是先改全部页面**

`AddScriptToExecuteOnDocumentCreated` 注入：

```javascript
window.__host = window.__host || {
  _pending: new Map(),
  _seq: 0,
  invoke(name, args) {
    const id = ++this._seq;
    const run = new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
    });
    chrome.webview.postMessage({ type: "call", id, method: name, args });
    return run;
  },
  _settle(id, ok, result) {
    const item = this._pending.get(id);
    if (!item) return;
    this._pending.delete(id);
    if (ok) item.resolve(result);
    else item.reject(new Error(String(result)));
  },
  setMaximized(on) {
    document.body.classList.toggle("maximized", !!on);
    const b = document.getElementById("btnMax");
    if (!b || !window.ICON) return;
    b.setAttribute("aria-label", on ? "还原窗口" : "最大化");
    b.innerHTML = on ? ICON.winRestore : ICON.winMax;
  }
};
window.addEventListener("resize", () => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  };
  chrome.webview.postMessage({
    type: "caption",
    min: pick(".winbtns .winbtn:nth-child(1)"),
    max: pick("#btnMax"),
    close: pick(".winbtns .winbtn.close")
  });
});
```

宿主收到 `caption` 后把 CSS 像素乘当前 DPI/96，调用 `setCaptionRects`。收到 `call` 且方法属于 `HOST_LOCAL_METHODS` 时本地处理并 `_settle`，不要等 Python。

- [ ] **Step 2: 映射资源目录**

开发期映射 `src/kazari_play/ui/web_assets`。用 `SetVirtualHostNameToFolderMapping`。不要 `NavigateToString` 整页内联。`index.html` 里的 `{{THEME}}`、`{{APP_VERSION}}`、`{{APP_TITLE}}`、`{{PRODUCT_LINE}}` 在复制到宿主可读目录前替换：主题先写 `light`，版本读现有 `version.py` 的 `DISPLAY_VERSION`。这一任务允许宿主启动时用 Python 一行命令打印版本，或直接读 `version.py` 的赋值。不要再调用 `_load_html()`。

- [ ] **Step 3: 构建并打开窗口**

Run: `cmake --build host/build --config Release`
Expected: 窗口里出现现有 UI。CSS 和 JS 从虚拟主机加载，不出现中文路径 `file://` 404。

- [ ] **Step 4: 验收贴靠飞出**

鼠标悬停粉色最大化按钮，Windows 11 应出现贴靠布局。双击标题栏空白最大化。按钮图标与真实最大化状态一致，不依赖点击次数。若飞出不出现，先检查该点返回值是不是 `HTMAXBUTTON`，不要回到 JS 拖拽。

- [ ] **Step 5: Commit**

```bash
git add host
git commit -m "feat: load KazariPlay UI in WinHost WebView2"
```

---

### Task 7: 接通管道与一次业务调用

**Files:**
- Create: `host/src/backend.hpp`
- Create: `host/src/backend.cpp`
- Modify: `host/src/main.cpp`
- Modify: `src/kazari_play/backend_main.py`
- Modify: `src/kazari_play/ui/web_assets/ts/core.ts`

**Interfaces:**
- Consumes: Task 1–4 的帧、`serve`、`dispatch`。
- Produces: 宿主在显示页面前完成握手。`core.ts` 的 `bridge` 通过 `__host.invoke` 调用。

- [ ] **Step 1: 改 core.ts 的取值，保留回调**

只替换 Proxy 的 `get`。末尾函数参数仍是回调。`invoke` 失败时保持现在的行为：回调 `('[]', true)` 并 `resolve('[]')`。不要改 `esc`、`toast`、`loadCoverTo`。

```typescript
const api = window.__host;
const fn = api && api.invoke;
if (!fn) { if (notify) notify('[]', true); return Promise.resolve('[]'); }
const p = fn.call(api, name, args);
```

- [ ] **Step 2: 宿主拉起后端并等待 ready**

`CreateNamedPipeW`，名称为 `\\.\pipe\KazariPlay.<GetCurrentProcessId()>`。`CreateProcessW` 启动：

```text
python src/kazari_play/backend_main.py \\.\pipe\KazariPlay.<pid>
```

15 秒内没有 `ready` 就 `MessageBoxW` 并退出。不要先显示 WebView 再等后端。

- [ ] **Step 3: 后端接到管道**

`backend_main.py` 用 `win32file` 或标准库不可用时用 `pywin32`。仓库已依赖 `pywin32`。连接管道后进入 `serve`。`WebBridge` 在这里构造，但不要调用 `webview.create_window`。文件对话框方法先抛 `DispatchError("dialog host not ready")`，Task 8 再接。

- [ ] **Step 4: 验收一条真实调用**

页面加载后，在 WebView2 开发工具或临时按钮调用 `bridge` 上一个只读方法（现有获取游戏列表的方法，以 `web_bridge.py` 的公开方法名为准）。预期：管道出现 `call`，Python 返回 `result`，页面 Promise 完成。窗口方法不会出现在 Python 日志里。

- [ ] **Step 5: Commit**

```bash
git add host src/kazari_play/backend_main.py src/kazari_play/ui/web_assets/ts/core.ts
git commit -m "feat: bridge WinHost calls to Python dispatch"
```

---

### Task 8: 推送与文件对话框

**Files:**
- Modify: `src/kazari_play/ui/sync.py`
- Modify: `src/kazari_play/ui/web_bridge.py`
- Modify: `host/src/backend.cpp`
- Test: `tests/test_backend_loop.py`

**Interfaces:**
- Consumes: `serve` 的 `dialog` / `dialog_result`，以及现有 `UISync` 的 `evaluate_js` 调用点。
- Produces: `HostPush.evaluate_js(code: str)`。WebBridge 里原来的 `create_file_dialog` 改为 `request_dialog`。

- [ ] **Step 1: 给后端循环补对话框测试**

```python
def test_dialog_cancel_returns_none():
    port = FakePort([
        {"type": "dialog_result", "id": 7, "ok": False, "path": ""},
    ])
    assert request_dialog(port, "folder", "选择游戏文件夹", "") is None
    assert port.written[-1]["type"] == "dialog"
    assert port.written[-1]["kind"] == "folder"
```

- [ ] **Step 2: 宿主处理 dialog**

收到 `kind == "folder"` 调用 `IFileDialog` 选文件夹。`kind == "file"` 用 `filter`。用户取消写 `ok: false`。不要用 Python 的 `tkinter` 对话框。

- [ ] **Step 3: 替换 WebBridge 的对话框实现**

搜索 `create_file_dialog` 和 `webview`。扫描文件夹、选择 exe、选择封面仍走原来的 WebBridge 方法名。方法内部改为向宿主要路径。返回值保持原方法的字符串或空。不要改这些方法的 JS 名称。

- [ ] **Step 4: UISync 改推到管道**

`evaluate_js` 改为 `port.write_frame({"type": "eval", "code": code})`。宿主收到后 `ExecuteScript`。不要在 Python 里保留 `window.evaluate_js`。

- [ ] **Step 5: 验收**

扫描文件夹弹出系统对话框。取消后库不变。触发一次会刷新卡片的操作，页面收到原来的 `window.__app.*` 调用。

- [ ] **Step 6: Commit**

```bash
git add src/kazari_play/ui/sync.py src/kazari_play/ui/web_bridge.py host/src/backend.cpp tests/test_backend_loop.py
git commit -m "feat: push UI updates and file dialogs through WinHost"
```

---

### Task 9: 生命周期

**Files:**
- Modify: `host/src/main.cpp`
- Modify: `src/kazari_play/backend_main.py`
- Modify: `src/kazari_play/ui/web_bridge.py`

**Interfaces:**
- Consumes: Task 7 的进程启动。
- Produces: 互斥量 `Local\KazariPlay.WinHost`。`on_host_shutdown()` 调用现有关闭路径：停封面服务、`overlay.quit()`。

- [ ] **Step 1: 单实例**

启动时 `CreateMutexW`。若 `GetLastError() == ERROR_ALREADY_EXISTS`，`FindWindowW(L"KazariPlayHost", nullptr)`，`ShowWindow(SW_RESTORE)`，`SetForegroundWindow`，然后退出码 0。不要开第二个 WebView。

- [ ] **Step 2: 关闭**

`WM_CLOSE` 发送 `shutdown`。Python 在 `on_host_shutdown` 里执行现在 `main.py` 的 `_on_window_closing` 所做的事。宿主等管道关闭或 5 秒，然后 `TerminateProcess`。5 秒是上限，不是正常路径。

- [ ] **Step 3: 后端崩溃**

在后端握手成功后手动结束 `python.exe`。预期：宿主弹出系统对话框，窗口关闭，没有残留 `overlay.exe`。用任务管理器确认。

- [ ] **Step 4: Commit**

```bash
git add host/src/main.cpp src/kazari_play/backend_main.py src/kazari_play/ui/web_bridge.py
git commit -m "feat: single-instance WinHost and bounded shutdown"
```

---

### Task 10: 删除 pywebview 窗口路径

**Files:**
- Modify: `src/kazari_play/ui/web_assets/ts/window.ts`
- Modify: `src/kazari_play/ui/web_assets/index.html`
- Modify: `src/kazari_play/main.py`
- Modify: `requirements.txt`
- Modify: `scripts/develop.spec`

**Interfaces:**
- Consumes: Task 6 的 `setMaximized`。
- Produces: 仓库源码和打包入口不再 import `webview`。

- [ ] **Step 1: 删掉页面里的窗口操作**

`window.ts` 只保留被宿主调用的 `setMaximized`。删除 `bindDrag`、`bindResize`、`toggleMax`。`index.html` 删除八个 `.resizer`，标题栏按钮去掉 `onclick`。按钮仍留在 DOM 里，供命中测试取矩形。

- [ ] **Step 2: main.py 不再创建窗口**

`main.py` 改为打印「请运行 host.exe」并退出码 0。业务启动只留在 `backend_main.py`。全仓库搜索 `import webview` 和 `pywebview`，源码与测试中应为 0。文档里的历史方案可以保留。

- [ ] **Step 3: 依赖与开发包**

`requirements.txt` 删除 `pywebview==6.2.1`。`develop.spec` 的用户可见 exe 改为 WinHost；Python 分析入口改为 `backend_main.py`，`console=False` 仍只属于宿主。不要在这一步做安装器。

- [ ] **Step 4: 前端类型检查与协议测试**

Run:

```text
python -m pytest tests/test_host_protocol.py tests/test_host_dispatch.py tests/test_backend_loop.py -v
npm --prefix src/kazari_play/ui/web_assets run build
```

Expected: 测试 PASS，`tsc` 通过。

- [ ] **Step 5: Commit**

```bash
git add src/kazari_play requirements.txt scripts/develop.spec
git commit -m "refactor: remove pywebview window path"
```

---

### Task 11: 完成定义验收

**Files:**
- Create: `host/ACCEPTANCE.md`

**Interfaces:**
- Consumes: Task 10 的可运行宿主。
- Produces: 一份勾过的验收记录。未勾项不能宣称本计划完成。

- [ ] **Step 1: 按下面清单在 Windows 11 上做一次**

- [ ] 只启动 `KazariPlay.exe`，不启动 Python 命令。游戏库能显示。
- [ ] 再启动一次，只出现一个窗口，原窗口被激活。
- [ ] 拖标题栏、拉边框、Win+Left、最大化不盖任务栏。
- [ ] 悬停最大化按钮出现贴靠布局。图标与实际状态一致。
- [ ] 150% 缩放下窗口和按钮命中区域不错位。
- [ ] 扫描文件夹是系统对话框。取消不改库。
- [ ] 关闭窗口后 5 秒内 `python` 后端和 `overlay.exe` 都退出。
- [ ] 握手成功后结束 Python 进程，宿主弹对话框并退出。
- [ ] 源码搜索不到 `import webview`。

- [ ] **Step 2: 把结果写进 `host/ACCEPTANCE.md`**

写机器 Windows 版本、DPI、通过或失败。失败项不要改写成已知问题后算通过。

- [ ] **Step 3: Commit**

```bash
git add host/ACCEPTANCE.md
git commit -m "docs: record WinHost acceptance"
```

---

## 自检

- 已锁定设计里的每条约束都有任务：帧协议 Task 1–2，dispatch Task 3，后端循环 Task 4，系统边框 Task 5，WebView2 与 `HTMAXBUTTON` Task 6，桥 Task 7，推送和对话框 Task 8，单实例与关闭 Task 9，删除 pywebview Task 10，验收 Task 11。
- 安装器、签名、热键替换、系统主题、任务栏进度写在「明确不在本计划」，没有被任务偷偷扩进去。
- 方法名 `dispatch`、`serve`、`request_dialog`、`HOST_LOCAL_METHODS`、`setMaximized`、`kazariplay.local` 在前后任务中一致。
