"""P1 截图、身份、重新定位与任务隔离回归。"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_p0_data_flow as base
from core import screenshot_service as shots
from utils.title_utils import normalize_title


class ReliabilityTests(base.DataFlowTests):
    def test_same_timestamp_concurrent_screenshots_do_not_overwrite(self):
        from PIL import Image, ImageGrab
        image = Image.new("RGB", (48, 32), "red")
        fixed = SimpleNamespace(now=lambda: datetime(2026, 10, 5, 12, 0, 0, 123456))
        with patch.object(shots, 'datetime', fixed), \
             patch.object(shots, 'get_game_screenshots_dir', return_value=str(self.root)), \
             patch.object(shots, '_thumb_canvas_size', return_value=(24, 16)), \
             patch.object(ImageGrab, 'grab', side_effect=lambda: image.copy()):
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = list(pool.map(lambda _: shots.take_screenshot('fixture'), range(8)))
        self.assertEqual(len(set(paths)), 8)
        for p in paths:
            self.assertTrue(Path(p).is_file())
            self.assertTrue(Path(shots._screenshot_thumb_path(p)).is_file())
            self.assertEqual(shots._extract_time(Path(p).name), '2026-10-05 12:00')
        self.assertEqual(shots._extract_time('shot_20260811_201530.png'), '2026-08-11 20:15')

    def test_identity_preserves_chapters_subtitles_and_unknown_suffix(self):
        self.assertEqual(normalize_title('Series Chapter 1'), 'Series')
        names = ('Series Chapter 1', 'Series Chapter 2', 'Series～After～', 'Series～Before～',
                 'Series_Part1', 'Series_Part2')
        identities = [self.manager.scanner._make_identity('rpg_maker', n) for n in names]
        self.assertEqual(len(set(identities)), len(names))
        self.assertEqual(self.manager.scanner._make_identity('rpg_maker', '[studio]Series_测试汉化组'),
                         self.manager.scanner._make_identity('rpg_maker', 'Series_官方中文'))
        for name in names[:2]:
            folder = self.root / name
            folder.mkdir()
            (folder / 'game.exe').write_bytes(b'fixture')
        self.assertEqual(self.manager.scan_and_add(str(self.root))[0], 2)

    def test_identity_backfill_uses_folder_name(self):
        game = self.fixture('Series Chapter 1')
        # 篡改 identity 后 _backfill_identity 应按文件夹名重算回正确值
        self.manager.repository.db.execute(
            'UPDATE games SET identity=? WHERE id=?', ('rpg_maker|bogus', game.id))
        self.manager._backfill_identity()
        expect = self.manager.scanner._make_identity(game.engine, 'Series Chapter 1')
        self.assertEqual(self.manager.get_game(game.id).identity, expect)

    def test_relocation_preview_reports_multiple_candidates(self):
        game = self.fixture()
        self.bridge._window = SimpleNamespace(create_file_dialog=lambda *a: [str(self.root)])
        candidates = [SimpleNamespace(identity=game.identity, exe_path=str(self.root / n)) for n in ('a.exe', 'b.exe')]
        with patch.object(self.manager.scanner, 'scan', return_value=candidates):
            response = json.loads(self.bridge.previewRelocate(json.dumps([game.id])))
        self.assertEqual(response['items'][0]['status'], 'conflict')
        self.assertEqual(response['items'][0]['new_exe'], '')

    def test_relocation_moves_internal_override_and_preserves_other_fields(self):
        game = self.fixture()
        new = self.root / 'Moved'
        new.mkdir()
        (new / 'game.exe').write_bytes(b'fixture')
        (new / 'custom.exe').write_bytes(b'fixture')
        response = json.loads(self.bridge.applyRelocate(json.dumps([{'id': game.id, 'new_exe': str(new / 'game.exe')}])))
        self.assertTrue(response['ok'])
        current = self.manager.get_game(game.id)
        self.assertEqual(current.launch_exe_path, str(new / 'custom.exe'))
        for field in ('vndb_id', 'hook_code', 'translate_enabled', 'play_time', 'is_favorite'):
            self.assertEqual(getattr(current, field), getattr(game, field))

    def test_relocation_external_override_and_write_failure(self):
        game = self.fixture()
        external = self.root / 'external.exe'
        external.write_bytes(b'fixture')
        game.launch_exe_path = str(external)
        self.manager.repository.update_game(game)
        target = self.root / 'Moved'
        target.mkdir()
        exe = target / 'game.exe'
        exe.write_bytes(b'fixture')
        with patch.object(self.manager.repository, 'update_game', return_value=False):
            response = json.loads(self.bridge.applyRelocate(json.dumps([{'id': game.id, 'new_exe': str(exe)}])))
        self.assertEqual(response['updated'], 0)
        self.assertFalse(response['ok'])
        self.assertEqual(self.manager.get_game(game.id).exe_path, game.exe_path)
        response = json.loads(self.bridge.applyRelocate(json.dumps([{'id': game.id, 'new_exe': str(exe)}])))
        self.assertTrue(response['ok'])
        self.assertEqual(self.manager.get_game(game.id).launch_exe_path, str(external))

    def test_relocation_missing_override_leaves_old_path(self):
        game = self.fixture()
        exe = self.root / 'Moved' / 'game.exe'
        exe.parent.mkdir()
        exe.write_bytes(b'fixture')
        response = json.loads(self.bridge.applyRelocate(json.dumps([{'id': game.id, 'new_exe': str(exe)}])))
        self.assertFalse(response['ok'])
        self.assertEqual(response['updated'], 0)
        self.assertEqual(self.manager.get_game(game.id).exe_path, game.exe_path)

    def test_task_rejection_does_not_reset_cancel_and_retry_gets_new_event(self):
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(3)
        self.assertTrue(self.bridge._start_task(work))
        self.assertTrue(entered.wait(3))
        event = self.bridge._vndb_cancel
        self.bridge.cancelMatch()
        self.assertFalse(self.bridge._start_task(lambda: None))
        self.assertIs(self.bridge._vndb_cancel, event)
        self.assertTrue(event.is_set())
        release.set()
        self.bridge._task_thread.join(3)
        self.assertTrue(self.bridge._start_task(lambda: None))
        self.bridge._task_thread.join(3)
        self.assertIsNot(event, self.bridge._vndb_cancel)
        self.assertFalse(self.bridge._vndb_cancel.is_set())

    def test_task_exception_releases_gate(self):
        def fail():
            raise RuntimeError('fixture error')
        self.assertTrue(self.bridge._start_task(fail))
        self.bridge._task_thread.join(3)
        self.assertTrue(self.bridge._start_task(lambda: None))
        self.bridge._task_thread.join(3)


if __name__ == '__main__':
    unittest.main()
