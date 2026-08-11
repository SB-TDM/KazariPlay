"""游戏管理门面 - 对外统一接口，协调 scanner/launcher/monitor/repository"""
from typing import List, Optional, Dict, Any, Callable, Tuple
from core.game_model import Game
from core.game_scanner import GameScanner
from core.game_launcher import GameLauncher
from core.game_monitor import GameMonitor
from database.game_repository import GameRepository
from utils.logger import get_logger

logger = get_logger()


class GameManager:
    """游戏管理门面

    对外聚合所有子模块能力，调用方只需要面对这一个类。
    """

    def __init__(self, db_path: Optional[str] = None):
        # 必须先让 DatabaseManager 用指定 db_path 完成初始化，
        # 再创建 GameRepository（后者内部会复用这个单例）。
        # db_path=None 时由 DatabaseManager 内部走 get_default_db_path()
        # 固定到用户目录，避免随工作目录漂移。
        from database.db_manager import DatabaseManager
        DatabaseManager(db_path=db_path)

        self.repository = GameRepository()
        self.scanner = GameScanner()
        self.launcher = GameLauncher()
        self.monitor = GameMonitor(self.repository, self.launcher)
        from database.tag_repository import TagRepository
        self.tag_repo = TagRepository()
        from database.collection_repository import CollectionRepository
        self.collection_repo = CollectionRepository()

    # ---------- 查询 ----------

    def get_all_games(self) -> List[Game]:
        """获取所有游戏"""
        return self.repository.get_all()

    def get_game(self, game_id: str) -> Optional[Game]:
        """根据 ID 获取单个游戏"""
        return self.repository.get_by_id(game_id)

    def get_favorites(self) -> List[Game]:
        """获取收藏列表"""
        return self.repository.get_favorites()

    def search(self, keyword: str) -> List[Game]:
        """按标题/引擎/标签搜索"""
        return self.repository.search(keyword)

    def get_count(self) -> int:
        """游戏总数"""
        return self.repository.get_count()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        games = self.repository.get_all()
        total_time = sum(g.play_time for g in games)
        fav_count = sum(1 for g in games if g.is_favorite)
        return {
            "total_games": len(games),
            "total_play_time_minutes": total_time,
            "favorite_count": fav_count,
            "engines": self._count_by_engine(games),
        }

    def _count_by_engine(self, games: List[Game]) -> Dict[str, int]:
        stats: Dict[str, int] = {}
        for g in games:
            key = g.engine or "未知"
            stats[key] = stats.get(key, 0) + 1
        return stats

    # ---------- 扫描/添加/删除 ----------

    def scan_and_add(self, folder: str) -> Tuple[int, List[Game]]:
        """扫描文件夹并添加新游戏，返回 (新增数量, 新增游戏列表)"""
        games = self.scanner.scan(folder)
        new_games = []
        for game in games:
            # 跳过已存在的（按 exe_path 判重）
            if self.repository.get_by_path(game.exe_path):
                continue
            if self.repository.add(game):
                new_games.append(game)
        return len(new_games), new_games

    def add_game(self, game: Game) -> bool:
        """手动添加单个游戏（标签同步写入关联表）"""
        if not self.repository.add(game):
            return False
        return self.tag_repo.set_game_tags(game.id, game.tags)

    def delete_game(self, game_id: str) -> bool:
        """删除游戏。若该游戏正在运行，先关闭"""
        if self.launcher.current_game_id == game_id and self.launcher.is_running():
            self.close_game()
        return self.repository.delete(game_id)

    # ---------- 收藏/评分/标签 ----------

    def set_favorite(self, game_id: str, is_favorite: bool) -> bool:
        """设置收藏状态"""
        return self.repository.update_favorite(game_id, is_favorite)

    def toggle_favorite(self, game_id: str) -> bool:
        """切换收藏状态，返回切换后的状态"""
        game = self.repository.get_by_id(game_id)
        if not game:
            return False
        new_state = not game.is_favorite
        self.repository.update_favorite(game_id, new_state)
        return new_state

    def set_rating(self, game_id: str, rating: int) -> bool:
        """设置评分（1-5）"""
        if not 1 <= rating <= 5:
            return False
        return self.repository.update_rating(game_id, rating)

    def rename_game(self, game_id: str, new_title: str) -> bool:
        """手动修改游戏标题"""
        if not new_title or not new_title.strip():
            return False
        if not self.repository.get_by_id(game_id):
            return False
        return self.repository.update_title(game_id, new_title)

    def update_game(self, game: Game) -> bool:
        """更新游戏全部可编辑字段（标题/引擎/标签/Logo/封面/描述/分类）

        保留 play_count/play_time/last_played/date_added/is_favorite/rating 不变。
        标签同步写入关联表。
        """
        if not self.repository.update_game(game):
            return False
        return self.tag_repo.set_game_tags(game.id, game.tags)

    # ---------- 标签 / 分类 / 批量操作（v2.4） ----------

    def get_all_tags(self):
        """获取所有标签（含颜色与排序）"""
        return self.tag_repo.get_all_tags()

    def add_tag(self, name: str, color: str = ""):
        """新建标签，返回 id（重名返回 None）"""
        return self.tag_repo.add_tag(name, color)

    def rename_tag(self, tag_id: int, new_name: str) -> bool:
        return self.tag_repo.rename_tag(tag_id, new_name)

    def delete_tag(self, tag_id: int) -> bool:
        """删除标签（级联移除所有游戏关联）"""
        return self.tag_repo.delete_tag(tag_id)

    def get_game_tags(self, game_id: str):
        return self.tag_repo.get_game_tags(game_id)

    def set_game_tags(self, game_id: str, tag_names: List[str]) -> bool:
        return self.tag_repo.set_game_tags(game_id, tag_names)

    def get_all_categories(self):
        return self.tag_repo.get_all_categories()

    def add_category(self, name: str):
        return self.tag_repo.add_category(name)

    def delete_category(self, cat_id: int) -> bool:
        return self.tag_repo.delete_category(cat_id)

    def set_game_category(self, game_id: str, cat_id: int) -> bool:
        return self.tag_repo.set_game_category(game_id, cat_id)

    def get_games_by_category(self, cat_id: int) -> List[str]:
        return self.tag_repo.get_games_by_category(cat_id)

    def batch_add_tag(self, game_ids: List[str], tag_id: int) -> int:
        """批量为多个游戏添加标签（单事务），返回处理数量"""
        statements = [
            ("INSERT OR IGNORE INTO game_tags (game_id, tag_id) VALUES (?, ?)",
             (gid, tag_id))
            for gid in game_ids
        ]
        return len(game_ids) if self.tag_repo.db.execute_many(statements) else 0

    def batch_remove_tag(self, game_ids: List[str], tag_id: int) -> int:
        statements = [
            ("DELETE FROM game_tags WHERE game_id = ? AND tag_id = ?", (gid, tag_id))
            for gid in game_ids
        ]
        return len(game_ids) if self.tag_repo.db.execute_many(statements) else 0

    def batch_set_category(self, game_ids: List[str], cat_id: int) -> int:
        statements = [
            ("UPDATE games SET category_id = ? WHERE id = ?", (cat_id, gid))
            for gid in game_ids
        ]
        return len(game_ids) if self.repository.db.execute_many(statements) else 0

    def batch_set_favorite(self, game_ids: List[str], is_favorite: bool) -> int:
        statements = [
            ("UPDATE games SET is_favorite = ? WHERE id = ?",
             (1 if is_favorite else 0, gid))
            for gid in game_ids
        ]
        return len(game_ids) if self.repository.db.execute_many(statements) else 0

    def batch_delete(self, game_ids: List[str]) -> int:
        """批量删除游戏（正在运行的先关闭）"""
        statements = []
        for gid in game_ids:
            if self.launcher.current_game_id == gid and self.launcher.is_running():
                self.close_game()
            statements.append(("DELETE FROM games WHERE id = ?", (gid,)))
        return len(game_ids) if self.repository.db.execute_many(statements) else 0

    # ---------- 收藏夹管理（V1.0 collections，委托 CollectionRepository）----------

    def get_collections_tree(self) -> list:
        """返回树形收藏夹结构"""
        return self.collection_repo.get_tree()

    def create_collection(self, name: str, parent_id=None, icon: str = "",
                          color: str = "") -> Optional[dict]:
        """新建收藏夹。parent_id=None 表示根节点（分组）"""
        return self.collection_repo.create(name, parent_id or None, icon, color)

    def update_collection(self, collection_id: int, **kwargs) -> Optional[dict]:
        """更新收藏夹（name/parent_id/icon/color/sort_order）"""
        return self.collection_repo.update(collection_id, **kwargs)

    def delete_collection(self, collection_id: int) -> bool:
        """删除收藏夹（级联删除子分类 + 关联）"""
        return self.collection_repo.delete(collection_id)

    def reorder_collection(self, collection_id: int, new_sort_order: int) -> bool:
        return self.collection_repo.reorder(collection_id, new_sort_order)

    def add_games_to_collections(self, game_ids: list, collection_ids: list) -> bool:
        return self.collection_repo.add_games_to_collections(game_ids, collection_ids)

    def set_game_collections(self, game_id: str, collection_ids: list) -> bool:
        """整体替换某游戏的收藏夹列表"""
        return self.collection_repo.set_game_collections(game_id, collection_ids)

    def get_games_in_collection(self, collection_id: int) -> list:
        return self.collection_repo.get_games_in_collection(collection_id)

    def get_game_collections(self, game_id: str) -> list:
        return self.collection_repo.get_game_collections(game_id)

    def move_game_in_collection(self, collection_id: int, game_id: str,
                                new_sort_order: int) -> bool:
        return self.collection_repo.move_game_order(collection_id, game_id, new_sort_order)

    def batch_add_to_collection(self, game_ids: list, collection_id: int) -> bool:
        """批量添加游戏到收藏夹（替代原 batch_add_tag / batch_move_category）"""
        return self.collection_repo.add_games_to_collections(game_ids, [collection_id])

    def batch_remove_from_collection(self, game_ids: list, collection_id: int) -> bool:
        """从收藏夹批量移除游戏"""
        return self.collection_repo.remove_games_from_collection(game_ids, collection_id)

    def set_collection_games(self, collection_id: int, game_ids: list) -> bool:
        """整体替换某收藏夹的游戏列表 + 排序（管理游戏对话框用）"""
        return self.collection_repo.set_collection_games(collection_id, game_ids)

    def remove_games_from_collection(self, game_ids: list, collection_id: int) -> bool:
        """从收藏夹批量移除游戏（单数方法别名，Bridge 用）"""
        return self.collection_repo.remove_games_from_collection(game_ids, collection_id)

    # ---------- 启动/关闭/监控 ----------

    def launch(self, game_id: str, extra_args: Optional[list] = None) -> bool:
        """启动游戏并开始监控"""
        game = self.repository.get_by_id(game_id)
        if not game:
            return False

        # 启动前若有其他游戏在跑，先关闭
        if self.launcher.is_running():
            self.close_game()

        if not self.launcher.launch(game, extra_args=extra_args):
            return False

        # 记录最后游玩时间
        self.repository.record_play(game_id)
        # 开启监控
        self.monitor.start(game_id)
        return True

    def close_game(self) -> None:
        """关闭当前游戏并停止监控"""
        self.monitor.stop()
        self.launcher.close()

    def is_game_running(self) -> bool:
        """是否有游戏正在运行"""
        return self.launcher.is_running()

    def get_running_game(self) -> Optional[Game]:
        """获取当前正在运行的游戏对象"""
        gid = self.launcher.current_game_id
        if not gid or not self.launcher.is_running():
            return None
        return self.repository.get_by_id(gid)

    def get_running_runtime(self) -> int:
        """当前游戏已运行分钟数"""
        return self.monitor.get_runtime_seconds() // 60 or self.launcher.get_runtime()

    # ---------- VNDB 元数据匹配 ----------

    def match_vndb_metadata(self, game_id: str, force: bool = False) -> Tuple[str, str]:
        """为指定游戏匹配 VNDB 元数据并写回数据库

        Args:
            game_id: 游戏 ID
            force: True 时强制重新匹配（即使已有 vndb_id）

        Returns:
            (status, message) status ∈ {"skip", "match", "fail"}
        """
        from core import metadata_matcher
        game = self.repository.get_by_id(game_id)
        if not game:
            return "fail", "游戏不存在"
        status, msg = metadata_matcher.match_single(game, force=force)
        # 无论是否更新都写回数据库（vndb_id 已标记时也保存，避免重复匹配）
        if status in ("match", "skip") and game.vndb_id:
            self.repository.update_game(game)
        return status, msg

    def match_all_vndb_metadata(
        self,
        force: bool = False,
        progress_cb: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> Tuple[int, int, int]:
        """批量匹配所有游戏的 VNDB 元数据

        Args:
            force: True 时强制重新匹配已有 vndb_id 的游戏
            progress_cb: 进度回调 callback(game_id, title, status, msg)

        Returns:
            (matched, skipped, failed)
        """
        from core import metadata_matcher
        games = self.repository.get_all()
        if not games:
            return 0, 0, 0

        # 先在内存中批量匹配（避免每次都查库）
        matched, skipped, failed = metadata_matcher.match_batch(
            games, force=force, progress_cb=progress_cb
        )
        # 统一写回数据库（已匹配或已标记 vndb_id 的）
        for game in games:
            if game.vndb_id:
                try:
                    self.repository.update_game(game)
                except Exception as e:
                    logger.error("写回 VNDB 元数据失败: %s, %s", game.id, e)
        return matched, skipped, failed

    def match_vndb_for_games(
        self,
        games: List[Game],
        force: bool = False,
        progress_cb: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> Tuple[int, int, int]:
        """为指定游戏列表匹配 VNDB 元数据（不匹配全库，扫描后精准匹配用）

        Args:
            games: 要匹配的游戏列表
            force: True 时强制重新匹配已有 vndb_id 的游戏
            progress_cb: 进度回调 callback(game_id, title, status, msg)

        Returns:
            (matched, skipped, failed)
        """
        from core import metadata_matcher
        if not games:
            return 0, 0, 0
        matched, skipped, failed = metadata_matcher.match_batch(
            games, force=force, progress_cb=progress_cb
        )
        # 统一写回数据库（已匹配或已标记 vndb_id 的）
        for game in games:
            if game.vndb_id:
                try:
                    self.repository.update_game(game)
                except Exception as e:
                    logger.error("写回 VNDB 元数据失败: %s, %s", game.id, e)
        return matched, skipped, failed
