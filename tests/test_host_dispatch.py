"""WinHost dispatch allowlist 与错误边界回归。"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kazari_play"))

from ui.host_dispatch import (  # noqa: E402
    HOST_DISPATCH_METHODS,
    HOST_INTERNAL_METHODS,
    HOST_LOCAL_METHODS,
    DispatchError,
    dispatch,
)


class FakeApi:
    def getGames(self):
        return '[{"id":"1"}]'

    def saveConfigs(self, data_json):
        return data_json

    def fail(self):
        raise RuntimeError("boom")


class HostDispatchTests(unittest.TestCase):
    def test_public_business_method(self):
        self.assertEqual(dispatch(FakeApi(), "getGames", []), '[{"id":"1"}]')
        self.assertEqual(dispatch(FakeApi(), "saveConfigs", ["{}"]), "{}")

    def test_rejects_private_missing_internal_and_window_methods(self):
        for method in ("_secret", "missing", "cleanup_unused_covers", "windowClose"):
            with self.subTest(method=method):
                with self.assertRaises(DispatchError) as caught:
                    dispatch(FakeApi(), method, [])
                self.assertEqual(caught.exception.code, "unknown_method"
                                 if method != "windowClose" else "unsupported_window_method")

    def test_rejects_bad_args_and_method_exception(self):
        with self.assertRaises(DispatchError) as caught:
            dispatch(FakeApi(), "saveConfigs", [])
        self.assertEqual(caught.exception.code, "invalid_args")

        with self.assertRaises(DispatchError) as caught:
            dispatch(FakeApi(), "saveConfigs", "{}")
        self.assertEqual(caught.exception.code, "invalid_args")

        class FailingApi:
            def getGames(self):
                raise RuntimeError("boom")

        with self.assertRaises(DispatchError) as caught:
            dispatch(FailingApi(), "getGames", [])
        self.assertEqual(caught.exception.code, "method_failed")
        self.assertIn("RuntimeError", str(caught.exception))

    def test_rejects_non_callable_business_name(self):
        class NotCallable:
            getGames = 1

        with self.assertRaises(DispatchError) as caught:
            dispatch(NotCallable(), "getGames", [])
        self.assertEqual(caught.exception.code, "unknown_method")

    def test_allowlist_covers_frontend_bridge_calls(self):
        assets = ROOT / "src" / "kazari_play" / "ui" / "web_assets"
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in list((assets / "ts").glob("*.ts")) + [assets / "index.html"]
        )
        called = set(re.findall(r"bridge\.([A-Za-z_][A-Za-z0-9_]*)", text))
        called -= {"py", "xxx"}
        business_calls = called - HOST_LOCAL_METHODS
        self.assertTrue(business_calls, "no frontend bridge calls found")
        missing = business_calls - HOST_DISPATCH_METHODS
        self.assertFalse(missing, f"frontend calls missing from allowlist: {sorted(missing)}")

    def test_allowlist_sets_are_disjoint_and_explicit(self):
        self.assertFalse(HOST_DISPATCH_METHODS & HOST_LOCAL_METHODS)
        self.assertFalse(HOST_DISPATCH_METHODS & HOST_INTERNAL_METHODS)
        self.assertFalse(any(name.startswith("_") for name in HOST_DISPATCH_METHODS))
        self.assertIn("windowMaximize", HOST_LOCAL_METHODS)
        self.assertIn("windowRestore", HOST_LOCAL_METHODS)

    def test_allowlist_names_exist_on_web_bridge(self):
        source = (ROOT / "src" / "kazari_play" / "ui" / "web_bridge.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        bridge = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "WebBridge"
        )
        methods = {
            node.name for node in bridge.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(HOST_DISPATCH_METHODS - methods)
        self.assertFalse(HOST_LOCAL_METHODS - methods)


if __name__ == "__main__":
    unittest.main()
