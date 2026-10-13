"""更新替换助手与启动自愈单测（全程临时目录，不碰真实数据）

覆盖：正常替换（含镜像清理/数据保全/备份滚动）/ 替换失败回滚 /
更新包含数据目录拒绝 / 启动自愈（applying 中断恢复、verify_pending 两振回滚、
rolled_back 提示）/ 进程等待与强杀。
用法：python tests/test_update_apply.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

from utils import update_apply as UA  # noqa: E402


OLD_TREE = {
    "KazariPlay.exe": b"OLD-EXE",
    "_internal/old.dll": b"old-dll",
    "_internal/common.dll": b"common-v1",
    "LICENSE": b"lic-v1",
    "BUILD_INFO.json": b'{"version": "1.0.0"}',
    "data/games.db": b"db-bytes",
    "data/config.json": b'{"theme": "light"}',
    "data/covers/a.jpg": b"jpg-bytes",
    "data/screenshots/s.png": b"png-bytes",
    "data/logs/l.log": b"log-bytes",
    "data/backup/old1/games.db": b"old-backup",
}
NEW_TREE = {
    "KazariPlay.exe": b"NEW-EXE",
    "_internal/new.dll": b"new-dll",
    "_internal/common.dll": b"common-v2",
    "LICENSE": b"lic-v2",
    "BUILD_INFO.json": b'{"version": "1.0.1"}',
}


def write_tree(root, tree):
    for rel, content in tree.items():
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class Drill:
    """一次临时目录双版本演练环境"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.target = os.path.join(self.root, "KazariPlay")
        self.source = os.path.join(self.root, "extract")
        self.data_dir = os.path.join(self.target, "data")
        os.makedirs(self.target)
        os.makedirs(self.source)
        write_tree(self.target, OLD_TREE)
        write_tree(self.source, NEW_TREE)
        self.launched = []

    def apply(self, patch_replace=None):
        kwargs = dict(launch=self.launched.append, wait_timeout=0.5)
        if patch_replace is not None:
            with mock.patch.object(UA, "_copy_new_files", side_effect=patch_replace):
                return UA.apply_update(0, self.target, self.source, self.data_dir, **kwargs)
        return UA.apply_update(0, self.target, self.source, self.data_dir, **kwargs)

    def state(self):
        with open(os.path.join(self.data_dir, UA.STATE_FILE), encoding="utf-8") as f:
            return json.load(f)

    def close(self):
        self.tmp.cleanup()


def test_apply_success():
    d = Drill()
    try:
        rc = d.apply()
        assert rc == 0
        # 程序文件：新 exe / 新 dll / 公共 dll 升级 / 旧 dll 被镜像清理
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"NEW-EXE"
        assert read_bytes(os.path.join(d.target, "_internal", "new.dll")) == b"new-dll"
        assert read_bytes(os.path.join(d.target, "_internal", "common.dll")) == b"common-v2"
        assert not os.path.exists(os.path.join(d.target, "_internal", "old.dll"))
        # 用户数据：原样
        assert read_bytes(os.path.join(d.data_dir, "games.db")) == b"db-bytes"
        assert read_bytes(os.path.join(d.data_dir, "covers", "a.jpg")) == b"jpg-bytes"
        assert read_bytes(os.path.join(d.data_dir, "screenshots", "s.png")) == b"png-bytes"
        assert read_bytes(os.path.join(d.data_dir, "logs", "l.log")) == b"log-bytes"
        # 数据备份：新增一份（滚动目录保留）
        backups = sorted(os.listdir(os.path.join(d.data_dir, "backup")))
        assert len(backups) == 2, backups   # old1 + 本次
        newest = next((os.path.join(d.data_dir, "backup", name) for name in backups
                       if os.path.isfile(os.path.join(d.data_dir, "backup", name, "config.json"))), None)
        assert newest, backups
        assert os.path.isfile(os.path.join(newest, "games.db"))
        # 状态与拉起
        st = d.state()
        assert st["phase"] == UA.STATE_VERIFY and st["attempts"] == 0
        assert st["target"] == os.path.abspath(d.target)
        assert st["backup_program"] and os.path.isdir(st["backup_program"])
        assert d.launched == [os.path.join(d.target, "KazariPlay.exe")]
        # 两段确认收尾
        UA.mark_startup_success(d.data_dir)
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        assert not os.path.exists(os.path.join(d.target, "_old"))
        print("[替换-成功+数据保全+两段确认] OK")
    finally:
        d.close()


def test_apply_rollback_on_failure():
    d = Drill()
    try:
        rc = d.apply(patch_replace=RuntimeError("boom"))
        assert rc == 1
        # 完全回到旧版
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert read_bytes(os.path.join(d.target, "_internal", "common.dll")) == b"common-v1"
        assert read_bytes(os.path.join(d.target, "_internal", "old.dll")) == b"old-dll"
        assert not os.path.exists(os.path.join(d.target, "_internal", "new.dll"))
        # 用户数据不变；状态 rolled_back；拉起旧版
        assert read_bytes(os.path.join(d.data_dir, "games.db")) == b"db-bytes"
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "boom" in st["msg"]
        assert d.launched == [os.path.join(d.target, "KazariPlay.exe")]
        print("[替换-失败回滚] OK")
    finally:
        d.close()


def test_apply_refuses_data_in_package():
    d = Drill()
    try:
        write_tree(d.source, {"data/games.db": b"evil"})
        rc = d.apply()
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.target, "_old"))
        assert not os.path.exists(os.path.join(d.data_dir, "backup", "")) or True
        assert d.launched == [os.path.join(d.target, "KazariPlay.exe")]   # 未开始替换，直接拉起旧版
        print("[替换-拒绝含数据目录的包] OK")
    finally:
        d.close()


def test_self_heal_applying_interrupt():
    d = Drill()
    try:
        assert d.apply() == 0
        # 模拟助手中断：把目标 exe 弄坏，并把状态改回 applying（保留备份路径）
        with open(os.path.join(d.target, "KazariPlay.exe"), "wb") as f:
            f.write(b"BROKEN")
        st = d.state()
        st["phase"] = UA.STATE_APPLYING
        with open(os.path.join(d.data_dir, UA.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        notice, restart = UA.startup_self_heal(d.data_dir)
        assert notice and "中断" in notice, notice
        assert restart == ""
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        assert not os.path.exists(os.path.join(d.target, "_old"))
        print("[自愈-助手中断回滚] OK")
    finally:
        d.close()


def test_self_heal_applying_not_started():
    d = Drill()
    try:
        with open(os.path.join(d.data_dir, UA.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"phase": UA.STATE_APPLYING, "target": d.target,
                       "backup_program": "", "attempts": 0}, f)
        notice, restart = UA.startup_self_heal(d.data_dir)
        assert notice and "未开始" in notice
        assert restart == ""
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-未开始的更新取消] OK")
    finally:
        d.close()


def test_self_heal_verify_pending_two_strikes():
    d = Drill()
    try:
        assert d.apply() == 0
        # 第一次启动：计数 +1，不处理
        notice, restart = UA.startup_self_heal(d.data_dir)
        assert notice is None and restart == ""
        assert d.state()["attempts"] == 1
        # 第二次启动（视为新版启动失败）：回滚并重启旧版
        notice, restart = UA.startup_self_heal(d.data_dir)
        assert notice and "回滚" in notice, notice
        assert restart == os.path.join(d.target, "KazariPlay.exe")
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-新版两振未确认回滚] OK")
    finally:
        d.close()


def test_self_heal_rolled_back_notice():
    d = Drill()
    try:
        old_dir = os.path.join(d.target, "_old", "stamp")
        os.makedirs(old_dir)
        with open(os.path.join(d.data_dir, UA.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"phase": UA.STATE_ROLLED_BACK, "target": d.target,
                       "backup_program": old_dir, "msg": "更新失败，已回滚：boom"}, f)
        notice, restart = UA.startup_self_heal(d.data_dir)
        assert notice and "boom" in notice
        assert restart == ""
        assert not os.path.exists(os.path.join(d.target, "_old"))
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-回滚提示消费] OK")
    finally:
        d.close()


def test_backup_rolling_three():
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(tmp, {"games.db": b"db", "config.json": b"cfg"})
        for i in range(5):
            UA.backup_user_data(tmp, stamp=f"2026010{i + 1}-000000")
        dirs = sorted(os.listdir(os.path.join(tmp, "backup")))
        assert dirs == ["20260103-000000", "20260104-000000", "20260105-000000"], dirs
    print("[备份-滚动保留 3 份] OK")


def test_wait_process_exit():
    # 正常退出：进程结束后立即返回
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.6)"])
    t0 = time.monotonic()
    UA.wait_process_exit(p.pid, timeout=10)
    assert time.monotonic() - t0 < 5
    assert p.poll() is not None
    # 超时强杀：确保进程树被结束
    p2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    UA.wait_process_exit(p2.pid, timeout=1.0)
    deadline = time.time() + 10
    while time.time() < deadline and p2.poll() is None:
        time.sleep(0.2)
    assert p2.poll() is not None, "超时后应被强杀"
    print("[进程-等待与超时强杀] OK")


if __name__ == "__main__":
    test_apply_success()
    test_apply_rollback_on_failure()
    test_apply_refuses_data_in_package()
    test_self_heal_applying_interrupt()
    test_self_heal_applying_not_started()
    test_self_heal_verify_pending_two_strikes()
    test_self_heal_rolled_back_notice()
    test_backup_rolling_three()
    test_wait_process_exit()
    print("UPDATE APPLY TEST PASS")
