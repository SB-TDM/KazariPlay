# KazariPlay 文档索引

> 文档状态：2026-10-02 整理
>
> 本页区分当前有效文档、历史记录和未实施方案。当前代码与运行行为以代码、测试结果和“当前有效”文档为准。

## 当前有效

| 文档 | 用途 |
|---|---|
| [README.md](../README.md) | 用户安装、运行、功能和当前版本说明；当前版本为 V1.3 |
| [AGENTS.md](../AGENTS.md) | Agent/协作者工作入口、目录约定和验证命令 |
| [DEV_RULES.md](DEV_RULES.md) | 改代码、打包、提交和用户数据保护约束 |
| [CHANGELOG.md](CHANGELOG.md) | 按时间记录实际开发改动和验证记录 |
| [RELEASE_NOTES.md](../RELEASE_NOTES.md) | 面向用户的版本发行说明 |
| [THIRD_PARTY.md](../THIRD_PARTY.md) | 第三方组件和许可证说明 |
| [web_assets/README.md](../kazari_play/ui/web_assets/README.md) | 前端 TypeScript、HTML、CSS 构建和加载约定 |
| [overlay/README.md](../overlay/README.md) | C++ Overlay 构建、运行和命名管道协议 |

## 历史记录

以下文档保留开发背景、修复过程和交接信息，不应覆盖当前代码或当前 README 的结论：

| 文档 | 说明 |
|---|---|
| [HOOK_TRANSLATION_HANDOVER.md](HOOK_TRANSLATION_HANDOVER.md) | 2026-08 Hook 翻译系统交接记录 |
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

截至 2026-10-02，已验证 TypeScript 类型检查、前端组装、扫描器、多源、缓存、UI Sync、收藏夹、截图和 Overlay 控制面板冒烟流程。`tests/smoke_translation.py` 仍有一项 CSS 检查失败，且 C++ x64/x86 构建尚未在当前终端完成验证；这些状态不能写成“全部通过”。
