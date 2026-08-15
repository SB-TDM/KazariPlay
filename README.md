# KazariPlay V1.02

视觉小说（Galgame）本地库启动器 · **pywebview（系统 WebView）渲染 HTML UI**

原名 Minato Launcher，V1.0 起正式更名为 **KazariPlay**。V1.01 引入**收藏夹文件夹系统**；V1.02 引入**游戏内截图提示（C++ Overlay）**与 Steam 式截图管理；V1.1 引入 **Hook 实时翻译（实验性）**。

## 特性

- **Hook 实时翻译（V1.1 新增，⚠️ 实验性）**：Hook 提取游戏对话文本（基于 Textractor，支持 KRKR/Ren'Py/Unity/RPGMaker 等）+ C++ 内部 AI 翻译（OpenAI 兼容 API，默认 DeepSeek），字幕先显示原文、AI 翻译完成后替换为译文；含过滤器链文本清洗（去重/注音/标签/乱码）、每游戏独立清洗配置、字幕窗口跟随游戏窗口、实时翻译开关联动
  > ⚠️ **实验性功能，使用隐患**：Hook 兼容性依游戏与 Hook 点而异，可能出现文本抓取不完整/错乱；AI 翻译质量不保证、可能误译人名与专有名词；实时翻译会调用第三方 AI API（如 DeepSeek）并产生实际费用；文本清洗过滤器可能误伤正常字幕（默认保守策略，激进过滤器需手动开启）。请在理解这些风险后使用。
- **Kawaii Minimal 视觉**：UI 为 HTML/CSS（`kazari_play/ui/web_assets/`），由 pywebview + 系统 Edge WebView2 渲染，与设计稿一致
- **游戏内截图提示（V1.02 新增）**：F12 截图后在**游戏画面右下角**弹出 Steam 式 toast（缩略图 + 游戏名，从底部上滑），由独立 C++ 进程 `overlay.exe` 渲染（Direct2D + DirectWrite），仅作用于游戏窗口，与主程序经命名管道通信
- **Steam 式截图管理**：详情页截图卡片左键放大预览、右键菜单（重命名 / 定位到文件 / 复制到剪贴板 / 删除），预览窗口带加载动画
- **收藏夹系统（V1.01 新增）**：树形分组→分类、游戏多对多归类、手风琴侧边栏、拖拽排序、管理游戏对话框
- **游戏库主界面**：自适应卡片网格、星级评分、收藏角标、真实封面（base64 内联）
- **详情底部抽屉（Modal Bottom Sheet）**：点击卡片底部上拉，信息栏 3 列、收藏夹路径 chips、简介
- **批量选择模式**：卡片圆形勾选框 + 批量工具栏（全选/批量加入收藏夹/批量移除/从库移除）
- **设置窗口**：居中模态，常规/主题（即时预览）/快捷键/伪装/关于
- 搜索 / 排序 / 收藏 / 继续游玩 导航、无边框窗口 + HTML 标题栏拖拽
- 启动游戏、游玩时长统计、VNDB/Bangumi 元数据匹配与多源搜索
- 前后端经 **pywebview js_api**（`kazari_play/ui/web_bridge.py`）桥接

## 前置要求

- Python 3.8+
- **Microsoft Edge WebView2 Runtime**（Windows 10/11 一般已内置；缺失时用 winget 安装）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 运行

```bash
pip install -r requirements.txt
python kazari_play/main.py     # 在 KazariPlay_V1.0 目录下
```

## 构建 C++ Overlay（可选）

游戏内截图提示由独立进程 `overlay/bin/overlay.exe` 提供，首次运行前需编译（需要 MSVC Build Tools，含 C++ 工作负载）：

```bat
cd overlay
build.bat        # 产物：overlay/bin/overlay.exe
```

overlay.exe 缺失或编译失败时，截图提示自动降级（不影响截图主功能）。

## 目录结构

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview 入口（无边框窗口 + js_api；html/js/css 启动时内联）
│   ├── core/                  # 后端核心（扫描/启动/监控/截图/元数据/多源搜索/overlay 客户端）
│   ├── database/              # 数据层（游戏库 + 收藏夹关联表）
│   ├── utils/                 # 工具（配置/日志/路径/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api 桥（后端能力暴露给前端）
│   │   ├── sync.py            # 界面更新总线（数据变化 → 前端刷新的统一推送/合并）
│   │   └── web_assets/        # 前端源码（详见 web_assets/README.md）
│   │       ├── index.html     # 应用壳（侧边栏/主区/窗口手柄 + PARTIALS/SCRIPTS 占位符）
│   │       ├── css/style.css
│   │       ├── js/            # 12 个 JS 模块，按依赖顺序由 main.py 内联（_JS_MANIFEST）
│   │       └── partials/      # 各窗口/对话框分块 HTML（_PARTIAL_MANIFEST）
│   └── resources/
├── overlay/                   # C++ 游戏内截图 overlay（Direct2D + 命名管道 IPC）
│   ├── src/                   # main / toast_window / pipe_server / protocol
│   ├── third_party/           # nlohmann/json 单头文件
│   ├── build.bat              # MSVC 编译脚本
│   └── bin/overlay.exe        # 编译产物（git 忽略）
├── screenshots/               # 截图存放（按游戏分文件夹，git 忽略）
└── tests/
```

## 数据

- 数据库：`%APPDATA%\KazariPlay\games.db`
- 配置：`%APPDATA%\KazariPlay\config.json`（默认浅色 Kawaii 主题）
- 截图：`KazariPlay_V1.0/screenshots/{game_id}/`
- 从旧版 Minato Launcher 升级时，`%APPDATA%\MinatoLauncher` 下已有的数据会自动迁移
