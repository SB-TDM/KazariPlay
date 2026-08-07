"""游戏监控器 - 后台线程监控进程状态并统计运行时长"""
import threading
import time
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, List

logger = logging.getLogger(__name__)


class GameMonitor:
    """游戏进程监控器

    职责：
      1. 后台线程定期检测游戏进程是否存活
      2. 进程结束时触发 on_exit 回调，并把累计运行时长写入数据库
      3. 周期性触发 on_tick 回调，并增量记录运行时长（分钟级）
    """

    # 支持的事件
    EVENTS = ("on_start", "on_tick", "on_exit")

    def __init__(self, repository, launcher, tick_interval: int = 2):
        """
        Args:
            repository: GameRepository 实例，用于持久化运行时长
            launcher:   GameLauncher 实例，用于读取进程状态
            tick_interval: 进程存活检测周期（秒），默认 2 秒
                           运行时长按实际秒数累积，每满 60 秒写一次数据库
        """
        self.repository = repository
        self.launcher = launcher
        self.tick_interval = tick_interval

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_game_id: Optional[str] = None
        self._start_time: Optional[float] = None

        # 事件回调注册表
        self._callbacks: Dict[str, List[Callable]] = {e: [] for e in self.EVENTS}

    # ---------- 对外接口 ----------

    def register_callback(self, event: str, callback: Callable) -> None:
        """注册事件回调。event 取值：on_start / on_tick / on_exit"""
        if event not in self.EVENTS:
            raise ValueError(f"不支持的事件: {event}，可选: {self.EVENTS}")
        self._callbacks[event].append(callback)

    def start(self, game_id: str) -> bool:
        """开始监控指定游戏（前提：launcher 已启动该游戏进程）"""
        if not self.launcher.is_running():
            logger.warning("监控启动失败：launcher 中没有运行中的进程")
            return False

        # 若已在监控，先停止
        self.stop()

        self._current_game_id = game_id
        self._start_time = time.time()
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"GameMonitor-{game_id}",
            daemon=True,
        )
        self._thread.start()
        self._fire("on_start", game_id)
        logger.info(f"开始监控游戏: {game_id}")
        return True

    def stop(self) -> None:
        """停止监控（不主动结束游戏进程，仅结束监控线程）"""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=self.tick_interval + 1)
        self._thread = None
        self._current_game_id = None
        self._start_time = None

    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._thread is not None and self._thread.is_alive()

    def get_runtime_seconds(self) -> int:
        """当前游戏已运行秒数"""
        if not self._start_time or not self.is_monitoring():
            return 0
        return int(time.time() - self._start_time)

    # ---------- 内部实现 ----------

    def _monitor_loop(self) -> None:
        """监控循环：周期性检测存活 + 按实际秒数累积运行时长

        每 tick_interval 秒检测一次进程是否存活（默认 2 秒），
        关闭游戏后最多 2 秒内触发 on_exit 回调，UI 能快速恢复"启动"按钮。
        运行时长按实际秒数累积，每满 60 秒写一次数据库（避免短时游玩漏记）。
        """
        accumulated_seconds = 0  # 累积运行秒数（用于判断是否满 1 分钟）
        accumulated_minutes = 0  # 累积已记录的分钟数（用于 on_tick 回调）

        while not self._stop_event.is_set():
            # 检查进程是否还活着
            if not self.launcher.is_running():
                logger.info(f"游戏进程已结束: {self._current_game_id}")
                # 退出前补记剩余秒数（满 1 分钟的部分丢弃，避免高估）
                self._fire("on_exit", self._current_game_id, self.get_runtime_seconds())
                self._current_game_id = None
                self._start_time = None
                return

            # 等待一个 tick（可被 stop 提前唤醒）
            if self._stop_event.wait(self.tick_interval):
                # 被显式 stop 唤醒
                return

            # 仍在运行，累积秒数
            if self._current_game_id and self.repository:
                accumulated_seconds += self.tick_interval
                # 每满 60 秒写一次数据库（按实际秒数，避免短 tick 高估）
                if accumulated_seconds >= 60:
                    minutes = accumulated_seconds // 60
                    try:
                        self.repository.increment_play_time(
                            self._current_game_id, minutes
                        )
                        accumulated_seconds -= minutes * 60
                        accumulated_minutes += minutes
                        self._fire("on_tick", self._current_game_id, accumulated_minutes)
                    except Exception as e:
                        logger.error(f"记录运行时长失败: {e}")

    def _fire(self, event: str, *args, **kwargs) -> None:
        """触发事件回调，吞掉异常避免影响主循环"""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error(f"回调 {event} 执行失败: {e}")
