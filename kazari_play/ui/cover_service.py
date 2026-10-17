"""本地 HTTP 封面服务：仅监听 127.0.0.1，提供 512 缩略图

URL:
    http://127.0.0.1:{port}/c/{token}/cover/{game_id}?v=<mtime>-<size>

- token 每安装生成一次并持久化，保证 URL 跨重启稳定（Chromium 缓存可命中）
- 首选端口持久化；被占用时本次退回随机端口
- 只提供缩略图；缩略图失败时回退原图；都没有则 404
"""
import hmac
import os
import random
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from utils.config import Config
from utils.logger import get_logger

logger = get_logger()

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CACHE_IMMUTABLE = "private, max-age=31536000, immutable"
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class _CoverHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _resolve(self) -> Tuple[str, str]:
        """返回 (game_id, 文件路径)；不合法返回空"""
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        # c / {token} / cover / {game_id}
        if len(parts) != 4 or parts[0] != "c" or parts[2] != "cover":
            return "", ""
        token = parts[1]
        server = self.server
        if not hmac.compare_digest(token, server.cover_token):  # type: ignore[attr-defined]
            return "", ""
        game_id = parts[3]
        if not _ID_RE.match(game_id):
            return "", ""
        store = server.cover_store  # type: ignore[attr-defined]
        path = store.ensure_thumb(game_id) or store.find_cover(game_id)
        return game_id, path

    def _send_file(self, path: str, with_body: bool) -> None:
        try:
            size = os.path.getsize(path)
            ext = os.path.splitext(path)[1].lower()
            ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", _CACHE_IMMUTABLE)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if with_body:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        _, path = self._resolve()
        if not path:
            self.send_error(404)
            return
        self._send_file(path, True)

    def do_HEAD(self):
        _, path = self._resolve()
        if not path:
            self.send_error(404)
            return
        self._send_file(path, False)


class CoverService:
    def __init__(self, store, token: Optional[str] = None,
                 port: Optional[int] = None, enabled: bool = True,
                 config: Optional[Config] = None):
        self.store = store
        self._cfg = config or Config()
        self._enabled = enabled
        self._token = token or ""
        self._preferred_port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0

    @property
    def started(self) -> bool:
        return self._server is not None

    def _load_config(self) -> None:
        data = self._cfg.get("cover_service") or {}
        changed = False
        if not self._token:
            token = str(data.get("token") or "")
            if not token:
                token = secrets.token_urlsafe(18)
                changed = True
            self._token = token
        if self._preferred_port is None:
            try:
                preferred = int(data.get("port") or 0)
            except (TypeError, ValueError):
                preferred = 0
            if not preferred:
                preferred = random.randint(40000, 60000)
                changed = True
            self._preferred_port = preferred
        if changed:
            try:
                payload = dict(data)
                payload["token"] = self._token
                payload["port"] = int(self._preferred_port or 0)
                self._cfg.set("cover_service", payload)
                self._cfg.save()
            except Exception as e:  # noqa: BLE001
                logger.warning("封面服务配置保存失败: %s", e)

    def start(self) -> bool:
        if not self._enabled:
            return False
        self._load_config()
        server = None
        for bind_port in (self._preferred_port, 0):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", int(bind_port or 0)), _CoverHandler)
                break
            except OSError as e:
                if bind_port:
                    logger.warning("封面服务端口 %s 不可用，改用随机端口: %s", bind_port, e)
        if server is None:
            logger.warning("封面服务启动失败，回退内嵌封面")
            return False
        server.daemon_threads = True
        server.cover_token = self._token  # type: ignore[attr-defined]
        server.cover_store = self.store  # type: ignore[attr-defined]
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True,
                                        name="cover-service")
        self._thread.start()
        logger.info("封面服务已启动: 127.0.0.1:%s", self.port)
        return True

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        self._thread = None

    def cover_url(self, game_id: str, version: str) -> str:
        if not self.started or not self._token:
            return ""
        return (f"http://127.0.0.1:{self.port}/c/{self._token}/cover/"
                f"{quote(str(game_id))}?v={quote(str(version))}")
