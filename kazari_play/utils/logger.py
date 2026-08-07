"""日志系统

提供全局可配置的 logger，支持控制台 + 文件双输出。
首次调用 get_logger() 时自动初始化，默认级别 INFO。

用法:
    from utils.logger import get_logger
    logger = get_logger()
    logger.info("启动游戏: %s", title)
    logger.error("数据库失败: %s", e)
"""
import logging
import sys
from typing import Optional

from utils.path_utils import get_default_log_dir

_initialized = False
_logger: Optional[logging.Logger] = None


def get_logger(name: str = "KazariPlay", level: str = "INFO") -> logging.Logger:
    """获取全局 logger（首次调用时初始化）

    Args:
        name:  logger 名称
        level: 日志级别 "DEBUG" / "INFO" / "WARNING" / "ERROR"
    """
    global _initialized, _logger
    if _initialized and _logger:
        return _logger

    _logger = logging.getLogger(name)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 防止重复添加 handler（logging.getLogger 会复用同名 logger）
    if not _logger.handlers:
        _setup_handlers(_logger)
    _initialized = True
    return _logger


def _setup_handlers(logger: logging.Logger):
    """配置控制台 + 文件双输出"""
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出（stderr，不干扰正常 print）
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件输出：尝试多个路径，必须能真正写入才用
    # （sandbox 可能允许创建 FileHandler 但写入时拦截）
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_paths_to_try = [
        os.path.join(project_root, "debug.log"),  # 优先项目目录（最可靠）
    ]
    try:
        log_dir = get_default_log_dir()
        log_paths_to_try.append(os.path.join(log_dir, "app.log"))
    except Exception:
        pass

    for log_path in log_paths_to_try:
        try:
            # 创建 handler 后立即写一行测试日志，验证可写
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
            # 测试写入
            logger.info("日志文件已就绪: %s", log_path)
            return  # 成功则不再尝试
        except Exception:
            # 移除失败的 handler
            if file_handler in logger.handlers:
                logger.removeHandler(file_handler)
            continue


def set_level(level: str):
    """运行时调整日志级别"""
    if _logger:
        _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
