# frontend/ — 前端总览

> 前端是**运行时内联进单个 HTML** 的经典脚本（不是模块打包）。唯一真相是 `ts/` 源；
> `tsc` 编译到 `js/`（gitignore），`main.py` 按清单把 `js/*.js` + `partials/*.html` + css 内联。
> 逐模块细节见 [`modules.md`](modules.md)。

## 目录

```
kazari_play/ui/web_assets/
├── ts/            # TypeScript 源（唯一真相，改这里）
├── js/            # tsc 编译产物（勿手改，gitignore）
├── css/           # style.css 为 @import 入口；启动时递归展开内联
├── partials/      # 各窗口/对话框独立 HTML 片段
├── index.html     # 骨架（含 <!-- PARTIALS --> 与 <!-- SCRIPTS --> 标记）
├── package.json   # script: build(tsc) / typecheck
└── tsconfig.json  # removeComments:true（产物 js 无注释）
```

## 构建与内联

```bash
cd kazari_play/ui/web_assets
npm ci                # 首次
npm run build         # tsc: ts/ -> js/
npm run typecheck     # 只类型检查
```

`main.py::_load_html()` 在启动时组装最终 HTML：
1. **partials**：`_PARTIAL_MANIFEST` 顺序读 `partials/*.html` 注入 `<!-- PARTIALS -->`（**顺序即 DOM 层叠顺序**，`common.html` 放最后盖在最上）
2. **js**：`_JS_MANIFEST` 顺序把 `js/*.js` 各包一个 `<script>` 注入 `<!-- SCRIPTS -->`（**顺序即依赖顺序**）
3. **css**：递归展开 `@import`（`style.css` 入口）内联为单个 `<style>`（html= 模式无 base URL，浏览器无法解析 `@import` 相对路径）
4. 图标占位符 → data URI；`{{APP_VERSION}}/{{PRODUCT_LINE}}/{{APP_TITLE}}` 替换

> **新增前端模块**：`ts/` 建文件 → 登记 `main.py::_JS_MANIFEST`（位置即依赖顺序）。

## 加载顺序（`_JS_MANIFEST`）

```
state → core → ui → window → games → cards → detail → screenshots
      → collections → manage_games → batch → form → settings → app
```
- `state` 最先（定义全局 `App` 与后端入口 `__app`）；`app` 最后（引导 + 全局事件绑定）。
- 经典脚本共享顶层作用域：`let/const/function` 跨 `<script>` 块可见（等价「按文件拆分的单文件脚本」）。

## 全局模型

- **`App`（state.ts）**：`App.data`（`games/currentGame/editingId/runningId`）+ `App.ui.state`（`nav/kw/sort/batch/selected/collectionId/collectionGroupId/openGroupId/collectionTree`）。各模块统一经 `App.xxx` 读写。
- **`bridge`（core.ts，必须全局）**：`Proxy` 转发 `window.pywebview.api.*`，返回 Promise；最后一个函数参数视作回调（兼容旧 `bridge.xxx(args, cb)` 风格）。`index.html` 内联 `onclick` 直接引用它，故不能包进 IIFE。
- **`__app`（state.ts）**：后端 `UISync` 推送的入口 `window.__app.*`，全部用**函数包装**（属性值在 state.ts 执行时即求值，直接引用会 ReferenceError）。域 → 方法映射见后端 [ui-bridge.md](../backend/ui-bridge.md#syncts--uisync-更新总线)。

```ts
// 调用后端
const games = JSON.parse(await bridge.getGames());
bridge.getCover(id, uri => { /* 回调风格 */ });
// 被后端调用（UISync → window.__app.*）
__app = { refresh, toast, reloadCovers, reloadCover, applyGamesDelta,
          refreshScreenshots, setRunning, updateScanProgress,
          updateBatchProgress, updateCoverProgress };
```

## 就绪判定（app.ts）

pywebview 先注入 `window.pywebview`（`api` 为**空对象**），导航完成后才填充并派发 `pywebviewready`。故就绪判定为 **`Object.keys(api).length > 0`** + 轮询兜底 + `pywebviewready` 事件三重保障（`_ready` 防重复）。就绪后：拉配置（`applyTheme` + `applyCoverSize`）→ `refreshAll(true)` → 30s 长轮询兜底。

## 渲染与性能约定

- **全量/增量分离**：`refreshAll`（全量，`_gamesChanged` 判定后才重建网格）vs `applyGamesDelta`（只更新变化卡片）。
- **卡片窗口化**：`cards.ts` 用上下 spacer + `IntersectionObserver` 懒加载封面，只渲染可视窗口 ± 缓冲行。
- **封面懒加载**：`getGames` 不内联 base64；滚动到卡片附近才 `getCover(id)`；`cover_version`（mtime）判断是否重载。
- **耗时逻辑占位**：卡片先出占位（灰色），封面到达后淡入（`coverFade`）。
- **单卡定向刷新**：`reloadCover(id)` 只重载一张卡，避免全量重载导致所有封面重新淡入。
- **`cover_progress`**：`updateCoverProgress(states: Record<id, pct>)`，用**全量快照**渲染下载中卡片的环形进度。

## 约定

- 用户输入进 `innerHTML` 前必须 `esc()`（`core.ts`）。
- 通用交互统一走 `ui.ts`：`showSheet/closeSheet/closeTopSheet`、`showConfirmDialog`、`showInputDialog`、`openPicker`、`showContextMenu`；通用勾选全选用 `makeCheckAll`。
- 模态用 CSS `.overlay`（统一 `z-index`，靠 DOM 顺序层叠）；`Esc` 关闭最上层。
- 只改 `ts/`，改完必须 `npm run build`；新增模块登记 `main.py::_JS_MANIFEST`。
