# develop 试用问题交接

> 归档日期：2026-10-07。用户要求只归档，交由其他 agent 修复；本轮没有修改功能代码或重打包。三项均为现有问题，状态全部 `pending`。

## 基线与范围

- 反馈对象：无翻译原版 `develop`，Windows x64 试用包 `1.4.0-beta.1`。
- 试用包与源码基线：`85d936b5a5da43b6ac34928735bc0a79151ada13`，BUILD_INFO.json 的构建时工作区为空。
- 包目录：`trial-build-1.4.0-beta.1-win64/dist/KazariPlay/`，数据在包旁 `data/`；构建与隔离要求见 [PACKAGING.md](PACKAGING.md)。
- 用户原话有“两个问题”，实际列出三项，按三项独立归档。没有提供截图、具体被遮挡弹窗、匹配游戏/网络状态或取消延迟秒数。
- 证据：用户试用反馈 + 当前代码静态核对；本轮没有复跑 UI 遮挡、真实网络取消时序或重新测量耗时。下文复现步骤是接手验证路径，不能视为本轮已执行的复现。
- 三项属于共享 UI/元数据业务问题，先在原版修复验收，再选择性同步实验版适用部分。不可将实验分支整体合入 develop/main。

## 问题索引

| ID | 状态 | 建议优先级 | 问题 |
|---|---|---|---|
| DEV-TRIAL-01 | pending | P1 | 进度条窗口覆盖优先度过高 |
| DEV-TRIAL-02 | pending | P1 | 匹配中点击取消后响应过慢 |
| DEV-TRIAL-03 | pending | P2 | “VNDB 匹配”统一命名为“元数据匹配” |

优先级为交接建议，不表示用户已经指定修复顺序。以上问题验收前，试用不能记为全面通过，也不能凭此前离线打包自检认定可以直接合入 main/master。

## DEV-TRIAL-01 进度面板层级

**用户报告的症状**：进度条窗口覆盖优先度太高。

**触发/复现路径**：开始扫描或批量匹配，进度面板显示后打开详情、设置、编辑、收藏夹管理、重新定位或确认弹窗；检查面板是否盖住弹窗内容/底部按钮、是否在模态打开时仍可点击。具体用户看到的是哪个弹窗尚未明确，需补截图和窗口尺寸/DPI。

**静态事实与根因线索**：

- [widgets.css](../kazari_play/ui/web_assets/css/widgets.css) 的 `.batch-progress`（49 行附近）使用 `position:fixed; z-index:300`，`.show` 恢复 `pointer-events:auto`。
- [sheets.css](../kazari_play/ui/web_assets/css/sheets.css) 的 `.overlay`（7 行附近）是 `z-index:100`；进度面板与模态没有分别定义合理的层级策略。
- 同文件 `.toast` 也为 300，但其交互和用途与可点击进度面板不同；接手时需要分别检查，不能仅凭同值一并调整。
- [index.html](../kazari_play/ui/web_assets/index.html) 的 `batchProgress`、[batch.ts](../kazari_play/ui/web_assets/ts/batch.ts) 的 `showBatchProgress/trackBatchProgress/updateScanProgress` 是显示接线。以上是样式/代码证据，最终遮挡关系还需检查实际 stacking context 与点击命中。

**修复目标与验收**：主界面进度仍可见且取消可操作；打开模态后不遮挡模态内容/确认操作、不抢占模态交互。覆盖扫描和匹配两种阶段、详情/设置/编辑/确认弹窗、最小窗口 900x620 和当前 DPI；关闭模态后任务状态与取消入口正常。隐藏面板不能误取消任务，也不能破坏既有迟到进度响应隔离。

## DEV-TRIAL-02 取消匹配响应

**用户报告的症状**：VNDB 匹配中点击“取消匹配”后响应时间过慢。

**触发/复现路径**：手动批量匹配或扫描后自动匹配期间，在搜索请求、请求重试/退避、下一关键词搜索、封面下载阶段分别点击取消。记录点击、前端确认、取消事件置位、停止发新请求、任务结束和门禁释放的时间；用户没有给出耗时，本轮未实测。

**已核对的取消链路**：

1. [batch.ts](../kazari_play/ui/web_assets/ts/batch.ts) 的 `bpCancel`（282 行附近）直接调用 `bridge.cancelMatch()`，没有切换到“正在取消”状态或处理返回结果；进度轮询每 600ms。
2. [web_bridge.py](../kazari_play/ui/web_bridge.py) 的 `cancelMatch`（736 行附近）只置 `_vndb_cancel`；`_run_vndb_match` 完成后才标记 `running=False`，`_start_task` 的 finally 才释放门禁。
3. [game_manager.py](../kazari_play/core/game_manager.py) 的 `match_vndb_for_games` 传事件到 [metadata_matcher.py](../kazari_play/core/metadata_matcher.py) 的 `match_batch`（178 行附近）。事件仅在每个游戏开始前检查；`match_single` 没有收到事件，关键词回退循环和封面下载不会因点击取消而跳出。
4. [vndb_client.py](../kazari_play/utils/vndb_client.py) 的 `_REQUEST_TIMEOUT=15`、`_MAX_RETRIES=2`、`_RETRY_BACKOFF=2`；`_request_with_retry` 使用不可由事件唤醒的 `time.sleep`，HTTP 请求/读取也没有取消参数。单次搜索可能经历多次请求，同一游戏还可能进行多个关键词搜索和封面下载；15 秒不是任务取消总时限，不能把理论相加当作实测上限。

**与已修 P0 的区别**：P0 修复的是“传递取消事件、不要开始下一个游戏”，并明确当时允许已发请求按既有超时返回。本问题是进一步改善反馈和单游戏内部取消粒度，不应删除历史 fixed 记录或宣称此前已实现即时中断。

**修复目标与验收**：

- 分开定义“立即确认正在取消”和“实际任务已终止”，不能只隐藏面板并提前释放门禁伪装成功。用户没有指定毫秒/秒 SLA，接手应提出响应目标并报告实测时间。
- 取消后不再启动新的关键词、重试、下一游戏或尚未开始的封面下载；退避等待能唤醒。明确如何处理已在途网络请求和已经匹配成功/写入的数据。
- 无取消时保持正常匹配、失败/重试及已完成数据保留；连续点击取消、取消后再启动、异常退出不串任务，门禁释放正确，统计与提示不把取消算作普通成功。
- 用受控慢请求/失败替身验证搜索、退避、封面和各阶段时序，再走源码 GUI 与重新打包的同一路径；不能只缩短 timeout 或仅复用下一游戏检查来宣称修复。
- 现有 [test_p0_data_flow.py](../tests/test_p0_data_flow.py) 的 `test_manual_batch_cancel_stops_next_item_and_resets_for_retry` 以及 [test_p1_reliability.py](../tests/test_p1_reliability.py) 的任务拒绝/异常释放回归需保留；现有覆盖不包含真实网络取消响应时限。

## DEV-TRIAL-03 匹配命名与数据源

**用户要求**：界面“VNDB 匹配”统一改为“元数据匹配”，因为数据源不止一个。

**已确认的产品现状**：

- [multi_source.py](../kazari_play/core/multi_source.py) 注册 VNDB、Bangumi、月幕等源，可按 `metadata_sources.mixed` 检索候选；部分源只是 pending 占位，不能宣称全部已接入。
- [web_bridge.py](../kazari_play/ui/web_bridge.py) 的 `searchMetadata/applyCandidate`（1152 行附近）与 [form.ts](../kazari_play/ui/web_assets/ts/form.ts) 是现有多源手动检索/选择/应用路径。
- 卡片、详情菜单、批量和扫描后自动匹配调用 `matchVndb/matchVndbBatch/_run_vndb_match`，经 `metadata_matcher.match_single` 实际仍只用 `vndb_client`，尚未接入混合源配置。必须记录这一区别，不能把当前自动匹配说成多源。

**现役文案检查入口**：[cards.ts](../kazari_play/ui/web_assets/ts/cards.ts) 的卡片菜单、[detail.html](../kazari_play/ui/web_assets/partials/detail.html) 的详情菜单、[index.html](../kazari_play/ui/web_assets/index.html) 的批量按钮、[batch.ts](../kazari_play/ui/web_assets/ts/batch.ts) 的批量标题，以及 [web_bridge.py](../kazari_play/ui/web_bridge.py) 的开始/运行中/完成/取消/失败反馈。搜索前端和桥层中的 `VNDB 匹配`、`批量匹配 VNDB`、`VNDB 批量匹配中` 等变体。

**修复目标与验收**：通用操作按钮/菜单/进度/通知采用“元数据匹配”；VNDB 作为实际来源名称仍可展示，源选择器、source ID、vndb_id、API URL 和历史 changelog 不做盲目全局替换。单/批量/扫描后/取消/失败提示全部检查；来源信息与实际调用一致，已有多源手动候选路径可用。

**待明确的范围**：用户已要求统一通用命名，但没有在本轮指定自动/批量匹配的跨源顺序、回退或合并策略。接手 agent 先核对这些入口的产品预期；文案调整和把自动链路接入多源属于不同工作量，不能改名后就声称所有入口支持多源，也不默认授权整体重写匹配器。

## 接手步骤与边界

1. 先读 [DEV_RULES.md](DEV_RULES.md)、[BRANCH_WORKFLOW.md](BRANCH_WORKFLOW.md) 和新鲜 Git 状态，以试用包 BUILD_INFO.json 核对源码基线。
2. 补齐上文未测的复现、截图与时序证据，确定根因和修复范围；状态从 pending 开始，不凭历史自检结果关闭问题。
3. 修改前端只改 ts/CSS/partials，运行类型检查、构建、前端组装与针对性 UI/任务回归；完成源码及新冻结包的相同场景验证。
4. 打包必须选新输出目录，保护现有试用 data、正式库、旧 EXE/DLL/OBJ 和旧构建目录；不得手改已交付 ZIP/生成 JS 来冒充源码修复。
5. 验收后在本档与主待办更新提交号、测量结果和剩余限制。公共修复选择性同步实验版，不整分支互相合并。

本轮只有问题归档，不执行修复、推送、重打包、main/master 合并或 Release/tag。当前试用包继续保持 `85d936b` 基线。
