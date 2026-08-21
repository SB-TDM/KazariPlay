# KazariPlay WebView 性能优化实施计划书

> 版本：V1.0（计划稿）
> 日期：2026-08-21
> 依据：`docs/prompt1.md`（API 与刷新合并优化要求）
> 原则：不改架构、尽量少动代码、逐项独立可回退、语义不变、线程安全、无视觉改动
> 状态：**已实施完成（2026-08-21）**，步骤 A/B/C/D/F/G 全部落地；步骤 E（读桥异步化）按计划剥离未实施

---

## 0. 现状梳理（已核对代码）

| 关注点 | 现状 | 位置 |
|---|---|---|
| 封面缓存 | 全局 `OrderedDict` LRU，**无锁**；任何封面变化调 `reloadCovers()` → `_cover_cache_clear()` 清空**全部** | `web_bridge.py:39-68` |
| 封面失效触发 | `reloadCovers()` 清全缓存 + `_ui.invalidate("covers")`；前端 `reloadCovers()` 遍历**所有** `.card` 重新 getCover | `web_bridge.py:1206` / `ts/games.ts:13-26` |
| 封面请求去重 | **无**。并发/短时多次请求同一路径会重复读文件 + base64 编码 | `web_bridge.py:138-159` |
| 封面缩略图 | `_ensure_cover_thumb()` 按 `path+mtime` 幂等落盘，但**多线程首次并发生成同一张时无锁**，可能重复缩放+写盘 | `web_bridge.py:93-135` |
| 截图缩略图 | `getScreenshotThumb` 直接读**原图** base64（无缩略图生成、无缓存、无去重）；前端对**全部**截图并发请求 | `web_bridge.py:862-881` / `ts/screenshots.ts:28-40` |
| 截图列表 | `get_screenshots` 返回该游戏全部截图（无分页/上限参数） | `screenshot_service.py:156-171` |
| 前端封面节流 | IntersectionObserver 懒加载（进入视口才取），但**无暂停节流/批量合并**，滚动中逐张同步往返 | `ts/cards.ts:104-122` |
| 卡片 DOM | `renderCards` 为**全部**游戏建 DOM（`_renderedIds` 全量），仅封面图懒加载；**无窗口化** | `ts/cards.ts:42-102` |
| 截图 DOM | `renderScreenshots` 对**所有**截图全量建 DOM + 全量取缩略图；**无可视区限制** | `ts/screenshots.ts:17-42` |
| 刷新归口 | `UISync` 已有 50ms 跨域合并（`_FLUSH_DELAY`），但 `games` 域永远全量 `refresh()` | `ui/sync.py:37-42` |
| 写操作刷新 | 35+ 处 `self.refresh()`（全量 games）+ 4 处 `reloadCovers()` | `web_bridge.py` 各方法 |
| 批量 VNDB | `_run_vndb_match` 结束时 `reloadCovers()`（符合"全部结束一次"）+ `refresh()` | `web_bridge.py:682-684` |
| 读桥方法 | 全部同步返回字符串（pywebview 默认串行执行 js_api） | `web_bridge.py` |

**根因归纳**：
1. 封面缓存"一变清全"→ 单卡变化触发全卡重载（大量 base64 重编码 + 桥往返）。
2. 封面读/缩略图生成无去重 → 并发重复 I/O 与 CPU。
3. 前端滚动封面逐张即取，无节流。
4. 写操作刷新无"变化项"信息 → 前端全量重建网格。
5. **截图链路**：无缩略图/缓存/去重/懒加载，全量原图 base64 + 全量并发请求，负载高于封面。
6. **DOM 全量渲染**：卡片与截图 DOM 均为全量创建，只有图片懒加载，无"只渲染可视区"的虚拟化。

---

## 1. 总体方案

在**不改架构**前提下，改造落在 `web_bridge.py` + `ui/sync.py` + 前端 `ts/*`（+ 对应 `js/*` 产物）。每一步独立可回退。

关键设计：**封面缓存改为"按 path 定向失效"**，配合新前端入口 `reloadCover(gameId)`（单卡）与 `reloadCovers()`（全量，仅批量结束用）；**新增"变化项"刷新域 `games_delta`**，携带变化的 game_id 列表，前端只更新这些卡片；**截图链路补齐缩略图/缓存/去重/懒加载**；**卡片与截图网格引入"可视区窗口化"**（只渲染可视区 ± 缓冲区）。

---

## 2. 分步计划

### 步骤 A：封面缓存定向失效 + 前端单卡重载入口

**改动**：
- `web_bridge.py`：
  - 新增 `_cover_cache_invalidate(path)`：只删该 path 的缓存条目并同步 `_cover_cache_bytes`（需加锁）。
  - `_cover_cache_get/_put/_clear` 加 `threading.Lock`（步骤 C 的并发去重也依赖它）。
  - `reloadCovers()` 保留全量清空（批量结束场景），**新增** `reloadCover(game_id)`：查该游戏 cover_path → 只 invalidate 该 path → `_ui.invalidate("cover", game_id)`。
  - `setCover` / `_do_match`（单卡 VNDB）改用 `reloadCover(game_id)`；`_run_vndb_match` 批量保持 `reloadCovers()`。
- `ui/sync.py`：
  - `_DOMAIN_JS` 新增 `"cover"` → `reloadCover`（payload: game_id）。
- 前端：
  - `ts/games.ts` 新增 `reloadCover(gameId)`：只对 `[data-id=gameId]` 卡片清 `coverLoaded` + 重取 getCover，逻辑与 reloadCovers 单卡一致。
  - `ts/state.ts` 的 `__app` 增加 `reloadCover` 入口。
- 验证：单卡换封面 → 仅该卡重载；批量 VNDB → 仍一次全量。

**收益**：单卡封面变化不再清空 128 条缓存、不再全卡重编码。
**风险**：低。调用点从 2 处 reloadCovers 拆出，行为对齐现有逻辑。

---

### 步骤 B：封面请求去重（后端"同一路径同时只算一次"）

**改动**：
- `web_bridge.py`：
  - 新增 `_cover_inflight: Dict[str, threading.Event]` + 锁；`_cover_data_uri` 逻辑改为：cache 未命中 → 检查 inflight，若同 path 正在计算则等待其完成并读缓存（结果共享），否则登记 inflight → 读文件编码 → 写缓存 → 释放。
  - 超时保护（如 5s）防死等，超时后自身重算。
- 说明：pywebview 默认串行执行 js_api 回调，但 UISync 线程、monitor 线程、多窗口下仍可能有并发，去重保证"同时只读一次文件"。
- 验证：日志/断点确认同 path 并发只执行一次 `_cover_data_uri` 的文件读取段。

**收益**：消除滚动中重复读图与编码。
**风险**：中。加锁需小心死锁（用 Event + 超时，不嵌套持锁等锁）。

---

### 步骤 C：封面缩略图生成并发去重（按 path 加锁）

**改动**：
- `web_bridge.py`：
  - 新增 `_thumb_locks: Dict[str, threading.Lock]` + 全局锁保护字典；`_ensure_cover_thumb` 在检查 `os.path.exists(thumb)` 未命中后，先取得该 path 的锁，**锁内二次检查**（double-checked locking），再执行缩放+落盘。
  - 缩略图路径本身已含 mtime（幂等命名），锁仅防并发首先生成。
- 验证：多线程同时请求同一封面 → 只生成一次（检查 thumbs 目录无并发写、日志无重复缩放）。

**收益**：消除重复图片缩放与落盘的 CPU/IO 浪费。
**风险**：低。锁粒度小、路径唯一、无死锁风险。

---

### 步骤 D：刷新归口"增量更新"（games_delta 域）

**改动**：
- `ui/sync.py`：
  - `_DOMAIN_JS` 新增 `"games_delta"` → `applyGamesDelta`（payload: game_id 数组）。
  - `_emit` 处理 `games_delta`：payload 为空数组则降级为 `refresh()`（保持语义），否则 `applyGamesDelta([...])`。
- `web_bridge.py`：
  - 新增 `refresh_delta(game_ids: list)`：`self._ui.invalidate("games_delta", list(game_ids))`。
  - 将写操作结尾的 `self.refresh()` 逐步替换为 `refresh_delta([game_id])`（收藏/评分/删除/启动/收藏夹归属/截图/标签等单对象操作）；批量操作（批量收藏夹、批量 VNDB、批量删除）仍用 `refresh()` 全量。
  - **保持调用顺序与异步语义**：仅改推送域，不改变方法返回时机。
- 前端：
  - `ts/games.ts` 新增 `applyGamesDelta(ids)`：仅对这些 id 的游戏拉最新（`getGame`）或按现有增量渲染路径更新对应卡片；空数组走 `refreshAll(false)` 兜底。
  - `ts/state.ts` `__app` 增加 `applyGamesDelta`。
- 验证：收藏/评分后仅相关卡片刷新，无整页重建。

**收益**：单点操作不再全量重建网格，滚动位置与已加载封面保留。
**风险**：中。需保证"前端只更新变化项"与现有 `renderCards` 增量逻辑不冲突（复用 `_renderedIds` 对比）。

---

### 步骤 E（可选）：读类桥方法异步化

- 将 `getCover` / `getScreenshotThumb` 等高频只读方法改为在独立线程处理并返回，让多个待处理调用可并发。pywebview 的 js_api 本身是同步串行的，改异步需要后端线程池 + 前端 Promise 适配。
- **评估**：改动面大（前端 bridge 代理、全部调用点回调语义、异常处理），且 pywebview 对 js_api 返回值的同步保证会变化。**建议从本批剥离**，单独评估后实施。
- 若后续做：方案为 WebBridge 内加 `ThreadPoolExecutor`，只读方法 `submit` 后由 UISync/回调回传结果；前端 `bridge` 代理对异步方法改 Promise。

---

### 步骤 F：截图链路补齐（缩略图 / 缓存 / 去重 / 懒加载）

**改动**：
- `web_bridge.py`：
  - 新增 `_screenshot_thumb(path)`：仿 `_ensure_cover_thumb`（`screenshot_service` 或 bridge 内），截图原图 → 512px 宽 JPEG 缩略图，落盘命名含 `path+mtime`（幂等失效重建）。截图缩略图尺寸可更小（如 256px，对应卡片缩略展示）。
  - `getScreenshotThumb` 改走缩略图 + 独立 LRU 缓存（或复用 `_cover_cache` 机制，加锁）；同样纳入步骤 B 的"同路径同时只算一次"去重。
  - `getScreenshots` 保持返回全部（列表元数据轻量），但可加可选 `limit` 参数（默认全量，兼容现有前端调用）。
- 前端：
  - `ts/screenshots.ts` 截图卡片改为 **IntersectionObserver 懒加载缩略图**（进入视口才 `getScreenshotThumb`），不再全量并发请求；复用 `renderCards` 的增量渲染思路（或结合步骤 G 的窗口化）。
- 验证：多截图游戏的详情页滚动时缩略图按需加载，无一次性全量 base64 请求；缩略图只生成一次。

**收益**：截图负载从"全量原图 base64"降为"按需缩略图"，内存与桥往返显著下降。
**风险**：中。`getScreenshotThumb` 被预览（原图路径应保留）与缩略图两处调用，需区分：**预览仍读原图**，卡片缩略走缩略图。

---

### 步骤 G：卡片与截图网格 DOM 窗口化（只渲染可视区 ± 缓冲区）

**目标**：根治"DOM 全量 + 全量重绘"。当前 `renderCards` 为全部游戏建 DOM、`renderScreenshots` 为全部截图建 DOM。改为**只渲染可视区 ± 缓冲区**内的节点，滚动时增量替换。

**改动**（前端，`ts/cards.ts` / `ts/screenshots.ts`）：
- 卡片网格：
  - 保留现有**增量复用**（`_renderedIds` + `oldMap`）与排序逻辑，但**只对窗口范围内的 id** 建/复用卡片；窗口外 id 不建 DOM。
  - 计算窗口：由 `scrollTop` / 卡片固定高度（`--card-h` + 行距）算出可见 id 区间 `[start, end]`，上下各扩缓冲区（如 1~2 屏）。
  - 滚动监听（`scroll` + `requestAnimationFrame` 节流）→ 重算窗口 → 增量替换（窗口内新建、窗口外移除，仍复用中间重叠节点）。
  - 保持 `coverObserver` 懒加载与封面缓存失效逻辑（步骤 A/B/C 结果天然作用于窗口内节点）。
  - 空状态/排序/筛选/批量选中逻辑不变（它们基于数据而非 DOM）。
- 截图网格：
  - 详情抽屉内截图列表窗口化（高度固定行），同样只渲染可视区 ± 缓冲区。
  - 无窗口化时至少保证缩略图按需加载（步骤 F），避免全量取图。
- **不改变**：视觉、交互、滚动位置恢复、批量模式、右键菜单。

**验证**：千库滚动时 DOM 节点数保持在"可视区 ± 缓冲"恒定数量（可在 DevTools 确认 `<div class=card>` 数量），滚动流畅；筛选/排序/批量行为与现在一致。

**收益**：DOM 节点数从 O(全部) 降为 O(可视区)，滚动重绘与内存占用实质下降——这是"WebView 不整页/全图重绘"的根因级修复。
**风险**：高（涉及核心渲染路径）。需严格保持增量复用 + 滚动位置语义；作为**独立 commit 最后实施**，若回归明显可整体回退。

---

## 3. 实施顺序与回退

| 步骤 | 涉及文件 | 独立回退方式 |
|---|---|---|
| A | `web_bridge.py` `ui/sync.py` `ts/games.ts` `ts/state.ts`（+ `js/*` 产物） | 单 commit，revert 即回 |
| B | `web_bridge.py` | 单 commit |
| C | `web_bridge.py` | 单 commit |
| D | `web_bridge.py` `ui/sync.py` `ts/games.ts` `ts/state.ts`（+ 产物） | 单 commit |
| E | 剥离，暂不做 | — |
| F | `web_bridge.py` `ts/screenshots.ts`（+ 产物） | 单 commit |
| G | `ts/cards.ts` `ts/screenshots.ts`（+ 产物） | 单 commit（最后实施） |

每步完成后：`npm run build`（若涉前端）→ `python tests/verify_frontend.py` → 对应功能手动冒烟 → 提交。

---

## 4. 验证清单（全部完成后肉眼确认）

1. **滚动封面**：进入大库向下快速滚动，观察无逐张卡顿、无整页重绘；后端日志确认同一封面 path 只计算一次。
2. **单卡封面更换**：详情页换某游戏封面 → 仅该卡片刷新封面，其余卡片无闪烁/重载。
3. **批量 VNDB 匹配**：多选游戏批量匹配 → 全程无每张刷新，结束才整体刷新一次。
4. **单点数据变化**：收藏/评分一个游戏 → 网格不整体重建，仅该卡更新，滚动位置保持。
5. **截图缩略图**：打开多截图游戏的详情 → 缩略图按需加载、不一次性全量取图；预览大图仍读原图清晰。
6. **DOM 窗口化**：DevTools 检查大库滚动时 `<div class=card>` 数量恒定在"可视区 ± 缓冲"，不随库规模增长；滚动流畅无白屏。
7. **内存/进程**：长时间滚动后 WebView2 内存占用不再线性增长。

---

## 5. 说明约定

- 前端改动后 `js/` 产物由 `npm run build` 重新生成并随提交。
- 所有新增锁/去重/缓存逻辑保证线程安全（UISync 已在多线程调用）。
- 不改任何现有交互与渲染视觉；只减少多余重绘与重复计算。