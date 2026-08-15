# 变更日志（CHANGELOG）

> 记录 KazariPlay 的开发改动。按功能块组织，最新在前。

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
