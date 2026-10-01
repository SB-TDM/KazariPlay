# KazariPlay 截图功能改造计划书 — 原图+缩略图双保存 + 缩略图统一尺寸（留边）

> 版本：V2.0（计划稿）
> 日期：2026-08-29
> 范围：`kazari_play/core/screenshot_service.py` + `kazari_play/ui/web_bridge.py`（截图保存/缩略图链路）+ 前端 `ts/screenshots.ts` 适配
> 原则：不改架构、小步可验证、语义不变、保留 WGC/PrintWindow 捕获内核
> 状态：**已实施完成（2026-09-12）**：截图双保存 + 留边缩略图 + 删除/重命名联动；缩略图回退 512px 小画布（体积 24 倍下降）

---

## 1. 现状梳理（已核对代码）

| 关注点 | 现状 | 位置 |
|---|---|---|
| 截图捕获 | 三级回退：①WGC（客户区物理像素）→ ②PrintWindow（客户区逻辑像素）→ ③ImageGrab 全屏 | `screenshot_service.py:239-279` |
| 截图保存 | **仅一张**原图 `shot_{时间戳}.png`（PNG），存 `screenshots/{game_id}/` 或 `_unsorted/` | `screenshot_service.py:268-279` |
| 缩略图 | **运行时按需**生成：`getScreenshotThumb` → `_ensure_screenshot_thumb` → 512px JPEG 落盘到 `app_data/screenshots/thumbs/`（mtime 命名幂等 + 锁去重） | `web_bridge.py:942-1014` |
| 截图尺寸 | **不统一**：WGC=客户区物理、PrintWindow=客户区逻辑、全屏=屏幕分辨率 | `screenshot_service.py:239-279` |
| 前端展示 | `renderScreenshots` 列截图 → `getScreenshotThumb` 懒加载缩略图 | `ts/screenshots.ts:18-58` |
| 删除/重命名 | 只删原图，不删缩略图（缩略图 mtime 幂等，下次访问失效重建） | `screenshot_service.py:310-346` |

**根因归纳**：
1. 截图只存原图，缩略图是"运行时按需生成"，不随截图持久化 → 每次新访问若缩略图未生成会现场生成（延迟 + 首次 I/O）。
2. 截图尺寸由捕获路径决定，不统一 → 不同游戏/不同捕获方式截图大小不一致。

---

## 2. 目标

1. **每次截图保存两份**：原图 + 缩略图，**截图时立即生成并落盘**（非运行时按需）。
2. **缩略图统一尺寸**：所有缩略图统一为屏幕分辨率画布，**等比缩放 + 留边**（letterbox），不拉伸变形。
3. **原图保持原始捕获尺寸**（不统一、不缩放）。
4. 保持捕获内核（WGC 三级回退）、归属逻辑（game_id / _unsorted）、前端交互不变。

---

## 3. 总体方案

在**不改架构**前提下改造 `screenshot_service.py` + `web_bridge.py`：

- **截图时双保存**：`take_screenshot` 捕获到图后，保存**原图**（保持原始尺寸）到 `screenshots/{game_id}/`，同时**立即生成缩略图**并保存到 `screenshots/{game_id}/thumbs/`。
- **缩略图统一尺寸 + 留边**：缩略图画布 = 主屏分辨率（`GetSystemMetrics(0)×(1)`），原图**等比缩放**放入画布，不足部分**留边**（黑边/透明），不拉伸变形。
- **缩略图落盘位置**：随原图存放（`screenshots/{game_id}/thumbs/`），删除/重命名联动。
- **前端适配**：`getScreenshots` 排除 `thumbs/` 子目录；`getScreenshotThumb` 直接读已保存缩略图。

---

## 4. 已确认决策（2026-08-29）

| 决策点 | 结论 |
|---|---|
| 4.1 缩略图存放位置 | **A：随原图存放** `screenshots/{game_id}/thumbs/{名称}_thumb.jpg`，删除/重命名联动 |
| 4.2 原图尺寸 | **不统一**，保持捕获时的原始尺寸 |
| 4.3 缩略图尺寸 | **统一为屏幕分辨率画布**，等比缩放 + 留边（letterbox），不拉伸 |
| 4.4 屏幕分辨率来源 | **主屏** `GetSystemMetrics(0)×(1)` |
| 缩略图编码 | JPEG（沿用现有缩略图编码，画布尺寸按决策调整） |

---

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `kazari_play/core/screenshot_service.py` | ① `take_screenshot` 保存原图（**保持原始尺寸**）；② 立即生成缩略图（**等比缩放 + 留边到屏幕分辨率画布**）并保存到 `thumbs/`；③ `get_screenshots` 排除 `thumbs/` 子目录；④ 删除/重命名联动缩略图 |
| `kazari_play/ui/web_bridge.py` | `getScreenshotThumb` 改为**直接读已保存缩略图**（不再运行时生成）；`_screenshot_thumb_path`/`_ensure_screenshot_thumb` 逻辑调整 |
| `kazari_play/ui/web_assets/ts/screenshots.ts` | 缩略图加载路径适配（若缩略图文件名/位置变化） |
| `tests/smoke_screenshots.py` | 追加：截图后原图+缩略图双文件断言；缩略图尺寸=屏幕分辨率断言 |
| （不改）`web_bridge.py` 的 takeScreenshot/takeScreenshotRunning | 仅 `take_screenshot` 内部变化，外部接口不变 |

---

## 6. 分步计划（每步独立可回退）

### 步骤 A：截图时双保存（原图保持原尺寸 + 缩略图统一屏幕分辨率留边）
- `screenshot_service.py`：
  - 新增 `_screen_resolution()`：`GetSystemMetrics(0)×(1)`（主屏）
  - 新增 `_make_letterbox_thumb(img, screen_w, screen_h)`：原图**等比缩放**放入屏幕分辨率画布，不足部分**留边**（黑边），不拉伸
  - `take_screenshot`：捕获 `img` 后 → 保存 `shot_{时间戳}.png` 原图（**原始尺寸**）；随后**立即**用 `_make_letterbox_thumb` 生成缩略图保存到 `thumbs/`
  - 返回主图路径（兼容现有调用方）
- **验证**：截图后目录含原图 + 缩略图两个文件；原图尺寸=捕获原始尺寸；缩略图尺寸=屏幕分辨率。

### 步骤 B：缩略图随原图存放 + 删除/重命名联动（方案 A）
- `screenshot_service.py`：
  - 新增 `_shot_thumb_path(original_path)`：缩略图路径 = `screenshots/{game_id}/thumbs/{basename}_thumb.jpg`
  - `get_screenshots` 排除 `thumbs/` 子目录（只列原图）
  - `delete_screenshot`：删除原图时**连带删除对应缩略图**
  - `rename_screenshot`：重命名原图时**同步重命名缩略图**（或删旧缩略图让下次重建）
- **验证**：删除截图后原图+缩略图都不存在；get_screenshots 不列出 thumbs 子目录。

### 步骤 C：前端与 getScreenshotThumb 适配
- `getScreenshotThumb` 直接读已保存缩略图（截图时已生成），不再运行时生成。
- 前端 `screenshots.ts` 缩略图路径适配。

### 步骤 D：测试与回归
- 冒烟测试追加断言；跑全部 smoke + verify_frontend。

---

## 7. 验证清单（全部完成后）

1. 截图后：`screenshots/{game_id}/` 下**同时存在**原图 + 缩略图。
2. **原图尺寸 = 捕获时的原始尺寸**（不统一、不缩放）。
3. **缩略图尺寸 = 屏幕分辨率**，且内容**等比无拉伸**（两侧/上下留边）。
4. 前端截图区：缩略图正常显示（懒加载），点击预览显示原图。
5. 删除截图：原图 + 缩略图**一起删除**。
6. 无 pid（未运行游戏）：全屏截图同样双保存 + 缩略图统一尺寸。
7. 未装 windows-capture：降级 PrintWindow/全屏，仍双保存 + 缩略图统一尺寸。

---

## 8. 风险与对策

| 风险 | 缓解 |
|---|---|
| 缩略图留边画布大（屏幕分辨率）导致体积大 | 内容等比缩放后压缩为 JPEG，画布大但内容占比小，JPEG 体积仍可控；必要时可限制缩略图最大边（如 ≤ 1920） |
| 双保存增加磁盘占用 | 缩略图为 JPEG 小体积；原图是必要存储 |
| 缩略图生成失败 | 原图保存不受影响；缩略图失败仅日志（前端可回退读原图） |
| 旧截图兼容 | 旧截图（无预生成缩略图）在 `getScreenshotThumb` 仍可运行时按需生成兜底 |

---

## 9. 决策记录（已确认）

1. **缩略图存放位置**：随原图同目录 `screenshots/{game_id}/thumbs/`（A）
2. **原图尺寸**：不统一，保持捕获原始尺寸
3. **缩略图尺寸**：统一为屏幕分辨率画布，**等比缩放 + 留边**（不拉伸）
4. **屏幕分辨率来源**：主屏 `GetSystemMetrics(0)×(1)`
5. **缩略图编码**：JPEG