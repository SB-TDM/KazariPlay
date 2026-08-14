"""全局热键管理（keyboard 库，注册失败静默降级）

目前仅实现截图热键（默认 F12）：
- 启动时由 main.py 调用 register_screenshot_hotkey() 注册一次
- 用户在设置里修改后，WebBridge.updateScreenshotHotkey() 调用
  reconfigure_screenshot_hotkey() 重新注册（先移除旧热键），立即生效无需重启
- keyboard 库缺失 / 注册失败时静默降级（截图仍可通过前端按钮触发）
"""
import threading

from utils.config import Config
from utils.logger import get_logger

logger = get_logger()

# 当前截图热键回调（由 register_screenshot_hotkey 保存，重注册时复用）
_screenshot_callback = None
# keyboard.add_hotkey 返回的 handler（传给 remove_hotkey 移除）
_screenshot_handler = None
_lock = threading.Lock()


def _normalize(hotkey) -> str:
    """规范化热键字符串：小写 + 去空格，兼容设置页的 'Ctrl + Shift + P' 格式"""
    return "".join(str(hotkey or "").lower().split())


def _current_screenshot_hotkey() -> str:
    """从配置读取截图热键（默认 f12）"""
    hotkey = (Config().get("hotkeys") or {}).get("screenshot", "f12")
    return _normalize(hotkey)


def register_screenshot_hotkey(callback) -> bool:
    """注册全局截图热键（可重复调用：先移除旧的再注册新的）

    Args:
        callback: 触发时执行的回调（无参数）

    Returns:
        True 注册成功 / False 降级（keyboard 不可用或注册失败）
    """
    global _screenshot_callback, _screenshot_handler
    with _lock:
        _screenshot_callback = callback
        try:
            import keyboard
        except Exception as e:
            logger.warning("keyboard 库不可用，全局截图热键禁用: %s", e)
            return False
        # 先移除旧热键（避免重复注册）
        if _screenshot_handler is not None:
            try:
                keyboard.remove_hotkey(_screenshot_handler)
            except Exception:
                pass
            _screenshot_handler = None
        hotkey = _current_screenshot_hotkey()
        if not hotkey:
            logger.warning("截图热键为空，跳过注册")
            return False
        try:
            _screenshot_handler = keyboard.add_hotkey(hotkey, callback)
            logger.info("全局截图热键已注册: %s", hotkey)
            return True
        except Exception as e:
            logger.warning("注册截图热键失败（可能需要管理员权限）: %s", e)
            return False


def reconfigure_screenshot_hotkey() -> bool:
    """按当前配置重新注册截图热键（设置修改后调用，立即生效）

    Returns:
        True 注册成功 / False 降级（未注册过或 keyboard 不可用）
    """
    if _screenshot_callback is None:
        return False
    return register_screenshot_hotkey(_screenshot_callback)
