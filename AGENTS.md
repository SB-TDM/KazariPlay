# AGENTS.md — KazariPlay

## 项目定位

视觉小说（Galgame）本地库启动器：扫描/管理本地游戏、Hook 实时翻译、VNDB/Bangumi 元数据匹配。
Python + pywebview（系统 Edge WebView2）渲染 HTML UI；独立 C++ overlay 负责游戏内截图提示与字幕。

## 怎么跑

```bash
pip install -r requirements.txt
python kazari_play/main.py        # 在 KazariPlay_V1.0 目录下运行
```

前端改动（改 `ts/` 后必须编译）：

```bash
cd kazari_play/ui/web_assets
npm run build                     # tsc: ts/ -> js/（js/ 为编译产物，gitignore）
npm run typecheck                 # 只做类型检查
```

C++ overlay（可选，需 MSVC Build Tools，含 C++ 工作负载）：

```bat
cd overlay
build.bat          # x64 -> bin/overlay.exe
build32.bat        # x86 -> bin32/overlay.exe
```

验证门禁：

```bash
python tests/verify_frontend.py   # 前端 script 块数 / HTML id 交叉校验
python tests/test_scanner.py      # 扫描器单测
python tests/smoke_screenshots.py # 截图冒烟（需显示环境）
```

## 技术栈

- **前端**：TypeScript（`ts/` 源）→ tsc 编译为经典脚本（`js/` 产物）；`main.py` 按 `_JS_MANIFEST` 内联进单个 HTML
- **后端**：Python 3.11（pywebview 6 / SQLite / Pillow / windows-capture / pywin32 / keyboard）
- **Overlay**：C++（Direct2D + DirectWrite + Textractor），命名管道 IPC

## 目录与约定

- `kazari_play/core|database|ui|utils`：后端；`ui/web_bridge.py` = js_api 桥，`ui/sync.py` = UISync 刷新总线
- `kazari_play/ui/web_assets/`：`ts/` = TypeScript 源（唯一真相），`js/` = 编译产物（勿手改），`css/`、`partials/`、`index.html`
- 新增前端模块：`ts/` 建文件 → 登记 `main.py` 的 `_JS_MANIFEST`（顺序即依赖顺序，两处同步）
- `overlay/`：C++ 注入层；`tests/`：`smoke_*` / `test_*` / `verify_frontend.py`
- 文档：`README.md`（怎么用）、`docs/CHANGELOG.md`（改动历史）、`docs/*_PLAN.md`（设计/迁移方案）

## 当前状态与下一步

- 最新改动见 `docs/CHANGELOG.md`（2026-09 开发批次 + 2026-10 扫描去重与体验）
- 前端已全量 TypeScript 迁移；截图内核 WGC 三级回退 + 双保存；扫描支持多选/进度/取消/跨文件夹去重
- 游戏身份键 `identity = 引擎 | 归一化文件夹名`（`utils/title_utils.py`）：扫描按 `exe 路径` + `identity` 双重判重；改判重或标题归一化时两处需同步
- 当前版本 V1.3（前端 TS 迁移 / 截图内核 WGC / 扫描去重与体验）
