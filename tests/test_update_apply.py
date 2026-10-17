"""更新替换助手、回滚助手与启动自愈单测（全程临时目录，不碰真实数据）

覆盖：正常替换（含镜像清理/数据保全/备份滚动）/ 替换失败回滚 /
数据备份失败中止 / 状态不可写中止与回滚 / 拉起异常回滚 / 新版早退回滚 /
数据包断言拒绝 / 启动自愈（applying 中断、verify_pending 两振、rolled_back 提示）/
回滚助手（真实文件锁等待、安装锁互斥）/ 进程等待与强杀失败中止 /
桥接层更新任务原子占用。
用法：python tests/test_update_apply.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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
    "_internal/cv2/data/__init__.py": b"cv2-data",   # 程序内部同名 data 子目录（不得误判为用户数据）
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

    def exe(self):
        return os.path.join(self.target, "KazariPlay.exe")

    def apply(self, patch_replace=None, launch=None):
        kwargs = dict(launch=launch or self.launched.append, wait_timeout=0.5)
        if patch_replace is not None:
            with mock.patch.object(UA, "_copy_new_files", side_effect=patch_replace):
                return UA.apply_update(0, self.target, self.source, self.data_dir, **kwargs)
        return UA.apply_update(0, self.target, self.source, self.data_dir, **kwargs)

    def state(self):
        with open(os.path.join(self.data_dir, UA.STATE_FILE), encoding="utf-8") as f:
            return json.load(f)

    def write_state(self, state):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(os.path.join(self.data_dir, UA.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

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
        # 程序内部同名 data 子目录（如 _internal/cv2/data）必须正常复制，不误判为用户数据
        assert read_bytes(os.path.join(d.target, "_internal", "cv2", "data",
                                       "__init__.py")) == b"cv2-data"
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
        assert d.launched == [d.exe()]
        # 两段确认收尾：就绪缓存（ready.json + zip）也要随确认清理
        cache = os.path.join(d.data_dir, "update_cache")
        os.makedirs(cache, exist_ok=True)
        zip_path = os.path.join(cache, "KazariPlay-win64.zip")
        with open(zip_path, "wb") as f:
            f.write(b"x")
        with open(os.path.join(cache, "ready.json"), "w", encoding="utf-8") as f:
            json.dump({"zip": "KazariPlay-win64.zip"}, f, ensure_ascii=False)
        msg = UA.mark_startup_success(d.data_dir)
        assert msg and "已更新到" in msg, msg
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        assert not os.path.exists(os.path.join(d.target, "_old"))
        assert not os.path.exists(zip_path)
        assert not os.path.exists(os.path.join(cache, "ready.json"))
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
        assert d.launched == [d.exe()]
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
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "未执行" in st["msg"]
        assert d.launched == [d.exe()]   # 未开始替换，直接拉起旧版
        print("[替换-拒绝含数据目录的包] OK")
    finally:
        d.close()


def test_apply_backup_failure_aborts():
    """用户数据备份失败必须中止更新（UPD-REV-06）"""
    d = Drill()
    try:
        with mock.patch.object(UA, "backup_user_data", side_effect=RuntimeError("permission denied")):
            rc = d.apply()
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.target, "_old"))
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "permission denied" in st["msg"]
        assert d.launched == [d.exe()]
        print("[替换-备份失败中止] OK")
    finally:
        d.close()


def test_apply_state_write_failure_aborts():
    """状态文件写不进去时不得进入替换（UPD-REV-05）"""
    d = Drill()
    try:
        with mock.patch.object(UA, "_write_state", side_effect=UA.UpdateStateError("disk full")):
            rc = d.apply()
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert d.launched == [d.exe()]
        print("[替换-状态不可写中止] OK")
    finally:
        d.close()


def test_apply_space_precheck_aborts():
    """替换前磁盘空间不足：中止且不改动文件（D11）"""
    d = Drill()
    try:
        with mock.patch.object(UA, "ensure_free_space",
                               side_effect=RuntimeError("磁盘空间不足：需要约 450 MB")):
            rc = d.apply()
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "磁盘空间不足" in st["msg"]
        print("[替换-空间预检中止] OK")
    finally:
        d.close()


def test_apply_verify_state_write_failure_rolls_back():
    """替换后"待验证"状态持久化失败：按失败回滚（UPD-REV-05）"""
    d = Drill()
    try:
        real = UA._write_state
        calls = {"n": 0}

        def flaky(data_dir, state):
            calls["n"] += 1
            if calls["n"] == 2 and state.get("phase") == UA.STATE_VERIFY:
                raise UA.UpdateStateError("disk full")
            return real(data_dir, state)

        with mock.patch.object(UA, "_write_state", side_effect=flaky):
            rc = d.apply()
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.target, "_internal", "new.dll"))
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "状态不可写" in st["msg"]
        assert d.launched == [d.exe()]
        print("[替换-待验证状态不可写回滚] OK")
    finally:
        d.close()


def test_apply_launch_failure_rolls_back():
    """拉起新版异常：立即回滚并拉起旧版（UPD-REV-03）"""
    d = Drill()
    try:
        calls = []

        def launch(exe):
            calls.append(exe)
            if len(calls) == 1:
                raise RuntimeError("spawn failed")

        rc = d.apply(launch=launch)
        assert rc == 1
        assert calls == [d.exe(), d.exe()]   # 先试新版，失败后拉起旧版
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "拉起失败" in st["msg"]
        print("[替换-拉起异常回滚] OK")
    finally:
        d.close()


class DeadProc:
    pid = 999999

    def poll(self):
        return 0


def test_apply_early_exit_rolls_back():
    """新版拉起后未确认即退出：立即回滚（UPD-REV-03）"""
    d = Drill()
    try:
        calls = []

        def launch(exe):
            calls.append(exe)
            return DeadProc() if len(calls) == 1 else None

        rc = d.apply(launch=launch)
        assert rc == 1
        assert calls == [d.exe(), d.exe()]
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "启动失败" in st["msg"]
        print("[替换-新版早退回滚] OK")
    finally:
        d.close()


def test_apply_wait_process_failure_aborts():
    """无法确认旧进程退出：不得进入备份与替换（UPD-REV-13）"""
    d = Drill()
    try:
        with mock.patch.object(UA, "wait_process_exit",
                               side_effect=RuntimeError("无法结束进程 42")):
            rc = UA.apply_update(os.getpid(), d.target, d.source, d.data_dir,
                                 launch=d.launched.append, wait_timeout=0.1)
        assert rc == 1
        assert read_bytes(os.path.join(d.target, "KazariPlay.exe")) == b"OLD-EXE"
        assert not os.path.exists(os.path.join(d.target, "_old"))
        assert d.launched == []   # 旧进程仍存活：不重复拉起
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "无法结束旧进程" in st["msg"]
        print("[替换-等待退出失败中止] OK")
    finally:
        d.close()


def test_self_heal_applying_interrupt():
    d = Drill()
    try:
        assert d.apply() == 0
        d.launched.clear()
        # 模拟助手中断：把目标 exe 弄坏，并把状态改回 applying（保留备份路径）
        with open(d.exe(), "wb") as f:
            f.write(b"BROKEN")
        st = d.state()
        st["phase"] = UA.STATE_APPLYING
        d.write_state(st)
        spawned = []
        notice, exit_req = UA.startup_self_heal(
            d.data_dir, spawn_helper=lambda t, dd: spawned.append((t, dd)) or True)
        assert notice is None and exit_req is True
        assert spawned == [(os.path.abspath(d.target), os.path.abspath(d.data_dir))]
        # 状态保留：由回滚助手完成后推进（不能误报成功）
        assert os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        # 模拟回滚助手执行：等待已退出 → 恢复 → 拉起旧版
        with mock.patch.object(UA, "_launch_default"):
            assert UA.rollback_update(0, d.target, d.data_dir) == 0
        assert read_bytes(d.exe()) == b"OLD-EXE"
        assert d.state()["phase"] == UA.STATE_ROLLED_BACK
        print("[自愈-助手中断交由回滚助手] OK")
    finally:
        d.close()


def test_self_heal_applying_not_started():
    d = Drill()
    try:
        d.write_state({"phase": UA.STATE_APPLYING, "target": d.target,
                       "backup_program": "", "attempts": 0})
        notice, exit_req = UA.startup_self_heal(d.data_dir)
        assert notice and "未开始" in notice
        assert exit_req is False
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-未开始的更新取消] OK")
    finally:
        d.close()


def test_self_heal_verify_pending_two_strikes():
    d = Drill()
    try:
        assert d.apply() == 0
        d.launched.clear()
        # 第一次启动：计数 +1，不处理
        notice, exit_req = UA.startup_self_heal(d.data_dir)
        assert notice is None and exit_req is False
        assert d.state()["attempts"] == 1
        # 第二次启动（视为新版启动失败）：拉起回滚助手
        spawned = []
        notice, exit_req = UA.startup_self_heal(
            d.data_dir, spawn_helper=lambda t, dd: spawned.append(1) or True)
        assert notice is None and exit_req is True and spawned
        # 模拟回滚助手执行
        with mock.patch.object(UA, "_launch_default"):
            assert UA.rollback_update(0, d.target, d.data_dir) == 0
        assert read_bytes(d.exe()) == b"OLD-EXE"
        st = d.state()
        assert st["phase"] == UA.STATE_ROLLED_BACK and "回滚" in st["msg"]
        print("[自愈-新版两振未确认回滚] OK")
    finally:
        d.close()


def test_self_heal_spawn_failure_keeps_state():
    """回滚助手拉不起来：保留状态、备份与错误，不误报成功（UPD-REV-01）"""
    d = Drill()
    try:
        assert d.apply() == 0
        d.launched.clear()
        UA.startup_self_heal(d.data_dir)   # attempts = 1
        old_backup = d.state()["backup_program"]
        notice, exit_req = UA.startup_self_heal(d.data_dir, spawn_helper=lambda t, dd: False)
        assert notice and "重试" in notice and exit_req is False
        st = d.state()
        assert st["phase"] == UA.STATE_VERIFY and st.get("rollback_error")
        assert os.path.isdir(old_backup)          # 备份保留
        assert os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-回滚助手拉起失败保留状态] OK")
    finally:
        d.close()


def test_self_heal_rolled_back_notice():
    d = Drill()
    try:
        old_dir = os.path.join(d.target, "_old", "stamp")
        os.makedirs(old_dir)
        d.write_state({"phase": UA.STATE_ROLLED_BACK, "target": d.target,
                       "backup_program": old_dir, "msg": "更新失败，已回滚：boom"})
        notice, exit_req = UA.startup_self_heal(d.data_dir)
        assert notice and "boom" in notice
        assert exit_req is False
        assert not os.path.exists(os.path.join(d.target, "_old"))
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[自愈-回滚提示消费] OK")
    finally:
        d.close()


def test_rollback_helper_waits_real_file_lock():
    """真实文件锁：目标 EXE 被占用时，原位恢复会失败；助手等待/强杀后恢复成功（UPD-REV-01）"""
    if os.name != "nt":
        print("[回滚-真实文件锁] SKIP（非 Windows）")
        return
    d = Drill()
    locker = None
    try:
        # 构造"替换后待确认"状态：备份为完整旧版，目标被替换为新版并被占用
        old_dir = os.path.join(d.target, "_old", "stamp")
        os.makedirs(old_dir)
        write_tree(old_dir, {k: v for k, v in OLD_TREE.items() if not k.startswith("data/")})
        shutil.copy2(os.path.join(d.source, "KazariPlay.exe"), d.exe())   # 新 exe 生效
        d.write_state({"phase": UA.STATE_VERIFY, "target": d.target,
                       "backup_program": old_dir, "attempts": 1})
        lock_script = (
            "import ctypes, sys, time\n"
            "k = ctypes.windll.kernel32\n"
            "k.CreateFileW.restype = ctypes.c_void_p\n"
            "h = k.CreateFileW(sys.argv[1], 0x80000000, 1, None, 3, 0, None)\n"
            "if not h or h == 0xFFFFFFFFFFFFFFFF:\n"
            "    sys.exit(3)\n"
            "time.sleep(60)\n"
        )
        locker = subprocess.Popen([sys.executable, "-c", lock_script, d.exe()])
        time.sleep(0.8)
        assert UA._process_alive(locker.pid)
        with mock.patch.object(UA, "_launch_default"):
            rc = UA.rollback_update(locker.pid, d.target, d.data_dir, wait_timeout=0.5)
        assert rc == 0, rc
        assert read_bytes(d.exe()) == b"OLD-EXE"          # 占用解除后恢复成功
        assert d.state()["phase"] == UA.STATE_ROLLED_BACK
        print("[回滚-真实文件锁等待与恢复] OK")
    finally:
        if locker is not None:
            try:
                locker.kill()
            except Exception:
                pass
        d.close()


def test_install_lock_exclusive_and_stale():
    """安装目录锁：活动锁互斥，陈旧锁可清理（UPD-REV-04 助手侧）"""
    with tempfile.TemporaryDirectory() as tmp:
        lock = UA._acquire_install_lock(tmp)
        assert lock and os.path.isfile(lock)
        assert UA._acquire_install_lock(tmp) is None    # 活动锁互斥
        UA._release_install_lock(lock)
        assert not os.path.exists(lock)
        with open(os.path.join(tmp, UA.LOCK_FILE), "w", encoding="ascii") as f:
            f.write("999999")                            # 死 PID = 陈旧锁
        lock2 = UA._acquire_install_lock(tmp)
        assert lock2
        UA._release_install_lock(lock2)
        # 回滚入口遇到活动锁时放弃（返回 2，不做任何事）
        lock3 = UA._acquire_install_lock(tmp)
        try:
            rc = UA.run_apply_rollback(["--pid", "0", "--target", tmp,
                                        "--data-dir", os.path.join(tmp, "d")])
            assert rc == 2
        finally:
            UA._release_install_lock(lock3)
    print("[安装锁-互斥与陈旧清理] OK")


def test_relative_forbidden_scope():
    """禁用区只认安装根级段：_internal 内的同名 data 子目录不算用户数据"""
    with tempfile.TemporaryDirectory() as tmp:
        assert UA._relative_forbidden(tmp, os.path.join(tmp, "data", "games.db"))
        assert UA._relative_forbidden(tmp, os.path.join(tmp, "screenshots", "a.png"))
        assert UA._relative_forbidden(tmp, os.path.join(tmp, "logs", "x.log"))
        assert UA._relative_forbidden(os.path.join(tmp, "t"), os.path.join(tmp, "other"))
        assert not UA._relative_forbidden(
            os.path.join(tmp, "t"),
            os.path.join(tmp, "t", "_internal", "cv2", "data", "__init__.py"))
        assert not UA._relative_forbidden(
            os.path.join(tmp, "t"), os.path.join(tmp, "t", "LICENSE"))
    print("[断言-仅根级禁用区] OK")


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


def test_wait_process_exit_kill_failure_raises():
    """taskkill 失败且进程仍存活：等待函数必须抛错（UPD-REV-13）"""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        class FakeRun:
            returncode = 1
        with mock.patch.object(UA.subprocess, "run", return_value=FakeRun()):
            try:
                UA.wait_process_exit(p.pid, timeout=0.3)
                raise AssertionError("强杀失败且进程存活时必须抛出")
            except RuntimeError as e:
                assert "无法结束进程" in str(e)
    finally:
        try:
            p.kill()
        except Exception:
            pass
    print("[进程-强杀失败中止] OK")


def test_bridge_update_claim_atomic():
    """两个入口共用原子占用：并发只允许一个成功（UPD-REV-04）"""
    from ui.web_bridge import WebBridge
    b = WebBridge.__new__(WebBridge)
    b._update_apply_lock = threading.Lock()
    b._update_apply_claimed = False
    b._update_applied = False
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(b._claim_update_apply())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1, results
    # 发起失败后可重新占用
    b._release_update_apply()
    assert b._claim_update_apply() is True
    # 已成功发起（applied）后不再允许
    b._update_applied = True
    b._release_update_apply()
    assert b._claim_update_apply() is False
    print("[桥-更新任务原子占用] OK")


def test_bridge_single_entry_repeat_trigger():
    """单入口重复点击/重试：begin_apply 至多执行一次（原子占用）"""
    from ui.web_bridge import WebBridge
    b = WebBridge.__new__(WebBridge)
    b._update_apply_lock = threading.Lock()
    b._update_apply_claimed = False
    b._update_applied = False
    calls = []

    def fake_begin(extract_dir, target, data_dir, pid):
        calls.append(1)
        return True, "ok"

    with tempfile.TemporaryDirectory() as tmp:
        extract = os.path.join(tmp, "extract")
        os.makedirs(extract)

        class FakeUpdater:
            def state(self):
                return {"state": "ready", "extract_dir": extract}

        with mock.patch("ui.web_bridge.get_updater", return_value=FakeUpdater()), \
             mock.patch("ui.web_bridge.get_app_data_dir", return_value=tmp), \
             mock.patch.object(UA, "current_install_dir", return_value=tmp), \
             mock.patch.object(UA, "begin_apply", side_effect=fake_begin):
            b.applyUpdate()
            b.applyUpdate()   # 重复触发：已在进行中，不再拉起
    assert len(calls) == 1, calls
    print("[桥-单入口重复触发] OK")


def test_frontend_ready_handshake():
    """前端就绪握手是首启确认的唯一入口，并返回完成提示（UPD-REV-02/D6）"""
    from ui.web_bridge import WebBridge
    d = Drill()
    try:
        d.write_state({"phase": UA.STATE_VERIFY, "target": d.target,
                       "backup_program": "", "attempts": 1})
        b = WebBridge.__new__(WebBridge)
        with mock.patch("ui.web_bridge.get_app_data_dir", return_value=d.data_dir):
            msg = b.updateFrontendReady()
        assert isinstance(msg, str) and "已更新到" in msg, msg
        assert not os.path.exists(os.path.join(d.data_dir, UA.STATE_FILE))
        print("[桥-前端就绪握手确认] OK")
    finally:
        d.close()


def test_startup_heals_stale_new_files():
    """启动自愈清理根级白名单 *.new；不碰非白名单与用户数据区（D9）"""
    d = Drill()
    try:
        for name in ("KazariPlay.exe.new", "LICENSE.new"):
            open(os.path.join(d.target, name), "wb").close()
        open(os.path.join(d.target, "custom.new"), "wb").close()
        os.makedirs(os.path.join(d.data_dir, "x"), exist_ok=True)
        open(os.path.join(d.data_dir, "x", "a.new"), "wb").close()
        d.write_state({"phase": UA.STATE_ROLLED_BACK, "target": d.target, "msg": "已回滚"})
        notice, exit_req = UA.startup_self_heal(d.data_dir)
        assert notice and exit_req is False
        assert not os.path.exists(os.path.join(d.target, "KazariPlay.exe.new"))
        assert not os.path.exists(os.path.join(d.target, "LICENSE.new"))
        assert os.path.exists(os.path.join(d.target, "custom.new"))
        assert os.path.exists(os.path.join(d.data_dir, "x", "a.new"))
        print("[自愈-清理根级 *.new] OK")
    finally:
        d.close()


def test_cleanup_ready_cache_and_extract():
    """清理规则：待回滚保留 extract 与就绪 zip；确认后（keep_ready=False）全清"""
    with tempfile.TemporaryDirectory() as tmp:
        cache = os.path.join(tmp, "update_cache")
        extract = os.path.join(cache, "extract")
        os.makedirs(extract)
        zip_path = os.path.join(cache, "KazariPlay-win64.zip")
        with open(zip_path, "wb") as f:
            f.write(b"x")
        with open(os.path.join(cache, "KazariPlay-win64.zip.part"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(cache, "ready.json"), "w", encoding="utf-8") as f:
            json.dump({"zip": "KazariPlay-win64.zip"}, f, ensure_ascii=False)
        UA.cleanup_update_cache(tmp, keep_extract=True)
        assert os.path.isdir(extract)
        assert os.path.isfile(zip_path)          # 就绪缓存引用的 zip 保留
        assert os.path.isfile(os.path.join(cache, "ready.json"))
        assert not os.path.exists(os.path.join(cache, "KazariPlay-win64.zip.part"))
        UA.cleanup_update_cache(tmp, keep_ready=False)
        assert not os.path.exists(extract)
        assert not os.path.exists(zip_path)
        assert not os.path.exists(os.path.join(cache, "ready.json"))
        print("[清理-就绪 zip/解压目录/确认全清] OK")


if __name__ == "__main__":
    test_apply_success()
    test_apply_rollback_on_failure()
    test_apply_refuses_data_in_package()
    test_apply_backup_failure_aborts()
    test_apply_state_write_failure_aborts()
    test_apply_space_precheck_aborts()
    test_apply_verify_state_write_failure_rolls_back()
    test_apply_launch_failure_rolls_back()
    test_apply_early_exit_rolls_back()
    test_apply_wait_process_failure_aborts()
    test_self_heal_applying_interrupt()
    test_self_heal_applying_not_started()
    test_self_heal_verify_pending_two_strikes()
    test_self_heal_spawn_failure_keeps_state()
    test_self_heal_rolled_back_notice()
    test_rollback_helper_waits_real_file_lock()
    test_install_lock_exclusive_and_stale()
    test_relative_forbidden_scope()
    test_backup_rolling_three()
    test_wait_process_exit()
    test_wait_process_exit_kill_failure_raises()
    test_bridge_update_claim_atomic()
    test_bridge_single_entry_repeat_trigger()
    test_frontend_ready_handshake()
    test_startup_heals_stale_new_files()
    test_cleanup_ready_cache_and_extract()
    print("UPDATE APPLY TEST PASS")
