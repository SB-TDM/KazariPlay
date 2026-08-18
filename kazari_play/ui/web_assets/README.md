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

## CSS 模块（css/）

样式按功能职责拆分，`style.css` 作为连接端仅含 `@import` 清单；
`main.py` 的 `_expand_imports()` 递归展开后整体内联。
**拆分 / 新增 CSS 模块时保持 `style.css` 中 `@import` 的相对顺序**（
同特异性且属性重叠的规则靠后加载覆盖前者，层叠语义与顺序绑定）。

| 文件 | 职责 |
|---|---|
| `variables.css` | 亮 / 暗主题变量（design tokens） |
| `base.css` | reset / body / 全局滚动条 / 焦点 / 按钮重置 / 复制区 / 减少动态效果 |
| `titlebar.css` | 无边框窗口标题栏 / 窗口按钮 / 品牌 logo |
| `layout.css` | 导航栏 / 侧边栏 / 主区域 / 排序下拉 / 空状态 / 窗口缩放手柄 |
| `collections.css` | 收藏夹树 / 分组 / 管理游戏 / 标签管理抽屉 |
| `cards.css` | 游戏卡片网格 / 封面 / 批量勾选 / 运行中标记 |
| `widgets.css` | FAB / FAB 菜单 / 批量工具栏 / Toast / 批量进度条 |
| `sheets.css` | 底部抽屉基础设施（overlay / dialog）/ 确认对话框 / 主题切换过渡禁用 |
| `detail.css` | 详情抽屉 / pill 按钮 / chip |
| `screenshots.css` | 截图区 / 大图预览 / 更多菜单 / 截图右键菜单 |
| `form.css` | 编辑 / 添加表单 / 选择面板 / 元数据候选 / 校验 |
| `settings.css` | 设置窗口（居中模态） |
| `sources.css` | 多源元数据 / 自定义复选框（Kawaii 方块） |
| `hook.css` | Hook 选择 / 翻译卡片 |

## JS 模块（js/）

| 文件 | 职责 | 定义的关键全局 |
|---|---|---|
| `state.js` | 全局共享状态（最先加载） | `GAMES` `currentGame` `editingId` `runningId` `state` `window.__app`（refresh/toast/reloadCovers/refreshScreenshots） |
| `core.js` | bridge 代理 + 通用工具 | `bridge` `esc` `toast` `stars` `chipColor` `loadCoverTo` |
| `ui.js` | Sheet / 对话框 / 右键菜单基础设施 | `showSheet` `closeSheet` `showConfirmDialog` `showInputDialog` `openPicker` `showContextMenu` |
| `window.js` | 无边框窗口控制 | `toggleMax` `bindDrag` `bindResize` |
| `games.js` | 游戏数据 / 筛选 / 整体渲染调度 + 卡片状态 | `refreshAll` `renderAll` `filterGames` `markRunning` `toggleSelect` `setActiveCard` `renderEmpty` |
| `cards.js` | 卡片 DOM 构建 / 增量渲染（懒加载）/ 右键菜单 | `buildCard` `renderCards` `openCardMenu` |
| `detail.js` | 详情底部抽屉（展示 / 评分 / 收藏） | `openDetail` `refreshDetail` `initRateEdit` |
| `detail_translate.js` | 详情内 Hook 实时翻译行 + 每游戏清洗配置 | `renderTransRow` `loadCleanCfg` `saveCleanCfg` |
| `screenshots.js` | 截图卡片 / 预览 / 右键管理 / 截图后定向刷新 | `renderScreenshots` `refreshScreenshots` `openShotPreview` `showShotMenu` |
| `collections.js` | 收藏夹树 / 收藏夹管理抽屉 | `renderCollectionTree` `selectCollection` `openCollectionManager` |
| `manage_games.js` | 管理游戏对话框（批量勾选收藏夹内游戏） | `openManageGames` `renderManageGames` `saveManageGames` |
| `batch.js` | 批量选择模式 | `updateBatchBar` `batchPickCollection` |
| `form.js` | 编辑 / 添加表单 + 元数据候选 | `openEdit` `openAdd` `saveForm` `renderCandidates` |
| `hook_select.js` | Hook 点选择弹窗（自包含 IIFE） | `window.HookSelect` |
| `subtitle_style.js` | 字幕样式控制面板（设置页「字幕」tab，自包含 IIFE） | `window.SubtitleStyle` |
| `settings.js` | 设置窗口（自包含 IIFE） | `window.Settings` `window.CLEAN_FILTER_DEFS` |
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
