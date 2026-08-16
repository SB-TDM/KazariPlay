# KazariPlay UI 改造计划书

> 版本：V1.0（计划稿）
> 日期：2026-08-16
> 依据：`docs/UI_REVIEW_CONTROL_PANEL_HANDOVER.md` 之后的 UI 产品评审结论（问题清单见 §1）
> 范围：纯前端改造（web_assets/ + web_bridge.py 少量接口），不涉及 C++ overlay 渲染逻辑
> 原则：小步可验证，每阶段独立可交付、可回退

---

## 1. 问题清单（评审结论摘要）

| 编号 | 问题 | 严重度 | 位置 |
|---|---|---|---|
| P0-1 | 设置页「翻译」tab 职责过载（7 类设置 + 30+ 字幕样式控件挤在一个 tab） | 高 | `settings.html` / `settings.js` |
| P0-2 | 生效模型混乱：同一设置页混用「保存生效 / 实时生效 / change 即生效 / 跳详情页生效」四种 | 高 | `settings.js` |
| P0-3 | 批量操作（尤其 VNDB 批量匹配）零进度反馈，用户面对数分钟静默 | 高 | `batch.js` + `web_bridge.py` |
| P0-4 | 卡片拖拽排序无位移阈值，点击误触拖拽 | 高 | `games.js` `bindCardDrag` |
| P1-5 | 12 个 JS 模块全局作用域共享，跨模块隐式耦合，改一处崩三处 | 中 | `_JS_MANIFEST` 全部 |
| P1-6 | 设置页 tab 无记忆，每次打开回「常规」 | 中 | `settings.js open()` |
| P1-7 | 热键设置无冲突检测 | 中 | `settings.js bindHotkey` |
| P1-8 | 详情页翻译卡打断「元数据→简介」阅读流 | 中 | `detail.html` |
| P2-9 | 空状态文案分裂（「扫描文件夹」vs「批量扫描文件夹导入」） | 低 | `index.html` / `games.js` |
| P2-10 | 搜索无纠错/无空结果建议 | 低 | `games.js filterGames` |

> 交互细节（role=menu 无键盘导航、emoji 图标、z-index 隐式契约等）作为工程纪律项并入各阶段。

---

## 2. 目标与非目标

### 目标
1. 让设置页**每个 tab 一种生效模型**，用户可预测。
2. 让批量/耗时长操作**有明确进度反馈**。
3. 消除核心操作的**误触**与**发现性差**问题。
4. 分步收敛全局作用域，**降低新增功能的事故概率**。

### 非目标（本计划不做）
- 不做 C++ overlay 渲染层改造（D2D 管线、模糊等）。
- 不做完整主题重设计（保留 Kawaii 视觉语言）。
- 不迁移 ES Module / 构建工具链（见 §8 风险，列为后续单独计划）。

---

## 3. 阶段规划总览

| 阶段 | 内容 | 交付物 | 预计改动量 |
|---|---|---|---|
| **阶段 A（P0）** | 设置页拆分 + 生效模型统一 | 可用的设置页 | 中 |
| **阶段 B（P0）** | 批量操作进度反馈 | 可见的进度条/计数 | 小 |
| **阶段 C（P0）** | 卡片拖拽位移阈值 + 点击/拖拽判定 | 无感误触修复 | 小 |
| **阶段 D（P1）** | 模块命名空间化（state 收敛先行） | 架构债开始偿还 | 中 |
| **阶段 E（P1）** | 设置页 tab 记忆 + 热键冲突检测 | 体验收尾 | 小 |
| **阶段 F（P1）** | 详情页阅读流重排（翻译卡折叠） | 阅读体验 | 小 |
| **阶段 G（P2）** | 空状态文案统一 + 搜索空结果建议 | 文案一致性 | 小 |

> 阶段 A→C 为第一交付批次（高价值低风险）；D→G 为第二批次。每阶段独立可回退。

---

## 4. 阶段 A：设置页拆分 + 生效模型统一

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 现状
- `settings.html` 的 `set-translate` 页 = AI 配置（base_url/key/model）+ 语言方向 + 文本编码 + 显示字幕开关 + host 目录 + 清洗说明 + AI 兜底清洗 + 字幕样式区（预设/背景/文字/位置/快捷操作）。
- 生效模型：AI 配置保存生效；字幕滑块 150ms 实时；显示字幕 change 即实时；清洗跳详情页。

### 方案
1. **导航拆分为 8 个 tab**（原 7 个 → 拆出「字幕」）：
   - 常规 / 主题 / 快捷键 / 伪装 / 元数据 / **翻译** / **字幕** / 关于
2. **重新划分内容**：
   - 「翻译」tab：仅 AI 配置、源/目标语言、文本编码、host 目录、清洗说明、AI 兜底清洗 → **统一为「保存后生效」**。
   - 「字幕」tab：显示字幕开关、字幕样式全量控件（预设/背景/文字/位置/快捷操作）→ **统一为「实时生效，无需保存」**，页面顶部加说明条。
3. **保存按钮逻辑**：
   - 字幕 tab 改动**不写 `subtitle` 键**（实时路径已持久化），`save()` 仅处理其它 tab。
   - 「显示字幕」开关移入字幕 tab，change 即实时下发（保持现有 `setSubtitleEnabled` 链路）。
4. **取消/恢复默认语义修正**：
   - 取消：仅回滚「保存生效」的改动；字幕 tab 已实时应用的值不回滚（标注说明）。
   - 恢复默认：恢复默认配置后，字幕 tab 控件重新从 config 拉取（复用 `SubtitleStyle.load()`）。

### 涉及文件
- `partials/settings.html`（拆 `set-translate` 为 `set-translate` + `set-subtitle`，新增 nav-item）
- `js/settings.js`（`open()`/`loadConfig()`/`save()`/导航切换；`subLoadConfig` 改由字幕 tab 激活时加载）
- `css/style.css`（如需 subtitle 区说明条样式，复用 `.sub-sec`）

### 验收标准
- [x] 设置页出现独立「字幕」tab，翻译 tab 不再含样式控件。
- [x] 翻译 tab 改动保存后生效；字幕 tab 滑块改动即时在游戏中生效（无需点保存）。
- [x] 取消设置不丢失字幕 tab 已应用的样式。
- [x] `verify_frontend` PASS（id/引用一致）。

---

## 5. 阶段 B：批量操作进度反馈

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 现状
- `btnBVndb` 点击 → toast「开始批量匹配 VNDB」→ 无后续。
- 后端 `web_bridge.py` 已有 `_vndb_counter` 节流计数（进度数据存在，未暴露）。

### 方案
1. 后端新增桥方法 `getBatchProgress()` 返回 `{total, done, failed, running}`：
   - 批量操作开始时在 bridge 记录任务上下文（类型 + total）。
   - 每完成一条更新 `done`（VNDB 匹配/收藏夹移动/删除共用计数结构）。
2. 前端批量操作触发后：
   - 显示一个**进度胶囊/进度条**（右下角，复用 toast 位置或新增 `.progress`），文案如「批量匹配中 3/12…」。
   - 每 800ms 轮询 `getBatchProgress()`，完成时 toast「批量完成（成功 11 / 失败 1）」。
   - 手动关闭按钮 + 自动超时隐藏。
3. 删除、移动等短操作复用同一组件（秒级完成时进度条一闪即过或仅 toast）。

### 涉及文件
- `ui/web_bridge.py`（批量任务上下文 + `getBatchProgress`）
- `js/batch.js`（触发进度组件）
- `js/core.js` 或 `js/ui.js`（进度组件 DOM/样式）
- `css/style.css`（`.progress` 样式）

### 验收标准
- [x] 批量 VNDB 匹配 ≥3 个游戏时显示进度条且计数递增。
- [x] 完成后显示成功/失败汇总 toast。
- [x] 进度组件不遮挡主操作区，可手动关闭。

---

## 6. 阶段 C：卡片拖拽位移阈值

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 现状
- `bindCardDrag`：`card.draggable=true` 后 `dragstart` 立即生效，点击与拖拽无区分。

### 方案
1. 弃用 HTML5 drag & drop（`draggable` 无位移判定），改用 **mousedown/mousemove/mouseup 自实现拖拽**：
   - `mousedown` 记录起点；`mousemove` 位移超过 **6px** 才进入拖拽态（设置卡片浮动样式 + `dragFromId`）。
   - 小于阈值松开 = 单击 → `openDetail`。
   - 拖拽中 `mouseover` 判定落点、`mouseup` 落定 + 持久化（复用现有 `reorderCards`）。
2. 保留键盘可达（Enter 打开详情）。
3. 拖拽态视觉沿用现有 `.dragging` 样式。

> 备选：若实现量超预期，退化为「长按 300ms 进入拖拽」方案，但仍需位移阈值。

### 涉及文件
- `js/games.js`（重写 `bindCardDrag`/`markDragOver`/`reorderCards` 调用链）
- `css/style.css`（`.dragging` 复用）

### 验收标准
- [x] 收藏夹视图点击卡片稳定打开详情，3-5px 抖动不触发拖拽。
- [x] 拖拽排序、持久化行为与改造前一致。
- [x] 非收藏夹视图/批量模式仍禁止拖拽。

---

## 7. 阶段 D：模块命名空间化（state 收敛先行）

> **状态：✅ 全部完成（2026-08-16，V1.3）——第一步数据收敛 + 第二步按功能域拆分**

### 现状
- `state.js` 顶层 `let GAMES / currentGame / editingId / runningId / state` 全全局共享。
- 各模块直接读写，隐式耦合。

### 方案（分两步，本阶段只做第一步）
**第一步（本阶段）——命名空间收敛**：
1. 引入 `window.App = {}`（在 `state.js` 定义）承载**数据**：
   - `App.state`（原 `state`）、`App.games`（原 `GAMES`）、`App.currentGame`、`App.runningId`、`App.editingId`。
   - 提供 `App.getGames()/setGames()` 访问器（后续可加变更通知）。
2. 各模块 `GAMES→App.games`、`state.xxx→App.state.xxx` 机械替换（用脚本批量替换 + 逐文件人工核对）。
3. 保留 `window.__app` 后端注入入口（对外 API 不变）。
4. 函数（`renderAll`/`openDetail` 等）暂不动，仅数据收敛——**先止血，再治本**。

**第二步（已完成）——按功能域拆分**：
- `App.data`：业务数据（`games` / `currentGame` / `editingId` / `runningId`）
- `App.ui.state`：UI 状态（导航/搜索/排序/批量/收藏夹筛选，10 字段）
- `bridge` 保持全局（core.js 定义，index.html 内联 onclick 直接引用，非共享数据状态）
- 脚本处理模板字符串 `${...}` 插值区；引用完整性静态验证（`App.data` 4 字段 / `App.ui.state` 10 字段定义与引用全匹配）

**第三步（未开始，可选）**：按功能域继续深化（如收编 bridge 到 `App.bridge`、函数/组件化拆分），或评估 esbuild 单文件构建迁移（见 §12 风险）。

### 涉及文件
- `js/state.js`（新增 `window.App`）
- 全部 11 个 JS 模块（机械替换 + 核对）
- `tests/verify_frontend.py` 同步（若检查顶层声明）

### 验收标准
- [x] 全局顶层仅剩 `App` / `bridge` / `window.__app` / 各模块对外函数。
- [x] `smoke_translation` / `smoke_control_panel` / 前端 verify 全 PASS。
- [x] GUI 启动 + 打开详情 + 收藏夹操作正常。

---

## 8. 阶段 E：设置页 tab 记忆 + 热键冲突检测

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 方案
1. **tab 记忆**：`open()` 时读取 `localStorage['settings_tab']` 恢复上次 tab；切换时写入（复用现有 nav 切换代码）。
2. **热键冲突检测**：
   - `bindHotkey` 捕获组合键后，与其它三个热键 + 系统保留键（`Ctrl+Alt+Del` 等）比对，冲突则红字提示「与 xx 冲突」并禁止保存。
   - 后端无需改（纯前端校验；保存时后端仅做最终写入）。

### 涉及文件
- `js/settings.js`

### 验收标准
- [x] 关闭重开设置页停留在上次 tab。
- [x] 设置冲突热键被拒绝并给出冲突项提示。

---

## 9. 阶段 F：详情页阅读流重排

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 现状
- `detail.html` 顺序：翻译卡片 → 收藏夹 chips → 简介 → 截图。翻译卡打断阅读流。

### 方案
1. 顺序调整为：**元数据信息栏 → 简介 → 收藏夹 chips → 截图**。
2. 翻译卡移到「简介之后、截图之前」，默认折叠为一行摘要（「实时翻译」+ 开关），点击展开 Hook/清洗配置。
3. 若游戏未启用翻译或非 galgame 引擎，整卡隐藏（保持现状的 `style.display` 逻辑）。

### 涉及文件
- `partials/detail.html`（顺序 + 折叠结构）
- `js/detail.js`（`renderTransRow` 折叠逻辑）

### 验收标准
- [x] 详情页阅读顺序符合「元数据→简介→收藏→截图」。
- [x] 翻译功能仍可一键展开操作，功能无损。

---

## 10. 阶段 G：空状态文案统一 + 搜索空结果建议

> **状态：✅ 已完成（2026-08-16，V1.3）**

### 方案
1. 空库主按钮统一为「扫描游戏文件夹」（`index.html` + `games.js renderEmpty` 两处同步）。
2. 搜索无结果时，在空状态追加「检查关键词拼写 / 试试开发商名 / 清除筛选」建议行（复用 `renderEmpty` 的 filterEmpty 分支）。

### 涉及文件
- `index.html` / `js/games.js`

### 验收标准
- [x] 全项目仅出现一种「扫描」入口文案。
- [x] 搜索空结果给出可操作建议。

---

## 11. 验证与回归策略

每个阶段完成即跑：
```bash
# 前端完整性（id/JS 引用一致性，本计划最重要的护栏）
python tests/verify_frontend.py
# 语法
python -m py_compile kazari_play/ui/web_bridge.py kazari_play/main.py
node --check kazari_play/ui/web_assets/js/<改动文件>.js
# 回归
python tests/smoke_translation.py
python tests/smoke_control_panel.py
# GUI 启动冒烟
python kazari_play/main.py   # 手动检查受影响页面
```

改动集成分批提交，每批 commit 独立可回退。

---

## 12. 风险与约束

| 风险 | 影响 | 缓解 |
|---|---|---|
| 阶段 D 全局替换引入跨模块行为差异 | 高 | 逐文件小步提交；每个文件替换后跑 verify + GUI 冒烟；先加访问器再替换 |
| 阶段 A 拆 tab 时字幕实时逻辑误伤 | 中 | 字幕 tab 复用现有 `subLoadConfig`/`subPush`，不重写链路 |
| 阶段 C 自实现拖拽破坏收藏夹排序 | 中 | 保留 `reorderCards`/持久化不动，仅替换触发层；备选长按方案兜底 |
| 阶段 B 进度轮询与后端任务生命周期耦合 | 中 | 进度上下文独立于桥实例，超时自动清空 |
| 前端无构建工具（html= 内联模式） | 长期 | 阶段 D 第二步再评估 esbuild 单文件构建（本计划不含） |

---

## 13. 批次划分与建议排期

| 批次 | 阶段 | 建议顺序 | 相对工作量 |
|---|---|---|---|
| 批次一 | A → C → B | 先拆设置（影响面最大，尽早） | 中 |
| 批次二 | E → F → G | 体验收尾 | 小 |
| 批次三 | D | 架构债（独立、谨慎，可与批次二并行） | 中 |

> 若人力有限，最低可行交付 = 批次一（A/B/C 三项），即评审中「只改三件事」的完整落地。
