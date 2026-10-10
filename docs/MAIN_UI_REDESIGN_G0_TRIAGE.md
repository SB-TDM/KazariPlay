# KazariPlay 主界面改造 G0 分诊记录

> 日期：2026-10-10。实施工作区：`E:\文件夹\Launcher\KazariPlay_main-ui`（独立克隆），分支 `feature/main-ui-redesign`。
> 基线提交：`e70d018`（其上是 `6388bca` 计划修订、`57ff38f` 初始计划与快照）。工作树干净，前端已 `npm ci` + `build`。
> 关联：[MAIN_UI_REDESIGN_PLAN.md](MAIN_UI_REDESIGN_PLAN.md) §4、§8。方法：静态源码走查（`file:line`）+ 既有 2026-10-07 测量；未运行真实 GUI 复现的条目已注明。

## 1. 基线门禁结果

| 命令 | 结果 | 备注 |
|---|---|---|
| `npm --prefix kazari_play/ui/web_assets run typecheck` | PASS | |
| `npm --prefix kazari_play/ui/web_assets run build` | PASS | 生成 `js/`（克隆里原本缺失） |
| `python tests/verify_frontend.py` | PASS | 14 脚本块 / 153 id / 132 行交叉校验 |
| `python tests/test_classic_boundary.py` | PASS | 4 项 |
| `node tests/test_p1_frontend.cjs` | FAIL（既有） | `makeCheckAll is not defined`；见 §4 |

## 2. 复验矩阵（§4 待复验决定项）

结论取值：**仍存在** / **已修** / **部分** / **未验证**。证据行号基于基线提交。

| 编号 | 条目 | 结论 | 证据（file:line） | 说明 |
|---|---|---|---|---|
| C03 | 批量栏小窗口越界 | **仍存在** | `css/widgets.css:23-27,31-33`（`.batchbar` 无 `max-width`/`flex-wrap`，按钮 `white-space:nowrap`）；`index.html:72-81`（8 个展开按钮，无折叠）；最小窗口 `kazari_play/main.py:265` 900×620，主区=窗口−`--sidebar-w:140px` | 2026-10-07 实测 869.3px > 主区 760px。改造后侧栏改 72px 可增宽至约 828px，估计仍溢出。未重跑 GUI |
| C04 | 有效文本/主按钮对比度 | **仍存在** | `css/variables.css:8-10`（`--text-sub:#9c92a8` 等未变）；2026-10-07 计算：副文本/白底 2.96:1、浅说明/白底 1.82:1、粉底白字 1.68～2.15:1 | 承接项（非可选）。样式未变，数值仍适用；像素级合成未复测 |
| C08 | 详情 A慢/B快 乱序 | **仍存在** | `ts/detail.ts:23-33`（回调仅校验 payload，第 27 行无条件写 `App.data.currentGame`）；`ts/core.ts:63-70`（`loadCoverTo` 无 gid/序号校验） | 无请求序号/代际。参考 `ts/screenshots.ts:26,37` 的 request+gid 保护 |
| C09 | 候选搜索/收藏夹管理迟到响应 | **仍存在** | `ts/form.ts:263-272`（第 270 行无条件 `renderCandidates`）；`ts/collections.ts:166-181`（第 173 行无条件覆盖，第 178 行按 stale 目标渲染） | 同缺序号/gid 校验；`screenshots.ts`、`batch.ts:62,74,86` 已有可复用模式 |
| C10 | 启动/刷新/保存/复制假成功 | **仍存在** | 刷新 `ts/app.ts:109`；`ts/core.ts:44-47`（`launch` 无回调、忽略 ok）；`ts/settings.ts:128,132,134` 无回调即 `:137` 提示；`ts/screenshots.ts:182-183`；`ts/form.ts:241-242` | 后端 `launch`/`copyScreenshotToClipboard`/`updateScreenshotHotkey` 已返回 bool 或 ok，可接；`applyCandidate`/`saveConfigs` 无返回需契约 |
| C11 | 取消/任务阶段 | **部分** | `36c17dc` 全部保留：`css/widgets.css:51` z-index=90、`ts/batch.ts:276` 正在取消、`utils/vndb_client.py:66-95` cancel_event 链路 | 仍无 TaskProgress 状态机；`ts/batch.ts:68,83,140` 在关闭/新建/扫描进度推送时重置取消按钮（扫描反馈会被覆盖）；在途 HTTP 不可中断（`vndb_client.py:154-164` 分块读不查取消） |
| C13 | 表单错误独立行/aria、设置标签/tab | **仍存在** | `css/form.css:10,42`（父 `.form-row` 为 nowrap flex，`flex-basis:100%` 无法换行）；`ts/form.ts:70-81`（无 `aria-invalid`/`aria-describedby`）；`partials/settings.html:10-17,22-24`（label 用 `div`，tab 无 `role`/`aria-selected`/方向键，`ts/settings.ts:180-190` 仅 click） | 未做浏览器实测；nowrap 下不换行由标准 Flexbox 行为确定 |
| C16 | 主题保存语义、截图预览反色 | **仍存在** | 文案/行为不一致：`partials/settings.html:44`“保存后生效” vs `ts/settings.ts:100-107` 点击即 `bridge.setTheme`（`ui/web_bridge.py:388-392` 即时写盘）；预览 `css/screenshots.css:21-32` 固定深色面 `rgba(20,16,26,.92)` 仍用 `var(--text/--text-sub/--border-soft)`，无 inverse token | 亮色主题下深色面 + 深色字，对比不足；全仓无 `inverse` token |
| UI-D05 | 取消响应时限 | **未验证** | `utils/vndb_client.py:42,45`（API 15s / 封面 90s），`154-164` 分块读不查取消 | 需真实环境测在途结束时限 |
| UI-D07 | 设置保存模型 | **仍存在（不一致）** | 同 C16 主题文案 | 主题即时保存，其余设置点“保存”生效；说明需与行为对齐 |

## 3. 与主工作区未提交改动的关系

主工作区 5 个未提交文件实现的是“**扫描前提示**”独立功能，与上述条目无重叠，也不修复其中任何一项：
- `ts/app.ts`（`startScan()` + 读 `scan_hint_dismissed`）、`ts/ui.ts`（confirm 增加可选复选框）、`partials/common.html`（`#confirmCheckRow`）、`css/form.css`（`#confirmCheckRow` 样式）、`utils/config.py`（`scan_hint_dismissed` 默认值）。
- 该功能触及 `app.ts`/`ui.ts`/`form.css`（S1/S2 实施文件），故必须在隔离工作区实施，且不混入本轮提交。

## 4. 基线异常

- `node tests/test_p1_frontend.cjs`：`makeCheckAll is not defined`。`ts/batch.ts:238-239` 依赖 `core.ts` 的 `makeCheckAll`，但该测试（`tests/test_p1_frontend.cjs:26,59`）只加载 `screenshots.js`、`batch.js`，未加载 `core.js`。**克隆与主工作区同样失败，非本轮引入。**
- 处置待定：a) 让测试补载 `core.js`；b) 标记该测试陈旧、本轮不依赖。需与维护者确认后再决定，不计入本轮回退。

## 5. 处置建议（待确认）

| 编号 | 建议 | 理由 |
|---|---|---|
| C03 | 本轮随主界面改造一并修（局部限宽/折行） | 位于主窗口，改造会改动工具栏尺寸；修复小且局部 |
| C04 | 本轮承接，用主界面局部 token 调整，不全局换色 | 计划 §4 定为承接项；改动限定作用域 |
| C08/C09 | 本轮修（复用现有 request+gid 模式） | 小改、低风险、高收益；不涉及受保护文件 |
| C10 | 本轮修已具返回契约者（launch/refresh/copy）；`applyCandidate`/`saveConfigs` 契约待批 | 避免新增后端 API |
| C11 | 本轮做最小修（取消中不重置按钮）；TaskProgress 状态机延期 | 避免新增通用模型 |
| C13/C16 | 视范围决定：文案/预览反色可小改；表单错误换行+aria、设置 tab 语义较大 | 可能超出主界面改造范围 |
| UI-D05 | 单独实测 | 需真实环境 |

> 本记录为 G0 交付，未改动任何生产代码，未提交 `ts/`、`css/`、Python 或 Overlay。

## 6. 实施进展（2026-10-10 更新）

| 编号 | 状态 | 提交 |
|---|---|---|
| C03 批量栏越界 | 已修（限宽 + 折行；渲染验证留 S4） | `f87af8a` |
| C04 对比度 | 正文 `--text-sub` 加深；白字控件改用 `--action-bg`/`--action-mint-bg`（装饰保留浅粉）。像素级复测与 `--text-disabled` 误用清理留 S4 | `aefe893`、`c9d357b` |
| C08/C09 异步迟到 | 已修（request+gid 代际校验）；陈旧测试修复 + 新增 ordering 测试 | `6d2b191` |
| C10 真实结果反馈 | 已修可用契约部分（launch/openFolder/copy/refresh）；`applyCandidate`/`saveConfigs` 无返回契约，仍待批 | `60e2742` |
| C11 取消/任务阶段 | 最小修（取消等待锁定）；TaskProgress 状态机延期 | `64da3a7` |
| C13 表单/设置 a11y | 部分：表单错误换行 + `aria-invalid`/`aria-describedby`、设置 tab `role`/`aria-selected`/方向键。设置字段 `<div class="label">` 转 `<label for>` 留待办 | `8c60c32` |
| C16 主题/预览 | 已修（主题文案、截图预览反色 token） | `8c60c32` |

仍未做：S1–S3 主界面实施、S4 完整回归（真实 GUI/DPI/像素对比度）。
