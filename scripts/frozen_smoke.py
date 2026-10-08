"""Explicit, offline verification inside the real frozen WebView window."""
import json
import os
import sys
import threading
import time
from pathlib import Path


def install():
    if not os.environ.get("KAZARIPLAY_SMOKE_REPORT", "").strip() or not os.environ.get("KAZARIPLAY_DATA_DIR", "").strip():
        raise RuntimeError("--smoke-test requires KAZARIPLAY_SMOKE_REPORT and an isolated data directory")
    data_dir = Path(os.environ["KAZARIPLAY_DATA_DIR"])
    if data_dir.exists():
        raise RuntimeError("--smoke-test requires a new data directory")
    import webview
    original_create = webview.create_window

    def create(*args, **kwargs):
        window = original_create(*args, **kwargs)
        bridge = kwargs["js_api"]
        bridge._run_vndb_match = lambda *a: None

        def check():
            report = {"ok": False, "checks": [], "bundle": str(getattr(sys, "_MEIPASS", ""))}
            try:
                from version import VERSION, WINDOW_TITLE
                from core import screenshot_service
                report["version"] = VERSION
                report["config"] = bridge._cfg.path

                def wait(expression):
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if window.evaluate_js(expression):
                            return
                        time.sleep(.1)
                    raise AssertionError(expression)

                wait("Boolean(window.pywebview && pywebview.api && window.Settings)")
                assert window.evaluate_js("document.title") == WINDOW_TITLE
                assert window.evaluate_js("typeof pywebview.api.testTranslation") == "undefined"
                assert not hasattr(bridge, "testTranslation")
                window.evaluate_js("Settings.open(); document.querySelector('#setNav [data-tab=about]').click();")
                wait("document.querySelector('#set-about').style.display==='block'")
                assert VERSION in window.evaluate_js("document.querySelector('.a-ver').textContent")
                report["checks"].append("frozen WebView bridge, version, about, no translation")

                fixture = Path(os.environ["KAZARIPLAY_DATA_DIR"]) / "fixture" / "game.exe"
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.write_bytes(b"offline-fixture")
                window.evaluate_js("Settings.close(); openAdd(); document.getElementById('fExe').value=" + json.dumps(str(fixture)) + "; saveForm();")
                wait("App.data.games.length===1")
                game = bridge.manager.get_all_games()[0]
                window.evaluate_js("openEdit(App.data.games[0]); document.getElementById('fTitle').value='Frozen package edit'; saveForm();")
                wait("App.data.games[0].title==='Frozen package edit'")
                report["checks"].append("frozen UI add/edit and SQLite persistence")

                game_exe = os.environ.get("KAZARIPLAY_SMOKE_GAME", "")
                if game_exe:
                    game.exe_path = game_exe
                    game.folder = str(Path(game_exe).parent)
                    assert bridge.manager.update_game(game)
                    assert json.loads(bridge.launch(game.id))["ok"]
                    process = bridge.manager.launcher.current_process
                    assert bridge.manager.launcher.wait_for_game_pid() == process.pid
                    assert screenshot_service.find_main_window_by_pid(process.pid)
                    assert bridge.manager.close_game()
                    assert process.poll() is not None
                    report["checks"].append("frozen controlled game launch/window/monitor/close")

                image = screenshot_service._capture_via_wgc(os.getpid())
                assert image is not None, "Frozen WGC capture failed"
                assert image.width > 100 and image.height > 100
                capture = Path(os.environ["KAZARIPLAY_SMOKE_REPORT"]).with_suffix(".png")
                image.save(capture)
                report["capture_size"] = list(image.size)
                shot = json.loads(bridge.takeScreenshot(game.id))
                assert shot["ok"]
                assert Path(shot["path"]).is_relative_to(Path(os.environ["KAZARIPLAY_DATA_DIR"]))
                assert bridge.getScreenshotThumb(game.id, Path(shot["path"]).name).startswith("data:image/")
                assert bridge.renameScreenshot(game.id, Path(shot["path"]).name, "frozen-test")
                assert bridge.deleteScreenshot(game.id, "frozen-test.png")
                report["checks"].append("frozen WGC/Pillow capture, thumbnail, rename/delete, isolated paths")

                client = bridge._get_overlay_client()
                for arch in (True, False):
                    exe = client._resolve_exe(arch)
                    assert Path(exe).is_relative_to(Path(sys._MEIPASS)), exe
                    assert client.ensure_bidirectional(arch), "Frozen Overlay connection failed"
                    process = client._proc
                    assert client.hide()
                    assert client.quit()
                    assert process.wait(timeout=5) == 0
                report["checks"].append("bundled x64/x86 Overlay pipes and zero exit")
                bridge.deleteGame(game.id)
                wait("App.data.games.length===0")
                assert bridge.manager.get_count() == 0
                report["checks"].append("frozen UI delete")
                report["ok"] = True
            except Exception as exc:
                import traceback
                report["error"] = str(exc)
                report["traceback"] = traceback.format_exc()
            finally:
                Path(os.environ["KAZARIPLAY_SMOKE_REPORT"]).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                try:
                    bridge.manager.close_game()
                    bridge._get_overlay_client().quit()
                finally:
                    window.destroy()

        window.events.loaded += lambda: threading.Thread(target=check, daemon=True).start()
        watchdog = threading.Timer(60, window.destroy)
        watchdog.daemon = True
        watchdog.start()
        window.events.closed += watchdog.cancel
        return window

    webview.create_window = create
