"""更新流程进程级冒烟（真实助手子进程 / 真实文件占用；不触网、不碰用户数据）

场景：
1) 正常更新：等待旧进程退出 → 备份用户数据 → 白名单替换 → 拉起新版 →
   前端就绪握手（调用真实的 mark_startup_success）→ 助手成功收尾；
2) 回滚助手（main.py --apply-rollback）：目标 EXE 被真实占用（拒写句柄）→
   等待/强杀 → 从程序备份恢复旧版 → rolled_back 状态；
3) 安装锁：安装目录已有活动更新任务时，回滚入口放弃（rc=2，不改动文件）。

前置：Windows；已编译 overlay/bin/overlay.exe（复制为"新版程序"作为长驻占位）。
用法：python tests/smoke_update_flow.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAZARI = ROOT / "src" / "kazari_play"
PY = sys.executable
OVERLAY = ROOT / "overlay" / "bin" / "overlay.exe"

OLD_TREE = {
    "KazariPlay.exe": b"OLD-EXE",
    "_internal/old.dll": b"old-dll",
    "_internal/common.dll": b"common-v1",
    "LICENSE": b"lic-v1",
}
NEW_TREE = {
    "_internal/new.dll": b"new-dll",
    "_internal/common.dll": b"common-v2",
    "LICENSE": b"lic-v2",
}
DATA_FILES = {"games.db": b"db-bytes", "config.json": b'{"theme": "light"}'}

LOCK_SCRIPT = (
    "import ctypes, sys, time\n"
    "k = ctypes.windll.kernel32\n"
    "k.CreateFileW.restype = ctypes.c_void_p\n"
    "h = k.CreateFileW(sys.argv[1], 0x80000000, 1, None, 3, 0, None)\n"
    "if not h or h == 0xFFFFFFFFFFFFFFFF:\n"
    "    sys.exit(3)\n"
    "time.sleep(120)\n"
)


def write_tree(root, tree):
    for rel, content in tree.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def read_bytes(path):
    return Path(path).read_bytes()


def helper_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(KAZARI) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def wait_for(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(message)


def kill_spawned_app(tmp_root):
    """结束由助手拉起、位于本次临时目录下的实验进程并等待退出（按目录名匹配，避免误伤）"""
    marker = os.path.basename(str(tmp_root).rstrip("\\/"))
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'KazariPlay.exe' -and $_.ExecutablePath -like '*"
        + marker + "*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
        "Wait-Process -Id $_.ProcessId -Timeout 15 -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", command],
                   capture_output=True, timeout=60)


def scenario_apply(tmp):
    target = os.path.join(tmp, "apply", "KazariPlay")
    source = os.path.join(tmp, "apply", "extract")
    data = os.path.join(target, "data")
    write_tree(target, OLD_TREE)
    write_tree(data, DATA_FILES)
    write_tree(source, NEW_TREE)
    shutil.copy2(OVERLAY, os.path.join(source, "KazariPlay.exe"))
    # 以"程序目录中的 main.py"运行真实入口（argv[0] 所在目录 = 助手自身程序根）
    shutil.copy2(KAZARI / "main.py", os.path.join(source, "main.py"))

    old = subprocess.Popen([PY, "-c", "import time; time.sleep(2.0)"])
    helper = subprocess.Popen(
        [PY, os.path.join(source, "main.py"), "--apply-update",
         "--pid", str(old.pid), "--target", target, "--data-dir", data],
        cwd=source, env=helper_env())

    state_file = os.path.join(data, "update_state.json")
    overlay_bytes = read_bytes(OVERLAY)

    def pending_ready():
        try:
            with open(state_file, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            return False
        return (st.get("phase") == "verify_pending"
                and read_bytes(os.path.join(target, "KazariPlay.exe")) == overlay_bytes)

    wait_for(pending_ready, 90, "未观察到待验证状态（替换未完成）")
    # 模拟前端就绪握手（桥 updateFrontendReady 调用的同一函数）
    handshake = subprocess.run(
        [PY, "-c", ("import sys; sys.path.insert(0, r'%s'); "
                    "from utils.update.update_apply import mark_startup_success; "
                    "mark_startup_success(r'%s')") % (KAZARI, data)],
        env=helper_env(), capture_output=True, timeout=60)
    assert handshake.returncode == 0, handshake.stderr

    rc = helper.wait(timeout=120)
    assert rc == 0, "助手退出码 %s" % rc
    # 程序：新文件生效、旧文件镜像清理
    assert read_bytes(os.path.join(target, "KazariPlay.exe")) == overlay_bytes
    assert read_bytes(os.path.join(target, "_internal", "new.dll")) == b"new-dll"
    assert read_bytes(os.path.join(target, "_internal", "common.dll")) == b"common-v2"
    assert not os.path.exists(os.path.join(target, "_internal", "old.dll"))
    # 数据：原样保留 + 备份生成 + 回滚资源清理
    assert read_bytes(os.path.join(data, "games.db")) == b"db-bytes"
    backups = os.listdir(os.path.join(data, "backup"))
    assert backups, "缺少更新前数据备份"
    assert os.path.isfile(os.path.join(data, "backup", backups[0], "games.db"))
    assert not os.path.exists(state_file)
    assert not os.path.exists(os.path.join(target, "_old"))
    assert not os.path.exists(os.path.join(target, "_update.lock"))
    print("[流程-正常更新+数据保全+握手清理] OK")


def scenario_rollback(tmp):
    target = os.path.join(tmp, "rollback", "KazariPlay")
    data = os.path.join(target, "data")
    write_tree(target, {"KazariPlay.exe": b"NEW-EXE",
                        "_internal/common.dll": b"common-v2"})
    write_tree(data, DATA_FILES)
    old_dir = os.path.join(target, "_old", "stamp")
    write_tree(old_dir, OLD_TREE)
    with open(os.path.join(data, "update_state.json"), "w", encoding="utf-8") as f:
        json.dump({"phase": "verify_pending", "target": target,
                   "backup_program": old_dir, "attempts": 2}, f)

    exe = os.path.join(target, "KazariPlay.exe")
    locker = subprocess.Popen([PY, "-c", LOCK_SCRIPT, exe])
    time.sleep(1.0)
    assert locker.poll() is None, "占位进程未启动"

    helper = subprocess.Popen(
        [PY, str(KAZARI / "main.py"), "--apply-rollback",
         "--pid", str(locker.pid), "--target", target, "--data-dir", data],
        env=helper_env())
    try:
        rc = helper.wait(timeout=120)
        assert rc == 0, "回滚助手退出码 %s" % rc
        assert read_bytes(exe) == b"OLD-EXE"
        assert read_bytes(os.path.join(target, "_internal", "common.dll")) == b"common-v1"
        with open(os.path.join(data, "update_state.json"), encoding="utf-8") as f:
            st = json.load(f)
        assert st.get("phase") == "rolled_back", st
        wait_for(lambda: locker.poll() is not None, 10, "占用进程未被助手结束")
        assert not os.path.exists(os.path.join(target, "_update.lock"))
    finally:
        if locker.poll() is None:
            locker.kill()
    print("[流程-真实占用下回滚助手恢复] OK")


def scenario_install_lock(tmp):
    target = os.path.join(tmp, "lock", "KazariPlay")
    data = os.path.join(target, "data")
    write_tree(target, {"KazariPlay.exe": b"NEW-EXE"})
    write_tree(data, DATA_FILES)
    with open(os.path.join(data, "update_state.json"), "w", encoding="utf-8") as f:
        json.dump({"phase": "verify_pending", "target": target,
                   "backup_program": "", "attempts": 2}, f)
    lock = os.path.join(target, "_update.lock")
    with open(lock, "w", encoding="ascii") as f:
        f.write(str(os.getpid()))   # 活动锁（本进程存活）

    helper = subprocess.Popen(
        [PY, str(KAZARI / "main.py"), "--apply-rollback",
         "--pid", "0", "--target", target, "--data-dir", data],
        env=helper_env())
    rc = helper.wait(timeout=60)
    assert rc == 2, "已有活动任务时应放弃（rc=2），实际 %s" % rc
    assert read_bytes(os.path.join(target, "KazariPlay.exe")) == b"NEW-EXE"
    with open(os.path.join(data, "update_state.json"), encoding="utf-8") as f:
        assert json.load(f).get("phase") == "verify_pending"
    os.remove(lock)
    print("[流程-安装锁互斥] OK")


def main():
    if os.name != "nt":
        raise RuntimeError("Windows desktop required")
    if not OVERLAY.is_file():
        raise RuntimeError("Build Overlay first: " + str(OVERLAY))
    with tempfile.TemporaryDirectory(prefix="kazari_update_flow_",
                                     ignore_cleanup_errors=True) as tmp:
        try:
            scenario_apply(tmp)
            scenario_rollback(tmp)
            scenario_install_lock(tmp)
        finally:
            try:
                kill_spawned_app(tmp)   # 结束"新版程序"占位进程，释放临时目录
            except Exception:
                pass
    print("UPDATE FLOW SMOKE PASS")


if __name__ == "__main__":
    main()
