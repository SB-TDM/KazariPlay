# KazariPlay「批量扫描游戏文件夹」优化计划书

> 版本：V1.0（计划稿）
> 日期：2026-09-12
> 范围：`core/game_scanner.py`（扫描准确性/性能）+ `ui/web_bridge.py`（多选/进度/取消）+ `ui/sync.py` + 前端 `ts/batch.ts`/`index.html`（进度 UI）
> 原则：不改架构、小步可验证、语义不变、保留"一个文件夹=一个游戏"聚合策略
> 状态：**计划稿，尚未改代码**

---

## 1. 现状梳理（已核对代码）

| 关注点 | 现状 | 位置 |
|---|---|---|
| 扫描入口 | `btnScan`（空状态）/ `fabScan`（FAB 菜单）→ `bridge.scanFolder()` | `app.ts:103,111` |
| 目录选择 | `create_file_dialog(FOLDER_DIALOG)` **单选**（取 `folder[0]`） | `web_bridge.py:645-654` |
| 扫描执行 | 后台线程 `_do_scan` → `manager.scan_and_add` → `scanner.scan`（递归 `os.walk`） | `web_bridge.py:656-664` |
| 聚合计粒度 | **一个文件夹 = 一个游戏**；多 exe 选主（汉化优先 → 文件名排序） | `game_scanner.py:95-136,158-171` |
| exe 过滤 | 黑名单**仅英文**关键词（uninstall/config/setup/patch/launcher/viewer…） | `game_scanner.py:65-83` |
| 文件夹过滤 | 跳过（补丁/备份/patch/backup/副本） | `game_scanner.py:90-92` |
| 引擎检测 | 特征文件 `os.listdir` > exe 全名 > 子串；每文件夹一次 listdir | `game_scanner.py:226-292` |
| 标题 | = exe 所在文件夹名（有意简化） | `game_scanner.py:213-224` |
| 去重 | 按 `exe_path`，已存在跳过 | `game_manager.py scan_and_add` |
| 进度/取消 | **无**（仅"扫描中…"） | `_do_scan` |
| 扫描后 | `refresh()` + 新增则自动 VNDB 匹配 | `_do_scan` |

**已实测确认的问题**：`启动游戏.exe`（SmartSteamEmu 启动器）**未被黑名单过滤**（`_is_valid_game_exe('启动游戏.exe') == True`）。

---

## 2. 目标

1. **准确性**：消除中文启动器误识别；主 exe 选择更智能（体积优先）。
2. **性能**：减少重复 IO、跳过辅助目录。
3. **体验**：支持多选目录、扫描进度反馈、可取消。

---

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `core/game_scanner.py` | ① 黑名单加中文启动器关键词；② `_pick_primary_exe` 按体积优先；③ `_detect_engine` 复用 walk 的 listdir；④ `ignore_folders` 加辅助目录；⑤ `scan` 加 `progress_cb` + `cancel_event` |
| `ui/web_bridge.py` | ① `scanFolder` 支持多选（`allow_multiple=True`）；② 扫描进度经 UISync 上报；③ 新增 `cancelScan()` |
| `ui/sync.py` | 新增 `scan_progress` 域 → 前端 `updateScanProgress` |
| `ui/web_assets/partials/index.html` | 扫描进度 UI 复用 `batchProgress`（加"取消"按钮）或新增 |
| `ui/web_assets/ts/batch.ts`（或新 scan 模块） | `updateScanProgress` 渲染 + 取消按钮绑定 |
| `tests/` | 扫描器单测（中文启动器过滤、体积优先、进度回调、取消） |

---

## 4. 分阶段实施（每阶段独立可回退）

### 阶段 A：扫描准确性 + 性能（`game_scanner.py` 为主）

**A1. 中文启动器过滤**
- `ignore_patterns` 增加中文关键词：`启动`、`开始`、`游戏启动`、`安装`、`设置`、`卸载`、`说明`、`工具`、`补丁`…
- 注意：`游戏.exe`（中文通用主程序名）**不能**被"游戏"关键词误伤 → 用**精确整名匹配**或更具体的关键词（如"启动游戏""游戏启动"），避免误伤。
- 验证：`启动游戏.exe` 被过滤；`nine_kokoiro.exe`/`游戏.exe` 保留。

**A2. 主 exe 选择按体积优先**
- `_pick_primary_exe(folder, exes)`：优先级改为
  1. 汉化版（chs 关键词）
  2. **exe 文件体积最大**（真游戏主程序通常最大）
  3. 文件名排序
- 需改签名传入 `folder` 以 `os.path.getsize`。
- 验证：`启动游戏.exe`(小) + 真游戏.exe(大) → 选真游戏。

**A3. 引擎检测复用 listdir**
- `scan` 的 `os.walk` 已拿到每 `root` 的 `files`；构建 `{root: files}` 缓存传给 `_detect_engine`，省去重复 `os.listdir`。
- 验证：功能不变，大目录耗时下降。

**A4. 跳过辅助目录（性能）**
- `ignore_folders` 增加：`smartsteamemu`、`remotestorage`、`plugin`、`dxwebsetup`、`__macosx` 等（**谨慎**：只加确定非游戏内容的目录名）。
- 验证：辅助目录不被遍历。

**A5. 标题清洗（保守规则）**
- 现状：标题 = exe 所在文件夹名，含平台/语言前缀后缀噪声（如 `PC[ぱれっと]9nine①-..._官方中文`）。
- **保守清洗规则**（只去除明确噪声，不臆测内容）：
  1. 去除开头平台前缀：`^PC[\s\-_]?`、`^【PC】`、`^\[PC\]`
  2. 去除开头来源标签：`^\[[^\]]*\]` / `^【[^】]*】`（**仅开头**，通常是开发商/汉化组/平台标识）
  3. 去除结尾语言/版本后缀：`_官方中文$`、`_官方繁體$`、`_汉化版$`、`_中文版$`、`_汉化$`、`_全年龄$`、`_无修$`、`_(无修)$`、`_完全版$`
  4. 去除首尾空白
  5. **兜底**：清洗后为空则回退原文件夹名
- 示例：`PC[ぱれっと]9nine①-九次九日九重色_官方中文` → `9nine①-九次九日九重色`
- 验证：常见噪声文件夹名清洗后保留核心游戏名；无噪声的文件夹名不变。

### 阶段 B：扫描体验（`web_bridge.py` + `sync.py` + 前端）

**B1. 多选目录**
- `scanFolder`：`create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=True)` → 遍历返回的目录列表，逐个后台扫描。
- 兼容单选（返回 1 个目录）。
- 验证：一次选多个目录，全部被扫描。

**B2. 扫描进度**
- `game_scanner.scan` 加 `progress_cb(dirs_done, games_found)` 回调，`os.walk` 每遍历一个目录回调一次（节流）。
- `web_bridge._do_scan` 把回调接到 `self._ui.invalidate("scan_progress", {...})`。
- `sync.py` 新增域：`scan_progress` → 前端 `updateScanProgress(payload)`。
- 前端：复用 `batchProgress` UI 区域（标题/计数/进度条），显示"已扫描 N 个文件夹 · 发现 M 个游戏"。
  - 进度条用**不确定动画**（无法预知总目录数）或按"已发现游戏数"表现。
- 验证：扫描大目录时进度实时更新。

**B3. 取消扫描**
- `game_scanner.scan` 加 `cancel_event`（`threading.Event`），`os.walk` 循环检查 → 提前返回。
- `web_bridge.cancelScan()` 设置 event；前端进度 UI 加"取消"按钮 → `bridge.cancelScan()`。
- 验证：扫描中途点取消，扫描停止，已完成部分入库。

### 阶段 C：测试与回归
- 新增扫描器单测：中文启动器过滤、体积优先选主、进度回调触发、取消提前返回。
- 跑 smoke + verify_frontend + typecheck。

---

## 5. 验证清单（全部完成后）

1. `启动游戏.exe`（中文启动器）被过滤；真游戏 exe 正常识别。
2. 同目录多 exe：优先选体积最大的真游戏主程序。
3. 辅助目录（SmartSteamEmu 等）不被遍历。
4. 一次可选**多个目录**，全部扫描入库。
5. 扫描大目录时**进度实时更新**（文件夹数/游戏数）。
6. 扫描中途**取消有效**，已完成部分正常入库。
7. 无回归：自动扫描（启动时）、去重、`library_paths` 记录、扫描后自动 VNDB 匹配均正常。

---

## 6. 风险与对策

| 风险 | 缓解 |
|---|---|
| 中文关键词误伤真实游戏名（如"游戏.exe"） | 用精确/具体关键词（"启动游戏"而非"游戏"）；保留白名单机制 |
| 体积优先选错（如带大体积补丁 exe） | 体积作为汉化之后的次级规则；过于激进时回退文件名排序 |
| 多选目录扫描量大 | 配合进度 + 取消；后台线程不阻塞 UI |
| 进度频繁推送拖慢 | 回调节流（如每 N 个目录或每 200ms 推一次） |
| 取消后部分入库 | 语义明确：已扫描完成的部分正常入库，未扫描的跳过 |

---

## 7. 决策记录（已确认 2026-09-12）

1. **中文启动器关键词表**：使用基础关键词（启动/开始/安装/设置/卸载/补丁/工具等），暂无额外补充
2. **进度条形式**：**按"已发现游戏数"估算百分比**
3. **取消语义**：**取消后已完成部分正常入库**
4. **标题清洗（A5）**：**纳入本次**，采用保守清洗规则（§4 A5）

> A4（标题清洗）已并入 §4 阶段 A 的 A5。