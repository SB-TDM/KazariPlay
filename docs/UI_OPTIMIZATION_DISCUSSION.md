# KazariPlay UI 优化讨论草案

> 状态：`draft / pending-discussion`，待进一步讨论，尚未批准实施。评审与归档日期：2026-10-07。
>
> 本文保存全量 UI 评审、代码建议和验收目标，供后续确定范围与优先级；示例不是已落地实现，性能预算不是实测成绩。写入文档不表示授权改代码、重打包、合并分支或发布。

## 一、快速诊断

### 项目事实与评审基线

- 项目类型：Windows 桌面视觉小说本地库启动器，核心操作为游戏查找/启动、元数据、收藏夹、截图和批量任务。
- 技术栈：Python 3.11 + pywebview 6.2.1 / Edge WebView2；TypeScript 经典脚本经 tsc 编译，由 main.py 组装内联；原版 14 个前端模块，自研 CSS 与控件，没有 React/Vue/Tailwind 或现成组件库。
- 范围：用户选择全量原版 UI，包括首页、详情、设置、表单、收藏夹管理、进度面板、截图和重新定位，没有提供额外材料。现有 [试用反馈](TRIAL_FEEDBACK_20261007.md) 作为历史背景。
- 交付基线：试用包为 `85d936b / 1.4.0-beta.1`。评审期间其他 agent 提交了 `36c17dc`，将进度层级降至 90、增加取消反馈并统一匹配文案；随后 widgets.css 还有批量工具栏避让改动。评审结果对应当时的代码与运行快照，不能把旧包、新代码和已验收状态等同。
- 方法：静态源码分析、CSS 颜色对比度计算、隔离源码 GUI 探针。使用 80 条临时游戏记录，在 900×620 和请求尺寸 1366×768 下检查；后者实际 WebView 视口约 1352×731。详情乱序测试使用 A=700ms、B=30ms 的受控延迟。本次评审没有调用真实网络服务或读取真实用户库/配置。
- 目标假设：保留现有品牌和功能，先减少错误操作、等待不确定性、小窗口遮挡和键盘障碍；桌面优先，不假定需要移动端 H5。该假设待产品讨论确认。

下表级别是本次 UI 评审的建议排序，P0 表示影响可用性、操作正确性或关键键盘路径，不表示已经证实数据丢失；最终实施范围与顺序仍待定。

| 优先级 | 问题 | 影响 | 判断依据 |
|---|---|---|---|
| P0 | 快速切换详情，旧响应覆盖新目标 | 显示与后续操作对象可能错误 | GUI 实测 A 慢/B 快后 currentGame 与标题回到 A；[detail.ts](../kazari_play/ui/web_assets/ts/detail.ts) 的 openDetail、[core.ts](../kazari_play/ui/web_assets/ts/core.ts) 的 loadCoverTo 未核验目标/代际 |
| P0 | 900×620 下批量工具栏超出主区 | 右侧命令可能不可见或不能点击 | 实测工具栏约 869px，主区仅 760px，右边界约 955px；[widgets.css](../kazari_play/ui/web_assets/css/widgets.css) 的 .batchbar |
| P0 | 成功提示先于真实写入结果 | 用户误以为保存或复制成功 | 静态确认：[settings.ts](../kazari_play/ui/web_assets/ts/settings.ts) 的 save、[screenshots.ts](../kazari_play/ui/web_assets/ts/screenshots.ts) 的 copyShot、[form.ts](../kazari_play/ui/web_assets/ts/form.ts) 的候选应用；本轮未注入磁盘失败 |
| P0（键盘路径） | 模态无焦点隔离，关闭层级遗漏确认/输入/定位 | 键盘可能操作后台或关闭错误层 | GUI 设置打开后焦点仍为 searchInput；调用 closeTopSheet 时确认仍显示而详情已关闭；[ui.ts](../kazari_play/ui/web_assets/ts/ui.ts) 的 showSheet/closeTopSheet |
| P1 | 卡片无游戏标题和明确可访问名称 | 无封面/相似封面时难以辨识 | [cards.ts](../kazari_play/ui/web_assets/ts/cards.ts) 的 buildCard 仅显示开发商/星级；GUI 中 aria-label 与 title 为空，读屏实际播报未测试 |
| P1 | 取消反馈改善，但在途请求仍可能等待 | 用户难判断任务阶段和剩余等待 | `36c17dc` 已有“正在取消”和 Event.wait；[vndb_client.py](../kazari_play/utils/vndb_client.py) 的在途 urllib 请求仍等待，本轮未测真实取消耗时 |
| P1 | 浅色有效文本与主按钮对比度不足 | 开发商、简介、说明和操作文字难读 | CSS 计算：副文本/白底约 2.96:1，浅说明/白底约 1.82:1，白字/粉色渐变端点约 1.68～2.15:1 |
| P1 | 元数据候选、封面没有统一迟到响应保护 | 结果可能覆盖新的检索或游戏上下文 | [form.ts](../kazari_play/ui/web_assets/ts/form.ts) 的 searchMetadata、[core.ts](../kazari_play/ui/web_assets/ts/core.ts) 的 loadCoverTo；截图模块已有保护，其他场景为静态判断 |
| P1 | 表单错误挤在输入行右侧，无字段错误语义 | 输入区缩窄、提示换行费力，读屏不知无效字段 | GUI 中 fExeRow 错误约 129×52px；[form.css](../kazari_play/ui/web_assets/css/form.css) 未给错误独立行，aria-invalid/describedby 为空 |
| P2 | 样式/状态局部散落，性能没有测量预算 | 易再次出现层级、尺寸和状态不一致 | gap、z-index、色值硬编码，卡片常驻 will-change；package.json 只有 build/watch/typecheck，静态判断 |

已有基础应保留：字符串 Game.id、App.data/App.ui 状态收敛、DOM 窗口化、封面/截图 IntersectionObserver 懒加载、200ms 搜索防抖、固定卡片尺寸、focus-visible、prefers-reduced-motion、保存失败保留输入和截图请求代际保护。

## 二、分维度优化建议

各示例只展示关键方向，需结合现行函数和类型契约补齐；工时是假设熟悉项目的一名工程师的估计，不是排期承诺。

### 1. 设计系统与视觉一致性

- **现状问题**：[variables.css](../kazari_play/ui/web_assets/css/variables.css) 有亮暗主题 token，但 text-sub/text-disabled 用于有效信息，白字主操作直接叠浅粉渐变；危险色、菜单阴影、边框和层级仍有硬编码。进度 z-index 已从 300 改为 90，不重复当成尚未改动。
- **影响**：信息难读，组件层级依赖经验。收益高，成本低到中，约 0.5～1 天加主题回归。
- **改动建议**：品牌粉色保留为装饰，增加可读文本、主操作、焦点和层级 token；有效说明不使用 disabled token。圆角先统一职责，进度、模态、模态内菜单、toast 明确层级。
- **具体 CSS 示例**：下列颜色在白底计算通过，其他实际背景仍需测量。

```css
:root {
  --text-sub: #74687f;
  --action-bg: #b82f62;
  --action-fg: #fff;
  --focus-ring: #b82f62;
  --z-progress: 90;
  --z-modal: 100;
  --z-modal-menu: 200;
  --z-toast: 300;
}
.pill-btn.primary { background: var(--action-bg); color: var(--action-fg); }
.batch-progress { z-index: var(--z-progress); }
```

- **验收标准**：普通字号有效文本至少 4.5:1，功能图标/焦点/必要控件边界目标 3:1；真正禁用控件另行处理。候选 text-sub/白底约 5.21:1，action-bg/白底约 5.80:1。两个主题分别测量透明/渐变/opacity 合成结果；模态交互和当前焦点不被浮层挡住。

### 2. 布局与响应式

- **现状问题**：[layout.css](../kazari_play/ui/web_assets/css/layout.css) 的搜索绝对居中，与命令区独立排版；batchbar 不换行、无 max-width。900×620 实测搜索与按钮约重叠 8px，工具栏超视口约 55px。详情 640px 断点无法覆盖应用 900×620 的最小窗口。
- **影响**：核心命令被裁剪。收益高，成本中，约 1 天；改变卡片尺寸要联动虚拟列表度量。
- **改动建议**：搜索与命令参与同一 Flex/Grid，主区 min-width:0；批量栏限制宽度，普通命令折行或聚合到更多菜单，危险操作保持清楚。实际工具栏高度写入 CSS 变量，给列表与进度面板动态留底部空间，不只依赖固定 bottom:92px。
- **具体 CSS 示例**：需同时取消现有搜索居中 transform。

```css
.main { min-width: 0; }
.navbar { gap: 12px; }
.search { position: static; transform: none; flex: 1 1 360px;
  min-width: 0; max-width: 460px; width: auto; }
.navbtns { flex: none; margin-inline-start: auto; }
.batchbar { max-width: calc(100% - 24px); flex-wrap: wrap; border-radius: 12px; }
.scroll { padding-bottom: calc(var(--batchbar-height, 56px) + 28px); }
```

- **验收标准**：900×620、1024×768、1366×768、1920×1080，100%/125%/150%/200% DPI，以真实 innerWidth/innerHeight 为准；所有命令可见可点击，长按钮、长标题及 300 字符路径不溢出。移动端是否需要支持另定。

### 3. 信息层级与排版

- **现状问题**：首页只有封面、开发商、评分，无游戏名；默认封面下多张卡难辨识。[detail.css](../kazari_play/ui/web_assets/css/detail.css) 将简介限制在 96px 的独立滚动区，信息固定三列。
- **影响**：查找需要反复开详情，小窗口嵌套滚动影响阅读。收益高，成本中，约 0.5～1 天。
- **改动建议**：GameCard 增加始终可见标题，开发商降为次行；标题两行截断，完整名称放 title/accessible name。详情保留一个主要滚动区，简介自然布局或显式展开/收起。卡片总高度固定并重新校准 card-h/WindowCalculator。
- **具体代码 / CSS 示例**：buildCard 模板和复用节点更新都要同步。

```ts
card.setAttribute('aria-label', g.title || '未命名游戏');
card.title = g.title;
// 模板加入 <div class="game-title">${esc(g.title || '未命名游戏')}</div>
```

```css
.game-title { font-size: 13px; line-height: 1.4; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.detail-desc { max-height: none; overflow: visible; }
```

- **验收标准**：缺封面、同开发商、长日文/英文名、空标题可辨识，读屏名称为游戏名；无卡片跳高、虚拟列表空行或更新后旧标题不刷新。

### 4. 交互与反馈

- **现状问题**：取消已有即时文案，任务却没有集中生命周期；hide/new progress 更新可能重新启用取消按钮。[app.ts](../kazari_play/ui/web_assets/ts/app.ts) 刷新立即报“已刷新”，launchGame 忽略返回 ok，部分保存/复制也先报成功。主题实际即时持久化，说明却写“保存后生效”。
- **影响**：不能区分请求提交与实际完成。收益高，成本中；持久化结果需少量后端契约协同，不是纯 CSS。
- **改动建议**：TaskProgress 集中 idle/running/cancelling/completed/failed；取消不释放后台门禁，收到真实结束才恢复。启动、刷新、保存按结果提示，长任务展示阶段/来源；保留已完成数据和现有迟到进度隔离。
- **具体 TypeScript 示例**：task/renderTask 是待实现的状态模型，不是现有全局变量。

```ts
type TaskPhase = 'idle' | 'running' | 'cancelling' | 'completed' | 'failed';
async function requestCancel(): Promise<void> {
  if (task.phase !== 'running') return;
  task.phase = 'cancelling'; renderTask();
  try { await window.pywebview!.api.cancelMatch(); }
  catch { task.phase = 'running'; renderTask(); toast('取消请求失败'); }
  // 等后端进度结束，不在这里宣布任务已经终止。
}
```

- **验收标准**：建议 UI 反馈小于 150ms，属于待确认目标；重复取消只提交一次，取消期间进度更新不重启按钮，异常可恢复。已在途 HTTP 的实际结束时限单独测量，不能只隐藏进度伪装完成。

### 5. 状态覆盖与异步正确性

- **现状问题**：openDetail/getGame 和 loadCoverTo 缺目标核验，候选搜索无请求序号；bridge 的异常 fallback [] 可能把网络错误呈现为“未找到”。错误文本挤在输入行右侧，无字段错误关联。
- **影响**：详情乱序已受控复现，用户可能在错误对象上继续操作；断网与空结果难区分。收益高，成本中；详情隔离是小改，统一错误契约更大。
- **改动建议**：沿用 [screenshots.ts](../kazari_play/ui/web_assets/ts/screenshots.ts) 的 generation+gid 规则，推广至详情、封面、候选和收藏夹管理。loading/empty/error 分开，失败保留输入及旧内容并可重试；保存 busy 防重复提交，错误占独立行。
- **具体 TypeScript / CSS 示例**：放入 openDetail 对应请求路径，关闭时也使代际失效。

```ts
let detailRequest = 0;
const request = ++detailRequest, gid = g.id;
bridge.getGame(gid, raw => {
  if (request !== detailRequest || App.data.currentGame?.id !== gid) return;
  const fresh = JSON.parse(String(raw));
  if (fresh.id !== gid) return;
  App.data.currentGame = fresh; refreshDetail();
});
```

```css
.edit-form .form-row { display: grid; grid-template-columns: 64px minmax(0,1fr) auto; }
.edit-form .form-error { grid-column: 2 / -1; padding-left: 0; }
```

- **验收标准**：A 慢/B 快、A→B→A、关闭后迟到、请求失败、长简介/路径、损坏图和超过后端 8MB 预览限制有明确状态。只声称受控乱序可复现，不声称真实用户已经误操作。

### 6. 可访问性

- **现状问题**：模态缺 role/aria-modal/labelledby、进入/限制/返回焦点；评分 span、截图/候选 div、来源 span、选择器 p-item 不可完整键盘操作；设置 label 为 div。[base.css](../kazari_play/ui/web_assets/css/base.css) 已有 focus-visible，管理游戏行已有 checkbox 语义，应继续覆盖核心路径。
- **影响**：键盘/读屏用户不能完整操作，后台可能误触。收益高，成本中，约 1～2 天含嵌套层回归。
- **改动建议**：ui.ts 的 ModalManager 维护栈与 opener，只有栈顶可交互，后台及下层 inert；Esc 先关栈顶再退出批量。设置 tab 补 tablist/selected 和方向键，截图/候选/来源用 button，评分用原生 radio/button；输入有 label 和错误描述。
- **具体 HTML / API 示例**：仅添加属性不能替代完整焦点管理。

```html
<div class="dialog settings" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
  <h3 id="settingsTitle">设置</h3>
</div>
<label for="setCoverSize">封面尺寸</label>
<button type="button" class="shot-item" aria-label="预览截图 shot_001.png">...</button>
```

```ts
const opener = document.activeElement as HTMLElement;
document.querySelector<HTMLElement>('.app')!.inert = true;
dialog.querySelector<HTMLElement>('button, input, select, [tabindex="0"]')?.focus();
// 关闭栈顶时重算 inert，并返回 opener；被回收则回到列表容器。
```

- **验收标准**：Tab/Shift+Tab 不离开顶层模态，Esc 只关一层，确认/输入/定位都覆盖；所有命令可键盘完成，aria-pressed/checked 暴露状态。鼠标目标以 24×24 CSS px 为基准，频繁点击建议 32～40px；桌面不机械套用 iOS 44pt。

### 7. 性能与渲染

- **现状问题**：已有窗口化，80 条 fixture 在两视口仅渲染 20/30 卡片；但滚动每次计算会 filter/sort 全库，gap=14 在 JS/CSS 重复，resize 无 ResizeObserver；常驻 will-change:transform，刷新逐卡 offsetHeight 强制布局。
- **影响**：大库滚动、缩放和刷新可能增加主线程开销，FPS/INP 未实测。收益中，成本中，约 1 天加基准。
- **改动建议**：筛选/排序在数据或条件变化时缓存，纯滚动只算窗口；ResizeObserver 监听 grid/scroller，gap 从 computed style 读；重排批读批写，避免所有卡片长期提升合成层。保留懒加载、缓存和请求去重，不回退全量 DOM。
- **具体 TypeScript 示例**：cachedFilteredGames 为待加入缓存。

```ts
const gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
const observer = new ResizeObserver(() => requestAnimationFrame(() => {
  renderCards(cachedFilteredGames);
}));
observer.observe(grid);
```

- **验收标准**：100/1000/10000 条固定数据前后比较。建议滚动主要工作小于 16.7ms、交互 P95 小于 200ms、CLS 小于 0.1，需绑定测试机器和负载；并非当前成绩。页面 LCP 与 EXE 启动/bridge-ready 分开记录；resize 后 DOM、占位和滚动位置一致。

### 8. 组件架构与代码质量

- **现状问题**：manifest 顺序共享全局，App 已收敛，但模态、任务与错误处理散落。[core.ts](../kazari_play/ui/web_assets/ts/core.ts) 的 bridge 在回调失败时返回 []，失败/空结果语义混淆，设置保存也不能识别哪项失败。
- **影响**：易多处复制竞态或反馈错误。收益中到高，成本中；不建议迁移 React/Vite/Tailwind 来解决局部问题。
- **改动建议**：在现有模块补 ModalManager（ui.ts）、TaskProgress（batch.ts）、BridgeService（core.ts）。query 失败抛错，command 解析既有 bool/ok；无结果写操作需最小返回契约调整，await None 不能证明磁盘成功。保留 App、manifest、Python js_api。
- **具体 TypeScript 示例**：使用原生 API Promise 保留失败语义。

```ts
async function query<T>(method: () => Promise<string>): Promise<T> {
  return JSON.parse(await method()) as T;
}
const result = await query<{ok: boolean; msg?: string}>(
  () => window.pywebview!.api.launch(gid));
if (!result.ok) toast(result.msg || '启动失败');
```

- **验收标准**：桥失败不呈现假成功或空库；Python 返回与 pywebview.d.ts 联动，保留字符串 ID、UISync 和代际行为。新增模块登记 manifest，运行 verify_frontend，不手改生成 JS。

### 9. 主题与多端

- **现状问题**：危险 hover、占位、开关和菜单混入硬编码亮色；[screenshots.css](../kazari_play/ui/web_assets/css/screenshots.css) 预览固定深表面却使用 root text，浅色主题可能深字深底。language 配置存在不等于 UI 已国际化。
- **影响**：暗色组件局部刺眼，预览控件可读性差；主题即时持久化与说明不一致。收益中，成本低到中；i18n/RTL 全支持需产品确认。
- **改动建议**：预览独立 inverse-surface/text token；danger/field/placeholder 语义化，pickTheme 实际行为与文案一致。用逻辑属性为后续适配留空间，但最低 WebView2 版本需核实，不能预设所有 inert/容器查询都兼容。
- **具体 CSS 示例**：

```css
#shotPreviewOverlay { --preview-bg: #17131d; --preview-text: #f4f0f6; }
#shotPreviewOverlay .shot-preview { background: var(--preview-bg); }
#shotPreviewOverlay .dlg-title { color: var(--preview-text); }
.detail-body { padding-inline: 22px; }
```

- **验收标准**：亮暗独立覆盖设置、详情、预览、error/danger/disabled/focus；主题即时保存与取消行为一致。没有 i18n/RTL 实测就标待规划，不额外添加移动安全区样式改变桌面布局。

### 10. 工程化与验收

- **现状问题**：package.json 只有 typecheck/build/watch，已有 manifest/HTML ID 与 Node 回归，视觉/键盘/大库性能未形成验收预算。并行代码、文档与同一 beta 编号的多个包易混淆。
- **影响**：编译通过仍可能遮挡/焦点/竞态，反馈基线难对齐。收益高，成本中，约 1～2 天固定 fixture 和可靠环境。
- **改动建议**：ESLint/Stylelint 先约束新增和核心入口；视觉/键盘测试用 main._load_html() 真实组装 + mock bridge，Windows 冻结自检验证真实桥/WGC/Overlay；离线延迟/失败/乱序替身优先。性能/错误先本地匿名记录，外部遥测另定，不能默认上传游戏名或库内容。
- **具体配置 / 测量示例**：需要配套依赖与 lint 配置，当前尚未新增。

```json
{"scripts": {"lint": "eslint ts", "lint:css": "stylelint css/*.css"}}
```

```ts
performance.mark('library-render:start');
renderCards(cachedFilteredGames);
performance.mark('library-render:end');
performance.measure('library-render', 'library-render:start', 'library-render:end');
```

- **验收标准**：typecheck/build/verify_frontend + 聚焦 Node/GUI 回归；两主题两尺寸视觉矩阵，截图隔离/字符串 ID/保存失败/任务门禁保持。性能同机同 fixture 比较，离线测试避免服务/favicon 干扰；试用包 BUILD_INFO 对应验收提交，新输出不覆盖 data。本轮文档归档不添加 CI/远端设置。

## 三、优先级路线图

路线图为候选顺序，未形成实施承诺；开工前先确定第五节讨论项并核对其他 agent 的新提交。

### P0：建议先解决

- **异步目标正确性**：详情/封面/候选加目标和代际核验，先修 A→B 受控复现。成本约 0.5～1 天，收益是避免错误操作对象。
- **最小窗口可用性**：搜索和命令同布局，批量栏限宽且动态保留底部空间。成本约 0.5～1 天，恢复被裁剪命令。
- **真实结果反馈**：启动、复制、保存、设置、候选应用按结果提示，无返回写操作补最小契约。成本约 1～2 天，减少假成功。
- **键盘模态主路径**：显式栈、进入/隔离/返回焦点、栈顶 Esc。成本约 1～2 天，恢复核心键盘操作。

### P1：建议尽快安排

- 卡片游戏标题/可访问名称、表单独立错误行和字段语义、有效文本对比度。
- TaskProgress 和取消阶段/来源提示；复验 `36c17dc`，已在途请求耗时另测，不重复无依据重写网络层。
- ResizeObserver、尺寸 token、筛选排序缓存、虚拟列表焦点恢复，详情减少嵌套滚动。
- 通用元数据命名与实际来源一致；自动 VNDB 与手动多源候选的区别需说明。

### P2：可排期

- emoji 控件图标逐步统一为本地矢量图标，尺寸、tooltip、可访问名称一致；游戏封面保留内容本身。
- spacing/radius/shadow/motion token，减少全量装饰动画，保留现有品牌风格。
- lint、视觉快照、本地性能预算；国际化/RTL/触控支持在需求确认后安排。

## 四、回归测试清单

以下是未来实施的验收清单，不表示已全部执行。

| 页面/组件 | 必测交互与边界 |
|---|---|
| 游戏库 | 空库、0/1/80/1000/10000 游戏，无封面/损坏图、长标题、相同开发商，筛选/排序/收藏/评分更新 |
| 导航/搜索 | 900×620、1024×768、1366×768、1920×1080 的实际视口；DPI 100/125/150/200%，中文输入法、防抖、无结果/恢复全部、搜索与按钮不重叠 |
| 批量栏 | 全选/清空、八个命令、长文案和危险操作可见；不挡最后一行与焦点，选中状态可读 |
| 批量任务 | 扫描→匹配、取消→正在取消→终止、退避/在途/封面阶段、异常/拒绝、重复取消、取消后新任务和迟到轮询 |
| 模态栈 | 详情→确认、截图→重命名、设置、编辑、选择器、重新定位；Tab/Shift+Tab/Esc 只作用栈顶，返回焦点正确 |
| 详情/封面 | A 慢/B 快、A→B→A、关闭后迟到、删除当前目标，启动/编辑/收藏/评分均对应正确 gid |
| 表单/设置 | 字段错误、无效 exe、长路径/简介、重复提交、桥失败、磁盘不可写、热键注册失败；不假成功、不关失败表单 |
| 元数据候选 | 初载、空结果、断网、源错误、乱序、来源显示、pending 源不可选，自动/手动路径不误标 |
| 截图 | 无图、损坏图、大原图、慢缩略图、失败重试、键盘预览/菜单/复制/删除、跨游戏同名隔离 |
| 重新定位 | conflict、缺文件、路径占用、部分失败、内部/外部 override、收藏和时长保留，跳过项文本可读 |
| 主题/访问性 | 亮暗的 normal/hover/active/disabled/error/focus、inverse surface、减少动效、label/aria/对比度、完整键盘路径 |
| 性能 | 同机固定 fixture，滚动帧、bridge-ready、首次主要内容、筛选/排序延迟、DOM/占位和 resize 一致性 |
| 打包 | BUILD_INFO 指向验收提交，新输出不覆盖 data/旧产物，真实冻结 WebView/桥/库/截图/Overlay；用户试用后再决定合并发布 |

本次评审没有真实 LCP/CLS/INP、万条长库、屏幕阅读器、真实网络取消或多显示器成绩；测试预算不写成通过。源码/打包操作遵循 [DEV_RULES.md](DEV_RULES.md) 和 [PACKAGING.md](PACKAGING.md)。

## 五、假设与待确认

### 讨论事项

以下均为 `pending`，用户目前只要求保存文档，未选择实施方案。

| 编号 | 待讨论事项 | 建议起点 | 状态 |
|---|---|---|---|
| UI-D01 | 第一批实施范围与负责人 | 先讨论异步目标、最小窗口、结果反馈、模态键盘四项；与现有修复负责人对齐 | pending |
| UI-D02 | 卡片标题与固定尺寸 | 标题常显两行，开发商次行，联动虚拟列表高度；是否所有封面卡都常显待定 | pending |
| UI-D03 | 配色约束 | 保留品牌粉色，功能文本/主操作可深色化；是否需要高对比度模式待定 | pending |
| UI-D04 | 窗口与设备边界 | 桌面最小 900×620；DPI、1366 物理屏幕、触控需求需确认 | pending |
| UI-D05 | 取消响应目标 | 即时 UI 确认与实际后台终止分开，150ms 仅建议 UI 目标；在途请求时限需实测 | pending |
| UI-D06 | 自动元数据匹配的多源范围 | 当前自动 VNDB、手动混合并存；是否接入多源、优先级/回退/合并规则另定 | pending |
| UI-D07 | 设置保存模型 | 主题即时保存、其他项点击保存是否保留差异；说明必须与行为一致 | pending |
| UI-D08 | 国际化、访问性、兼容与遥测 | 最低 WebView2、目标读屏、i18n/RTL、外部匿名遥测是否需要逐项确认 | pending |

UI-D01～08 的建议不构成已确认约束。Beta 与实验产品线保持独立，实验字幕/AI 设置页需要单独矩阵，不能根据本原版评审认定已评估。

### 已测事实与证据边界

| 检查 | 本次评审结果 | 边界 |
|---|---|---|
| 900×620 布局 | 搜索右边 729px、按钮区左边约 721.5px；批量栏宽约 869.3px、右边约 954.7px；主区宽 760px | 仅该 fixture/视口/DPI，不代表全尺寸测完 |
| 模态焦点 | 设置打开后焦点仍在后台 searchInput，未启用背景 inert | 未进行真实屏幕阅读器验收 |
| 详情乱序 | A 700ms、B 30ms，最终 currentGame=fixture-0、标题=Audit Game 0 | 受控延迟，不声称真实用户误操作已发生 |
| 关闭分发 | closeTopSheet 调用后 confirmVisible=true、detailVisible=false | 验证共享关闭函数，不代表所有系统键盘事件均测试 |
| 表单错误 | fExeRow 错误提示约 129×52px，位于输入行右侧；无 aria-invalid/describedby | 本次未注入真实磁盘失败 |
| 列表窗口化 | 80 条数据在两视口分别只渲染 20/30 张卡片 | 未测 1000/10000 条性能 |
| 对比度 | 副文本/白底 2.96:1、浅说明/白底 1.82:1、粉色主操作白字 1.68～2.15:1 | CSS 计算，透明/opacity/渐变合成还需像素复测 |

探针 `ui_audit_probe.py` 及 `ui-audit-900x620.json/png`、`ui-audit-1366x768.json/png` 的原始文件保留在本机临时评审目录，仅含 fixture 数据；关键测量已写入上表，后续讨论不依赖临时文件存在。修复 agent 若基线变化，应重跑对应路径并更新证据，不能仅凭旧评审或提交说明宣布完成。

### 与其他文档的关系

- [TRIAL_FEEDBACK_20261007.md](TRIAL_FEEDBACK_20261007.md) 保存原用户三项反馈的报告基线；`36c17dc` 是后续代码修复，两者时间状态需区分，验收与归档更新由修复负责人处理。
- [DEVELOPMENT_BACKLOG.md](DEVELOPMENT_BACKLOG.md) 继续作为项目主待办，本讨论草案的建议未自动转为已授权任务。
- 工作区另有独立的 `COVER_DOWNLOAD_OPTIMIZATION.md` 草案，由其他任务维护；其中的封面耗时和网络结论不属于本次 UI 评审实测，也未作为本讨论的验收证据。
- [UI_REDESIGN_PLAN.md](UI_REDESIGN_PLAN.md) 为历史改造记录，本次新评审不覆盖它；讨论定板后再决定是否形成新实施计划。

下一次讨论可先定 UI-D01 与 UI-D03，再确定每批范围、验收指标和新包版本；本次只保存评审结果。
