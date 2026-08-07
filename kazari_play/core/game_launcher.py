import subprocess
import os
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

            return True

        except Exception as e:
            logger.error("启动游戏失败: %s", e)
            return False
    
    def close(self):
        """关闭当前游戏进程"""
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