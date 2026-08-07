"""批量重跑库内所有游戏的 VNDB 匹配（标题更新为 VNDB 正式名 + 填充元数据/封面）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))
from core.game_manager import GameManager


def main():
    m = GameManager()
    games = m.get_all_games()
    print("待匹配游戏:", len(games))

    def cb(gid, title, status, msg):
        print(f"  [{status}] {title[:36]:<36} : {msg[:56]}")

    matched, skipped, failed = m.match_all_vndb_metadata(
        force=True, progress_cb=cb)
    print(f"=== 完成: 成功={matched} 跳过={skipped} 失败={failed} ===")
    for g in m.get_all_games():
        print(f"  「{g.title}」 dev={g.developer or '-'} "
              f"vndb={g.vndb_id or '-'} rating={g.rating} cover={'有' if g.cover_path else '无'}")


if __name__ == "__main__":
    main()
