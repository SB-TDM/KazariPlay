"""WinHost 管道帧与结果分片协议。

本模块只处理长度前缀、JSON 和逻辑结果分片，不依赖窗口、网络或 WebBridge。
协议版本、消息字段和等待者匹配由 transport 层校验。
"""
from __future__ import annotations

import base64
import json
import struct
from typing import Any


MAX_FRAME = 8 * 1024 * 1024
MAX_RESULT_BYTES = 128 * 1024 * 1024
RESULT_CHUNK_BYTES = 256 * 1024


class ProtocolError(Exception):
    """帧格式、JSON 或结果大小不符合协议。"""


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _json_bytes(obj: Any) -> bytes:
    try:
        text = json.dumps(
            obj,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"JSON encode failed: {exc}") from exc
    return text.encode("utf-8")


def encode_frame(obj: dict) -> bytes:
    """把 JSON 对象编码为一个长度前缀帧。"""
    if not isinstance(obj, dict):
        raise ProtocolError("frame must be an object")
    body = _json_bytes(obj)
    if len(body) > MAX_FRAME:
        raise ProtocolError("frame too large")
    return struct.pack("<I", len(body)) + body


def decode_frame(buf: bytearray) -> dict | None:
    """从缓冲中取出一个完整帧；不足一帧时不消耗缓冲。"""
    if len(buf) < 4:
        return None
    size = struct.unpack_from("<I", buf, 0)[0]
    if size == 0:
        raise ProtocolError("empty frame")
    if size > MAX_FRAME:
        raise ProtocolError("frame too large")
    if len(buf) < 4 + size:
        return None
    body = bytes(buf[4:4 + size])
    del buf[:4 + size]
    try:
        msg = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ProtocolError(f"invalid frame JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("frame must be an object")
    return msg


def build_result_messages(message: dict) -> list[dict]:
    """把逻辑 result 转换为一个普通 result 或一组 result_chunk 消息。"""
    if not isinstance(message, dict) or message.get("type") != "result":
        raise ProtocolError("result message required")
    if not isinstance(message.get("id"), int) or isinstance(message.get("id"), bool):
        raise ProtocolError("result id must be an integer")
    body = _json_bytes(message)
    if len(body) > MAX_RESULT_BYTES:
        raise ProtocolError("result too large")
    if len(body) <= MAX_FRAME:
        return [message]

    count = (len(body) + RESULT_CHUNK_BYTES - 1) // RESULT_CHUNK_BYTES
    messages = []
    for index in range(count):
        start = index * RESULT_CHUNK_BYTES
        chunk = body[start:start + RESULT_CHUNK_BYTES]
        messages.append({
            "type": "result_chunk",
            "id": message["id"],
            "index": index,
            "count": count,
            "total_bytes": len(body),
            "data": base64.b64encode(chunk).decode("ascii"),
        })
    return messages


def build_result_frames(message: dict) -> list[bytes]:
    """编码逻辑 result；超过单帧上限时拆为 result_chunk。"""
    return [encode_frame(item) for item in build_result_messages(message)]
