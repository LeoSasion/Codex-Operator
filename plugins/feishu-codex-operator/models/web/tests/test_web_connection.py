"""Owned Python tunnel/browser fixtures and actual loopback MCP, no real account."""

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
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from aiohttp import ClientSession

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / 'scripts'))
import operator_web_model as service
from operator_core.web_connection import WebMcpConnection
from operator_core.web_mcp_transport import WebMcpEndpoint


CONNECTOR = {'id': 'plugin:asdk_app_' + 'a' * 32, 'name': 'Operator fixture'}
FUNCTION = {'type': 'function', 'name': 'inspect', 'description': 'Synthetic read-only inspection',
    'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}},
        'required': ['value'], 'additionalProperties': False}}
RESULT = {'type': 'input_text', 'text': 'Permission denied fixture\r\n中文😀  '}

TUNNEL = '''import sys,time
from pathlib import Path
assert '--retries' in sys.argv and sys.argv[sys.argv.index('--retries')+1]==str(EXPECTED_RETRIES)
assert '--no-autoupdate' in sys.argv and '--http-host-header' in sys.argv
print('2026-09-16T00:00:00Z INF |  Your quick Tunnel has been created! Visit it at (fixture) |',flush=True)
print('2026-09-16T00:00:00Z INF | https://synthetic-fixture.trycloudflare.com |',flush=True)
print('2026-09-16T00:00:00Z INF Registered tunnel connection connIndex=0 fixture',flush=True)
while not Path(RELEASE).exists():time.sleep(.01)
print('2026-09-16T00:00:00Z ERR PRIVATE URL AND BODY must never enter diagnostics',flush=True)
time.sleep(30)
'''

RECONNECT_TUNNEL = TUNNEL.replace(
    "print('2026-09-16T00:00:00Z ERR PRIVATE URL AND BODY must never enter diagnostics',flush=True)\ntime.sleep(30)",
    '''print('2026-09-16T00:00:00Z ERR failed to serve incoming request error="Error shutting down control stream: client disconnected"',flush=True)
print('2026-09-16T00:00:00Z INF Retrying connection in up to 1s connIndex=0 event=0 ip=127.0.0.1',flush=True)
while not Path(RECOVER).exists():time.sleep(.01)
print('2026-09-16T00:00:00Z INF Registered tunnel connection connIndex=0 fixture',flush=True)
time.sleep(30)''')

BROWSER = '''import json,sys,time,urllib.request
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));root=Path(c['workerDirectory'])
def emit(kind,**v):print(json.dumps({'operator_web':1,'kind':kind,**v}),flush=True)
emit('worker_ready')
while not (root/'shutdown.json').exists():
 if Path(EXIT_BROWSER).exists():
  Path(EXIT_BROWSER).unlink();raise SystemExit(1)
 assist=root/'assist.json'
 if assist.exists():
  a=json.loads(assist.read_text(encoding='utf-8'));assist.rename(root/'assisting.json')
  emit('assistance_opened',assistanceId=a['id'])
  while not Path(RELEASE_ASSIST).exists() and not (root/'shutdown.json').exists():time.sleep(.01)
  if (root/'shutdown.json').exists():break
  Path(RELEASE_ASSIST).unlink();(root/'assisting.json').unlink()
  emit('assistance_hidden',assistanceId=a['id'],visible=False,focused=False,userClosed=True)
  continue
 p=root/'next.json'
 if not p.exists():time.sleep(.01);continue
 r=json.loads(p.read_text(encoding='utf-8'));p.rename(root/'active.json');ident=r['id'];cfg=r
 assert cfg['connectorMention']==CONNECTOR and cfg['autoSelectConnector'] is True
 assert c['visible'] is False and c['backgroundInput']=='dom_v1'
 text=cfg['text'];env=json.loads(text.split('BEGIN_MCP_CONTINUATION_JSON ')[1].split(' END_MCP_CONTINUATION_JSON')[0])
 assert env['protocol']=='mcp_context_records_v3' and 'request' not in env
 key=env['mcp_transport']['turn_key'];sid=None
 def rpc(i,method,params):
  global sid
  headers={'Content-Type':'application/json'}
  if sid:headers['Mcp-Session-Id']=sid
  req=urllib.request.Request(URL,json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params}).encode(),headers)
  with urllib.request.urlopen(req,timeout=10) as response:
   if response.headers.get('Mcp-Session-Id'):sid=response.headers['Mcp-Session-Id']
   return json.loads(response.read())['result']
 rpc(1,'initialize',{'protocolVersion':'2025-03-26'})
 listed=rpc(2,'tools/list',{})
 call_tool=next(tool for tool in listed['tools'] if tool['name']=='operator_call')
 assert call_tool['outputSchema']['required']==['codex_function_result']
 emit('dispatch_started',requestId=ident)
 number=2
 def section(read_key):
  global number
  fragments=[];entries=[];records=[];pages=0
  while read_key:
   number+=1
   result=rpc(number,'tools/call',{'name':'operator_begin','arguments':{'turn_key':read_key}})
   page=result['structuredContent'] if 'structuredContent' in result else json.loads(result['content'][0]['text'])
   assert page['index']==pages;pages+=1
   if 'records' in page:records.extend(page['records'])
   elif 'entries' in page:entries.extend(page['entries'])
   else:fragments.append(page['json_fragment'])
   read_key=page['next_read_key']
  if records:
   assert all(r['encoding']=='json' for r in records)
   assert [r['record_index'] for r in records]==list(range(len(records)))
   values=[r['value'] for r in records];first=values[0]
   assert first['input_format']=='array' and first['input_count']==len(values)-1
   assert [r['request_input_index'] for r in values[1:]]==list(range(len(values)-1))
   request=first['value'];request['input']=[r['value'] for r in values[1:]]
   return {'request':request,'tools_present':first['tools_present'],'tool_count':first['tool_count']},page
  return (entries if entries else json.loads(''.join(fragments))),page
 context,last=section(key)
 catalog,_=section(last['catalog_read_key'])
 schema,_=section(catalog[0]['schema_read_key'])
 active=context['request']
 assert active['input'][0]['content']=='synthetic request 中文😀'
 assert active['model']=='gpt-5.6-sol'
 assert schema['mcp_tool']['name']==catalog[0]['name']=='inspect'
 answer=rpc(number+1,'tools/call',{'name':'operator_call','arguments':{'turn_key':key,'name':catalog[0]['name'],'arguments':{'value':'raw \\r\\n中文😀'}}})
 assert answer['content']==[] and answer['isError'] is False
 original=answer['structuredContent']['codex_function_result']
 assert original['output']==[RESULT]
 public={'id':'fixture-final','author':{'role':'assistant'},'recipient':'all','channel':'final',
  'status':'finished_successfully','end_turn':True,'content':{'content_type':'text','parts':[RESULT['text']]}}
 emit('window_state',requestId=ident,visible=False,focused=False,backgroundInput=True,inputMode='dom_v1',shown=0,focusedEvents=0)
 emit('completed',requestId=ident,model='gpt-5.6-sol',effortIndex=2,publicMessage=public)
 (root/'active.json').unlink();emit('worker_idle',requestId=ident,resultCode=0)
'''


class WebConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='web-connection-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'release-tunnel.fixture'
        self.exit_browser = self.root / 'exit-browser.fixture'
        self.release_assist = self.root / 'release-assist.fixture'
        self.launches = []
        self.children = []
        self.endpoint = None
        self.reconnect_policy = 'never'
        self.tunnel_program = TUNNEL
        self.recover = self.root / 'recover-tunnel.fixture'
        original = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            self.launches.append((args, kwargs))
            if args[1] == 'tunnel':
                code = ('RELEASE=' + repr(str(self.release)) + '\nRECOVER=' + repr(str(self.recover))
                    + '\nEXPECTED_RETRIES=' + str(5 if self.reconnect_policy == 'idle_v1' else 0)
                    + '\n' + self.tunnel_program)
                arguments = args[1:]
            else:
                config = Path(args[-1])
                # A synthetic tunnel never forwards publicly. The actual MCP
                # endpoint's loopback address is supplied directly to this fixture.
                code = ('URL=' + repr('http://' + self.endpoint.host + self.endpoint.path)
                    + '\nCONNECTOR=' + repr(CONNECTOR) + '\nRESULT=' + repr(RESULT)
                    + '\nEXIT_BROWSER=' + repr(str(self.exit_browser))
                    + '\nRELEASE_ASSIST=' + repr(str(self.release_assist)) + '\n' + BROWSER)
                arguments = (str(config),)
            child = await original(sys.executable, '-u', '-c', code, *arguments, **kwargs)
            self.children.append(child)
            return child

        replacement = patch('operator_core.web_connection.asyncio.create_subprocess_exec', spawn)
        replacement.start()
        self.addCleanup(replacement.stop)
        for module in ('web_browser_driver', 'web_browser_session'):
            replacement = patch('operator_core.' + module + '.desktop_session_state', return_value='unlocked')
            replacement.start()
            self.addCleanup(replacement.stop)

    async def until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 5)

    async def connection(self):
        endpoint = WebMcpEndpoint()
        self.endpoint = endpoint
        connection = WebMcpConnection({'cloudflared': sys.executable,
            'reconnect_policy': self.reconnect_policy}, endpoint, self.root)
        self.addAsyncCleanup(connection.close)
        await connection.start()
        return connection

    async def test_connection_binds_exact_instance_address_then_stops_on_first_disconnect(self):
        connection = await self.connection()
        self.assertFalse(connection.ready)
        setup = connection.setup()
        bad = {k: setup[k] for k in ('connection_id', 'endpoint_url')}
        bad.update(connector=CONNECTOR, endpoint_url='https://wrong.invalid/mcp/not-this-endpoint')
        with self.assertRaisesRegex(ValueError, 'web_connection_binding_changed'):
            connection.bind(bad)
        self.assertFalse(connection.ready)
        binding = {k: setup[k] for k in ('connection_id', 'endpoint_url')}
        binding['connector'] = CONNECTOR
        self.assertEqual(connection.bind(binding), CONNECTOR)
        self.assertTrue(connection.ready)
        with self.assertRaisesRegex(ValueError, 'web_connection_bind_unavailable'):
            connection.bind(binding)
        self.release.write_bytes(b'disconnect')
        await self.until(connection.failed.is_set)
        self.assertFalse(connection.ready)
        self.assertNotIn('PRIVATE', json.dumps(connection.status()))
        self.assertNotIn(setup['endpoint_url'], json.dumps(connection.status()))
        await asyncio.gather(connection.close(), connection.close())
        self.assertTrue(all(p.returncode is not None for p in self.children))
        self.assertEqual(len(self.launches), 1)
        with self.assertRaisesRegex(ValueError, 'web_connection_already_started_or_closed'):
            await connection.start()

    async def test_executable_change_rejected_before_any_listener_or_child(self):
        executable = self.root / 'fixture.exe'
        executable.write_bytes(b'first')
        endpoint = WebMcpEndpoint()
        connection = WebMcpConnection({'cloudflared': str(executable)}, endpoint, self.root)
        executable.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'web_tunnel_executable_changed'):
            await connection.start()
        self.assertIsNone(endpoint.runner)
        self.assertEqual(self.launches, [])

    async def start_service(self):
        profile = self.root / 'profile'
        profile.mkdir()
        settings = self.root / 'settings.json'
        settings.write_text(json.dumps({'electron': sys.executable, 'profile_directory': str(profile),
            'session_partition': 'persist:operator-fixture', 'transport': 'mcp_v1',
            'mcp': {'cloudflared': sys.executable, 'reconnect_policy': self.reconnect_policy},
            'timeout_ms': 10000}), encoding='utf8')
        state = self.root / 'service'
        original = WebMcpConnection.__init__
        def capture(connection, settings, endpoint, directory):
            original(connection, settings, endpoint, directory)
            self.endpoint = endpoint
        with patch.object(WebMcpConnection, '__init__', capture):
            task = asyncio.create_task(service.serve(settings, state, 60))
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
        await asyncio.wait_for(task, 5)

    def payload(self, turn):
        return {'model': service.SLUG, 'input': [{'role': 'user', 'content': 'synthetic request 中文😀'}],
            'tools': [FUNCTION], 'reasoning': {'effort': 'high'}, 'stream': False,
            'client_metadata': {'thread_id': 'same-fixture', 'turn_id': turn}}

    async def bind_service(self, state, session):
        setup = service.read_json(state / 'connection.json')
        binding = {k: setup[k] for k in ('connection_id', 'endpoint_url')}
        binding['connector'] = CONNECTOR
        service.write_command(state / 'connect.json', {'instance': session['instance'], 'binding': binding})
        await self.until(lambda: (state / 'connect-result.json').exists()
            and service.read_json(state / 'connect-result.json')['state'] == 'bound')
        self.assertEqual(service.read_json(state / 'connect-result.json')['state'], 'bound')

    async def test_complete_service_gates_setup_preserves_denial_and_reuses_hidden_worker(self):
        task, state, session = await self.start_service()
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            url = session['base_url'] + '/responses'
            service.write_command(state / 'connect.json', {'instance': '0' * 32, 'binding': {}})
            await self.until(lambda: (state / 'connect-result.json').exists())
            self.assertEqual(service.read_json(state / 'connect-result.json')['code'],
                'web_connection_instance_changed')
            async with client.post(url, json=self.payload('unbound')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.assertEqual((await response.json())['error']['code'], 'web_connection_required_before_dispatch')
            self.assertEqual(len(self.launches), 1)  # Only the tunnel, no browser.
            await self.bind_service(state, session)
            for turn in ('first', 'second'):
                payload = self.payload(turn)
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    call = (await response.json())['output'][0]
                self.assertEqual(json.loads(call['arguments']), {'value': 'raw \r\n中文😀'})
                payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
                    'output': [deepcopy(RESULT)]}]
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    final = (await response.json())['output'][0]['content'][0]['text']
                self.assertEqual(final, RESULT['text'])
            await self.finish_service(task, state)
        self.assertEqual(len(self.launches), 2)
        self.assertTrue(all(p.returncode is not None for p in self.children))
        status = service.read_json(state / 'status.json')
        self.assertEqual(status['browser']['completed'], 2)
        self.assertEqual(status['connection']['state'], 'stopped')
        self.assertEqual(list((state / 'requests').iterdir()), [])

    async def test_explicit_closed_browser_replacement_keeps_connection_and_consumed_turns(self):
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        setup = service.read_json(state / 'connection.json')
        endpoint = self.endpoint
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            url = session['base_url'] + '/responses'

            async def complete(turn):
                payload = self.payload(turn)
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    call = (await response.json())['output'][0]
                payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
                    'output': [deepcopy(RESULT)]}]
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    self.assertEqual((await response.json())['output'][0]['content'][0]['text'], RESULT['text'])

            await complete('consumed')
            self.exit_browser.write_bytes(b'crash idle browser')
            await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'unavailable')
            self.assertEqual(len(self.launches), 2)
            self.assertTrue(service.read_json(state / 'status.json')['connection']['connected'])
            async with client.post(url, json=self.payload('while_unavailable')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
            service.write_command(state / 'assist.json', {'instance': session['instance'], 'id': 'c' * 32})
            await self.until(lambda: (state / 'assist-result.json').exists()
                and service.read_json(state / 'assist-result.json').get('state') == 'rejected')
            self.assertEqual(service.read_json(state / 'assist-result.json')['code'],
                'web_session_closed_explicit_replacement_required')
            self.assertEqual(len(self.launches), 2)

            def recover():
                output = io.StringIO()
                with patch.object(sys, 'argv', ['operator_web_model', 'assist', '--state', str(state),
                        '--replace-closed-browser']), redirect_stdout(output):
                    code = service.main()
                return code, json.loads(output.getvalue())

            code, recovery = await asyncio.to_thread(recover)
            self.assertEqual(code, 0)
            self.assertEqual(recovery['status'], 'assistance_requested')
            await self.until(lambda: service.read_json(state / 'status.json')['browser']['assistance_state'] == 'awaiting_user')
            self.assertEqual(len(self.launches), 3)  # Original tunnel, two browser children.
            self.assertIs(self.endpoint, endpoint)
            self.assertEqual(service.read_json(state / 'connection.json'), setup)
            async with client.post(url, json=self.payload('while_assisting')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
            self.release_assist.write_bytes(b'user closed empty page')
            await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'ready')
            async with client.post(url, json=self.payload('consumed')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                self.assertEqual((await response.json())['error']['code'], 'web_bridge_turn_consumed_no_retry')
            self.assertEqual(service.read_json(state / 'status.json')['browser']['attempts'], 1)
            await complete('independent_new_turn')
        await self.finish_service(task, state)
        status = service.read_json(state / 'status.json')
        self.assertEqual(status['explicit_browser_replacements'], 1)
        self.assertEqual(status['browser']['attempts'], 2)
        self.assertEqual(status['browser']['completed'], 2)
        self.assertEqual(len(self.launches), 3)
        self.assertTrue(all(p.returncode is not None for p in self.children))

    @unittest.skipUnless(os.name == 'nt', 'Windows reader sharing semantics')
    async def test_readers_keep_same_connection_binding_and_tool_completion_alive(self):
        task, state, session = await self.start_service()
        original = service.read_json(state / 'connection.json')
        with (state / 'connection.json').open('rb'), (state / 'status.json').open('rb'):
            await self.bind_service(state, session)
            self.assertEqual(service.read_json(state / 'connection.json'), original)
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                url = session['base_url'] + '/responses'
                for turn in ('locked-first', 'locked-second'):
                    payload = self.payload(turn)
                    async with client.post(url, json=payload) as response:
                        self.assertEqual(response.status, 200, await response.text())
                        call = (await response.json())['output'][0]
                    payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
                        'output': [deepcopy(RESULT)]}]
                    async with client.post(url, json=payload) as response:
                        self.assertEqual(response.status, 200, await response.text())
                        self.assertEqual((await response.json())['output'][0]['content'][0]['text'], RESULT['text'])
                    await asyncio.sleep(.25)
                    self.assertFalse(task.done())
                    self.assertTrue(all(p.returncode is None for p in self.children))
                async with client.post(url, json=self.payload('locked-first')) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            self.assertEqual(list(state.glob('*.pending')), [])
        await self.until(lambda: service.read_json(state / 'status.json')['browser']['completed'] == 2
            and service.read_json(state / 'connection.json')['connector'] == CONNECTOR)
        current = service.read_json(state / 'connection.json')
        for key in ('instance', 'connection_id', 'endpoint_url'):
            self.assertEqual(current[key], original[key])
        await self.finish_service(task, state)
        self.assertEqual(len(self.launches), 2)
        self.assertTrue(all(p.returncode is not None for p in self.children))
        self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')

    async def test_idle_reconnect_retains_address_binding_child_and_consumed_turns(self):
        self.reconnect_policy, self.tunnel_program = 'idle_v1', RECONNECT_TUNNEL
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        setup = service.read_json(state / 'connection.json')
        endpoint = self.endpoint
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            url = session['base_url'] + '/responses'

            async def complete(turn):
                payload = self.payload(turn)
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    call = (await response.json())['output'][0]
                payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
                    'output': [deepcopy(RESULT)]}]
                async with client.post(url, json=payload) as response:
                    self.assertEqual(response.status, 200, await response.text())
                    self.assertEqual((await response.json())['output'][0]['content'][0]['text'], RESULT['text'])

            await complete('before-idle-loss')
            self.release.write_bytes(b'idle control connection lost')
            await self.until(lambda: service.read_json(state / 'status.json')['connection']['state'] == 'reconnecting')
            before = service.read_json(state / 'status.json')
            async with client.post(url, json=self.payload('during-loss')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.assertEqual((await response.json())['error']['code'], 'web_connection_reconnecting_before_dispatch')
            self.assertFalse(task.done())
            self.assertIs(self.endpoint, endpoint)
            self.assertEqual(service.read_json(state / 'connection.json'), setup)
            self.assertTrue(all(child.returncode is None for child in self.children))
            self.recover.write_bytes(b'same child connected')
            await self.until(lambda: service.read_json(state / 'status.json')['connection']['idle_recoveries'] == 1)
            current = service.read_json(state / 'status.json')
            self.assertEqual(current['browser']['attempts'], before['browser']['attempts'])
            async with client.post(url, json=self.payload('before-idle-loss')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            await complete('new-after-idle-loss')
        await self.finish_service(task, state)
        current = service.read_json(state / 'status.json')
        self.assertEqual(current['browser']['completed'], 2)
        self.assertEqual(current['connection']['idle_interruptions'], 1)
        self.assertEqual(current['connection']['idle_recoveries'], 1)
        self.assertEqual(service.read_json(state / 'connection.json'), setup)
        self.assertEqual(len(self.launches), 2)
        self.assertTrue(all(child.returncode is not None for child in self.children))

    async def test_idle_policy_keeps_active_control_loss_terminal_without_replay(self):
        self.reconnect_policy, self.tunnel_program = 'idle_v1', RECONNECT_TUNNEL
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            async with client.post(session['base_url'] + '/responses', json=self.payload('active-loss')) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())['output'][0]['type'], 'function_call')
            turn = self.endpoint.turn
            self.assertIsNotNone(turn.pending)
            self.release.write_bytes(b'active control connection lost')
            await asyncio.wait_for(task, 5)
        self.assertTrue(turn.closed)
        current = service.read_json(state / 'status.json')
        self.assertEqual(current['connection']['failure'], 'web_tunnel_connection_failed_no_retry')
        self.assertEqual(current['connection']['idle_recoveries'], 0)
        self.assertEqual(current['browser']['attempts'], 1)
        self.assertEqual(len(self.launches), 2)
        self.assertTrue(all(child.returncode is not None for child in self.children))

    async def test_idle_reconnect_deadline_is_bounded_and_never_restarts_child(self):
        self.reconnect_policy, self.tunnel_program = 'idle_v1', RECONNECT_TUNNEL
        connection = await self.connection()
        with patch('operator_core.web_connection.IDLE_RECONNECT_SECONDS', .1):
            self.release.write_bytes(b'loss without recovery')
            await self.until(connection.failed.is_set)
        self.assertEqual(connection.failure, 'web_tunnel_idle_reconnect_timeout_no_retry')
        await connection.close()
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(connection.recoveries, 0)

    async def test_idle_reconnect_rejects_changed_address_and_preserves_original(self):
        self.reconnect_policy = 'idle_v1'
        self.tunnel_program = RECONNECT_TUNNEL.replace(
            "while not Path(RECOVER).exists():time.sleep(.01)",
            "while not Path(RECOVER).exists():time.sleep(.01)\n"
            "print('2026-09-16T00:00:00Z INF | https://changed-fixture.trycloudflare.com |',flush=True)")
        connection = await self.connection()
        original = connection.setup()
        self.release.write_bytes(b'idle loss')
        await self.until(lambda: connection.reconnecting)
        self.recover.write_bytes(b'changed announcement')
        await self.until(connection.failed.is_set)
        self.assertEqual(connection.failure, 'web_tunnel_output_rejected_no_retry')
        self.assertTrue(original['endpoint_url'].startswith(connection.announcement.origin))
        self.assertEqual(connection.recoveries, 0)
        await connection.close()
        self.assertEqual(len(self.launches), 1)

    async def test_idle_policy_does_not_swallow_unknown_errors(self):
        self.reconnect_policy = 'idle_v1'
        connection = await self.connection()
        self.release.write_bytes(b'unknown failure')
        await self.until(connection.failed.is_set)
        self.assertEqual(connection.failure, 'web_tunnel_connection_failed_no_retry')
        self.assertEqual(connection.interruptions, 0)
        await connection.close()
        self.assertEqual(len(self.launches), 1)

    async def test_closed_browser_is_unavailable_even_before_connector_binding(self):
        task, state, session = await self.start_service()
        self.exit_browser.write_bytes(b'fail before any request')
        service.write_command(state / 'assist.json', {'instance': session['instance'], 'id': 'b' * 32})
        await self.until(lambda: service.read_json(state / 'status.json')['browser']['session_closed'])
        await self.until(lambda: service.read_json(state / 'status.json')['state'] == 'unavailable')
        status = service.read_json(state / 'status.json')
        self.assertEqual(status['readiness'], 'unavailable')
        self.assertTrue(status['connection']['connected'])
        self.assertFalse(status['connection']['connector_bound'])
        self.assertEqual(status['browser']['attempts'], 0)
        self.assertEqual(len(self.launches), 2)
        await self.finish_service(task, state)

    async def test_public_check_validates_session_and_complete_tools_without_binding_or_browser(self):
        task, state, session = await self.start_service()
        calls = []

        class Response:
            status = 200
            headers = {'Mcp-Session-Id': 's' * 43}
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, limit): return json.dumps(self.value).encode()[:limit]

        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                value = json.loads(request.data)
                result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'operator-web-tools', 'version': '0.2.0'}} \
                    if len(calls) == 1 else {'tools': deepcopy(service.MCP_TOOLS)}
                return Response({'jsonrpc': '2.0', 'id': value['id'], 'result': result})

        health = {'active': False}
        with patch.object(service, 'build_opener', return_value=Opener()), \
                patch.object(service, 'live_status', return_value=(session, health)):
            result = service.check_connection(state, session, health)
        self.assertEqual(result['state'], 'reachable')
        self.assertEqual(result['rpc_requests'], 2)
        self.assertEqual([json.loads(r.data)['method'] for r in calls], ['initialize', 'tools/list'])
        self.assertIsNone(calls[0].get_header('Mcp-session-id'))
        self.assertEqual(calls[1].get_header('Mcp-session-id'), 's' * 43)
        self.assertTrue(all(r.get_header('Authorization') is None for r in calls))
        self.assertFalse(service.read_json(state / 'status.json')['connection']['connector_bound'])
        self.assertEqual(len(self.launches), 1)
        self.assertNotIn(session['token'], json.dumps(result))
        await self.finish_service(task, state)

    async def test_public_http_error_is_terminal_and_does_not_launch_assistance(self):
        task, state, session = await self.start_service()
        calls = []

        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                raise HTTPError(request.full_url, 530, 'PRIVATE upstream error', {}, None)

        with patch.object(service, 'build_opener', return_value=Opener()):
            result = service.check_connection(state, session, {'active': False})
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['code'], 'web_connection_probe_http_failed')
        self.assertEqual(result['http_status'], 530)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(result['tool_calls'], 0)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('trycloudflare.com', json.dumps(result))
        await self.finish_service(task, state)

    async def test_tunnel_failure_ends_service_without_browser_or_restart(self):
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        self.release.write_bytes(b'disconnect')
        await asyncio.wait_for(task, 5)
        status = service.read_json(state / 'status.json')
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['connection']['failure'], 'web_tunnel_connection_failed_no_retry')
        self.assertEqual(status['browser']['attempts'], 0)
        self.assertEqual(len(self.launches), 1)

    async def test_tunnel_loss_with_pending_tool_closes_native_turn_and_hidden_worker(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        errors = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        self.addCleanup(loop.set_exception_handler, previous_handler)
        task, state, session = await self.start_service()
        await self.bind_service(state, session)
        async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
            async with client.post(session['base_url'] + '/responses', json=self.payload('cancel-tool')) as response:
                self.assertEqual(response.status, 200, await response.text())
                self.assertEqual((await response.json())['output'][0]['type'], 'function_call')
            self.assertIsNotNone(self.endpoint.turn.pending)
            self.release.write_bytes(b'disconnect while result pending')
            await asyncio.wait_for(task, 5)
        self.assertIsNone(self.endpoint.turn)
        status = service.read_json(state / 'status.json')
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['browser']['dispatches'], 1)
        self.assertEqual(status['browser']['completed'], 0)
        self.assertFalse(status['browser']['process_running'])
        self.assertEqual(len(self.launches), 2)
        self.assertTrue(all(p.returncode is not None for p in self.children))
        await asyncio.sleep(0)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
