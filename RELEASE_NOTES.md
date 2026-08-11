# KazariPlay V1.01 发行说明

> 发布日期：2026-08-11
> 项目：KazariPlay（原名 Minato Launcher，V1.0 起正式更名）
> 仓库：github.com/SB-TDM/KazariPlay

## 主要更新（V1.01）

### 收藏夹文件夹系统（全新）
- **树形收藏夹**：分组→分类两级结构，游戏可同时归入多个收藏夹（多对多）
- **数据迁移**：启动时自动将旧分类/标签迁移为收藏夹（collections + game_collection_link 表），迁移前自动备份数据库，幂等可重复执行
- **手风琴侧边栏**：点击分组展开/收起子分类（互斥单开），点击分组名直接筛选
- **拖拽排序**：收藏夹内卡片拖拽调整顺序并持久化（sort_order）
- **管理游戏对话框**：右键收藏夹批量勾选游戏归属（支持分组聚合子分类）

### 交互与 UI
- 详情页显示收藏夹完整路径（分组/分类），可一键进入收藏夹管理
- 右键菜单加图标 + 分段（参考 ReinaManager 交互）
- 卡片 hover 封面微放大、当前详情卡片高亮描边
- 批量操作/收藏夹 CRUD 增加操作反馈 toast

### 清理与优化
- 移除编辑表单的标签/收藏夹编辑（归属统一由收藏夹系统管理）
- 清理旧标签系统的死代码（前端 JS/CSS）
- 封面更新后自动刷新卡片（VNDB 匹配/手动更换即时生效）
- 已匹配游戏可强制重新匹配 VNDB

---

# KazariPlay V1.0 发行说明

> 发布日期：2026-08-07
> 项目：KazariPlay（原名 Minato Launcher，V1.0 起正式更名）
> 仓库：github.com/SB-TDM/KazariPlay

## 简介

**KazariPlay** 是一款面向视觉小说（Galgame）玩家的本地游戏库启动器，
支持统一管理 KRKR、Ren'Py、Unity 等主流引擎作品，提供收纳、快速启动、
游玩记录、收藏、分类与标签检索，并集成 VNDB / Bangumi 元数据匹配。

界面采用「深色 Kawaii」设计语言——奶油白 / 深紫灰双主题、糖果色点缀、
大圆角贴纸卡片与胶囊按钮，由 **pywebview + 系统 Edge WebView2** 渲染 HTML/CSS，
与设计稿 100% 一致。

## 主要特性

### 游戏库管理
- 扫描文件夹批量导入（按文件夹聚合、引擎识别、汉化版优先）
- 手动添加游戏、自定义启动文件、更换封面
- 自适应卡片网格：星级评分、收藏角标、真实封面（base64 内联）
- 搜索 / 排序 / 收藏 / 继续游玩（最近 7 天）导航与分类筛选

### 详情与操作
- 详情底部抽屉（Modal Bottom Sheet）：信息栏 3 列、糖果色标签、简介
- 点击星级直接评分；启动 / 编辑 / 打开目录 / 删除
- 批量选择模式：全选、批量加/移除标签、移动分组、批量删除、批量 VNDB

### 标签与分类
- 标签管理抽屉：当前游戏绑定/移除标签，自动创建全局标签
- 扁平分类（自定义分组）、右键管理分组

### 元数据（VNDB / Bangumi）
- 单条 / 批量 / 扫描后自动 VNDB 匹配（标题更新为 VNDB 正式名、填充开发商/评分/简介/发售日/封面）
- 多源搜索手动匹配候选并一键应用
- 已取消本地速率限制

### 设置与体验
- 设置窗口：常规（封面尺寸、日志级别、显示日志窗口）、主题（浅色/深色即时预览）、快捷键、伪装、关于
- 深色主题：低饱和深紫灰背景 + 夜用糖果色，弱化发光
- 无边框窗口：标题栏拖拽、四边/四角自由缩放、任务栏点击最小化、启动居中
- 全局统一滚动带、统一确认/输入弹窗

## 技术栈

- **前端**：HTML / CSS / JavaScript（`ui/web_assets/`）
- **渲染**：pywebview 6 + Microsoft Edge WebView2
- **后端**：Python 3.8+（标准库为主）
- **数据**：SQLite（游戏库 + 标签/分类关联表）
- **元数据**：VNDB API、Bangumi API

## 系统要求

- Windows 10/11
- Python 3.8+
- Microsoft Edge WebView2 Runtime（缺失时安装）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 安装与运行

```bash
pip install -r requirements.txt
python kazari_play/main.py
```

## 数据与升级

- 数据库：`%APPDATA%\KazariPlay\games.db`
- 配置：`%APPDATA%\KazariPlay\config.json`（默认浅色主题）
- 从旧版 Minato Launcher 升级：`%APPDATA%\MinatoLauncher` 下的数据自动迁移

## 已知问题

- VNDB 官方 API 存在约 200 次/小时的限速；取消本地限制后，短时间内大量请求可能触发 429，需等待下一小时窗口
- 任务栏图标在个别系统可能受 Windows 图标缓存影响，需刷新资源管理器后显示
- 无边框窗口的边缘缩放基于 HTML 手柄实现，在极高 DPI 缩放下可能略有延迟

## 后续计划

- 游戏库导出 / 导入（JSON/CSV 备份）
- 沉浸模式（F11）
- 全局快捷键（紧急隐藏、静音）
- 列表 / 网格视图切换
