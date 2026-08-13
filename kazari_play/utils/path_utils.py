"""路径工具 - 获取系统标准路径（桌面、文档、AppData 等）

Windows 优先用 winreg 读取注册表真实路径（用户可能改过桌面位置），
读不到时回退到 os.path.expanduser。非 Windows 用 HOME 兜底。

数据目录策略：
    优先用 AppData（系统标准位置）；
    若 AppData 不可写（某些 sandbox 环境会拦截 GUI 进程写入），
    自动降级到项目目录下的 data/ 子目录。
"""
import os
import shutil
from typing import Optional


# 缓存可写目录检测结果，避免每次都做写测试
_writable_cache: Optional[str] = None


def _is_writable(path: str) -> bool:
    """检测目录是否真正可写（创建 + 写入 + 删除）"""
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, "_writable_test.tmp")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except Exception:
        return False


def _get_project_data_dir() -> str:
    """获取项目目录下的 data/ 子目录"""
    # path_utils.py 在 utils/ 下，项目根目录是上一级
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_screenshots_dir() -> str:
    """获取项目根目录下的 screenshots/ 根目录（Steam 式截图存放处）

    结构：
        screenshots/
        ├── {game_id}/          # 每个游戏一个子文件夹，单独管理该游戏截图
        │   ├── shot_20260811_201530.png
        │   └── ...
        └── _unsorted/          # 无运行游戏时的截图（暂存）

    定位到项目根（KazariPlay_V1.0/），即 path_utils.py 上级的上级的上级：
        kazari_play/utils/path_utils.py -> KazariPlay_V1.0/
    """
    project_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    shots_dir = os.path.join(project_root, "screenshots")
    os.makedirs(shots_dir, exist_ok=True)
    return shots_dir


def get_game_screenshots_dir(game_id: str) -> str:
    """获取某游戏截图子目录（不存在时自动创建）"""
    d = os.path.join(get_screenshots_dir(), game_id)
    os.makedirs(d, exist_ok=True)
    return d

def get_app_data_dir(app_name: str = "KazariPlay") -> str:
    """获取应用数据目录（用于存数据库、配置、日志等）

    Windows: %APPDATA%\\<app_name>
    其他:    ~/.<app_name>

    若 AppData 不可写（sandbox 拦截），降级到项目目录 data/。
    目录不存在时自动创建。
    """
    global _writable_cache
    # 有缓存直接返回
    if _writable_cache is not None:
        return _writable_cache

    # 1. 尝试 AppData
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        app_dir = os.path.join(base, app_name)
    else:
        app_dir = os.path.join(os.path.expanduser("~"), f".{app_name.lower()}")

    try:
        os.makedirs(app_dir, exist_ok=True)
    except Exception:
        app_dir = None

    # 2. 检测 AppData 是否可写
    if app_dir and _is_writable(app_dir):
        _writable_cache = app_dir
        return app_dir

    # 3. 降级到项目目录 data/
    fallback = _get_project_data_dir()
    _writable_cache = fallback
    return fallback


def migrate_data_if_needed() -> bool:
    """若降级到项目目录，把 AppData 的现有数据迁移过来

    Returns:
        True 表示执行了迁移或无需迁移，False 表示迁移失败
    """
    global _writable_cache
    if _writable_cache is None:
        get_app_data_dir()  # 触发检测

    # 只有降级到项目目录时才需要迁移
    project_data = _get_project_data_dir()
    if _writable_cache != project_data:
        return True  # 用的是 AppData，无需迁移

    # 找到 AppData 原目录
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        old_dir = os.path.join(base, "MinatoLauncher")
    else:
        old_dir = os.path.join(os.path.expanduser("~"), ".MinatoLauncher")

    if not os.path.exists(old_dir):
        return True  # 无旧数据，无需迁移

    # 迁移文件（不覆盖已有文件）
    try:
        for item in os.listdir(old_dir):
            src = os.path.join(old_dir, item)
            dst = os.path.join(project_data, item)
            if os.path.exists(dst):
                continue  # 不覆盖
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst)
        return True
    except Exception:
        return False


def get_default_db_path(app_name: str = "KazariPlay") -> str:
    """获取默认数据库路径（固定到用户 AppData 目录）"""
    return os.path.join(get_app_data_dir(app_name), "games.db")


def get_default_config_path(app_name: str = "KazariPlay") -> str:
    """获取默认配置文件路径"""
    return os.path.join(get_app_data_dir(app_name), "config.json")


def get_default_log_dir(app_name: str = "KazariPlay") -> str:
    """获取默认日志目录"""
    log_dir = os.path.join(get_app_data_dir(app_name), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
