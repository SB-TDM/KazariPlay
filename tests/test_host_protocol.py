"""WinHost 帧编解码与结果分片的离线回归。"""
import base64
import json
import os
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "kazari_play"))

import host_protocol  # noqa: E402
from host_protocol import (  # noqa: E402
    MAX_FRAME,
    ProtocolError,
    build_result_frames,
    decode_frame,
    encode_frame,
)


def frame_from_body(body: bytes) -> bytearray:
    return bytearray(struct.pack("<I", len(body)) + body)


class HostProtocolTests(unittest.TestCase):
    def test_roundtrip_call(self):
        message = {"type": "call", "id": 1, "method": "getGames", "args": []}
        buf = bytearray(encode_frame(message))
        self.assertEqual(decode_frame(buf), message)
        self.assertEqual(buf, bytearray())

    def test_golden_ready_frame(self):
        self.assertEqual(
            encode_frame({"type": "ready"}),
            bytes.fromhex("100000007b2274797065223a227265616479227d"),
        )

    def test_partial_prefix_and_body_wait_without_consuming(self):
        raw = encode_frame({"type": "ready", "value": "中文"})
        for cut in (1, 3, 4, len(raw) - 1):
            buf = bytearray(raw[:cut])
            self.assertIsNone(decode_frame(buf))
            self.assertEqual(bytes(buf), raw[:cut])

    def test_two_frames_in_one_buffer(self):
        buf = bytearray(
            encode_frame({"type": "ready"})
            + encode_frame({"type": "shutdown", "reason": "test"})
        )
        self.assertEqual(decode_frame(buf), {"type": "ready"})
        self.assertEqual(decode_frame(buf), {"type": "shutdown", "reason": "test"})
        self.assertEqual(buf, bytearray())

    def test_unicode_and_emoji_roundtrip(self):
        message = {"type": "toast", "text": "你好 🎮"}
        self.assertEqual(decode_frame(bytearray(encode_frame(message))), message)

    def test_rejects_oversize_prefix_and_body(self):
        with self.assertRaises(ProtocolError):
            decode_frame(bytearray((MAX_FRAME + 1).to_bytes(4, "little")))
        with self.assertRaises(ProtocolError):
            encode_frame({"type": "x", "data": "a" * MAX_FRAME})

    def test_rejects_zero_length_invalid_json_and_non_object(self):
        for body in (b"", b"{", b"[]", b"null"):
            with self.subTest(body=body):
                with self.assertRaises(ProtocolError):
                    decode_frame(frame_from_body(body))

    def test_rejects_invalid_utf8_and_non_finite_numbers(self):
        with self.assertRaises(ProtocolError):
            decode_frame(frame_from_body(b"\xff"))
        with self.assertRaises(ProtocolError):
            decode_frame(frame_from_body(b'{"type":"x","value":NaN}'))
        with self.assertRaises(ProtocolError):
            encode_frame({"type": "x", "value": float("nan")})

    def test_non_object_encode_rejected(self):
        for value in ([], "x", 1, None):
            with self.assertRaises(ProtocolError):
                encode_frame(value)

    def test_small_result_uses_single_result_frame(self):
        message = {"type": "result", "id": 3, "ok": True, "result": "[]"}
        frames = build_result_frames(message)
        self.assertEqual(len(frames), 1)
        self.assertEqual(decode_frame(bytearray(frames[0])), message)

    def test_large_result_chunks_and_reassembles(self):
        message = {"type": "result", "id": 7, "ok": True, "result": "汉" * 3000000}
        frames = build_result_frames(message)
        self.assertGreater(len(frames), 1)
        chunks = []
        for frame in frames:
            wrapper = decode_frame(bytearray(frame))
            self.assertEqual(wrapper["type"], "result_chunk")
            self.assertLessEqual(len(frame) - 4, MAX_FRAME)
            chunks.append(base64.b64decode(wrapper["data"]))
        self.assertEqual(json.loads(b"".join(chunks).decode("utf-8")), message)

    def test_result_size_limit(self):
        message = {"type": "result", "id": 1, "ok": True, "result": "x" * 100}
        with patch.object(host_protocol, "MAX_RESULT_BYTES", 10):
            with self.assertRaises(ProtocolError):
                build_result_frames(message)

    def test_result_requires_integer_id(self):
        with self.assertRaises(ProtocolError):
            build_result_frames({"type": "result", "id": True, "ok": True})
        with self.assertRaises(ProtocolError):
            build_result_frames({"type": "call", "id": 1})


if __name__ == "__main__":
    unittest.main()
