<p align="center">
  <img src="docs/design/logo.png" width="160" alt="KazariPlay logo">
</p>

<h1 align="center">KazariPlay</h1>

<p align="center">
  面向 Windows 的视觉小说本地库启动器：扫描、整理、匹配元数据、截图，并保持自动更新。
</p>

<p align="center">
  <a href="https://github.com/SB-TDM/KazariPlay/releases/latest">
    <img alt="Release" src="https://img.shields.io/github/v/release/SB-TDM/KazariPlay?label=release">
  </a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D4">
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/SB-TDM/KazariPlay">
  </a>
</p>

<p align="center">
  <a href="https://github.com/SB-TDM/KazariPlay/releases/latest">
    <img alt="下载最新版" src="https://img.shields.io/badge/下载-最新版本-2ea44f?style=for-the-badge">
  </a>
</p>

KazariPlay 是一个无翻译原版视觉小说（Galgame）库管理工具。它不绑定特定启动器，直接扫描本地文件夹，用卡片方式展示游戏，并自动匹配 VNDB、Bangumi、Kungal 等来源的元数据。

> 本项目不包含翻译、Hook 注入或 AI 字幕功能；相关实验实现保留在独立分支 `feature/hook-translation`。

## 核心特色：你负责选文件夹，它负责把库整理好

选一个或多个游戏目录，KazariPlay 会自动把一堆“看起来像游戏”的文件夹收拾成能看的游戏库：

1. **先认人**：扫描子目录、识别主启动程序，不会把 `uninstall.exe`、补丁和启动器当成游戏供起来。
2. **防重影**：按 exe 路径和游戏身份判重，换位置、换 exe、重新扫描，都不会凭空多出一张卡。
3. **四处打听**：扫描到新游戏后自动去 VNDB、Bangumi、Kungal 等来源查资料，不用你逐个点“匹配”。
4. **顺手整理**：中文标题、中文简介、开发商、发售日、时长和封面能补就补，扫描完直接进入可浏览状态。

> 它拿不准的时候不会硬猜：自动匹配失败或结果有歧义时，会保留手动搜索入口，候选来源和字段都能自己挑。

## 功能

- **自动扫描匹配（招牌菜）**：选目录、自动识别主启动程序、去重，再把 VNDB / Bangumi / Kungal 的资料搬回来。
- **手动兜底**：自动结果不确定时，可以自己搜候选、看来源、逐字段应用，不让它替你瞎决定。
- **本地游戏库**：搜索、排序、评分、收藏夹、批量操作和重新定位。
- **网络代理**：跟随系统、直连或自定义 HTTP 代理，还能测试 VNDB / Bangumi / Kungal 通不通。
- **截图与游戏内提示**：F12 截图，WGC / PrintWindow / 全屏三级回退；游戏窗口内显示 Steam 风格 toast。
- **收藏夹与批量操作**：树形收藏夹、批量归类、批量移除、批量重新定位。
- **自动更新**：从 GitHub Releases 检查、下载、SHA256 校验，更新前备份数据库与配置，失败自动回滚。
- **原生 Windows 体验**：无边框窗口、本地 HTTP 封面服务、系统 WebView2 渲染。

## 下载与安装

前往 [Releases](https://github.com/SB-TDM/KazariPlay/releases/latest) 下载：

```text
KazariPlay-win64.zip
```

1. 解压到**非系统盘的用户可写目录**
2. 运行 `KazariPlay.exe`
3. 首次启动后按需扫描游戏目录

建议不要放在 `Program Files` 等需要管理员权限的位置。程序需要 Microsoft Edge WebView2 Runtime；Windows 10/11 通常已内置。

## 网络与代理

元数据匹配依赖 VNDB、Bangumi、Kungal 等外部服务。部分地区或网络环境下这些站点可能超时，导致匹配变慢、封面加载失败或只匹配到部分来源。

遇到连接失败、持续超时或来源不可用时，建议先开启代理软件，再在「设置 → 网络代理」中选择「跟随系统」或填写代理地址，并测试 VNDB / Bangumi / Kungal 的连通性。

应用默认使用直连；代理配置只影响应用自身的元数据、封面和更新请求。

## 数据位置

| 数据 | 默认位置 |
|---|---|
| 数据库 | `%APPDATA%\KazariPlay\games.db` |
| 配置 | `%APPDATA%\KazariPlay\config.json` |
| 日志 | `%APPDATA%\KazariPlay\logs\` |
| 封面 | `%APPDATA%\KazariPlay\covers\` |
| 截图 | 程序目录或 `KAZARIPLAY_DATA_DIR` 下的 `screenshots/` |

升级或重装前建议先备份 `%APPDATA%\KazariPlay`。旧 Minato Launcher 数据会在首次启动时尝试迁移。

## 从源码运行

需要 Python 3.11、Node.js/npm 和 WebView2。

```bash
pip install -r requirements.txt
npm --prefix src/kazari_play/ui/web_assets ci
npm --prefix src/kazari_play/ui/web_assets run build
python src/kazari_play/main.py
```

<details>
<summary>构建本地自测包</summary>

```powershell
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.2.0
```

输出目录：

```text
artifacts/trial-builds/trial-build-1.2.0/dist/KazariPlay/
```

运行 `run_develop.cmd`，数据库、配置、日志和截图会隔离在包旁 `data/`。

</details>

<details>
<summary>构建正式发布资产</summary>

```powershell
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.2.0 --release
```

会生成：

```text
KazariPlay-win64.zip
SHA256SUMS.txt
```

要求工作区干净。

</details>

## 技术栈

- Python 3.11 + pywebview 6 + SQLite
- TypeScript 前端，tsc 编译为经典脚本
- Windows Graphics Capture / PrintWindow 截图
- C++ overlay（Direct2D + 命名管道 IPC）
- PyInstaller onedir 打包

## 开发

- [架构说明](docs/ARCHITECTURE.md)
- [后端模块](docs/backend/README.md)
- [前端模块](docs/frontend/README.md)
- [开发约束](docs/dev/DEV_RULES.md)
- [测试说明](docs/dev/testing.md)
- [变更日志](docs/dev/CHANGELOG.md)
- [分支流程](docs/dev/BRANCH_WORKFLOW.md)

## 致谢

KazariPlay 的架构、交互和数据组织参考了以下项目。仅作设计与实现思路参考，不代表直接复用其代码；各项目许可证以其仓库为准。

- [ReinaManager](https://github.com/huoshen80/ReinaManager)：数据源适配、候选选择、外部 ID 桥接、限速策略与收藏夹结构参考。
- [PotatoVN](https://github.com/GoldenPotato137/PotatoVN)：封面路径组织与本地图片服务思路参考。
- [LunaTranslator](https://github.com/HIllya51/LunaTranslator)：文本过滤与实验性翻译流程的设计参考，仅用于 `feature/hook-translation`。
- [Textractor](https://github.com/Artikash/Textractor)：实验分支 Hook 方案参考，原版不包含相关代码或二进制。

同时感谢 VNDB、Bangumi、Kungal、Ymgal 等站点提供公开元数据接口。

## 许可证

GNU General Public License v3.0，详见 [LICENSE](LICENSE)。

第三方组件与许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。

---

[English README](README_EN.md)
