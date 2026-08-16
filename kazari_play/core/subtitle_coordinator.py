"""字幕翻译协调器（方案 A：翻译完全在 C++ 内部）

架构：
- C++ overlay 负责：Hook 提取 → 稳定去重 → AI 翻译 → 字幕渲染（先原文后替换）
- Python 只负责：会话启动/停止、Hook 点选择、AI 配置传递、候选/错误转发

线程模型：
- OverlayClient 读线程只解析 + 分发（hook_candidates / hook_error）
- 翻译在 C++ 的 AiTranslator worker 线程，Python 不参与
"""
import threading
from typing import Optional

from core.overlay_client import OverlayClient
from utils.config import Config
from utils.logger import get_logger

logger = get_logger()


class SubtitleCoordinator:
    """字幕翻译协调器（配置传递 + 会话状态）"""

    def __init__(self):
        self._cfg = Config()
        self._overlay = OverlayClient()
        self._running = False
        self._selected_handle: Optional[int] = None
        self._awaiting_selection = False   # 首次配置：等待用户选择 Hook 点
        self._last_candidates: list = []
        self._last_error: str = ""
        # 外部回调（web_bridge 挂接，任意线程触发）
        self.on_candidates_updated: Optional[callable] = None
        self.on_error_updated: Optional[callable] = None

    # ---------- 会话控制 ----------

    def start_hook_session(self, pid: int, is_x64: bool,
                           hook_code: str = "",
                           engine: str = "",
                           codepage: int = 0,
                           ai_config: dict = None,
                           filter_override: str = "",
                           ai_clean_mode: int = 0) -> bool:
        """通知 C++ overlay 开始 Hook 会话，并传 AI 翻译配置（翻译在 C++）"""
        self._running = True
        self._awaiting_selection = not bool(hook_code)
        self._selected_handle = None
        self._last_candidates = []
        # 注册回调（由 OverlayClient 的读线程调用，必须快速返回）
        self._overlay.on_candidates = self._on_candidates
        self._overlay.on_error = self._on_error

        # 启动 overlay 双向管道（含读线程）
        if not self._overlay.ensure_bidirectional():
            self._running = False
            logger.warning("start_hook_session: ensure_bidirectional 失败")
            return False

        # 发 start_hook 命令（带 AI 配置）
        ok = self._overlay.send_start_hook(
            pid=pid, is_x64=is_x64,
            hook_code=hook_code, engine=engine, codepage=codepage,
            ai_config=ai_config,
            ai_clean_mode=ai_clean_mode,
        )
        logger.info("start_hook_session: send_start_hook=%s pid=%s x64=%s hook_empty=%s",
                    ok, pid, is_x64, not bool(hook_code))
        if not ok:
            self._running = False
            return False
        # 应用该游戏的清洗过滤器覆盖（非空则覆盖引擎默认策略）
        import json
        try:
            ov = json.loads(filter_override or "[]") or []
        except (ValueError, TypeError):
            ov = []
        if ov:
            self._overlay.send_update_filter_config(ov)
        # 应用全局字幕总开关（设置页「显示字幕」；C++ 默认开启，需显式下发）
        try:
            sub_enabled = bool(self._cfg.get("subtitle.enabled", True))
            self._overlay.send_set_subtitle_enabled(sub_enabled)
        except Exception as e:
            logger.error("下发字幕开关失败: %s", e)
        return True

    def select_hook(self, handle: int, hook_code: str = ""):
        """用户选定 Hook 点（hook_code 持久化由调用方负责）"""
        self._selected_handle = handle
        self._awaiting_selection = False
        self._overlay.send_select_hook(handle, hook_code)

    def stop(self):
        """停止 Hook 会话：先停 hook 并隐藏字幕，再退出 overlay 进程
        （避免 overlay 残留干扰下次 GUI 启动后新实例的注入/字幕加载）"""
        self._running = False
        for fn in (self._overlay.send_stop_hook, self._overlay.send_hide_subtitle):
            try:
                fn()
            except Exception as e:
                logger.error("停止翻译发送失败: %s", e)
        try:
            self._overlay.quit()
        except Exception as e:
            logger.error("退出 overlay 失败: %s", e)

    # ---------- 回调（读线程，必须快速返回） ----------

    def _on_candidates(self, candidates: list):
        self._last_candidates = candidates or []
        if self.on_candidates_updated:
            self.on_candidates_updated(self._last_candidates)

    def _on_error(self, msg: str):
        self._last_error = msg or ""
        logger.error("Hook 错误: %s", msg)
        if self.on_error_updated:
            self.on_error_updated(msg or "")
