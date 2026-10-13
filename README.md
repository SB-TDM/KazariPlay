# KazariPlay

视觉小说（Galgame）本地库启动器 · **pywebview（系统 WebView）渲染 HTML UI**

> **本分支（`master`）为历史遗留分支**：这里保留的是更名前后的旧版源码与旧默认分支。**当前开发线与最新说明在 [`develop`](https://github.com/SB-TDM/KazariPlay/tree/develop) 分支**；稳定线为 `main`；含 Hook/翻译的实现保留在 `feature/hook-translation`。

原名 Minato Launcher，V1.0（现编号 `0.1.0`）起正式更名为 **KazariPlay**。当前无翻译原版进入新界面世代（`1.0.0` 线）自测——主界面重构、主页与评分半星制等已并入 `develop`。

## 当前状态

| 产品线 | 分支 | 编号 |
|---|---|---|
| 无翻译原版（当前开发） | `develop` | `1.0.0-beta.N`（自测包计数，不对外发布） |
| 无翻译原版（稳定） | `main` | 下一次发布并入后更新 |
| Hook/翻译实验版 | `feature/hook-translation` | `1.4.0-experimental.1`（下次交付起 `1.0.0-exp.N`） |

版本编号体系（世代 / 自测包 / 正式发布）与历史编号映射见 [版本策略](https://github.com/SB-TDM/KazariPlay/blob/develop/docs/dev/VERSIONING.md)；完整安装、运行与打包说明见 [develop 的 README.md](https://github.com/SB-TDM/KazariPlay/blob/develop/README.md)。

## 主要特性（无翻译原版）

- **游戏库管理**：扫描文件夹批量导入（引擎识别、跨文件夹去重、进度与取消）、手动添加、自适应卡片网格、星级评分（0.5 半星）、收藏、搜索/排序
- **详情与操作**：底部抽屉详情、启动与游玩时长统计、编辑、批量选择、批量重新定位
- **收藏夹**：树形分组→分类、游戏多对多归类、手风琴侧边栏、拖拽排序
- **元数据**：VNDB / Bangumi / YMGal 多源匹配（单条、批量、扫描后自动）
- **截图**：WGC 三级回退截图（原图 + 缩略图）、Steam 式截图管理、游戏内 C++ Overlay toast（命名管道）
- **界面**：Kawaii 双主题（浅/深）、无边框窗口、设置（主题/快捷键/伪装/关于）
- **技术栈**：Python 3.11 + pywebview 6 + SQLite；前端 TypeScript 内联为单 HTML；C++ Overlay

## 运行（源码）

```bash
pip install -r requirements.txt
npm --prefix kazari_play/ui/web_assets ci
npm --prefix kazari_play/ui/web_assets run build
python kazari_play/main.py
```

> 以上步骤请在 `develop` 分支执行；`master` 分支为旧版源码，仅供参考。
