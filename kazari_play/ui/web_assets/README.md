# 前端模块说明（web_assets）

前端由 **pywebview（Edge WebView2）** 渲染。`main.py` 的 `_load_html()` 在启动时把
`index.html` 中的两个占位符替换为实际内容，**全部内联**进单个 HTML 字符串
（`html=` 模式），以彻底规避中文路径下 `file://` 加载 404 的问题。

> 因此前端**不能使用 ES Module（import/export）**——没有文件服务器可解析相对模块路径。
> 模块化采用「按文件拆分 + 顶层声明共享」的经典脚本方案：
> 多个 `<script>` 块按依赖顺序内联，顶层 `let/const/function` 在所有块间共享，
> 等价于"按文件拆分的单文件脚本"，零跨模块重命名风险。

## 加载机制

- `index.html` 中的 `<!-- PARTIALS -->` → 依次注入 `partials/` 下的分块 HTML
- `index.html` 中的 `<!-- SCRIPTS -->` → 依次注入 `js/` 下的 JS 模块
- 两份清单（顺序即依赖顺序）是 `main.py` 中的 `_PARTIAL_MANIFEST` / `_JS_MANIFEST`，
  **新增模块时两处都要登记**

## JS 模块（js/）

| 文件 | 职责 | 定义的关键全局 |
|---|---|---|
| `state.js` | 全局共享状态（最先加载） | `GAMES` `currentGame` `editingId` `runningId` `state` `window.__app`（refresh/toast/reloadCovers/refreshScreenshots） |
| `core.js` | bridge 代理 + 通用工具 | `bridge` `esc` `toast` `stars` `chipColor` `loadCoverTo` |
| `ui.js` | Sheet / 对话框 / 右键菜单基础设施 | `showSheet` `closeSheet` `showConfirmDialog` `showInputDialog` `openPicker` `showContextMenu` |
| `window.js` | 无边框窗口控制 | `toggleMax` `bindDrag` `bindResize` |
| `games.js` | 游戏数据 + 卡片网格 | `refreshAll` `renderAll` `filterGames` `renderCards` `buildCard` `markRunning` `setActiveCard` `openCardMenu` |
| `detail.js` | 详情底部抽屉 | `openDetail` `refreshDetail` `initRateEdit` |
| `screenshots.js` | 截图卡片 / 预览 / 右键管理 / 截图后定向刷新 | `renderScreenshots` `refreshScreenshots` `openShotPreview` `showShotMenu` |
| `collections.js` | 收藏夹树 / 管理 / 管理游戏 | `renderCollectionTree` `selectCollection` `openCollectionManager` `openManageGames` |
| `batch.js` | 批量选择模式 | `updateBatchBar` `batchPickCollection` |
| `form.js` | 编辑 / 添加表单 + 元数据候选 | `openEdit` `openAdd` `saveForm` `renderCandidates` |
| `settings.js` | 设置窗口（自包含 IIFE） | `window.Settings` |
| `app.js` | 启动引导（最后加载，只做粘合） | `init` `bindFilterMenu` |

模块间通过全局函数/变量互相调用（经典脚本共享作用域）。每个文件头部注释标注了
「依赖 / 定义 / 被依赖」，修改跨模块接口时请同步更新。

## HTML 分块（partials/）

| 文件 | 包含的窗口/对话框 | 对应 JS 模块 |
|---|---|---|
| `common.html` | 输入 / 确认 / 选择器 | `ui.js` |
| `detail.html` | 详情抽屉 + 截图预览 + 截图右键菜单 | `detail.js` / `screenshots.js` |
| `collections.html` | 收藏夹管理 + 管理游戏 | `collections.js` |
| `form.html` | 编辑 / 添加表单 | `form.js` |
| `settings.html` | 设置窗口 | `settings.js` |

**注意**：所有 `.overlay` 均为 `z-index:100`，层叠顺序由 DOM 顺序决定，因此
`_PARTIAL_MANIFEST` 的顺序不能随意调整（设置窗口必须最后，保证盖在一切之上）。
`.shot-menu` 为 `z-index:200`，与 DOM 顺序无关。
