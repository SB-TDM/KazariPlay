"""Hook 实时翻译系统 —— 离线冒烟测试（V1.1）

覆盖（无需 pywebview / 无需 Textractor 二进制 / 不启动 GUI）：
1. 前端清单拼接（模拟 main.py _load_html）
2. DB hook_code/translate_enabled 字段往返（临时库）
3. GameLauncher 翻译接线（mock Popen/SubtitleCoordinator）
4. SubtitleCoordinator 队列保序（Fake 翻译器/客户端）

用法：
    python tests/smoke_translation.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kazari_play"))

_FAILED = []


def check(name: str, cond: bool, detail: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"{mark} | {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        _FAILED.append(name)


# ---------- 1. 前端清单 ----------
def test_frontend_manifests():
    assets = os.path.join(ROOT, "kazari_play", "ui", "web_assets")
    js = ["state.js", "core.js", "ui.js", "window.js", "games.js", "detail.js",
          "screenshots.js", "collections.js", "batch.js", "form.js",
          "hook_select.js", "settings.js", "app.js"]
    partials = ["common.html", "detail.html", "collections.html", "form.html",
                "settings.html", "hook_select.html"]
    missing = [f for f in js if not os.path.exists(os.path.join(assets, "js", f))]
    check("前端 JS 清单完整", not missing, str(missing))
    missing = [f for f in partials if not os.path.exists(os.path.join(assets, "partials", f))]
    check("前端 partials 清单完整", not missing, str(missing))
    html = open(os.path.join(assets, "index.html"), encoding="utf-8").read()
    parts = "\n".join(open(os.path.join(assets, "partials", n), encoding="utf-8").read()
                      for n in partials)
    scripts = "\n".join(
        f"<script>\n{open(os.path.join(assets,'js',n), encoding='utf-8').read()}\n</script>"
        for n in js)
    css = open(os.path.join(assets, "css", "style.css"), encoding="utf-8").read()
    out = (html.replace("<!-- PARTIALS -->", parts)
               .replace("<!-- SCRIPTS -->", scripts)
               .replace('<link rel="stylesheet" href="css/style.css">',
                        "<style>" + css + "</style>"))
    check("拼接后无残留占位符",
          "<!-- SCRIPTS -->" not in out and "<!-- PARTIALS -->" not in out)
    check("拼接后含 hook_select 弹窗", 'id="hookSelectOverlay"' in out)
    check("拼接后含翻译设置页", 'id="set-translate"' in out and "setTransTest" in out)
    check("拼接后含详情翻译开关", 'id="dlgTransRow"' in out)
    check("CSS 含 Hook 样式", ".hook-select" in css and ".trans-card" in css)
    bom = css.count("\ufeff")
    check("CSS 无中间 BOM", bom == 0 or (css.startswith("\ufeff") and bom == 1),
          f"BOM count={bom}")


# ---------- 2. DB 字段往返 ----------
def test_db_fields():
    from database.db_manager import DatabaseManager
    from database.game_repository import GameRepository
    from core.game_model import Game

    tmp = os.path.join(tempfile.gettempdir(), "kazari_test_translate.db")
    for f in (tmp, tmp + "-journal", tmp + "-wal"):
        if os.path.exists(f):
            os.remove(f)
    DatabaseManager._instance = None
    DatabaseManager(db_path=tmp)
    repo = GameRepository()
    g = Game(title="测试翻译", exe_path=os.path.join(ROOT, "_tmp_test_exe.exe"),
             folder=ROOT, engine="krkr", hook_code="kzh:4A5B6C:2:",
             translate_enabled=True)
    g.date_added = "2026-08-14T00:00:00"
    check("DB 写入游戏", repo.add(g))
    g2 = repo.get_by_path(g.exe_path)
    check("hook_code 读回", g2 is not None and g2.hook_code == "kzh:4A5B6C:2:",
          str(getattr(g2, "hook_code", None)))
    check("translate_enabled 读回", g2 is not None and g2.translate_enabled is True)
    repo.update_hook_code(g.id, "kzh:DEADBEEF:0:")
    check("update_hook_code 生效",
          repo.get_by_id(g.id).hook_code == "kzh:DEADBEEF:0:")
    repo.set_translate_enabled(g.id, False)
    check("set_translate_enabled 生效",
          repo.get_by_id(g.id).translate_enabled is False)
    for f in (tmp, tmp + "-journal", tmp + "-wal"):
        if os.path.exists(f):
            os.remove(f)
    DatabaseManager._instance = None


# ---------- 3. GameLauncher 翻译接线 ----------
def test_launcher_wiring():
    import core.subtitle_coordinator as sc_mod
    import core.game_launcher as gl_mod
    from core.game_launcher import GameLauncher
    from core.game_model import Game

    exe = os.path.join(tempfile.gettempdir(), "kazari_fake_game.exe")
    open(exe, "w").close()

    class FakeProc:
        pid = 4242
        def poll(self):
            return None
        def wait(self, t=0):
            pass
        def terminate(self):
            pass
        def kill(self):
            pass

    class FakeCoord:
        def __init__(self):
            self.started = None
            self.stopped = False
        def start_hook_session(self, **kw):
            self.started = kw
            return True
        def stop(self):
            self.stopped = True

    orig_coord, orig_popen = sc_mod.SubtitleCoordinator, gl_mod.subprocess.Popen
    try:
        fake = FakeCoord()
        sc_mod.SubtitleCoordinator = lambda: fake
        gl_mod.subprocess.Popen = lambda *a, **k: FakeProc()
        launcher = GameLauncher()
        g = Game(title="T", exe_path=exe, folder=os.path.dirname(exe),
                 engine="krkr", hook_code="kzh:ABC:0:", translate_enabled=True)
        check("launch 返回 True", launcher.launch(g))
        check("launch 传 hook_code/engine",
              fake.started is not None and fake.started["hook_code"] == "kzh:ABC:0:"
              and fake.started["engine"] == "krkr", str(fake.started))
        launcher.close()
        check("close 停止翻译", fake.stopped)

        fake2 = FakeCoord()
        sc_mod.SubtitleCoordinator = lambda: fake2
        launcher2 = GameLauncher()
        g2 = Game(title="U", exe_path=exe, folder=os.path.dirname(exe),
                  engine="unity", translate_enabled=False)
        launcher2.launch(g2)
        check("未启用翻译不启动", fake2.started is None)
        launcher2.close()
        check("is_x64 兜底 True", launcher._is_process_x64(4242) is True)
    finally:
        sc_mod.SubtitleCoordinator = orig_coord
        gl_mod.subprocess.Popen = orig_popen
        if os.path.exists(exe):
            os.remove(exe)


# ---------- 4. SubtitleCoordinator 会话控制（翻译在 C++，Python 只传配置/状态） ----------
def test_coordinator_session():
    from core.subtitle_coordinator import SubtitleCoordinator

    class FakeOverlay:
        def __init__(self):
            self.start_kw = None
            self.select = None
        def ensure_bidirectional(self):
            return True
        def send_start_hook(self, **kw):
            self.start_kw = kw
            return True
        def send_stop_hook(self):
            return True
        def send_hide_subtitle(self):
            return True
        def send_select_hook(self, h, hook_code=""):
            self.select = (h, hook_code)

    sc = SubtitleCoordinator()
    sc._overlay = FakeOverlay()
    ai = {"base_url": "https://api.deepseek.com", "api_key": "k",
          "model": "m", "source_lang": "ja", "target_lang": "zh"}
    ok = sc.start_hook_session(123, True, hook_code="kzh:1234:0:", engine="krkr",
                               ai_config=ai)
    check("start_hook_session 返回 True", ok)
    check("AI 配置透传", sc._overlay.start_kw.get("ai_config") == ai,
          str(sc._overlay.start_kw.get("ai_config")))
    check("首次配置等待选择", sc._awaiting_selection is False)
    sc.select_hook(100, "kzh:1234:0:")
    check("select_hook 已发送", sc._overlay.select == (100, "kzh:1234:0:"))
    sc.stop()
    check("stop 后 running=False", sc._running is False)


def main():
    test_frontend_manifests()
    test_db_fields()
    test_launcher_wiring()
    test_coordinator_session()
    print("OVERALL:", "ALL PASS" if not _FAILED else f"FAILED: {_FAILED}")
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
