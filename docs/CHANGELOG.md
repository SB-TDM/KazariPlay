# 变更日志（CHANGELOG）

> 记录 KazariPlay 的开发改动。按功能块组织，最新在前。

---

## V1.3 UI 优化（刷新瘦身补充：清洗配置勾选不刷新）

日期：2026-08-16

- **`setCleanFilterConfig` 移除 `self.refresh()`**：详情页勾选清洗过滤器时不再触发全量网格重建。勾选状态前端已本地维护，卡片不展示清洗配置，刷新无可见收益（与「实时翻译开关」同批瘦身）。
- 验证：`py_compile`、`smoke_translation` ALL PASS、GUI 启动无异常。

---

## V1.3 字幕功能：可开关源语言字幕

日期：2026-08-16

- **新增「显示源语言字幕」开关**（设置页 → 字幕 → 文字样式区）：关闭后字幕仅显示译文行，不再显示日文/英文原文行。
- C++：`SubtitleStyle` 新增 `show_source` 字段（默认 true）+ JSON 解析；`contentHeight()` 与 `render()` 在关闭时只渲染译文行（底板高度/宽度按单行计算）。
- 前端：字幕 tab 新增 `setSubShowSource` 复选框（实时下发）；三个内置预设补 `show_source: True`。
- 验证：双版本重编译；`show_source:false` 下发冒烟确认字幕窗口高度 = 单行（2560x60，原两行为 87px）；`verify_frontend`（219 id / 188 引用）、`smoke_control_panel`、`smoke_translation` 全 PASS；GUI 启动无异常。

---

## V1.3 UI 优化（用户反馈第二、三批：刷新瘦身 + 拖拽跟手）

日期：2026-08-16

### 第二批：不必要的刷新瘦身
- **实时翻译开关**：`toggleGameTranslation` 移除 `self.refresh()`（开关不影响卡片网格展示，前端已本地同步详情开关态，刷新无可见收益）。
- **收藏夹选择**：`selectCollection` 合并重复的 `renderAll()`（原立即渲染 + 回调渲染两次全量重建 → 仅回调渲染一次，order 即到）。
- **批量选择按钮**：进入/退出批量模式改为仅切换 `body.batch` 类（CSS 控制勾选框显隐）+ 局部同步卡片 `selected` 类，不再全量重建网格。
- **全选/取消全选**：`btnSelAll` 改为局部同步全部卡片选中态，不再 `renderAll()`。

### 第三批：卡片拖拽跟手效果
- 拖拽中源卡片**跟随鼠标移动**（记录按下点偏移，mousemove 实时 `transform:translate`），原布局占位保留。
- `.dragging` 样式增强：z-index 置顶 + 轻微放大 + 强阴影 + 半透明，营造"拿起来"实体感（禁 transition 避免拖拽滞后）。
- 落点新增**插入线**提示（`drag-over::after` 粉色条），比单纯边框高亮更明确插入位置。

### 验证
- `node --check`（games/batch/collections）、`verify_frontend`（218 id / 188 引用全匹配）、`smoke_translation`、`smoke_control_panel` 全 PASS；GUI 启动无异常。

---

## V1.3 UI 优化（用户反馈第一批：侧边栏高亮互斥 / 排序文案 / 字幕预览隐藏）

日期：2026-08-16

- **侧边栏高亮互斥**：`selectCollection` 选择收藏夹时清除「全部作品 / 继续游玩 / 我的收藏」等 `.side-item` 高亮，只保留当前项粉色胶囊（与 `clearCollectionFilter` 对称）。
- **排序按钮文案**：导航栏「筛选 ▾」→「排序 ▾」（下拉实际是排序功能，消除误导）。
- **字幕预览生命周期**：离开字幕 tab 或关闭设置页时调用 `hideSubtitle()`，预览字幕不再残留屏幕。
- 验证：`node --check`（settings/collections）、`verify_frontend`（218 id / 188 引用全匹配）、GUI 启动无异常。

---

## V1.3 UI 改造（阶段 D 第二步：App 命名空间按功能域拆分）

日期：2026-08-16

- **`window.App` 按功能域拆分**（`state.js`）：
  - `App.data`：业务数据（`games` / `currentGame` / `editingId` / `runningId`）
  - `App.ui.state`：UI 状态（导航 / 搜索 / 排序 / 批量 / 收藏夹筛选，10 字段）
  - `bridge` 保持全局（core.js 定义，index.html 内联 onclick 直接引用，不属于共享数据状态）
- 12 个模块引用更新：`App.games→App.data.games` 等 4 项 + `App.state→App.ui.state`；脚本处理模板字符串 `${...}` 插值区（静态文本不受影响）。
- 引用完整性验证：`App.data` 4 字段 / `App.ui.state` 10 字段定义与引用全部匹配，无缺失。
- 依据 `docs/UI_REDESIGN_PLAN.md` 阶段 D 第二步；第一步（数据收敛到 App）已完成。
- 验证：13 个 JS `node --check` 全 PASS；`verify_frontend`（218 id / 188 引用）、`smoke_translation`、`smoke_control_panel` 全 PASS；GUI 启动无异常。

---

## V1.3 UI 改造（阶段 D：模块命名空间化）

日期：2026-08-16

- **全局数据收敛到 `window.App` 命名空间**（`state.js` 定义）：`games`（原 `GAMES`）/ `currentGame` / `editingId` / `runningId` / `state`（UI 状态）。各模块不再依赖顶层 `let/const` 跨脚本共享，改为统一经 `App.xxx` 读写，消除跨模块隐式耦合。
- 用脚本对 12 个 JS 模块做代码级整词替换（跳过注释/字符串/模板字符串），并手动修正模板字符串内插值漏替换处（`batch.js`/`collections.js`/`detail.js`/`games.js`）。
- 数据对象字段无缺失（静态分析：所有 `App.xxx` 引用均可在定义中找到，`App.state.xxx` 均在 state 字段内）。
- 依据 `docs/UI_REDESIGN_PLAN.md` 阶段 D（第一步：数据收敛；第二步按功能域拆命名空间留待后续）。
- 验证：13 个 JS 文件 `node --check` 全 PASS；`verify_frontend`（218 id / 188 引用全匹配）、`smoke_translation`、`smoke_control_panel` 全 PASS；GUI 启动无异常。

---

## V1.3 UI 改造（批次二：E 设置页记忆/热键冲突 + F 详情阅读流 + G 空状态文案）

日期：2026-08-16

### 阶段 E：设置页体验收尾
- **tab 记忆**：关闭重开设置页停留在上次停留的 tab（`localStorage.settings_tab`）。
- **热键冲突检测**：捕获热键时与其它三个已配置热键比对，冲突则红字提示「冲突，请换一个」并拦截（不写入）。

### 阶段 F：详情页阅读流重排
- 顺序调整为 **信息栏 → 操作按钮 → 简介 → 收藏夹 → 翻译卡 → 截图**，翻译卡不再打断元数据→简介阅读流。
- **翻译卡默认折叠**：仅显示标题行 + 开关，点击展开 Hook/清洗配置；已配置 Hook 且启用翻译时自动展开。

### 阶段 G：空状态文案统一
- 扫描入口统一为「扫描游戏文件夹」（主按钮）/「批量扫描游戏文件夹」（FAB）。
- 搜索空结果给出可操作建议（「没有找到 xx——检查关键词拼写、试试开发商名，或清除搜索条件」）。

### 验证
- `verify_frontend`（218 id / 188 JS 引用全匹配）、`node --check`（settings/detail/games）、GUI 启动无异常。

---

## V1.3 UI 改造（阶段 C：卡片拖拽位移阈值）

日期：2026-08-16

- **卡片拖拽误触修复**：收藏夹视图卡片拖拽由 HTML5 drag & drop 改为 mousedown 自实现，按住移动超过 **6px** 才进入拖拽态；轻微抖动不再触发排序，点击正常打开详情。
- 实现：`mousedown` 记录起点 → 全局 `mousemove` 位移判定（`DRAG_THRESHOLD=6`）→ 超阈值才设 `dragFromId` 加 `dragging` 高亮 → 全局 `mouseup` 落点重排 + 清理。落点判定改用 `elementFromPoint`（原 `dragover` 不可靠）。
- 依据 `docs/UI_REDESIGN_PLAN.md` 阶段 C；阶段 A（设置页拆分）/ B（批量进度）已完成。
- 验证：`verify_frontend`（215 id / 185 JS 引用全匹配）、`node --check`、GUI 启动无异常。

---

## V1.3 UI 改造（阶段 B：批量操作进度反馈）

日期：2026-08-16

- **批量 VNDB 匹配进度条**：前端右下角进度胶囊（标题 + 百分比 + `已完成 x/y`），每 600ms 轮询后端；完成后自动收起（汇总 toast 由后端 notify 提供）。
- 后端新增 `getBatchProgress()` 桥方法 + `_batch_ctx` 批量任务上下文（total/done/running），`_vndb_progress` 回调更新计数，`_run_vndb_match` 结束时置 running=false。扫描后自动匹配同样计入进度（无前端轮询时静默）。
- 依据 `docs/UI_REDESIGN_PLAN.md` 阶段 B；阶段 A（设置页拆分）已在上一个改动完成。
- 验证：`verify_frontend`（215 id / 185 JS 引用全匹配）、`node --check`、`py_compile`、后端进度上下文单元验证（total=3/done=3/结束标志）PASS；GUI 启动无异常。

---

## V1.3 UI 改造（阶段 A：设置页拆分）

日期：2026-08-16

- **设置页新增独立「字幕」tab**：从原「翻译」tab 拆出（导航 7→8 个 tab）。「翻译」tab 仅保留 AI 配置 / 源目标语言 / 文本编码 / host 目录 / 清洗说明 / AI 兜底清洗（保存后生效）；「字幕」tab 收纳显示字幕开关 + 全量字幕样式控件（预设/背景/文字/位置/快捷操作）。
- **生效模型统一**：字幕 tab 顶部新增说明条「改动实时生效，无需点保存」；进入字幕 tab 时加载样式（`SubtitleStyle.load()`）；「显示字幕」开关 change 实时下发 C++ 并持久化。
- **保存逻辑修正**：`save()` 不再写 `subtitle` 键（字幕 tab 已走实时持久化路径），避免与实时链路重复。
- 依据 `docs/UI_REDESIGN_PLAN.md` 阶段 A；后续阶段 B（批量进度）/ C（拖拽阈值）等按计划书推进。
- 验证：`verify_frontend`（210 id / 180 JS 引用全匹配）、`node --check`、GUI 启动无异常。

---

## V1.2.4 字幕预设命名保存

日期：2026-08-16

- **保存命名预设**：设置页「字幕样式」新增「存为预设」输入框 + 「保存命名」按钮，把当前样式保存为自定义命名预设（`config.subtitle.presets[name]`，覆盖同名）。
- **动态预设列表**：预设下拉改为动态渲染（内置原作/极简/半透黑底 + 全部用户预设），保存/删除后即时刷新并选中。
- **删除预设**：选中下拉中的用户预设可删除（内置 3 套不可删）。
- 后端新增桥方法：`saveSubtitlePreset` / `deleteSubtitlePreset`；`getSubtitleStylePresets` 合并内置 + 用户预设。
- 验证：`verify_frontend`（209 id / 180 JS 引用全匹配）、`py_compile`、预设 CRUD 单元验证（保存/覆盖/删除/内置保护/空名拒绝）PASS；GUI 启动无异常。

---

## V1.2.3 字幕功能检查修复

日期：2026-08-16

- **修复 `saveConfigs` 覆盖 `subtitle.style`**：设置页保存时 `subtitle: {enabled}` 整体替换 `subtitle` 键，冲掉用户调好的字幕样式（`web_bridge.py saveConfigs` 对 dict 值改浅合并，保留未涉及的子键）。
- **修复「显示字幕」开关启动不生效**：C++ `subtitleEnabled` 初始 true，`start_hook_session` 从不携带全局开关 → 用户在设置页关闭字幕，下次启动游戏仍显示。现于会话启动后下发 `subtitle.enabled`（`subtitle_coordinator.py`）。
- **修复字幕拖拽剧烈抖动**（`subtitle_window.cpp`）：拖拽换算用 `WM_MOUSEMOVE` 的客户区坐标（相对窗口），窗口每帧移动后坐标反向变化，与 `m_dragWinX` 叠加成振荡。改用 `GetCursorPos` 屏幕坐标计算位移，与窗口位置完全解耦。模拟拖拽 30 步位移精确（300,100）、0 次回跳；双版本重编译。
- 验证：`py_compile` / `verify_frontend` / `smoke_translation` / `smoke_control_panel` ALL PASS；`saveConfigs` 合并、启动开关下发、拖拽稳定性单元验证 PASS；GUI 启动无异常。

---

## V1.2.2 字幕控制面板并入主设置页

日期：2026-08-16

### 架构调整：取消独立窗口，并入主 GUI

- **删除**独立「字幕控制面板」窗口：`main.py` 的 `_panel_html` / `_create_panel_window` 与 `control_panel.html` 移除，不再创建第二个 pywebview 窗口。
- **字幕样式控件并入设置窗口「翻译」tab**（`settings.html` + `settings.js`）：预设（原作/极简/半透黑底 + 保存/加载）、背景设置（模式/颜色/透明度/圆角/内边距/渐变/边框）、文字样式（字体/字号/字重/文字色/描边/阴影/对齐/行间距/最大宽度）、位置（水平/垂直/拖拽调整/底部避让）、快捷操作（预览/临时隐藏）。
- 控件改动沿用 150ms 防抖实时下发 + 值去重；样式适配浅/深双主题（`style.css` 新增 `.sub-sec` 区块）。
- **移除窗口专属功能**：折叠/记住位置/鼠标穿透（`setPanelClickThrough` / `panelCollapse` / `getPanelState` / `savePanelState` / `setPanelWindow` 删除）。
- **位置回传改转发主窗口**：`_ensure_subtitle_pos_handler` 经 `self._window.evaluate_js` 调 `window.updateSubtitlePos` 更新设置页滑块（仍写回 config）。
- **字幕总开关统一**：设置页「显示字幕」开关 change 时实时下发 C++（`set_subtitle_enabled`）并持久化 `subtitle.enabled`，替代原控制面板 enabled 复选框。
- 验证：`verify_frontend`（13 脚本 / 207 HTML id / 178 JS 引用全匹配）、`py_compile`、`smoke_control_panel`、`smoke_translation` ALL PASS；启动实测仅主窗口、桥接口集成与位置回传转发 PASS。

---

## V1.2.1 控制面板 Bug 修复

日期：2026-08-16

- **面板折叠高度钳制**：`main.py _create_panel_window` 补 `min_size=(330, 36)`。pywebview 默认 `min_size=(200, 100)` 会把折叠 `resize(330, 36)` 钳制到 330x100（实测偶发高度异常根因）；实测修复后折叠为 330x36。
- **多显示器拖拽换算**：`overlay/src/subtitle_window.cpp` 无游戏窗口时不再固定用主显示器（`MonitorFromPoint(0,0, MONITOR_DEFAULTTOPRIMARY)`），改为字幕窗口当前所在显示器（`MonitorFromWindow(..., MONITOR_DEFAULTTONEAREST)`）；`computeGeometry` 的屏幕钳制同步改为目标 rect 所在显示器，副屏拖拽百分比不再被钳到 1.0。双版本重编译。
- 验证：`verify_frontend` / `smoke_control_panel` / `smoke_translation` ALL PASS；面板折叠高度实测 330x36。

---

## V1.2 UI 审查修复 + 字幕控制面板

日期：2026-08-16

### 字幕控制面板（Overlay 控制面板，按《控制面板设计方案》）

- 新增 `overlay/src/subtitle_style.h`：`SubtitleStyle` 样式结构体 + JSON 解析（全字段值域裁剪）
- `SubtitleWindow` 渲染参数化：背景模式（自适应底板/通栏/无底板）、RGBA 颜色、圆角、内边距、垂直渐变、边框；字体/字号/字重、文字色、8 向描边、阴影、对齐、行间距、最大宽度；位置百分比 + 底部避让
- 新增拖拽定位：`set_subtitle_drag` 进入拖拽模式（去穿透 + 暂停跟随），松开回传 `subtitle_pos` 百分比并自动恢复
- `protocol.h` / `main.cpp`：新增 `set_subtitle_style` / `set_subtitle_drag` / `preview_subtitle` 命令与 `SubtitlePos` 回传
- `overlay_client.py`：`send_subtitle_style` / `send_subtitle_drag` / `send_preview_subtitle` + `on_subtitle_pos` 回调
- `web_bridge.py`：控制面板桥接口（样式读写 / 3 套预设 / 穿透 / 折叠 / 窗口状态 / 位置回传转发）
- `main.py`：第二个独立置顶窗口 `control_panel.html`（330x560，可折叠窄条，记住位置）
- 新增 `ui/web_assets/control_panel.html`：深色简约面板，滑块 150ms 防抖实时下发（含值去重），「预览字幕」无需游戏即可实时预览样式

### 前端审查修复（Web Interface Guidelines）

- 修复 `detail.js renderInfoBar` XSS（用户可编辑字段未转义）
- 焦点：全局 `outline:none` → `:focus-visible` 焦点环
- 语义化：窗口按钮/FAB/菜单项/侧边栏/主题卡片 → `<button>` + aria-label；表单 label `for` 关联；搜索/热键/开关 aria-label；卡片与收藏夹树键盘可达
- 动效：18 处 `transition:all` → 显式属性；新增 `prefers-reduced-motion`
- 主题：暗色补 `color-scheme:dark`；内容区恢复 `user-select:text`
- 表单校验改为内联错误 + 聚焦首个错误字段；搜索框 200ms 防抖
- Toast 置顶修复（`position:fixed` + `z-index:300`，弹窗打开时可见）；删除 `saveMetadataSources` 后端 notify 消除双 toast 覆盖
- CSS 重复清理（`.confirm-msg`/`.pill-btn.danger`/`.form-row`）

详细交接见 `docs/UI_REVIEW_CONTROL_PANEL_HANDOVER.md`。

---

## V1.1 Hook 实时翻译系统（开发中）

日期：2026-08-15

### 架构调整：方案A（翻译下沉 C++）

将 AI 翻译从 Python 移入 C++ overlay.exe 内部执行，链路变为：
`Hook 文本 → TextStabilizer(debounce) → 过滤器链(清洗) → C++ AI 翻译 → 字幕`

- 新增 `overlay/src/ai_translator.{h,cpp}`：WinHTTP 调用 OpenAI 兼容 API（默认 DeepSeek），异步队列翻译 + 同步测试翻译
- 字幕策略：**先显示原文，AI 翻译完成后替换为译文**；翻译失败保持原文
- `overlay_client.py`：移除 `send_subtitle`，新增 `send_test_translate` + `test_translate_result` 回调，`start_hook` 携带 AI 配置
- `subtitle_coordinator.py` 重写：只做会话控制与配置透传，翻译不再经过 Python
- 删除 `translate.py`（百度/DeepL 翻译模块）；`config.py` 只保留 AI 配置
- 前端设置页翻译 tab 只保留 AI 配置 + 测试翻译

### 对话文本捕获

- 恢复 `textractor_host.cpp` 的手动 `insertHook` 逻辑（自动 KiriKiriZ hook 只抓系统文本，手动 UserHook 才能抓对话）

### 字幕窗口跟随

- `SubtitleWindow` 新增 `setGamePid` / `findGameWindow`：按 PID 定位游戏主窗口
- `show()` 目标失效时回退到 `findGameWindow`；`updatePosition()` 跟随目标失效时持续重找，避免永久停在全屏回退位置

### Hook 点过滤

- `select_hook` 同时设置 handle（当前运行内可靠过滤）与 address（跨运行过滤）
- 当前运行内只按 handle 过滤；跨运行才用 address/function 过滤，且 function 为空时不误杀（修复 GDI hook 选定后无字幕）
- 二次启动（有 hook_code）恢复 address 过滤 + function 匹配

### overlay 进程生命周期

- 游戏关闭时 `stop()` 追加 `overlay.quit()`（overlay 随游戏退出，不再残留）
- `PipeServer` 新增 `onDisconnect` 回调：客户端（Python）断开 → overlay 自动退出，覆盖异常退出场景

### 文本清洗过滤器链（按《Hook文本清洗策略计划书》）

新增 `text_filter.h` / `filter_chain.{h,cpp}` / `engine_policy.{h,cpp}` / `cleanliness_checker.{h,cpp}` 及 13 个过滤器（`src/filters/`）：

| 过滤器 ID | 功能 |
|---|---|
| `dedup_chars` | 重复字符去重（自动分析重复周期，取众数） |
| `dedup_lines` | 整句重复去重（最小周期匹配，≥90% 才采用） |
| `dedup_mixed_lines` | 混合重复行去重（连续相同行压缩） |
| `incremental_dedup` | 递增拼接去重（逐字渲染的渐进累积文本 → 保留最后完整段） |
| `furigana` | 注音清理 `{漢字/かな}→漢字` |
| `html_tag` | HTML 标签清理 |
| `control_char` | ASCII 控制字符过滤 |
| `shift_jis` | 非 Shift-JIS 字符过滤（乱码；谨慎，默认仅未知引擎启用） |
| `english_symbol` | 英文标点过滤 |
| `quote_only` | 仅保留「」内容（会丢旁白，默认不启用） |
| `unicode_normalize` | 全角转半角 |
| `line_trimmer` | 行截取 |
| `regex_replace` | 用户自定义正则/字面量替换 |

- `text_stabilizer.cpp`：移除原 `DedupText`/`IsNoiseText`（只做 debounce），去重移入稳定回调后的过滤器链
- `main.cpp`：`start_hook` 按引擎选默认过滤器（`EnginePolicy`），稳定回调先清洗（空则丢弃）再翻译
- 引擎匹配改为大小写不敏感；krkr 策略含 `furigana + control_char + dedup_chars + incremental_dedup + dedup_lines`

### 前端清洗配置（每游戏）

- 协议新增 `update_filter_config` / `query_filter_config` / `filter_config_response`（C++ 动态重配过滤器链，空列表 = 恢复引擎默认）
- 设置页"文本清洗"区改为引导到游戏详情页
- 游戏详情页实时翻译卡新增"清洗配置"：13 个过滤器勾选 + 保存/恢复引擎默认，**每游戏独立**（`games.clean_filter_override`）

### 数据迁移

- `games` 表新增 `clean_filter_override` 列（TEXT，JSON 数组，空 = 引擎默认），启动时自动迁移

### 测试与验证

- 过滤器链单元测试：12+ 项用例（含计划书验收样例）全部 PASS
- 双版本（x64/x86）编译通过；`smoke_translation`、`verify_frontend` 回归通过
- 真机验证：9-nine（kirikiri）字幕去重/递增拼接清洗正常；中文游戏（GDI 逐字）正常

### AI 兜底清洗（Phase 3，已完成）

- `AiTranslator` 支持 `cleanAsync`（清洗任务 + 独立回调），清洗 prompt：只清洗不翻译、temperature=0、保留最后完整句
- 协议 `start_hook` 新增 `ai_clean_mode`（0=关, 1=脏文本才洗, 2=每条都洗）
- 稳定回调：过滤器链清洗后判定（`CleanlinessChecker`）不干净 → 先显示原文 → 异步 AI 清洗 → 更新字幕 + 翻译
- 配置：`clean.ai_assist_enabled` / `clean.ai_assist_threshold`（off/dirty/always，默认 dirty）
- 前端设置页加"AI 兜底清洗"开关 + 触发阈值

### 打包

- 同步 overlay/（含 bin/bin32 + texthook.dll）与 kazari_play/ 到构建目录 `KazariPlay_V1.0_build`
- `KazariPlay.spec` datas 修正：同时打包 x64（bin）与 x86（bin32）两个 overlay.exe + texthook.dll，匹配 `_resolve_exe` 查找路径（`sys._MEIPASS/overlay/bin|bin32`）
- PyInstaller 打包完成，产出 `dist/KazariPlay/KazariPlay.exe`

### 后续修复与调优（真机验证阶段）

- **AI 请求失败修复**：`ai_translator.cpp` 请求头缺 `Authorization: ` 前缀（非法头 → WinHTTP ERROR_INVALID_PARAMETER），导致所有 AI 请求失败、字幕只有原文。已修复并验证 status=200
- **人名/全同字符去重**：`dedup_chars.analyzeRepeatPeriod` 对全段同一字符（如"翔翔翔"）不记录 → 补记首个字符连续次数
- **递增拼接去重增强**（`incremental_dedup`）：
  - 检测前**压缩连续重复字符**（dedup_chars 众数对混合重复去不净的残留）
  - `.` 连续（省略号 `...`）保留，不压缩
  - **容错最后一段回退**：只要求最长连续递增前缀，返回顶点段（处理渲染中途截断）
- **稳定器句子结束检测**（`text_stabilizer`）：flush 前检查是否以明确结束标点（全角 `。！？…」』`）结尾，半角标点/省略号（`·····. !`）不算结束 → 再等完整句；长文本（≥15 字符）retry 上限提到 8 轮
- **去重扩展替换**（`main.cpp`）：新文本是旧文本的前缀扩展（不完整句→完整句）时更新 recentClean 并继续处理，不再被相似度去重误杀
- **清洗策略默认保守**（LunaTranslator 式）：各引擎默认安全档（furigana/control_char/dedup_chars/dedup_lines/unicode_normalize），激进项（incremental_dedup/dedup_mixed_lines/shift_jis/quote_only/line_trimmer）默认关、详情页手动开；`dedup_lines` 加长度阈值（≥8 字符）保护叠词
- **每游戏清洗配置**：`games.clean_filter_override`（每游戏独立，替代全局）
- **勾选即生效**：详情页清洗配置勾选即自动保存 + 实时下发 C++
- **开关联动字幕**：实时翻译开关（胶囊）联动字幕窗口显示/隐藏（`set_subtitle_enabled`）
- 已知限制：hook 点抓取不完整的句子（如渲染缓冲只到 40 字符）无法在清洗/稳定器层修复，属 hook 点配置问题

### 待办

- [ ] 真机验证打包版（运行 exe 启动游戏测试翻译/清洗）
- [ ] 同步最终改动到构建目录并重打包
- [ ] 真机验证 AI 兜底清洗（需配置 AI key）
