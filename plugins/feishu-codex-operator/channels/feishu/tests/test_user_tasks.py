from __future__ import annotations

from pathlib import Path
import sys
PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'scripts'))

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operator_core.state import SessionStore
from operator_core.user_tasks import (
    DATABASE_NAME, PROFILE_NAME, RECEIPT_DIR, UserTaskError, UserTaskManager,
    UserTaskStore, configure, read_profile, revoke, setup_program, verify_native_task,
)

PROJECT = '11111111-1111-4111-8111-111111111111'
CREATED = '22222222-2222-4222-8222-222222222222'
MANUAL = '33333333-3333-4333-8333-333333333333'
BEEPER = '44444444-4444-4444-8444-444444444444'


class UserTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='operator-user-task-')
        self.root = Path(self.tmp.name)
        self.runtime = self.root / 'runtime'
        self.project = self.root / 'project with spaces'
        self.runtime.mkdir()
        self.project.mkdir()
        self.grant = dict(status='granted', project_registered=True, allow_fixed_relay_task=True,
            allow_create_project=True, allow_create_user_tasks=True, allow_reuse_user_tasks=True,
            scope='authorized_private_users', channel='Feishu', app_id='cli_synthetic',
            bot_open_id='ou_bot', project_id=PROJECT, project_path=str(self.project),
            granted_at='2026-09-21T00:00:00+00:00', grant_source_thread_id=BEEPER,
            fixed_relay_creation={'status': 'created', 'thread_id': BEEPER})
        self.config = SimpleNamespace(runtime_dir=self.runtime, beeper_thread_id=BEEPER, app_server_timeout_seconds=5)
        self.sessions = SessionStore(self.runtime / 'sessions.json')
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.tmp.cleanup()

    def enable(self):
        configure(self.runtime, self.grant, executable=Path('unused'))
        return read_profile(self.runtime)

    def session(self, user='ou_one', name='同名用户', scope='p2p:one'):
        return self.sessions.update(scope, dict(chat_type='p2p', user_open_id=user, name=name))

    def manager(self, queue, verifier=lambda *args, **kwargs: None):
        relay = SimpleNamespace(queue_user_task_setup=queue, codex_executable=Path('unused'))
        manager = UserTaskManager(self.config, self.sessions, relay, verifier=verifier)
        self.managers.append(manager)
        return manager

    def receipt(self, request_id, thread_id=CREATED):
        store = UserTaskStore(self.runtime)
        self.assertIsNotNone(store.take(request_id))
        path = self.project / RECEIPT_DIR / (request_id + '.json')
        path.write_text(json.dumps(dict(request_id=request_id, thread_id=thread_id, host_id='local')), encoding='utf-8')

    def test_grants_are_independent_and_disabled_default_has_no_effect(self):
        calls = []
        manager = self.manager(calls.append)
        self.assertIsNone(manager.begin('p2p:one', self.session(), 'ou_bot'))
        self.assertFalse((self.runtime / DATABASE_NAME).exists())
        self.grant['allow_create_user_tasks'] = False
        with self.assertRaises(UserTaskError):
            self.enable()
        self.assertFalse((self.project / RECEIPT_DIR).exists())
        self.assertEqual(calls, [])

    def test_oversized_grant_is_rejected_before_creating_registration_state(self):
        self.grant['grant_source_thread_id'] = 'x' * 16_384
        with self.assertRaisesRegex(UserTaskError, 'user_task_record_too_large'):
            self.enable()
        self.assertFalse((self.runtime / PROFILE_NAME).exists())
        self.assertFalse((self.runtime / DATABASE_NAME).exists())
        self.assertFalse((self.project / RECEIPT_DIR).exists())

    def test_stopped_configuration_and_unknown_existing_grant_are_preserved(self):
        (self.runtime / 'operator.pid').write_text('123')
        with self.assertRaises(UserTaskError):
            self.enable()
        (self.runtime / 'operator.pid').unlink()
        self.enable()
        before = (self.runtime / PROFILE_NAME).read_bytes()
        self.assertTrue(configure(self.runtime, self.grant, executable=Path('unused'))['reused'])
        self.grant['project_id'] = MANUAL
        with self.assertRaises(UserTaskError):
            configure(self.runtime, self.grant, executable=Path('unused'))
        self.assertEqual(before, (self.runtime / PROFILE_NAME).read_bytes())

    def test_same_names_and_renames_use_scoped_identity(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        first, fresh = store.reserve(profile, digest, 'ou_one', '同名', 'p2p:one')
        renamed, again = store.reserve(profile, digest, 'ou_one', '新名字', 'p2p:one')
        other, distinct = store.reserve(profile, digest, 'ou_two', '同名', 'p2p:two')
        self.assertTrue(fresh and distinct)
        self.assertFalse(again)
        self.assertEqual(first['request_id'], renamed['request_id'])
        self.assertNotEqual(first['request_id'], other['request_id'])

    def test_owner_reviewed_existing_binding_is_recorded_without_rebinding_or_list_inference(self):
        self.session()
        self.sessions.bind_thread('p2p:one', CREATED, {'host_id': 'local'})
        before = (self.runtime / 'sessions.json').read_bytes()
        self.grant['initial_user_creation'] = dict(status='bound', user_open_id='ou_one',
            scope='p2p:one', display_name='名字', thread_id=CREATED)
        calls = []
        class API:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def request(api, method, args):
                calls.append((method, args))
                return {'thread': {'id': CREATED, 'cwd': str(self.project), 'turns': []}}
        with patch('operator_core.user_tasks.AppServerSession', API):
            self.enable()
        self.assertEqual([method for method, _ in calls], ['thread/read'])
        self.assertIs(calls[0][1]['includeTurns'], False)
        self.assertEqual(before, (self.runtime / 'sessions.json').read_bytes())
        profile, digest = read_profile(self.runtime)
        job, fresh = UserTaskStore(self.runtime).reserve(profile, digest, 'ou_one', '新名字', 'p2p:one')
        self.assertFalse(fresh)
        self.assertEqual(job['thread_id'], CREATED)

    def test_initial_registration_cannot_claim_a_different_binding(self):
        self.session()
        self.sessions.bind_thread('p2p:one', MANUAL)
        self.grant['initial_user_creation'] = dict(status='bound', user_open_id='ou_one',
            scope='p2p:one', display_name='名字', thread_id=CREATED)
        with self.assertRaisesRegex(UserTaskError, 'initial_binding_changed'):
            self.enable()
        self.assertFalse((self.runtime / PROFILE_NAME).exists())

    def test_concurrent_reservations_and_consumption_are_single_use(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: store.reserve(profile, digest, 'ou_one', '名字', 'p2p:one'), range(8)))
        self.assertEqual(sum(fresh for _, fresh in results), 1)
        request = results[0][0]['request_id']
        self.assertIsNotNone(store.take(request))
        self.assertIsNone(UserTaskStore(self.runtime).take(request))
        self.assertEqual(store.get(request)['state'], 'consumed')

    def test_revocation_preserves_existing_binding_and_stops_new_work(self):
        profile, digest = self.enable()
        session = self.session()
        store = UserTaskStore(self.runtime)
        job, _ = store.reserve(profile, digest, 'ou_one', '名字', 'p2p:one')
        revoke(self.runtime)
        self.assertIsNone(store.take(job['request_id']))
        manager = self.manager(lambda _: self.fail('must not queue'))
        self.assertIsNone(manager.begin('p2p:one', session, 'ou_bot'))
        self.sessions.bind_thread('p2p:one', MANUAL)
        self.assertIsNone(manager.begin('p2p:one', self.sessions.get('p2p:one'), 'ou_bot'))
        self.assertEqual(self.sessions.get('p2p:one')['thread_id'], MANUAL)
        with self.assertRaises(UserTaskError):
            configure(self.runtime, self.grant, executable=Path('unused'))

    def test_exact_capacity_configured_grant_revokes_to_readable_idempotent_state(self):
        self.enable()
        small = (self.runtime / PROFILE_NAME).read_bytes()
        self.grant['grant_source_thread_id'] += 'x' * (16_384 - len(small))
        runtime = self.root / 'exact-capacity-runtime'
        runtime.mkdir()
        self.assertEqual(configure(runtime, self.grant, executable=Path('unused')),
            {'enabled': True, 'reused': False})
        path = runtime / PROFILE_NAME
        original = path.read_bytes()
        self.assertEqual(len(original), 16_384)
        self.assertIsNotNone(read_profile(runtime))
        self.assertEqual(revoke(runtime), {'enabled': False, 'state': 'revoked'})
        self.assertEqual(len(path.read_bytes()), 16_384)
        self.assertIsNone(read_profile(runtime))
        backups = list(runtime.glob(PROFILE_NAME + '.before-revocation-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        expected = json.loads(original)
        expected['status'] = 'revoked'
        self.assertEqual(json.loads(path.read_bytes()), expected)
        before = {entry.name: entry.read_bytes() for entry in runtime.iterdir() if entry.is_file()}
        self.assertEqual(revoke(runtime), {'enabled': False, 'state': 'revoked'})
        self.assertEqual(before, {entry.name: entry.read_bytes() for entry in runtime.iterdir() if entry.is_file()})

    def test_revocation_encoding_over_capacity_rejects_before_backup_or_write(self):
        profile, _ = self.enable()
        profile['grant_source_thread_id'] = '中' * 3_000
        original = json.dumps(profile, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertLessEqual(len(original), 16_384)
        path = self.runtime / PROFILE_NAME
        path.write_bytes(original)
        self.assertIsNotNone(read_profile(self.runtime))
        before = {entry.name: entry.read_bytes() for entry in self.runtime.iterdir() if entry.is_file()}
        with self.assertRaisesRegex(UserTaskError, 'user_task_record_too_large'):
            revoke(self.runtime)
        self.assertEqual(before, {entry.name: entry.read_bytes() for entry in self.runtime.iterdir() if entry.is_file()})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.runtime.glob(PROFILE_NAME + '.before-revocation-*')), [])
        self.assertEqual(list(self.runtime.glob(PROFILE_NAME + '.revoke-*')), [])

    def test_revocation_preserves_later_edit_and_original_backup(self):
        self.enable()
        path = self.runtime / PROFILE_NAME
        original = path.read_bytes()
        edited = original + b' '
        fsync = os.fsync
        def edit_during_write(descriptor):
            fsync(descriptor)
            path.write_bytes(edited)
        with patch('operator_core.user_tasks.os.fsync', side_effect=edit_during_write), \
                patch('operator_core.user_tasks.os.replace') as replace:
            with self.assertRaisesRegex(UserTaskError, 'user_task_grant_changed'):
                revoke(self.runtime)
            replace.assert_not_called()
        self.assertEqual(path.read_bytes(), edited)
        backups = list(self.runtime.glob(PROFILE_NAME + '.before-revocation-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(list(self.runtime.glob(PROFILE_NAME + '.revoke-*')), [])

    def test_group_and_explicit_binding_never_create_and_wrong_bot_rejected(self):
        self.enable()
        manager = self.manager(lambda _: self.fail('must not queue'))
        self.assertIsNone(manager.begin('group:x', dict(chat_type='group'), 'ou_bot'))
        self.assertIsNone(manager.begin('p2p:one', dict(thread_id=MANUAL), 'ou_other'))
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', self.session(), 'ou_other')

    def test_new_task_is_verified_then_bound_and_reused(self):
        self.enable()
        queues, reads = [], []
        def queue(request):
            queues.append(request)
            self.receipt(request)
        manager = self.manager(queue, verifier=lambda *args, **kwargs: reads.append((args, kwargs)))
        bound = manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertEqual(bound['thread_id'], CREATED)
        self.assertEqual(bound['desktop_project_id'], PROJECT)
        self.assertEqual(len(queues), 1)
        self.assertIn('since', reads[0][1])
        self.assertTrue(self.sessions.unbind_thread('p2p:one'))
        bound = manager.begin('p2p:one', self.sessions.get('p2p:one'), 'ou_bot').result(5)
        self.assertEqual(bound['thread_id'], CREATED)
        self.assertEqual(len(queues), 1)
        self.assertEqual(reads[1][1], {})

    def test_concurrent_begin_shares_creation_and_manual_binding_wins(self):
        self.enable()
        entered, release = threading.Event(), threading.Event()
        queues = []
        def queue(request):
            queues.append(request)
            entered.set()
            release.wait(3)
            self.receipt(request)
        manager = self.manager(queue)
        session = self.session()
        first = manager.begin('p2p:one', session, 'ou_bot')
        self.assertTrue(entered.wait(2))
        self.assertIs(first, manager.begin('p2p:one', session, 'ou_bot'))
        self.sessions.bind_thread('p2p:one', MANUAL)
        release.set()
        self.assertEqual(first.result(5)['thread_id'], MANUAL)
        self.assertEqual(len(queues), 1)

    def test_changed_sender_cannot_return_a_concurrent_manual_binding(self):
        self.enable()
        queues = []
        def queue(request):
            queues.append(request)
            self.receipt(request)
            self.sessions.update('p2p:one', {'user_open_id': 'ou_other'})
            self.sessions.bind_thread('p2p:one', MANUAL)
        manager = self.manager(queue)
        with self.assertRaisesRegex(UserTaskError, 'user_task_session_identity_changed'):
            manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertEqual(self.sessions.get('p2p:one')['thread_id'], MANUAL)
        self.assertEqual(self.sessions.get('p2p:one')['user_open_id'], 'ou_other')
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', dict(chat_type='p2p', user_open_id='ou_one'), 'ou_bot').result(5)
        self.assertEqual(len(queues), 1)

    def test_sender_change_between_read_and_binding_is_rejected_atomically(self):
        self.enable()
        manager = self.manager(self.receipt)
        bind = self.sessions.bind_thread_if_current
        def changed(*args, **kwargs):
            self.sessions.update('p2p:one', {'user_open_id': 'ou_other'})
            return bind(*args, **kwargs)
        with patch.object(self.sessions, 'bind_thread_if_current', side_effect=changed):
            with self.assertRaisesRegex(UserTaskError, 'user_task_session_identity_changed'):
                manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertFalse(self.sessions.get('p2p:one').get('thread_id'))
        self.assertEqual(self.sessions.get('p2p:one')['user_open_id'], 'ou_other')

    def test_sender_change_in_binding_conflict_does_not_return_other_task(self):
        self.enable()
        manager = self.manager(self.receipt)
        def changed(*args, **kwargs):
            self.sessions.update('p2p:one', {'chat_type': 'group'})
            self.sessions.bind_thread('p2p:one', MANUAL)
            raise ValueError('concurrent binding')
        with patch.object(self.sessions, 'bind_thread_if_current', side_effect=changed):
            with self.assertRaisesRegex(UserTaskError, 'user_task_session_identity_changed'):
                manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertEqual(self.sessions.get('p2p:one')['thread_id'], MANUAL)
        self.assertEqual(self.sessions.get('p2p:one')['chat_type'], 'group')

    def test_unknown_queue_and_later_messages_do_not_retry_creation(self):
        self.enable()
        calls = []
        def queue(request):
            calls.append(request)
            raise TimeoutError('uncertain')
        manager = self.manager(queue)
        session = self.session()
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', session, 'ou_bot').result(5)
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', session, 'ou_bot').result(5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(UserTaskStore(self.runtime).get(calls[0])['state'], 'uncertain')

    def test_native_read_uncertainty_does_not_create_replacement(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        store.seed(profile, digest, 'ou_one', '名字', 'p2p:one', CREATED)
        def unknown(*args, **kwargs):
            raise UserTaskError('unavailable')
        manager = self.manager(lambda _: self.fail('must not queue'), verifier=unknown)
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertFalse(self.sessions.get('p2p:one').get('thread_id'))

    def test_revoked_during_creation_does_not_replace_binding(self):
        self.enable()
        def queue(request):
            self.receipt(request)
            revoke(self.runtime)
        manager = self.manager(queue)
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        self.assertFalse(self.sessions.get('p2p:one').get('thread_id'))

    def test_corrupt_or_unavailable_local_state_never_queues(self):
        self.enable()
        manager = self.manager(lambda _: self.fail('must not queue'))
        session = self.session()
        with patch('operator_core.user_tasks.read_profile', side_effect=PermissionError):
            with self.assertRaisesRegex(UserTaskError, 'grant_unavailable'):
                manager.begin('p2p:one', session, 'ou_bot')
        with patch('operator_core.user_tasks.UserTaskStore', side_effect=sqlite3.OperationalError):
            with self.assertRaisesRegex(UserTaskError, 'creation_uncertain'):
                manager.begin('p2p:one', session, 'ou_bot').result(5)

    def test_conflicting_binding_receipt_is_preserved_without_recreation(self):
        self.enable()
        manager = self.manager(self.receipt)
        manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
        # Deliberately malformed partial edit, unlike the public unbind operation.
        before = self.sessions.update('p2p:one', {'thread_id': ''})
        with self.assertRaisesRegex(UserTaskError, 'binding_changed'):
            manager.begin('p2p:one', before, 'ou_bot').result(5)
        self.assertEqual(self.sessions.get('p2p:one'), before)

    def test_expired_setup_and_late_receipt_cannot_be_replayed(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        job, _ = store.reserve(profile, digest, 'ou_one', '名字', 'p2p:one')
        with patch('operator_core.user_tasks.time.time', return_value=job['created_at'] + 181):
            self.assertIsNone(store.take(job['request_id']))
        self.assertEqual(store.get(job['request_id'])['state'], 'uncertain')
        self.assertIsNone(store.take(job['request_id']))
        manager = self.manager(lambda _: self.fail('must not queue'))
        with self.assertRaises(UserTaskError):
            manager.begin('p2p:one', self.session(), 'ou_bot').result(5)

    def test_mcp_registration_is_single_use_and_business_collision_rejected(self):
        import relay_mcp_server as mcp
        from operator_core.final_callback import FinalCallbackStore
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        job, _ = store.reserve(profile, digest, 'ou_one', '名字', 'p2p:one')
        with patch.object(mcp, '_verified_runtime', return_value=(self.runtime, None)):
            self.assertIn('__create_thread', mcp.call_tool('take_relay', {'request_id': job['request_id']})['code'])
            duplicate = mcp.call_tool('take_relay', {'request_id': job['request_id']})['code']
            self.assertIn('setup_already_consumed_or_closed', duplicate)
            self.assertNotIn('__create_thread', duplicate)
            other, _ = store.reserve(profile, digest, 'ou_two', '名字', 'p2p:two')
            callbacks = FinalCallbackStore(self.runtime / 'callbacks.sqlite3')
            callbacks.open(other['request_id'], 'synthetic-event', CREATED, relay_prompt='original')
            with self.assertRaises(mcp.FinalCallbackError):
                mcp.call_tool('take_relay', {'request_id': other['request_id']})
            self.assertEqual(store.get(other['request_id'])['state'], 'queued')
            self.assertIsNotNone(callbacks.take_relay(other['request_id']))

    def test_native_verifier_only_reads_metadata_and_rejects_archive_or_wrong_project(self):
        calls = []
        thread = dict(id=CREATED, cwd=str(self.project), turns=[], createdAt=time.time())
        page = {'data': [thread]}
        class API:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, params):
                calls.append((method, params))
                return page if method == 'thread/list' else {'thread': thread}
        with patch('operator_core.user_tasks.AppServerSession', API):
            verify_native_task(self.config, Path('unused'), CREATED, str(self.project), since=time.time())
            self.assertEqual([method for method, _ in calls], ['thread/list', 'thread/read'])
            self.assertIs(calls[-1][1]['includeTurns'], False)
            thread['cwd'] = str(self.root)
            with self.assertRaises(UserTaskError):
                verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
            page['data'] = []
            with self.assertRaises(UserTaskError):
                verify_native_task(self.config, Path('unused'), CREATED, str(self.project))

    @unittest.skipUnless(shutil.which('node') and shutil.which('pwsh'), 'Node and PowerShell required')
    def test_generated_program_creates_once_and_writes_real_exclusive_receipt(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        job, _ = store.reserve(profile, digest, 'ou_one', '名字";$(noop)', 'p2p:one')
        code = setup_program(store.take(job['request_id']))
        fixture = """
const {spawnSync}=require('node:child_process');
const started=Date.now(); const seen=[];
const ALL_TOOLS=[{name:'native__create_thread'},{name:'native__list_projects'},{name:'native__wait_threads'},{name:'exec_command'}];
const tools={native__list_projects:async()=>({structuredContent:{projects:[PROJECT_ROW]}}),
native__wait_threads:async()=>({isError:false}),
native__create_thread:async args=>{seen.push(args);return {content:[{type:'text',text:JSON.stringify({threadId:THREAD,hostId:'local'})}]};},
exec_command:async args=>{const r=spawnSync('pwsh',['-NoProfile','-NonInteractive','-Command',args.cmd],{cwd:args.workdir,encoding:'utf8'});return {exit_code:r.status};}};
const text=()=>{};
(async()=>{await eval(CODE)();process.stdout.write(JSON.stringify(seen));})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
""".replace('THREAD', json.dumps(CREATED)).replace('CODE', json.dumps(code)).replace('PROJECT_ROW', json.dumps(dict(
            projectId=PROJECT, hostId='local', projectKind='local', isGitRepository=False, path=str(self.project))))
        result = subprocess.run(['node', '-e', fixture], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = json.loads(result.stdout)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['title'], '名字";$(noop)')
        self.assertNotIn('model', calls[0])
        self.assertEqual(calls[0]['target']['projectId'], PROJECT)
        receipt = json.loads((self.project / RECEIPT_DIR / (job['request_id'] + '.json')).read_text())
        self.assertEqual(receipt['thread_id'], CREATED)
        self.assertIsNone(store.take(job['request_id']))

    def test_registered_task_can_be_verified_after_provider_switch_without_creation(self):
        calls = []
        thread = dict(id=CREATED, cwd=str(self.project), turns=[], modelProvider='registered_web')
        class API:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, params):
                calls.append((method, params))
                if method == 'thread/list':
                    return {'data': [thread] if params.get('modelProviders') == [] else []}
                if method == 'thread/read':
                    return {'thread': thread}
                raise AssertionError(method)
        with patch('operator_core.user_tasks.AppServerSession', API):
            verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
        self.assertEqual([method for method, _ in calls], ['thread/list', 'thread/read'])
        self.assertIs(calls[0][1]['archived'], False)
        self.assertIs(calls[0][1]['useStateDbOnly'], True)
        self.assertIs(calls[1][1]['includeTurns'], False)

    def empty_preview_native(self):
        home = self.root / 'native-home'
        rollout = home / 'sessions' / '2026' / '09' / '22' / 'rollout.jsonl'
        rollout.parent.mkdir(parents=True)
        rollout.write_bytes(b'private history must not be read or modified\n')
        database = home / 'state_5.sqlite'
        now = int(time.time())
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, cwd TEXT, '
                       'source TEXT, model_provider TEXT, history_mode TEXT, preview TEXT, '
                       'archived INTEGER, archived_at INTEGER, created_at INTEGER, updated_at INTEGER)')
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (CREATED, str(rollout), str(self.project), 'vscode', 'openai', 'paginated', '', 0, None, now, now))
        thread = dict(id=CREATED, cwd=str(self.project), path=str(rollout), turns=[],
                      createdAt=now, updatedAt=now, source='vscode', modelProvider='openai',
                      historyMode='paginated', preview='', ephemeral=False, parentThreadId=None)
        calls = []
        settings = {'config': {'sqlite_home': None}}
        required = {'requirements': None}
        class API:
            server_info = {'codexHome': str(home)}
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, params):
                calls.append((method, params))
                if method == 'thread/list': return {'data': [], 'nextCursor': None}
                if method == 'thread/read': return {'thread': thread}
                if method == 'config/read': return settings
                if method == 'configRequirements/read': return required
                raise AssertionError(method)
        return API, database, rollout, thread, calls, settings, required

    def test_empty_preview_creation_and_reuse_preserve_native_bytes_and_queue_once(self):
        self.enable()
        API, database, rollout, thread, calls, _, _ = self.empty_preview_native()
        original = database.read_bytes(), rollout.read_bytes()
        queued = []
        def queue(request):
            queued.append(request)
            self.receipt(request)
        manager = self.manager(queue, verifier=verify_native_task)
        with patch('operator_core.user_tasks.AppServerSession', API), patch.dict(os.environ, {'CODEX_SQLITE_HOME': ''}):
            first = manager.begin('p2p:one', self.session(), 'ou_bot').result(5)
            self.sessions.unbind_thread('p2p:one')
            second = manager.begin('p2p:one', self.sessions.get('p2p:one'), 'ou_bot').result(5)
        self.assertEqual(first['thread_id'], CREATED)
        self.assertEqual(second['thread_id'], CREATED)
        self.assertEqual(len(queued), 1)
        self.assertEqual([m for m, _ in calls], ['thread/list', 'thread/read', 'config/read', 'configRequirements/read'] * 2)
        self.assertTrue(all(p.get('includeTurns') is False for m, p in calls if m == 'thread/read'))
        self.assertEqual(original, (database.read_bytes(), rollout.read_bytes()))

    def test_empty_preview_requires_active_matching_native_row(self):
        API, database, _, thread, _, _, _ = self.empty_preview_native()
        updates = [dict(archived=1), dict(archived_at=123), dict(preview='visible'),
                   dict(model_provider='other'), dict(created_at=0), dict(updated_at=0),
                   dict(source='subAgent'), dict(history_mode='legacy'),
                   dict(cwd=str(self.root)), dict(rollout_path=str(self.project / 'missing'))]
        with patch('operator_core.user_tasks.AppServerSession', API), patch.dict(os.environ, {'CODEX_SQLITE_HOME': ''}):
            for update in updates:
                with self.subTest(update=update):
                    before = database.read_bytes()
                    with closing(sqlite3.connect(database)) as db, db:
                        db.execute('UPDATE threads SET ' + ','.join(k+'=?' for k in update), tuple(update.values()))
                    changed = database.read_bytes()
                    with self.assertRaisesRegex(UserTaskError, 'not_confirmed_active'):
                        verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
                    self.assertEqual(changed, database.read_bytes())
                    database.write_bytes(before)
            with closing(sqlite3.connect(database)) as db, db: db.execute('DELETE FROM threads')
            with self.assertRaisesRegex(UserTaskError, 'not_confirmed_active'):
                verify_native_task(self.config, Path('unused'), CREATED, str(self.project))

    @unittest.skipUnless(os.name == 'nt', 'Windows native metadata path spelling')
    def test_empty_preview_accepts_equivalent_verbatim_drive_paths(self):
        API, database, rollout, thread, _, _, _ = self.empty_preview_native()
        extended = '\\\\?\\'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('UPDATE threads SET rollout_path=?,cwd=?',
                       (extended + str(rollout), extended + str(self.project)))
        thread['path'] = extended + str(rollout)
        original = database.read_bytes()
        with patch('operator_core.user_tasks.AppServerSession', API), patch.dict(os.environ, {'CODEX_SQLITE_HOME': ''}):
            verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
        self.assertEqual(original, database.read_bytes())

    def test_empty_preview_unknown_storage_and_nonmatching_api_fail_closed(self):
        API, database, _, thread, _, settings, required = self.empty_preview_native()
        original_thread = dict(thread)
        with patch('operator_core.user_tasks.AppServerSession', API), patch.dict(os.environ, {'CODEX_SQLITE_HOME': ''}):
            for update in [dict(preview='visible'), dict(historyMode='legacy'), dict(ephemeral=True),
                           dict(parentThreadId=MANUAL), dict(updatedAt=0), dict(path=str(database)),
                           dict(cwd=str(self.root)), dict(createdAt=True)]:
                with self.subTest(update=update):
                    thread.update(update)
                    with self.assertRaises(UserTaskError):
                        verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
                    thread.clear(); thread.update(original_thread)
            for field in (settings['config'], required):
                old = dict(field)
                field.update({'sqlite_home': str(database.parent)} if field is settings['config'] else
                             {'requirements': {'sqlite_home': str(database.parent)}})
                with self.assertRaises(UserTaskError):
                    verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
                field.clear(); field.update(old)
            with patch.dict(os.environ, {'CODEX_SQLITE_HOME': str(database.parent)}):
                with self.assertRaises(UserTaskError):
                    verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
            newer = database.with_name('state_6.sqlite'); newer.write_bytes(b'new store')
            with self.assertRaises(UserTaskError):
                verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
            newer.unlink()
            with patch.object(API, 'server_info', {}):
                with self.assertRaises(UserTaskError):
                    verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
            with closing(sqlite3.connect(database)) as db, db: db.execute('ALTER TABLE threads RENAME COLUMN archived TO unknown_archive')
            with self.assertRaises(UserTaskError):
                verify_native_task(self.config, Path('unused'), CREATED, str(self.project))

    def test_unfinished_catalog_never_uses_empty_preview_compatibility(self):
        for mode in ('loop', 'limit', 'invalid'):
            calls = []
            class API:
                def __init__(self, *args, **kwargs): pass
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def request(self, method, params):
                    calls.append(method)
                    if method != 'thread/list': raise AssertionError(method)
                    return {'data': None if mode == 'invalid' else [],
                            'nextCursor': str(len(calls)) if mode == 'limit' else 'repeat'}
            with self.subTest(mode=mode), patch('operator_core.user_tasks.AppServerSession', API):
                with self.assertRaisesRegex(UserTaskError, 'native_read_uncertain'):
                    verify_native_task(self.config, Path('unused'), CREATED, str(self.project))
                self.assertLessEqual(len(calls), 10)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_native_program_rejects_changed_project_or_uncertain_creation_without_retry(self):
        profile, digest = self.enable()
        store = UserTaskStore(self.runtime)
        job, _ = store.reserve(profile, digest, 'ou_one', '名字', 'p2p:one')
        code = setup_program(store.take(job['request_id']))
        row = dict(projectId=PROJECT, hostId='local', projectKind='local', isGitRepository=False, path=str(self.project))
        for mode, expected_creations in [('project_changed', 0), ('missing_tools', 0), ('slow', 0),
                ('create_throws', 1), ('create_error', 1), ('queued_worktree', 1), ('bad_identity', 1), ('conflict', 1)]:
            with self.subTest(mode=mode):
                harness = """
let count=0,writes=0; const mode=MODE; const started=Date.now()-(mode==='slow'?3000:0);
const row=ROW; if(mode==='project_changed')row.isGitRepository=true;
const tools={native__list_projects:async()=>({content:[{type:'text',text:JSON.stringify({projects:[row]})}]}),
native__wait_threads:async()=>({isError:false}),
native__create_thread:async()=>{count++;if(mode==='create_throws')throw Error('unknown');
if(mode==='create_error')return {isError:true};
if(mode==='queued_worktree')return {structuredContent:{clientThreadId:THREAD}};
if(mode==='bad_identity')return {structuredContent:{threadId:'bad',hostId:'local'}};
return {structuredContent:{threadId:THREAD,hostId:'local'},content:[{type:'text',text:JSON.stringify({threadId:OTHER,hostId:'local'})}]};},
exec_command:async()=>{writes++;return {exit_code:0};}};
let ALL_TOOLS=Object.keys(tools).map(name=>({name}));if(mode==='missing_tools')ALL_TOOLS=[];
const text=()=>{};(async()=>{try{await eval(CODE)();}catch{}process.stdout.write(JSON.stringify({count,writes}));})();
""".replace('MODE', json.dumps(mode)).replace('ROW', json.dumps(row)).replace('THREAD', json.dumps(CREATED)).replace('OTHER', json.dumps(MANUAL)).replace('CODE', json.dumps(code))
                result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'count': expected_creations, 'writes': 0})


if __name__ == '__main__':
    unittest.main()
