"""应用内更新的替换助手与启动自愈（见 docs/dev/AUTO_UPDATE_DESIGN.md §2/§6）

- **助手模式**：`KazariPlay.exe --apply-update --pid <旧PID> --target <安装目录> --data-dir <数据目录>`
  等待旧进程退出（超时强杀进程树）→ 备份用户数据（滚动 3 份）→ 备份程序文件 →
  白名单替换（代码级路径断言）→ 失败回滚并拉起旧版 / 成功写入"待验证"并拉起新版。
- **启动自愈**：应用启动早期调用 `startup_self_heal()`：
  - `applying`（助手中断）→ 从程序备份回滚；
  - `verify_pending`（新版未确认首启成功）→ 第二次启动仍未确认则回滚；
  - `rolled_back` → 消费提示并清理。
  新版窗口加载成功后调用 `mark_startup_success()` 完成两段确认并清理旧文件。
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

from utils.logger import get_logger

logger = get_logger()

STATE_FILE = "update_state.json"
STATE_APPLYING = "applying"
STATE_VERIFY = "verify_pending"
STATE_ROLLED_BACK = "rolled_back"

# 程序文件白名单（替换集 = 这些条目；助手由"新版本"的代码执行，清单随新版本走）
PROGRAM_WHITELIST = {
    "KazariPlay.exe", "_internal",
    "LICENSE", "THIRD_PARTY.md", "RELEASE_NOTES.md", "TRIAL_README.txt",
    "BUILD_INFO.json", "run_develop.cmd",
}
# 禁用区（用户数据）；任何目标路径命中即中止
FORBIDDEN_PARTS = {"data", "screenshots", "logs"}
BACKUP_KEEP = 3


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
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(_state_path(data_dir), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("更新状态写入失败：%s", e)


def _delete_state(data_dir: str) -> None:
    try:
        os.remove(_state_path(data_dir))
    except OSError:
        pass


# ---------- 路径与断言 ----------

def current_install_dir() -> str:
    """当前运行的安装目录（仅冻结形态；源码运行返回空 = 不支持自动替换）"""
    if not getattr(sys, "frozen", False):
        return ""
    return os.path.dirname(os.path.abspath(sys.executable))


def _relative_forbidden(target: str, path: str) -> bool:
    """path 相对 target 是否命中用户数据区（或越出 target）"""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(target))
    except ValueError:
        return True
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return True
    parts = [p.lower() for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    return any(p in FORBIDDEN_PARTS for p in parts)


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


# ---------- 备份 ----------

def backup_user_data(data_dir: str, stamp: Optional[str] = None) -> Optional[str]:
    """只读备份 games.db + config.json 到 data/backup/<时间戳>/；滚动保留最近 BACKUP_KEEP 份"""
    names = [n for n in ("games.db", "config.json") if os.path.isfile(os.path.join(data_dir, n))]
    if not names:
        return None
    name = stamp or time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(data_dir, "backup", name)
    try:
        os.makedirs(dest, exist_ok=True)
        for n in names:
            shutil.copy2(os.path.join(data_dir, n), os.path.join(dest, n))
    except Exception as e:
        logger.warning("用户数据备份失败：%s", e)
        return None
    prune_backups(data_dir)
    return dest


def prune_backups(data_dir: str, keep: int = BACKUP_KEEP) -> None:
    root = os.path.join(data_dir, "backup")
    if not os.path.isdir(root):
        return
    dirs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for d in dirs[:-keep] if keep > 0 else dirs:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _backup_program(target: str, backup_root: str) -> None:
    """把 target 中现有的白名单程序条目复制到 backup_root（回滚用；只读复制）"""
    os.makedirs(backup_root, exist_ok=True)
    for name in PROGRAM_WHITELIST:
        src = os.path.join(target, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup_root, name))
        elif os.path.isdir(src):
            shutil.copytree(src, os.path.join(backup_root, name))


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
    """从程序备份整目录恢复（镜像）：目录整体替换，文件复制覆盖"""
    for name in os.listdir(backup_root):
        src = os.path.join(backup_root, name)
        dst = os.path.join(target, name)
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


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
    """等待进程退出；超时后 taskkill /T /F 结束进程树（含 WebView2 子进程）"""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return
        time.sleep(0.2)
    if _process_alive(pid):
        logger.info("等待进程 %s 超时，强杀进程树", pid)
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           capture_output=True)
        except Exception as e:
            logger.warning("taskkill 失败：%s", e)
        time.sleep(1.0)


# ---------- 启动 / 拉起 ----------

def _launch_default(exe: str) -> None:
    subprocess.Popen([exe], cwd=os.path.dirname(exe),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def relaunch_and_exit(exe: str) -> None:
    """回滚场景：以旧版重启并让当前进程立刻退出（不执行 Python 清理）"""
    try:
        _launch_default(exe)
    except Exception as e:
        logger.error("回滚后重启失败：%s", e)
    os._exit(0)


def _read_build_version(root: str) -> str:
    try:
        with open(os.path.join(root, "BUILD_INFO.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "")
    except Exception:
        return ""


# ---------- 助手主流程 ----------

def apply_update(pid: int, target: str, source: str, data_dir: str,
                 launch: Optional[Callable[[str], None]] = None,
                 wait_timeout: float = 30.0) -> int:
    """执行替换；返回 0=成功（已拉起新版）、1=失败（已回滚/未开始，已尝试拉起旧版）"""
    launch = launch or _launch_default
    target = os.path.abspath(target)
    source = os.path.abspath(source)
    data_dir = os.path.abspath(data_dir)
    old_exe = os.path.join(target, "KazariPlay.exe")

    try:
        if pid:
            wait_process_exit(pid, timeout=wait_timeout)

        plan = build_replace_plan(target, source)          # 先校验，后任何改动
        data_backup = backup_user_data(data_dir) or ""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        old_dir = os.path.join(target, "_old", stamp)
        _backup_program(target, old_dir)

        marker = {
            "phase": STATE_APPLYING, "target": target,
            "new_version": _read_build_version(source), "old_version": _read_build_version(target),
            "backup_program": old_dir, "backup_data": data_backup,
            "attempts": 0, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write_state(data_dir, marker)

        try:
            _copy_new_files(plan)
            _remove_stale(target, plan)
        except Exception as e:
            logger.warning("替换失败，回滚：%s", e)
            _restore(old_dir, target)
            marker.update({"phase": STATE_ROLLED_BACK, "msg": f"更新失败，已回滚：{e}"})
            _write_state(data_dir, marker)
            try:
                launch(old_exe)
            except Exception as le:
                logger.error("回滚后拉起旧版失败：%s", le)
            return 1

        marker.update({"phase": STATE_VERIFY, "attempts": 0})
        _write_state(data_dir, marker)
        try:
            launch(os.path.join(target, "KazariPlay.exe"))
        except Exception as le:
            logger.error("更新完成但拉起新版失败：%s", le)
        return 0
    except Exception as e:
        logger.error("更新助手失败：%s", e)
        try:
            launch(old_exe)
        except Exception:
            pass
        return 1


def run_apply_update(argv: List[str]) -> int:
    """`--apply-update` 入口：解析参数并执行；source = 助手自身所在解压目录"""
    def _arg(name: str, default: str = "") -> str:
        try:
            return argv[argv.index(name) + 1]
        except (ValueError, IndexError):
            return default
    pid = int(_arg("--pid", "0") or 0)
    target = _arg("--target", "")
    data_dir = _arg("--data-dir", "")
    if not target or not data_dir:
        logger.error("更新助手参数缺失（--target/--data-dir）")
        return 2
    source = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
    logger.info("更新助手启动：pid=%s target=%s", pid, target)
    return apply_update(pid, target, source, data_dir)


# ---------- 应用侧：发起更新 ----------

def begin_apply(extract_dir: str, target: str, data_dir: str, pid: int) -> Tuple[bool, str]:
    """应用（旧版）侧：写"更新中"标记并拉起助手进程（分离）；随后调用方自行退出"""
    exe = os.path.join(extract_dir, "KazariPlay.exe")
    if not os.path.isfile(exe):
        return False, "更新包缺少 KazariPlay.exe"
    _write_state(data_dir, {
        "phase": STATE_APPLYING, "target": os.path.abspath(target),
        "backup_program": "", "backup_data": "", "attempts": 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    try:
        subprocess.Popen(
            [exe, "--apply-update", "--pid", str(int(pid)),
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

def startup_self_heal(data_dir: str) -> Tuple[Optional[str], str]:
    """启动早期调用；返回（提示文案, 需要重启的 exe 路径）；无残留时返回 (None, "")"""
    st = _read_state(data_dir)
    if not st:
        return None, ""
    phase = st.get("phase", "")
    target = st.get("target") or ""
    old_dir = st.get("backup_program") or ""
    exe = os.path.join(target, "KazariPlay.exe") if target else ""

    if phase == STATE_APPLYING:
        # 助手中断（替换中途被杀/断电）：从程序备份回滚
        if old_dir and os.path.isdir(old_dir) and target:
            try:
                _restore(old_dir, target)
                shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
                _delete_state(data_dir)
                logger.warning("检测到中断的更新，已回滚程序文件")
                return "上次更新被中断，已恢复到更新前的版本", ""
            except Exception as e:
                logger.error("中断更新回滚失败：%s", e)
                return "上次更新被中断且自动恢复失败，请重新下载安装", ""
        _delete_state(data_dir)
        return "上次更新未开始，已取消", ""

    if phase == STATE_VERIFY:
        attempts = int(st.get("attempts") or 0) + 1
        if attempts >= 2:
            # 连续两次启动都未确认成功（新版无法正常运行）：回滚并重启旧版
            if old_dir and os.path.isdir(old_dir) and target:
                try:
                    _restore(old_dir, target)
                    shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
                except Exception as e:
                    logger.error("新版启动失败回滚出错：%s", e)
            _delete_state(data_dir)
            logger.warning("新版本连续两次未确认启动，已回滚")
            return "新版本启动失败，已回滚到更新前的版本", exe
        st["attempts"] = attempts
        _write_state(data_dir, st)
        return None, ""

    if phase == STATE_ROLLED_BACK:
        msg = st.get("msg") or "更新失败，已回滚到更新前的版本"
        if target:
            shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
        _delete_state(data_dir)
        return msg, ""

    _delete_state(data_dir)
    return None, ""


def mark_startup_success(data_dir: str) -> None:
    """新版窗口加载成功后调用：完成"待验证"确认并清理旧文件与下载缓存"""
    st = _read_state(data_dir)
    if not st or st.get("phase") != STATE_VERIFY:
        return
    _delete_state(data_dir)
    target = st.get("target") or ""
    if target:
        shutil.rmtree(os.path.join(target, "_old"), ignore_errors=True)
    cleanup_update_cache(data_dir)
    logger.info("更新完成确认，旧版本文件已清理")


def cleanup_update_cache(data_dir: str) -> None:
    """清理下载与解压缓存（启动时与确认成功后调用）"""
    cache = os.path.join(data_dir, "update_cache")
    if not os.path.isdir(cache):
        return
    shutil.rmtree(os.path.join(cache, "extract"), ignore_errors=True)
    try:
        for name in os.listdir(cache):
            if name.endswith(".zip") or name.endswith(".part"):
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
