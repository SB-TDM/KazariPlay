# 变更日志（CHANGELOG）
> 注：本文是历史记录；文中路径可能反映当时的目录布局。当前源码位于 src/kazari_play/。

> 记录 KazariPlay 的开发改动。按功能块组织，最新在前。

## 未发布
- 修复手动多源搜索结果缺少简介/开发商：去重后对带 `detail` 的非 VNDB 源按 ID 并发补详情，Kungal/Hikarinagi/Shionlib 候选可正确填入“应用元数据”弹层。
- 新增应用内网络代理：`network.proxy_mode` 支持跟随系统/直连/自定义 HTTP 代理，所有元数据、封面与更新请求统一走该配置；设置页可测试 VNDB/Bangumi/Kungal 连通性，保存时校验代理地址。
- 收藏夹侧边栏新增「全部作品」入口：显示全库数量，点击清除收藏夹筛选并保留当前搜索词，供从任意收藏夹快速返回全部作品。
- 搜索框改为输入框 + 右侧可点击放大镜按钮：点击或回车立即搜索，输入仍保留 200ms 防抖；按钮支持键盘焦点与主题色悬停。
- 调整副标题栏与搜索框尺寸：导航栏高度 48px，搜索框高度 36px、最大宽度 500px，修复输入光标上下被裁切。
- 重构 CSS 为全局分层：`style.css` 声明 `tokens → reset → base → layout → components → features → utilities`，文件迁入 `global/` 与 `features/`；抽出共享 `pill-btn`/`close-btn`/`chip`/`navbtn`，并将下拉菜单、空状态下沉到 `global/components/`；`main.py` 的 `@import` 展开支持 `layer(name)`。规则集与重构前逐条一致。
- 调整视觉效果：移除 `--glow-strong` 强光晕与 `--shadow-dlg`/`.dialog` 深投影；卡片常态无光晕，active/selected 使用弱光晕。
- 修复深色主题首帧闪浅色：`main.py` 将配置主题注入 `<html data-theme>`；主题切换改为新主题绘制一帧后再恢复 transition，并跳过重复主题应用。

## 1.1.0 正式发布（2026-10-18）
- 源码迁移到 `src/kazari_play/`，按 `core/games|metadata|media|platform`、`database/repositories`、`ui/services`、`utils/clients|update|infra|domain|system` 分层；同步测试、脚本、文档与 PyInstaller 路径。
- 新增 Kungal 中文锚点：读取 Kungal 详情的 `vndb_id` 直接补 VNDB 详情，支持批量锚点预取与 VNDB 批量详情。
- 增加同名/续作编号、副标题、HD/FHD、Reflection Blue、Golden Time、SANA Edition 判断；VNDB release 仅接受官方且语言匹配的条目。
- 新增全局按源限速、429 `Retry-After` 退避、Kungal 锚点并发设置与批量进度阶段。
- 完整 unittest 65 项、冻结包 smoke、冻结更新演练通过。

## 1.1.0-beta.7 自测（2026-10-17）

- 审查修复：`update_game` 不再写 `cover_path`，封面路径只由 CoverStore / `update_cover_path` 维护，消除批量匹配/保存的旧快照覆盖异步下载或手动封面的竞态；候选应用后单独写封面路径。
- `reloadCover` 同时失效确定性缩略图（`{id}_w512.jpg`）的 base64 回退缓存。
- `setCover` 返回 `{ok, msg}`，前端按结果提示成功/失败（不再无条件提示“封面已更换”）。
- 手动封面 64MB 上限；缩略图失败清理 `.part`；迁移计数幂等（不再每次启动重复计数）。
- README/AGENTS 同步封面服务与“立即重启更新”描述；版本同步 beta.7。

## 1.1.0-beta.6 自测（2026-10-17）

- 安全边界：封面迁移只清理由 CoverStore 管理的旧变体；外部路径/旧数据目录文件保留，避免误删。
- `cover_service.enabled` 配置开关生效（默认 true）；关闭后整会话回退 base64。
- 封面术语、ADR-0002 与 beta.6 版本同步。

## 1.1.0-beta.5 自测（2026-10-17）

- 封面改为单文件模型：`covers/{game_id}.{ext}` + `thumbs/{game_id}_w512.jpg`；旧 `_vndb/_ms/_manual` 变体迁移后删除。
- 新增本地 HTTP 封面服务：只绑 `127.0.0.1`，持久化 token 与首选端口，`/c/{token}/cover/{id}?v=<mtime>-<size>`；只提供 512 缩略图，`Cache-Control: immutable`，支持 GET/HEAD；`cover_service.enabled` 可关闭。
- 前端改用 WebView 原生加载 `cover_url`（payload 内嵌 + `getCoverUrl`）；加载失败回退默认图；服务启动失败整会话回退 base64（保留一个 beta）。
- 缩略图保存/下载时后台预生成，HTTP 首次请求按 game_id 加锁懒生成；失败回退原图，原图缺失回退默认图。
- 删游戏同步删封面；启动迁移旧路径/旧变体并清理未引用文件与过期缩略图。
- 验证：Phase 0 内联 `html=` 可加载 localhost 图片；真实 34 游戏 34/34 `cover_url` 返回 200，base64 回退正常。

## 1.1.0-beta.4 自测（2026-10-17）

- 新增封面清理：启动时后台删除 `covers/` 中未被任何游戏引用的封面与过期缩略图（10 分钟宽限期）；换封面/删游戏时立即清理旧文件及其缩略图。
- 数据目录迁移：`cover_path` 仍指向旧目录时，按文件名自动迁移回当前 `covers/`，避免复制自测数据后封面失效或被误清。
- 封面文件缺失视为无封面，重新匹配/批量匹配时会重新下载。
- 恢复被清理的测试库封面：按 VNDB/Bangumi ID 重新下载 33 张并修正路径（34/34 有效）。

## 1.1.0-beta.3 自测（2026-10-17）

- 修复“应用元数据后保存回滚”：候选应用后立即用后端最新数据刷新编辑表单；此前表单仍显示旧标题/旧简介，点保存会把刚应用的元数据写回旧值。
- 元数据候选字段默认全选（可手动取消），不再默认跳过已有字段导致标题不更新。
- 保存失败改为在可见行显示 + toast（编辑态不再写到隐藏的“启动文件”行）。
- 封面异步下载/手动换封面只更新 `cover_path`，不再整行回写，避免覆盖同时进行的编辑。
- 批量元数据匹配进行中禁止保存，并返回明确提示。
- 编辑时仅当 exe 路径变化才校验文件存在（允许文件暂时缺失时编辑元数据）。

## 1.1.0-beta.2 自测（2026-10-17）

- 修复批量写回覆盖异步下载的封面路径：扫描后 26 张封面已落盘但数据库 `cover_path` 为空。
- 标题归一：CJK 提取剔除括号内容（`9nine⑤-新章(最终章)` → `新章`）；标题比较剔除 `-Subtitle-` / `～Subtitle～` / `* tagline`。
- 年份冲突处理：VNDB 精确同名优先、带版本标记候选优先；用 VNDB 标题补查另一源（只接受同年候选）。
- 版本标记补搜：目录含 HD/FHD/Reflection Blue/Golden Time 时，用已命中源的原版标题查找对应版本。
- 真实扫描 34 个：首轮 26/34；失败 8 个重试后修复 6 个（eden*、Golden Time、9-nine-新章、纯白交响曲、REFLECTION BLUE、素晴らしき日々HD）；`MashiroiroSymphonyFHD` 与 `五彩斑斓的世界HD` 因版本歧义保留手动。

## 1.1.0-beta.1 自测（2026-10-17）

- 元数据自动匹配改为多源（按设置中的混合源，默认 VNDB + Bangumi）并行搜索：每个源按“归一化标题 → 纯 CJK 提取 → 原标题”逐级尝试；跨源标题一致性校验（相似度 ≥0.7 + 发行年份一致）一致才合并，单源命中要求候选与标题相似度 ≥0.8，冲突则拒绝并提示手动确认，降低误匹配。
- 无空格驼峰标题拆分（`MashiroiroSymphonyFHD` → `Mashiroiro Symphony FHD`）；某源无结果时用已命中源的标题做跨语言桥接（解决罗马音/日文标题在 Bangumi 搜不到）；Bangumi 备用名的 `Episode.N` 后缀在相似度比较时剔除。
- 版本标记守卫：文件夹含 `FHD/HD/Remake/SANA` 而候选标题全部缺失时，优先按已有发售年份选择重制版；无年份线索才拒绝，避免把重制版匹配到原版。
- `force=True` 重匹配时覆盖已有非空元数据字段（开发商/发售日/时长/简介等），但**不覆盖用户评分**；常规匹配仍只覆盖标题/简介/ID。批量匹配入口改为 `force=True`（可刷新全部已选游戏），评分始终保持用户原值。
- 简介按 中文 → 日语 → 英文 优先选择并替换（force 时无条件替换），语言优先级相同时按 Bangumi → 月幕 → VNDB。
- 字段合并：标题/简介优先 Bangumi（取 `name_cn` 中文名/中文简介），开发商/时长优先 VNDB；VNDB 候选补充 `alt_title` 供跨语言标题校验。
- `games` 表新增 `bangumi_id`（自动迁移）：Bangumi-only 匹配也会记录 ID 并跳过重复匹配；手动应用候选同步记录来源 ID。
- 新增 `tests/test_metadata_match.py` 离线回归（合并/单源/冲突/跳过/年份重制版/force 覆盖/简介语言优先级），`test_p0_data_flow.py` 覆盖 `bangumi_id` 读写与编辑保留。
- 真实 API 小样本（10 个）：**10/10 匹配成功**且全部获得中文标题/简介；`MashiroiroSymphonyFHD` 按年份选中 2023 重制版（`v37651` / Bangumi `417463`，纯白交响曲 SANA EDITION）；「9-nine- 新章」旧数据里的错误开发商 `NanaWind` 已修正为 `Palette`。

## 1.0.1 应用内更新实证（2026-10-17）

- 功能与 `1.0.0` 相同，仅版本号递增；用于验证 `1.0.0 → 1.0.1` 的应用内自动更新完整链路（检查 / 下载 / 摘要校验 / 替换 / 首启确认）。
- 发布：tag `v1.0.1` + GitHub Release（`KazariPlay-win64.zip` + `SHA256SUMS.txt`）。
- **E2 实证（2026-10-17）**：1.0.0 发布版成功更新到 `v1.0.1`——检查（匿名 API 限流期间使用预置缓存）→ 直连下载 18.3s @4.09MB/s → 摘要校验 → 替换（总 6.20s，backup_program 0.17s 硬链接）→ 新版启动并握手确认；数据备份生成、无残留。真实匿名 API 检查待限流重置后补验。

## 1.0.0 正式发布（2026-10-17）

- 新界面世代首个正式版：包含 1.0.0 线 beta.1–beta.6 的全部改动（主界面重构、主页、评分半星制、应用内自动更新、更新提速与就绪复用、硬链接程序备份、启动自动提示、首启探测竞态修复）。
- 发布动作：`develop` 合入 `main`（快进）、tag `v1.0.0`、GitHub Release（`KazariPlay-win64.zip` + `SHA256SUMS.txt`）。
- 后续：`1.0.1` 作为 E2 真实更新演练版本。

## 1.0.0-beta.6 自测包：启动就绪探测避开首启确认（2026-10-17）

- **修复竞态**：更新后首启时，启动本地探测（`probeReadyUpdate`）与"更新完成确认"清理缓存可能并发——实测日志出现 `就绪缓存重水化失败: ... No such file`，极端情况下会在内存里显示已被删除的就绪包。现确认期间（`verify_pending`）直接返回 idle，由握手完成确认与清理后再探测。
- 验证：新增桥接用例（确认期间不探测）；全部离线套件、冻结自检与受控演练通过。
- 换版同步：`version.py`、前端 package/lock、README、RELEASE_NOTES、VERSIONING 示例、docs/README、AGENTS、本文件。

## 1.0.0-beta.5 自测包：程序备份改用硬链接（2026-10-17）

- **C1 实施（硬链接变体）**：`_backup_program` 优先 `os.link` 建立硬链接备份（同卷、不复制数据、**不移动目标文件**；FAT/exFAT 自动回退复制），本地写入从约 2×183MB 降到约 1×183MB；`_restore` 保持幂等复制并跳过同一文件（samefile），恢复中断后可重试；状态标记改为在备份前落盘（避免"备份完成但状态未写"留下无人清理的 `_old`）。
- **未采用"移动到 `_old`"**：移动会让安装目录在替换窗口内没有可运行程序，断电后无法启动自愈。
- 验证：`test_update_apply.py` 新增硬链接备份 / 复制回退 / 恢复中断重试用例；全部离线套件、冻结自检与受控演练通过。
- 换版同步：`version.py`、前端 package/lock、README、RELEASE_NOTES、VERSIONING 示例、docs/README、AGENTS、本文件。

## 1.0.0-beta.4 自测包：重启自动提示就绪（2026-10-17）

- **启动自动提示**：新增桥 `probeReadyUpdate`（本地探测 `ready.json`，不联网、无网络检查）；启动时静默检查若被禁用（预发布）或失败，则本地探测到就绪缓存时与"发现新版本"一致**自动弹层提示一次**（标题标注"基于上次检查"）；正式版静默检查命中就绪同样提示。解决"下载完成、关闭应用后重启，必须先手动检查更新才能看到就绪"的体验缺口。
- 验证：`test_updater.py`（新增 `probe_ready`）、`test_update_ui.cjs`（启动自动弹层）、冻结自检（新增 `probeReadyUpdate` 桥断言）与 `verify_frozen_update.py` 回归。
- 复测（2026-10-17）：重启后本地探测命中就绪并**自动弹层**（日志 `离线就绪命中（9.9.9）`，无下载行），用户确认步骤 1–4 全部通过；同轮 A1：直连 10.0s 失败 → gh-proxy 首字节 0.66s / 3.8s / 19.70MB/s，总下载 13.8s。
- 换版同步：`version.py`、前端 package/lock、README、RELEASE_NOTES、VERSIONING 示例、docs/README、AGENTS、本文件。

## 1.0.0-beta.3 自测包：更新提速与就绪复用（2026-10-14）

- **下载通道**（DEV-UPD-03，归并 DEV-UPD-02）：候选链改为「记忆通道 → 直连 → 镜像」；单通道 socket 超时 30s→**10s**、下载开始 15s 做**单次**低速检查（已收 <5MiB 即切）、候选链**1 轮**（失败交界面重试）；切换静默从零重传；`update.last_good_lane` 记忆成功通道（校验失败不清记忆、本次会话降权）；默认镜像更新为 gh-proxy/ghfast/ghproxy.net；逐通道埋点（首字节/耗时/均速/结果）。
- **就绪缓存**（DEV-UPD-01）：校验通过后写 `update_cache/ready.json` 并保留 zip；检查更新命中 tag+摘要时**跳过下载**直接 ready（按需重解压）；离线（检查失败）命中就绪时标注"基于上次检查"；失效含 tag/digest 变化、zip 损坏、结构预检失败、当前版本 ≥ ready 版本、跳过该版本；确认成功后**先删 ready.json 再全清**。
- **应用方式**：移除「退出时更新」，就绪弹层只保留「立即重启更新」；删除 exit 分支、`apply_pending_update_on_exit`、`_update_on_exit` 与关闭钩子调用；原子占用保留。
- **观测与体验**：助手分阶段耗时（wait_exit/backup_data/backup_program/replace/launch）、下载逐通道日志、新版「入口→窗口就绪/前端就绪」耗时；新版首启 toast「已更新到 vX」；早期观察窗口 20s→**8s**；快速退出机制就位（默认关闭，等埋点数据决定）。
- **清理与预检**：启动自愈清理安装根目录白名单 `*.new`；下载前/替换前磁盘空间预检；`ready.json` 清理顺序修正。
- 验证：`tests/test_updater.py`（31 项）、`tests/test_update_apply.py`（26 项）、`tests/test_update_ui.cjs`、`tests/smoke_update_flow.py`；冻结包自检 + `scripts/verify_frozen_update.py`（新增就绪缓存保留场景）。**真实链路复测（v9.9.9 资产 = beta.3）**：两轮更新均成功——死直连 10.0s 超时 → gh-proxy 首字节 0.78s/5.2s/14.33MB/s，单轮总下载 15.2s；应用窗口 7.11–7.58s（wait_exit ~1.6s、backup_program ~0.8s、replace ~1.5s、launch ~0.2s、新版入口→窗口 ~2.1s）；D5 快速退出不启用（wait_exit <3s 且 <30%）；就绪复用经手动检查验证通过（0 下载），重启自动提示由 beta.4 补齐。
- 版本同步：`version.py`、前端 package/lock、README、RELEASE_NOTES、VERSIONING 示例、docs/README、AGENTS、本文件。

## 自动更新审查问题修复（2026-10-14，UPD-REV-01～13）

- **恢复与健康确认**（REV-01/02/03）：启动自愈的回滚改为**独立回滚助手**（`--apply-rollback`，从更新解压缓存运行、等待当前进程退出后从程序备份恢复并重启旧版），不再在运行中的进程内覆盖自身 EXE；回滚助手拉起失败时保留状态、备份与可诊断错误，不误报成功。新版首启确认改为**前端就绪握手**（首屏数据加载成功后经桥 `updateFrontendReady` 确认），移除"窗口显示 1 秒即成功"的定时器确认。替换助手在拉起新版异常、或新版未完成启动确认即退出时，立即回滚并拉起旧版。
- **互斥与持久化**（REV-04/05/06/13）：立即更新与退出时更新共用**原子占用**（检查-置位间无窗口），助手侧增加**安装目录锁**（O_EXCL + 陈旧锁按 PID 清理），同一安装目录至多一个替换任务；状态文件改**原子写入**且失败即中止/回滚（不会留下无法恢复的替换）；用户数据备份失败与"无需备份"区分，失败即中止更新；等待旧进程超时强杀后**确认退出**，无法确认不得进入备份与替换。
- **包与校验契约**（REV-07/12）：下载校验优先使用发布元数据（GitHub API）中的 `sha256` 摘要；无摘要时仅接受**官方源直连**的 `SHA256SUMS.txt`，镜像自报校验值一律拒绝（镜像只承担文件传输）。进入 ready 前预检解压结构（唯一程序根 + `_internal` 运行资源；包内 data/screenshots/logs 拒绝），兼容旧资产单层包裹目录并规范化提取路径。
- **前端状态恢复**（REV-08～11）：就绪弹层关闭后手动检查可重新打开安装入口；下载发起与状态补查双失败时解锁弹层并给出重试反馈；进度轮询改**串行 + 代际校验**，迟到/旧代际/弹层关闭后的响应一律丢弃；启动自愈 notice（回滚/中断恢复）在首个状态响应中带出并在前端展示一次。
- **冻结演练追加修复**（`4e1238e`）：替换计划的路径断言原按"任意层级段名"匹配用户数据区，真实 PyInstaller 包内 `_internal/cv2/data/` 等程序资源会被误判，导致真实包更新被中止；改为**仅安装根级段**判定（`data`/`screenshots`/`logs`），并补断言取值与嵌套 data 目录的回归。
- 验证：`tests/test_updater.py`（23 项）、`tests/test_update_apply.py`（24 项，含真实文件锁等待恢复、并发占用、双入口单助手、备份/状态失败中止、嵌套 data 目录）、新增 `tests/test_update_ui.cjs`（5 场景）、新增 `tests/smoke_update_flow.py`（真实子进程：正常更新+握手清理 / 真实文件占用回滚 / 安装锁互斥）；冻结包 `1.0.0-beta.2-e2e` 自检 6 项与 `scripts/verify_frozen_update.py` 受控演练（真实替换助手→拉起新版→前端就绪握手→数据保全 / 真实占用回滚 / 安装锁）通过；**真实 GitHub 链路更新演练**（v9.9.9 测试 Release 资产替换为修复版构建）全链路通过：检查→下载→API 摘要校验→修复版助手替换→前端握手→清理，数据保全、无 `_old`/状态残留；同轮实测旧资产在修复前助手下按预期于替换前中止（文件未动）、资产更换后旧摘要不匹配被 fail-closed 拒绝；typecheck/build/verify_frontend（17 脚本块）/classic_boundary/bridge_contract/UI ordering/P1 frontend 通过。审查报告见 [自动更新代码审查](AUTO_UPDATE_CODE_REVIEW_20261014.md)。
- 未验证：正式发布资产的 E2 演练（`1.0.0` → `1.0.1`）与镜像回退线路的真实下载，仍待首次正式发布后执行（GitHub 测试 Release 的真实链路已验证，含摘要校验与 fail-closed）。

## 1.0.0-beta.2 自测包（2026-10-13）

- 自测包计数递增（同一开发周期的新一轮交付）：首个包含**应用内自动更新**的自测包（实现见下一节）。
- 换版同步点已更新：`version.py`、前端构建元数据、`README.md`、`RELEASE_NOTES.md`、`docs/README.md` 索引、`AGENTS.md`（清单见 [版本策略](VERSIONING.md)）。

## 应用内自动更新（2026-10-13，feature/auto-update）

- **更新核心**（`utils/updater.py`）：GitHub `releases/latest` 检查（24h 缓存；仓库尚无 Release 视为最新）；镜像回退下载（直连优先，候选列表 config 可配，SHA256 兜底）；分块进度（百分比/速度/ETA）；`SHA256SUMS.txt` 校验（失败即终止）；下载后解压（防路径穿越）；状态机 `idle / checking / up_to_date / available / skipped / downloading / ready / failed`。
- **替换助手与数据保护**（`utils/update_apply.py`）：`--apply-update` 模式（等待进程树退出、超时强杀 → 数据备份滚动 3 份 → 程序文件备份 → **白名单 + 路径断言**替换 → 失败回滚拉起旧版 / 成功写"待验证"拉起新版）；**启动自愈**（`applying` 中断恢复、`verify_pending` 两振未确认自动回滚、`rolled_back` 提示）；**两段确认**（新版窗口加载成功才清理旧文件）；WebView2 缺失显式提示（注册表检测 + winget 指引）。
- **前端**（`ts/updater.ts` + 更新弹层）：关于页「检查更新」；启动静默检查（只提示一次、不打扰）；下载进度含速度/剩余时间；**下载中锁定弹层**（`ui.ts::setSheetLocked`）；失败三键（重试 / 打开发布页 / 退出）；「跳过此版本」记入 config；「立即重启更新 / 退出时更新」。
- **发布配套**（`scripts/package_develop.py --release`）：干净树构建出固定名 `KazariPlay-win64.zip` + `SHA256SUMS.txt`；`BUILD_INFO.json` 增 `platform`/`arch`；发布版包内说明（安装位置建议）。
- 验证：`tests/test_updater.py`（19 项 0 网络单测）、`tests/test_update_apply.py`（9 项双版本演练：替换/回滚/中断恢复/两振回滚/断言拒绝/备份滚动/进程强杀）；离线 harness「更新验证」6 场景；冻结自检扩展（更新模块与桥 API）；既有全部回归通过。设计见 [自动更新设计](AUTO_UPDATE_DESIGN.md)。
- 待办：E2 真实更新演练（发布 `1.0.0` 后由 `1.0.1` 完成一次真实自动更新并记录）。

## 版本号体系重新定义（2026-10-13）

- **世代模型**：`0.x` = KazariPlay 初代（旧界面，历史 `V1.x` 全量映射）；`1.x` = 新界面世代（当前开发线 `1.0.0-beta.1`）；MinatoLauncher 不编号。`1.0.0` 起严格 semver，核心号随 `main` 发布定稿。规则与历史映射见 [版本策略](VERSIONING.md)。
- **生命周期**：`develop` 期间以 `-beta.N` 自测包计数（每包 +1，不对外发布）；取消 `-rN` 构建批次（输出目录名 = 完整版本）；`-rc.N` 为可选冻结候选；实验版主版本跟随原版，后缀简化为 `-exp.N`。
- **历史重映射**：`V1.0`→`0.1.0`、`V1.01`→`0.1.1`、`V1.02`→`0.1.2`、`V1.1`→`0.2.0`、`V1.2.x`→`0.3.x`、`V1.3`→`0.4.0`、`1.4.0-beta.1` 作废拆分归入 `0.5.0-beta.1` 与 `1.0.0` 两线；历史产物不重命名。
- **标签**：`v1.0.0` 改名 `v0.1.0`（本地与 GitHub，同提交、内容零变化）；GitHub 上附于旧标签的 V1.0 Release 按明确授权删除（正文保留于 `RELEASE_NOTES.md`）。
- 新增 [GLOSSARY.md](../../GLOSSARY.md)（领域术语表）与 [ADR-0001](../adr/0001-version-renumbering.md)；`tests/verify_frontend.py` 增加版本一致性校验（`version.py` ↔ 前端构建元数据 ↔ `README.md`）。

## 评分半星制与星级滑条（2026-10-11）

- **交互**：详情评分从「点击星星」改为**星级滑条**（五星星轨 + 覆盖其上的原生 range 输入），支持点击/拖动/键盘（←→ ±0.5）；编辑表单的评分下拉同步换成同款滑条。拖动中只更新本地显示，**松手（change）才保存一次**；滑到最左 = 未评分。
- **数值**：评分从整数扩展为 **0-5 半星制（0.5 步进）**，0 仍表示未评分；卡片评分显示（一位小数）与排序（评分优先）本就按数字处理，无需改。
- **后端**：新增 `utils/rating_utils.py`（`normalize_rating`：0-5 半星对齐 + 非法拒绝；`rating_from_100`：0-100 → 0-5 半星）；`web_bridge.setRating` 返回 bool 且仅在成功时局部刷新；`saveGame` 编辑/添加与 `applyCandidate` 的 `int()` 截断全部改走规范化；`game_manager.set_rating` 校验放宽为 0-5 半星（允许清除为 0）；`game_model.rating` 改 float；VNDB/YMGal 来源评分换算改半星（低于 1 星仍归 0）。
- **兼容**：SQLite 动态类型直接存小数（`rating INTEGER` 列无需迁移）；旧整数评分显示与排序不变。
- 验证：新增 `tests/test_rating.py`（规范化/换算边界）；离线回归新增「评分滑条」8 项（结构/拖动 4.5→90%/0=未评分/失败回退 + toast/表单回填与保存）；主页 2 场景、既有离线回归 11 项、typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract/P1 全过。

## 主页代码审查整改（R7–R14、R16，2026-10-11）

- **R7**：抽 `compareLastPlayedDesc` 共用最近游玩比较器（games.ts 时间排序与主页继续游玩/统计，原 3 处重复）。
- **R8**：抽 `cards.cardCols(width)`（含 `CARD_GAP` 常量）共用列数计算（列表窗口化 + 主页继续游玩）。
- **R9**：主页统计改为**就地更新**静态骨架节点（不再整体 `innerHTML` 重建；跳转 `onclick` 初始化时绑定一次），节点身份与焦点保留。
- **R10**：`renderHomeEmpty()` 具名化，与其余板块渲染函数一致。
- **R11**：同步 home.ts 头注释与 modules.md 的 cards.ts/games.ts 定义（补 `syncCard`/`loadCardCover`/`cardCols`/`compareLastPlayedDesc`）。
- **R12**：抽共享 `.btn-primary`（base.css）；删除 `.empty .primary` 与 `.home-empty .primary` 两处重复定义。唯一外观变化：列表空状态主按钮获得与主页一致的阴影与 hover。
- **R13**：主页视图短路列表计算与渲染——`renderAll`/`applyGamesDelta`/收藏夹树回包先判 `onHome`，避免对隐藏列表的无效 filter/sort 与 nav 信息更新。
- **R14**：去掉多余类型断言（改显式注解）。
- **R16**：合并 `[hidden]` 规则；收藏夹 chips 无变化时跳过重建（保留焦点）。**R15**（合并两处 diff 循环）按评审结论保留记录、不实施。
- 验证：主页离线回归新增“统计节点身份保留”断言；主页 2 场景、既有离线回归 11 项、typecheck/build/verify_frontend（178 id）/classic_boundary/ordering/bridge_contract/P1/图标一致性全部通过。

## 主页继续游玩块改为与列表同款复用渲染（R4，2026-10-11）

- 用户要求主页图片采用与「全部作品」相同的方法。实现：`cards.ts` 抽出 `syncCard(card, g)`（列表复用分支的字段同步 + `cover_version` 失效检测、重置封面），列表与主页共用；主页「继续游玩」改为按 id 复用节点的 diff 渲染（`_homeContinueIds` + oldMap + anchor 挪位），不再整排重建。
- 效果：数据无变化重渲染不重取封面；标题/评分/收藏变化就地同步；`cover_version` 变化只重载该卡；排序变化复用节点挪位；新卡才加载封面；运行角标由 `markRunning` 就地更新。
- 顺带保留先前修正：数量测量前先取消 `hidden`（区块初始隐藏时 `clientWidth=0` 会按上限计算宽度适配）。
- 验证：主页离线回归断言（首次 6 张封面 / 无变化 0 次重取 / 收藏变化 0 次且星标就地消失 / `cover_version` 变化仅 +1 且 dataset 更新 / 排序变化 0 次且位次正确）全过；既有离线回归 11 项与全部门禁通过。

## 主页代码复评修复（2026-10-11）

- **R1**：`setActiveCard` 改为对全部 `.card[data-id]` 匹配项置高亮——列表网格与主页卡片同 id 并存时，可见的主页卡片此前拿不到 active 环（实测：`.card.active` 只落在隐藏的网格卡上）。
- **R2**：主页**不再隐藏批量栏**（移除 `body.home-view .batchbar{display:none}`）——批量模式下点主页卡片会切换勾选，此前批量栏被隐藏导致无操作入口、且点不进详情；现与其它视图行为一致。
- **R3**：主页统计的「作品总数/收藏数」按钮补 `aria-label`（含数量与跳转去向），静态骨架同步。
- **R6**：`home.ts` 的 `_homeResizeBound` 声明移至使用函数之前（可读性）。
- 验证：审查探针确认 R1（主页卡获得 active）与 R2（主页批量栏可见）；主页离线回归 2 场景、既有离线回归 11 项、typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract/P1/图标一致性全部通过。

## 主页（默认视图）实施（2026-10-11）

- 新增 `ts/home.ts`（登记 `_JS_MANIFEST`，位于 `app.js` 之前）与 `css/home.css`：主页头部（按时段问候 + 「日期 · 今天想玩点什么？」）、继续游玩（`last_played` 倒序，数量随宽度自适应 1~6，复用现有卡片/右键/运行角标）、统计（总数/收藏数点击跳转；总游玩时长/最近一次游玩只读，总时长与后端 `format_play_time` 同口径）、收藏夹快捷（树序前 8 chips，点击走 `selectCollection` 筛选）、空库扫描引导；设计依据见 [主页设计稿](../ui/MAIN_UI_HOME_DESIGN.md)。
- 默认视图改为主页：侧栏首项「主页」(house)、「全部作品」换 `controller` 素材；`body.home-view` 由 `updateHomeView` 统一维护（主页时隐藏副标题栏与列表；批量栏、FAB 与任务进度保留）。
- 接线：`renderAll`、`applyGamesDelta`、收藏夹树回包三条链路均挂主页刷新，主页时跳过列表渲染。
- 数据零后端改动：全部派生自 `App.data.games` 与收藏夹树；`cards.ts` 抽出 `loadCardCover` 供懒加载与主页卡片共用。
- 验证：新增主页离线回归 2 场景（默认视图/跳转/排序/角标/统计/chips/窄窗 900；空库引导）全过；既有离线回归 11 项适配后全过；typecheck/build/verify_frontend（16 脚本块）/classic_boundary（清单 16）/ordering/bridge_contract/P1 与图标一致性检查全过。源码 GUI 实机复验待做。

## 收藏夹开关仅限「全部作品」视图（2026-10-11）

- 副标题栏的收藏夹开关只在「全部作品」视图存在（nav=全部作品且未筛选收藏夹）；切到「我的收藏」或收藏夹筛选时隐藏，切回后恢复（保持原激活态）。
- 隐藏只影响开关本身：抽屉若已打开保持原状，可用 Esc / 点遮罩收起。
- 实现：`updateCollectionsEntry()` 由 `renderAll()` 链路统一维护；`hidden` 配合 `.nav-collections[hidden]{display:none}` 生效（覆盖 `display:flex`）。
- 验证：离线对抗回归新增该项（可见性 / 切回恢复 / 抽屉保持原状），共 11 项全过；typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract 与图标一致性检查通过。

## 收藏夹入口移入副标题栏（2026-10-11）

- 侧栏图标列的「收藏夹」按钮移除，移入主界面副标题栏：横向对齐原抽屉关闭按钮一带（抽屉右端）、垂直居中；收起/展开均可点击。
- 抽屉头部删除「‹」收起按钮；开关兼任开合：收起时显示收藏夹图标（三栏），展开时按钮激活并切换为「‹」样式（图标由 CSS 按 `.active` 切换），`aria-expanded` / `aria-label`（收藏夹 ↔ 收起收藏夹）同步。
- 视图名宽度上限 240px → 185px，避免与开关重叠；抽屉本体（标题 / ＋新建 / 树列表）、Esc 与遮罩点击关闭、遮罩下 inert 等行为不变。
- 验证：离线对抗回归 10 项全过（含开关开合、图标切换、Esc 焦点、遮罩不穿透）；900/1366 及长名称场景开关零重叠；typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract 与图标一致性检查通过。

## 修复最大化/还原无效：窗口句柄被同名 Shell 窗口抢占（2026-10-11）

- **根因**：`_win32_hwnd()` 用 `FindWindowW(None, WINDOW_TITLE)` 按标题取句柄；Windows 11 的 Shell 内部窗口 `Windows.Internal.Shell.TabProxyWindow` 会以同名标题先被命中（探针实测：该句柄属于其它进程、类名为 `TabProxyWindow`）。于是 `ShowWindow(SW_RESTORE)` 作用到错误窗口且返回成功，应用把 `_maximized` 置回 False，主窗口却仍最大化——表现为“最大化后点还原没反应 / 疑似没绑定”。
- **修复**：`_win32_hwnd()` 改为枚举顶层窗口，取「本进程 + `WindowsForms10` 类 + 标题匹配」的主窗口并缓存，仅找不到时退回 `FindWindowW`；其余窗口逻辑保持原版（本地 `_maximized` + `_restore_win32`）。
- **验证**：pywebview 探针在真实窗口上运行同一查找算法——返回值等于本进程主窗、而 `FindWindowW` 返回同名 TabProxy 窗口；对该句柄 `SW_MAXIMIZE`/`SW_RESTORE` 均生效。typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract 通过。

## 最大化按钮改为沿用原版实现（2026-10-11）

- **背景**：曾为“最大化后无法还原”把切换改成“后端按 Win32 `IsZoomed` 判定真实状态并回传前端驱动 UI”，但实机表现为点击后按钮样式不再更新；经用户指出——原版实现是正常的。
- **处理**：
  - 后端窗口方法回退原版：`windowToggleMaximize` 恢复本地 `_maximized` 标志 + `_restore_win32`，不返回状态、不做 `IsZoomed` 判定、`windowResize` 恢复原守卫（句柄查找的后续修复见上一节）。
  - 前端 `toggleMax` 沿用原版本地切换；因按钮内容已 SVG 化（原版为文本 `□`/`❐`），状态标记改用 `aria-label`（`最大化` ↔ `还原窗口`），点击后切 `.maximized` 类并切换 `ICON.winMax` / `ICON.winRestore`。
- **验证**：typecheck/build/verify_frontend/classic_boundary/ordering/bridge_contract 通过；Playwright（桩桥）与真实 pywebview 端到端（组装 HTML + `js_api`）均确认「标签 / `.maximized` / 图标」两次点击正确往返，每次点击只调用一次 `windowToggleMaximize`。

## 修复最大化按钮（2026-10-11，已被下方“沿用原版实现”取代）

- 首次尝试：后端改用 Win32 `IsZoomed` 判定真实状态并回传前端驱动 UI。实机验证发现按钮样式不再更新，用户确认原版实现正常；该方案已回退，最终状态见上一节。

## 选中态/按钮配色还原（2026-10-11）

- 用户要求将按钮选中态及同类颜色按钮还原为原品牌渐变：撤销 C04（`948249f`）的深色操作色方案，移除 `--action-bg/--action-fg/--action-mint-bg` 变量。
- 还原范围（14 处）：侧栏 `.side-item.active`、导航 `.navbtn.active`、设置 tab `.nav-item.active`、收藏夹分组/分类 `.active`、分组展开按钮 hover、主按钮 `.pill-btn.primary`、空状态 `.primary`、FAB、运行徽标 `.card .running`、源芯片 `.src-chip.on`、管理项 `.mg-item.on`、标签 `.taglist .chip.on`——统一回到 `--grad-pink`/`--grad-mint` + `#fff`。
- 说明：这些控件的白字对比度因此回到原值（低于 4.5:1 目标），为用户明确选择；后续如需可读性调整再单独讨论。图标改动不受影响。

## 前端图标全量 SVG 化（2026-10-11）

- **新增 `ts/icons.ts`**（Bootstrap Icons 16×16、`currentColor`）并登记 `main.py::_JS_MANIFEST`（state 之后）；`ICON.*` 供卡片/收藏夹右键菜单、评分星、收藏按钮、排序箭头、窗口按钮等复用；静态图标（标题栏/侧栏/关闭按钮/关于页）在 HTML 内联同一路径。
- **替换 emoji 与符号图标**：📂🗂✏️🔄🗑🎮⚙▶★☆▸▾⋮‹＋─□❐✕ → 内联 SVG；**标题栏与关于页的笑脸保留原字符 `☺`**；移除已无消费者的 `stars()`；空状态文案不再引用 ★ 字形；窗口最大化/还原按钮以 `aria-label` 驱动图标切换（详见“最大化按钮改为沿用原版实现”）。
- **样式**：新增 `.ic`（1em 随字号、`currentColor` 随主题）；右键菜单图标位、窗口按钮、抽屉箭头、FAB 等按上下文设定尺寸。
- 验证：typecheck/build、`verify_frontend`（15 脚本块）、`test_classic_boundary`（清单同步为 15）、`test_p1_frontend`、`test_ui_ordering`、`test_bridge_contract` 通过；离线对抗回归 10 项全过；图标一致性脚本校验 HTML 图标与 `ICON` 逐字符一致、无残留字形。未做源码 GUI/原生 DPI 实机验收。

## 扫描整棵树规则与元数据匹配/封面体验优化（2026-10-08）

- **扫描整棵树规则**（`game_scanner.py`，`f5b2046`）：从扫描根向下，第一个含有效 exe 的目录视为游戏根；识别后剪枝其子树，同一游戏树下只识别一个游戏。父目录无 exe 时不剪枝，合集仍各自识别。eden\*（含 `eden PLUS MOSAIC` 特典子目录）识别为 1 个。
- **封面下载与匹配解耦**（`vndb_client`/`metadata_matcher`/`game_manager`/`web_bridge`，`3e0356c`）：`match_single/match_batch` 新增 `cover_cb`，封面改由 `web_bridge` 后台线程池下载（不重试），完成写库并定向 `reloadCover`；匹配不再等待封面。实测 35 游戏匹配约 97s（此前含封面数分钟）。详见 [封面优化](../archive/COVER_DOWNLOAD_OPTIMIZATION.md)。
- **单游戏匹配复用批量进度条 + 取消**：右键「元数据匹配」现显示进度条；批量模式下进度面板上移，避免遮挡底部批量工具栏。
- **封面下载参数可在设置页配置**（`config.py`/`vndb_client`/`web_bridge`/`settings.html`/`settings.ts`）：新增「封面下载」设置组——下载超时下拉（默认 **90 秒**，即时生效）、最大并发下拉（默认 **4**，重启生效）。此前固定 8s 对 t.vndb.org（实测单张 15~35s）过短，导致多数封面超时失败；改为可配的 90s 默认。
- **封面下载可视化**（`sync.py`/`web_bridge`/`state.ts`/`cards.ts`/`cards.css`）：新增 UISync `cover_progress` 域，封面下载中在**可见卡片**封面中心显示环形转圈，结束（成功/失败）收起；**失败不重试、不显示**。
- **多源搜索整体超时**（`multi_source.py`）：混合搜索**并发**发起各源，整次上限 **30s**，超时返回已完成候选（不再按源顺序累加等待）。
- **元数据候选字段勾选**（`web_bridge.applyCandidate`/`form.ts`/`partials/meta_apply.html`）：编辑界面选中候选后弹字段选择框（标题/开发商/发售日/评分/简介/时长/封面），**空白字段默认勾（将添加）、已有值默认不勾（覆盖需手动）**，可全选/取消全选，只应用勾选字段。
- 验证：`npm run build`、`verify_frontend`、P0(9)、P1(18)、扫描器单测、无翻译边界(4)、`py_compile` 通过。

## 1.4.0-beta.1 版本标识统一（2026-10-06）

- 原版开发线使用 `1.4.0-beta.1`，实验线使用 `1.4.0-experimental.1`；新版本来源 `src/kazari_play/version.py` 统一包版本、入口、日志、窗口标题、标题栏和关于页，Win32 句柄查找共享标题。
- 前端 package/lock 元数据同步，前端组装门禁检查版本占位符、标题/关于页与构建元数据一致。
- 发行说明补齐 V1.2～1.2.4 历史开发批次，保留已有历史编号；开发日期不当作已核实发布日期，不补建标签。现行规则见 [版本策略](VERSIONING.md)。
- 原版公共 P1 的 20 个文件更改已在本地 `develop` 集成，实验专属修复不整分支合入原版；本轮不推送、不更新稳定 `main`。
- 两版类型检查/构建、Python 语法、前端组装与各 18 项 P1 回归通过；源码 GUI 标题/关于页/布局、Win32 句柄查找及最大化/还原通过，原版无翻译边界和实验离线冒烟仍通过。

## develop 试用包（2026-10-07）

- 新增 `scripts/package_develop.py`、`scripts/develop.spec` 和 portable runtime hook，生成隔离 PyInstaller onedir 试用包；包旁 `data/` 保存测试数据库、配置、日志和截图，不读取现有用户数据。
- 冻结包内含前端、资源、原版 x64/x86 截图 Overlay；冻结 WebView 自检通过版本/关于页、原版无翻译边界、UI 新增/编辑/删除、SQLite、受控游戏启动/监控/关闭、WGC/Pillow 截图、缩略图、重命名/删除、Overlay 管道与零退出。
- 试用包为本地 `develop` 的 Windows x64 onedir，构建信息记录真实源码提交和依赖版本，源码/冻结测试均使用隔离库；包旁 data 为空时首次运行创建，不附带测试游戏或数据库。
- 原有 `KazariPlay_V1.0_build` 完整保留；未推送、未发布、未合入 `main/master`。真实游戏、多显示器、独占全屏、网络元数据和另一台干净机器仍需用户试用；本机 Pillow/pywin32 与 requirements 固定版本不同，实际版本见 BUILD_INFO.json 和 [打包说明](PACKAGING.md)。

## 实验产物启用状态同步（2026-10-06）

- 实验 `3cc0d76` 默认启用 runtime 双架构产物，`00dc19f` 修复字幕 COM 重复释放；旧产物哈希保护、双架构构建/显示/退出、管道和源码 GUI 离线验收通过。
- 原版只同步记录，运行目录与代码不变；真实游戏/AI 服务和实际打包仍未验收，本轮未推送或更新稳定 main。

## 实验版 P2 状态同步（2026-10-06）

- 实验分支 `a34ee97` 完成 AI JSON/HTTP 状态解析、仅允许 HTTPS 和文本日志隐私修复，x64/x86 受控请求与源码 GUI 拒绝路径通过；原版没有对应执行链，本次只同步待办/验证记录。
- P0/P1/P2 源码修复已本地完成，真实游戏/AI 服务及远端事项继续待验收；实验旧 EXE/DLL/OBJ 保留，新修复使用临时 EXE 验证。详细状态见 [开发待办](DEVELOPMENT_BACKLOG.md)。

## P1 截图、重新定位与任务生命周期修复（2026-10-05）

- 截图微秒命名、原子创建与冲突后缀避免覆盖，列表兼容旧时间格式；跨游戏节点、异步列表/缩略图/预览隔离，确认操作固定目标。
- 身份键保留章节与副标题，搜索清洗单独使用原规则；回填旧游戏和忽略项 identity。
- 重新定位拒绝歧义和失效目标，迁移目录内自定义启动路径、保留目录外启动器，写库失败返回明细并保留预览。
- 扫描/匹配采用单任务门禁及独立取消事件，异常释放状态；前端准确提示拒绝，迟到轮询不影响下一任务。
- 管道取消后等待挂起 I/O 与线程完成再释放，重连和位数切换不被旧线程关闭。截图冒烟真正隔离到临时目录，toast 冒烟修正 DPI 坐标。
- 原版代码已集成到本地 `develop`；公共修复选择性同步实验版，字幕序号/worker 修复只在实验版。两版数据/前端/GUI、x64/x86 构建和管道回归通过，详细提交与验证边界见 [开发待办](DEVELOPMENT_BACKLOG.md)。本轮未推送，真实服务和 P2 待处理。

## P0 数据与进程生命周期修复（2026-10-05）

- 编辑在旧记录上只更新表单字段；手动添加明确使用空 ID，返回保存结果，失败时保留表单，重复路径不覆盖用户数据。
- 游戏 ID 统一字符串，增量删除正确移除卡片；收藏夹和标签仍使用数字 ID。
- 单个/批量删除共用忽略清单与关联清理事务，数据库失败时回滚；手动 VNDB 批量取消接入事件，不再开始下一项。
- 追踪与关闭统一目标生命周期，校验 PID 创建时间，保留已确认启动链并正确关闭子进程；关闭失败不清空运行状态。
- 公共修复单独提交并选择性同步翻译实验版，原版继续无翻译；Hook PID 修复只在实验分支。已纠正的全选/路径/跨游戏删除结论不作为改造依据。
- 验证与提交记录见 `docs/DEVELOPMENT_BACKLOG.md`；真实用户库、Overlay 产物和默认分支设置未修改，本轮未推送。

## 原版与翻译实验版分离（2026-10-05）

- `main` / `develop` 定位为当前版本的无翻译原版；含翻译基线保存到 `feature/hook-translation`，不回退旧版、不重写历史。
- 原版移除翻译 UI、桥 API、Hook/AI/字幕链路和 Textractor 构建依赖，保留扫描、元数据、重新定位、截图与截图 toast。
- 旧库翻译列及旧配置保留为兼容数据，原版不执行、不向前端输出；常规写入和恢复默认不会覆盖旧翻译数据。
- 本地使用独立 worktree 与生成物；既有用户数据及实验工作区的 Overlay 产物不动。远端推送、默认分支切换、保护规则、Release 和构建开关另行决定。
- 验证进度与开发流程见 `docs/BRANCH_WORKFLOW.md`，其他审查问题仍记录在 `docs/DEVELOPMENT_BACKLOG.md`。

---

## V1.3 扫描去重与体验（2026-10-01）

- **跨文件夹去重**：游戏身份键 `identity = 引擎 | 归一化文件夹名`（新增 `utils/title_utils.py`，与 VNDB 搜索清洗共用同一套归一化）。扫描按 `exe 路径` + `identity` 双重判重，同一游戏换文件夹 / 换命名不再重复添加；入库后 `identity` 固定，不受 VNDB 标题覆盖影响。旧库启动时按文件夹名自动重算回填（幂等）。
- **引擎黑名单补充**：`unitycrashhandler`（Unity 崩溃处理器，避免被误选为主程序）、`jcef_helper`、`wacom`。
- **扫描反馈**：完成提示「新增 X 个，跳过 Y 个重复」；无新增时提示「无新游戏，跳过 N 个重复」。
- **VNDB 匹配可取消**：`match_batch` / `match_vndb_for_games` 支持 `cancel_event`；进度条取消按钮按阶段切换「取消扫描 / 取消匹配」。
- **进度可见性**：扫描后自动 VNDB 匹配新增 `batch_progress` 界面更新域，进度条不再静默。
- **修复**：批量进度框 `.show` 未恢复 `pointer-events`，导致取消按钮点击穿透、按不动。

验证：`npm run build` / `verify_frontend` / `test_scanner` / `py_compile` 全通过；真实库迁移回填 33 条（0 空 / 0 重复）；端到端扫描判重「再次扫描新增 0」。

---

## V1.3 开发（2026-09）：TypeScript 迁移 / 截图内核 / 扫描优化

日期：2026-09-12

### 前端 TypeScript 渐进迁移（全量完成）
- 17 个前端模块 JS → TypeScript：源在 `ui/web_assets/ts/`，`tsc` 编译到 `js/`（编译产物 gitignore）；`_JS_MANIFEST` 与 `main.py` 零改动
- 新增类型契约：`pywebview.d.ts`（bridge 全 API）、`globals.d.ts`（跨文件全局类型）
- 构建：`cd src/kazari_play/ui/web_assets && npm run build`

### 截图内核 WGC + 双保存 + 全屏预览
- 三级捕获回退：WGC（Windows Graphics Capture，兼容 D3D/Vulkan 独占渲染）→ PrintWindow（GDI）→ 全屏兜底
- 每次截图保存**原图（原始尺寸）+ 缩略图**（512px 宽 + 屏幕同比例、等比留边不拉伸）；缩略图随原图存放，删除/重命名联动
- 点击缩略图**全屏预览原图**（新增桥方法 `getScreenshotOriginal`）

### 扫描功能优化
- 准确性：中文启动器过滤（`启动游戏.exe` 等）、主 exe **体积优先**、文件夹名标题清洗、跳过辅助目录（SmartSteamEmu 等）
- 体验：支持**多选文件夹** + 扫描进度（按已发现游戏数估算）+ **可取消**

### 性能与体验
- 封面缓存定向失效 + 请求去重 + 缩略图生成加锁；写操作经 `games_delta` 增量刷新
- 卡片网格 DOM 窗口化（只渲染可视区 ± 缓冲，DOM 数量恒定）
- 封面动画修复（上浮跟随 / `.active:hover` 组合 / coverFade 防 DOM 重算重播）+ 手动刷新重播淡入
- 游戏运行状态即时推送（UISync `running` 域）；最后游玩时间改为 `on_exit` 记录（带进程存活检测）
- 总游玩时长最大单位改为小时；游戏窗口检测支持启动器→真游戏子进程追踪

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
- 后端新增 `getBatchProgress()` 桥方法 + `_batch_ctx` 批量任务上下文（total/done/running），`_vndb_progress` 回调更新计数，`_run_vndb_match` 结束时置 running=false。扫描后自动匹配同样计入进度（**当时**前端无轮询入口、静默；该可见性已于 2026-10 修复，见最新条目）。
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

- 同步 overlay/（含 bin/bin32 + texthook.dll）与 src/kazari_play/ 到构建目录 `KazariPlay_V1.0_build`
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
