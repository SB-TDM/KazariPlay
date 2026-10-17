"""封面文件仓库：单文件、确定性缩略图、原子写入、迁移与清理

布局：
    <data>/covers/{game_id}.{jpg|png|webp|gif}
    <data>/covers/thumbs/{game_id}_w512.jpg

来源（VNDB/Bangumi/手动）只是元数据，不再对应不同文件；换封面覆盖同一文件，
旧变体与旧缩略图在保存成功后删除。
"""
import glob
import os
import re
import shutil
import threading
import time
from typing import Callable, List, Optional, Tuple

from PIL import Image

from utils.path_utils import get_app_data_dir
from utils.logger import get_logger
from utils import vndb_client

logger = get_logger()

_COVER_EXTS = (".jpg", ".png", ".webp", ".gif")
_LEGACY_SUFFIXES = ("_manual", "_ms", "_vndb")
_THUMB_WIDTH = 512
_THUMB_QUALITY = 85
_CLEANUP_GRACE = 600


def detect_extension(data: bytes) -> str:
    """按文件头识别图片格式；未知返回空串"""
    if not data:
        return ""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ""


def _replace_with_retry(src: str, dst: str, attempts: int = 12) -> None:
    """Windows 下目标可能正被 HTTP 读取；短暂重试 os.replace"""
    last = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:  # noqa: PERF203
            last = e
            time.sleep(0.05)
    raise last  # type: ignore[misc]


class CoverStore:
    def __init__(self, base_dir: Optional[str] = None):
        self.covers_dir = base_dir or os.path.join(get_app_data_dir(), "covers")
        self.thumbs_dir = os.path.join(self.covers_dir, "thumbs")
        self._locks: dict = {}
        self._locks_guard = threading.Lock()

    # ---------- 路径 ----------

    def _ensure_dirs(self) -> None:
        os.makedirs(self.covers_dir, exist_ok=True)
        os.makedirs(self.thumbs_dir, exist_ok=True)

    def canonical_path(self, game_id: str, ext: str) -> str:
        return os.path.join(self.covers_dir, f"{game_id}{ext}")

    def thumb_path(self, game_id: str) -> str:
        return os.path.join(self.thumbs_dir, f"{game_id}_w512.jpg")

    def find_cover(self, game_id: str) -> str:
        """优先正式文件，其次旧版 _manual/_ms/_vndb 变体"""
        for ext in _COVER_EXTS:
            p = self.canonical_path(game_id, ext)
            if os.path.isfile(p):
                return p
        for suffix in _LEGACY_SUFFIXES:
            pattern = os.path.join(self.covers_dir, f"{glob.escape(game_id)}{suffix}.*")
            found = [p for p in glob.glob(pattern) if os.path.isfile(p)]
            if found:
                return max(found, key=os.path.getmtime)
        return ""

    @staticmethod
    def version(path: str) -> str:
        try:
            st = os.stat(path)
            return f"{int(st.st_mtime)}-{st.st_size}"
        except OSError:
            return "0-0"

    # ---------- 保存 / 删除 ----------

    def _lock_for(self, game_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(game_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[game_id] = lock
            return lock

    def _remove_other_variants(self, game_id: str, keep: str) -> None:
        keep_abs = os.path.normcase(os.path.abspath(keep))
        for ext in _COVER_EXTS:
            p = self.canonical_path(game_id, ext)
            if os.path.normcase(os.path.abspath(p)) == keep_abs:
                continue
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        for suffix in _LEGACY_SUFFIXES:
            for p in glob.glob(os.path.join(
                    self.covers_dir, f"{glob.escape(game_id)}{suffix}.*")):
                if os.path.normcase(os.path.abspath(p)) == keep_abs:
                    continue
                try:
                    os.remove(p)
                except OSError:
                    pass
        thumb = self.thumb_path(game_id)
        if os.path.isfile(thumb):
            try:
                os.remove(thumb)
            except OSError:
                pass

    def save_bytes(self, game_id: str, data: bytes) -> str:
        ext = detect_extension(data)
        if not ext:
            logger.warning("封面格式无法识别: game_id=%s, %d bytes", game_id, len(data))
            return ""
        self._ensure_dirs()
        dest = self.canonical_path(game_id, ext)
        tmp = os.path.join(self.covers_dir,
                           f".{game_id}.{os.getpid()}.{threading.get_ident()}.part")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            with self._lock_for(game_id):
                _replace_with_retry(tmp, dest)
                self._remove_other_variants(game_id, dest)
        except OSError as e:
            logger.warning("封面写入失败: game_id=%s, %s", game_id, e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return ""
        return dest

    def save_file(self, game_id: str, src: str) -> str:
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError as e:
            logger.warning("读取封面失败: %s, %s", src, e)
            return ""
        return self.save_bytes(game_id, data)

    def download(self, game_id: str, url: str, cancel_event=None,
                 progress_cb: Optional[Callable] = None) -> str:
        """下载到临时文件后原子替换；返回正式封面路径，失败返回空串"""
        if not url:
            return ""
        self._ensure_dirs()
        tmp = os.path.join(self.covers_dir,
                           f".{game_id}.{os.getpid()}.{threading.get_ident()}.dl")
        try:
            ok = vndb_client.download_cover(url, tmp, cancel_event=cancel_event,
                                            progress_cb=progress_cb)
            if not ok or not os.path.isfile(tmp):
                return ""
            with open(tmp, "rb") as f:
                head = f.read(16)
            ext = detect_extension(head)
            if not ext:
                logger.warning("下载封面格式无法识别: %s", url)
                return ""
            dest = self.canonical_path(game_id, ext)
            with self._lock_for(game_id):
                _replace_with_retry(tmp, dest)
                self._remove_other_variants(game_id, dest)
            return dest
        except Exception as e:  # noqa: BLE001
            logger.warning("封面下载失败: game_id=%s, %s", game_id, e)
            return ""
        finally:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def delete(self, game_id: str) -> int:
        removed = 0
        for ext in _COVER_EXTS:
            p = self.canonical_path(game_id, ext)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        for suffix in _LEGACY_SUFFIXES:
            for p in glob.glob(os.path.join(
                    self.covers_dir, f"{glob.escape(game_id)}{suffix}.*")):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        thumb = self.thumb_path(game_id)
        if os.path.isfile(thumb):
            try:
                os.remove(thumb)
                removed += 1
            except OSError:
                pass
        return removed

    # ---------- 缩略图 ----------

    def ensure_thumb(self, game_id: str) -> str:
        cover = self.find_cover(game_id)
        if not cover:
            return ""
        thumb = self.thumb_path(game_id)
        try:
            if os.path.isfile(thumb) and os.path.getmtime(thumb) >= os.path.getmtime(cover):
                return thumb
        except OSError:
            pass
        with self._lock_for(game_id):
            try:
                if os.path.isfile(thumb) and os.path.getmtime(thumb) >= os.path.getmtime(cover):
                    return thumb
                self._ensure_dirs()
                with Image.open(cover) as im:
                    im = im.convert("RGB")
                    w, h = im.size
                    if w > _THUMB_WIDTH:
                        im = im.resize((_THUMB_WIDTH, max(1, int(h * _THUMB_WIDTH / w))),
                                       Image.LANCZOS)
                    tmp = thumb + ".part"
                    im.save(tmp, "JPEG", quality=_THUMB_QUALITY)
                _replace_with_retry(tmp, thumb)
                return thumb
            except Exception as e:  # noqa: BLE001
                logger.warning("封面缩略图生成失败: game_id=%s, %s", game_id, e)
                return ""

    # ---------- 迁移 / 清理 ----------

    def migrate(self, repo) -> int:
        """把旧路径/旧变体收敛到 covers/{id}.{ext}，失败不阻塞"""
        migrated = 0
        for g in repo.get_all():
            try:
                src = ""
                if g.cover_path and os.path.isfile(g.cover_path):
                    src = g.cover_path
                else:
                    src = self.find_cover(g.id)
                if not src:
                    continue
                src_name = os.path.basename(src)
                canonical = self.find_cover(g.id)
                is_canonical = bool(re.fullmatch(rf"{re.escape(g.id)}\.(jpg|png|webp|gif)", src_name))
                if is_canonical and canonical:
                    dest = canonical
                else:
                    dest = self.save_file(g.id, src)
                    if not dest:
                        continue
                    # 只清理由 CoverStore 管理的旧变体；旧目录/外部路径保留，避免误删用户文件
                if os.path.normcase(os.path.abspath(g.cover_path or "")) != os.path.normcase(os.path.abspath(dest)):
                    repo.update_cover_path(g.id, dest)
                migrated += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("封面迁移失败: %s, %s", g.id, e)
        if migrated:
            logger.info("封面迁移完成: %d 个", migrated)
        return migrated

    def cleanup(self, repo) -> int:
        """删除未引用封面与过期缩略图（保留 10 分钟宽限）"""
        if not os.path.isdir(self.covers_dir):
            return 0
        games = repo.get_all()
        refs = set()
        expected_thumbs = set()
        for g in games:
            p = self.find_cover(g.id)
            if p:
                refs.add(os.path.normcase(os.path.abspath(p)))
                expected_thumbs.add(os.path.basename(self.thumb_path(g.id)))
        now = time.time()
        removed = 0
        for name in os.listdir(self.covers_dir):
            p = os.path.join(self.covers_dir, name)
            if not os.path.isfile(p):
                continue
            if os.path.normcase(os.path.abspath(p)) in refs:
                continue
            try:
                if now - os.path.getmtime(p) < _CLEANUP_GRACE:
                    continue
                os.remove(p)
                removed += 1
            except OSError:
                pass
        if os.path.isdir(self.thumbs_dir):
            for name in os.listdir(self.thumbs_dir):
                p = os.path.join(self.thumbs_dir, name)
                if not os.path.isfile(p) or name in expected_thumbs:
                    continue
                try:
                    if now - os.path.getmtime(p) < _CLEANUP_GRACE:
                        continue
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("封面清理: 删除 %d 个未使用文件", removed)
        return removed
