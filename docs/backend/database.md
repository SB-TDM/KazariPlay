# database/ — 数据层

> SQLite 单库（`%APPDATA%\KazariPlay\games.db`）。`DatabaseManager` 是全局单例连接管理器；
> 三个 repository 封装各表 CRUD。所有写操作经 `_DB_LOCK` 串行化，每次短连接 + commit。

## db_manager.py — 连接与建表

**对象**：`DatabaseManager`（单例：`__new__` + `_instance`）

**连接策略**：`get_connection()` 每次新建 `sqlite3.connect(check_same_thread=False)`，`row_factory=sqlite3.Row`（**支持列名访问**，规避 ALTER 追加列导致的新老库列序差异）。

**线程安全 API**（均在 `_DB_LOCK` 内取连接、执行、关闭）
- `execute(sql, params) -> bool`：增删改
- `execute_return_id(sql, params) -> Optional[int]`：INSERT 取 `lastrowid`
- `query(sql, params) -> list[Row] | None`：查询并 fetchall
- `execute_many(statements: list[(sql, params)]) -> bool`：**单事务**批量（替代逐条 commit）

**表结构**
| 表 | 用途 | 关键列 |
|---|---|---|
| `games` | 游戏主表 | `id(PK)`、`exe_path(UNIQUE)`、`title`、`folder`、`engine`、`identity`、`cover_path`、`logo_path`、`launch_exe_path`、`is_favorite`、`rating`、`play_count`、`play_time`、`last_played`、`date_added`、`description`、`vndb_id/released/developer/length_minutes`、`category_id`、`tags`(兼容快照)、`hook_code* / translate_enabled / clean_filter_override`(实验版兼容) |
| `tags` | 标签 | `id`、`name(UNIQUE)`、`color`、`sort_order` |
| `game_tags` | 游戏-标签多对多 | `(game_id, tag_id)` PK |
| `categories` | 扁平分类 | `id`、`name(UNIQUE)`、`sort_order` |
| `collections` | 收藏夹树 | `id`、`name`、`parent_id`(NULL=分组)、`sort_order`、`icon`、`color` |
| `game_collection_link` | 游戏-收藏夹多对多 | `(game_id, collection_id)` 唯一、`sort_order` |
| `settings` | KV | `key`、`value`（存 `schema_version`） |

**索引**：`idx_title`、`idx_engine`、`idx_favorite`、`idx_identity`、`idx_game_tags_tag`、`idx_collections_parent`、`idx_gcl_unique/collection/game`。

**迁移机制**
- `_ensure_column(conn, table, col, type)`：`ALTER TABLE ADD COLUMN`，已存在则忽略（`OperationalError`）。旧库升级靠此追加新列（identity/vndb_*/category_id/logo_path/hook_* 等）。
- `_create_collections_tables` + `_migrate_to_collections`：一次性把旧 `categories/tags` 迁到 `collections`（幂等，`settings.schema_version='collections_v1'`），迁移前**自动备份** `games.db.bak.{时间戳}`；保留旧表不删。
- **移除忽略清单**：建表末尾 `DROP TABLE IF EXISTS ignored_games` 清理旧库遗留。

**时间约定**：`date_added` 等由 Python 端写 ISO 字符串（不用 DB 默认 `CURRENT_TIMESTAMP`），保证全库一致。

---

## game_repository.py — 游戏表

**对象**：`GameRepository(process_checker=None)`；`self.db = DatabaseManager()`（单例）。

**读**
- `get_by_id` / `get_by_path(exe_path)` / `get_by_identity(identity)`（identity 空返回 None）
- `get_all()`（按 title）/ `get_favorites()` / `search(keyword)`（title/engine/tags LIKE）/ `get_count()`
- `_row_to_game(row)`：行 → `Game`；**标签从 `game_tags` 加载**（`_load_tags`），收藏夹 `_load_collections`；新增列一律用**列名**访问（`row["col"] if "col" in row.keys()`）。
- `_load_tags`：`JOIN game_tags`；`_load_collections`：`JOIN game_collection_link`。

**写**
- `add(game)`：`INSERT OR REPLACE`；`date_added` 空则补当前 ISO；**标签列写空**（关联表唯一源）；已存在则保留 `hook_code/hook_code_custom/translate_enabled/clean_filter_override`（实验版兼容字段不丢）。
- `update_game(game)`：更新可编辑字段（title/engine/cover_path/logo_path/description/launch_exe_path/exe_path/folder/vndb_*/category_id/rating/identity），**不动** play_count/play_time/last_played/date_added/is_favorite；标签列写空。
- `update_favorite` / `update_rating` / `update_title`（去空白）/ `set_identity`（迁移回填）
- `record_play(game_id)`：仅更新 `last_played`；若 `process_checker()` 为真（游戏仍在跑）则**跳过**，避免游玩中误刷。
- `increment_play_time(game_id, minutes)`：`play_time += ?`。
- `delete(game_id)` → `delete_many([id])`；`delete_many(ids)`：单事务依次 `DELETE game_tags` → `DELETE game_collection_link` → `DELETE games`（去重输入）。

**依赖**：`core.game_model.Game`、`DatabaseManager`。

---

## tag_repository.py — 标签与扁平分类

**对象**：`TagRepository`；`self.db = DatabaseManager()`。

**约定**：`game_tags` 关联表是标签**唯一数据源**；`games.tags` 列仅兼容快照（写空）。

**标签**：`get_all_tags`（含 color/sort_order）、`add_tag`（`INSERT OR IGNORE`，返回 id）、`rename_tag`、`delete_tag`、`get_tag_usage_count`、`get_games_by_tag`。

**游戏-标签**：`get_game_tags(game_id)`（返回 `[{id,name,color}]`）、`set_game_tags(game_id, tag_names)`（**全量替换**：删旧 + 逐个 `INSERT OR IGNORE` tags 与关联，单事务）、`add_tag_to_game`/`remove_tag_from_game`。

**分类（扁平）**：`get_all_categories`、`add_category`、`delete_category`（先把游戏 `category_id` 归 0，再删）、`set_game_category`、`get_games_by_category`、`get_game_category`。

---

## collection_repository.py — 收藏夹（树 + 多对多）

**对象**：`CollectionRepository`；`self.db = DatabaseManager()`。

**定位**：树形收藏夹（分组=根节点 → 分类=子节点）+ 游戏多对多归属，核心是 **diff 差异算法 + 单事务**。

**CRUD**：`get_tree()`（内存组树，带 `game_count`）、`get_root_collections`、`get_children`、`get_by_id`、`create`（sort_order 自动取同级 MAX+1）、`update`（仅改非 None 字段）、`delete`（显式清理关联 + 子分类，不依赖 `PRAGMA foreign_keys`）、`reorder`、`count_collections`。

**关联（diff 算法，均 `execute_many` 单事务）**
- `add_games_to_collections(game_ids, collection_ids)`：笛卡尔积，已存在跳过，追加末尾
- `set_game_collections(game_id, ids)`：整体替换某游戏的收藏夹（删多余 + 插缺失）
- `set_collection_games(collection_id, ids)`：整体替换某收藏夹的游戏 + 排序（**删/插/改序**三类）
- `remove_games_from_collection(game_ids, collection_id)`
- `move_game_order(collection_id, game_id, new_sort_order)`
- 读：`get_games_in_collection`（按 sort_order）、`get_game_collections(game_id)`

**辅助**：`_current_links()`（`(game_id, collection_id, id)`）、`_max_sort_order(collection_id)`。

**注意**：删除收藏夹时因 self-referencing FK + SQLite 需 `PRAGMA foreign_keys=ON` 才级联，故**显式**清理子分类关联。

---

## 依赖与写库路径速查

```
GameManager ─▶ GameRepository / TagRepository / CollectionRepository
                      └────────────▶ DatabaseManager（单例）
WebBridge（写）──▶ GameManager / *_repo
封面下载完成写库：web_bridge._download_cover_bg ─▶ repository.update_game
```
