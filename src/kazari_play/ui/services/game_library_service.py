"""游戏库用例层：查询、删除、收藏、评分、启动。"""
from typing import List, Optional

from core.games.game_manager import GameManager
from core.games.game_model import Game


class GameLibraryService:
    def __init__(self, manager: GameManager):
        self.manager = manager

    def list_games(self) -> List[Game]:
        return self.manager.get_all_games()

    def get_game(self, game_id: str) -> Optional[Game]:
        return self.manager.get_game(game_id)

    def toggle_favorite(self, game_id: str) -> bool:
        return self.manager.toggle_favorite(game_id)

    def set_rating(self, game_id: str, rating: float) -> bool:
        return self.manager.set_rating(game_id, rating)

    def delete_game(self, game_id: str) -> bool:
        return self.manager.delete_game(game_id)

    def batch_delete(self, game_ids: list) -> int:
        return self.manager.batch_delete(game_ids)

    def launch(self, game_id: str) -> bool:
        return self.manager.launch(game_id)

    def running_game_id(self) -> str:
        game = self.manager.get_running_game()
        return game.id if game else ""

    def source_records(self, game_id: str) -> list:
        return self.manager.source_repo.list_for_game(game_id)
