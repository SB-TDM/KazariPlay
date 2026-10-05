# KazariPlay 文档索引

> 文档状态：2026-10-06 P0/P1/P2 本地修复收尾
>
> 本页区分当前有效文档、历史记录和未实施方案。当前代码与运行行为以代码、测试结果和“当前有效”文档为准。

## 当前有效

| 文档 | 用途 |
|---|---|
| [README.md](../README.md) | 用户安装、运行、功能和当前版本说明；当前本地版本为 V1.4.0 Beta 1 |
| [AGENTS.md](../AGENTS.md) | Agent/协作者工作入口、目录约定和验证命令 |
| [DEV_RULES.md](DEV_RULES.md) | 改代码、打包、提交和用户数据保护约束 |
| [CHANGELOG.md](CHANGELOG.md) | 按时间记录实际开发改动和验证记录 |
| [RELEASE_NOTES.md](../RELEASE_NOTES.md) | 面向用户的版本发行说明 |
| [THIRD_PARTY.md](../THIRD_PARTY.md) | 第三方组件和许可证说明 |
| [WEBVIEW2_OPTIMIZATION.md](WEBVIEW2_OPTIMIZATION.md) | WebView2 参数决策、性能基线和后续优化原则 |
| [DEVELOPMENT_BACKLOG.md](DEVELOPMENT_BACKLOG.md) | 代码审查问题、修复优先级、已确认分支方向和待定仓库事项 |
| [BRANCH_WORKFLOW.md](BRANCH_WORKFLOW.md) | 原版 main/develop 与翻译实验分支的开发、构建和同步规则 |
| [VERSIONING.md](VERSIONING.md) | 三段式编号、两版预发布标识、唯一版本来源和历史编号映射 |
| [web_assets/README.md](../kazari_play/ui/web_assets/README.md) | 前端 TypeScript、HTML、CSS 构建和加载约定 |
| [overlay/README.md](../overlay/README.md) | C++ Overlay 构建、运行和命名管道协议 |

## 历史记录

以下文档保留开发背景、修复过程和交接信息，不应覆盖当前代码或当前 README 的结论：

| 文档 | 说明 |
|---|---|
| [HOOK_TRANSLATION_HANDOVER.md](HOOK_TRANSLATION_HANDOVER.md) | 仅适用于历史和 feature/hook-translation，原版不提供对应源码/API |
| [UI_REVIEW_CONTROL_PANEL_HANDOVER.md](UI_REVIEW_CONTROL_PANEL_HANDOVER.md) | 2026-08 UI 审查和字幕控制面板交接记录；独立控制面板后来被合并进主设置页 |
| [UI_REDESIGN_PLAN.md](UI_REDESIGN_PLAN.md) | 已完成 UI 改造批次及历史计划 |

## 未实施方案

以下文档是保留的技术方案草稿，不代表当前项目已经采用对应架构，也不属于当前构建入口：

| 文档 | 状态 |
|---|---|
| [MIGRATION_PLAN.md](../MIGRATION_PLAN.md) | Python → C# + WebView2 方案，未实施 |
| [CPP_REWRITE_PLAN.md](CPP_REWRITE_PLAN.md) | C++ 全栈重写方案，未实施；当前项目仍使用 Python + pywebview |
| [TAURI_MIGRATION_PLAN.md](TAURI_MIGRATION_PLAN.md) | Tauri + Python sidecar 方案，未实施 |

## 当前验证边界

P0/P1 已集成到本地原版 `develop`，公共修复选择性同步实验版；两版数据、前端、源码 GUI、x64/x86 构建和管道回归通过。P2 与新产物启用只在实验版，默认使用 runtime 双架构 EXE/DLL，受控请求、日志隐私、GUI HTTPS 拒绝、toast/字幕像素和 COM 成对释放回归通过。旧实验 EXE/DLL/OBJ 保留且哈希未变，显式配置仍优先；原版运行目录不变。真实 Hook、TLS/AI 服务、独占全屏、多显示器和实际打包尚未验收，本轮未推送或更新稳定 `main`。详细结果以 [开发待办](DEVELOPMENT_BACKLOG.md) 为准，运行与同步步骤见 [分支流程](BRANCH_WORKFLOW.md)。
