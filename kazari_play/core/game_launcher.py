import subprocess
import os
import threading
import time
from typing import Optional
from core.game_model import Game
from utils.logger import get_logger

logger = get_logger()

# 子进程树追踪：等待真游戏进程出现的超时（秒）。
# 部分游戏经启动器（如 SmartSteamEmu / 安装器）拉真 exe，启动器随后退出，
# current_process 会指向已退出的启动器 → 需追踪其子进程找到真正的游戏进程。
_GAME_SPAWN_TIMEOUT = 10.0
# 子进程树追踪轮询间隔（秒）
_GAME_TRACE_INTERVAL = 0.3
# 排除的控制台/系统进程名（不可能是游戏主进程）
_NON_GAME_EXES = frozenset(name.lower() for name in (
    "conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "explorer.exe",
    "svchost.exe", "dllhost.exe", "rundll32.exe", "sihost.exe", "taskhostw.exe",
    "ctfmon.exe", "SearchHost.exe", "RuntimeBroker.exe", "backgroundTaskHost.exe",
    "WmiPrvSE.exe", "conhost", "cmd", "powershell",
))


def _process_children(pid: int) -> list:
    """枚举指定进程的直接子进程 PID（用 Toolhelp32 快照）。

    只返回直接子进程；若要整棵进程树，调用方需递归。
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x2
    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []

    children = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.th32ParentProcessID == pid:
                    children.append((entry.th32ProcessID, entry.szExeFile))
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return children


def _collect_descendants(root_pid: int) -> list:
    """收集 root_pid 的整棵后代进程树（BFS），返回 [(pid, exe), ...]"""
    result = []
    seen = {root_pid}
    queue = [root_pid]
    while queue:
        cur = queue.pop(0)
        for cpid, cexe in _process_children(cur):
            if cpid in seen:
                continue
            seen.add(cpid)
            result.append((cpid, cexe))
            queue.append(cpid)
    return result


def _is_process_alive(pid: int) -> bool:
    """进程是否存活（OpenProcess + GetExitCodeProcess 判定）"""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259   # STILL_ACTIVE
    except Exception:
        return False
    finally:
        kernel32.CloseHandle(h)


def _has_visible_window(pid: int) -> bool:
    """进程是否有可见顶层窗口（用于区分真游戏与 conhost 等控制台进程）"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    found = [False]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        wp = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if wp.value == pid and user32.IsWindowVisible(hwnd):
            found[0] = True
            return False
        return True

    user32.EnumWindows(_cb, 0)
    return found[0]


def _creation_time(handle) -> Optional[int]:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def _process_creation_time(pid: int) -> Optional[int]:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        return _creation_time(handle)
    finally:
        kernel32.CloseHandle(handle)


def _terminate_pid(pid: Optional[int], creation_time: Optional[int], timeout_ms: int = 5000) -> bool:
    """终止由本次启动链确认的单个进程。失败返回 False，不按进程名匹配。"""
    if not pid or creation_time is None or os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    PROCESS_TERMINATE = 0x0001
    SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE | 0x1000, False, pid)
    if not handle:
        return False
    try:
        if _creation_time(handle) != creation_time:
            return False
        if not kernel32.TerminateProcess(handle, 1):
            return False
        return kernel32.WaitForSingleObject(handle, timeout_ms) == 0
    finally:
        kernel32.CloseHandle(handle)


class GameLauncher:
    """游戏启动器 - 管理进程启动"""

    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.current_game_id: Optional[str] = None
        # 真正游戏的进程 PID：当前进程可能是启动器（SmartSteamEmu 等），
        # 真游戏是它的子进程。追踪线程会找到它并填入此字段；
        # 截图 / 存活检测都应基于此 pid 而非 current_process.pid。
        self.current_game_pid: Optional[int] = None
        self._start_time: Optional[float] = None
        self._trace_stop = threading.Event()
        self._trace_thread: Optional[threading.Thread] = None
        self._trace_done = threading.Event()
        self._trace_done.set()
        self._game_creation_time: Optional[int] = None
        self._tracked_processes = {}
        self._target_ready = False

    def _start_trace(self):
        """启动子进程追踪线程：找到真游戏 pid 填入 current_game_pid。

        适用于启动器拉起真游戏的场景（SmartSteamEmu / 安装器退出后游戏仍在）。
        追踪到真进程后线程退出（该 pid 由 monitor 生命周期管理）。
        """
        self._trace_stop = threading.Event()
        self._trace_done = threading.Event()
        self._tracked_processes = {}
        self._target_ready = False
        self._trace_thread = threading.Thread(
            target=self._trace_loop,
            args=(self.current_process, self._trace_stop, self._trace_done),
            name="GameTrace", daemon=True)
        self._trace_thread.start()

    def _trace_loop(self, process, stop_event, done_event):
        """轮询追踪 current_process 的后代进程，找到真正的游戏进程

        优先选「有可见顶层窗口」的后代（排除 conhost/cmd 等控制台进程）；
        启动器已退出时仍能通过整棵后代树找到真游戏。
        """
        root_pid = process.pid
        deadline = time.monotonic() + _GAME_SPAWN_TIMEOUT
        known = {root_pid: ("", self._game_creation_time)}
        fallback = root_pid

        def select(pid, created):
            if not stop_event.is_set() and self.current_process is process:
                self.current_game_pid = pid
                self._game_creation_time = created
                self._target_ready = True
                logger.info("游戏目标已就绪: pid=%s (启动 PID=%s)", pid, root_pid)

        try:
            while not stop_event.is_set():
                # 保留已观察到的中间启动器，父进程退出后仍可找到它的后代。
                for parent, (_, created) in list(known.items()):
                    now_created = _process_creation_time(parent)
                    if now_created is not None and created is not None and now_created != created:
                        continue
                    for pid, name in _collect_descendants(parent):
                        if pid not in known:
                            child_created = _process_creation_time(pid)
                            if child_created is not None and (created is None or child_created >= created):
                                known[pid] = (name, child_created)
                                if not stop_event.is_set() and (name or "").lower() not in _NON_GAME_EXES:
                                    self._tracked_processes[pid] = child_created
                candidates = []
                for pid, (name, created) in reversed(list(known.items())):
                    if pid == root_pid or (name or "").lower() in _NON_GAME_EXES:
                        continue
                    if _process_creation_time(pid) == created and _is_process_alive(pid):
                        candidates.append((pid, created))
                        if _has_visible_window(pid):
                            select(pid, created)
                            return
                if candidates:
                    fallback = candidates[0][0]
                if time.monotonic() >= deadline:
                    if _is_process_alive(fallback):
                        select(fallback, known[fallback][1])
                    return
                stop_event.wait(_GAME_TRACE_INTERVAL)
        finally:
            done_event.set()

    def launch(self, game: Game, extra_args: list = None) -> bool:
        """
        启动游戏

        优先使用 launch_exe_path（自定义启动路径），为空则回退到 exe_path。
        不再使用 CREATE_NEW_CONSOLE，直接启动 exe。

        Args:
            game: 游戏对象
            extra_args: 额外命令行参数

        Returns:
            是否启动成功
        """
        # 优先用自定义启动路径，为空则回退到扫描时的 exe_path
        exe = game.launch_exe_path.strip() if game.launch_exe_path else ""
        if not exe:
            exe = game.exe_path
        if not os.path.exists(exe):
            logger.error("启动 exe 不存在: %s", exe)
            return False

        try:
            # 如果已有游戏在运行，先关闭
            if not self.close():
                return False

            # 构建命令
            args = [exe]
            if extra_args:
                args.extend(extra_args)

            # 启动进程
            # CREATE_NEW_CONSOLE 是 krkr/Ren'Py 等引擎的必要条件：
            # 它让子进程拥有独立的工作目录环境，避免相对路径解析错误
            # （krkr 引擎用 GetCurrentDirectory() 定位 savedata，无此标志会路径错乱）
            self.current_process = subprocess.Popen(
                args,
                cwd=game.folder,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            self.current_game_pid = self.current_process.pid   # 默认即真游戏
            self._game_creation_time = _process_creation_time(self.current_process.pid)
            self.current_game_id = game.id
            self._start_time = time.time()

            # 追踪子进程树（若 exe 是启动器，找到真游戏 pid）
            self._start_trace()

            return True

        except Exception as e:
            logger.error("启动游戏失败: %s", e)
            return False
    
    def close(self):
        """关闭当前游戏进程"""
        self._trace_stop.set()
        if self._trace_thread and self._trace_thread.is_alive():
            self._trace_thread.join()
        root_pid = self.current_process.pid if self.current_process else None
        game_pid = self.current_game_pid
        targets = dict(self._tracked_processes)
        if self.current_process and self.current_process.poll() is None:
            for pid, name in _collect_descendants(root_pid):
                if pid not in targets and (name or "").lower() not in _NON_GAME_EXES:
                    targets[pid] = _process_creation_time(pid)
        if game_pid and game_pid != root_pid:
            targets[game_pid] = self._game_creation_time
        for pid, created in reversed(list(targets.items())):
            if not _is_process_alive(pid):
                continue
            current_created = _process_creation_time(pid)
            if created is None or current_created is None:
                logger.error("无法确认游戏子进程身份，保留运行状态: pid=%s", pid)
                return False
            if current_created != created:
                continue
            if not _terminate_pid(pid, created) and _is_process_alive(pid):
                logger.error("游戏子进程关闭失败，保留运行状态: pid=%s", pid)
                return False
        if self.current_process:
            try:
                if self.current_process.poll() is None:
                    self.current_process.terminate()
                try:
                    self.current_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.current_process.kill()
                    self.current_process.wait(timeout=5)
            except Exception as e:
                logger.error("启动进程关闭失败: %s", e)
                return False
        self.current_process = None
        self.current_game_id = None
        self.current_game_pid = None
        self._game_creation_time = None
        self._start_time = None
        self._trace_thread = None
        self._tracked_processes = {}
        self._target_ready = False
        return True
    
    def is_running(self) -> bool:
        """检查游戏是否正在运行（优先用追踪到的真游戏 pid）"""
        if not self._trace_stop.is_set() and not self._trace_done.is_set():
            return True
        pid = self.get_game_pid()
        if not pid:
            return False
        if self._game_creation_time is not None and _process_creation_time(pid) != self._game_creation_time:
            return False
        return _is_process_alive(pid)

    def get_game_pid(self) -> Optional[int]:
        """返回真正的游戏进程 PID（优先追踪结果，回退 current_process）"""
        if self.current_game_pid:
            return self.current_game_pid
        if self.current_process and self.current_process.poll() is None:
            return self.current_process.pid
        return None

    def wait_for_game_pid(self) -> Optional[int]:
        """等待本轮启动目标就绪；关闭或切换后不能返回旧目标。"""
        process = self.current_process
        stop_event = self._trace_stop
        if not self._trace_done.wait(_GAME_SPAWN_TIMEOUT + 1):
            return None
        if stop_event.is_set() or self.current_process is not process or not self._target_ready:
            return None
        pid = self.get_game_pid()
        if pid and _is_process_alive(pid) and _process_creation_time(pid) == self._game_creation_time:
            return pid
        return None
    
    def get_runtime(self) -> int:
        """获取当前游戏已运行时长（分钟）"""
        if not self._start_time or not self.is_running():
            return 0
        return int((time.time() - self._start_time) / 60)
