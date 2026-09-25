"""Owned Python fixture workers and loopback HTTP only; never a real browser."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from aiohttp import ClientSession

import operator_web_model as service
from operator_core.web_browser_driver import WebTextBrowserDriver
from operator_core.web_browser_session import WebBrowserSession
from operator_core.web_mcp_transport import WebMcpEndpoint, WebResponsesBridge
from operator_core.web_responses_provider import WebResponsesProvider
from test_web_model_protocol import message


class BrowserServiceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='web-lifecycle-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'profile').mkdir()
        self.release = self.root / 'release.fixture'
        self.trace = self.root / 'worker-trace.fixture'
        self.settings = {'electron': sys.executable,
            'profile_directory': str(self.root / 'profile'),
            'session_partition': 'persist:operator-lifecycle-fixture', 'timeout_ms': 10000}
        for module in ('web_browser_driver', 'web_browser_session'):
            replacement = patch('operator_core.' + module + '.desktop_session_state', return_value='unlocked')
            replacement.start()
            self.addCleanup(replacement.stop)

    @staticmethod
    def payload(turn='first'):
        return {'model': service.SLUG, 'input': [{'role': 'user', 'content': 'exact 中文😀\r\n'}],
            'reasoning': {'effort': 'high'}, 'stream': False,
            'client_metadata': {'thread_id': 'private-lifecycle-fixture', 'turn_id': turn}}

    async def until(self, condition):
        async def poll():
            while not condition():
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), 4)

    def worker_program(self, variant='normal'):
        header = '\n'.join((
            'VARIANT=' + repr(variant), 'PUBLIC=' + repr(message()),
            'RELEASE=' + repr(str(self.release)), 'TRACE=' + repr(str(self.trace))))
        return header + '\n' + '''import json,sys,time
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'));root=Path(c['workerDirectory'])
assert c['mode']=='worker' and c['visible'] is False and c['backgroundInput']=='dom_v1'
assert 'startupAssistance' not in c and 'text' not in c
def emit(kind,**values):print(json.dumps({'operator_web':1,'kind':kind,**values}),flush=True)
def trace(kind,ident):
 with open(TRACE,'a',encoding='utf8') as stream:stream.write(json.dumps([kind,ident])+'\\n')
if VARIANT=='exit_before_ready':raise SystemExit(1)
emit('worker_ready');count=0;seen=set()
if VARIANT=='exit':raise SystemExit(1)
if c.get('startupPrepare') is True:
 if VARIANT in ('prepare_gate_failed','prepare_gate_extra','prepare_structure_extra','prepare_structure_duplicate'):
  fields=dict(stage='startup_prepare',sent=False,route='temporary',pageKind='chatgpt',
   composer='yes',modelControl='zero',loginVisible='no',userRows='zero',assistantRows='zero')
  if VARIANT=='prepare_gate_extra':fields['rawUrl']='PRIVATE URL'
  emit('startup_prepare_state',**fields)
  structure=dict(stage='startup_prepare',sent=False,readyState='complete',
   legacyEditorCount='one',legacyEditorEditable='no',legacyEditorRect='yes',
   testIdEditorVisible='one',roleTextboxEditableVisible='one',editableVisible='one',
   textareaVisible='zero',globalModelTotal='one',globalModelVisible='one',
   editorFormExists='yes',accessibleModelCount='one',accessibleModelSource='aria_label',
   accessibleModelTag='button',accessibleModelInEditorForm='no',
   accessibleModelHaspopup='menu',accessibleModelDisabled='no')
  if VARIANT=='prepare_structure_extra':structure['rawUrl']='PRIVATE URL'
  emit('startup_control_structure',**structure)
  if VARIANT=='prepare_structure_duplicate':emit('startup_control_structure',**structure)
  emit('failed',stage='startup_prepare',sent=False,error='web_startup_prepare_unavailable')
  raise SystemExit(1)
 if VARIANT in ('prepare_failed','prepare_failed_extra'):
  fields=dict(stage='startup_prepare',sent=False,error='web_page_state_timeout')
  if VARIANT=='prepare_failed_extra':fields['rawUrl']='PRIVATE URL'
  emit('failed',**fields)
  raise SystemExit(1)
 if VARIANT=='prepare_hold':
  while not Path(RELEASE).exists() and not (root/'shutdown.json').exists():time.sleep(.01)
  if (root/'shutdown.json').exists():raise SystemExit(0)
  Path(RELEASE).unlink()
 emit('worker_prepared',hidden=True,empty=True)
while not (root/'shutdown.json').exists():
 p=root/'assist.json'
 if p.exists():
  r=json.loads(p.read_text());p.rename(root/'assisting.json');ident=r['id']
  trace('assist',ident)
  if VARIANT=='wrong_assistance':ident='f'*32
  inspecting=r.get('inspect_completed',False)
  emit('assistance_opened',assistanceId=ident,inspectCompleted=inspecting if VARIANT!='wrong_inspection' else False)
  while not Path(RELEASE).exists() and not (root/'shutdown.json').exists():time.sleep(.01)
  if (root/'shutdown.json').exists():break
  Path(RELEASE).unlink()
  if VARIANT in ('assistance_close_diagnostic','assistance_close_extra'):
   fields=dict(assistanceId=ident,stage='worker_assistance',sent=False,
    phase='before',route='temporary',pageKind='chatgpt',composer='yes',
    modelControl='zero',loginVisible='no',userRows='zero',assistantRows='zero',
    composerEmpty='unchecked')
   if VARIANT=='assistance_close_extra':fields['rawUrl']='PRIVATE URL'
   emit('assistance_close_state',**fields)
   emit('assistance_failed',assistanceId=ident,error='web_assistance_closed_before_ready')
   raise SystemExit(1)
  emit('assistance_hidden',assistanceId=ident,visible=VARIANT=='unhidden',focused=False,userClosed=True,
   inspectCompleted=inspecting,pagePreserved=inspecting and VARIANT!='lost_page')
  (root/'assisting.json').unlink();continue
 p=root/'next.json'
 if not p.exists():time.sleep(.01);continue
 r=json.loads(p.read_text(encoding='utf8'));p.rename(root/'active.json');ident=r['id']
 assert ident not in seen;seen.add(ident);trace('request',ident);count+=1
 if count==1 and VARIANT.startswith(('login','challenge','bad_')):
  reason='web_browser_challenge_required_before_dispatch' if VARIANT=='challenge' else 'web_browser_login_required_before_dispatch'
  if VARIANT=='bad_dispatch':emit('dispatch_started',requestId=ident)
  emit('failed',requestId=ident,error=reason,sent=VARIANT=='bad_sent',
   stage='other' if VARIANT=='bad_stage' else 'load_fresh_page')
  (root/'active.json').unlink()
  emit('worker_idle',requestId=ident,resultCode=1,assistanceRequired=True)
  continue
 emit('dispatch_started',requestId=ident)
 if VARIANT in ('hold','cancel') or VARIANT.startswith('cancel_') and count==1:
  while not Path(RELEASE).exists() and not (root/'cancel.json').exists():time.sleep(.01)
  if (root/'cancel.json').exists():
   cancellation=json.loads((root/'cancel.json').read_text())
   assert cancellation['id']==ident and set(cancellation)<={'id','reuse_when_idle'}
   trace('reuse_requested',cancellation.get('reuse_when_idle',False))
   (root/'cancel.json').unlink();(root/'active.json').unlink()
   if VARIANT.startswith('cancel_'):
    emit('window_state',requestId=ident,visible=VARIANT=='cancel_visible',focused=False,
     backgroundInput=True,inputMode='dom_v1',shown=0,focusedEvents=0)
   error='web_host_deadline_no_retry' if VARIANT=='cancel_other_failure' else 'web_cancelled_no_retry'
   emit('failed',requestId=ident,error=error,sent=VARIANT!='cancel_unsent')
   emit('worker_idle',requestId='f'*32 if VARIANT=='cancel_wrong_identity' else ident,resultCode=1,
    cancelledIdleVerified=VARIANT not in ('cancel','hold','cancel_unverified'))
   if VARIANT=='cancel_idle':continue
   break
  Path(RELEASE).unlink()
 emit('window_state',requestId=ident,visible=False,focused=False,backgroundInput=True,inputMode='dom_v1',shown=0,focusedEvents=0)
 emit('completed',requestId=ident,model='gpt-5.6-sol',effortIndex=2,publicMessage=PUBLIC)
 (root/'active.json').unlink();emit('worker_idle',requestId=ident,resultCode=0)
'''

    def spawn_fixture(self, variant, launches):
        original = asyncio.create_subprocess_exec
        program = self.worker_program(variant)
        async def spawn(*args, **kwargs):
            config = Path(args[-1])
            launches.append(json.loads(config.read_text(encoding='utf8')))
            return await original(sys.executable, '-u', '-c', program, str(config), **kwargs)
        return patch('operator_core.web_browser_session.asyncio.create_subprocess_exec', spawn)

    def session(self, suffix='session', *, startup_prepare=False):
        driver = WebBrowserSession(WebTextBrowserDriver(self.settings, self.root / suffix),
            startup_prepare=startup_prepare)
        self.addAsyncCleanup(driver.close)
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
        self.addAsyncCleanup(bridge.stop)
        return driver, bridge

    def test_lifecycle_defaults_hidden_but_preserves_explicit_diagnostics(self):
        self.assertEqual(service.selected_lifecycle({}), 'session_v1')
        self.assertEqual(service.selected_lifecycle({'window_mode': 'visible'}), 'per_turn')
        self.assertEqual(service.selected_lifecycle({'browser_lifecycle': 'per_turn'}), 'per_turn')
        with self.assertRaisesRegex(ValueError, 'web_browser_lifecycle_invalid'):
            service.selected_lifecycle({'browser_lifecycle': 'retry'})

    async def test_service_progress_reports_transport_without_claiming_task_success(self):
        driver, bridge = self.session('transport-progress')
        provider = WebResponsesProvider(bridge)
        launches = []
        with self.spawn_fixture('normal', launches):
            await bridge.exchange(self.payload())
        details = service.service_status('a' * 32, driver, provider)
        self.assertEqual(details['transport']['last_turn']['outcome'], 'public_final_returned')
        self.assertEqual(details['transport']['last_turn']['calls_released'], 0)
        self.assertEqual(details['mcp'],bridge.endpoint.diagnostics())
        self.assertIn('最近一次网页回复已返回', service.service_guidance(details))
        self.assertIn('收到 0 份配对结果', service.service_guidance(details))
        self.assertIn('任务是否完成需核对实际结果', service.service_guidance(details))
        self.assertNotIn('任务已完成', service.service_guidance(details))
        self.assertEqual(len(launches), 1)

    async def test_pre_dispatch_assistance_keeps_one_worker_but_never_replays_consumed_turn(self):
        for variant in ('login', 'challenge'):
            with self.subTest(variant=variant):
                driver, bridge = self.session(variant)
                launches = []
                with self.spawn_fixture(variant, launches):
                    with self.assertRaisesRegex(ValueError, 'web_browser_.*_required_before_dispatch'):
                        await bridge.exchange(self.payload())
                    status = driver.status()
                    self.assertEqual(status['readiness'], 'assistance_required')
                    self.assertTrue(status['needs_assistance'])
                    self.assertTrue(status['process_running'])
                    self.assertEqual((status['attempts'], status['dispatches']), (1, 0))
                    self.assertFalse((driver.folder / 'assist.json').exists())
                    with self.assertRaisesRegex(ValueError, 'web_bridge_turn_consumed_no_retry'):
                        await bridge.exchange(self.payload())
                    assistance = asyncio.create_task(driver.assist('a' * 32))
                    await self.until(lambda: driver.assistance_state == 'awaiting_user')
                    self.assertEqual(driver.status()['dispatches'], 0)
                    self.release.write_bytes(b'closed')
                    await asyncio.wait_for(assistance, 3)
                    self.assertEqual(driver.status()['readiness'], 'ready')
                    self.assertFalse(driver.status()['needs_assistance'])
                    response, _ = await bridge.exchange(self.payload('new-after-assistance'))
                    self.assertEqual(response['output'][0]['content'][0]['text'], message()['content']['parts'][0])
                    self.assertEqual(len(launches), 1)
                    self.assertEqual(driver.status()['completed'], 1)
                    await driver.close()
                    self.assertEqual(list(driver.base.work.iterdir()), [])

    async def test_contradictory_pre_dispatch_failure_cannot_retain_or_restart_worker(self):
        for variant in ('bad_sent', 'bad_stage', 'bad_dispatch'):
            with self.subTest(variant=variant):
                driver, bridge = self.session(variant)
                launches = []
                with self.spawn_fixture(variant, launches):
                    with self.assertRaisesRegex(ValueError, 'web_browser_driver_failed_no_retry'):
                        await bridge.exchange(self.payload())
                    self.assertTrue(driver.closed)
                    self.assertFalse(driver.status()['process_running'])
                    self.assertFalse(driver.status()['needs_assistance'])
                    with self.assertRaisesRegex(ValueError, 'web_assistance_requires_idle_session'):
                        await driver.assist('b' * 32)
                    self.assertEqual(len(launches), 1)

    async def test_explicit_assistance_starts_hidden_and_rejects_unbound_or_visible_completion(self):
        for variant in ('normal', 'wrong_assistance', 'unhidden'):
            with self.subTest(variant=variant):
                driver, _ = self.session(variant)
                launches = []
                with self.spawn_fixture(variant, launches):
                    operation = asyncio.create_task(driver.assist('c' * 32))
                    if variant != 'wrong_assistance':
                        await self.until(lambda: driver.assistance_state == 'awaiting_user')
                        self.release.write_bytes(b'closed')
                    if variant == 'normal':
                        await asyncio.wait_for(operation, 3)
                        self.assertEqual(driver.assistance_state, 'background')
                    else:
                        with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                            await asyncio.wait_for(operation, 3)
                        self.assertEqual(driver.status()['readiness'], 'unavailable')
                    self.assertEqual(len(launches), 1)
                    self.assertEqual(driver.base.dispatches, 0)
                    await driver.close()

    async def test_assistance_close_diagnostic_retains_only_fixed_gates_and_failure_code(self):
        for variant in ('assistance_close_diagnostic', 'assistance_close_extra'):
            with self.subTest(variant=variant):
                driver, _ = self.session(variant)
                launches = []
                with self.spawn_fixture(variant, launches):
                    operation = asyncio.create_task(driver.assist('c' * 32))
                    await self.until(lambda: driver.assistance_state == 'awaiting_user')
                    self.release.write_bytes(b'closed')
                    with self.assertRaisesRegex(ValueError,
                            'web_assistance_failed_no_retry|web_session_worker_failed_no_retry'):
                        await asyncio.wait_for(operation, 3)
                    events = driver.base.status()['events']
                    checks = [row for row in events if row['kind'] == 'assistance_close_state']
                    if variant == 'assistance_close_diagnostic':
                        self.assertEqual(len(checks), 1)
                        self.assertEqual(checks[0]['modelControl'], 'zero')
                        self.assertEqual(checks[0]['composerEmpty'], 'unchecked')
                        failures = [row for row in events if row['kind'] == 'assistance_failed']
                        self.assertEqual(failures[-1]['code'], 'web_assistance_closed_before_ready')
                    else:
                        self.assertEqual(checks, [])
                    self.assertNotIn('PRIVATE URL', json.dumps(events))
                    self.assertEqual(driver.base.dispatches, 0)

    async def test_hidden_prepare_failure_retains_only_fixed_phase_and_code(self):
        for variant in ('prepare_failed', 'prepare_failed_extra', 'exit_before_ready'):
            with self.subTest(variant=variant):
                driver, _ = self.session(variant, startup_prepare=True)
                launches = []
                with self.spawn_fixture(variant, launches):
                    with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                        await asyncio.wait_for(driver.prepare_hidden(), 3)
                    events = driver.base.status()['events']
                    failures = [row for row in events if row['kind'] == 'startup_failed']
                    self.assertEqual(len(failures), 1)
                    self.assertEqual(failures[0]['stage'],
                        'startup_prepare' if variant == 'prepare_failed' else 'unknown')
                    self.assertEqual(failures[0]['code'],
                        'web_page_state_timeout' if variant == 'prepare_failed'
                        else 'web_session_worker_failed_no_retry')
                    self.assertEqual(any(row['kind'] == 'startup_worker_ready' for row in events),
                        variant != 'exit_before_ready')
                    self.assertNotIn('PRIVATE URL', json.dumps(events))
                    self.assertEqual(driver.base.dispatches, 0)

    async def test_hidden_prepare_launch_failure_records_no_exception_text(self):
        driver, _ = self.session('launch-failed', startup_prepare=True)
        with patch('operator_core.web_browser_session.asyncio.create_subprocess_exec',
                side_effect=OSError('PRIVATE executable path')):
            with self.assertRaisesRegex(OSError, 'PRIVATE executable path'):
                await driver.prepare_hidden()
        self.assertEqual(driver.base.status()['events'], [{'kind': 'startup_failed',
            'stage': 'launch', 'code': 'web_session_worker_failed_no_retry'}])
        self.assertTrue(driver.closed)
        self.assertEqual(driver.base.dispatches, 0)
        self.assertEqual(list(driver.base.work.iterdir()), [])

    async def test_hidden_prepare_gate_diagnostic_rejects_extra_page_data(self):
        for variant in ('prepare_gate_failed', 'prepare_gate_extra',
                'prepare_structure_extra', 'prepare_structure_duplicate'):
            with self.subTest(variant=variant):
                driver, _ = self.session(variant, startup_prepare=True)
                launches = []
                with self.spawn_fixture(variant, launches):
                    with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                        await asyncio.wait_for(driver.prepare_hidden(), 3)
                    events = driver.base.status()['events']
                    gates = [row for row in events if row['kind'] == 'startup_prepare_state']
                    if variant == 'prepare_gate_failed':
                        self.assertEqual(gates, [{'kind': 'startup_prepare_state',
                            'route': 'temporary', 'pageKind': 'chatgpt', 'composer': 'yes',
                            'modelControl': 'zero', 'loginVisible': 'no',
                            'userRows': 'zero', 'assistantRows': 'zero'}])
                        failures = [row for row in events if row['kind'] == 'startup_failed']
                        self.assertEqual(failures[-1]['code'], 'web_startup_prepare_unavailable')
                    elif variant == 'prepare_gate_extra':
                        self.assertEqual(gates, [])
                    structures = [row for row in events if row['kind'] == 'startup_control_structure']
                    if variant in ('prepare_gate_failed', 'prepare_structure_duplicate'):
                        self.assertEqual(structures, [{'kind': 'startup_control_structure',
                            'readyState': 'complete', 'legacyEditorCount': 'one',
                            'legacyEditorEditable': 'no', 'legacyEditorRect': 'yes',
                            'testIdEditorVisible': 'one', 'roleTextboxEditableVisible': 'one',
                            'editableVisible': 'one', 'textareaVisible': 'zero',
                            'globalModelTotal': 'one', 'globalModelVisible': 'one',
                            'editorFormExists': 'yes', 'accessibleModelCount': 'one',
                            'accessibleModelSource': 'aria_label', 'accessibleModelTag': 'button',
                            'accessibleModelInEditorForm': 'no',
                            'accessibleModelHaspopup': 'menu', 'accessibleModelDisabled': 'no'}])
                    else:
                        self.assertEqual(structures, [])
                    self.assertNotIn('PRIVATE URL', json.dumps(events))
                    self.assertEqual(driver.base.dispatches, 0)

    async def test_active_request_blocks_assistance_and_concurrent_close_has_one_owner(self):
        driver, bridge = self.session()
        launches = []
        with self.spawn_fixture('cancel', launches):
            request = asyncio.create_task(bridge.exchange(self.payload()))
            await self.until(lambda: driver.base.dispatches == 1)
            with self.assertRaisesRegex(ValueError, 'web_assistance_requires_idle_session'):
                await driver.assist('d' * 32)
            self.assertFalse((driver.folder / 'assist.json').exists())
            await asyncio.wait_for(asyncio.gather(*(driver.close() for _ in range(5))), 4)
            with self.assertRaisesRegex(ValueError, 'web_browser_driver_failed_no_retry'):
                await request
            self.assertEqual(len(launches), 1)
            self.assertEqual(driver.base.dispatches, 1)
            self.assertEqual(list(driver.base.work.iterdir()), [])

    async def test_client_cancel_reuses_only_sealed_idle_worker_for_a_new_http_turn(self):
        driver, bridge = self.session('cancel-reuse')
        provider = WebResponsesProvider(bridge)
        base = await provider.start()
        self.addAsyncCleanup(provider.stop)
        launches = []
        with self.spawn_fixture('cancel_idle', launches):
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                request = asyncio.create_task(client.post(base + '/responses', json=self.payload()))
                await self.until(lambda: driver.base.dispatches == 1)
                old_turn = bridge.turn
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                await self.until(lambda: not driver.base.active)
                self.assertTrue(old_turn.closed)
                self.assertTrue(old_turn.client_cancelled)
                self.assertEqual(bridge.diagnostics()['last_turn']['outcome'], 'cancelled')
                self.assertEqual(driver.status()['readiness'], 'ready')
                self.assertFalse(driver.status()['inspection_available'])
                self.assertEqual((driver.base.cancelled, driver.base.failed), (1, 0))
                async with client.post(base + '/responses', json=self.payload('new-after-cancel')) as response:
                    self.assertEqual(response.status, 200)
                    result = await response.json()
                    self.assertEqual(result['output'][0]['content'][0]['text'], message()['content']['parts'][0])
                with self.assertRaisesRegex(ValueError, 'web_bridge_turn_consumed_no_retry'):
                    await bridge.exchange(self.payload())
                self.assertEqual((driver.base.dispatches, driver.base.completed, len(launches)), (2, 1, 1))
                events = [json.loads(line) for line in self.trace.read_text().splitlines()]
                self.assertIn(['reuse_requested', True], events)
                self.assertEqual(len({row[1] for row in events if row[0] == 'request'}), 2)

    async def test_cancel_unverified_or_contradictory_worker_seals_and_never_restarts(self):
        for variant in ('cancel_unverified', 'cancel_visible', 'cancel_unsent',
                'cancel_wrong_identity', 'cancel_other_failure'):
            with self.subTest(variant=variant):
                driver, bridge = self.session(variant)
                launches = []
                with self.spawn_fixture(variant, launches):
                    request = asyncio.create_task(bridge.exchange(self.payload()))
                    await self.until(lambda: driver.base.dispatches == 1)
                    request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
                    self.assertTrue(driver.closed)
                    self.assertFalse(driver.status()['process_running'])
                    self.assertEqual(driver.base.dispatches, 1)
                    self.assertEqual(len(launches), 1)

    async def test_stop_or_driver_deadline_never_requests_cancel_reuse(self):
        for action in ('stop', 'driver-cancel', 'concurrent-close'):
            with self.subTest(action=action):
                driver, bridge = self.session(action)
                launches = []
                trace_start = len(self.trace.read_text().splitlines()) if self.trace.exists() else 0
                with self.spawn_fixture('cancel_idle', launches):
                    request = asyncio.create_task(bridge.exchange(self.payload()))
                    await self.until(lambda: driver.base.dispatches == 1)
                    if action == 'stop':
                        await bridge.stop()
                    elif action == 'driver-cancel':
                        bridge.driver.cancel()
                    else:
                        request.cancel()
                        await driver.close()
                    await asyncio.gather(request, return_exceptions=True)
                    self.assertTrue(driver.closed)
                    self.assertFalse(driver.status()['process_running'])
                    self.assertEqual((driver.base.dispatches, len(launches)), (1, 1))
                    events = [json.loads(line) for line in self.trace.read_text().splitlines()[trace_start:]]
                    self.assertNotIn(['reuse_requested', True], events)

    async def test_inspection_requires_completed_page_and_preserves_one_worker_without_replay(self):
        driver, bridge = self.session()
        launches = []
        with self.spawn_fixture('normal', launches):
            with self.assertRaisesRegex(ValueError, 'web_inspection_completed_page_required'):
                await driver.assist('a' * 32, inspect_completed=True)
            self.assertEqual(launches, [])
            await bridge.exchange(self.payload())
            self.assertTrue(driver.status()['inspection_available'])
            operation = asyncio.create_task(driver.assist('b' * 32, inspect_completed=True))
            await self.until(lambda: driver.assistance_state == 'awaiting_user')
            self.assertFalse(driver.status()['inspection_available'])
            with self.assertRaisesRegex(ValueError, 'web_browser_assistance_pending_before_dispatch'):
                await driver(None)
            self.release.write_bytes(b'closed')
            await asyncio.wait_for(operation, 3)
            self.assertTrue(driver.status()['inspection_available'])
            self.assertEqual((driver.base.attempts, driver.base.dispatches), (1, 1))
            with self.assertRaisesRegex(ValueError, 'web_bridge_turn_consumed_no_retry'):
                await bridge.exchange(self.payload())
            await bridge.exchange(self.payload('new-after-inspection'))
            self.assertEqual(len(launches), 1)
            self.assertEqual(driver.base.completed, 2)

    async def test_inspection_rejects_unbound_mode_or_unverified_page_preservation(self):
        for variant in ('wrong_inspection', 'lost_page'):
            driver, bridge = self.session(variant)
            with self.spawn_fixture(variant, []):
                await bridge.exchange(self.payload())
                operation = asyncio.create_task(driver.assist('c' * 32, inspect_completed=True))
                if variant == 'lost_page':
                    await self.until(lambda: driver.assistance_state == 'awaiting_user')
                    self.release.write_bytes(b'closed')
                with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                    await asyncio.wait_for(operation, 3)
                self.assertFalse(driver.status()['inspection_available'])
                self.assertEqual(driver.base.dispatches, 1)
                await driver.close()

    def test_inspection_command_rejects_replacement_and_consumes_once(self):
        state = self.root / 'inspection-commands'; state.mkdir()
        command = state / 'assist.json'
        service.write_command(command, {'instance': 'a' * 32, 'id': 'b' * 32, 'inspect_completed': True})
        self.assertEqual(service.take_assistance_request(state, 'a' * 32), ('b' * 32, False, True))
        for value in (1, 'true', None):
            service.write_command(command, {'instance': 'a' * 32, 'id': 'c' * 32, 'inspect_completed': value})
            with self.assertRaisesRegex(ValueError, 'web_inspection_mode_invalid'):
                service.take_assistance_request(state, 'a' * 32)
            self.assertFalse(command.exists())
        service.write_command(command, {'instance': 'a' * 32, 'id': 'd' * 32,
            'inspect_completed': True, 'replace_closed_browser': True})
        with self.assertRaisesRegex(ValueError, 'web_inspection_mode_invalid'):
            service.take_assistance_request(state, 'a' * 32)
        self.assertFalse(command.exists())

    async def test_dead_idle_worker_is_unavailable_and_never_automatically_restarted(self):
        driver, _ = self.session()
        launches = []
        with self.spawn_fixture('exit', launches):
            try:
                await driver.start()
            except ValueError:
                pass
            await self.until(lambda: driver.closed)
            self.assertEqual(driver.status()['readiness'], 'unavailable')
            with self.assertRaisesRegex(ValueError, 'web_session_closed_new_service_required'):
                await driver.start()
            self.assertEqual(len(launches), 1)

    async def test_assistance_wait_and_service_stop_share_one_bounded_cleanup(self):
        driver, _ = self.session()
        launches = []
        with self.spawn_fixture('normal', launches):
            assistance = asyncio.create_task(driver.assist('1' * 32))
            await self.until(lambda: driver.assistance_state == 'awaiting_user')
            await asyncio.wait_for(asyncio.gather(driver.close(), driver.close()), 3)
            with self.assertRaisesRegex(ValueError, 'web_assistance_stopped_no_retry'):
                await assistance
            self.assertEqual(driver.status()['readiness'], 'unavailable')
            self.assertEqual(len(launches), 1)
            self.assertEqual(list(driver.base.work.iterdir()), [])

    def test_private_commands_are_exclusive_instance_bound_and_consumed_on_rejection(self):
        state = self.root / 'commands'
        state.mkdir()
        command = state / 'assist.json'
        service.write_command(command, {'instance': 'a' * 32, 'id': 'b' * 32})
        with self.assertRaisesRegex(ValueError, 'web_service_command_pending'):
            service.write_command(command, {'instance': 'a' * 32, 'id': 'c' * 32})
        with self.assertRaisesRegex(ValueError, 'web_service_assistance_identity_changed'):
            service.take_assistance_request(state, 'f' * 32)
        self.assertEqual(list(state.iterdir()), [])
        for seconds in (-1, 31, True):
            path = state / 'stop.json'
            service.write_json(path, {'instance': 'a' * 32, 'drain_seconds': seconds})
            with self.assertRaisesRegex(ValueError, 'web_service_drain_invalid'):
                service.stop_request(path, 'a' * 32)

    async def start_service(self, *, variant='normal', lifetime=service.DEFAULT_SERVICE_LIFETIME,
            prepare_hidden=False):
        settings, state = self.root / 'settings.json', self.root / 'service'
        settings.write_text(json.dumps(self.settings), encoding='utf8')
        task = asyncio.create_task(service.serve(settings, state, lifetime,
            prepare_hidden=prepare_hidden))
        self.addAsyncCleanup(self.finish_service, task, state)
        await self.until(lambda: (state / 'status.json').exists())
        session = service.read_json(state / 'session.json')
        return task, state, session

    def test_snapshot_serialization_and_storage_errors_preserve_original_and_remove_staging(self):
        path = self.root / 'snapshot.json'
        original = {'text': 'exact 中文😀\r\n'}
        service.write_json(path, original)
        for invalid in ({'value': float('nan')}, {'value': object()}):
            with self.assertRaises((ValueError, TypeError)):
                service.write_json(path, invalid)
            self.assertEqual(service.read_json(path), original)
            self.assertEqual(list(self.root.glob('*.pending')), [])
        snapshots = service.ServiceSnapshots(self.root)
        snapshots.queue(path.name, {'new': True})
        for error in (OSError(errno.ENOSPC, 'synthetic full storage'),
                      PermissionError(errno.EACCES, 'synthetic non-Windows denial')):
            with patch.object(service.os, 'replace', side_effect=error), self.assertRaises(OSError):
                snapshots.flush()
            self.assertEqual(service.read_json(path), original)
            self.assertEqual(list(self.root.glob('*.pending')), [])
        snapshots.flush()
        self.assertEqual(service.read_json(path), {'new': True})

    @unittest.skipUnless(os.name == 'nt', 'Windows reader sharing semantics')
    def test_windows_reader_blocks_only_snapshot_publication_without_poisoning_next_write(self):
        path = self.root / 'snapshot.json'
        service.write_json(path, {'generation': 0})
        with path.open('rb') as reader:
            with self.assertRaises(PermissionError):
                service.write_json(path, {'generation': 1})
            snapshots = service.ServiceSnapshots(self.root)
            for generation in (2, 3):
                snapshots.queue(path.name, {'generation': generation})
                snapshots.flush()
                self.assertEqual(service.read_json(path), {'generation': 0})
                self.assertEqual(list(self.root.glob('*.pending')), [])
            self.assertEqual(json.loads(reader.read()), {'generation': 0})
        snapshots.flush()
        self.assertEqual(service.read_json(path), {'generation': 3})
        self.assertEqual(snapshots.pending, {})
        service.write_json(path, {'state': 'stopped'})
        self.assertEqual(service.read_json(path), {'state': 'stopped'})

    @unittest.skipUnless(os.name == 'nt', 'Windows reader sharing semantics')
    async def test_locked_status_does_not_cancel_final_response_or_block_explicit_stop(self):
        launches = []
        with self.spawn_fixture('normal', launches):
            task, state, session = await self.start_service()
            path = state / 'status.json'
            before = path.read_bytes()
            with path.open('rb'):
                async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                    async with client.post(session['base_url'] + '/responses', json=self.payload()) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual((await response.json())['output'][0]['content'][0]['text'],
                            message()['content']['parts'][0])
                await asyncio.sleep(.5)
                self.assertFalse(task.done())
                _, health = await asyncio.to_thread(service.live_status, state)
                self.assertTrue(health['accepting_requests'])
                self.assertFalse(health['active'])
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(state.glob('*.pending')), [])
            await self.until(lambda: service.read_json(path)['browser']['completed'] == 1)
            with path.open('rb'), redirect_stderr(io.StringIO()) as errors:
                await self.finish_service(task, state)
            self.assertEqual(json.loads(errors.getvalue())['code'], 'web_service_snapshot_publication_deferred')
            with self.assertRaises(OSError):
                await asyncio.to_thread(service.live_status, state)
            self.assertEqual(len(launches), 1)
            self.assertEqual(list((state / 'requests').iterdir()), [])
            self.assertEqual(list(state.glob('*.pending')), [])

    async def finish_service(self, task, state):
        if not task.done():
            session = service.read_json(state / 'session.json')
            if not (state / 'stop.json').exists():
                service.write_json(state / 'stop.json', {'instance': session['instance']})
        await asyncio.wait_for(task, 5)

    async def test_default_service_has_no_expiry_and_keeps_explicit_stop_and_lazy_browser(self):
        launches = []
        with self.spawn_fixture('normal', launches), patch.object(service, 'time') as clock:
            clock.time.side_effect = time.time
            clock.monotonic.return_value = time.monotonic()
            task, state, session = await self.start_service()
            self.assertIsNone(session['expires_at'])
            clock.monotonic.return_value += 100 * 365 * 24 * 60 * 60
            await asyncio.sleep(0.3)
            self.assertFalse(task.done())
            _, health = await asyncio.to_thread(service.live_status, state)
            self.assertTrue(health['ready'])
            self.assertEqual(launches, [])
            await self.finish_service(task, state)
            self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')
            self.assertEqual(launches, [])

    async def test_saved_service_prepares_hidden_page_before_admitting_a_new_turn(self):
        launches = []
        with self.spawn_fixture('prepare_hold', launches):
            task, state, session = await self.start_service(prepare_hidden=True)
            await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'preparing')
            self.assertEqual(service.read_json(state / 'status.json')['readiness'], 'preparing')
            _, health = await asyncio.to_thread(service.live_status, state)
            self.assertEqual(health['state'], 'preparing')
            self.assertFalse(health['accepting_requests'])
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                async with client.post(session['base_url'] + '/responses', json=self.payload('during-preparation')) as response:
                    self.assertEqual(response.status, 400)
                    error = (await response.json())['error']
                    self.assertEqual((error['code'], error['cause_http_status']),
                        ('web_browser_preparing_before_dispatch', 503))
                self.assertFalse(self.trace.exists())
                self.release.write_bytes(b'page ready')
                await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'ready')
                async with client.post(session['base_url'] + '/responses', json=self.payload('new-after-preparation')) as response:
                    self.assertEqual(response.status, 200)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0]['startupPrepare'])
            await self.until(lambda: service.read_json(state / 'status.json')['browser']['dispatches'] == 1)
            self.assertEqual(service.read_json(state / 'status.json')['browser']['dispatches'], 1)
            await self.finish_service(task, state)
            self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')

    async def test_opt_in_lifetime_expires_and_rejects_invalid_limits_before_creating_state(self):
        launches = []
        with self.spawn_fixture('normal', launches), patch.object(service, 'time') as clock:
            clock.time.side_effect = time.time
            clock.monotonic.return_value = time.monotonic()
            task, state, session = await self.start_service(lifetime=72 * 60 * 60)
            self.assertLessEqual(abs(session['expires_at'] - time.time() - 72 * 60 * 60), 3)
            self.assertEqual(launches, [])
            clock.monotonic.return_value += 72 * 60 * 60 + 1
            await asyncio.wait_for(task, 3)
            self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')
            self.assertEqual(launches, [])
        for limit in (-1, True, 1, 59, 72 * 60 * 60 + 1):
            with self.assertRaisesRegex(ValueError, 'web_service_lifetime_invalid'):
                await service.serve(self.root / 'settings.json', self.root / 'invalid-limit', limit)
            self.assertFalse((self.root / 'invalid-limit').exists())

    async def test_service_defaults_lazy_hidden_and_explicit_cli_assistance_controls_one_worker(self):
        launches = []
        with self.spawn_fixture('normal', launches):
            task, state, session = await self.start_service()
            self.assertEqual(launches, [])
            self.assertEqual(service.read_json(state / 'status.json')['readiness'], 'not_started')
            def request_assistance():
                output = io.StringIO()
                with patch.object(sys, 'argv', ['operator_web_model', 'assist', '--state', str(state)]), redirect_stdout(output):
                    code = service.main()
                return code, json.loads(output.getvalue())
            code, result = await asyncio.to_thread(request_assistance)
            self.assertEqual(code, 0)
            self.assertEqual(result['status'], 'assistance_requested')
            await self.until(lambda: service.read_json(state / 'status.json')['browser']['assistance_state'] == 'awaiting_user')
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                async with client.post(session['base_url'] + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.assertEqual(len(launches), 1)
                self.release.write_bytes(b'closed')
                await self.until(lambda: service.read_json(state / 'status.json')['readiness'] == 'ready')
                async with client.post(session['base_url'] + '/responses', json=self.payload('new')) as response:
                    self.assertEqual(response.status, 200)
            await self.finish_service(task, state)
            self.assertEqual(len(launches), 1)
            self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')

    async def test_service_rejects_assistance_during_request_without_cancelling_that_request(self):
        launches = []
        with self.spawn_fixture('hold', launches):
            task, state, session = await self.start_service()
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                request = asyncio.create_task(client.post(session['base_url'] + '/responses', json=self.payload()))
                await self.until(lambda: self.trace.exists())
                service.write_command(state / 'assist.json', {'instance': session['instance'], 'id': 'e' * 32})
                await self.until(lambda: (state / 'assist-result.json').exists())
                result = service.read_json(state / 'assist-result.json')
                self.assertEqual(result['state'], 'rejected')
                self.assertEqual(result['code'], 'web_assistance_requires_idle_session')
                self.assertFalse(request.done())
                service.write_command(state / 'assist.json', {'instance': session['instance'],
                    'id': 'f' * 32, 'replace_closed_browser': True})
                await self.until(lambda: service.read_json(state / 'assist-result.json').get('id') == 'f' * 32)
                self.assertEqual(service.read_json(state / 'assist-result.json')['code'],
                    'web_assistance_requires_idle_session')
                self.assertFalse(request.done())
                self.assertEqual(len(launches), 1)
                self.release.write_bytes(b'complete')
                response = await asyncio.wait_for(request, 3)
                async with response:
                    self.assertEqual(response.status, 200)
            await self.finish_service(task, state)
            self.assertEqual(len(launches), 1)

    async def test_service_inspection_rejects_missing_page_then_fences_http_until_checked_close(self):
        launches = []
        with self.spawn_fixture('normal', launches):
            task, state, session = await self.start_service()
            command = {'instance':session['instance'], 'id':'1'*32, 'inspect_completed':True}
            service.write_command(state/'assist.json', command)
            await self.until(lambda: (state/'assist-result.json').exists())
            self.assertEqual(service.read_json(state/'assist-result.json')['code'], 'web_inspection_completed_page_required')
            self.assertEqual(launches, [])
            async with ClientSession(headers={'Authorization':'Bearer '+session['token']}) as client:
                async with client.post(session['base_url']+'/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 200)
                service.write_command(state/'assist.json', {**command, 'id':'2'*32})
                await self.until(lambda: service.read_json(state/'status.json')['browser']['assistance_state']=='awaiting_user')
                self.assertIn('只读文字快照', service.service_guidance(service.read_json(state/'status.json')))
                async with client.post(session['base_url']+'/responses', json=self.payload('during-inspection')) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.release.write_bytes(b'closed')
                await self.until(lambda: service.read_json(state/'status.json')['state']=='ready')
                result = service.read_json(state/'status.json')
                self.assertTrue(result['browser']['inspection_available'])
                self.assertEqual(result['browser']['dispatches'], 1)
                async with client.post(session['base_url']+'/responses', json=self.payload('new-after-inspection')) as response:
                    self.assertEqual(response.status, 200)
            await self.finish_service(task, state)
            self.assertEqual(len(launches), 1)

    async def test_service_rejects_another_instances_stop_without_stopping_or_starting_browser(self):
        launches = []
        with self.spawn_fixture('normal', launches):
            task, state, session = await self.start_service()
            service.write_command(state / 'stop.json', {'instance': '0' * 32})
            await self.until(lambda: (state / 'stop-result.json').exists())
            self.assertFalse(task.done())
            self.assertEqual(service.read_json(state / 'stop-result.json')['code'],
                'web_service_stop_identity_changed')
            self.assertFalse((state / 'stop.json').exists())
            _, health = await asyncio.to_thread(service.live_status, state)
            self.assertTrue(health['ready'])
            self.assertEqual(launches, [])
            await self.finish_service(task, state)

    async def test_service_drain_completes_existing_request_and_rejects_new_admission(self):
        launches = []
        with self.spawn_fixture('hold', launches):
            task, state, session = await self.start_service()
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                request = asyncio.create_task(client.post(session['base_url'] + '/responses', json=self.payload()))
                await self.until(lambda: self.trace.exists())
                service.write_command(state / 'stop.json', {'instance': session['instance'], 'drain_seconds': 3})
                await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'draining')
                async with client.post(session['base_url'] + '/responses', json=self.payload('other')) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.assertFalse(request.done())
                self.release.write_bytes(b'complete')
                response = await asyncio.wait_for(request, 3)
                async with response:
                    self.assertEqual(response.status, 200)
            await asyncio.wait_for(task, 3)
            status = service.read_json(state / 'status.json')
            self.assertEqual(status['state'], 'stopped')
            self.assertEqual(status['browser']['completed'], 1)
            self.assertEqual(status['browser']['dispatches'], 1)
            self.assertFalse(status['browser']['process_running'])

    async def test_service_drain_deadline_cancels_owned_request_without_new_worker(self):
        launches = []
        with self.spawn_fixture('cancel', launches):
            task, state, session = await self.start_service()
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                request = asyncio.create_task(client.post(session['base_url'] + '/responses', json=self.payload()))
                await self.until(lambda: self.trace.exists())
                service.write_command(state / 'stop.json', {'instance': session['instance'], 'drain_seconds': 1})
                await asyncio.wait_for(task, 5)
                try:
                    response = await asyncio.wait_for(request, 2)
                except (ConnectionError, asyncio.TimeoutError):
                    request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
                else:
                    async with response:
                        self.assertGreaterEqual(response.status, 400)
            status = service.read_json(state / 'status.json')
            self.assertEqual(status['state'], 'stopped')
            self.assertEqual(status['browser']['cancelled'], 1)
            self.assertEqual(status['browser']['dispatches'], 1)
            self.assertFalse(status['browser']['process_running'])
            self.assertEqual(len(launches), 1)


if __name__ == '__main__':
    unittest.main()
