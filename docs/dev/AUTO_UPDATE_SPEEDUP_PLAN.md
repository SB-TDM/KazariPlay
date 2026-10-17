# KazariPlay 更新提速与就绪复用计划

> 状态：**设计定稿，待实施**（2026-10-14 两轮问答定稿；同日追加**应用方式修订**：只保留手动「立即重启更新」，移除「退出时更新」；实施前不改代码）。实施完成后并入 [自动更新设计](AUTO_UPDATE_DESIGN.md)（v0.8）并记入 [CHANGELOG](CHANGELOG.md)。
> 相关：[自动更新设计](AUTO_UPDATE_DESIGN.md)、[代码审查](AUTO_UPDATE_CODE_REVIEW_20261014.md)、[开发待办](DEVELOPMENT_BACKLOG.md)（DEV-UPD-01/02/03）、[术语表](../../GLOSSARY.md)。

## 1. 背景与实测事实（2026-10-14）

| 事实 | 数据 |
|---|---|
| 直连 github.com | **完全不通**（连接 21s 超时，curl exit 28） |
| gh-proxy.com（唯一可用镜像） | **3.67–5.46 MB/s**；74.8MB 包约 14–20s |
| ghfast.top / gh.llkk.cc / github.moeyy.xyz / hub.gitmirror.com / ghproxy.cc | 全部不通（超时 / DNS 失败 / TLS 证书过期） |
| ghproxy.net | 可连但 ≈15 KB/s，不可用 |
| 重复下载 | 单轮测试完整下载 **≥5 次 ×74.8MB**（失败、重试、重装均从零重下，无缓存复用） |
| 应用窗口 | 22:51:15 助手启动 → 22:51:28 新版进程启动 → 22:51:30 窗口就绪（约 **13–16s**） |
| 本地同卷 IO 基准 | 整树 183MB `copy2` = **0.39s**；硬链接树 = 0.11s → 备份/替换**不是**瓶颈，13s 大头待埋点定位（疑：旧进程退出等待、新 exe 冷启动/杀软扫描） |
| API 限流 | 短时反复检查触发未认证 403；静默检查按设计跳过/走缓存（不在本计划范围） |

## 2. 目标与验收断言

| # | 断言 | 判定方式 |
|---|---|---|
| A1 | **死通道惩罚消除**：直连 10s 超时兜底（单次惩罚 ≤10s）；点"下载并更新"到出现非零进度 ≤12s | 真实链路日志（通道埋点） |
| A2 | **就绪复用**：下载完成 → **不点安装、直接关闭应用** → 重启 → 检查更新直接进入"就绪"、**0 重下** | zip 文件 mtime 不变 + 日志无下载开始行 |
| A3 | **应用窗口全程有数据**：等待退出 / 备份数据 / 备份程序 / 替换 / 拉起 / 新版冷启动到就绪 / 前端握手 | 下一轮实测日志 |
| A4 | 全部离线套件 + 冻结自检/受控演练通过；真实链路 A1/A2 场景通过 | 门禁与演练记录 |

## 3. 设计决策（已定稿）

### D1 下载通道与低速切换（对应 DEV-UPD-03，归并 DEV-UPD-02）

- 单候选 socket 超时：30s → **10s**（连接/读共用；死直连最多拖 10s）——"连接后零进展"的有界兜底即 DEV-UPD-02 的目标（无界等待变有界，不另做看门狗）
- 低速切换：t=15s 时已收 <5MiB（<0.35MB/s）→ 切下一候选；之后每 30s 复查，该段均速 <0.5MB/s → 继续切
- 切换语义：关闭当前流、丢弃半成品（.part）、**从零重传**；**不向用户提示**（进度回 0 即可）
- 候选顺序：**记忆通道 → 直连 → 镜像列表**（去重）；本会话内失败/被切的通道降权，不再优先
- 记忆通道同样受 10s 超时约束；失败自动回退默认顺序
- 整体重试保持现状：候选链走完为一轮，最多 2 轮（`DOWNLOAD_RETRIES=2`）
- 记忆落点：config `update.last_good_lane`（值 `direct` 或镜像前缀）；只有完成过一次完整传输的通道才写入
- 所有阈值集中为模块常量，按实测可调

### D2 默认镜像清单

- 默认改为 `["https://gh-proxy.com/", "https://ghfast.top/", "https://ghproxy.net/"]`：实测仅 gh-proxy 可用，后备保留以抗单点失效（每只后备失败成本 ≤10s）
- `update.mirror_prefixes` 配置覆盖机制不变

### D3 就绪缓存（对应 DEV-UPD-01）

- 落盘：`data/update_cache/ready.json`，字段 `{tag, version, asset_name, digest, zip, ts}`
- 命中：`check()` 确定 latest 后，若 `tag` 与 `digest` 均与发布元数据一致且 zip 存在 → 直接进入"就绪"（**不联网下载**）；解压目录缺失/无效时按需从 zip 重解压并做结构预检
- 失效：tag/digest 变化、zip 丢失或 SHA256 不符、结构预检失败 → 丢弃 `ready.json`（digest 不符的旧 zip 删除）→ 回到"发现新版本"
- 启动清理：`cleanup_update_cache` **保留被 `ready.json` 引用的完整 zip**（解压目录仍不跨重启保留），其余照删
- 提示行为：正式版启动静默检查命中"就绪"时与"发现新版本"一致提示一次；预发布维持仅手动检查；手动检查命中 → 弹层直接显示就绪
- 信任边界不变：命中条件绑定发布元数据摘要，镜像无法伪造（沿用 REV-07 的 fail-closed 模型）

### D4 埋点（只写日志，不加界面）

- 下载：每通道 `开始` / `结束（结果=成功｜超时｜低速切换｜错误；耗时；均速；字节）`，汇总 `下载完成（通道、总耗时、均速）`
- 助手（`update_apply`）：`wait_exit / backup_data / backup_program / replace / launch / 总计` 各耗时；失败时输出部分阶段
- 新版：`进程启动→窗口就绪`、`进程启动→前端握手` 两个差值（进程内时间差）

### D5 快速退出（机制就位，开关等数据）

- 机制：`立即重启更新` 拉起助手成功后 `win.destroy()`，最多 **1s 宽限**后 `os._exit(0)`（日志按行 flush；SQLite 崩溃安全）
- 开关：**初始关闭**；当 D4 数据证明"等待旧进程退出"是应用窗口大头时启用（小改动，单独提交）
- 若大头是新 exe 冷启动/杀软扫描：记录为环境成本，不硬治

### D6 更新完成提示

- `mark_startup_success` 返回「已更新到 vX」（X=当前版本）；桥 `updateFrontendReady` 返回该文案；前端在握手回调收到非空即 toast
- 预发布/正式版都显示；仅更新后首次启动弹一次

### D7 应用方式：只保留手动「立即重启更新」（2026-10-14 追加）

- **移除「退出时更新」**：前后端与关闭钩子里的 pending/exit 路径一并删除——`applyUpdate` 不再有 `exit` 模式；删除 `apply_pending_update_on_exit` 与 `_update_on_exit`；`main.py` 关闭钩子只保留 overlay 退出
- 就绪弹层只保留一个安装按钮「立即重启更新」；想稍后处理时关闭弹层或直接关应用即可（就绪缓存保证重启后 0 重下）
- 原子占用（`_claim_update_apply`）保留，作为重复点击/重试的防护
- 测试调整：删除"立即更新 vs 退出更新"双入口并发用例，改为单入口重复触发用例；`tests/test_update_ui.cjs` 的就绪弹层断言保留
- 文档：`AUTO_UPDATE_DESIGN.md` v0.8 同步删除退出时更新；审查报告 §8 的双入口描述作为历史记录保留

### D8 术语（已写入 GLOSSARY.md）

下载通道 / 低速切换 / 就绪缓存 / 应用窗口。

## 4. 实施步骤（文件级）

1. **`kazari_play/utils/updater.py`**：D1 通道切换与排序、D2 默认清单、`update.last_good_lane` 读写、D3 `ready.json` 写入/命中/失效与 `check()` 重水化、`cleanup_update_cache` 保留规则、D4 下载埋点
2. **`kazari_play/utils/update_apply.py`**：D4 助手阶段计时
3. **`kazari_play/main.py` / `ui/web_bridge.py` / `ui/web_assets/ts/*` / `partials/update.html`**：D4 新版计时；D6 握手文案与 toast；D5 快速退出机制（默认关闭）；**D7 移除退出时更新**（`applyUpdate` 去掉 exit 分支，删除 `apply_pending_update_on_exit`/`_update_on_exit`、关闭钩子调用、`updateApplyExit` 按钮与前端绑定）
4. **测试**：
   - `tests/test_updater.py`：死通道超时切换、低速切换、last-good 排序与降权、ready 命中/失效/清理保留、跳过版本优先于就绪
   - `tests/test_update_apply.py`：删除"立即更新 vs 退出更新"双入口并发用例，改为单入口重复触发用例（原子占用仍生效）
   - `scripts/frozen_smoke.py`：断言 `updateFrontendReady` 返回字符串；`tests/test_update_ui.cjs`、`tests/smoke_update_flow.py`、`scripts/verify_frozen_update.py` 回归
5. **换版 beta.2 → beta.3**（八点同步：`version.py`、前端 `package.json`/`package-lock.json`、`README.md`、`RELEASE_NOTES.md`、`VERSIONING.md` 表、`docs/README.md` 状态行、`AGENTS.md`、`CHANGELOG.md`）
6. **文档**：`AUTO_UPDATE_DESIGN.md` 并入 v0.8；`PACKAGING.md`/`testing.md` 同步；`DEVELOPMENT_BACKLOG` 的 DEV-UPD-01/02/03 标记实施并回链本计划

## 5. 验收演练（真实链路）

准备：

1. 构建 `trial-build-1.0.0-beta.3` → 冻结自检 + `scripts/verify_frozen_update.py`
2. 由该构建生成 `KazariPlay-win64.zip` + `SHA256SUMS.txt`，**替换 v9.9.9 测试 Release 的现有资产**（同时天然验证：旧缓存摘要失效会被正确丢弃）

场景 A（提速）：

- 手动检查 → 下载；预期日志：直连 ~10s 超时 → 切 gh-proxy → 首个非零进度 ≤12s；总耗时 ≈14–20s；无 21–30s 死等

场景 B（就绪复用）：

- 下载完成进入就绪 → **不点安装、直接关闭应用** → 重启 → 检查更新 → 直接"就绪"（0 重下，zip mtime 不变）
- 继续安装（就绪弹层唯一按钮「立即重启更新」）→ 新版首启 toast「已更新到 v…」→ `_old` 清理、状态清零

场景 C（应用窗口数据，决定 D5）：

- 从日志收集 A3 各阶段耗时；若 `wait_exit` 占比大 → 启用快速退出并复测；否则记录结论

## 6. 风险与回退

- 替换测试 Release 资产会改变摘要：持有旧摘要缓存的客户端按 fail-closed 拒绝（预期行为，已实测过一次）
- `ready.json` 与 zip 的一致性：命中前必验 SHA256 + 结构预检，失败即失效回退
- 参数（10s / 15s / 30s / 0.5MB/s）先按常量落地，可按实测调整，不影响架构
- 快速退出默认关闭，独立开关，随时可退

## 7. 明确不做

- 并行竞速、多连接分块下载、断点续传
- 通道切换提示、更新中独立界面（保持"无感"原则）；空窗期不加反馈，仅"更新完成"toast
- 「退出时更新」入口（本次移除，不再保留）

## 8. ADR（提议）

建议后续写 `docs/adr/0002-update-lane-switching.md`：记录两个取舍——①"阈值切换而非并行竞速"（复杂度/带宽 vs 启动延迟）；②"就绪缓存的命中必须绑定发布元数据摘要"（敢缓存的前提是信任模型不变）。
