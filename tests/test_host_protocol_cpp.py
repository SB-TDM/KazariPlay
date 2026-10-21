"""Python 与 C++ 帧编解码的跨语言互操作回归。"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "kazari_play"))

from host_protocol import decode_frame, encode_frame  # noqa: E402

EXE = os.path.join(ROOT, "host", "build", "bin", "host_protocol_test.exe")


@unittest.skipUnless(os.path.isfile(EXE), "build host_protocol_test first")
class HostProtocolCrossLanguageTests(unittest.TestCase):
    def run_cpp(self, *args):
        proc = subprocess.run(
            [EXE, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_cpp_encodes_python_decodes(self):
        message = {"type": "call", "id": 9, "method": "getGames", "args": []}
        cpp_hex = self.run_cpp("--encode", json.dumps(message, separators=(",", ":")))
        self.assertEqual(decode_frame(bytearray(bytes.fromhex(cpp_hex))), message)

    def test_python_encodes_cpp_decodes(self):
        message = {"type": "result", "id": 4, "ok": True, "result": "cross-language"}
        frame_hex = encode_frame(message).hex()
        self.assertEqual(json.loads(self.run_cpp("--decode", frame_hex)), message)


if __name__ == "__main__":
    unittest.main()
