# KazariPlay V1.4.0 Beta 1 原版

本版本用于 `main` / `develop`，基于 V1.3 的无翻译原版进入 `V1.4.0 Beta 1` 验收阶段，保留游戏库、扫描、重新定位、元数据与截图功能，不包含翻译前后端、Hook 注入或字幕。翻译实验版保留在 `feature/hook-translation`，分支和工作区使用见 [开发流程](docs/BRANCH_WORKFLOW.md)。

当前本地 `develop` 版本号为 `1.4.0-beta.1`；稳定 `main` 尚未接收本轮开发提交，未创建新标签或 Release。编号与版本来源见 [版本策略](docs/VERSIONING.md)。

视觉小说（Galgame）本地库启动器 · **pywebview（系统 WebView）渲染 HTML UI**

原名 Minato Launcher，V1.0 起正式更名为 **KazariPlay**。当前原版以 `V1.4.0 Beta 1` 作为本地验收版本，保留 V1.3 的前端 TypeScript、WGC 三级截图回退、扫描去重与进度取消，以及批量重新定位，不回退到旧版源码。

## 特性

- **Kawaii Minimal 视觉**：UI 为 HTML/CSS/TypeScript（源 `kazari_play/ui/web_assets/ts/`，tsc 编译到 `js/`），由 pywebview + 系统 Edge WebView2 渲染，与设计稿一致
- **游戏内截图提示（V1.02 新增）**：F12 截图后在**游戏画面右下角**弹出 Steam 式 toast（缩略图 + 游戏名，从底部上滑），由独立 C++ 进程 `overlay.exe` 渲染（Direct2D + DirectWrite），仅作用于游戏窗口，与主程序经命名管道通信
- **截图内核（三级回退）**：WGC（Windows Graphics Capture，兼容 D3D/Vulkan 独占渲染）→ PrintWindow（GDI）→ 全屏兜底；每次截图保存**原图 + 统一尺寸缩略图**（等比留边、随原图存放），删除/重命名联动
- **Steam 式截图管理**：详情页截图卡片左键**全屏预览原图**、右键菜单（重命名 / 定位到文件 / 复制到剪贴板 / 删除），缩略图懒加载
- **收藏夹系统（V1.01 新增）**：树形分组→分类、游戏多对多归类、手风琴侧边栏、拖拽排序、管理游戏对话框
- **游戏库主界面**：自适应卡片网格、星级评分、收藏角标、真实封面（base64 内联）
- **详情底部抽屉（Modal Bottom Sheet）**：点击卡片底部上拉，信息栏 3 列、收藏夹路径 chips、简介
- **批量选择模式**：卡片圆形勾选框 + 批量工具栏（全选/批量加入收藏夹/批量移除/从库移除）
- **批量重新定位**：按游戏身份匹配目标目录，预览确认后更新路径，保留游戏 ID、收藏夹和截图归属
- **设置窗口**：居中模态，常规/主题（即时预览）/快捷键/伪装/关于
- 搜索 / 排序 / 收藏 / 继续游玩 导航、无边框窗口 + HTML 标题栏拖拽
- 启动游戏、游玩时长统计、VNDB/Bangumi 元数据匹配与多源搜索
- 前后端经 **pywebview js_api**（`kazari_play/ui/web_bridge.py`）桥接

## 前置要求

- Windows 10/11，Python 3.11（当前验证环境）
- Node.js / npm：首次运行前需构建前端
- **Microsoft Edge WebView2 Runtime**（Windows 10/11 一般已内置；缺失时用 winget 安装）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 运行

```bash
pip install -r requirements.txt
npm --prefix kazari_play/ui/web_assets ci
npm --prefix kazari_play/ui/web_assets run build
python kazari_play/main.py     # 在对应工作区根目录下
```

## 构建 C++ Overlay（可选）

游戏内截图提示由独立进程 `overlay/bin/overlay.exe` 提供，首次运行前需编译（需要 MSVC Build Tools，含 C++ 工作负载）：

```bat
cd overlay
build.bat        # 产物：overlay/bin/overlay.exe
```

overlay.exe 缺失或编译失败时，截图提示自动降级（不影响截图主功能）。

原版 Overlay 只提供截图 toast，不链接 Textractor，无需 `hostlib.lib` 或 `texthook.dll`。x86 可使用 `overlay/build32.bat`；源码、DLL 和编译产物不可与实验工作区混用。

## 目录结构

```
KazariPlay_main/
├── kazari_play/
│   ├── main.py                # pywebview 入口（无边框窗口 + js_api；html/js/css 启动时内联）
│   ├── core/                  # 后端核心（扫描/启动/监控/截图/元数据/多源搜索/overlay 客户端）
│   ├── database/              # 数据层（游戏库 + 收藏夹关联表）
│   ├── utils/                 # 工具（配置/日志/路径/VNDB/Bangumi/标题归一化）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api 桥（后端能力暴露给前端）
│   │   ├── sync.py            # 界面更新总线（数据变化 → 前端刷新的统一推送/合并）
│   │   └── web_assets/        # 前端源码（详见 web_assets/README.md）
│   │       ├── index.html     # 应用壳（侧边栏/主区/窗口手柄 + PARTIALS/SCRIPTS 占位符）
│   │       ├── css/style.css
│   │       ├── ts/            # TypeScript 源（原版 14 个模块）
│   │       ├── js/            # tsc 编译产物（由 ts/ 生成，gitignore；main.py 按 _JS_MANIFEST 内联）
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
- 截图：当前工作区 `screenshots/{game_id}/`
- 从旧版 Minato Launcher 升级时，`%APPDATA%\MinatoLauncher` 下已有的数据会自动迁移

旧实验版数据库中的 Hook/翻译列和配置中的翻译数据保留作兼容；原版不启动这些能力，也不会将翻译配置传给前端。恢复默认设置仍保留旧翻译配置。两版本不要同时写同一数据库，切换前先备份；截图保留在各工作区自己的目录，不自动搬迁。

## 文档

- [文档索引](docs/README.md)：区分当前有效文档、历史记录和未实施方案
- [分支开发流程](docs/BRANCH_WORKFLOW.md)：原版与实验版的边界、公共修复同步和远端待办
- [工作约束](docs/DEV_RULES.md)：修改代码、打包、提交前必读
- [变更日志](docs/CHANGELOG.md)：开发改动与验证记录
- [第三方组件声明](THIRD_PARTY.md)：依赖和许可证说明

## 开源许可

本项目以 **GNU General Public License v3.0（GPL-3.0）** 授权，详见 [LICENSE](LICENSE)。

- 原版 Overlay 不链接 Textractor；项目继续使用既有 GPL-3.0 许可，源码与构建脚本随项目提供。
- 第三方组件（pywebview / Pillow / keyboard / pywin32 / numpy / nlohmann-json 等）的使用与许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。
- 完整源码：https://github.com/SB-TDM/KazariPlay
