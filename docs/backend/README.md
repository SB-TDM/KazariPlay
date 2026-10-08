# 后端总览

> 后端 = Python 3.11 + SQLite + pywebview。分四层：`core`（业务）、`database`（数据）、`ui`（桥/刷新）、`utils`（工具）。
> 逐模块细节见 [`core.md`](core.md)、[`database.md`](database.md)、[`ui-bridge.md`](ui-bridge.md)、[`utils.md`](utils.md)。

## 模块地图

### core/（业务层，经 `GameManager` 门面聚合）
| 模块 | 职责（一句话） |
|---|---|
| `game_manager.py` | **门面**：聚合 scanner/launcher/monitor/metadata/multi_source/repository，对桥暴露统一接口 |
| `game_model.py` | `Game` dataclass；`to_dict`/`from_dict` 与 DB 行互转；时长格式化 |
| `game_scanner.py` | 目录扫描、引擎识别、主 exe 选择、`identity` 生成、辅助程序黑名单 |
| `game_launcher.py` | 启动/关闭游戏进程、子进程树追踪、自定义启动路径、热键 |
| `game_monitor.py` | 运行中游戏的存活监控、退出回调、游玩计时 |
| `metadata_matcher.py` | VNDB 标题归一化搜索、多关键词回退、字段保守合并、封面 `cover_cb` |
| `multi_source.py` | 多源（VNDB/Bangumi/YMGal）搜索、合并去重、并发 + 整体超时 |
| `screenshot_service.py` | 截图内核 WGC→PrintWindow→ImageGrab 三级回退；原图 + 留边缩略图双保存 |
| `overlay_client.py` | C++ overlay 客户端单例：命名管道长连接、懒启动、退出 |

### database/（数据层）
| 模块 | 职责 |
|---|---|
| `db_manager.py` | SQLite 单例：建表、**旧库迁移**（`_ensure_column`/`DROP`）、连接与事务（`execute`/`query`/`execute_many`，锁保护） |
| `game_repository.py` | `games` 表 CRUD、按 `exe_path`/`identity` 查询、`identity` 回填、删除（连带关联） |
| `collection_repository.py` | 收藏夹树 + 游戏多对多关联 |
| `tag_repository.py` | 标签与游戏-标签关联 |

### ui/（桥接层）
| 模块 | 职责 |
|---|---|
| `web_bridge.py` | pywebview `js_api`：前端可调用的**全部**方法（数据/写操作/扫描/匹配/截图/overlay/设置…） |
| `sync.py` | `UISync` 事件域总线：后端变化 → 50ms 合并 → `window.__app.*`；线程安全的 `invalidate(domain, payload)` |

### utils/（工具层）
| 模块 | 职责 |
|---|---|
| `config.py` | `config.json` 读写（单例）、默认值 + 深合并 |
| `logger.py` | 日志（文件 + 控制台），`set_level` |
| `path_utils.py` | 应用数据目录/DB/配置/日志路径（AppData，不可写降级项目 `data/`） |
| `proxy_utils.py` | 网络 opener（代理） |
| `singleton.py` | 单例装饰器 |
| `time_utils.py` | 时间格式化 |
| `title_utils.py` | `normalize_title`（VNDB 搜索清洗 + `for_identity` 保守模式） |
| `image_safe_loader.py` | 安全图片加载（Pillow） |
| `hotkeys.py` | 全局热键注册（keyboard） |
| `vndb_client.py` | VNDB API 客户端（搜索/封面下载/重试/进度回调） |
| `bangumi_client.py` | Bangumi API 客户端 |
| `ymgal_client.py` | 月幕 API 客户端 |

## 依赖关系（谁依赖谁）

```
ui/web_bridge ──▶ core/game_manager ──▶ scanner / launcher / monitor
      │                    │             metadata_matcher ──▶ utils/vndb_client
      │                    └────────────▶ multi_source ──▶ utils/{vndb,bangumi,ymgal}_client
      ├──▶ ui/sync（被各层调用以推送前端）
      └──▶ core/{screenshot_service, overlay_client}
database/*_repository ──▶ database/db_manager（单例连接）
utils/*（无业务依赖，最底层）
```

- 依赖方向：`ui → core → database`、各层 → `utils`。`utils` 不反向依赖业务。
- 跨层数据用 `Game` 对象在 core↔database 间传递。

## 状态与线程模型（要点）

- `DatabaseManager` 全局单例，`_DB_LOCK` 串行化；每次操作短连接 + commit。
- 后台线程：扫描 `_do_scan`、匹配 `_run_vndb_match`、封面池 `_cover_pool`。
- 取消：扫描 `_scan_cancel`、匹配 `_vndb_cancel`（各自 `threading.Event`）。
- 刷新：所有前端推送经 `UISync.invalidate`，不直接 `evaluate_js`。

> 逐模块的**对象/方法/关键逻辑**见各自板块文档。
