import sqlite3
import os
import threading
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
