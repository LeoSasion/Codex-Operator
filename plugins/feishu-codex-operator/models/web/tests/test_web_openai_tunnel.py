"""Fixed identity, real loopback MCP/Responses and owned synthetic child tests."""

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
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / 'scripts'))
import operator_web_model as service
from operator_core.web_openai_tunnel import WebOpenAITunnel, poll_timestamp, tunnel_environment
from operator_core.web_mcp_transport import WebMcpEndpoint
from operator_web_tunnel_setup import save_profile
from test_web_connection import BROWSER, CONNECTOR as ASCII_CONNECTOR, FUNCTION, RESULT

CONNECTOR = {**ASCII_CONNECTOR, 'name': 'Operator 固定连接'}


TUNNEL = r'''import json,os,sys,time,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
c=json.loads(Path(sys.argv[-1]).read_text());control=c['control_plane']
assert sys.argv[1:3]==['run','--profile-file']
assert control['api_key'].startswith('file:') and control['poll_channels']==['main']
key=Path(control['api_key'][5:]).read_text()
assert key not in str(sys.argv) and key not in str(os.environ)
assert 'MCP_COMMAND' not in os.environ and 'LOG_HTTP_RAW_UNSAFE' not in os.environ
assert c['admin_ui']['open_browser'] is False and 'cloudflared' not in c
assert c['mcp']['server_urls'][0]['url'].startswith('http://127.0.0.1:')
trigger=Path(TRIGGER)
def mode():return trigger.read_text() if trigger.exists() else ''
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  state=mode();status=200;body=b''
  if self.path=='/readyz':
   status=503 if state in ('idle','auth','no_poll') else 200
   body=b'not ready' if status==503 else b'ready'
  elif self.path=='/metrics':
   stamp=0 if state in ('idle','auth','no_poll') else int(time.time())
   if state=='bad_metric':body=b'commands_poll_last_successful_timestamp_seconds 1e999\n'
   else:body=('commands_poll_last_successful_timestamp_seconds{otel_scope_name="controlplane"} '+str(float(stamp))+'\n').encode()
  else:status=404
  self.send_response(status);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
Path(c['health']['url_file']).write_text('http://127.0.0.1:'+str(server.server_port))
last=''
while True:
 state=mode()
 if state!=last and state in ('idle','auth'):
  print(json.dumps({'msg':'poll failed; backing off','status_code':403 if state=='auth' else 503,'error':'private fixture data'}),flush=True)
 if state=='exit':raise SystemExit(3)
 last=state;time.sleep(.01)
'''


class FixedTunnelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fixed-tunnel-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / 'fixed-profile'
        self.key = 'sk-' + 'x' * 24
        self.settings = save_profile(self.profile, Path(sys.executable), 'tunnel_' + 'a' * 32, self.key)
        self.trigger = self.root / 'trigger.fixture'
        self.exit_browser = self.root / 'browser-exit.fixture'
        self.release_assist = self.root / 'assist.fixture'
        self.launches, self.children = [], []
        self.endpoint = self.connection = None
        original_spawn = asyncio.create_subprocess_exec
        original_init = WebOpenAITunnel.__init__

        def capture(connection, *args, **kwargs):
            original_init(connection, *args, **kwargs)
            self.connection, self.endpoint = connection, connection.endpoint

        async def spawn(*args, **kwargs):
            self.launches.append((args, kwargs))
            if args[1] == 'run':
                code = 'TRIGGER=' + repr(str(self.trigger)) + '\n' + TUNNEL
                arguments = args[1:]
            else:
                code = ('URL=' + repr('http://' + self.endpoint.host + self.endpoint.path)
                    + '\nCONNECTOR=' + repr(CONNECTOR) + '\nRESULT=' + repr(RESULT)
                    + '\nEXIT_BROWSER=' + repr(str(self.exit_browser))
                    + '\nRELEASE_ASSIST=' + repr(str(self.release_assist)) + '\n' + BROWSER)
                arguments = (args[-1],)
            child = await original_spawn(sys.executable, '-u', '-c', code, *arguments, **kwargs)
            self.children.append(child)
            return child

        replacements = [patch.object(WebOpenAITunnel, '__init__', capture),
            patch('operator_core.web_openai_tunnel.asyncio.create_subprocess_exec', spawn),
            patch('operator_core.web_openai_tunnel.HEALTH_INTERVAL', .04)]
        for module in ('web_browser_driver', 'web_browser_session'):
            replacements.append(patch('operator_core.' + module + '.desktop_session_state', return_value='unlocked'))
        for replacement in replacements:
            replacement.start()
            self.addCleanup(replacement.stop)

    async def until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 6)

    async def standalone(self, name='state'):
        state = self.root / name
        state.mkdir()
        connection = WebOpenAITunnel(self.settings, WebMcpEndpoint(), state)
        self.addAsyncCleanup(connection.close)
        await connection.start()
        return connection

    async def start_service(self, name='service'):
        browser_profile = self.root / 'browser-profile'
        browser_profile.mkdir(exist_ok=True)
        settings = self.root / (name + '.json')
        service.write_json(settings, {'electron': sys.executable, 'profile_directory': str(browser_profile),
            'session_partition': 'persist:operator-fixture', 'transport': 'mcp_v1',
            'mcp': self.settings, 'timeout_ms': 10000})
        state = self.root / name
        task = asyncio.create_task(service.serve(settings, state))
        self.addAsyncCleanup(self.finish_service, task, state)
        await self.until(lambda: task.done() or (state / 'status.json').exists())
        if task.done():
            await task
        return task, state, service.read_json(state / 'session.json')

    async def finish_service(self, task, state):
        if not task.done():
            if not (state / 'session.json').exists():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            session = service.read_json(state / 'session.json')
            service.write_command(state / 'stop.json', {'instance': session['instance']})
        await asyncio.wait_for(task, 6)

    def binding(self, connection):
        setup = connection.setup()
        return {**{key: setup[key] for key in ('connection_id', 'tunnel_id')}, 'connector': CONNECTOR}

    async def bind_service(self, state, session):
        service.write_command(state / 'connect.json',
            {'instance': session['instance'], 'binding': self.binding(self.connection)})
        await self.until(lambda: (state / 'connect-result.json').exists())
        self.assertEqual(service.read_json(state / 'connect-result.json')['state'], 'bound')
        await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'ready')

    def payload(self, turn):
        return {'model': service.SLUG, 'input': [{'role': 'user', 'content': 'synthetic request 中文😀'}],
            'tools': [FUNCTION], 'reasoning': {'effort': 'high'}, 'stream': False,
            'client_metadata': {'thread_id': 'fixed-fixture', 'turn_id': turn}}

    async def complete(self, client, url, turn):
        payload = self.payload(turn)
        async with client.post(url, json=payload) as response:
            self.assertEqual(response.status, 200, await response.text())
            call = (await response.json())['output'][0]
        self.assertEqual(json.loads(call['arguments']), {'value': 'raw \r\n中文😀'})
        payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
            'output': [deepcopy(RESULT)]}]
        async with client.post(url, json=payload) as response:
            self.assertEqual(response.status, 200, await response.text())
            self.assertEqual((await response.json())['output'][0]['content'][0]['text'], RESULT['text'])

    async def test_idle_recovery_preserves_binding_tools_and_no_replay(self):
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        original = self.connection.setup()
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            url = session['base_url'] + '/responses'
            await self.complete(client, url, 'before')
            self.trigger.write_text('idle')
            await self.until(lambda: self.connection.reconnecting)
            async with client.post(url, json=self.payload('during')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
            self.trigger.write_text('')
            await self.until(lambda: self.connection.ready)
            await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'ready')
            self.assertEqual(self.connection.setup(), original)
            async with client.post(url, json=self.payload('before')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            await self.complete(client, url, 'after')
        await self.finish_service(task, state)
        self.assertEqual(len(self.launches), 2)
        self.assertEqual(self.connection.recoveries, 1)
        self.assertFalse(self.connection.lock_path.exists())
        self.assertTrue(all(child.returncode is not None for child in self.children))

    async def test_fixed_check_uses_live_health_without_claiming_plugin_authorization(self):
        task, state, session = await self.start_service()
        def check():
            current, health = service.live_status(state)
            return service.check_connection(state, current, health)
        result = await asyncio.to_thread(check)
        self.assertEqual(result['state'], 'transport_ready')
        self.assertFalse(result['chatgpt_authorization_verified'])
        self.assertEqual(result['rpc_requests'], 0)
        self.assertEqual(self.endpoint.requests, 0)
        self.trigger.write_text('idle')
        await self.until(lambda: self.connection.reconnecting)
        self.assertEqual((await asyncio.to_thread(check))['state'], 'failed')
        await self.finish_service(task, state)

    async def test_clean_restart_reuses_exact_saved_plugin_with_new_local_endpoint(self):
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        first = self.connection.setup()
        endpoint = self.endpoint.path
        await self.finish_service(task, state)
        task2, state2, session2 = await self.start_service('second')
        self.assertEqual(self.connection.connector, CONNECTOR)
        self.assertEqual(self.connection.setup()['tunnel_id'], first['tunnel_id'])
        self.assertNotEqual(self.connection.id, first['connection_id'])
        self.assertNotEqual(self.endpoint.path, endpoint)
        self.assertEqual(service.read_json(state2 / 'status.json')['state'], 'ready')
        async with ClientSession(headers={'Authorization': 'Bearer ' + session2['token']}) as client:
            await self.complete(client, session2['base_url'] + '/responses', 'fresh')
        await self.finish_service(task2, state2)
        self.assertEqual(len(self.launches), 3)
        for path in (state / 'openai-tunnel.yaml', state / 'connection.json', state / 'status.json'):
            self.assertNotIn(self.key, path.read_text(encoding='utf8'))

    async def test_active_disconnect_stops_owned_children_without_call_replay(self):
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            async with client.post(session['base_url'] + '/responses', json=self.payload('active')) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())['output'][0]['name'], 'inspect')
            self.assertIsNotNone(self.endpoint.turn.pending)
            self.trigger.write_text('idle')
            await asyncio.wait_for(task, 6)
        self.assertEqual(self.connection.failure, 'web_fixed_tunnel_active_disconnect_no_retry')
        self.assertEqual(len(self.launches), 2)
        self.assertEqual(self.endpoint.methods.get('tools/call'), 4)
        self.assertTrue(all(child.returncode is not None for child in self.children))

    async def test_authorization_failure_is_terminal_even_when_idle(self):
        connection = await self.standalone()
        self.trigger.write_text('auth')
        await self.until(connection.failed.is_set)
        self.assertEqual(connection.failure, 'web_fixed_tunnel_authorization_required')
        await connection.close()
        self.assertEqual(len(self.launches), 1)
        self.assertNotIn('private fixture', json.dumps(connection.status()))

    async def test_no_poll_and_ambiguous_metric_cannot_claim_remote_ready(self):
        self.trigger.write_text('no_poll')
        with patch('operator_core.web_openai_tunnel.START_TIMEOUT', .4):
            with self.assertRaises(asyncio.TimeoutError):
                await self.standalone()
        self.assertFalse(self.connection.ready)
        self.assertTrue(all(child.returncode is not None for child in self.children))
        for raw in (b'commands_poll_last_successful_timestamp_seconds 1e999',
                b'commands_poll_last_successful_timestamp_seconds 3\ncommands_poll_last_successful_timestamp_seconds 3'):
            with self.assertRaises(ValueError):
                poll_timestamp(raw)
        self.assertEqual(poll_timestamp(b'commands_poll_last_successful_timestamp_seconds{x="y"} 1.789551506e+09'), 1789551506)

    async def test_profile_conflict_and_changed_identity_do_not_start_another_child(self):
        first = await self.standalone()
        with self.assertRaisesRegex(ValueError, 'web_fixed_tunnel_profile_already_active'):
            await self.standalone('competing')
        self.assertTrue(first.connected)
        self.assertEqual(len(self.launches), 1)
        binding = self.binding(first)
        binding['tunnel_id'] = 'tunnel_' + 'b' * 32
        with self.assertRaisesRegex(ValueError, 'web_connection_binding_changed'):
            first.bind(binding)
        first.bind(self.binding(first))
        await first.close()
        changed = dict(self.settings, tunnel_id='tunnel_' + 'b' * 32)
        with self.assertRaisesRegex(ValueError, 'web_fixed_tunnel_saved_binding_changed'):
            WebOpenAITunnel(changed, WebMcpEndpoint(), self.root / 'unused')

    async def test_idle_recovery_timeout_and_child_exit_never_restart(self):
        connection = await self.standalone()
        with patch('operator_core.web_openai_tunnel.IDLE_TIMEOUT', .1):
            self.trigger.write_text('idle')
            await self.until(connection.failed.is_set)
        self.assertEqual(connection.failure, 'web_fixed_tunnel_idle_timeout_no_retry')
        await connection.close()
        self.trigger.write_text('')
        second = await self.standalone('next')
        self.trigger.write_text('exit')
        await self.until(second.failed.is_set)
        await second.close()
        self.assertEqual(len(self.launches), 2)

    async def test_absent_oauth_metadata_does_not_open_other_paths_or_hosts(self):
        connection = await self.standalone()
        async with ClientSession() as client:
            base = 'http://' + self.endpoint.host
            async with client.get(base + '/.well-known/oauth-protected-resource') as response:
                self.assertEqual(response.status, 404)
            async with client.get(base + '/.well-known/oauth-protected-resource', headers={'Host': 'outside.invalid'}) as response:
                self.assertEqual(response.status, 403)
            async with client.get(base + '/unrelated') as response:
                self.assertEqual(response.status, 403)
        self.assertEqual(self.endpoint.requests, 0)
        await connection.close()


class FixedSetupTests(unittest.TestCase):
    def test_local_save_is_private_exclusive_and_does_not_store_key_in_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'private'
            key = 'sk-' + 'z' * 24
            result = save_profile(root, Path(sys.executable), 'tunnel_' + 'c' * 32, key)
            self.assertEqual(Path(result['api_key_file']).read_text(), key)
            self.assertNotIn(key, (root / 'mcp-settings.json').read_text())
            self.assertEqual(result['tunnel_client_sha256'], hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest())
            before = (root / 'mcp-settings.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'web_private_directory_must_be_new'):
                save_profile(root, Path(sys.executable), 'tunnel_' + 'd' * 32, key)
            self.assertEqual((root / 'mcp-settings.json').read_bytes(), before)

    def test_environment_cannot_override_key_route_tool_command_or_window(self):
        poisoned = {'MCP_COMMAND': 'not admitted', 'CONTROL_PLANE_BASE_URL': 'https://outside.invalid',
            'CONTROL_PLANE_API_KEY': 'not admitted', 'LOG_HTTP_RAW_UNSAFE': 'true', 'OPEN_WEB_UI': 'true',
            'HEALTH_LISTEN_ADDR': '0.0.0.0:1234', 'HTTPS_PROXY': 'http://outside.invalid:1234'}
        with patch.dict(os.environ, poisoned):
            env = tunnel_environment()
        self.assertTrue(set(poisoned).isdisjoint(env))


if __name__ == '__main__':
    unittest.main()
