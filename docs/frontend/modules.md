# frontend/ — 模块详解

> 每模块含：定位 / 依赖 / 按 `_JS_MANIFEST` 的加载顺序。改动后必须 `npm run build`。

---

## state.ts — 全局状态（最先加载）

**定位**：唯一的全局数据与 UI 状态命名空间 + 后端推送入口。
**依赖**：无。
**定义**：`App`（`App.data` / `App.ui.state`）、`__app`、类型 `Game` / `CollectionRef` / `CollectionTreeNode`。

- `App.data`：`games`（列表快照）、`currentGame`、`editingId`（编辑目标，`null`=手动添加）、`runningId`。
- `App.ui.state`：`nav`（全部作品/继续游玩/我的收藏/collection）、`kw`、`sort`、`batch`、`selected:Set`、`collectionId`、`collectionGroupId`、`openGroupId`（手风琴单开）、`collectionTree`。
- `__app`：全部用**函数包装**（延迟到调用时解析跨脚本符号）。后端 UISync 推送入口。

---

## icons.ts — 内联 SVG 图标库

**定位**：全站图标字形的唯一来源（Bootstrap Icons，16×16 视口，`currentColor`）。
**依赖**：无（先于 core.ts 加载）。
**定义**：`ICON`（play/folder/collection/edit/refresh/trash/controller/starFill/star/gear/close/more/winMin/winMax/winRestore/chevronLeft/chevronDown/chevronRight/plus）。
**约定**：`<svg class="ic">` 尺寸随容器 `font-size`（1em）、随主题着色；静态 HTML 图标（侧栏/关闭按钮/窗口按钮等）内联同一路径；界面不再使用 emoji 或文字字形充当图标（标题栏/关于页的笑脸 `☺` 为既有的品牌字符，保留）。

---

## core.ts — 桥代理 + 通用工具

**定位**：pywebview 桥兼容层 + 全站通用小工具。
**依赖**：state.ts（运行期）。

- `bridge`：`Proxy` 转发 `window.pywebview.api.*` → Promise；末位函数参数视作回调（`bridge.xxx(args, cb)`），回调签名 `(result, failed?)`：调用未到达/同步异常/Promise 拒绝时 `failed=true`，与“空列表 / 对象不存在”区分；业务回调自身异常不再触发第二次回调。`dataChanged` 返回空 `{connect()}`（无信号，改轮询）。**必须全局**（内联 onclick 引用）。
- `esc(s)`：HTML 转义（用户输入进 innerHTML 前必须）。
- `toast(msg)`：顶部胶囊，1.8s。
- `launchGame(id)` / `chipColor(tag)`（哈希 → 5 色糖果板）。
- `beginCoverRequest(el)` / `isCoverRequestCurrent(el, seq)`：封面请求代际标记；迟到响应只有在仍是元素最新请求时才允许写入（覆盖同 ID、A→B→A 与懒加载/重载交错）。
- `loadCoverTo(gameId, el, prefix)`：`prefix='img'` 设 src，否则设 backgroundImage + 渐变兜底；写入前做请求代际校验。
- `makeCheckAll(listSel, checkSel, btnId)`：勾选列表 + 全选/取消全选按钮通用绑定（relocate / metaApply 共用），返回 `{boxes, update}`。

---

## ui.ts — Sheet / 对话框 / 右键菜单基础设施

**定位**：所有模态与上下文菜单的统一实现。
**依赖**：core.ts。
**定义**：`showSheet/closeSheet(id,instant)/closeTopSheet(boolean)`、`showConfirmDialog(opts)/confirmOk`、`showInputDialog(opts)/inputOk`、`openPicker(title,items,onPick)`、`showContextMenu(entries,x,y,width)`（返回元素，全局点击自动移除）。
**Esc 语义**：`closeTopSheet` 按 overlay 注入顺序（即层叠顺序，后出现者在上）倒序关闭第一个可见弹层；输入/确认清理对应回调，设置窗口走 `Settings.close`；无可见弹层返回 false（调用方继续处理抽屉/批量）。
**被依赖**：games/cards/collections/batch/detail/screenshots。

---

## window.ts — 无边框窗口控制

**定位**：标题栏拖拽 / 缩放 / 最大化（frameless 自绘窗口）。
**依赖**：core.ts / icons.ts。
**定义**：`toggleMax`（**内联 onclick 引用，须全局**；调用 `windowToggleMaximize` 并按后端回传的真实状态切 `.maximized` 类、更新按钮图标与 aria）、`bindDrag`（拖拽）、`bindResize`（四边/四角缩放）。

---

## games.ts — 数据 / 筛选 / 渲染调度

**定位**：游戏数据流与整体渲染调度 + 运行状态。
**依赖**：state / core / cards / collections / batch / detail。
**定义**
- 刷新：`refreshAll(force, done?)`（`getGames`+`getCollectionsTree`+`getRunning`；桥失败保留现有数据且不触发 `done`；游戏列表 `_gamesChanged` 判定后才 `renderAll`，树回包同步 `updateNavInfo/renderCards/renderEmpty`）、`applyGamesDelta(ids)`（增量：逐个 `getGame` 更新本地数组；桥失败不视为删除，只有后端返回空对象才移除）、`_gamesChanged`（比较影响显示的字段，**排除**派生的 `last_text/play_time_text`，避免每分钟误全量重渲染）、`syncCurrentGame`
- 封面：`reloadCovers`（全部卡）、`reloadCover(id)`（单卡定向）、`applyCoverSize(size)`（`COVER_SIZES` small/medium/large → CSS 变量 `--card-w/h`，随后 `refreshWindow()` 重算窗口化）
- 渲染：`renderAll`（保持滚动位置）、`filterGames`（nav/kw/collectionId/sort；时间排序对所有视图统一生效）、`renderEmpty`（收藏空/筛选空/库空三态）、`markRunning`、`setRunning`、`toggleSelect`、`setActiveCard`

---

## cards.ts — 卡片构建与窗口化渲染

**定位**：卡片 DOM + **虚拟窗口渲染** + 封面懒加载 + 卡片右键菜单。
**依赖**：state / core / ui / games / detail / collections / form。
**定义**：`buildCard(g)`、`renderCards(list)`（DOM diff + 窗口化）、`openCardMenu(g,x,y)`、`updateCoverProgress(states)`（环形进度）、`replayCoverFade`、`_playCoverFade`。
**关键逻辑**
- 窗口化：`_winStart/_winEnd` + 上下 spacer（`_ensureSpacers/_updateSpacers`）+ 滚动 rAF（`_bindWindowScroll`）+ 容器尺寸 `ResizeObserver`（`_bindWindowResize`）；统一入口 `_recomputeWindow`，外部度量变化用 `refreshWindow()`。`_renderedIds` 做 diff，复用未变卡片（连同已加载封面）。
- 懒加载：`coverObserver`（IntersectionObserver）滚动到附近才 `getCover`，响应按 `beginCoverRequest` 代际校验；`cover_version` 判断重载并作废在途旧响应。
- 事件：卡片点击/键盘/右键只绑定 id，动作执行时经 `_currentGame(id)` 解析最新对象（节点复用不携带旧快照）；`openCardMenu(gameId, x, y)` 同样按 id 取对象，目标已移除则不操作。
- 动画：`coverFade` 播放一次后置 `animation:none`，避免重排重播。

---

## detail.ts — 详情底部抽屉

**定位**：底部 Sheet：封面 / 信息条 / 评分 / 收藏 / 标签 / 收藏夹路径 / 启动 / 截图区。
**依赖**：state / core / ui / games / screenshots / collections。
**定义**：`openDetail(g)`（存 `currentGame`、高亮卡、异步重取最新）、`refreshDetail`、`renderInfoBar`、`initRateEdit`、`collectionPath`、`renderDetailTags`、`updateFavBtn`。

---

## screenshots.ts — 截图管理

**定位**：详情内截图区：卡片 / 预览 / 右键管理。
**依赖**：state / core / ui。
**定义**：`renderScreenshots`（`shotObserver` 懒加载缩略图，`shotsRequest` 防竞态）、`refreshScreenshots(gameId)`、`openShotPreview`（原图，`previewRequest` 防竞态）、`showShotMenu/hideShotMenu`、`renameShot`、`openShotFolder`、`copyShot`、`deleteShot`。

---

## collections.ts — 收藏夹

**定位**：侧边栏树 + 收藏夹管理抽屉（当前游戏加入/退出收藏夹）。
**依赖**：state / core / ui。
**定义**：`renderCollectionTree`、`renderCollectionGroup`（手风琴，`toggleExpand`）、`renderCollectionCategory`、`bindCollectionItems`、`findCollectionNode`、`selectCollection`（选中集合/分组过滤）、`findParentGroupId`、`clearCollectionFilter`、`showCollectionCtx`（右键：重命名/删除/管理游戏）、`newCollection`、`renameCollection`、`delCollection`、`openCollectionManager`、`renderGameCollections`。

---

## manage_games.ts — 管理游戏对话框

**定位**：批量勾选收藏夹内游戏（分组时聚合子分类保存）。
**依赖**：state / core / ui。
**状态**：`manageGamesId`、`manageGamesIsGroup`、`manageGamesSel`、`manageGamesData`。
**定义**：`openManageGames(node)`、`renderManageGames`、`toggleManageGame`、`updateManageCount`、`saveManageGames`。

---

## batch.ts — 批量选择模式

**定位**：勾选 / 全选 / 批量收藏夹 / 批量匹配 / 批量删除 + 进度条 + 重新定位。
**依赖**：state / games / ui。
**定义**
- `updateBatchBar`（工具栏状态）、`collectionPickerItems`、`batchPickCollection(mode)`（add/remove/move）
- 进度：`showBatchProgress/hideBatchProgress/trackBatchProgress`（`bpTimer` 轮询 `getBatchProgress`，`bpGeneration` 防旧轮询回填）
- `updateScanProgress(p)`（扫描/匹配进度 + 取消按钮，`cancelMode` 区分 scan/match）
- `updateBatchProgress(p)`、重新定位预览 `renderRelocatePreview(items)` + `relocateSel`（`makeCheckAll`）

---

## form.ts — 编辑/添加表单 + 元数据候选

**定位**：编辑与手动添加表单；多源元数据搜索、候选展示与字段勾选应用。
**依赖**：state / core / ui。
**定义**
- 表单：`openEdit(g)` / `openAdd()`（`setFormRows` 切换显示行）、`saveForm()`（校验 + `saveGame`）、`showFormError/clearFormError`
- 元数据：`initMetaSources`（`getMetadataSources`）、`renderSrcBar`（源切换 mixed/单源）、`currentSearchTargets`、`renderCandidates`、`META_FIELDS`（字段定义表：key/label/cur/next/hasCand）、`openMetaApply(c)`（字段勾选对话框，`metaApplySel = makeCheckAll(...)`）、`closeMetaApply`；应用调 `bridge.applyCandidate(id, cand, fields)`

---

## settings.ts — 设置窗口（自包含 IIFE）

**定位**：设置窗口逻辑；暴露 `window.Settings`。
**依赖**：core（bridge/toast）。
**结构**：`(function(){ ... })()`，导出 `window.Settings = { open, close, pickTheme, applyTheme, initTheme }`。
**定义**：`applyTheme(t)`（加 `.theme-switch` 全局禁用 transition 防重排痕迹，设 `dataset.theme`）、`initTheme(t)`（启动初始主题；用户已显式选择则不覆盖）、`markThemeCard`、`fmtKey`、`open/close`（各自的会话代际使在途保存失效）、`loadConfig`（`getConfig` 填表；代际校验 + `themePicked` 保护，迟到回包不覆盖新选择）、`loadMetaSources`、`pickTheme`（即时预览并标记 themePicked）、`save()`（点击时定格完整快照与会话代际；`saveConfigs`/热键重注册/元数据源均用快照值；失败保留窗口与输入，重复提交由按钮禁用与请求代际约束）、`takenHotkeys`/`bindHotkey`（单一活动捕获目标，失焦/关闭/保存统一 `stopHotkeyCapture` 并恢复原值）、`setReset`。

---

## app.ts — 启动引导（最后加载）

**定位**：只做「粘合」——初始化、导航、搜索、筛选下拉、FAB、全局点击与键盘。
**依赖**：state / core / ui / window / games / collections / batch / form。
**定义**
- `init()`：就绪判定（`apiReady = Object.keys(api).length>0` + 轮询 + `pywebviewready` 三重，`_ready` 防重复）→ 拉配置（`Settings.applyTheme` + `applyCoverSize`）→ `refreshAll(true)` → 30s 长轮询
- `bindFilterMenu`：排序下拉
- 事件：搜索框（200ms 防抖）、筛选按钮、侧边栏导航、设置入口、空状态/FAB（扫描/添加/刷新）、全局点击收浮层、`Esc`（退出批量或关最上层 Sheet）
- 末尾：`bindDrag(); bindResize(); init();`

---

## 类型声明

- `pywebview.d.ts`：`window.pywebview` / `window.Settings` / `window.bridgeReady` 等全局类型。
- `globals.d.ts`：`ContextMenuEntry` 等跨模块共享的全局类型。
