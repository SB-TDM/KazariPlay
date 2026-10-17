# KazariPlay 文档索引

> 文档状态：2026-10-13 版本号体系重新定义（`0.x` = 初代世代、`1.0.0` = 新界面世代，当前正式版 `1.0.1`、开发线自测 `1.1.0-beta.5`，见 [版本策略](dev/VERSIONING.md) 与 [ADR-0001](adr/0001-version-renumbering.md)）；文档目录已按 `dev/`、`ui/`、`archive/`、`plans/` 归类（本页同步重构）。主体状态沿用 2026-10-11 记录：主界面重构（含 FR-01～FR-12 修复与复评整改 R1–R16）、主页、评分半星制已并入 `develop` 并推送 GitHub（`154ea63`）；源码 GUI/DPI 验收待补；试用三项反馈已修复（`36c17dc` 批次），待新自测包复验。2026-10-14：自动更新代码审查（UPD-REV-01～13）完成修复，纳入离线回归、冻结包受控演练与真实 GitHub 测试 Release 链路演练（含 fail-closed 拒绝）；更新提速与就绪复用已随 `1.0.0` 正式发布（真实链路复测通过；重启自动提示、硬链接备份、首启探测竞态修复均已纳入）；`1.0.1` 为应用内更新实证版本（2026-10-17 已实证通过）；2026-10-17：元数据自动匹配改为多源一致性校验（VNDB/Bangumi/月幕、中文优先、年份重制版、force 覆盖非空元数据且保留用户评分），新增 `bangumi_id`，见 [审查报告](dev/AUTO_UPDATE_CODE_REVIEW_20261014.md) 与 [提速计划](dev/AUTO_UPDATE_SPEEDUP_PLAN.md)。
>
> 目录约定：`dev/` 工程流程与记录 · `ui/` 界面线 · `backend/`、`frontend/` 架构模块 · `plans/` 未实施方案 · `archive/` 历史记录。
>
> 本页区分当前有效文档、历史记录和未实施方案。当前代码与运行行为以代码、测试结果和“当前有效”文档为准。

## 顶层入口

| 文档 | 用途 |
|---|---|
| [README.md](../README.md) | 用户安装、运行、功能和当前版本说明；当前版本以 `kazari_play/version.py` 为准 |
| [AGENTS.md](../AGENTS.md) | Agent/协作者工作入口、目录约定和验证命令 |
| [GLOSSARY.md](../GLOSSARY.md) | 领域术语表（世代 / 核心号 / 预发布标识 / 自测包 / 正式发布等） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 总体架构：分层、核心对象、主要数据流、生命周期、前端内联机制 |
| [adr/](adr/) | 架构决策记录（ADR），当前：[0001 版本号重新定义](adr/0001-version-renumbering.md) |
| [overlay.md](overlay.md) | C++ overlay：管道协议、分层窗口、动画与 Python 对接 |
| [RELEASE_NOTES.md](../RELEASE_NOTES.md) | 面向用户的版本发行说明 |
| [THIRD_PARTY.md](../THIRD_PARTY.md) | 第三方组件和许可证说明 |

## dev/ — 工程流程与记录

| 文档 | 用途 |
|---|---|
| [DEV_RULES.md](dev/DEV_RULES.md) | 改代码、打包、提交和用户数据保护约束 |
| [BRANCH_WORKFLOW.md](dev/BRANCH_WORKFLOW.md) | 原版 main/develop 与翻译实验分支的开发、构建和同步规则 |
| [VERSIONING.md](dev/VERSIONING.md) | 版本编号体系（世代 / 核心号 / 自测包 / 正式发布）、唯一版本来源与历史编号映射 |
| [PACKAGING.md](dev/PACKAGING.md) | develop 文件夹自测包的构建、隔离数据、冻结验收与合并边界 |
| [AUTO_UPDATE_DESIGN.md](dev/AUTO_UPDATE_DESIGN.md) | 应用内自动更新设计 v0.7（GitHub API 更新源、数据保护最高原则、镜像回退、健康检查、平台接缝、实施计划）；已实施，E2 真实更新演练待首次正式发布后执行 |
| [AUTO_UPDATE_CODE_REVIEW_20261014.md](dev/AUTO_UPDATE_CODE_REVIEW_20261014.md) | 自动更新代码审查（13 项问题，UPD-REV-01～13）；2026-10-14 已修复并纳入离线回归，真实发布资产与冻结包全流程仍待验收 |
| [AUTO_UPDATE_SPEEDUP_PLAN.md](dev/AUTO_UPDATE_SPEEDUP_PLAN.md) | 更新提速与就绪复用实施计划（设计定稿待实施）：通道切换、就绪缓存、埋点、快速退出与真实链路验收演练 |
| [testing.md](dev/testing.md) | 测试分类、运行方式与改动验证建议 |
| [CHANGELOG.md](dev/CHANGELOG.md) | 按时间记录实际开发改动和验证记录 |
| [DEVELOPMENT_BACKLOG.md](dev/DEVELOPMENT_BACKLOG.md) | 代码审查问题、修复优先级、已确认分支方向和待定仓库事项 |

## ui/ — 界面线

| 文档 | 用途 |
|---|---|
| [MAIN_UI_REDESIGN_PLAN.md](ui/MAIN_UI_REDESIGN_PLAN.md) | 主界面设计与保护约束；主界面代码已实施，完整验收未完成；后续确认和修复状态以当前修复台账为准 |
| [MAIN_UI_HOME_DESIGN.md](ui/MAIN_UI_HOME_DESIGN.md) | 主页设计稿 v0.3：个人化聚合仪表盘（问候/继续游玩/统计/收藏夹快捷/空库引导）；已实施并随 `develop` 推送（`154ea63`，含复评整改 R1–R16），待最终实机验收 |
| [FRONTEND_REVIEW_REPAIR_PLAN_20261011.md](ui/FRONTEND_REVIEW_REPAIR_PLAN_20261011.md) | 主界面特性分支前端修复统一台账：`b5c8b8d` 基线、FR-01～FR-12 复现/根因/验收、原版对照、结构评价与分阶段建议；修复批次 `85e895a` 已实施并随 `develop` 推送（`154ea63`），离线回归通过，待源码 GUI/DPI 验收 |
| [WEBVIEW2_OPTIMIZATION.md](ui/WEBVIEW2_OPTIMIZATION.md) | WebView2 参数决策、性能基线和后续优化原则 |

## 架构与模块

面向开发者的代码结构说明（与 `main`/`develop` 原版对应）：

| 文档 | 用途 |
|---|---|
| [backend/README.md](backend/README.md) | 后端总览与模块地图（core/database/ui/utils） |
| [backend/core.md](backend/core.md) | core 九模块逐一：对象、方法、关键逻辑与依赖 |
| [backend/database.md](backend/database.md) | DB schema、迁移机制与三个 repository |
| [backend/ui-bridge.md](backend/ui-bridge.md) | WebBridge（js_api）与 UISync（刷新总线、事件域） |
| [backend/utils.md](backend/utils.md) | 13 个工具模块（路径/配置/网络客户端/标题归一化/热键等） |
| [frontend/README.md](frontend/README.md) | 前端架构：ts 源码、清单内联、全局模型、bridge、渲染约定 |
| [frontend/modules.md](frontend/modules.md) | 16 个 ts 模块逐一：定位、依赖、定义 |
| [web_assets/README.md](../kazari_play/ui/web_assets/README.md) | 前端 TypeScript、HTML、CSS 构建和加载约定 |
| [overlay/README.md](../overlay/README.md) | C++ Overlay 构建、运行和命名管道协议 |

## plans/ — 未实施方案

以下文档是保留的技术方案草稿，不代表当前项目已经采用对应架构，也不属于当前构建入口：

| 文档 | 状态 |
|---|---|
| [MIGRATION_PLAN.md](../MIGRATION_PLAN.md) | Python → C# + WebView2 方案，未实施 |
| [CPP_REWRITE_PLAN.md](plans/CPP_REWRITE_PLAN.md) | C++ 全栈重写方案，未实施；当前项目仍使用 Python + pywebview |
| [TAURI_MIGRATION_PLAN.md](plans/TAURI_MIGRATION_PLAN.md) | Tauri + Python sidecar 方案，未实施 |

## archive/ — 历史记录

以下文档保留开发背景、修复过程和交接信息，不应覆盖当前代码或当前 README 的结论：

| 文档 | 说明 |
|---|---|
| [TRIAL_FEEDBACK_20261007.md](archive/TRIAL_FEEDBACK_20261007.md) | develop 试用三项反馈的基线、证据、验收要求和接手边界；三项已于 `36c17dc`/`d1b30fa` 修复（层级/取消反馈/命名），底层网络取消仍按既有超时返回，待新试用包复验 |
| [SESSION_20261008.md](archive/SESSION_20261008.md) | 2026-10-08 本轮改动说明（扫描整棵树 / 封面解耦与体验 / 搜索超时 / 候选字段勾选） |
| [COVER_DOWNLOAD_OPTIMIZATION.md](archive/COVER_DOWNLOAD_OPTIMIZATION.md) | 元数据匹配与封面下载性能优化：封面与匹配解耦、短超时不重试、可配置与可视化 |
| [MAIN_UI_REDESIGN_G0_TRIAGE.md](archive/MAIN_UI_REDESIGN_G0_TRIAGE.md) | 2026-10-10 G0 基线及早期实施记录；不能用其中的“已修/待做”代替 `b5c8b8d` 前端审查结论 |
| [UI_OPTIMIZATION_DISCUSSION.md](archive/UI_OPTIMIZATION_DISCUSSION.md) | 2026-10-07 评审证据与候选建议；设计承接见主界面计划，当前修复状态见 2026-10-11 前端台账，不自动全量授权实施 |
| [UI_REDESIGN_PLAN.md](archive/UI_REDESIGN_PLAN.md) | 已完成 UI 改造批次及历史计划 |
| [HOOK_TRANSLATION_HANDOVER.md](archive/HOOK_TRANSLATION_HANDOVER.md) | 仅适用于历史和 feature/hook-translation，原版不提供对应源码/API |
| [UI_REVIEW_CONTROL_PANEL_HANDOVER.md](archive/UI_REVIEW_CONTROL_PANEL_HANDOVER.md) | 2026-08 UI 审查和字幕控制面板交接记录；独立控制面板后来被合并进主设置页 |

## 当前验证边界

主界面在 `b5c8b8d` 审查基线的验证边界统一见 [前端修复参考](ui/FRONTEND_REVIEW_REPAIR_PLAN_20261011.md)：关键离线缺陷已修复并入 `develop`；Windows 原生 DPI、窗口拉伸、完整 GUI 和颜色矩阵仍待验收。以下为此前 develop/实验分支记录，不代表新主界面通过验收。

P0/P1 已集成到本地原版 `develop`，公共修复选择性同步实验版；两版数据、前端、源码 GUI、x64/x86 构建和管道回归通过。P2 与新产物启用只在实验版，默认使用 runtime 双架构 EXE/DLL，受控请求、日志隐私、GUI HTTPS 拒绝、toast/字幕像素和 COM 成对释放回归通过。旧实验 EXE/DLL/OBJ 保留且哈希未变，显式配置仍优先；原版运行目录不变。真实 Hook、TLS/AI 服务、独占全屏、多显示器和实际打包尚未验收，本轮未推送或更新稳定 `main`。详细结果以 [开发待办](dev/DEVELOPMENT_BACKLOG.md) 为准，运行与同步步骤见 [分支流程](dev/BRANCH_WORKFLOW.md)。
