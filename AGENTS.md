# AGENTS.md — KazariPlay

## 项目定位

`main` / `develop` 为无翻译原版：扫描/管理本地游戏、VNDB/Bangumi 元数据匹配、批量重新定位与截图。
Python + pywebview 渲染 HTML UI；独立 C++ overlay 仅提供截图 toast。翻译实验实现保留在 `feature/hook-translation`。

## 怎么跑

```bash
pip install -r requirements.txt
npm --prefix kazari_play/ui/web_assets ci
npm --prefix kazari_play/ui/web_assets run build
python kazari_play/main.py        # 在对应工作区根目录运行
# develop 自测包（新目录；不写入现有用户数据，不对外发布）
python scripts/package_develop.py --output trial-build-1.1.0-beta.7
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
python tests/test_classic_boundary.py # 无翻译边界与旧数据兼容
python tests/smoke_overlay.py     # 原版截图 toast（需先编译 overlay）
```

## 技术栈

- **前端**：TypeScript（`ts/` 源）→ tsc 编译为经典脚本（`js/` 产物）；`main.py` 按 `_JS_MANIFEST` 内联进单个 HTML
- **后端**：Python 3.11（pywebview 6 / SQLite / Pillow / windows-capture / pywin32 / keyboard）
- **Overlay**：C++（Direct2D + DirectWrite），命名管道 IPC，无 Textractor 依赖

## 目录与约定

- `kazari_play/core|database|ui|utils`：后端；`ui/web_bridge.py` = js_api 桥，`ui/sync.py` = UISync 刷新总线
- `kazari_play/ui/web_assets/`：`ts/` = TypeScript 源（唯一真相），`js/` = 编译产物（勿手改），`css/`、`partials/`、`index.html`
- 新增前端模块：`ts/` 建文件 → 登记 `main.py` 的 `_JS_MANIFEST`（顺序即依赖顺序，两处同步）
- `overlay/`：截图 toast 源码；`tests/`：原版回归与边界检查
- 文档：`README.md`（怎么用）、`docs/README.md`（文档索引）、`docs/dev/DEV_RULES.md`（**工作约束，改代码/打包/提交前必读**）、`docs/dev/CHANGELOG.md`（改动历史）；`docs/` 按 `dev/`（流程与记录）、`ui/`（界面线）、`archive/`（历史）、`plans/`（未实施方案）归类
- 架构文档（改代码前先看；按板块拆分）：`docs/ARCHITECTURE.md`（总体架构/数据流/核心对象）、`docs/backend/`（core/database/ui/utils 逐模块）、`docs/frontend/`（ts 模块与构建/内联约定）、`docs/overlay.md`（C++ overlay 与管道协议）、`docs/dev/testing.md`（测试分类与改动验证）

## 当前状态与下一步

- 最新改动见 `docs/dev/CHANGELOG.md`；P0/P1/P2 本地修复与未验收项以 `docs/dev/DEVELOPMENT_BACKLOG.md` 为准
- 前端已全量 TypeScript 迁移；截图内核 WGC 三级回退 + 双保存；扫描支持多选/进度/取消/跨文件夹去重
- 游戏身份键 `identity = 引擎 | 归一化文件夹名`（`utils/title_utils.py` 的 `for_identity=True`）：与搜索清洗分开，扫描按 `exe 路径` + `identity` 判重；修改时同步旧游戏 identity 回填
- 当前开发线自测版 `1.1.0-beta.7`（当前正式版 `1.0.1`；核心号随 `main` 发布定稿）；版本规则与历史映射见 `docs/dev/VERSIONING.md`，历史版本见 `RELEASE_NOTES.md`
- 元数据自动匹配（1.1.0 线）：VNDB/Bangumi/月幕多源并行 + 跨源一致性校验；中文标题/简介优先，`bangumi_id` 自动迁移；批量入口 force=True（用户评分不覆盖）。
- 封面（1.1.0 线）：`covers/{id}.{ext}` + `thumbs/{id}_w512.jpg` 单文件模型；本地 HTTP 服务（127.0.0.1、持久 token/端口、immutable），失败回退 base64；启动迁移旧变体与清理。
- 更新器（1.0.x）：通道切换 + 就绪缓存（启动本地探测自动提示，确认期间跳过）+ 硬链接程序备份 + 分阶段埋点；应用方式仅「立即重启更新」；设计见 `docs/dev/AUTO_UPDATE_SPEEDUP_PLAN.md`
- `scripts/package_develop.py` 生成隔离的 onedir 试用包，运行时数据在包旁 `data/`；不覆盖现有构建目录，打包前需先完成 Overlay x64/x86 构建。
- 主界面重构、主页、评分半星制已并入 `develop` 并推送 GitHub（`154ea63`）；本目录 `KazariPlay_main-ui` 为独立克隆（`origin`=本机 `KazariPlay_main`，`github`=SB-TDM/KazariPlay）。
- 分支职责见 `docs/dev/BRANCH_WORKFLOW.md`；不将实验分支整分支合入原版，不混用两版生成物，不删除用户数据或旧实验字段。
