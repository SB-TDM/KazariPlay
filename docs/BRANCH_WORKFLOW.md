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

## 远端边界

本轮只创建本地分支和提交，远端仍是原来的 `master`。没有推送、切换 GitHub 默认分支、删除旧远端分支或创建标签/Release。

后续需单独确认：推送三条分支、将 GitHub 默认分支设为 `main`，再决定是否删除旧 `master`。保护规则/Rulesets、编译期开关、正式 Release 保持待定，不能作为本地分离的附带操作执行。

## 当前实施与验证

含翻译源码基线保存为 `df48607`，实验分支源代码保持该版本。原版是其后的移除提交，历史和旧标签不重写。待办中的公共功能缺陷仍未修复，版本分离不等于正式 Release 就绪。

已通过：TypeScript 检查与构建、Python 语法、前端组装、扫描、多源、缓存、缩略图、UI Sync、收藏夹迁移，以及 4 项无翻译边界/兼容测试；MSVC x64/x86 截图 Overlay 均编译成功。

源码 GUI 已通过隔离冒烟：启动、设置页、详情与截图区、重新定位入口和无翻译 API 边界。x64/x86 toast 均通过真实测试窗口、像素、show/hide/quit 验证；CMake x64/x86 构建也已通过。

截图服务回归通过原图与缩略图保存、列表、重命名、删除和路径边界，本轮 WGC 探测实际取得 2560x1440 帧。未验证真实游戏 Hook、付费 API、独占全屏和多显示器；普通窗口采集成功不等于独占全屏已实测。
