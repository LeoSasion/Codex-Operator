"""Private manager tests: disposable Python child and loopback health only."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = _OPERATOR_PLUGIN_ROOT
sys.path.insert(0, str(ROOT / 'scripts'))
import operator_web_service as manager


FIXTURE = r'''
import argparse, json, os, secrets, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('action');p.add_argument('--settings');p.add_argument('--state');p.add_argument('--prepare-hidden',action='store_true')
a=p.parse_args();assert a.action=='serve'
assert a.prepare_hidden is True
root=Path(__file__).parent
variant=(root/'variant').read_text()
with (root/'launches').open('a') as f:f.write('launched\n')
if variant=='exit':raise SystemExit(7)
if variant=='slow':time.sleep(2)
state=Path(a.state);state.mkdir(mode=0o700)
ident=secrets.token_hex(16);token=secrets.token_urlsafe(32)
details={'instance':ident,'state':'ready','needs_assistance':False,
 'browser':{'active':False},'transport':{'active_turn':None,'last_turn':None}}
def write(name,value):
 temp=state/(name+'.pending');temp.write_text(json.dumps(value));os.replace(temp,state/name)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  assert self.path=='/health'
  if variant=='redirect':
   self.send_response(302);self.send_header('Location','http://127.0.0.1:1/leak');self.end_headers();return
  if self.headers.get('Authorization')!='Bearer '+token:
   self.send_response(401);self.end_headers();return
  health={'ready':True,'active':False,'state':'ready','accepting_requests':True}
  if (root/'health-extra.json').exists():health.update(json.loads((root/'health-extra.json').read_text()))
  body=json.dumps(health).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=HTTPServer(('127.0.0.1',0),Handler);server.timeout=.03
write('session.json',{'version':1,'instance':ident,'pid':os.getpid(),
 'base_url':'http://127.0.0.1:'+str(server.server_port)+'/v1','token':token,
 'model':'api/chatgpt-web/gpt-5.6-sol' if (root/'route-enabled').exists() else 'fixture',
 'expires_at':None,'mode':'mcp_v1' if (root/'route-enabled').exists() else 'text_only'})
write('status.json',details)
assists=0
while True:
 if (root/'exit-now').exists():break
 assist=state/'assist.json'
 if assist.exists():
  command=json.loads(assist.read_text());assert command['instance']==ident
  assists+=1;write('assist-count.json',{'count':assists,'replace':command.get('replace_closed_browser',False),
   **({'inspect':True} if command.get('inspect_completed') is True else {})})
  assist.unlink()
 stop=state/'stop.json'
 if stop.exists():
  command=json.loads(stop.read_text());assert command['instance']==ident
  assert 0<=command['drain_seconds']<=30
  stop.unlink();write('status.json',{**details,'state':'stopped'});break
 server.handle_request()
server.server_close()
'''


class WebServiceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-web-manager-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / 'fixture.py'
        self.fixture.write_text(FIXTURE, encoding='utf-8')
        (self.root / 'variant').write_text('normal')
        self.browser_profile = self.root / 'browser-profile'
        self.browser_profile.mkdir()
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps({'electron': str(Path(sys.executable).resolve()),
            'profile_directory': str(self.browser_profile), 'session_partition': 'persist:fixture'}))
        self.profile = self.root / 'saved-profile'
        self.children = []
        original_runtime = manager.runtime_identity
        def identity():
            value = original_runtime()
            return {**value, 'backend': str(self.fixture), 'fixture_sha256': manager.file_digest(self.fixture)}
        self.runtime_patch = patch.object(manager, 'runtime_identity', side_effect=identity)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        original_spawn = manager.spawn_child
        def spawn(argv, profile):
            self.assertFalse((profile / 'instances' / manager.current_record(profile)['attempt']).exists())
            self.assertEqual(manager.current_record(profile)['phase'], 'may_have_started')
            child = original_spawn(argv, profile)
            self.children.append(child)
            return child
        self.spawn_patch = patch.object(manager, 'spawn_child', side_effect=spawn)
        self.spawn_mock = self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)
        self.addCleanup(self.finish_children)

    def finish_children(self):
        # Fixture-only cooperative exit; never target any host service.
        (self.root / 'exit-now').write_text('fixture cleanup')
        for child in self.children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)

    def configured(self):
        self.assertEqual(manager.configure(self.profile, self.settings)['status'], 'configured')

    def state(self):
        return manager.state_path(self.profile, manager.current_record(self.profile))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(predicate())

    def snapshot(self):
        return {str(path.relative_to(self.profile)): path.read_bytes()
            for path in self.profile.rglob('*') if path.is_file()}

    def test_configuration_references_existing_settings_without_copying_credentials(self):
        key = self.root / 'runtime-key'; key.write_text('sk-fixture-private-never-copy')
        value = json.loads(self.settings.read_text())
        value.update(transport='mcp_v1', mcp={'mode':'openai_tunnel_v1',
            'tunnel_id':'tunnel_'+'a'*32,
            'tunnel_client':str(Path(sys.executable).resolve()),
            'tunnel_client_sha256':manager.file_digest(Path(sys.executable).resolve()),
            'api_key_file':str(key),'binding_file':str(self.root/'connector.json')})
        self.settings.write_text(json.dumps(value))
        before = self.settings.read_bytes(), key.read_bytes()
        self.configured()
        stored = b''.join(self.snapshot().values())
        self.assertNotIn(key.read_bytes(), stored)
        self.assertNotIn(b'"mcp":', stored)
        self.assertEqual(before, (self.settings.read_bytes(),key.read_bytes()))
        self.spawn_mock.assert_not_called()
        self.assertTrue(manager.configure(self.profile,self.settings)['reused'])

    def test_visible_or_automatic_assistance_settings_rejected_before_profile_write(self):
        base = json.loads(self.settings.read_text())
        for changed in ({'window_mode':'visible'},{'startup_assistance':True},
                {'browser_lifecycle':'per_turn'},{'inline_key':'PRIVATE'}):
            self.settings.write_text(json.dumps({**base,**changed}))
            with self.assertRaisesRegex(ValueError,'hidden_settings_required'):
                manager.configure(self.profile,self.settings)
            self.assertFalse(self.profile.exists())

    def test_start_reuses_owned_authenticated_instance_and_status_never_writes(self):
        self.configured()
        first = manager.start(self.profile)
        self.assertEqual(first['status'],'ready');self.assertFalse(first['reused'])
        before = self.snapshot()
        observed = manager.status(self.profile)
        self.assertEqual(observed['status'],'ready')
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(manager.start(self.profile)['reused'])
        self.assertEqual(len(self.children),1)
        self.assertEqual((self.root/'launches').read_text().splitlines(),['launched'])
        token = manager.read_json(self.state()/'session.json')['token']
        for result in (first,observed,manager.start(self.profile)):
            self.assertNotIn(token,json.dumps(result))
        self.assertFalse((self.state()/'assist.json').exists())

    def test_start_boundary_exists_before_spawn_and_launch_failure_never_retries(self):
        self.configured()
        def failed(*_):
            self.assertEqual(manager.current_record(self.profile)['phase'],'may_have_started')
            raise OSError('PRIVATE diagnostic')
        with patch.object(manager,'spawn_child',side_effect=failed) as spawn:
            with self.assertRaises(OSError):manager.start(self.profile)
            with self.assertRaisesRegex(ValueError,'ownership_unknown'):manager.start(self.profile)
        self.assertEqual(spawn.call_count,1)
        self.assertEqual(manager.current_record(self.profile)['phase'],'uncertain')

    def test_late_readiness_can_be_observed_without_second_start(self):
        (self.root/'variant').write_text('slow')
        self.configured()
        result=manager.start(self.profile,observation_seconds=0)
        self.assertEqual(result['status'],'starting')
        self.assertEqual(manager.start(self.profile)['status'],'starting')
        self.wait_for(lambda:(self.state()/'status.json').exists())
        self.assertEqual(manager.status(self.profile)['status'],'ready')
        self.assertTrue(manager.start(self.profile)['reused'])
        self.assertEqual(len(self.children),1)

    def test_operation_lock_coalesces_another_start_without_spawn(self):
        self.configured()
        with manager.operation_lock(self.profile):
            with self.assertRaisesRegex(ValueError,'operation_in_progress'):
                manager.start(self.profile)
        self.spawn_mock.assert_not_called()
        self.assertIsNone(manager.current_record(self.profile))
        self.assertEqual(manager.start(self.profile)['status'],'ready')

    def test_start_uses_configuration_read_after_operation_lock(self):
        self.configured()
        settings=self.root/'updated-settings.json';settings.write_bytes(self.settings.read_bytes())
        replacement=manager.read_json(self.profile/'profile.json')
        replacement['settings']=manager.settings_identity(settings)
        original=manager.load_profile
        switched=False
        def load(*args,**kwargs):
            nonlocal switched
            result=original(*args,**kwargs)
            if not switched:
                switched=True
                # Simulate another completed stopped configure between the
                # initial path read and our operation-lock acquisition.
                manager.service.write_json(self.profile/'profile.json',replacement)
            return result
        with patch.object(manager,'load_profile',side_effect=load):
            self.assertEqual(manager.start(self.profile)['status'],'ready')
        argv=self.spawn_mock.call_args.args[0]
        self.assertEqual(argv[argv.index('--settings')+1],str(settings))

    def test_explicit_stop_and_clean_restart_use_new_state_keep_original_settings(self):
        self.configured();manager.start(self.profile)
        first=manager.current_record(self.profile)
        original=self.settings.read_bytes()
        self.assertEqual(manager.control(self.profile,'stop',drain_seconds=2)['status'],'stop_requested')
        self.children[0].wait(timeout=5)
        self.assertEqual(manager.status(self.profile)['status'],'stopped')
        self.assertEqual(manager.control(self.profile,'stop')['status'],'stopped')
        second=manager.start(self.profile)
        self.assertFalse(second['reused'])
        self.assertNotEqual(manager.current_record(self.profile)['attempt'],first['attempt'])
        self.assertTrue((self.profile/'instances'/(first['attempt']+'.json')).is_file())
        self.assertEqual(self.settings.read_bytes(),original)
        self.assertEqual(len(self.children),2)

    def test_crashed_child_and_existing_tunnel_marker_never_restarted_or_deleted(self):
        self.configured();manager.start(self.profile)
        marker=self.root/'active-tunnel-fixture.json';marker.write_bytes(b'owned tunnel marker')
        (self.root/'exit-now').write_text('fixture abnormal exit')
        self.children[0].wait(timeout=5)
        with self.assertRaisesRegex(ValueError,'uncertain_stop_no_retry'):
            manager.start(self.profile)
        self.assertEqual(marker.read_bytes(),b'owned tunnel marker')
        self.assertEqual(len(self.children),1)

    def test_only_explicit_assist_requests_a_window_and_exact_replacement_flag(self):
        self.configured();manager.start(self.profile)
        self.assertEqual(manager.control(self.profile,'assist')['status'],'assistance_requested')
        self.wait_for(lambda:(self.state()/'assist-count.json').exists())
        self.assertEqual(manager.read_json(self.state()/'assist-count.json'),{'count':1,'replace':False})
        self.assertEqual(manager.control(self.profile,'assist',replace_closed_browser=True)['status'],'assistance_requested')
        self.wait_for(lambda:manager.read_json(self.state()/'assist-count.json')['count']==2)
        self.assertTrue(manager.read_json(self.state()/'assist-count.json')['replace'])
        self.assertEqual(len(self.children),1)

    def test_session_instance_or_token_change_blocks_control_without_command(self):
        self.configured();manager.start(self.profile)
        path=self.state()/'session.json';original=path.read_bytes()
        for key,value in (('instance','f'*32),('token','x'*43),('pid',os.getpid())):
            changed=json.loads(original);changed[key]=value
            manager.service.write_json(path,changed)
            with self.assertRaisesRegex(ValueError,'session_(changed|invalid)'):
                manager.control(self.profile,'assist')
            self.assertFalse((self.state()/'assist.json').exists())
            path.write_bytes(original)

    def test_inspect_uses_exact_live_instance_without_replacement_or_reconfiguration(self):
        self.configured(); manager.start(self.profile)
        original = (self.profile/'profile.json').read_bytes()
        self.assertEqual(manager.control(self.profile, 'inspect')['status'], 'inspection_requested')
        self.wait_for(lambda: (self.state()/'assist-count.json').exists())
        self.assertEqual(manager.read_json(self.state()/'assist-count.json'), {'count':1,'replace':False,'inspect':True})
        with self.assertRaisesRegex(ValueError, 'web_manager_replacement_invalid'):
            manager.control(self.profile, 'inspect', replace_closed_browser=True)
        self.assertEqual((self.profile/'profile.json').read_bytes(), original)
        self.assertEqual(len(self.children), 1)

    def test_inspection_guidance_does_not_request_login_again(self):
        text = manager.safe_guidance({'state':'assistance','needs_assistance':True,
            'assistance':{'inspect_completed':True}}, {'active':False})
        self.assertIn('只读文字快照', text)
        self.assertNotIn('登录', text)

    def test_changed_process_birth_blocks_control_even_with_valid_session(self):
        self.configured();manager.start(self.profile)
        owner=manager.current_record(self.profile)['process']
        with patch.object(manager,'process_identity',return_value={**owner,'birth':owner['birth']+'1'}):
            with self.assertRaisesRegex(ValueError,'process_identity_changed'):
                manager.control(self.profile,'stop')
        self.assertFalse((self.state()/'stop.json').exists())

    def test_pid_reuse_after_verified_clean_stop_does_not_control_new_process_or_block_start(self):
        self.configured();manager.start(self.profile)
        old=manager.current_record(self.profile)
        manager.control(self.profile,'stop');self.children[0].wait(timeout=5)
        previous={item['pid']:{**item,'birth':item['birth']+'1'}
            for item in (old['process'],old['worker'])}
        original=manager.process_identity
        with patch.object(manager,'process_identity',side_effect=lambda pid:previous.get(pid) or original(pid)):
            self.assertEqual(manager.status(self.profile)['status'],'stopped')
            self.assertEqual(manager.control(self.profile,'stop')['status'],'stopped')
            self.assertFalse(manager.start(self.profile)['reused'])
        self.assertEqual(len(self.children),2)
        old_state=self.profile/'instances'/old['attempt']
        self.assertFalse((old_state/'stop.json').exists())

    def test_exact_settings_and_source_changes_block_reuse_without_rewriting(self):
        self.configured();manager.start(self.profile)
        original=self.settings.read_bytes();self.settings.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'settings_changed'):manager.start(self.profile)
        self.settings.write_bytes(original)
        self.fixture.write_text(FIXTURE+'\n# changed source\n')
        with self.assertRaisesRegex(ValueError,'runtime_changed'):manager.start(self.profile)
        self.assertEqual(len(self.children),1)

    def test_source_upgrade_keeps_status_and_exact_stop_then_explicit_update_preserves_old_config(self):
        self.configured();manager.start(self.profile)
        old_config=(self.profile/'profile.json').read_bytes()
        self.fixture.write_text(FIXTURE+'\n# reviewed upgrade\n')
        result=manager.status(self.profile)
        self.assertEqual(result['status'],'ready');self.assertFalse(result['configuration_current'])
        with self.assertRaisesRegex(ValueError,'stopped_update_required'):
            manager.configure(self.profile,self.settings)
        self.assertEqual(manager.control(self.profile,'stop')['status'],'stop_requested')
        self.children[0].wait(timeout=5)
        self.assertTrue(manager.configure(self.profile,self.settings)['updated'])
        history=list((self.profile/'history').glob('profile-*.json'))
        self.assertEqual(len(history),1)
        self.assertEqual(json.loads(history[0].read_bytes()),json.loads(old_config))
        self.assertFalse(manager.start(self.profile)['reused'])

    def test_untrusted_status_counts_and_unknown_errors_never_enter_output(self):
        self.configured();manager.start(self.profile)
        path=self.state()/'status.json';details=manager.read_json(path)
        details['transport']={'active_turn':{'calls_released':'private_value','results_received':'private_value'}}
        manager.service.write_json(path,details)
        self.assertNotIn('private_value',json.dumps(manager.status(self.profile)))
        from operator_core.responses_capabilities import RouterError
        self.assertNotIn('private_value',json.dumps(manager.error_result(RouterError('private_value'))))
        details['state']='private_value';manager.service.write_json(path,details)
        with self.assertRaisesRegex(ValueError,'status_invalid'):manager.status(self.profile)

    def test_status_separates_network_and_delivery_without_probing_or_leaking(self):
        self.configured();manager.start(self.profile)
        path=self.state()/'status.json';base=manager.read_json(path)
        secret='PRIVATE page text, endpoint, token and alleged safety rejection'
        turn={'sequence':99,'calls_accepted':0,'calls_released':0,'results_received':0,
            'public_final_returned':True,'outcome':secret,'pending_call':secret}
        health=self.root/'health-extra.json'
        health.write_text(json.dumps({'transport':{'scope':'transport_only','active_turn':None,
            'last_turn':turn},'unknown':secret}))
        def observe(event, *, attempt=7, events=None):
            manager.service.write_json(path,{**base,'browser':{'attempts':attempt,'events':
                [event] if events is None else events,'unknown':secret},'unknown':secret})
            before=self.snapshot()
            result=manager.status(self.profile)
            self.assertEqual(before,self.snapshot())
            self.assertEqual(result['status'],'ready')
            self.assertNotIn(secret,json.dumps(result))
            self.assertEqual(len(self.children),1)
            self.assertFalse((self.state()/'assist.json').exists())
            return result['diagnostics']
        event={'attempt':7,'kind':'model_network_state','phase':'response_started',
            'status':200,'networkError':None,'url':secret,'error':secret}
        observed=observe(event)
        self.assertEqual(observed['network'],{'scope':'saved_browser_attempt','state':'http_response','http_status':200})
        self.assertEqual(observed['tools'],{'scope':'local_transport_only','state':'last_turn',
            'calls_accepted':0,'calls_released':0,'results_received':0,'public_final_returned':True})
        # Different observation counters are not joined into one claimed request.
        self.assertNotIn('sequence',observed['tools'])
        reset={**event,'phase':'error','status':None,'networkError':'net::ERR_CONNECTION_RESET'}
        self.assertEqual(observe(reset)['network']['state'],'network_error')
        self.assertEqual(observe(reset,attempt=8)['network']['state'],'unknown')
        self.assertEqual(observe(reset,events=[reset,event])['network']['state'],'http_response')
        for error,expected in [('net::ERR_ABORTED','aborted'),(secret,'other_error'),(None,'unknown')]:
            with self.subTest(error=error):
                self.assertEqual(observe({**reset,'networkError':error})['network']['state'],expected)
        for invalid in ({**event,'status':True},{**event,'status':700},{**event,'attempt':True}):
            self.assertEqual(observe(invalid)['network']['state'],'unknown')
        self.assertEqual(observe(event,events=[event]*129)['network']['state'],'unknown')
        self.assertEqual(observe(event,attempt=True)['network']['state'],'unknown')
        for bad in (secret,True,-1,9007199254740992,1):
            health.write_text(json.dumps({'transport':{'scope':'transport_only','active_turn':
                {**turn,'calls_released':bad},'last_turn':turn}}))
            self.assertEqual(observe(event)['tools']['state'],'unknown')
        health.write_text(json.dumps({'transport':{'scope':'transport_only','active_turn':
            {**turn,'calls_accepted':2,'calls_released':2,'results_received':1},'last_turn':None}}))
        self.assertEqual(observe(event)['tools']['state'],'active')
        self.assertEqual(observe(event)['tools']['results_received'],1)

    def test_pointer_cannot_select_state_outside_owned_profile(self):
        self.configured()
        manager.service.write_json(self.profile/'current.json',{'version':1,'attempt':'../outside'})
        with self.assertRaisesRegex(ValueError,'pointer_invalid'):manager.start(self.profile)
        self.spawn_mock.assert_not_called()

    def test_health_redirect_is_rejected_without_following_or_launching_again(self):
        (self.root/'variant').write_text('redirect')
        self.configured()
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as raised:manager.start(self.profile)
        self.assertEqual(raised.exception.code,302)
        with self.assertRaises(HTTPError):manager.start(self.profile)
        self.assertEqual(len(self.children),1)

    def test_existing_fixed_connection_lock_rejects_before_launch_boundary_and_stays_unchanged(self):
        key = self.root / 'runtime-key'; key.write_text('sk-fixture-private-never-read')
        value = json.loads(self.settings.read_bytes())
        value.update(transport='mcp_v1', mcp={'mode':'openai_tunnel_v1',
            'tunnel_id':'tunnel_'+'a'*32, 'tunnel_client':str(Path(sys.executable).resolve()),
            'tunnel_client_sha256':manager.file_digest(Path(sys.executable).resolve()),
            'api_key_file':str(key), 'binding_file':str(self.root/'connector.json')})
        self.settings.write_text(json.dumps(value))
        marker = self.root / ('active-tunnel_'+'a'*32+'.json')
        marker.write_bytes(b'private existing ownership record')
        self.configured()
        before = self.snapshot()
        report = manager.status(self.profile)
        self.assertEqual(report['status'], 'configured')
        self.assertFalse(report['start_available'])
        self.assertEqual(report['reason'], 'web_manager_fixed_connection_in_use')
        self.assertNotIn('private', json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'fixed_connection_in_use'):
            manager.start(self.profile)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(marker.read_bytes(), b'private existing ownership record')
        self.assertEqual(key.read_text(), 'sk-fixture-private-never-read')
        self.spawn_mock.assert_not_called()

    def test_fixed_connection_missing_identity_is_rejected_before_saving_profile(self):
        value=json.loads(self.settings.read_bytes())
        value.update(transport='mcp_v1',mcp={'mode':'openai_tunnel_v1'})
        self.settings.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'fixed_connection_required'):
            manager.configure(self.profile,self.settings)
        self.assertFalse(self.profile.exists())

    def route_fixture(self):
        (self.root/'route-enabled').write_text('synthetic tools service')
        self.configured()
        manager.start(self.profile)

    def test_route_snapshot_checks_live_owner_without_writes_or_key_output(self):
        self.route_fixture()
        before = self.snapshot()
        preview = manager.route_preview(self.profile)
        route = manager.resolve_route(self.profile, preview)
        session = manager.read_json(self.state()/'session.json')
        self.assertEqual(route.api_base, session['base_url'])
        self.assertEqual(route.key(), session['token'])
        self.assertEqual(route.model, session['model'])
        self.assertEqual(set(preview), {'profile_sha256','session_sha256'})
        self.assertNotIn(session['token'], repr(route) + repr(route.web_binding) + json.dumps(preview))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(self.children), 1)

    def test_route_can_bind_late_ready_launch_without_second_start_or_record_mutation(self):
        (self.root/'route-enabled').write_text('synthetic tools service')
        (self.root/'variant').write_text('slow')
        self.configured()
        self.assertEqual(manager.start(self.profile,observation_seconds=0)['status'],'starting')
        self.wait_for(lambda: (self.state()/'status.json').is_file())
        record=manager.current_record(self.profile)
        self.assertNotIn('session_sha256',record)
        before=self.snapshot()
        preview=manager.route_preview(self.profile)
        route=manager.resolve_route(self.profile,preview)
        self.assertEqual(route.web_binding.session_sha256,preview['session_sha256'])
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(len(self.children),1)
        with self.assertRaisesRegex(ValueError,'tools_route_required'):
            manager.resolve_route(self.profile,{**preview,'session_sha256':'0'*64})

    def test_route_snapshot_rejects_changed_digest_and_stopped_instance(self):
        self.route_fixture()
        preview = manager.route_preview(self.profile)
        for field in preview:
            with self.assertRaisesRegex(ValueError, 'route_digest_changed'):
                manager.resolve_route(self.profile, {**preview, field:'0'*64})
        manager.control(self.profile,'stop')
        self.children[0].wait(timeout=5)
        with self.assertRaisesRegex(ValueError, 'idle_ready_required'):
            manager.resolve_route(self.profile, preview)
        manager.start(self.profile)
        with self.assertRaisesRegex(ValueError, 'route_digest_changed'):
            manager.resolve_route(self.profile, preview)

    def test_route_preview_rejects_text_only_and_tampered_source(self):
        self.configured()
        manager.start(self.profile)
        with self.assertRaisesRegex(ValueError,'tools_route_required'):
            manager.route_preview(self.profile)
        self.fixture.write_text(self.fixture.read_text()+'\n# changed')
        with self.assertRaisesRegex(ValueError,'runtime_changed'):
            manager.route_preview(self.profile)

    def test_route_snapshot_rejects_health_failure_and_profile_change(self):
        self.route_fixture()
        preview = manager.route_preview(self.profile)
        with patch.object(manager, 'observe', side_effect=OSError('private detail')):
            with self.assertRaises(OSError):
                manager.resolve_route(self.profile, preview)
        raw = (self.profile/'profile.json').read_bytes()
        (self.profile/'profile.json').write_bytes(raw+b'\n')
        with self.assertRaisesRegex(ValueError,'route_digest_changed'):
            manager.resolve_route(self.profile, preview)

    def test_cli_error_is_sanitized_and_status_has_no_writes(self):
        self.configured()
        before=self.snapshot()
        output=io.StringIO()
        with patch.object(sys,'argv',['operator_web_service','status','--profile',str(self.profile)]),redirect_stdout(output):
            self.assertEqual(manager.main(),0)
        self.assertEqual(json.loads(output.getvalue())['status'],'configured')
        self.assertEqual(self.snapshot(),before)
        output=io.StringIO()
        with patch.object(sys,'argv',['operator_web_service','start','--profile',str(self.profile)]),\
                patch.object(manager,'start',side_effect=OSError('sk-PRIVATE')),redirect_stdout(output):
            self.assertEqual(manager.main(),1)
        self.assertNotIn('sk-PRIVATE',output.getvalue())


@unittest.skipUnless(os.name == 'nt', 'Windows independent service lifecycle')
class WindowsDetachedLaunchTests(unittest.TestCase):
    def test_child_survives_exact_launcher_job_and_preserves_arguments_environment(self):
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(key, ctypes.c_ulonglong) for key in ('read', 'write', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory(prefix="operator 独立 ' $") as directory:
            root = Path(directory).resolve()
            fixture = root/'child.py'
            fixture.write_text('''import json,os,sys,time
from pathlib import Path
root=Path(__file__).parent
(root/'alive.pending').write_text(json.dumps({'args':sys.argv[1:],'private_env':os.environ.get('OPERATOR_FIXTURE_SECRET')}))
os.replace(root/'alive.pending',root/'alive.json')
while not (root/'stop').exists():time.sleep(.03)
''', encoding='utf-8')
            args = ['中文 😀', 'a "quote"', 'C:\\path with space\\', '$(fixture);`literal']
            launcher = root/'launcher.py'
            launcher.write_text('''import json,sys,time
from pathlib import Path
sys.path[:0] = %r
import operator_web_service as manager
root=Path(__file__).parent
while not (root/'go').exists():time.sleep(.03)
child=manager.spawn_windows_child(%r,root)
(root/'launched.json').write_text(json.dumps({'pid':child.pid}))
while True:time.sleep(.1)
''' % ([str(ROOT/'scripts'), *sys.path], [str(Path(sys._base_executable).resolve()), str(fixture), *args]), encoding='utf-8')
            job = kernel.CreateJobObjectW(None, None); self.assertTrue(job)
            limits = Extended(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE, this disposable launcher only.
            self.assertTrue(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            child = None
            error_path = root/'launch-error.txt'
            with error_path.open('wb') as errors:
                parent = subprocess.Popen([sys._base_executable, str(launcher)],
                env={**os.environ, 'OPERATOR_FIXTURE_SECRET':'must-not-inherit'},
                stdout=subprocess.DEVNULL, stderr=errors, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                self.assertTrue(kernel.AssignProcessToJobObject(job, int(parent._handle)))
                (root/'go').write_text('fixture release')
                deadline = time.monotonic()+25
                while not (root/'launched.json').exists() and time.monotonic()<deadline:
                    self.assertIsNone(parent.poll(),error_path.read_text(encoding='utf-8',errors='replace')); time.sleep(.05)
                self.assertTrue((root/'launched.json').exists())
                child = manager.DetachedWindowsChild(json.loads((root/'launched.json').read_bytes())['pid'])
                inside = wintypes.BOOL()
                self.assertTrue(kernel.IsProcessInJob(child.handle, job, ctypes.byref(inside)))
                self.assertFalse(inside.value)
                kernel.CloseHandle(job); job = None
                parent.wait(timeout=5)
                self.assertIsNone(child.poll())
                # CIM process creation is not interpreter readiness. Observe the
                # same owned child after closing its launcher's job; never spawn
                # again or assume its report already exists under scheduler load.
                ready_deadline = time.monotonic()+5
                while not (root/'alive.json').exists() and time.monotonic()<ready_deadline:
                    self.assertIsNone(child.poll())
                    time.sleep(.03)
                self.assertTrue((root/'alive.json').exists(), 'Owned child did not publish readiness')
                report = json.loads((root/'alive.json').read_bytes())
                self.assertEqual(report, {'args':args,'private_env':None})
                (root/'stop').write_text('cooperative child exit')
                self.assertEqual(child.wait(timeout=5), 0)
            finally:
                (root/'stop').write_text('fixture cleanup')
                if job: kernel.CloseHandle(job)
                if parent.poll() is None: parent.kill()
                parent.wait(timeout=5)
                if child:
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)

    def test_uncertain_cim_result_has_one_attempt_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(manager.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture',20)) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    manager.spawn_windows_child([sys.executable, 'fixture'], Path(directory))
                self.assertEqual(run.call_count, 1)


@unittest.skipUnless(os.name == 'nt', 'Windows explicit dead-instance retirement')
class WebServiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-dead-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.profile = self.root/'profile'
        browser = self.root/'browser'; browser.mkdir()
        key = self.root/'key'; key.write_text('private-key-never-read')
        self.settings = self.root/'settings.json'
        self.settings.write_text(json.dumps({'electron':str(Path(sys.executable).resolve()),
            'profile_directory':str(browser),'session_partition':'persist:fixture','transport':'mcp_v1',
            'mcp':{'mode':'openai_tunnel_v1','tunnel_id':'tunnel_'+'a'*32,
                'tunnel_client':str(Path(sys.executable).resolve()),
                'tunnel_client_sha256':manager.file_digest(Path(sys.executable).resolve()),
                'api_key_file':str(key),'binding_file':str(self.root/'binding.json')}}))
        manager.configure(self.profile,self.settings)
        self.config = manager.read_json(self.profile/'profile.json')
        identity = {'pid':87654321,'birth':'12345','executable':self.config['runtime']['python']}
        self.record = {'version':1,'attempt':'b'*32,'phase':'running','runtime':self.config['runtime'],
            'process':identity,'worker':identity,'instance':'c'*32}
        self.state = manager.state_path(self.profile,self.record); self.state.mkdir()
        manager.service.write_json(self.state/'session.json',{'version':1,'pid':identity['pid'],
            'instance':'c'*32,'base_url':'http://127.0.0.1:32123/v1','token':'f'*43})
        self.record['session_sha256'] = manager.digest((self.state/'session.json').read_bytes())
        manager.save_record(self.profile,self.record)
        manager.service.write_json(self.profile/'current.json',{'version':1,'attempt':'b'*32})
        manager.service.write_json(self.state/'status.json',{'instance':'c'*32,'state':'ready'})
        manager.service.write_json(self.state/'connection.json',{'instance':'c'*32,
            'connection_id':'d'*32,'tunnel_id':'tunnel_'+'a'*32,'kind':'fixed_openai_tunnel'})
        self.marker = self.root/('active-tunnel_'+'a'*32+'.json')
        manager.service.write_json(self.marker,{'version':1,'instance':'d'*32,'pid':identity['pid'],'state':str(self.state)})
        for target, value in [('process_identity',None),('windows_process_entries',[])]:
            patcher=patch.object(manager,target,return_value=value);patcher.start();self.addCleanup(patcher.stop)

    def snapshot(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_preview_is_read_only_and_retirement_preserves_originals_without_launch(self):
        before = self.snapshot()
        preview = manager.recover(self.profile)
        self.assertEqual(before,self.snapshot())
        with patch.object(manager,'spawn_child') as spawn:
            self.assertEqual(manager.recover(self.profile,expected_preview=preview['preview_sha256'])['status'],'recovered')
            spawn.assert_not_called()
        self.assertIsNone(manager.current_record(self.profile)); self.assertFalse(self.marker.exists())
        for name in ('status.json','session.json','connection.json'):
            self.assertEqual((self.state/name).read_bytes(),before[str((self.state/name).relative_to(self.root))])
        self.assertEqual(manager.read_json(self.profile/'instances'/('b'*32+'.json')),self.record)
        archived = list(self.root.glob('retired-recovery-*-active-*.json'));self.assertEqual(len(archived),1)
        self.assertEqual(archived[0].read_bytes(),before[self.marker.name])
        receipts = list((self.profile/'history').glob('recovery-*/receipt.json'));self.assertEqual(len(receipts),1)
        receipt = manager.read_json(receipts[0]); self.assertEqual(receipt['phase'],'retired')
        self.assertFalse(receipt['replayed']);self.assertFalse(receipt['launched'])
        self.assertNotIn(b'private-key-never-read',b''.join(p.read_bytes() for p in (self.profile/'history').rglob('*') if p.is_file()))

    def test_changed_preview_live_reused_or_unknown_process_rejects_without_mutation(self):
        preview=manager.recover(self.profile);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'recovery_changed'):
            manager.recover(self.profile,expected_preview='0'*64)
        for observed,code in [(self.record['process'],'recovery_not_dead'),
                ({**self.record['process'],'birth':'999'},'identity_changed')]:
            with patch.object(manager,'process_identity',return_value=observed):
                with self.assertRaisesRegex(ValueError,code):manager.recover(self.profile)
        with patch.object(manager,'process_identity',side_effect=OSError('unobservable')):
            with self.assertRaises(OSError):manager.recover(self.profile)
        self.assertEqual(before,self.snapshot())
        path=self.state/'status.json';path.write_bytes(path.read_bytes()+b'\n')
        changed=self.snapshot()
        with self.assertRaisesRegex(ValueError,'recovery_changed'):
            manager.recover(self.profile,expected_preview=preview['preview_sha256'])
        self.assertEqual(changed,self.snapshot())

    def test_remaining_dependency_or_mismatched_marker_blocks_retirement(self):
        executable = self.config['settings']['dependencies']['electron']['path']
        with patch.object(manager,'windows_process_entries',return_value=[{'pid':123,'name':Path(executable).name}]),\
                patch.object(manager,'process_identity',side_effect=lambda pid: {'executable':executable} if pid==123 else None):
            with self.assertRaisesRegex(ValueError,'dependencies_live'):manager.recover(self.profile)
        original=self.marker.read_bytes();value=json.loads(original);value['pid']=111
        manager.service.write_json(self.marker,value);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'marker_invalid'):manager.recover(self.profile)
        self.assertEqual(before,self.snapshot())
        self.marker.write_bytes(original)
        os.link(self.marker,self.root/'marker-hardlink')
        with self.assertRaisesRegex(ValueError,'marker_invalid'):manager.recover(self.profile)

    def test_interrupted_retirement_keeps_journal_and_never_claims_clean_stop(self):
        preview=manager.recover(self.profile);old_status=(self.state/'status.json').read_bytes()
        original=manager.os.rename
        def fail_pointer(source,destination):
            if Path(source)==self.profile/'current.json':raise OSError('fixture interruption')
            return original(source,destination)
        with patch.object(manager.os,'rename',side_effect=fail_pointer):
            with self.assertRaises(OSError):manager.recover(self.profile,expected_preview=preview['preview_sha256'])
        self.assertTrue((self.profile/'current.json').exists());self.assertFalse(self.marker.exists())
        receipt=manager.read_json(next((self.profile/'history').glob('recovery-*/receipt.json')))
        self.assertEqual(receipt['phase'],'marker_archived');self.assertEqual((self.state/'status.json').read_bytes(),old_status)
        with self.assertRaises(ValueError):manager.start(self.profile)

    def unbind_stopped_fixture(self):
        self.record = {key: value for key, value in self.record.items()
            if key not in ('worker', 'instance', 'session_sha256')}
        self.record['phase'] = 'starting'
        manager.save_record(self.profile, self.record)
        manager.service.write_json(self.state/'status.json', {'instance':'c'*32, 'state':'stopped',
            'requests':0, 'browser':{'active':False}, 'transport':{'active_turn':None}})
        self.marker.unlink()

    def test_unbound_request_free_stopped_launch_can_be_explicitly_retired_without_binding(self):
        self.unbind_stopped_fixture()
        before = self.snapshot()
        preview = manager.recover(self.profile)
        self.assertEqual(before, self.snapshot())
        manager.recover(self.profile, expected_preview=preview['preview_sha256'])
        self.assertEqual(manager.read_json(self.profile/'instances'/('b'*32+'.json')), self.record)
        receipt = manager.read_json(next((self.profile/'history').glob('recovery-*/receipt.json')))
        self.assertEqual(receipt['outcome'], 'unbound_request_free_stopped_snapshot_retired')
        self.assertFalse(receipt['launched']); self.assertFalse(receipt['replayed'])

    def test_unbound_launch_with_requests_live_worker_or_marker_cannot_be_retired(self):
        self.unbind_stopped_fixture()
        for changes in ({'requests':1}, {'requests':False}, {'state':'ready'}, {'browser':{'active':True}},
                {'transport':{'active_turn':{'sequence':1}}}):
            original = (self.state/'status.json').read_bytes()
            manager.service.write_json(self.state/'status.json', {**json.loads(original), **changes})
            before = self.snapshot()
            with self.assertRaises(ValueError): manager.recover(self.profile)
            self.assertEqual(before, self.snapshot())
            (self.state/'status.json').write_bytes(original)
        with patch.object(manager, 'process_identity', return_value=self.record['process']):
            with self.assertRaises(ValueError): manager.recover(self.profile)
        self.marker.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'marker_invalid'): manager.recover(self.profile)


class WebReadOnlyUninstallDependencyTests(unittest.TestCase):
    def test_configured_web_profile_can_be_checked_without_aiohttp(self):
        with tempfile.TemporaryDirectory(prefix='operator-web-read-only-') as directory:
            project = Path(directory).resolve()
            home = project / 'home'; home.mkdir()
            config = home / 'config.toml'; config.write_bytes(b'')
            browser = project / 'browser'; browser.mkdir()
            settings = project / 'settings.json'
            settings.write_text(json.dumps({'electron': str(Path(sys.executable).resolve()),
                'profile_directory': str(browser), 'session_partition': 'persist:fixture'}))
            profile = project / '.codex/operator-web-service'
            profile.parent.mkdir()
            manager.configure(profile, settings)
            original = {str(path): path.read_bytes() for path in project.rglob('*') if path.is_file()}
            child = ('import importlib.util, pathlib, sys; '
                'assert importlib.util.find_spec("aiohttp") is None; '
                'sys.path.insert(0, sys.argv[1]); import operator_uninstall; '
                'operator_uninstall.inspect_web_startup(pathlib.Path(sys.argv[2]), '
                'pathlib.Path(sys.argv[3]))')
            environment = os.environ.copy()
            environment.pop('PYTHONPATH', None)
            result = subprocess.run([sys.executable, '-S', '-c', child,
                str(ROOT / 'scripts'), str(project), str(config)],
                capture_output=True, text=True, timeout=15, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({str(path): path.read_bytes() for path in project.rglob('*') if path.is_file()},
                original)


if __name__ == '__main__':
    unittest.main()
