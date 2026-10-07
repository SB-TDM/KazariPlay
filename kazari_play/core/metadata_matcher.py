"""元数据匹配服务 - 调用 VNDB API 拉取并保守地合并到本地 Game

策略：
- 自动选第一个搜索结果（用户需求：自动选策略）
- 保守更新：仅填充空字段，已有数据不动（用户需求：保守策略）
- 已有 vndb_id 的游戏跳过（避免重复匹配，强制覆盖需 force=True）

封面下载：
- VNDB image.url 下载到 AppData/covers/{game_id}_vndb.jpg
- 已有本地封面则不覆盖（保守策略）

速率限制：
- VNDB 官方限制约 200 次/小时，本地速率限制已按需求移除（不再做请求记账）。
  短时间内大量请求仍可能触发 VNDB 429，届时稍后再试即可。
"""
import os
from typing import Optional, Callable, List, Tuple
from core.game_model import Game
from utils import vndb_client
from utils.path_utils import get_app_data_dir
from utils.logger import get_logger
from utils.title_utils import normalize_title

logger = get_logger()

# 进度回调签名：callback(game_id, game_title, status, message)
#   status: "skip" | "match" | "fail"
ProgressCallback = Callable[[str, str, str, str], None]


def _extract_japanese(title: str) -> str:
    """提取标题中的中文/日文字符部分（用于归一化失败时的回退搜索）

    当归一化后仍搜不到时，用这个提取纯 CJK 字符作为第二次搜索关键词。
    会排除常见的汉化组/版本后缀词，避免把"汉化版"当主标题。
    """
    import re
    if not title:
        return ""
    # 先去掉 [] 包裹的公司名（避免把公司名当主标题）
    cleaned = re.sub(r"\[[^\]]*\]", "", title)
    # 匹配 CJK 统一表意文字 + 平假名 + 片假名
    m = re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+", cleaned)
    if not m:
        return ""
    # 排除汉化组/版本词（包含判断，避免"默示汉化组"漏网）
    blacklist = ("汉化", "中文版", "简体", "繁体",
                 "官方中文", "民间", "完结", "DL版")
    filtered = [s for s in m if not any(kw in s for kw in blacklist)]
    if not filtered:
        return ""
    # 取最长的 CJK 片段（通常是主标题）
    return max(filtered, key=len)


def _cover_dest_path(game_id: str, cover_url: str) -> str:
    """根据游戏 ID 和 URL 推断封面本地保存路径"""
    # 从 URL 取扩展名
    ext = ".jpg"
    if cover_url:
        url_lower = cover_url.lower().split("?")[0]
        if url_lower.endswith(".png"):
            ext = ".png"
        elif url_lower.endswith(".webp"):
            ext = ".webp"
    covers_dir = os.path.join(get_app_data_dir(), "covers")
    return os.path.join(covers_dir, f"{game_id}_vndb{ext}")


def match_single(game: Game, force: bool = False, cancel_event=None) -> Tuple[str, str]:
    """为单个游戏匹配 VNDB 元数据并保守更新

    Args:
        game: 要匹配的游戏（会被原地修改）
        force: True 时即使已有 vndb_id 也重新匹配
        cancel_event: threading.Event，置位时尽快终止（关键词回退 / 封面均检查）

    Returns:
        (status, message)
        status ∈ {"skip", "match", "fail", "cancelled"}
        message 是人类可读的说明
    """
    if not game:
        return "fail", "游戏对象为空"
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled", "已取消"

    # 已有 vndb_id 则跳过（除非 force）
    if game.vndb_id and not force:
        return "skip", f"已匹配过 VNDB（{game.vndb_id}）"

    # 标题归一化后搜索（多策略重试）
    query = normalize_title(game.title)
    if not query:
        return "fail", "标题为空，无法搜索"

    logger.info("VNDB 匹配开始: game_id=%s, title='%s', query='%s'",
                game.id, game.title, query)

    # 搜索策略：依次尝试 归一化标题 → 纯 CJK 提取 → 原标题
    queries_to_try = [query]
    cjk_only = _extract_japanese(game.title)
    if cjk_only and cjk_only != query:
        queries_to_try.append(cjk_only)
    if game.title and game.title != query and game.title != cjk_only:
        queries_to_try.append(game.title)

    result = None
    tried_queries = []
    for i, q in enumerate(queries_to_try):
        # 取消：不再尝试下一个关键词
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled", "已取消"
        tried_queries.append(q)
        logger.info("VNDB 搜索策略 %d: '%s'", i + 1, q)
        try:
            result = vndb_client.search_first_vn(q, cancel_event=cancel_event)
        except Exception as e:
            logger.error("VNDB 搜索异常: q='%s', %s", q, e)
            continue
        if result:
            break

    # 搜索途中被取消（结果为空且事件置位）→ 判为取消，不当作“未找到”
    if (not result) and cancel_event is not None and cancel_event.is_set():
        return "cancelled", "已取消"

    if not result:
        logger.info("VNDB 未找到匹配: 尝试过 %s", tried_queries)
        return "fail", f"未找到匹配（已尝试 {len(tried_queries)} 种关键词）"

    # 保守更新：仅填充空字段
    updated_fields = []

    # vndb_id（始终填，因为前面已检查过空）
    if not game.vndb_id:
        game.vndb_id = result["vndb_id"]
        updated_fields.append("vndb_id")

    # 标题（VNDB 匹配成功后，用 VNDB 正式标题覆盖本地文件夹名标题）
    if result["title"]:
        game.title = result["title"]
        updated_fields.append("title")

    # 描述
    if not game.description and result["description"]:
        game.description = result["description"]
        updated_fields.append("description")

    # 评分（0 表示未评分，本地未评分时填）
    if not game.rating and result["rating"]:
        game.rating = result["rating"]
        updated_fields.append("rating")

    # 发售日
    if not game.released and result["released"]:
        game.released = result["released"]
        updated_fields.append("released")

    # 开发商
    if not game.developer and result["developer"]:
        game.developer = result["developer"]
        updated_fields.append("developer")

    # 游戏长度
    if not game.length_minutes and result["length_minutes"]:
        game.length_minutes = result["length_minutes"]
        updated_fields.append("length_minutes")

    # 封面（VNDB image.url 下载到本地，已有封面则不覆盖）
    if not game.cover_path and result["cover_url"]:
        dest = _cover_dest_path(game.id, result["cover_url"])
        if vndb_client.download_cover(result["cover_url"], dest, cancel_event=cancel_event):
            game.cover_path = dest
            updated_fields.append("cover_path")
        else:
            logger.warning("封面下载失败，跳过: %s", result["cover_url"])

    if not updated_fields:
        return "skip", "所有字段已存在，未更新"

    msg = f"已更新 {len(updated_fields)} 项: {', '.join(updated_fields)}"
    logger.info("VNDB 匹配成功: %s -> %s, %s",
                game.title, result["vndb_id"], msg)
    return "match", msg


def match_batch(
    games: List[Game],
    force: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event=None,
) -> Tuple[int, int, int]:
    """批量匹配 VNDB 元数据

    Args:
        games: 要匹配的游戏列表
        force: True 时强制重新匹配已有 vndb_id 的游戏
        progress_cb: 进度回调（每个游戏调用一次）
        cancel_event: threading.Event，置位时提前结束（可选）

    Returns:
        (matched, skipped, failed) 三元组
    """
    matched = skipped = failed = 0
    total = len(games)

    for i, game in enumerate(games):
        if cancel_event is not None and cancel_event.is_set():
            logger.info("VNDB 批量匹配已取消（已处理 %d/%d）", i, total)
            break
        # 进度回调
        if progress_cb:
            try:
                progress_cb(game.id, game.title, "start",
                            f"[{i + 1}/{total}] 匹配中: {game.title}")
            except Exception:
                pass

        status, msg = match_single(game, force=force, cancel_event=cancel_event)

        if progress_cb:
            try:
                progress_cb(game.id, game.title, status, msg)
            except Exception:
                pass

        if status == "cancelled":
            # 取消不计入成功/跳过/失败，且不再处理后续游戏
            logger.info("VNDB 批量匹配在取消处停止")
            break
        if status == "match":
            matched += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1

    logger.info("VNDB 批量匹配完成: 共 %d, 成功 %d, 跳过 %d, 失败 %d",
                total, matched, skipped, failed)
    return matched, skipped, failed
