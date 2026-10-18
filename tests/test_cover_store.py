"""CoverStore 回归：格式识别、原子替换、旧变体清理、迁移、缩略图、清理"""
import io
import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "kazari_play"))

from PIL import Image  # noqa: E402
from core.media.cover_store import CoverStore, detect_extension  # noqa: E402


def jpeg_bytes(size=(800, 600), color=(200, 100, 50)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def write(path, data, old=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if old:
        t = time.time() - 3600
        os.utime(path, (t, t))


class Repo:
    def __init__(self, games):
        self.games = games
        self.updated = {}

    def get_all(self):
        return self.games

    def update_cover_path(self, game_id, path):
        self.updated[game_id] = path
        for g in self.games:
            if g.id == game_id:
                g.cover_path = path
        return True


def main():
    tmp = tempfile.mkdtemp(prefix="kp_cover_store_")
    store = CoverStore(base_dir=os.path.join(tmp, "covers"))
    data = jpeg_bytes()

    assert detect_extension(data) == ".jpg"
    assert detect_extension(b"\x89PNG\r\n\x1a\n....") == ".png"
    assert detect_extension(b"RIFF1234WEBP....") == ".webp"
    assert detect_extension(b"GIF89a....") == ".gif"
    assert detect_extension(b"not an image") == ""
    from core.media import cover_store as cs
    old_max = cs._MAX_COVER_BYTES
    try:
        cs._MAX_COVER_BYTES = 10
        assert store.save_bytes("big", data) == ""
    finally:
        cs._MAX_COVER_BYTES = old_max
    print("[detect] OK")

    # 写入 + 旧变体清除
    legacy = os.path.join(store.covers_dir, "g1_vndb.jpg")
    write(legacy, data)
    dest = store.save_bytes("g1", data)
    assert dest.endswith("g1.jpg") and os.path.isfile(dest)
    assert not os.path.exists(legacy), "旧变体未删除"
    assert store.find_cover("g1") == dest
    thumb = store.ensure_thumb("g1")
    assert os.path.isfile(thumb) and os.path.basename(thumb) == "g1_w512.jpg"
    with Image.open(thumb) as im:
        assert im.size[0] == 512, im.size
    # 再写一次（不同格式）应替换并删除旧 jpg + 旧缩略图
    png = io.BytesIO()
    Image.new("RGB", (300, 300), (0, 200, 0)).save(png, "PNG")
    dest2 = store.save_bytes("g1", png.getvalue())
    assert dest2.endswith("g1.png") and os.path.isfile(dest2)
    assert not os.path.exists(dest), "旧 jpg 未删除"
    assert not os.path.exists(thumb), "旧缩略图未删除"
    print("[save/replace/thumb] OK")

    # 迁移：legacy 变体 + 旧路径
    old = os.path.join(tmp, "old", "covers", "g2_ms.jpg")
    write(old, data)
    g2 = SimpleNamespace(id="g2", cover_path=old)
    repo = Repo([g2])
    migrated = store.migrate(repo)
    assert migrated == 1
    assert store.migrate(repo) == 0, "迁移应幂等"
    assert g2.cover_path and g2.cover_path.endswith("g2.jpg")
    assert os.path.isfile(g2.cover_path)
    assert os.path.exists(old), "外部旧路径不应被删除（安全边界）"
    print("[migrate] OK")

    # 清理：未引用文件/过期缩略图删除，引用文件保留
    orphan = os.path.join(store.covers_dir, "orphan.jpg")
    write(orphan, data)
    stale_thumb = os.path.join(store.thumbs_dir, "stale_w512.jpg")
    write(stale_thumb, data)
    keep = store.find_cover("g2")
    keep_thumb = store.thumb_path("g2")
    store.ensure_thumb("g2")
    removed = store.cleanup(repo)
    assert removed >= 2
    assert os.path.isfile(keep)
    assert os.path.isfile(keep_thumb)
    assert not os.path.exists(orphan)
    assert not os.path.exists(stale_thumb)
    print("[cleanup] OK")

    # 删除
    store.ensure_thumb("g2")
    store.delete("g2")
    assert not os.path.exists(keep)
    assert not os.path.exists(keep_thumb)
    print("[delete] OK")
    print("COVER STORE TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
