"""标题归一化工具 — 从杂乱文件夹名/标题中提取核心游戏名

供多处共用：
- metadata_matcher：VNDB 搜索前清洗查询词
- game_scanner：生成游戏 identity（跨文件夹判重，同一游戏不同命名归一为同一键）
"""
import re

# 语言/版本后缀（可出现在开头或结尾）
_LANG_SUFFIX = r"(?:DL版|简体版|繁体版|汉化版|中文版|完结版|官方中文|民间汉化)"


def normalize_title(title: str) -> str:
    """标题归一化：去除常见前缀/后缀和符号，提取核心游戏名

    处理规则（按顺序）：
    1. 去除开头的平台前缀：PC / PC+krkr / PC+renpy 等
    2. 去除开头的 [xxx] / (xxx) 前缀（公司名、汉化组标识）
    3. 去除 _xxx 后缀（汉化组、子标题、年份等）
    4. 去除版本号后缀：v1.02 / Ver1.02 / v1.02.3 / (1.02)
    5. 去除 DL版 / 简体版 / 繁体版 / 汉化版 / 中文版 等后缀
    6. 去除 ～副标题～ / 第X章 / Chapter X 等副标题
    7. 去除连续空格

    示例：
        PC+krkr[ぱれっとクオリア]少女领域_默示汉化组 -> 少女领域
        PC[AUGUST]更胜黎明前的琉璃色_月桂琉璃汉化组 -> 更胜黎明前的琉璃色
        [AUGUST]大图书馆的牧羊人_杏子御津爱护同好会 -> 大图书馆的牧羊人
        DL版_月姫 -> 月姫
        月姫 v1.02 -> 月姫
        少女领域～完结篇～ -> 少女领域
        CLANNAD 汉化版 -> CLANNAD
        月姫(1.02) -> 月姫
        月姫 第2章 -> 月姫
    """
    if not title:
        return ""
    t = title.strip()

    # 1. 去除开头平台前缀：PC / PC+xxx（直到遇到 [ 或中文/日文字符）
    m = re.match(r"^PC(?:\+\w+)?(?=\[|[^\x00-\x7f])", t)
    if m:
        t = t[m.end():].strip()

    # 1.5 去除开头的 DL版 / 简体版 / 繁体版 等前缀（前缀形式）
    t = re.sub(r"^" + _LANG_SUFFIX + r"[_\s]*", "", t).strip()

    # 2. 循环去除开头的 [xxx] / (xxx) 前缀（公司名、汉化组）
    while t and t[0] in "[(":
        close = "]" if t[0] == "[" else ")"
        end = t.find(close)
        if end == -1:
            break
        t = t[end + 1:].strip()

    # 3. 去除 _xxx 后缀（汉化组、子标题、年份）
    if "_" in t:
        t = t.split("_")[0].strip()

    # 4. 去除版本号后缀：v1.02 / Ver1.02 / v1.02.3（不区分大小写）
    t = re.sub(r"\s*[vV](?:er)?\d+(?:\.\d+)*\s*$", "", t).strip()

    # 5. 去除 (数字) 结尾的版本号：月姫(1.02) -> 月姫
    t = re.sub(r"\(\d+(?:\.\d+)*\)\s*$", "", t).strip()

    # 6. 去除 DL版 / 简体版 / 繁体版 / 汉化版 / 中文版 / 完结版 等后缀
    t = re.sub(r"\s*" + _LANG_SUFFIX + r"\s*$", "", t).strip()

    # 7. 去除 ～副标题～ / ~副标题~ 后缀（只保留主标题）
    t = re.sub(r"[～~][^～~]*[～~]\s*$", "", t).strip()

    # 8. 去除 第X章 / Chapter X 后缀
    t = re.sub(r"\s*第\d+章\s*$", "", t).strip()
    t = re.sub(r"\s*[Cc]hapter\s*\d+\s*$", "", t).strip()

    # 9. 去除多余空格
    t = re.sub(r"\s+", " ", t).strip()
    return t
