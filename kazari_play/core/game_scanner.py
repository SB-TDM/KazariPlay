import os
import hashlib
from typing import List, Optional
from core.game_model import Game

class GameScanner:
    """游戏扫描器 - 识别文件夹中的可执行文件"""

    # 常见的 Galgame 引擎标识
    # 每个引擎分两类关键词：
    #   exact:  exe 完整文件名（basename，含扩展名，大小写不敏感）匹配
    #           —— 用于 RPG Maker 的 Game.exe / RPG_RT.exe 这类固定入口程序
    #   substr: exe 文件名子串匹配（大小写不敏感）
    #           —— 用于 krkr / unity / renpy 这类出现在任意位置的特征词
    # 顺序即优先级：靠前的引擎在同等命中条件下优先返回。
    ENGINE_PATTERNS = {
        "rpg_maker": {
            "exact":  ["game.exe", "rpg_rt.exe", "rpgvxace.exe", "rpgmv.exe", "rpgmz.exe"],
            "substr": ["rpg_rt", "rpgvx", "rpgmv", "rpgmz"],
        },
        "renpy": {
            "exact":  [],
            "substr": ["renpy", "ren'py"],
        },
        "unity": {
            "exact":  [],
            "substr": ["unity", "unityplayer", "unityengine"],
        },
        "kirikiri": {
            "exact":  [],
            "substr": ["krkr", "kirikiri", "krkrrel"],
        },
        "bgi": {
            "exact":  ["bgi.exe"],
            "substr": ["bgi_chs", "bgi_cht"],
        },
        "tyrano": {
            "exact":  [],
            "substr": ["tyrano", "tyranoscript"],
        },
        "artemis": {
            "exact":  [],
            "substr": ["artemis"],
        },
        "siglus": {
            "exact":  [],
            "substr": ["siglus", "sigplus"],
        },
        "nscripter": {
            "exact":  [],
            "substr": ["nscripter", "nsa"],
        },
    }

    # 汉化版关键词（文件名子串匹配，大小写不敏感）
    # 用于"同文件夹多 exe 聚合"时优先选汉化启动器
    CHS_KEYWORDS = (
        "chs", "cht", "cn", "chinese", "gbk", "gb2312",
        "汉化", "中文", "简体", "繁体",
    )

    def __init__(self):
        # 辅助程序黑名单（子串匹配，大小写不敏感）
        # 这些是 Galgame 目录里常见的非游戏启动器
        self.ignore_patterns = [
            # 系统安装/卸载类
            "uninstall", "config", "setup", "install", "launcher",
            "dxwebsetup", "vcredist", "dotnet", "directx",
            # 运行库/补丁工具
            "patch", "update", "upgrade", "crack", "no_dvd", "nodvd",
            # 存档/存档编辑工具
            "saveedit", "save_edit", "saveeditor", "savedata",
            # 系统信息查看器
            "pcinformation", "sysinfo", "systeminfo",
            # 视频播放器（August 引擎的 BHVC = BGI Movie Player）
            "bhvc",
            # August 引擎的存档工具
            "esufor", "isesufor",
            # 通用查看器/编辑器（注意：不能太激进，避免误伤）
            "viewer", "editor", "converter", "extractor",
            # 配置工具
            "setting", "option", "preference",
        ]
        # 白名单：即使命中黑名单也保留的 exe（完整名匹配）
        # 防止某些游戏主程序名恰好包含黑名单词
        # 注意：只放确定是游戏主程序的名称
        self.whitelist_exact = set()
        # 文件夹名黑名单：扫描时跳过这些文件夹（子串匹配，大小写不敏感）
        # 用于过滤补丁备份、副本等非游戏目录
        self.ignore_folders = [
            "补丁", "备份", "patch", "backup", "副本",
        ]
        self.include_extensions = {".exe"}

    def scan(self, folder_path: str, recursive: bool = True) -> List[Game]:
        """扫描文件夹，返回游戏列表

        聚合策略：一个文件夹 = 一个游戏。
        同一文件夹内多个 exe 时，优先选汉化版启动器。

        Args:
            folder_path: 要扫描的文件夹
            recursive: 是否递归扫描子文件夹

        Returns:
            找到的游戏列表
        """
        if not os.path.exists(folder_path):
            return []

        # 1. 收集每个文件夹下的合法 exe（按文件夹分组）
        folder_exes = {}  # {folder_path: [exe_filename, ...]}
        if recursive:
            for root, dirs, files in os.walk(folder_path):
                # 跳过黑名单文件夹（补丁备份/副本等），原地修改 dirs 让 os.walk 不进入
                dirs[:] = [d for d in dirs if not self._is_ignored_folder(d)]
                for f in files:
                    if self._is_valid_game_exe(f):
                        folder_exes.setdefault(root, []).append(f)
        else:
            for f in os.listdir(folder_path):
                fp = os.path.join(folder_path, f)
                if os.path.isfile(fp) and self._is_valid_game_exe(f):
                    folder_exes.setdefault(folder_path, []).append(f)

        # 2. 每个文件夹选一个主 exe（汉化版优先）→ 创建 Game
        games = []
        for folder, exes in folder_exes.items():
            if not exes:
                continue
            primary = self._pick_primary_exe(exes)
            game = self._check_file(folder, primary)
            if game:
                games.append(game)

        return games

    def _is_valid_game_exe(self, filename: str) -> bool:
        """判断 exe 是否为合法游戏启动器（扩展名 + 黑名单过滤）"""
        file_lower = filename.lower()
        # 扩展名
        if not any(file_lower.endswith(ext) for ext in self.include_extensions):
            return False
        # 白名单优先
        if file_lower in self.whitelist_exact:
            return True
        # 黑名单
        for pattern in self.ignore_patterns:
            if pattern in file_lower:
                return False
        return True

    def _is_chs_exe(self, filename: str) -> bool:
        """判断 exe 是否为汉化版启动器（文件名含 chs/cht/汉化 等关键词）"""
        name_lower = filename.lower()
        return any(kw.lower() in name_lower for kw in self.CHS_KEYWORDS)

    def _pick_primary_exe(self, exes: list) -> str:
        """从同文件夹多个 exe 中选主启动器

        优先级：
          1. 汉化版启动器优先（玩家通常想玩汉化版）
          2. 同类里按文件名排序取第一个（保证可预测）
          3. 非汉化版里按文件名排序取第一个
        """
        if len(exes) <= 1:
            return exes[0] if exes else ""
        chs = [e for e in exes if self._is_chs_exe(e)]
        if chs:
            return sorted(chs)[0]
        return sorted(exes)[0]

    def _is_ignored_folder(self, folder_name: str) -> bool:
        """判断文件夹是否应被跳过（补丁备份/副本等）"""
        name_lower = folder_name.lower()
        return any(kw in name_lower for kw in self.ignore_folders)

    def _check_file(self, folder: str, filename: str) -> Optional[Game]:
        """检查单个文件是否为游戏"""
        file_lower = filename.lower()

        # 检查扩展名
        if not any(file_lower.endswith(ext) for ext in self.include_extensions):
            return None

        # 白名单优先：即使命中黑名单也保留
        if file_lower not in self.whitelist_exact:
            # 忽略辅助程序（安装/卸载/存档工具/查看器等）
            for pattern in self.ignore_patterns:
                if pattern in file_lower:
                    return None

        # 如果有 .exe 且不是辅助程序，创建游戏对象
        exe_path = os.path.join(folder, filename)

        # 检测引擎类型
        engine = self._detect_engine(folder, file_lower)

        # 生成标题（优先级：exe 内嵌元信息 → 文件夹名 → 文件名）
        title = self._generate_title(folder, filename)

        # 生成唯一 ID
        game_id = self._generate_id(exe_path)

        return Game(
            id=game_id,
            title=title,
            exe_path=exe_path,
            folder=folder,
            engine=engine
        )

    def _generate_title(self, folder: str, filename: str) -> str:
        """生成游戏标题

        简化方案：直接用 exe 直接父文件夹名作为标题。
        这是用户确认的方案 —— 简单可靠，无需复杂清洗逻辑。
        文件夹名通常包含游戏名（如「千之刃涛-桃花染之皇姬_弥生月汉化组」）。
        """
        folder_name = os.path.basename(os.path.normpath(folder))
        # 兜底：若文件夹名为空（理论上不会发生），用 exe 文件名
        if not folder_name:
            return os.path.splitext(filename)[0]
        return folder_name

    def _detect_engine(self, folder: str, exe_name: str) -> str:
        """检测游戏引擎

        检测顺序（可靠性从高到低）：
          1. 文件夹特征文件（最可靠，几乎不会误判）
          2. exe 完整文件名匹配（适用于 RPG Maker 固定入口）
          3. exe 文件名子串匹配（兜底）

        Args:
            folder:   exe 所在文件夹
            exe_name: exe 文件名（原始大小写）
        """
        exe_lower = exe_name.lower()

        # ---------- 1. 特征文件检测（最可靠）----------
        try:
            files = os.listdir(folder)
            files_lower = [f.lower() for f in files]

            # Ren'Py 特征：有 renpy 文件夹或 .rpyc 文件
            if "renpy" in files_lower or any(f.endswith(".rpyc") for f in files_lower):
                return "renpy"

            # Unity 特征：有 UnityPlayer.dll / UnityEngine.dll / Managed 文件夹
            if ("unityplayer.dll" in files_lower
                    or any("unityengine" in f for f in files_lower)
                    or "managed" in files_lower):
                return "unity"

            # RPG Maker MV/MZ 特征：www/data 文件夹
            if "www" in files_lower:
                www_path = os.path.join(folder, "www")
                if os.path.isdir(www_path) and "data" in os.listdir(www_path):
                    return "rpg_maker"

            # Kirikiri 特征：有 .xp3 文件
            if any(f.endswith(".xp3") for f in files_lower):
                return "kirikiri"

            # BGI (August) 特征：sysgrp.arc + sysprg.arc + BGI.exe 主程序
            # August 社招牌引擎（大图书馆的牧羊人 / 千之刃涛 / FORTUNE ARTERIAL 等）
            if ("sysgrp.arc" in files_lower
                    and "sysprg.arc" in files_lower
                    and "bgi.exe" in files_lower):
                return "bgi"

            # Tyrano 特征：有 tyrano 文件夹
            if "tyrano" in files_lower:
                return "tyrano"

        except Exception:
            pass

        # ---------- 2. exe 完整文件名匹配 ----------
        # 适用于 RPG Maker 系列：入口程序固定叫 Game.exe / RPG_RT.exe 等
        for engine, patterns in self.ENGINE_PATTERNS.items():
            for keyword in patterns.get("exact", []):
                if exe_lower == keyword:
                    return engine

        # ---------- 3. exe 文件名子串匹配（兜底）----------
        for engine, patterns in self.ENGINE_PATTERNS.items():
            for keyword in patterns.get("substr", []):
                if keyword in exe_lower:
                    return engine

        return "其他"

    def _generate_id(self, exe_path: str) -> str:
        """根据 exe 路径生成唯一 ID"""
        # 使用 MD5 的前16位作为 ID
        return hashlib.md5(exe_path.encode("utf-8")).hexdigest()[:16]