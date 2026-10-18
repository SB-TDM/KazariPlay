"""游戏编辑/添加用例：字段校验与持久化，不负责刷新 UI。"""
import os

from core.games.game_manager import GameManager
from core.games.game_model import Game
from utils.domain.rating_utils import normalize_rating


class GameEditService:
    def __init__(self, manager: GameManager):
        self.manager = manager

    def save(self, game_id: str, data: dict) -> dict:
        if game_id:
            return self._update(game_id, data)
        return self._add(data)

    def _update(self, game_id: str, data: dict) -> dict:
        game = self.manager.get_game(game_id)
        if game is None:
            return {"ok": False, "msg": "游戏不存在，请刷新后重试"}
        for field in ("title", "engine", "developer", "description"):
            if field in data:
                setattr(game, field, data[field])
        if "rating" in data:
            rating = normalize_rating(data["rating"])
            game.rating = rating if rating is not None else 0
        if "cat_id" in data:
            game.category_id = int(data["cat_id"] or 0)
        new_exe = (data.get("exe_path") or "").strip()
        if new_exe:
            new_exe = os.path.normpath(new_exe)
            if os.path.normcase(new_exe) != os.path.normcase(game.exe_path or ""):
                if not os.path.isfile(new_exe):
                    return {"ok": False, "msg": "启动文件不存在"}
                game.exe_path = new_exe
                game.folder = os.path.dirname(new_exe)
            else:
                game.exe_path = new_exe
        game.identity = self.manager.scanner._make_identity(
            game.engine, os.path.basename(os.path.normpath(game.folder or "")))
        if not self.manager.update_game(game):
            return {"ok": False, "msg": "保存失败，请检查标题或路径是否重复"}
        return {"ok": True, "msg": "", "updated": game_id}

    def _add(self, data: dict) -> dict:
        exe_path = (data.get("exe_path") or "").strip()
        if not exe_path or not os.path.isfile(exe_path):
            return {"ok": False, "msg": "请选择存在的 exe 文件"}
        exe_path = os.path.normpath(exe_path)
        if self.manager.repository.get_by_path(exe_path):
            return {"ok": False, "msg": "该游戏已在库中，请使用编辑功能"}
        title = (data.get("title") or "").strip()
        if not title:
            title = self.manager.scanner._generate_title(
                os.path.dirname(exe_path), os.path.basename(exe_path))
        game = Game(
            id=self.manager.scanner._generate_id(exe_path),
            title=title,
            exe_path=exe_path,
            folder=os.path.dirname(exe_path),
            engine=data.get("engine", ""),
            developer=data.get("developer", ""),
            description=data.get("description", ""),
            rating=normalize_rating(data.get("rating", 0)) or 0,
        )
        game.identity = self.manager.scanner._make_identity(
            game.engine, os.path.basename(os.path.normpath(game.folder)))
        game.category_id = int(data.get("cat_id", 0) or 0)
        if not self.manager.add_game(game):
            return {"ok": False, "msg": "添加失败，请检查启动路径是否重复"}
        return {"ok": True, "msg": "", "added": game}
