# KazariPlay 自动更新设计

> 状态：**v0.2 设计定案（2026-10-13），未实施**。决策依据为 2026-10-13 逐轮问答与三份开源参考的对照（见 §0）。
> **最高原则**：**① 用户数据保护第一**——更新流程任何环节都不得损坏、丢失或搬移用户数据；**② 原生无感体验**——更新存在感尽量低、界面融入应用自身视觉，不做第三方工具风格的独立窗口。
> 质量标准：按**对外多人分发**设计（清晰错误、可回滚、不静默失败）。
> 范围：应用内自动更新（检查 / 提示 / 下载 / 替换 / 回滚）；目标形态为便携文件夹版（PyInstaller onedir，数据在包旁 `data/`）。

## 0. 参考实现与取舍（2026-10-13）

| 参考 | 是什么 | 借鉴 | 不取 |
|---|---|---|---|
| [qtAutoUpdateApp](https://github.com/duolabmeng6/qtAutoUpdateApp) | PyInstaller 应用更新框架（Qt 演示） | 镜像回退思路、启动时自愈清理残留、进度含速度/剩余时间、跳过此版本、zip 中文文件名 UTF-8 修复 | HTML 抓取更新信息（GitHub 改版即挂；我们用 API）、onefile 自替换（保持 onedir+助手）、Actions 全自动发布（版本号人工定稿） |
| [Minecraft Client Updater](https://github.com/NamelessXiaoJiang/ClientUpdater) | Forge 客户端 mod + Flask 服务端，同步 mod 与配置 | 无感更新理念（无更新零打扰）、"镜像/覆盖"同步语义、完整性修复（留后续） | 自建更新服务器（GitHub Releases 免运维等价）、文件级增量同步（发行物不可分割） |
| [XiaoqiangUpdater](https://github.com/xiaoqiangclub/XiaoqiangUpdater) | 通用 Python 更新器（独立 updater.exe + tkinter） | **失败/取消必回启动旧版**、失败界面三键（重试 / 手动更新 / 取消） | MD5（用 SHA256）、校验失败可"继续安装"（**必须终止，无绕过**）、字符串版本比较（用三元组）、zip 覆盖解压无回滚（用 `_old` 回滚 + 白名单） |

## 1. 目标与边界

- 对外分发的正式版可自动升级到新的正式版；更新源为 **GitHub API**（仓库 `SB-TDM/KazariPlay`，公开）。
- 支持形态：便携文件夹版（`KazariPlay.exe` + `_internal/` + 附随文档；数据在包旁 `data/`）。
- **不做（v1）**：源码运行的自动更新（界面提示用发布包）；安装器；抢先体验渠道；断点续传；文件级增量更新。
- 带预发布后缀（`-beta.N` / `-exp.N`）的包默认**关闭自动检查**（关于页可手动检查）；更新只认正式 Release。
- 自动更新自 `1.0.0` 起随包发布——第一个正式版必须包含本功能，后续版本才能自助升级。

## 2. 数据保护（最高原则的落地）

- **替换白名单**：更新只替换 `KazariPlay.exe`、`_internal/` 与附随说明文档；`data/`、`screenshots/`、`logs/` 永不进入替换集，助手在替换前对路径做**代码级断言**（命中禁用区即中止）。
- **更新前自动备份**：替换前把 `data/games.db` 与 `data/config.json` 复制到 `data/backup/<时间戳>/`，滚动保留最近 **3** 份。
- **失败语义**：下载/校验失败 → 不进入替换阶段；替换阶段失败 → 用 `_old/` **自动回滚**；无论成败**必拉起可用版本**（成功=新版，失败/取消=旧版）——绝不把用户留在"没有应用"状态。
- **校验失败必须终止，不提供绕过**（明确拒绝 XiaoqiangUpdater 式"风险自负继续安装"）。
- 更新器**不读取、不迁移、不重写**任何用户数据文件；数据库结构迁移只由新版启动时自带的既有迁移流程（`_ensure_column`）完成。
- **数据位置原则**：便携包 `data/` 随包存放；分发文档与包内 README 建议解压到**非系统盘**；更新器不向 `C:` / `%APPDATA%` 写入任何数据；图片类数据（covers / screenshots）在便携模型下始终位于包内 `data/`，不入 `%APPDATA%`。（源码运行模式的 `%APPDATA%` 路径属开发模式遗留，图片数据不在 `%APPDATA%` 的方向记为后续优化。）

## 3. 体验（第二原则的落地）

- **应用内弹层**（复用现有 Kawaii 组件视觉），不做独立更新器窗口；**无更新零打扰**，启动发现新版只提示一次；24h 检查缓存。
- 下载进度展示：百分比 / 已下载 / 总大小 / **速度 / 剩余时间**（复用批量进度条组件）；**下载中禁止关闭弹层**。
- 更新执行尽量无感：助手**无窗口**（无黑框闪窗）、零交互替换；完成后自动启动新版。
- 完成选项：**立即重启更新** / **退出时更新**（挂起，窗口关闭钩子触发）。
- 失败界面：**重试 / 打开发布页（手动更新兜底）/ 退出**；"退出时更新"挂起期间失败则取消挂起并提示。
- "**跳过此版本**"记入 `config.json`（`update.skipped_version`），不再提示该版本。

## 4. 更新源与资产契约

- 检查：`GET https://api.github.com/repos/SB-TDM/KazariPlay/releases/latest`（未认证；遵守系统代理；24h 缓存；60 次/小时限流足够）。
  - 读取：`tag_name`（`v1.0.1` → `1.0.1`）、`body`（更新说明）、`assets[]`。
- **镜像回退链**：**直连优先**，失败后依次尝试**镜像前缀候选**（候选列表放 `config.` 可更新，避免死域名锁死旧客户端）；所有通道下载完成后以 **SHA256** 兜底防篡改。
- 发布资产（固定命名）：
  - `KazariPlay-win64.zip`：干净包（程序文件 + 包内资源；**不含** `data/`、构建缓存、会话产物）。
  - `SHA256SUMS.txt`：含 zip 的 SHA256。
  - 备用直链（不依赖 API）：`https://github.com/SB-TDM/KazariPlay/releases/latest/download/KazariPlay-win64.zip`。
- 版本比较：`主.次.修订` 三元组；预发布后缀版本默认视为"不提示更新"。

## 5. 流程状态机

```
Idle ─启动后台检查(24h 缓存) / 关于页手动─> Checking
Checking ─无新版─> Up-to-date
Checking ─有新版─> Available ──────────── 弹层：版本 / 大小 / 说明摘要
   │                                        [跳过此版本] [稍后] [下载并更新]
   ├─跳过─> Skipped（记入 config）
   └─下载并更新─> Downloading（直连→镜像回退；进度含速度/ETA；失败自动重试 2 次）
Downloading ─网络/校验失败─> Failed（重试 / 打开发布页 / 退出；日志）
Downloading ─SHA256 通过─> Ready
Ready ─立即重启更新─> Applying（拉起助手，主程序退出）
Ready ─退出时更新─> 标记 pending，窗口关闭钩子触发 Applying
Applying ─备份数据 → 白名单替换成功─> 自动启动新版
Applying ─替换失败─> 自动回滚旧文件 → 启动旧版 + 明确提示
```

## 6. 更新助手（新版本 exe 的 `--apply-update` 模式）

- 主程序在退出前拉起：`<新包解压目录>\KazariPlay.exe --apply-update --pid <旧进程ID> --target <安装目录>`。
- 助手步骤：
  1. 等待旧进程及子进程退出（WebView2 子进程持有文件；超时按进程树强杀）；
  2. **备份用户数据**（`data/games.db`、`data/config.json` → `data/backup/`，滚动 3 份）；
  3. 目标程序文件移入 `_old\<时间戳>\`；
  4. 按**白名单 + 路径断言**复制新程序文件；
  5. 成功：启动新版、清理 `_old\` 与临时目录；失败：`_old\` 移回（回滚）、启动旧版并提示；
  6. **启动自愈**：新版启动时清理上次更新残留（`_old\`、下载临时目录），覆盖"退出时更新被断电/崩溃打断"的情况。
- 助手无窗口运行；日志：`logs/update.log`。

## 7. 发布流程配套（增补到 PACKAGING 清单）

每次正式发布产出三件套：

1. `KazariPlay-win64.zip`——干净包（固定名，不带版本；zip 内 `BUILD_INFO.json` 含真实版本）；
2. `SHA256SUMS.txt`——zip 的 SHA256；
3. Release 正文——更新说明（更新器展示的摘要来源）。

`scripts/package_develop.py --release`：在自测包构建之外，额外生成 ①+②（从干净 tree 构建；拒绝工作区脏状态）。发布与推送仍由维护者在本地执行（不引入 CI）。

## 8. 实现位置（提案）

- 后端：`kazari_play/utils/updater.py`（检查/镜像回退下载/SHA256/状态机）；`ui/web_bridge.py` 暴露 `checkUpdate` / `downloadUpdate` / `applyUpdate` / `getUpdateState`；`main.py` 增加 `--apply-update` 入口、关闭钩子联动与启动自愈。
- 前端：`ts/settings.ts` 关于页接线；新增 `ts/updater.ts`（登记 `main.py::_JS_MANIFEST`）；进度复用批量进度条组件。
- 配置：`update.enabled`（预留）、`update.last_check`、`update.skipped_version`、`update.mirror_prefixes`（镜像候选）。

## 9. 验收（草案）

- **数据保护专项**：替换集路径断言（data/screenshots/logs 命中即拒绝）；备份生成与滚动；故障注入（替换中途杀进程）→ 回滚成功、旧版可启动；更新前后 `data/` 内容哈希一致。
- 离线：模拟 API 响应（有新版 / 无新版 / 资产缺失 / SHA256 不符 / 直连失败走镜像）→ 状态机与拒绝逻辑断言。
- 集成：本地两版本目录演练替换、回滚、`data/` 保留（不依赖真实发布）。
- 真实：发布 `1.0.1` 后由 `1.0.0` 完成一次真实自动更新（首个更新人工验证并记录）。

## 10. 未决与后续

- 断点续传（v1 不做，整体重试 2 次）。
- 代码签名证书（v1 不做；SmartScreen 警告写入用户文档）。
- 抢先体验渠道；安装器形态。
- 完整性修复（缺文件时从 `releases/tags/v{当前版本}/download/KazariPlay-win64.zip` 重下当前版本，镜像模式思路）。
- 源码运行模式的图片数据不入 `%APPDATA%` 的数据路径优化。
