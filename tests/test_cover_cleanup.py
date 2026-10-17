"""封面清理回归：未引用封面/过期缩略图删除，被引用文件保留"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from ui import web_bridge as wb  # noqa: E402


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    old = time.time() - 3600
    os.utime(path, (old, old))


def main():
    tmp = tempfile.mkdtemp(prefix="kp_cover_cleanup_")
    wb.get_app_data_dir = lambda *a, **k: tmp
    covers = os.path.join(tmp, "covers")
    thumbs = os.path.join(covers, "thumbs")
    os.makedirs(thumbs, exist_ok=True)
    keep = os.path.join(covers, "keep.jpg")
    old = os.path.join(covers, "old.jpg")
    write(keep)
    write(old)
    keep_thumb = wb._cover_thumb_path(keep)
    write(keep_thumb)
    stale_thumb = os.path.join(thumbs, "stale_w512.jpg")
    write(stale_thumb)

    game = SimpleNamespace(cover_path=keep)
    bridge = SimpleNamespace(manager=SimpleNamespace(
        repository=SimpleNamespace(get_all=lambda: [game])))

    removed = wb.WebBridge.cleanup_unused_covers(bridge)
    assert removed == 2, removed
    assert os.path.isfile(keep), "被引用封面被误删"
    assert os.path.isfile(keep_thumb), "被引用封面缩略图被误删"
    assert not os.path.exists(old), "未引用封面未删除"
    assert not os.path.exists(stale_thumb), "过期缩略图未删除"
    print("[cleanup unused] OK")

    # 换封面：旧文件及其缩略图立即删除
    old2 = os.path.join(covers, "old2.jpg")
    write(old2)
    old2_thumb = wb._cover_thumb_path(old2)
    write(old2_thumb)
    wb.WebBridge._delete_cover_if_unused(bridge, old2)
    assert not os.path.exists(old2) and not os.path.exists(old2_thumb)
    wb.WebBridge._delete_cover_if_unused(bridge, keep)
    assert os.path.isfile(keep), "被引用封面被误删"
    print("[delete replaced cover] OK")
    print("COVER CLEANUP TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
