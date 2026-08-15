import subprocess
import os
import threading
import time
from typing import Optional
from core.game_model import Game
from utils.logger import get_logger

logger = get_logger()


class GameLauncher:
    """游戏启动器 - 管理进程启动"""

    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.current_game_id: Optional[str] = None
        self._start_time: Optional[float] = None
        self.subtitle_coordinator = None   # Hook 实时翻译协调器（懒加载）
        from utils.config import Config
        self._cfg = Config()
    
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

            self.current_game_id = game.id
            self._start_time = time.time()

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
                self._start_time = None
    
    def is_running(self) -> bool:
        """检查游戏是否正在运行"""
        if not self.current_process:
            return False
        return self.current_process.poll() is None
    
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