"""封面缩略图生成回归测试（临时目录，不动真实数据/AppData）

验证 web_bridge._ensure_cover_thumb / _cover_data_uri：
1. 首次调用生成缩略图（jpg、宽 ≤ 512、保持宽高比、落盘 thumbs/）
2. 重复调用命中磁盘缓存（不重建）
3. 原图 mtime 变化 → 缩略图自动失效重建（新路径）
4. _cover_data_uri 返回缩略图 jpeg 的 data URI
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from ui import web_bridge as wb  # noqa: E402


def make_source_image(path, size=(2000, 1500)):
    """噪声图：PNG 几乎不可压缩（数 MB），保证"缩略图 < 原图"断言稳定成立"""
    from PIL import Image
    im = Image.effect_noise(size, 80).convert("RGB")
    im.save(path, "PNG")
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="kp_cover_thumb_")
    wb.get_app_data_dir = lambda *a, **k: tmp   # AppData 指向临时目录
    wb._cover_cache_clear()

    from PIL import Image as PILImage
    src = make_source_image(os.path.join(tmp, "cover.png"))
    thumb = wb._ensure_cover_thumb(src)
    assert os.path.exists(thumb), "缩略图未生成"
    assert os.path.getsize(thumb) < os.path.getsize(src), \
        f"缩略图应小于原图: {os.path.getsize(thumb)} vs {os.path.getsize(src)}"
    assert thumb != src and thumb.endswith(".jpg"), f"缩略图路径异常: {thumb}"
    with PILImage.open(thumb) as t:
        tw, th = t.size
        assert tw <= wb._THUMB_WIDTH, f"缩略图过宽: {tw}"
        # 宽高比保持（2000:1500 → 512:384，允许 ±1px 取整误差）
        assert abs(th / tw - 1500 / 2000) < 0.01, f"宽高比失真: {tw}x{th}"
    print(f"[生成] OK ({tw}x{th}, {os.path.getsize(thumb)}B)")

    thumb2 = wb._ensure_cover_thumb(src)
    assert thumb2 == thumb, "重复调用应命中磁盘缓存"
    print("[磁盘缓存] OK")

    os.utime(src, (os.path.getmtime(src) + 10, os.path.getmtime(src) + 10))
    thumb3 = wb._ensure_cover_thumb(src)
    assert thumb3 != thumb, "mtime 变化后应生成新缩略图"
    print("[mtime 失效] OK")

    uri = wb._cover_data_uri(src)
    assert uri.startswith("data:image/jpeg;base64,"), f"URI 格式异常: {uri[:40]}"
    print("[data URI] OK")

    wb._cover_cache_clear()
    print("COVER THUMB TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
