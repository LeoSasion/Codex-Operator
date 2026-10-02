from pathlib import Path
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

import asyncio
from copy import deepcopy
import threading
import tempfile
import os
import unittest
from unittest.mock import patch
from operator_core import web_native_interruption as subject

THREAD = '11111111-1111-4111-8111-111111111111'
TURN = '22222222-2222-4222-8222-222222222222'


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-metadata-home-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.closed = False
        self.calls = []
        self.thread = {'thread': {'id': THREAD, 'turns': []}}
        self.rows = {'data': [{'id': TURN, 'status': 'interrupted',
            'completedAt': 12, 'items': [], 'itemsView': 'notLoaded'}]}
        owner = self
        class Session:
            def __init__(self, path, timeout, **kwargs):
                owner.calls.append(('start', str(path), timeout, kwargs))
            def initialize(self):
                owner.calls.append(('initialize',))
            def request(self, method, params):
                owner.calls.append((method, params))
                return deepcopy(owner.thread if method == 'thread/read' else owner.rows)
            def close(self):
                owner.closed = True
        self.factory = Session

    def read(self, identity=(THREAD, TURN)):
        return subject.read_interruption(identity, executable=Path('codex.exe'),
            session_factory=self.factory, codex_home=self.home)

    def test_exact_home_is_passed_only_to_native_metadata_child(self):
        from operator_core.web_browser_driver import child_environment
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home)}):
            self.assertNotIn('CODEX_HOME', child_environment())
            self.assertIs(self.read(), True)
        self.assertEqual(self.calls[0][3], {'codex_home': self.home})

    def test_invalid_home_never_launches_metadata_child(self):
        for home in (Path('relative-home'), self.home / 'missing'):
            self.assertIsNone(subject.read_interruption((THREAD, TURN), executable=Path('codex.exe'),
                session_factory=self.factory, codex_home=home))
        self.assertEqual(self.calls, [])

    def test_exact_completed_interruption_reads_only_bounded_metadata_and_closes(self):
        self.assertIs(self.read(), True)
        self.assertTrue(self.closed)
        self.assertEqual([call[0] for call in self.calls],
            ['start', 'initialize', 'thread/read', 'thread/turns/list'])
        self.assertEqual(self.calls[-2][1], {'threadId': THREAD, 'includeTurns': False})
        self.assertEqual(self.calls[-1][1], {'threadId': THREAD, 'limit': 20,
            'sortDirection': 'desc', 'itemsView': 'notLoaded'})

    def test_ordinary_terminal_and_transient_interruption_are_not_cancellation(self):
        for status, ended in [('inProgress', None), ('completed', 12), ('failed', 12),
                ('interrupted', None), ('interrupted', True), ('interrupted', 0)]:
            self.rows['data'][0].update(status=status, completedAt=ended)
            self.assertIs(self.read(), False)

    def test_unknown_mismatch_duplicate_content_and_bounds_never_confirm(self):
        original = deepcopy(self.rows)
        for change in [[], original['data'] * 2, original['data'] * 21,
                [{**original['data'][0], 'id': THREAD}],
                [{**original['data'][0], 'items': [{'text': 'private'}]}],
                [{**original['data'][0], 'itemsView': 'loaded'}],
                [{**original['data'][0], 'status': 'unknown'}]]:
            self.rows = {'data': change}
            self.assertIsNone(self.read())
        self.rows = original
        self.thread = {'thread': {'id': TURN, 'turns': []}}
        self.assertIsNone(self.read())
        self.thread = {'thread': {'id': THREAD, 'turns': [{'private': 'content'}]}}
        self.assertIsNone(self.read())

    def test_synthetic_identity_does_not_launch_a_native_process(self):
        for value in [('fixture', TURN), (THREAD,), [THREAD, TURN], (True, TURN)]:
            self.assertIsNone(self.read(value))
        self.assertEqual(self.calls, [])

    def test_transport_error_closes_without_restarting(self):
        with patch.object(self.factory, 'request', side_effect=RuntimeError('private error')):
            self.assertIsNone(self.read())
        self.assertTrue(self.closed)
        self.assertEqual(sum(call[0] == 'start' for call in self.calls), 1)


class AsyncMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_cancellation_waits_for_readonly_child_cleanup(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        def read(_, **kwargs):
            self.assertEqual(kwargs, {'codex_home': None})
            started.set()
            try:
                release.wait(2)
                return False
            finally:
                closed.set()
        with patch.object(subject, 'read_interruption', side_effect=read):
            work = asyncio.create_task(subject.observe_interruption((THREAD, TURN)))
            try:
                await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 2)
                work.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(work.done())
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await work
                self.assertTrue(closed.is_set())
            finally:
                release.set()
                await asyncio.gather(work, return_exceptions=True)
