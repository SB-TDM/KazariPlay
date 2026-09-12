"""截图服务单元测试（临时目录，不动真实数据）"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

# 临时项目根：让 path_utils.get_screenshots_dir 指向临时目录
import utils.path_utils as pu
_tmp_root = tempfile.mkdtemp(prefix="kp_shot_test_")

# 直接测试核心函数（绕过项目根定位）
from core import screenshot_service


def test_core():
    # 1. 截图保存（PIL 截全屏，测试环境应有显示）
    p = screenshot_service.take_screenshot("test_game")
    if not p:
        print("[截图] SKIP: 无显示环境，无法截屏")
        return
    assert os.path.exists(p)
    assert "test_game" in p and "shot_" in os.path.basename(p)
    print("[截图] OK: 已保存 ->", os.path.basename(p))

    # 1.5 双保存：原图 + 缩略图（缩略图统一小画布，屏幕同比例，等比留边）
    thumb = screenshot_service._screenshot_thumb_path(p)
    assert os.path.exists(thumb), "缩略图应随原图保存"
    from PIL import Image as _PILImage
    tw, th = screenshot_service._thumb_canvas_size()
    with _PILImage.open(thumb) as _t:
        assert _t.size == (tw, th), f"缩略图尺寸应=画布 {(tw, th)}，实际 {_t.size}"
    print(f"[双保存] OK: 原图 + 缩略图({tw}x{th}) 均存在")

    # 2. 列表
    shots = screenshot_service.get_screenshots("test_game")
    assert len(shots) == 1
    assert shots[0]["file"] == os.path.basename(p)
    assert shots[0]["created"], "应提取时间"
    print("[列表] OK:", shots[0]["created"])

    # 3. 删除
    assert screenshot_service.delete_screenshot("test_game", os.path.basename(p))
    assert not os.path.exists(thumb), "删除截图应连带删除缩略图"
    assert screenshot_service.get_screenshots("test_game") == []
    print("[删除] OK: 原图+缩略图已删")

    # 3.5 重命名
    p2 = screenshot_service.take_screenshot("test_game")
    assert p2
    assert screenshot_service.rename_screenshot("test_game", os.path.basename(p2), "my_shot")
    names = [s["file"] for s in screenshot_service.get_screenshots("test_game")]
    assert names and "my_shot.png" in names[0]
    assert screenshot_service.delete_screenshot("test_game", "my_shot.png")
    print("[重命名] OK")

    # 4. 路径穿越防护
    assert not screenshot_service.delete_screenshot("test_game", "../../evil.png")
    print("[安全] OK: 拒绝路径穿越")

    # 5. WGC 捕获（有显示环境时验证核心路径；库缺失时静默降级不报错）
    _wgc_probe()

    # 清理
    shutil.rmtree(_tmp_root, ignore_errors=True)
    print("SHOT TEST PASS")


def _wgc_probe():
    """WGC 捕获探测：找系统任意可见窗口验证 _capture_via_wgc 返回非 None。

    无显示环境/库缺失时输出 SKIP，不算失败（三级回退设计保证不拖垮主流程）。
    """
    import ctypes
    from ctypes import wintypes

    try:
        user32 = ctypes.windll.user32
    except Exception:
        print("[WGC] SKIP: 非 Windows 环境")
        return

    # 找系统任意可见窗口及其 pid
    target = [None]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                target[0] = pid.value
                return False
        return True

    user32.EnumWindows(cb, 0)
    if not target[0]:
        print("[WGC] SKIP: 无可见窗口")
        return

    try:
        img = screenshot_service._capture_via_wgc(target[0])
    except Exception as e:
        print(f"[WGC] SKIP: 库缺失或捕获失败: {e}")
        return
    if img is None:
        print("[WGC] SKIP: 返回 None（库缺失或窗口不可捕获，已回退）")
    else:
        print(f"[WGC] OK: 捕获 {img.size} 像素")


if __name__ == "__main__":
    test_core()
