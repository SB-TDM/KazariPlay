# 原版与翻译实验版开发流程

> 2026-10-05，已确认的本地分支方案。分支保护、构建开关、正式发布仍待定。

## 分支职责

| 分支 | 内容 | 集成规则 |
|---|---|---|
| `main` | 基于当前 V1.3 的无翻译原版稳定基线 | 接收 `develop` 验收通过的变更 |
| `develop` | 无翻译原版日常集成 | 功能/修复工作分支以它为基线 |
| `feature/hook-translation` | 保存当前含翻译前后端、Hook、字幕的实验版 | 独立开发，只选择性同步公共修复 |

名称中的 `feature/` 不表示必须整分支合并：此分支是长期实验产品线，不整体合入原版。稳定主线的身份是无翻译版，不恢复到 `4c10c12` 历史源码。

## 工作区

本地使用一个 Git 仓库的两个 worktree：

- `KazariPlay_main/`：无翻译原版，`develop` 日常开发。
- `KazariPlay_V1.0/`：翻译实验版，`feature/hook-translation`。

两个工作区共享提交历史，不共享前端 `node_modules/js` 或 `overlay/bin/bin32`。切换/构建前用 `git status --short --branch` 核对身份。不要把实验目录的 EXE/DLL 拷贝进原版，以免旧生成物重新带回翻译能力。

## 无翻译边界

原版保留扫描、游戏库、启动/进程追踪、计时、收藏夹、元数据、多源、批量重新定位、WGC 截图与截图 toast。

原版移除翻译 UI、js_api、会话协调、Hook 注入、AI 请求、字幕和清洗过滤器，以及 Textractor 头文件、静态库、DLL 的源码/构建清单。截图 Overlay 保留 `main`、`ToastWindow`、管道与 JSON 协议，x64/x86 构建只链接 Windows 图形系统库。

## 数据兼容

两版沿用旧数据库结构。原版保留旧 Hook/翻译字段作为不执行的兼容数据，常规更新不覆盖这些列；旧配置中的翻译数据保留在磁盘，不由原版前端读取。恢复默认设置也保留旧翻译配置。

测试和并行开发应使用数据库副本与隔离配置。两版不能同时写真实 `%APPDATA%/KazariPlay`；截图按各工作区目录保存，现有截图不自动迁移。旧实验工作区的截图、DLL、EXE、OBJ 和配置保持原位置。

## 日常开发与同步

1. 原版任务从 `develop` 创建短期 `fix/*` 或 `feature/*` 分支。
2. 提交只包含当前任务文件，运行相应测试与原版边界检查。
3. 验收后合入 `develop`；版本稳定后合入 `main`。
4. 两版共用的修复单独提交，经审查后选择性 cherry-pick 到实验分支；冲突时逐处适配。
5. 不将原版分离提交合入实验分支，不将实验分支整分支合入 `main/develop`，不对共享历史反复 rebase。

## 本地构建

从各自工作区根目录执行：

```powershell
pip install -r requirements.txt
npm --prefix kazari_play/ui/web_assets ci
npm --prefix kazari_play/ui/web_assets run typecheck
npm --prefix kazari_play/ui/web_assets run build
python tests/verify_frontend.py
python tests/test_classic_boundary.py
python tests/smoke_overlay.py
```

最后两项为原版专用；`smoke_overlay.py` 需先在 `overlay/` 用 `build.bat`/`build32.bat` 构建。实验版继续用自身的翻译测试，测试前隔离本机 API 配置，不调用付费接口进行普通回归。

`build.bat` 与 `build32.bat` 共用当前目录的 OBJ，必须顺序运行；需要并行时分别指定独立中间产物目录。

P1 回归从对应工作区根目录运行：

```powershell
python -B tests/test_p1_reliability.py
node tests/test_p1_frontend.cjs
python -B tests/test_overlay_lifecycle.py
python -B tests/smoke_screenshots.py
```

前端回归需先构建 JS，真实管道回归需对应版本的 x64/x86 EXE。实验字幕另运行 `node tests/test_ai_worker.cjs`（MSVC，受控替身，无网络）；`tests/subtitle_revision.cpp` 与 `tests/pipe_lifecycle.cpp` 可用 MSVC 编译验证。

## 远端边界

2026-10-05 已推送 `main`、`develop`、`feature/hook-translation`，本地分支分别跟踪同名远端分支。原版分离代码已在 `main/develop`，翻译实验版已在对应远端分支。

GitHub 默认分支仍为 `master`：本机 `gh` 未登录，修改仓库设置被认证阻塞，用户明确选择暂缓切换。旧 `master` 保留，不自动删除；在默认分支调整前访问 GitHub 首页仍看到旧版，应主动选择对应版本分支。

后续先完成 GitHub CLI 授权，再切换默认分支到 `main`，最后单独决定旧 `master` 是否删除。保护规则/Rulesets、编译期开关、正式 Release 保持待定，本轮均未操作；Git SSH 推送权限不等于仓库设置 API 权限。

## 当前实施与验证

含翻译初始基线保存为 `df48607`，历史和旧标签不重写。2026-10-05 公共 P0/P1 已集成到本地 `develop`，选择性同步实验分支；实验另有 Hook PID 和字幕异步专属修复。代码提交映射与详细结果以 [开发待办](DEVELOPMENT_BACKLOG.md) 为准。

本轮未推送：本地 `main` 与 `origin/main`、`origin/develop` 仍为 `d0232a6`，`origin/feature/hook-translation` 为 `5aed7bc`；这些是本地跟踪引用记录，不表示 P0/P1 已发布。`fix/p1-reliability` 和两个 worktree 保留。

已通过：TypeScript 检查与构建、Python 语法、前端组装、扫描、多源、缓存、缩略图、UI Sync、收藏夹迁移，以及 4 项无翻译边界/兼容测试；MSVC x64/x86 截图 Overlay 均编译成功。

源码 GUI 已通过隔离冒烟：启动、设置页、详情与截图区、重新定位入口和无翻译 API 边界。x64/x86 toast 均通过真实测试窗口、像素、show/hide/quit 验证；CMake x64/x86 构建也已通过。

截图服务回归通过原图与缩略图保存、列表、重命名、删除和路径边界，本轮 WGC 探测实际取得 2560x1440 帧。未验证真实游戏 Hook、付费 API、独占全屏和多显示器；普通窗口采集成功不等于独占全屏已实测。

P0 增量验证：9 项写入/取消测试、10 项进程测试、前端字符串 ID/新增协议/失败状态探针，以及两版源码 UI 新增/编辑/删除通过。实验 Hook 目标、位数与取消的 5 项接线回归和离线翻译冒烟已通过；真实 Textractor 注入未验证。

P1 增量验证：两版 18 项数据/任务回归、Node 截图/进度隔离和源码 GUI 重新定位/同名截图通过；原版 x64/x86 toast、真实管道重连/架构切换/句柄计数和 C++ 挂起 I/O 停止通过。实验在临时目录完整构建 x64/x86，序号和真实 worker 的阻塞结果测试、临时 EXE 生命周期通过；原有实验 `bin/bin32` 未覆盖，普通启动不会自动使用临时产物。仍需真实游戏、AI 服务、独占全屏及多显示器验收。

2026-10-06 实验专属 P2 已本地完成，原版仅同步记录，详情见 [开发待办](DEVELOPMENT_BACKLOG.md)。实验 x64/x86 真实请求受控替身与日志隐私回归通过，随后默认运行目录启用为 `overlay/runtime/x64|x86`，bat/CMake 双架构构建、源码 GUI HTTPS 拒绝、toast/字幕预览像素和正常退出通过；字幕 COM 重复释放修复及计数回归通过。旧 EXE/DLL/OBJ 保留，显式 exe_path 仍优先；原版构建与路径不改变。P0/P1/P2 和启用提交尚未推送，稳定 `main` 未更新；真实游戏/TLS/AI 服务及实际打包仍未验收。
