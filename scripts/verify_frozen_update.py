"""冻结包受控更新/回滚演练（宿主侧；真实进程、真实文件占用，不触网、不碰用户数据）

用法：
    python scripts/verify_frozen_update.py --package <构建目录>/dist/KazariPlay

场景：
1) 更新：以包内 KazariPlay.exe 为替换助手（--apply-update）→ 等待旧进程 →
   备份数据 → 白名单替换 → 拉起新版（真实 GUI）→ 前端就绪握手 → 清理 _old；
2) 回滚：目标 EXE 被真实占用（拒写句柄）→ 包内 --apply-rollback 等待/强杀 →
   从程序备份恢复旧版 → 写入 rolled_back 状态；
3) 安装锁：安装目录已有活动更新任务时，回滚入口放弃（rc=2）。

完成后核对：新版程序文件生效、数据库哨兵数据保留、更新前备份存在、
回滚资源（_old / 状态 / 锁）清理。演练使用临时目录，结束后退出全部测试进程。
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PY = sys.executable

OLD_TREE = {
    "KazariPlay.exe": b"OLD-EXE",
    "_internal/old.dll": b"old-dll",
    "LICENSE": b"lic-old",
}

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


def wait_for(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError(message)


def kill_package_processes(tmp_root):
    """结束本次演练目录下被拉起的 KazariPlay 进程并等待退出"""
    marker = os.path.basename(str(tmp_root))
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'KazariPlay.exe' -and $_.ExecutablePath -like '*"
        + marker + "*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
        "Wait-Process -Id $_.ProcessId -Timeout 15 -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", command],
                   capture_output=True, timeout=60)


def scenario_update(package: Path, tmp: str):
    target = os.path.join(tmp, "update", "KazariPlay")
    data = os.path.join(target, "data")
    os.makedirs(data)
    write_tree(target, OLD_TREE)
    db = sqlite3.connect(os.path.join(data, "games.db"))
    db.execute("CREATE TABLE sentinel(x INTEGER)")   # 旧库有效数据：更新后必须保留
    db.execute("INSERT INTO sentinel VALUES (42)")
    db.commit()
    db.close()
    Path(data, "config.json").write_text('{"theme": "light"}', encoding="utf-8")

    env = dict(os.environ)
    env["KAZARIPLAY_DATA_DIR"] = data
    helper = subprocess.Popen(
        [str(package / "KazariPlay.exe"), "--apply-update", "--pid", "0",
         "--target", target, "--data-dir", data], env=env)
    state_file = os.path.join(data, "update_state.json")

    def verify_pending():
        try:
            with open(state_file, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            return False
        return st.get("phase") == "verify_pending"

    wait_for(verify_pending, 120, "未进入待验证状态（替换未完成）")
    # 新版被拉起；前端首屏加载成功（就绪握手）后清除状态并清理 _old
    wait_for(lambda: not os.path.exists(state_file), 90, "前端就绪握手未完成")
    assert helper.wait(timeout=60) == 0, "更新助手退出码非 0"

    assert (package / "KazariPlay.exe").read_bytes() == \
        Path(target, "KazariPlay.exe").read_bytes(), "新版程序文件未生效"
    assert not os.path.exists(os.path.join(target, "_internal", "old.dll"))
    kill_package_processes(tmp)
    time.sleep(0.5)
    db = sqlite3.connect(os.path.join(data, "games.db"))
    assert db.execute("SELECT x FROM sentinel").fetchone()[0] == 42, "用户数据丢失"
    db.close()
    assert os.path.isfile(os.path.join(data, "config.json"))
    backups = os.listdir(os.path.join(data, "backup"))
    assert backups and os.path.isfile(os.path.join(data, "backup", backups[0], "games.db")), \
        "缺少更新前数据备份"
    assert not os.path.exists(os.path.join(target, "_old")), "回滚资源未清理"
    assert not os.path.exists(os.path.join(target, "_update.lock"))
    print("[冻结演练-更新+握手+数据保全] OK")


def scenario_rollback(package: Path, tmp: str):
    target = os.path.join(tmp, "rollback", "KazariPlay")
    data = os.path.join(target, "data")
    os.makedirs(data)
    Path(target, "KazariPlay.exe").write_bytes(b"NEW-EXE")
    Path(target, "_internal").mkdir()
    Path(target, "_internal", "new.dll").write_bytes(b"new-dll")
    Path(data, "config.json").write_text("{}", encoding="utf-8")
    old_dir = os.path.join(target, "_old", "stamp")
    write_tree(old_dir, OLD_TREE)
    state_file = os.path.join(data, "update_state.json")
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"phase": "verify_pending", "target": target,
                   "backup_program": old_dir, "attempts": 2}, f)

    exe = os.path.join(target, "KazariPlay.exe")
    locker = subprocess.Popen([PY, "-c", LOCK_SCRIPT, exe])
    time.sleep(1.0)
    assert locker.poll() is None, "占用进程未启动"
    env = dict(os.environ)
    env["KAZARIPLAY_DATA_DIR"] = data
    helper = subprocess.Popen(
        [str(package / "KazariPlay.exe"), "--apply-rollback", "--pid", str(locker.pid),
         "--target", target, "--data-dir", data], env=env)
    try:
        assert helper.wait(timeout=120) == 0, "回滚助手退出码非 0"
        assert Path(exe).read_bytes() == b"OLD-EXE", "旧版未恢复"
        with open(state_file, encoding="utf-8") as f:
            st = json.load(f)
        assert st.get("phase") == "rolled_back", st
        wait_for(lambda: locker.poll() is not None, 10, "占用进程未被结束")
        assert not os.path.exists(os.path.join(target, "_update.lock"))
    finally:
        if locker.poll() is None:
            locker.kill()
    print("[冻结演练-真实占用下回滚恢复] OK")


def scenario_install_lock(package: Path, tmp: str):
    target = os.path.join(tmp, "lock", "KazariPlay")
    data = os.path.join(target, "data")
    os.makedirs(data)
    Path(target, "KazariPlay.exe").write_bytes(b"NEW-EXE")
    with open(os.path.join(data, "update_state.json"), "w", encoding="utf-8") as f:
        json.dump({"phase": "verify_pending", "target": target,
                   "backup_program": "", "attempts": 2}, f)
    lock = os.path.join(target, "_update.lock")
    with open(lock, "w", encoding="ascii") as f:
        f.write(str(os.getpid()))   # 活动锁（本进程存活）
    env = dict(os.environ)
    env["KAZARIPLAY_DATA_DIR"] = data
    helper = subprocess.Popen(
        [str(package / "KazariPlay.exe"), "--apply-rollback", "--pid", "0",
         "--target", target, "--data-dir", data], env=env)
    assert helper.wait(timeout=60) == 2, "已有活动任务时应放弃（rc=2）"
    assert Path(target, "KazariPlay.exe").read_bytes() == b"NEW-EXE"
    os.remove(lock)
    print("[冻结演练-安装锁互斥] OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True,
                        help="冻结包的程序目录（含 KazariPlay.exe 与 _internal）")
    args = parser.parse_args()
    package = args.package.resolve()
    if os.name != "nt":
        raise RuntimeError("Windows desktop required")
    if not (package / "KazariPlay.exe").is_file():
        raise SystemExit("Not a frozen package directory: " + str(package))
    if not shutil.which("powershell"):
        raise SystemExit("powershell is required")

    tmp = tempfile.mkdtemp(prefix="kazari_frozen_verify_")
    try:
        scenario_update(package, tmp)
        scenario_rollback(package, tmp)
        scenario_install_lock(package, tmp)
    finally:
        try:
            kill_package_processes(tmp)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    print("FROZEN UPDATE VERIFY PASS")


if __name__ == "__main__":
    main()
