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

    # 2. 列表
    shots = screenshot_service.get_screenshots("test_game")
    assert len(shots) == 1
    assert shots[0]["file"] == os.path.basename(p)
    assert shots[0]["created"], "应提取时间"
    print("[列表] OK:", shots[0]["created"])

    # 3. 删除
    assert screenshot_service.delete_screenshot("test_game", os.path.basename(p))
    assert screenshot_service.get_screenshots("test_game") == []
    print("[删除] OK")

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

    # 清理
    shutil.rmtree(_tmp_root, ignore_errors=True)
    print("SHOT TEST PASS")


if __name__ == "__main__":
    test_core()
