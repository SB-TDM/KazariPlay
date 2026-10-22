"""应用内更新的替换助手与启动自愈（见 docs/dev/AUTO_UPDATE_DESIGN.md §2/§6）

- **助手模式**：`KazariPlay.exe --apply-update --pid <旧PID> --target <安装目录> --data-dir <数据目录>`
  等待旧进程退出（超时强杀并确认退出，无法确认即中止）→ 备份用户数据（失败即中止）→
  备份程序文件（硬链接优先，失败回退复制；不移动目标文件）→ 白名单替换（失败回滚）→
  拉起新版。拉起异常或新版在启动确认前退出时立即回滚并拉起旧版；替换期间以安装目录锁
  保证同一安装目录至多一个替换任务。
- **回滚助手模式**：`KazariPlay.exe --apply-rollback ...`，由启动自愈从更新解压缓存中拉起，
  等待当前进程退出后从程序备份恢复旧版并拉起（避免覆盖运行中 EXE/_internal 的文件锁失败）。
- **启动自愈**：应用启动早期调用 `startup_self_heal()`：
  - `applying`（助手中断）→ 拉起回滚助手；
  - `verify_pending`（新版未确认首启成功）→ 第二次启动仍未确认则拉起回滚助手；
  - `rolled_back` → 消费提示并清理。
  回滚助手拉起失败时保留状态、备份与可诊断错误，不误报成功。
  新版前端完成首屏数据加载后经桥调用 `mark_startup_success()` 完成两段确认并清理旧文件。
- **用户数据保护**：`data/`、`screenshots/`、`logs/` 永不进入替换集（断言命中即中止）；
  数据只在替换前做只读备份，绝不改写、迁移或删除。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Callable, List, Optional, Tuple

from utils.infra.logger import get_logger
from utils.update.updater import READY_FILE, ensure_free_space

logger = get_logger()

STATE_FILE = "update_state.json"
STATE_APPLYING = "applying"
STATE_VERIFY = "verify_pending"
STATE_ROLLED_BACK = "rolled_back"
LOCK_FILE = "_update.lock"

# 程序文件白名单（替换集 = 这些条目；助手由"新版本"的代码执行，清单随新版本走）
PROGRAM_WHITELIST = {
    "KazariPlay.exe", "KazariPlayBackend.exe", "_internal",
    "LICENSE", "THIRD_PARTY.md", "RELEASE_NOTES.md", "TRIAL_README.txt",
    "BUILD_INFO.json", "run_develop.cmd",
}
# 禁用区（用户数据）；任何目标路径命中即中止
FORBIDDEN_PARTS = {"data", "screenshots", "logs"}
BACKUP_KEEP = 3
EARLY_EXIT_GRACE = 8.0       # 新版启动后观察窗口：确认前退出 → 回滚（秒）
APPLY_SPACE_MARGIN = 64 * 1024 * 1024    # 替换前预留空间余量


class UpdateStateError(RuntimeError):
    """更新状态持久化失败（调用方必须按失败语义处理）"""


# ---------- 状态文件 ----------

def _state_path(data_dir: str) -> str:
    return os.path.join(data_dir, STATE_FILE)


def _read_state(data_dir: str) -> Optional[dict]:
    try:
        with open(_state_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_state(data_dir: str, state: dict) -> None:
    """原子写入状态文件（临时文件 + os.replace）；失败抛 UpdateStateError"""
    try:
        os.makedirs(data_dir, exist_ok=True)
        path = _state_path(data_dir)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        raise UpdateStateError(f"更新状态写入失败：{e}") from e


def _write_state_best_effort(data_dir: str, state: dict) -> bool:
    """尽力写入状态（失败只记录，不抛出；状态文件保持原样）"""
    try:
        _write_state(data_dir, state)
        return True
    except Exception as e:
        logger.error("状态写入失败（保留现状与备份）：%s", e)
        return False


def _delete_state(data_dir: str) -> None:
    try:
        os.remove(_state_path(data_dir))
    except OSError:
        pass


def has_pending_update_state(data_dir: str) -> bool:
    """是否存在待自愈/待确认的更新状态（applying / verify_pending）"""
    st = _read_state(data_dir)
    return bool(st and st.get("phase") in (STATE_APPLYING, STATE_VERIFY))


# ---------- 路径与断言 ----------

def current_install_dir() -> str:
    """当前运行的安装目录（仅冻结形态；源码运行返回空 = 不支持自动替换）"""
    if not getattr(sys, "frozen", False):
        return ""
    return os.path.dirname(os.path.abspath(sys.executable))


def _relative_forbidden(target: str, path: str) -> bool:
    """path 相对 target 是否越出 target，或落在其根级用户数据区（data/screenshots/logs）

    只认根级段：程序内部资源可能含同名子目录（如 `_internal/cv2/data`），
    不视为用户数据。
    """
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(target))
    except ValueError:
        return True
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return True
    parts = [p.lower() for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    return bool(parts) and parts[0] in FORBIDDEN_PARTS


def build_replace_plan(target: str, source: str) -> List[Tuple[str, str]]:
    """生成 (源, 目标) 替换清单：仅白名单条目；源含用户数据目录 / 目标命中禁用区即中止"""
    plan: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(source)):
        if name.lower() in FORBIDDEN_PARTS:
            raise RuntimeError(f"更新包包含用户数据目录，已拒绝：{name}")
        if name not in PROGRAM_WHITELIST:
            continue
        src_entry = os.path.join(source, name)
        if os.path.isdir(src_entry):
            for root, _dirs, files in os.walk(src_entry):
                for f in files:
                    s = os.path.join(root, f)
                    dst = os.path.join(target, os.path.relpath(s, source))
                    if _relative_forbidden(target, dst):
                        raise RuntimeError(f"替换目标命中用户数据区：{dst}")
                    plan.append((s, dst))
        else:
            dst = os.path.join(target, name)
            if _relative_forbidden(target, dst):
                raise RuntimeError(f"替换目标命中用户数据区：{dst}")
            plan.append((src_entry, dst))
    if not any(os.path.basename(d) == "KazariPlay.exe" for _s, d in plan):
        raise RuntimeError("更新包缺少 KazariPlay.exe")
    return plan


# ---------- 安装目录互斥锁 ----------

def _lock_stale(lock: str) -> bool:
    try:
        with open(lock, encoding="ascii") as f:
            pid = int((f.read() or "0").strip() or 0)
    except Exception:
        return True
    return pid <= 0 or not _process_alive(pid)


def _acquire_install_lock(target: str) -> Optional[str]:
    """安装目录级互斥锁（O_EXCL 创建；陈旧锁按 PID 清理后重试一次）

    返回锁文件路径；已有活动任务时返回 None（调用方必须放弃本次替换）。
    """
    lock = os.path.join(target, LOCK_FILE)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return lock
        except FileExistsError:
            if not _lock_stale(lock):
                return None
            try:
                os.remove(lock)
            except OSError:
                return None
        except OSError as e:
            logger.error("创建更新锁失败：%s", e)
            return None
    return None


def _release_install_lock(lock: Optional[str]) -> None:
    if lock:
        try:
            os.remove(lock)
        except OSError:
            pass


# ---------- 备份 ----------

def backup_user_data(data_dir: str, stamp: Optional[str] = None) -> Optional[str]:
    """只读备份 games.db + config.json 到 data/backup/<时间戳>/；滚动保留最近 BACKUP_KEEP 份

    返回备份目录；没有需要备份的文件返回 None；备份失败抛异常（调用方必须中止更新）。
    """
    names = [n for n in ("games.db", "config.json") if os.path.isfile(os.path.join(data_dir, n))]
    if not names:
        return None
    name = stamp or time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(data_dir, "backup", name)
    os.makedirs(dest, exist_ok=True)
    for n in names:
        shutil.copy2(os.path.join(data_dir, n), os.path.join(dest, n))
    prune_backups(data_dir)
    return dest


def prune_backups(data_dir: str, keep: int = BACKUP_KEEP) -> None:
    root = os.path.join(data_dir, "backup")
    if not os.path.isdir(root):
        return
    dirs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for d in dirs[:-keep] if keep > 0 else dirs:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _link_or_copy(src: str, dst: str) -> None:
    """优先硬链接（同卷、瞬间完成、不复制数据），不支持时回退复制"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _backup_complete_path(backup_root: str) -> str:
    return os.path.join(backup_root, ".backup_complete")


def _backup_program(target: str, backup_root: str) -> None:
    """把 target 中现有的白名单程序条目备份到 backup_root（硬链接优先，失败回退复制）

    硬链接备份不复制数据、也不移动目标文件——任何时刻安装目录都保持可运行；
    FAT/exFAT 等不支持硬链接的文件系统自动回退为复制。
    """
    os.makedirs(backup_root, exist_ok=True)
    for name in PROGRAM_WHITELIST:
        src = os.path.join(target, name)
        if os.path.isfile(src):
            _link_or_copy(src, os.path.join(backup_root, name))
        elif os.path.isdir(src):
            for root, _dirs, files in os.walk(src):
                rel = os.path.relpath(root, target)
                dst_root = os.path.join(backup_root, rel)
                os.makedirs(dst_root, exist_ok=True)
                for f in files:
                    _link_or_copy(os.path.join(root, f), os.path.join(dst_root, f))
    with open(_backup_complete_path(backup_root), "w", encoding="utf-8") as f:
        f.write("ok")


# ---------- 替换 / 回滚 ----------

def _copy_new_files(plan: List[Tuple[str, str]]) -> None:
    """逐文件先写 .new 再原子替换，保证任何时刻目标文件要么旧要么新（完整）"""
    for src, dst in plan:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".new"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)


def _remove_stale(target: str, plan: List[Tuple[str, str]]) -> None:
    """镜像语义：删除 target/_internal 中不在新包清单里的旧文件"""
    newset = {os.path.normcase(os.path.normpath(d)) for _s, d in plan}
    root = os.path.join(target, "_internal")
    if not os.path.isdir(root):
        return
    for base, _dirs, files in os.walk(root):
        for f in files:
            path = os.path.join(base, f)
            if os.path.normcase(os.path.normpath(path)) not in newset:
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning("清理旧文件失败（忽略）：%s（%s）", path, e)


def _restore(backup_root: str, target: str) -> None:
    """从程序备份整目录恢复（镜像）：目录整体替换，文件复制覆盖

    备份可能是硬链接：当目标文件与备份条目仍是同一个文件（替换尚未发生）时跳过，
    避免 copy2 的 SameFileError，并保持重复恢复的幂等性。
    """
    backup_names = set(os.listdir(backup_root))
    for name in os.listdir(backup_root):
        src = os.path.join(backup_root, name)
        dst = os.path.join(target, name)
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            try:
                if os.path.exists(dst) and os.path.samefile(src, dst):
                    continue
            except OSError:
                pass
            shutil.copy2(src, dst)
    for name in PROGRAM_WHITELIST:
        if name in backup_names:
            continue
        stale = os.path.join(target, name)
        if os.path.isfile(stale):
            try:
                os.remove(stale)
            except OSError as e:
                logger.warning("回滚清理新程序文件失败（忽略）：%s（%s）", stale, e)


# ---------- 进程 ----------

def _process_alive(pid: int) -> bool:
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x00000102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def wait_process_exit(pid: int, timeout: float = 30.0) -> None:
    """等待进程退出；超时后 taskkill /T /F 结束进程树并确认退出

    无法确认退出时抛 RuntimeError（调用方不得继续备份或替换）。
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return
        time.sleep(0.2)
    if not _process_alive(pid):
        return
    logger.info("等待进程 %s 超时，强杀进程树", pid)
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       capture_output=True)
    except Exception as e:
        raise RuntimeError(f"taskkill 执行失败：{e}") from e
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return
        time.sleep(0.2)
    raise RuntimeError(f"无法结束进程 {pid}（强杀后仍存活），已中止更新")


# ---------- 启动 / 拉起 ----------

def _launch_default(exe: str):
    return subprocess.Popen([exe], cwd=os.path.dirname(exe),
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def _launch_quiet(launch: Callable[[str], object], exe: str) -> None:
    try:
        launch(exe)
    except Exception as e:
        logger.error("拉起失败（%s）：%s", exe, e)


def _read_build_version(root: str) -> str:
    try:
        with open(os.path.join(root, "BUILD_INFO.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "")
    except Exception:
        return ""


def _await_startup(data_dir: str, proc) -> bool:
    """等待新版启动确认（前端握手会清理状态文件）；False = 进程在确认前退出

    无法观察进程（测试替身 / 无 poll）时视为通过，交给两振自愈兜底。
    """
    if proc is None or not hasattr(proc, "poll"):
        return True
    deadline = time.monotonic() + EARLY_EXIT_GRACE
    while time.monotonic() < deadline:
        if not os.path.exists(_state_path(data_dir)):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.25)
    return True


# ---------- 助手主流程 ----------

def _estimate_program_size(target: str) -> int:
    """估算 target 中白名单程序条目总字节数（替换前空间预检用）"""
    total = 0
    for name in PROGRAM_WHITELIST:
        path = os.path.join(target, name)
        if os.path.isfile(path):
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        elif os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
    return total


def apply_update(pid: int, target: str, source: str, data_dir: str,
                 launch: Optional[Callable[[str], object]] = None,
                 wait_timeout: float = 30.0, backend_pid: int = 0) -> int:
    """执行替换；返回 0=成功（已拉起新版）、1=失败（已回滚/未开始，已尝试拉起旧版）"""
    launch = launch or _launch_default
    target = os.path.abspath(target)
    source = os.path.abspath(source)
    data_dir = os.path.abspath(data_dir)
    old_exe = os.path.join(target, "KazariPlay.exe")
    marker: Optional[dict] = None
    timings = {"wait_exit": 0.0, "backup_data": 0.0, "backup_program": 0.0,
               "replace": 0.0, "launch": 0.0}
    started = time.monotonic()

    def _log_phases() -> None:
        total = time.monotonic() - started
        logger.info(
            "更新阶段耗时：wait_exit=%.2fs backup_data=%.2fs backup_program=%.2fs "
            "replace=%.2fs launch=%.2fs 总计=%.2fs",
            timings["wait_exit"], timings["backup_data"], timings["backup_program"],
            timings["replace"], timings["launch"], total)

    def abort(msg: str) -> int:
        """未进入替换：记录原因并尽力拉起旧版（旧进程仍存活时不重复拉起）"""
        logger.error("%s", msg)
        state = dict(marker or {
            "target": target,
            "new_version": _read_build_version(source),
            "old_version": _read_build_version(target),
            "backup_program": "", "backup_data": "", "attempts": 0,
        })
        state.update({"phase": STATE_ROLLED_BACK, "msg": msg})
        _write_state_best_effort(data_dir, state)
        if pid == 0 or not _process_alive(pid):
            _launch_quiet(launch, old_exe)
        return 1

    def rollback(msg: str) -> int:
        """替换后失败：恢复程序文件并拉起旧版；恢复失败时保留状态与备份"""
        restored = False
        try:
            _restore(old_dir, target)
            restored = True
        except Exception as re:
            logger.error("回滚恢复失败（保留状态与备份）：%s", re)
            _write_state_best_effort(data_dir, {**(marker or {}), "rollback_error": str(re)})
        if restored:
            _write_state_best_effort(data_dir, {**(marker or {}),
                                                "phase": STATE_ROLLED_BACK, "msg": msg})
        _launch_quiet(launch, old_exe)
        return 1

    try:
        # 1) 等待旧进程退出（无法确认退出即中止，不进入备份与替换）
        t0 = time.monotonic()
        try:
            if pid:
                wait_process_exit(pid, timeout=wait_timeout)
            if backend_pid and backend_pid != pid:
                wait_process_exit(backend_pid, timeout=wait_timeout)
        except Exception as e:
            return abort(f"更新中止：无法结束旧进程（{e}）")
        finally:
            timings["wait_exit"] = time.monotonic() - t0

        # 2) 前置校验与备份（任何失败都不做替换；状态不可写即中止）
        t0 = time.monotonic()
        try:
            plan = build_replace_plan(target, source)          # 先校验，后任何改动
            ensure_free_space(target,
                              _estimate_program_size(target) + APPLY_SPACE_MARGIN,
                              "替换程序文件")
            t1 = time.monotonic()
            data_backup = backup_user_data(data_dir) or ""     # 备份失败即抛异常
            timings["backup_data"] = time.monotonic() - t1
            stamp = time.strftime("%Y%m%d-%H%M%S")
            old_dir = os.path.join(target, "_old", stamp)
            marker = {
                "phase": STATE_APPLYING, "target": target,
                "new_version": _read_build_version(source), "old_version": _read_build_version(target),
                "backup_program": old_dir, "backup_data": data_backup,
                "backup_program_complete": False,
                "attempts": 0, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            # 先落盘状态（硬链接备份不移动目标文件）：中断后可由启动自愈恢复，
            # 也避免备份完成但状态未写留下无人清理的 _old。
            _write_state(data_dir, marker)
            t1 = time.monotonic()
            _backup_program(target, old_dir)
            timings["backup_program"] = time.monotonic() - t1
        except Exception as e:
            return abort(f"更新未执行（前置检查或备份失败）：{e}")

        # 3) 白名单替换；失败立即回滚
        t0 = time.monotonic()
        try:
            _copy_new_files(plan)
            _remove_stale(target, plan)
        except Exception as e:
            timings["replace"] = time.monotonic() - t0
            logger.warning("替换失败，回滚：%s", e)
            return rollback(f"更新失败，已回滚：{e}")
        timings["replace"] = time.monotonic() - t0

        # 4) 持久化"待验证"；不可写即回滚（避免状态不可恢复的替换）
        try:
            _write_state(data_dir, {**marker, "phase": STATE_VERIFY, "attempts": 0})
        except Exception as e:
            logger.error("待验证状态写入失败，回滚：%s", e)
            return rollback(f"更新失败，已回滚：状态不可写（{e}）")

        # 5) 拉起新版；拉起异常立即回滚
        t0 = time.monotonic()
        try:
            proc = launch(os.path.join(target, "KazariPlay.exe"))
        except Exception as e:
            timings["launch"] = time.monotonic() - t0
            logger.error("拉起新版失败，回滚：%s", e)
            return rollback(f"新版本拉起失败，已回滚：{e}")
        timings["launch"] = time.monotonic() - t0
        logger.info("已拉起新版：%s", time.strftime("%Y-%m-%dT%H:%M:%S"))

        # 6) 观察启动：新版在完成启动确认前退出 → 立即回滚
        if not _await_startup(data_dir, proc):
            logger.warning("新版本启动后未确认即退出，回滚")
            return rollback("新版本启动失败，已回滚到更新前的版本")
        return 0
    finally:
        _log_phases()


def _find_helper_exe(data_dir: str) -> str:
    """回滚助手程序来源：更新解压缓存（不占用目标目录，可安全覆盖目标文件）"""
    base = os.path.join(data_dir, "update_cache", "extract")
    direct = os.path.join(base, "KazariPlay.exe")
    if os.path.isfile(direct):
        return direct
    try:
        entries = [e for e in os.listdir(base) if not e.startswith(".")]
        if len(entries) == 1:
            cand = os.path.join(base, entries[0], "KazariPlay.exe")
            if os.path.isfile(cand):
                return cand
    except OSError:
        pass
    return ""


def _spawn_rollback_helper(target: str, data_dir: str) -> bool:
    """拉起独立回滚助手（等待当前进程退出后恢复旧版）"""
    exe = _find_helper_exe(data_dir)
    if not exe:
        logger.error("回滚助手不可用：解压缓存缺失或已清理")
        return False
    host_pid = int(os.environ.get("KAZARIPLAY_HOST_PID", "0") or 0)
    pid = host_pid or os.getpid()
    backend_pid = os.getpid() if host_pid else 0
    try:
        subprocess.Popen(
            [exe, "--apply-rollback", "--pid", str(pid),
             "--backend-pid", str(backend_pid),
             "--target", os.path.abspath(target), "--data-dir", os.path.abspath(data_dir)],
            cwd=os.path.dirname(exe),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True)
        return True
    except Exception as e:
        logger.error("拉起回滚助手失败：%s", e)
        return False


def rollback_update(pid: int, target: str, data_dir: str,
                    wait_timeout: float = 30.0, backend_pid: int = 0) -> int:
    """回滚助手主体：等待当前进程退出 → 从程序备份恢复 → 拉起旧版

    返回 0=已恢复并拉起旧版；1=恢复失败（状态与备份保留）；2=无需回滚
    """
    target = os.path.abspath(target)
    data_dir = os.path.abspath(data_dir)
    st = _read_state(data_dir)
    if not st or st.get("phase") not in (STATE_APPLYING, STATE_VERIFY):
        logger.info("回滚助手：无待回滚状态，跳过")
        return 2
    old_dir = st.get("backup_program") or ""
    old_exe = os.path.join(target, "KazariPlay.exe")
    if not (old_dir and os.path.isdir(old_dir)):
        logger.error("回滚助手：缺少程序备份，无法自动恢复")
        _write_state_best_effort(data_dir, {**st, "rollback_error": "缺少程序备份，无法自动恢复"})
        return 1
    try:
        if pid:
            wait_process_exit(pid, timeout=wait_timeout)
        if backend_pid and backend_pid != pid:
            wait_process_exit(backend_pid, timeout=wait_timeout)
        _restore(old_dir, target)
        if not os.path.isfile(old_exe):
            raise RuntimeError("恢复后未找到 KazariPlay.exe")
        msg = ("新版本启动失败，已回滚到更新前的版本"
               if st.get("phase") == STATE_VERIFY
               else "上次更新被中断，已恢复到更新前的版本")
        updated = {**st, "phase": STATE_ROLLED_BACK, "msg": msg}
        updated.pop("rollback_error", None)
        try:
            _write_state(data_dir, updated)
        except Exception as e:
            # 状态不可写：至少清除待回滚状态，避免旧版反复触发回滚
            logger.error("回滚状态写入失败，尝试清除状态：%s", e)
            _delete_state(data_dir)
            if os.path.exists(_state_path(data_dir)):
                raise
        _launch_quiet(_launch_default, old_exe)
        logger.warning("回滚助手：已恢复旧版并拉起")
        return 0
    except Exception as e:
        logger.error("回滚助手失败（状态与备份保留）：%s", e)
        _write_state_best_effort(data_dir, {**st, "rollback_error": str(e)})
        if pid == 0 or not _process_alive(pid):
            _launch_quiet(_launch_default, old_exe)
        return 1


def _parse_args(argv: List[str]) -> Tuple[int, str, str, int]:
    def _arg(name: str, default: str = "") -> str:
        try:
            return argv[argv.index(name) + 1]
        except (ValueError, IndexError):
            return default
    return (int(_arg("--pid", "0") or 0), _arg("--target", ""),
            _arg("--data-dir", ""), int(_arg("--backend-pid", "0") or 0))


def run_apply_update(argv: List[str]) -> int:
    """`--apply-update` 入口：解析参数并执行；source = 助手自身所在解压目�?"""
    pid, target, data_dir, backend_pid = _parse_args(argv)
    if not target or not data_dir:
        logger.error("更新助手参数缺失（--target/--data-dir）")
        return 2
    source = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
    lock = _acquire_install_lock(target)
    if lock is None:
        logger.error("更新助手：安装目录已有其它更新任务，放弃")
        return 2
    try:
        logger.info("更新助手启动：pid=%s backend_pid=%s target=%s",
                    pid, backend_pid, target)
        return apply_update(pid, target, source, data_dir, backend_pid=backend_pid)
    finally:
        _release_install_lock(lock)


def run_apply_rollback(argv: List[str]) -> int:
    """`--apply-rollback` 入口：由启动自愈拉起，等待当前进程退出后恢复旧版并重�?"""
    pid, target, data_dir, backend_pid = _parse_args(argv)
    if not target or not data_dir:
        logger.error("回滚助手参数缺失（--target/--data-dir）")
        return 2
    lock = _acquire_install_lock(target)
    if lock is None:
        logger.error("回滚助手：安装目录已有其它更新任务，放弃")
        return 2
    try:
        logger.info("回滚助手启动：pid=%s backend_pid=%s target=%s",
                    pid, backend_pid, target)
        return rollback_update(pid, target, data_dir, backend_pid=backend_pid)
    finally:
        _release_install_lock(lock)


# ---------- 应用侧：发起更新 ----------

def begin_apply(extract_dir: str, target: str, data_dir: str, pid: int,
                backend_pid: int = 0) -> Tuple[bool, str]:
    """应用（旧版）侧：写"更新中"标记并拉起助手进程（分离）；随后调用方自行退出"""
    exe = os.path.join(extract_dir, "KazariPlay.exe")
    if not os.path.isfile(exe):
        return False, "更新包缺少 KazariPlay.exe"
    try:
        _write_state(data_dir, {
            "phase": STATE_APPLYING, "target": os.path.abspath(target),
            "backup_program": "", "backup_data": "", "attempts": 0,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    except Exception as e:
        logger.error("更新状态写入失败，取消更新：%s", e)
        return False, f"更新状态不可写，已取消更新（{e}）"
    try:
        subprocess.Popen(
            [exe, "--apply-update", "--pid", str(int(pid)),
             "--backend-pid", str(int(backend_pid)),
             "--target", os.path.abspath(target), "--data-dir", os.path.abspath(data_dir)],
            cwd=extract_dir,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True)
    except Exception as e:
        _delete_state(data_dir)
        return False, f"拉起更新助手失败：{e}"
    return True, "正在更新…"


# ---------- 启动自愈 ----------

def cleanup_stale_new_files(target: str) -> None:
    """删除安装根目录白名单条目的 `.new` 残留（不递归、不碰用户数据区）"""
    if not target or not os.path.isdir(target):
        return
    for name in PROGRAM_WHITELIST:
        path = os.path.join(target, name + ".new")
        if os.path.isfile(path):
            try:
                os.remove(path)
                logger.info("清理更新残留：%s", path)
            except OSError as e:
                logger.warning("清理更新残留失败（忽略）：%s（%s）", path, e)


def startup_self_heal(data_dir: str,
                      spawn_helper: Optional[Callable[[str, str], bool]] = None
                      ) -> Tuple[Optional[str], bool]:
    """启动早期调用；返回（提示文案, 是否需要立即退出以让回滚助手完成恢复）

    applying / verify_pending 需要回滚时，改为拉起独立回滚助手（等待本进程退出后
    从程序备份恢复，避免覆盖运行中 EXE 的文件锁失败）；助手拉起失败时保留状态、
    备份与可诊断错误，由下次启动重试。
    """
    spawn = spawn_helper or _spawn_rollback_helper
    st = _read_state(data_dir)
    if not st:
        return None, False
    phase = st.get("phase", "")
    target = st.get("target") or ""
    old_dir = st.get("backup_program") or ""

    # 中断现场可能残留 .new 临时文件（写 .new → os.replace 之间被杀）
    cleanup_stale_new_files(target)

    if phase == STATE_APPLYING:
        # 助手中断（替换中途被杀/断电）：只有完整备份才允许回滚
        if (st.get("backup_program_complete")
                or (old_dir and os.path.isfile(_backup_complete_path(old_dir)))) \
                and old_dir and os.path.isdir(old_dir) and target:
            if spawn(target, data_dir):
                logger.warning("检测到中断的更新，已拉起回滚助手")
                return None, True
            st["rollback_error"] = "回滚助手拉起失败"
            _write_state_best_effort(data_dir, st)
            return "上次更新被中断，自动恢复未能启动；请重新启动应用重试", False
        _delete_state(data_dir)
        return "上次更新未开始（备份未完成），已取消", False

    if phase == STATE_VERIFY:
        attempts = int(st.get("attempts") or 0) + 1
        if attempts >= 2:
            # 连续两次启动都未确认成功（新版无法正常运行）：回滚并重启旧版
            if old_dir and os.path.isdir(old_dir) and target:
                if spawn(target, data_dir):
                    logger.warning("新版连续两次未确认启动，已拉起回滚助手")
                    return None, True
                st["attempts"] = attempts
                st["rollback_error"] = "回滚助手拉起失败"
                _write_state_best_effort(data_dir, st)
                return "新版本启动失败，自动恢复未能启动；请重新启动应用重试", False
            st["attempts"] = attempts
            st["rollback_error"] = "缺少可回滚的旧版本备份"
            _write_state_best_effort(data_dir, st)
            return "新版本启动失败，且缺少可回滚的旧版本备份", False
        st["attempts"] = attempts
        _write_state_best_effort(data_dir, st)
        return None, False

    if phase == STATE_ROLLED_BACK:
        msg = st.get("msg") or "更新失败，已回滚到更新前的版本"
        if target:
            shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
        _delete_state(data_dir)
        return msg, False

    _delete_state(data_dir)
    return None, False


def mark_startup_success(data_dir: str) -> Optional[str]:
    """新版前端完成首屏数据加载后调用：完成"待验证"确认并清理旧文件与下载缓存

    返回完成提示（如「已更新到 v1.0.0」）；非更新确认场景返回 None。
    """
    st = _read_state(data_dir)
    if not st or st.get("phase") != STATE_VERIFY:
        return None
    target = st.get("target") or ""
    version = _read_build_version(target) if target else ""
    _delete_state(data_dir)
    if target:
        shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
        cleanup_stale_new_files(target)
    cleanup_update_cache(data_dir, keep_ready=False)   # 先删 ready.json，再清 zip/extract
    logger.info("更新完成确认，旧版本文件已清理")
    return f"已更新到 v{version}" if version else "更新完成"


def _read_ready_marker(cache: str) -> Optional[dict]:
    try:
        with open(os.path.join(cache, READY_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def cleanup_update_cache(data_dir: str, keep_extract: bool = False,
                         keep_ready: bool = True) -> None:
    """清理下载与解压缓存

    - keep_extract=True：待回滚期间保留解压目录（回滚助手运行来源）
    - keep_ready=True：保留被 `ready.json` 引用的完整 zip（就绪缓存）；zip 缺失则丢弃记录
    - keep_ready=False：确认成功后先删 `ready.json`，再全清
    """
    cache = os.path.join(data_dir, "update_cache")
    if not os.path.isdir(cache):
        return
    keep_zip = ""
    if keep_ready:
        ready = _read_ready_marker(cache)
        keep_zip = os.path.basename(str((ready or {}).get("zip") or ""))
        if keep_zip and not os.path.isfile(os.path.join(cache, keep_zip)):
            keep_zip = ""
            try:
                os.remove(os.path.join(cache, READY_FILE))
            except OSError:
                pass
    else:
        try:
            os.remove(os.path.join(cache, READY_FILE))
        except OSError:
            pass
    try:
        os.remove(os.path.join(cache, READY_FILE + ".tmp"))
    except OSError:
        pass
    if not keep_extract:
        shutil.rmtree(os.path.join(cache, "extract"), ignore_errors=True)
    try:
        for name in os.listdir(cache):
            if name.endswith(".zip") or name.endswith(".part"):
                if keep_zip and name == keep_zip:
                    continue
                try:
                    os.remove(os.path.join(cache, name))
                except OSError:
                    pass
    except OSError:
        pass


# ---------- WebView2 依赖检测 ----------

_WEBVIEW2_MSG = (
    "KazariPlay 需要 Microsoft Edge WebView2 Runtime，当前系统未检测到。\n\n"
    "安装方法（任选其一）：\n"
    "1. 命令行执行：winget install --id Microsoft.EdgeWebView2Runtime -e\n"
    "2. 打开 https://go.microsoft.com/fwlink/p/?LinkId=2124703 下载安装\n\n"
    "安装完成后重新启动 KazariPlay。"
)


def ensure_webview2() -> bool:
    """检测 WebView2 Runtime；缺失时弹系统提示并返回 False（不让 pywebview 抛原始报错）"""
    if os.name != "nt":
        return True
    try:
        import winreg
        client_id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        candidates = (
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client_id}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_id}"),
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_id}"),
        )
        for hive, path in candidates:
            try:
                with winreg.OpenKey(hive, path) as key:
                    pv, _ = winreg.QueryValueEx(key, "pv")
                    if pv and str(pv) != "0.0.0.0":
                        return True
            except OSError:
                continue
    except Exception:
        return True   # 检测本身失败不阻断启动（交给 pywebview）
    logger.warning("未检测到 WebView2 Runtime")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, _WEBVIEW2_MSG, "KazariPlay — 缺少 WebView2 Runtime", 0x30)
    except Exception:
        pass
    return False
