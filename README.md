# KazariPlay V1.01

视觉小说（Galgame）本地库启动器 · **pywebview（系统 WebView）渲染 HTML UI**

原名 Minato Launcher，V1.0 起正式更名为 **KazariPlay**。V1.01 引入**收藏夹文件夹系统**（树形分组→分类 + 游戏多对多归类），全面替换旧的扁平标签体系。

## 特性

- **Kawaii Minimal 视觉**：UI 为 HTML/CSS（`kazari_play/ui/web_assets/`），由 pywebview + 系统 Edge WebView2 渲染，与设计稿 100% 一致
- **收藏夹系统（V1.01 新增）**：树形分组→分类、游戏多对多归类、手风琴侧边栏、拖拽排序、管理游戏对话框
- **游戏库主界面**：自适应卡片网格、星级评分、收藏角标、真实封面（base64 内联）
- **详情底部抽屉（Modal Bottom Sheet）**：点击卡片底部上拉，信息栏 3 列、收藏夹路径 chips、简介
- **批量选择模式**：卡片圆形勾选框 + 批量工具栏（全选/批量加入收藏夹/批量移除/从库移除）
- **设置窗口**：居中模态，常规/主题（即时预览）/快捷键/伪装/关于
- 搜索 / 排序 / 收藏 / 继续游玩 导航、无边框窗口 + HTML 标题栏拖拽
- 启动游戏、游玩时长统计、VNDB/Bangumi 元数据匹配与多源搜索
- 前后端经 **pywebview js_api**（`kazari_play/ui/web_bridge.py`）桥接

## 前置要求

- Python 3.8+
- **Microsoft Edge WebView2 Runtime**（Windows 10/11 一般已内置；缺失时用 winget 安装）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 运行

```bash
pip install -r requirements.txt
python kazari_play/main.py     # 在 KazariPlay_V1.0 目录下
```

## 目录结构

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview 入口（无边框窗口 + js_api）
│   ├── core/                  # 后端核心（扫描/启动/监控/元数据/多源搜索）
│   ├── database/              # 数据层（游戏库 + 标签/分类关联表）
│   ├── utils/                 # 工具（配置/日志/路径/图片安全加载/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api 桥（后端能力暴露给前端）
│   │   └── web_assets/        # index.html + css/ + js/（真实 UI）
│   └── resources/
├── design/                    # 设计稿（preview.html / settings_preview.html / 预览图）
└── tests/
```

## 数据

- 数据库：`%APPDATA%\KazariPlay\games.db`
- 配置：`%APPDATA%\KazariPlay\config.json`（默认浅色 Kawaii 主题）
- 从旧版 Minato Launcher 升级时，`%APPDATA%\MinatoLauncher` 下已有的数据会自动迁移
