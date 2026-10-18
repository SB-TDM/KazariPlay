"""收藏夹用例层：树查询、增删改、游戏归属与排序。"""
from typing import List, Optional

from core.games.game_manager import GameManager


class CollectionService:
    def __init__(self, manager: GameManager):
        self.manager = manager

    def tree(self) -> list:
        return self.manager.get_collections_tree()

    def create(self, name: str, parent_id, icon: str, color: str) -> Optional[dict]:
        return self.manager.create_collection(name, parent_id or None, icon, color)

    def update(self, collection_id: int, data: dict) -> Optional[dict]:
        return self.manager.update_collection(collection_id, **data)

    def delete(self, collection_id: int) -> bool:
        return self.manager.delete_collection(collection_id)

    def reorder(self, collection_id: int, new_sort_order: int) -> bool:
        return self.manager.reorder_collection(collection_id, new_sort_order)

    def add_games(self, game_ids: list, collection_id: int) -> bool:
        return self.manager.add_games_to_collections(game_ids, [collection_id])

    def remove_games(self, game_ids: list, collection_id: int) -> bool:
        return self.manager.remove_games_from_collection(game_ids, collection_id)

    def set_game_collections(self, game_id: str, collection_ids: list) -> bool:
        return self.manager.set_game_collections(game_id, collection_ids)

    def set_games(self, collection_id: int, game_ids: list) -> bool:
        return self.manager.set_collection_games(collection_id, game_ids)

    def game_ids(self, collection_id: int) -> List[str]:
        return self.manager.get_games_in_collection(collection_id)

    def move_game(self, collection_id: int, game_id: str, new_sort_order: int) -> bool:
        return self.manager.move_game_in_collection(collection_id, game_id, new_sort_order)

    def batch_add(self, game_ids: list, collection_id: int) -> bool:
        return self.manager.batch_add_to_collection(game_ids, collection_id)

    def batch_remove(self, game_ids: list, collection_id: int) -> bool:
        return self.manager.batch_remove_from_collection(game_ids, collection_id)
