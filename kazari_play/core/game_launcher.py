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
_NON_GAME_EXES = frozenset((
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
    PROCESSENTRY32_SIZE = 568  # 32 位系统上不同，这里按 64 位；用 ctypes 动态算

    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_ulonglong),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
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


class GameLauncher:
    """游戏启动器 - 管理进程启动"""

    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.current_game_id: Optional[str] = None
        # 真正游戏的进程 PID：当前进程可能是启动器（SmartSteamEmu 等），
        # 真游戏是它的子进程。追踪线程会找到它并填入此字段；
        # 截图 / Hook / 存活检测都应基于此 pid 而非 current_process.pid。
        self.current_game_pid: Optional[int] = None
        self._start_time: Optional[float] = None
        self._trace_stop = threading.Event()
        self._trace_thread: Optional[threading.Thread] = None
        self.subtitle_coordinator = None   # Hook 实时翻译协调器（懒加载）
        from utils.config import Config
        self._cfg = Config()

    def _start_trace(self):
        """启动子进程追踪线程：找到真游戏 pid 填入 current_game_pid。

        适用于启动器拉起真游戏的场景（SmartSteamEmu / 安装器退出后游戏仍在）。
        追踪到真进程后线程退出（该 pid 由 monitor 生命周期管理）。
        """
        self._trace_stop.clear()
        self._trace_thread = threading.Thread(
            target=self._trace_loop, name="GameTrace", daemon=True)
        self._trace_thread.start()

    def _trace_loop(self):
        """轮询追踪 current_process 的后代进程，找到真正的游戏进程

        优先选「有可见顶层窗口」的后代（排除 conhost/cmd 等控制台进程）；
        启动器已退出时仍能通过整棵后代树找到真游戏。
        """
        import ctypes
        from ctypes import wintypes

        root_pid = self.current_process.pid if self.current_process else None
        if not root_pid:
            return
        deadline = time.time() + _GAME_SPAWN_TIMEOUT
        while not self._trace_stop.is_set() and time.time() < deadline:
            descendants = _collect_descendants(root_pid)
            # 第一遍：找「有可见窗口 且 非控制台/系统进程」的后代（真游戏）
            for cpid, cexe in descendants:
                exe_lower = (cexe or "").lower()
                if (exe_lower in _NON_GAME_EXES or not exe_lower.endswith(".exe")):
                    continue
                if _is_process_alive(cpid) and _has_visible_window(cpid):
                    self.current_game_pid = cpid
                    logger.info(
                        "追踪到游戏进程: pid=%s exe=%s (启动器 pid=%s)",
                        cpid, cexe, root_pid)
                    return
            # 第二遍：回退到任意存活非控制台后代（无窗口游戏/后台进程）
            for cpid, cexe in descendants:
                exe_lower = (cexe or "").lower()
                if exe_lower in _NON_GAME_EXES:
                    continue
                if _is_process_alive(cpid):
                    self.current_game_pid = cpid
                    logger.info(
                        "追踪到游戏进程(无窗口回退): pid=%s exe=%s (启动器 pid=%s)",
                        cpid, cexe, root_pid)
                    return
            # 还没有后代，等下一次轮询
            self._trace_stop.wait(_GAME_TRACE_INTERVAL)

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
            self.close()

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
            self.current_game_id = game.id
            self._start_time = time.time()

            # 追踪子进程树（若 exe 是启动器，找到真游戏 pid）
            self._start_trace()

            # 若该游戏启用实时翻译，启动 Hook 会话（失败不影响游戏本身）
            if getattr(game, "translate_enabled", False):
                self._start_translation(game)

            return True

        except Exception as e:
            logger.error("启动游戏失败: %s", e)
            return False
    
    def close(self):
        """关闭当前游戏进程"""
        self.stop_translation()
        self._trace_stop.set()
        if self.current_process:
            try:
                self.current_process.terminate()
                # 等待进程结束（最多5秒）
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            except Exception:
                pass
            finally:
                self.current_process = None
                self.current_game_id = None
                self.current_game_pid = None
                self._start_time = None
    
    def is_running(self) -> bool:
        """检查游戏是否正在运行（优先用追踪到的真游戏 pid）"""
        pid = self.get_game_pid()
        if not pid:
            return False
        return _is_process_alive(pid)

    def get_game_pid(self) -> Optional[int]:
        """返回真正的游戏进程 PID（优先追踪结果，回退 current_process）"""
        if self.current_game_pid:
            return self.current_game_pid
        if self.current_process and self.current_process.poll() is None:
            return self.current_process.pid
        return None
    
    def get_runtime(self) -> int:
        """获取当前游戏已运行时长（分钟）"""
        if not self._start_time or not self.is_running():
            return 0
        return int((time.time() - self._start_time) / 60)

    # ---------- Hook 实时翻译（C++ 接管版，见计划书 5.1） ----------

    def _start_translation(self, game: Game):
        """启动 Hook 翻译：通知 C++ overlay 注入并开始 Hook 会话（AI 配置一并传入）"""
        try:
            from core.subtitle_coordinator import SubtitleCoordinator

            logger.info("翻译启动: game_id=%s te=%s engine=%s hook=%s",
                        game.id, game.translate_enabled, game.engine,
                        "空(候选)" if not game.hook_code else "有")
            self.subtitle_coordinator = SubtitleCoordinator()
            is_x64 = self._is_process_x64(self.current_process.pid)
            codepage = self._cfg.get("textractor.codepage", 0) or 0
            ai_config = {
                "base_url": self._cfg.get("translate.ai.base_url", "") or "",
                "api_key": self._cfg.get("translate.ai.api_key", "") or "",
                "model": self._cfg.get("translate.ai.model", "") or "",
                "source_lang": self._cfg.get("translate.source_lang", "ja") or "ja",
                "target_lang": self._cfg.get("translate.target_lang", "zh") or "zh",
            }

            # 只传 pid + engine + hook_code，Hook 注入 + AI 翻译由 C++ 完成
            ai_clean_mode = 0
            if self._cfg.get("clean.ai_assist_enabled", False):
                th = self._cfg.get("clean.ai_assist_threshold", "dirty")
                ai_clean_mode = 2 if th == "always" else (1 if th == "dirty" else 0)
            ok = self.subtitle_coordinator.start_hook_session(
                pid=self.current_process.pid,
                is_x64=is_x64,
                hook_code=game.hook_code,     # 空表示首次需选择
                engine=game.engine,           # 驱动 C++ TextStabilizer 策略
                codepage=codepage,            # 文本编码（乱码时切 936/932）
                ai_config=ai_config,          # AI 翻译配置（C++ 内部翻译用）
                filter_override=getattr(game, "clean_filter_override", "") or "",
                ai_clean_mode=ai_clean_mode,
            )
            if not ok:
                logger.warning("翻译会话启动失败（overlay 不可用？），静默降级")
                self.subtitle_coordinator = None
        except Exception as e:
            logger.error("翻译启动失败: %s", e)
            self.subtitle_coordinator = None

    def stop_translation(self):
        """停止 Hook 翻译会话（游戏退出/切换时调用）"""
        if self.subtitle_coordinator:
            try:
                self.subtitle_coordinator.stop()
            except Exception as e:
                logger.error("停止翻译失败: %s", e)
            self.subtitle_coordinator = None

    def _is_process_x64(self, pid: int) -> bool:
        """判断进程是否 64 位（决定注入 texthook64/texthook32）

        IsWow64Process 返回 True 表示"32 位进程跑在 64 位系统"，
        即非 WOW64 = 原生 64 位。
        """
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        # 32 位系统上不存在 64 位进程，直接返回 False。
        # 注意 GetCurrentProcess 需设 restype=HANDLE，否则 64 位伪句柄
        # 被截断为 32 位导致 IsWow64Process 误判系统为 32 位。
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        try:
            sys_wow64 = wintypes.BOOL(False)
            if not kernel32.IsWow64Process(kernel32.GetCurrentProcess(),
                                           ctypes.byref(sys_wow64)) \
                    and not sys_wow64.value:
                return False
        except Exception:
            pass
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return True   # 打开失败按 64 位兜底（多数现代游戏为 64 位）
        try:
            is_wow64 = wintypes.BOOL(False)
            kernel32.IsWow64Process(h, ctypes.byref(is_wow64))
            return not bool(is_wow64.value)   # 非 WOW64 → 原生 64 位
        finally:
            kernel32.CloseHandle(h)