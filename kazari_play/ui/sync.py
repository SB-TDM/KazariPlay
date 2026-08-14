"""界面更新总线（UISync）— 集中管理"数据变化 → 前端刷新"的全部推送

为什么存在：
- 此前 web_bridge 里散落 35+ 处 self.refresh()、8 处 notify()、4 处 reloadCovers()、
  2 处定向截图刷新，每处直接拼 evaluate_js，线程安全 / 异常处理 / 窗口未就绪降级
  靠约定而非收敛。
- 本模块提供「事件域（domain）→ 前端刷新策略」的注册表 + 微延迟合并（coalesce）：
  同一小段时间内的多次 invalidate 合并为一次 evaluate_js，减少桥接往返。

用法：
    ui = UISync()
    ui.bind_window(window)               # 窗口创建后绑定一次
    ui.invalidate("games")               # 全量刷新（游戏列表/收藏夹树/运行状态）
    ui.invalidate("covers")              # 定向刷新封面（调用方需先清封面缓存）
    ui.invalidate("screenshots", game_id)  # 定向刷新某游戏截图区
    ui.invalidate("toast", "已保存")     # 轻提示

线程安全：任意线程可调用（扫描 / VNDB 匹配 / 键盘钩子线程），evaluate_js 串行化。
"""
import json
import threading

from utils.logger import get_logger

logger = get_logger()

# 微延迟（秒）：把同一时刻附近的多次 invalidate 合并为一次推送。
# 用户操作（收藏/评分等）的 50ms 延迟不可感知，但能显著减少桥接往返。
_FLUSH_DELAY = 0.05

# 事件域 → 前端 JS 入口（window.__app.*）。
# 新增数据域时在这里加一行即可，无需改动调用方。
#   games        -> refresh()               全量刷新
#   covers       -> reloadCovers()          封面定向重载
#   screenshots  -> refreshScreenshots(gid) 截图区定向刷新（payload: game_id）
#   toast        -> toast(msg)              轻提示（payload: 消息文本）
_DOMAIN_JS = {
    "games": "refresh",
    "covers": "reloadCovers",
    "screenshots": "refreshScreenshots",
    "toast": "toast",
}


class UISync:
    """前端界面更新总线"""

    def __init__(self):
        self._window = None
        self._lock = threading.Lock()        # 保护 _pending / _timer
        self._flush_lock = threading.Lock()  # 串行化 evaluate_js（多线程推送时）
        self._pending = {}                   # domain -> payload（插入序即触发序）
        self._timer = None

    # ---------- 对外接口 ----------

    def bind_window(self, window) -> None:
        """绑定 pywebview 窗口（窗口创建后调用；未绑定或已关闭时推送静默跳过）"""
        self._window = window

    def invalidate(self, domain: str, payload=None) -> None:
        """声明"什么数据变了"，稍后合并推送前端（可在任意线程调用）

        Args:
            domain: 事件域，见 _DOMAIN_JS
            payload: 域相关参数（screenshots 传 game_id，toast 传消息文本）
        """
        if domain not in _DOMAIN_JS:
            logger.warning("未知界面更新域: %s", domain)
            return
        with self._lock:
            self._pending[domain] = payload
            if self._timer is None:
                self._timer = threading.Timer(_FLUSH_DELAY, self._flush_scheduled)
                self._timer.daemon = True
                self._timer.start()

    def flush_now(self) -> None:
        """立即推送当前待处理的更新（正常由定时器触发，仅测试/退出前显式调用）"""
        with self._lock:
            pending, self._pending = self._pending, {}
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if pending:
            self._emit(pending)

    # ---------- 内部实现 ----------

    def _flush_scheduled(self) -> None:
        """定时器到期：取走全部待处理项并推送"""
        with self._lock:
            pending, self._pending = self._pending, {}
            self._timer = None
        if pending:
            self._emit(pending)

    def _emit(self, pending: dict) -> None:
        """把一批 pending 域合并为一次 evaluate_js"""
        window = self._window
        if window is None:
            return
        statements = []
        for domain, payload in pending.items():
            if domain == "toast":
                statements.append(
                    f"window.__app && window.__app.toast("
                    f"{json.dumps(payload, ensure_ascii=False)});")
            elif domain == "screenshots":
                gid = json.dumps(payload or "", ensure_ascii=False)
                statements.append(
                    f"window.__app && window.__app.refreshScreenshots({gid});")
            else:
                statements.append(f"window.__app && window.__app.{_DOMAIN_JS[domain]}();")
        if not statements:
            return
        js = "(function(){" + "".join(statements) + "})();"
        with self._flush_lock:
            try:
                window.evaluate_js(js)
            except Exception as e:
                logger.warning("前端更新推送失败: %s", e)
