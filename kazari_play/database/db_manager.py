import sqlite3
import os
import shutil
import threading
from datetime import datetime
from typing import Optional, List, Tuple

from utils.path_utils import get_default_db_path
from utils.logger import get_logger

logger = get_logger()

_DB_LOCK = threading.Lock()


class DatabaseManager:
    """SQLite 数据库管理器（单例）"""

    _instance = None

    def __new__(cls, db_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if self._initialized:
            return
        # db_path 为 None 时统一固定到用户目录，避免随工作目录漂移
        self.db_path = db_path if db_path else get_default_db_path()
        self._init_database()
        self._initialized = True

    def _init_database(self):
        """初始化数据库表"""
        conn = self.get_connection()
        try:
            self._init_database_tables(conn)
            conn.commit()
        finally:
            conn.close()

    def _init_database_tables(self, conn):
        """建表 + 兼容旧库升级（接收已打开的连接，事务由调用方管理）"""
        # 游戏表
        # 注意：date_added 不再用 CURRENT_TIMESTAMP 默认值，
        # 改由 Python 端统一写 ISO 格式时间，保证全库时间格式一致。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                exe_path TEXT NOT NULL UNIQUE,
                folder TEXT NOT NULL,
                cover_path TEXT,
                engine TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0,
                play_count INTEGER DEFAULT 0,
                play_time INTEGER DEFAULT 0,
                last_played TEXT,
                date_added TEXT,
                rating INTEGER DEFAULT 0,
                logo_path TEXT DEFAULT '',
                description TEXT DEFAULT '',
                launch_exe_path TEXT DEFAULT '',
                vndb_id TEXT DEFAULT '',
                released TEXT DEFAULT '',
                developer TEXT DEFAULT '',
                length_minutes INTEGER DEFAULT 0
            )
        """)

        # 创建索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_title ON games(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON games(engine)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorite ON games(is_favorite)")

        # 设置表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # 标签表（v2.4 新增：独立管理，关联表为标签唯一数据源）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)
        # 游戏-标签关联表（多对多）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_tags (
                game_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (game_id, tag_id),
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_id)")
        # 分类表（扁平结构，单归属）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)

        # 兼容旧库：增量添加新列（CREATE TABLE 已含新列，这里处理旧库升级）
        self._ensure_column(conn, "games", "logo_path", "TEXT DEFAULT ''")
        self._ensure_column(conn, "games", "description", "TEXT DEFAULT ''")
        self._ensure_column(conn, "games", "launch_exe_path", "TEXT DEFAULT ''")
        # VNDB 元数据字段（v2 新增）
        self._ensure_column(conn, "games", "vndb_id", "TEXT DEFAULT ''")
        self._ensure_column(conn, "games", "released", "TEXT DEFAULT ''")
        self._ensure_column(conn, "games", "developer", "TEXT DEFAULT ''")
        self._ensure_column(conn, "games", "length_minutes", "INTEGER DEFAULT 0")
        # 分类归属字段（v2.4 新增；0 = 未分类）
        self._ensure_column(conn, "games", "category_id", "INTEGER DEFAULT 0")

        # 收藏夹系统（V1.0 collections）：树形收藏夹 + 游戏多对多归类
        self._create_collections_tables(conn)
        self._migrate_to_collections(conn)

    def _create_collections_tables(self, conn):
        """创建 collections + game_collection_link（收藏夹树形 + 游戏多对多关联）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                parent_id   INTEGER,                    -- NULL=根节点(分组), 非NULL=子分类
                sort_order  INTEGER DEFAULT 0,          -- 同级排序
                icon        TEXT DEFAULT '',            -- 图标(emoji 或图片路径)
                color       TEXT DEFAULT '',            -- 颜色标识
                created_at  TEXT DEFAULT '',
                updated_at  TEXT DEFAULT '',
                FOREIGN KEY (parent_id) REFERENCES collections(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_collections_parent ON collections(parent_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_collection_link (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id         TEXT NOT NULL,
                collection_id   INTEGER NOT NULL,
                sort_order      INTEGER DEFAULT 0,      -- 游戏在该收藏夹内的排序
                created_at      TEXT DEFAULT '',
                FOREIGN KEY (game_id)       REFERENCES games(id)        ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id)  ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_gcl_unique ON game_collection_link(game_id, collection_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gcl_collection ON game_collection_link(collection_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gcl_game ON game_collection_link(game_id)")

    def _migrate_to_collections(self, conn):
        """一次性迁移：categories/tags → collections（幂等，已迁移则跳过）

        迁移前自动备份 games.db → games.db.bak.{timestamp}。
        保留 categories 与 tags 数据（Phase 5 才删除旧表/字段，本阶段不删）。
        """
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
            if row and row[0] == "collections_v1":
                return  # 已迁移
        except Exception:
            pass
        # 全新数据库（无 categories/tags 表数据）时无需迁移
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
            tcnt = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        except Exception:
            cnt, tcnt = 0, 0
        if cnt == 0 and tcnt == 0:
            try:
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('schema_version', 'collections_v1')")
            except Exception:
                pass
            return

        # 备份数据库（不可逆操作）
        try:
            if os.path.exists(self.db_path):
                bak = f"{self.db_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                shutil.copy2(self.db_path, bak)
                logger.info("迁移前备份数据库 -> %s", bak)
        except Exception as e:
            logger.error("数据库备份失败，中止迁移: %s", e)
            return

        now = datetime.now().isoformat()
        try:
            # Step 2: categories → collections 根节点（作为分组）
            conn.execute("""
                INSERT INTO collections (name, parent_id, sort_order, created_at, updated_at)
                SELECT name, NULL, COALESCE(sort_order, 0), COALESCE(created_at, ''), COALESCE(created_at, '')
                FROM categories
            """)
            # Step 3: games.category_id → game_collection_link（按分类名匹配新 collection id）
            conn.execute("""
                INSERT INTO game_collection_link (game_id, collection_id, sort_order, created_at)
                SELECT g.id, c.id, 0, g.date_added
                FROM games g
                JOIN categories cat ON g.category_id = cat.id
                JOIN collections c ON c.name = cat.name AND c.parent_id IS NULL
                WHERE g.category_id != 0
            """)
            # Step 4: tags → 「标签」临时分组下的子分类
            conn.execute(
                "INSERT INTO collections (name, parent_id, sort_order, created_at, updated_at) VALUES ('标签', NULL, 99, ?, ?)",
                (now, now))
            tag_group_id = conn.execute(
                "SELECT id FROM collections WHERE name = '标签' AND parent_id IS NULL").fetchone()
            if tag_group_id:
                conn.execute("""
                    INSERT INTO collections (name, parent_id, sort_order, color, created_at, updated_at)
                    SELECT t.name, ?, COALESCE(t.sort_order, 0), COALESCE(t.color, ''), COALESCE(t.created_at, ''), COALESCE(t.created_at, '')
                    FROM tags t
                """, (tag_group_id[0],))
                # Step 5: game_tags 关联 → game_collection_link（按标签名匹配新 collection id）
                conn.execute("""
                    INSERT INTO game_collection_link (game_id, collection_id, sort_order, created_at)
                    SELECT gt.game_id, c.id, 0, ''
                    FROM game_tags gt
                    JOIN tags t ON gt.tag_id = t.id
                    JOIN collections c ON c.name = t.name
                    WHERE c.parent_id = ?
                """, (tag_group_id[0],))
            # Step 7: 标记迁移完成
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('schema_version', 'collections_v1')")
            logger.info("收藏夹系统迁移完成：collections=%s links=%s",
                        conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0],
                        conn.execute("SELECT COUNT(*) FROM game_collection_link").fetchone()[0])
        except Exception as e:
            logger.error("collections 迁移失败: %s", e)
            raise

    def _ensure_column(self, conn, table: str, column: str, type_def: str):
        """安全添加列（若已存在则跳过）"""
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")
        except sqlite3.OperationalError:
            pass  # 列已存在

    def get_connection(self):
        """获取数据库连接

        check_same_thread=False：连接可跨线程使用（由 _DB_LOCK 串行化，
        不会并发复用同一连接）。
        """
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def execute(self, sql: str, params: tuple = ()) -> bool:
        """执行 SQL（增删改），线程安全"""
        with _DB_LOCK:
            try:
                conn = self.get_connection()
                try:
                    conn.execute(sql, params)
                    conn.commit()
                    return True
                finally:
                    conn.close()
            except Exception as e:
                logger.error("数据库执行失败: %s", e)
                return False

    def execute_return_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        """执行 INSERT 并返回 lastrowid（同连接内取，线程安全）"""
        with _DB_LOCK:
            try:
                conn = self.get_connection()
                try:
                    cur = conn.execute(sql, params)
                    conn.commit()
                    return cur.lastrowid
                finally:
                    conn.close()
            except Exception as e:
                logger.error("数据库插入失败: %s", e)
                return None

    def query(self, sql: str, params: tuple = ()):
        """查询数据，线程安全

        在锁内完成查询并返回全部行（list of sqlite3.Row 或 tuple），
        连接随即关闭，避免游标/连接跨线程复用或长期不释放。
        """
        with _DB_LOCK:
            try:
                conn = self.get_connection()
                try:
                    cursor = conn.execute(sql, params)
                    return cursor.fetchall()
                finally:
                    conn.close()
            except Exception as e:
                logger.error("数据库查询失败: %s", e)
                return None

    def get_db_path(self) -> str:
        """暴露当前 db 文件路径，便于调试和备份"""
        return self.db_path

    def execute_many(self, statements: list) -> bool:
        """在单个事务中执行多条 (sql, params) 语句

        批量操作（如给 N 个游戏打标签）用它替代逐条 execute，
        避免每条 SQL 独立开连接 + commit（N 次磁盘提交）。
        """
        with _DB_LOCK:
            try:
                conn = self.get_connection()
                try:
                    for sql, params in statements:
                        conn.execute(sql, params)
                    conn.commit()
                    return True
                finally:
                    conn.close()
            except Exception as e:
                logger.error("批量执行失败: %s", e)
                return False
