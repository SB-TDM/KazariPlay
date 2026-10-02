# KazariPlay → Tauri 外壳迁移方案（路线 B）

> **文档状态：未实施的历史方案。** 当前仓库没有 Tauri/Rust sidecar 工程，现行运行方式仍是 Python + pywebview + C++ Overlay。本文只保留方案评估，不是当前构建入口。文档分类见 [README.md](README.md)。

> 版本：V1.0 · 2026-08-19
> 目标：保留原有 Python 后端业务，用 **Tauri 原生壳 + Python 后端 sidecar** 换掉 pywebview，
> 拿到原生窗口 / 托盘 / 自启 / 标准安装包体验，同时不推倒既有的 Python 业务代码。
> 约束：**保留原项目 `KazariPlay_V1.0` 不动，迁移工作全部在新的 `KazariPlay_V2.0` 目录进行。**

---

## 一、为什么是路线 B

| 对比 | 结论 |
|---|---|
| 路线 A（后端全线重写 Rust） | 需把 `kazari_play/` 约 25+ 模块（元数据客户端/扫描/监控/截图/命名管道 IPC 等）全部用 Rust 重写，代价极高；维护人（个人、长期）不主打 Rust，风险比收益大。 |
| **路线 B（Tauri 壳 + Python sidecar）** | 前端 ~100% 复用，Python 业务零改动，Rust 只做一个薄转发壳。拿到原生壳 + 标准打包，成本最低。 |
| 不迁移，仅 PyInstaller | 解决「没人会装 Python」，但拿不到原生托盘/自启/通知等体验 —— 与本目标不符。 |

**本方案选路线 B。**

关键前提（已从现有代码确认）：
1. 前后端已完全解耦 —— 前端是纯静态 HTML/CSS/JS，经 `html=` 内联注入加载，无服务端依赖；
2. 前后端通信统一走 `pywebview.api.*` 的 JSON 字符串桥（WebBridge）；
3. 翻译 / 截图 toast 由独立 C++ 进程 `overlay.exe` 承担，Python 只透传配置 —— **换壳不影响它们**。

---

## 二、目标目录结构（新文件夹 KazariPlay_V2.0）

```
KazariPlay_V2.0/
├── README.md
├── docs/
│   └── TAURI_MIGRATION_PLAN.md      # 本文档
├── src/
│   └── web/                          # 前端：从原 KazariPlay_V1.0/kazari_play/ui/web_assets 拷贝
│       ├── index.html
│       ├── css/                      # 13 个 css
│       ├── js/                       # 17 个 js（含 core.js 桥代理改造点）
│       └── partials/                 # 6 个 partial
├── src-tauri/                        # Rust 壳（薄）
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── icons/
│   ├── src/
│   │   ├── main.rs
│   │   └── lib.rs                    # 窗口 + api 转发命令（含 sidecar 拉起/退出）
│   └── sidecars/
│       └── kazariplay-backend.exe    # PyInstaller 打包后的 Python 后端（产物）
├── backend/                          # Python sidecar（复用原 kazari_play）
│   ├── requirements.txt
│   ├── sidecar.spec                  # PyInstaller 打包脚本
│   ├── server.py                     # 本地 HTTP + WebSocket 服务（新写）
│   ├── fake_window.py                # 伪造 pywebview 窗口对象，代理 evaluate_js → WebSocket（新写）
│   └── kazari_play/                  # 从原项目拷贝（业务层，零改动）或通过路径引用
└── scripts/
    ├── build_sidecar.bat             # 打包 Python 后端为 exe
    └── dev.bat                       # 开发：先起 Python server，再 tauri dev
```

---

## 三、通信架构（核心设计）

原架构：
```
[HTML/CSS/JS] --pywebview.api.X()--> [Python WebBridge]
[Python UISync] --window.evaluate_js--> [HTML/CSS/JS]
```

新架构（只换传输层，不改协议/方法名/数据形状）：
```
[HTML/CSS/JS] --invoke('api',{method,args})--> [Tauri Rust 壳] --HTTP POST /api--> [Python server.py]
[Python server.py] --WebSocket push--> [HTML/CSS/JS]   （替代 evaluate_js 推送）
               ↑
        复用 WebBridge 全部业务方法（原名暴露）
```

**要点：**
- **请求通路**：JS → Rust `invoke('api', ...)` → HTTP → Python。Python 仍以「同名方法 + JSON 字符串参数」被调用，`server.py` 用反射把 WebBridge 方法按名字分发，业务层不改。
- **推送通路**：原来 UISync 调 `window.evaluate_js(cmd)`，改为 `fake_window.evaluate_js(cmd)` 内部经 WebSocket 发送 `{type:'eval', code:cmd}`，前端收到后 `eval` 执行（保持与 pywebview 一致的执行语义）。这样 `ui/sync.py` 等推送代码零改动。
- **端口**：Python 启动时绑定 `127.0.0.1` 随机空闲端口，把端口通过 stdout 或文件告知 Rust sidecar；避免写死占用冲突。
- **生命周期**：Rust 启动时拉起 sidecar 进程，窗口关闭时结束 sidecar + 退出 overlay.exe（对齐原 [main.py](../kazari_play/main.py) 的清理逻辑）。

---

## 四、改动清单

### 4.1 前端（改动极小，单点）
- 只改 **`core.js` 里的 bridge 代理**：
  - 原：`pywebview.api[method](...args)` 返回 Promise
  - 新：`invoke('api', {method, args})`（Tauri 前端 API `@tauri-apps/api`）或自定义 `window.__api(method, ...args)`
  - 建议抽成 `window.__api` 统一封装，其它 16 个 JS 模块无需改动。
- 其余 JS / CSS / partials：原样拷贝复用。
- **可删掉的兼容逻辑**：`main.py` 里为了绕开 pywebview 中文本路径 `file://` 问题而写的 `_load_html()` 内联注入（css/js/partial 拼接、@import 展开、data-uri icon）——Tauri 自带 asset 协议可静态加载，这段代码不需要了。

### 4.2 Python sidecar（新增少量代码）
- `server.py`：基于 `http.server` 或 `FastAPI` + `websockets`，提供：
  - `POST /api`：`{method, args[]}` → 反射调用 `WebBridge.<method>(*args)` → 返回 JSON。
  - `GET /health`：健康检查（Rust 等 sidecar 就绪）。
  - WebSocket：服务端 → 前端推送（eval）。
- `fake_window.py`：实现 `create_file_dialog`、`evaluate_js`、`minimize/maximize/resize` 等 pywebview 窗口接口的子集，供 WebBridge 调用，内部转 HTTP/WS。文件对话框可先对接 Rust 的 `dialog` 命令。
- 数据 / 配置 / 截图像目录：沿用 `%APPDATA%\KazariPlay`，**迁移零成本**（与前端数据兼容）。

### 4.3 Rust 壳（薄）
- 新建 `src-tauri`，`tauri init`+ 配置：
  - `frontendDist: "../src/web"`（无 bundler，静态目录直接服务）；
  - `frameless: true`、`resizable`、大小/位置对齐原 [main.py](../kazari_play/main.py#L250-L263)（0.82 屏幕宽、最小 900x620）。
- Rust 命令：
  - `spawn_backend`：拉起 Python sidecar 进程（开发期 `python server.py`；发布期跑打包的 exe）。
  - `api(method, args)`：HTTP 转发到 sidecar。
  - `kill_backend`：关闭 sidecar（窗口关闭时）。
- 托盘 / 开机自启 / 系统通知：后续增量加，不影响首版。

---

## 五、C++ overlay 与翻译的保留

- `overlay.exe`（x64 / x86）与 `texthook.dll` 原样使用，作为独立进程被启动。
- Python `OverlayClient` 的命名管道 IPC（`FILE_FLAG_OVERLAPPED` 重叠 I/O）**不必改**——sidecar 里 Python 自己连 overlay 管道，Rust 不参与。
- 因此**实时翻译 / 清洗 / 字幕 / 截图 toast 全部原样保留**。

---

## 六、前置条件与安装（执行前需满足）

| 项 | 状态 | 动作 |
|---|---|---|
| Node.js / npm | ✅ 已装 (v22.19.0 / 10.9.3) | — |
| Rust / Cargo / rustup | ❌ 未装 | `winget install Rustlang.Rustup`，重启终端，`rustc -V` 验证 |
| MSVC Build Tools (含 C++) | ✅ 已装 (14.44) | Tauri 需其链接器 |
| WebView2 Runtime | ✅ 已装 | — |
| @tauri-apps/cli | 待 | 在 KazariPlay_V2.0 内 `pnpm/npm add -D @tauri-apps/cli` |

---

## 七、分阶段落地路线

1. **阶段 0（环境）**：装 Rust；建 KazariPlay_V2.0 骨架；`tauri init` 通。
2. **阶段 1（最小可用 MVP）**：
   - 拷贝前端，改 `core.js` 桥代理单点；
   - 写 `server.py` + `fake_window.py`，Python 源码模式跑通；
   - Rust `api` 转发打通 → 能显示游戏库并增删改查。
3. **阶段 2（补齐交互）**：窗口缩放 / 拖拽 / 最小化 / 最大化在 Rust 层落地；文件对话框对接。
4. **阶段 3（原生活体验）**：托盘、开机自启、系统通知。
5. **阶段 4（打包分发）**：PyInstaller 打 sidecar → Tauri sidecar 打包 → Windows 安装包（x64 / 便携版）。

---

## 八、风险与待决策

- **Rust 是新增维护面**：即使只写薄壳，仍需懂最小 Rust 与 Tauri API 才能维护。备选：把壳进一步抽象成「只转发，不含业务」。
- **推送通道从 evaluate_js 换 WebSocket**：需验证前端 `eval` 语义与原 `evaluate_js` 完全一致（作用域/返回值/异步）。首版先以最朴素 `eval` 实现，跑通后再优化。
- **文件对话框**：`create_file_dialog`（scanFolder / selectExe / pickCover 等多处）需从 pywebview API 迁到 Tauri/Rust 命令，属集中改动点。
- **进程生命周期**：sidecar 崩溃/退出需有重拉机制；overlay 管道连接时序（OverlayClient 单例）需在 sidecar 内保持一致。
- **是否保留 pywebview 分支**：V2.0 与 V1.0 并行，建议 V2.0 验证稳定前保留 V1.0 可运行。

**待确认**：
- KazariPlay_V2.0 前端是否直接拷贝（独立副本）还是用符号链接/共享路径引用 V1.0？默认建议**独立拷贝**，避免两边互相影响。
- Python 后端用「拷贝进 backend/」还是「运行时引用原项目路径」？默认建议 **PyInstaller 阶段拷贝**，开发期用引用路径。
