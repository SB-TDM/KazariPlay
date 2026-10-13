# KazariPlay 自动更新设计

> 状态：**v0.1 设计定案（2026-10-13），未实施**。决策依据为当日逐轮问答；实施前不再改动本节的边界，只增补细节。
> 范围：应用内自动更新（检查 / 提示 / 下载 / 替换 / 回滚）；目标形态为便携文件夹版（PyInstaller onedir）。
> 质量标准：按**对外多人分发**设计（清晰错误、可回滚、不静默失败），不按单机脚本标准。

## 1. 目标与边界

- 对外分发的正式版可自动升级到新的正式版；更新源为 **GitHub API**（仓库 `SB-TDM/KazariPlay`，公开）。
- 支持形态：便携文件夹版（`KazariPlay.exe` + `_internal/` + 附随文档；数据在包旁 `data/`）。
- **不做（v1）**：源码运行的自动更新（界面提示用发布包）；安装器；抢先体验渠道；断点续传。
- 带预发布后缀（`-beta.N` / `-exp.N`）的包默认**关闭自动检查**（关于页可手动检查）；更新只认正式 Release。
- 自动更新自 `1.0.0` 起随包发布——第一个正式版必须包含本功能，后续版本才能自助升级。

## 2. 更新源与资产契约

- 检查：`GET https://api.github.com/repos/SB-TDM/KazariPlay/releases/latest`（未认证；遵守系统代理，复用 `utils/proxy_utils.get_opener`；限流 60 次/小时，24h 缓存足够）。
  - 读取：`tag_name`（`v1.0.1` → `1.0.1`）、`body`（更新说明）、`assets[]`。
- 发布资产（固定命名，见 §6）：
  - `KazariPlay-win64.zip`：干净包（程序文件 + 包内资源；**不含** `data/`、构建缓存、会话产物）。
  - `SHA256SUMS.txt`：含 zip 的 SHA256。
  - 备用直链（不依赖 API）：`https://github.com/SB-TDM/KazariPlay/releases/latest/download/KazariPlay-win64.zip`。
- 版本比较：`主.次.修订` 三元组，仅比较正式版；预发布后缀版本默认视为"不提示更新"。

## 3. 体验流程（状态机）

```
Idle ─启动后台检查(24h 缓存) / 关于页手动─> Checking
Checking ─无新版─> Up-to-date
Checking ─有新版─> Available ──────────── 弹层：版本 / 大小 / 说明摘要
   │                                        [跳过此版本] [稍后] [下载并更新]
   ├─跳过─> Skipped（记入 config：update.skipped_version，不再提示该版本）
   └─下载并更新─> Downloading（进度条；失败自动重试 2 次）
Downloading ─网络/校验失败─> Failed（toast + 关于页状态 + 日志；可重试）
Downloading ─SHA256 通过─> Ready
Ready ─立即重启更新─> Applying（拉起助手，主程序退出）
Ready ─退出时更新─> 标记 pending，窗口关闭钩子触发 Applying
Applying ─替换成功─> 自动重启新版
Applying ─替换失败─> 自动回滚旧文件 + 明确提示（不静默）
```

- 检查在启动后**后台线程**执行，不阻塞窗口；结果缓存 24h；发现新版启动时只提示一次，不弹窗轰炸。
- 关于页常驻状态文案：`已是最新` / `发现新版本 vX` / `下载中 xx%` / `更新失败（可重试）`。

## 4. 更新助手（新版本 exe 的 `--apply-update` 模式）

- 主程序在退出前拉起：`<新包解压目录>\KazariPlay.exe --apply-update --pid <旧进程ID> --target <安装目录>`。
- 助手步骤：
  1. 等待旧进程及其子进程退出（WebView2 子进程持有文件；超时后按进程树强杀）；
  2. 目标目录程序文件移入 `_old\<时间戳>\`；
  3. 从解压目录复制新程序文件（**白名单**：`KazariPlay.exe`、`_internal/`、附随说明文档）；
  4. `data/`、`screenshots/`、`logs/` 与任何用户文件永不进入替换集；
  5. 成功：启动新版并清理 `_old\` 与临时目录；失败：`_old\` 移回原位（回滚）并提示。
- 助手运行日志：`logs/update.log`。

## 5. 安全

- HTTPS + **SHA256 校验**（先校验后替换；`SHA256SUMS.txt` 缺失或不符即终止并提示）。
- **不做代码签名（v1）**：SmartScreen 警告为已知限制（写入用户文档）；签名证书列入后续待办。
- 接口异常、资产缺失、校验失败、替换失败——全部给出明确提示与日志，不静默、不降级成"看起来更新了"。

## 6. 发布流程配套（增补到 PACKAGING 清单）

每次正式发布产出三件套：

1. `KazariPlay-win64.zip`——干净包（固定名，不带版本；zip 内 `BUILD_INFO.json` 含真实版本）；
2. `SHA256SUMS.txt`——zip 的 SHA256；
3. Release 正文——更新说明（更新器展示的摘要来源）。

`scripts/package_develop.py --release`：在自测包构建之外，额外生成 ①+②（从干净 tree 构建；拒绝工作区脏状态）。

## 7. 实现位置（提案）

- 后端：`kazari_play/utils/updater.py`（检查/下载/校验/状态机）；`ui/web_bridge.py` 暴露 `checkUpdate` / `downloadUpdate` / `applyUpdate` / `getUpdateState`；`main.py` 增加 `--apply-update` 入口与关闭钩子联动。
- 前端：`ts/settings.ts` 关于页接线；如需新模块 `ts/updater.ts`（登记 `main.py::_JS_MANIFEST`）；下载进度复用批量进度条组件。
- 配置：`update.enabled`（预留）、`update.last_check`（时间戳缓存）、`update.skipped_version`。

## 8. 验收（草案）

- 离线：模拟 API 响应（有新版 / 无新版 / 资产缺失 / SHA256 不符）→ 状态机与拒绝逻辑断言。
- 集成：本地两版本目录演练替换、回滚、`data/` 保留（不依赖真实发布）。
- 真实：发布 `1.0.1` 后由 `1.0.0` 完成一次真实自动更新（首个更新人工验证并记录）。

## 9. 未决与后续

- 代理与镜像：v1 用系统代理直连；国内网络反馈差时再评估镜像。
- 断点续传：v1 不做（整体重试 2 次）。
- 代码签名证书；抢先体验渠道；安装器形态。
