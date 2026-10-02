"""Current native CLI tool declarations and search through an isolated router.

All endpoints, sign-in and results are synthetic. No host account is loaded.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'scripts'))
from aiohttp import web
from aiohttp.test_utils import TestServer
import operator_mode_entry as mode
from operator_core import model_router as router_module
from operator_core.model_registry import ModelRegistry


@unittest.skipUnless(os.environ.get('CODEX_OPERATOR_TEST_CLI'), 'explicit installed CLI required')
class ModeEntryCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_live_mode_declares_hosted_search_before_dispatch(self):
        await self.exercise(standalone=False)

    async def test_standalone_search_and_result_round_trip_keep_credentials_separate(self):
        await self.exercise(standalone=True)

    async def exercise(self, *, standalone):
        executable = Path(os.environ['CODEX_OPERATOR_TEST_CLI']).resolve(strict=True)
        calls, searches, unexpected = [], [], []
        native_access, native_account = 'synthetic-native-access', 'synthetic-native-account'
        original_search = {'output': 'SYNTHETIC_SEARCH_DATA_29', 'encrypted_output': None, 'results': []}
        registration = json.loads((PLUGIN / 'models/api/examples/glm-5.3-flash.candidate.json').read_text('utf-8'))
        registration.update(slug='local/mode-search-fixture', model='mode-search-fixture', api_key_env='')

        async def endpoint(request):
            if request.method != 'POST':
                unexpected.append((request.method, request.path))
                return web.Response(status=404)
            if request.path == '/native/alpha/search':
                searches.append({'body': await request.json(), 'authorization': request.headers.get('Authorization'),
                                 'account': request.headers.get('ChatGPT-Account-Id')})
                return web.json_response(original_search)
            if request.path != '/v1/responses':
                unexpected.append((request.method, request.path))
                return web.Response(status=404)
            payload = await request.json()
            calls.append({'body': payload, 'authorization': request.headers.get('Authorization'),
                          'account': request.headers.get('ChatGPT-Account-Id')})
            if not standalone:
                return web.json_response({'error': 'synthetic_capture_terminal'}, status=400)
            if len(calls) == 1:
                tools = [t for t in payload.get('tools', []) if t.get('name', '').startswith('operator_web_run_')]
                if len(tools) != 1:
                    return web.json_response({'error': 'synthetic_search_declaration_missing'}, status=400)
                output = [{'type': 'function_call', 'id': 'fc_mode_search', 'call_id': 'call_mode_search',
                           'name': tools[0]['name'], 'arguments': json.dumps({
                               'search_query': [{'q': 'synthetic-query-29'}], 'response_length': 'short'}),
                           'status': 'completed'}]
            else:
                outputs = [i for i in payload.get('input', []) if i.get('type') == 'function_call_output'
                           and i.get('call_id') == 'call_mode_search']
                if len(calls) != 2 or len(outputs) != 1 or 'SYNTHETIC_SEARCH_DATA_29' not in json.dumps(outputs[0]):
                    return web.json_response({'error': 'synthetic_search_result_missing'}, status=400)
                output = [{'type': 'message', 'id': 'msg_mode_search', 'role': 'assistant', 'status': 'completed',
                           'content': [{'type': 'output_text', 'text': 'SYNTHETIC_MODE_SEARCH_OK', 'annotations': []}]}]
            return web.json_response({'id': 'resp_mode_search_' + str(len(calls)), 'object': 'response',
                                      'status': 'completed', 'model': registration['model'], 'output': output})

        app = web.Application()
        app.router.add_route('*', '/{tail:.*}', endpoint)
        upstream = TestServer(app)
        await upstream.start_server()
        gateway, child = None, None
        try:
            with tempfile.TemporaryDirectory(prefix='operator-mode-search-') as directory:
                root = Path(directory).resolve()
                user = root / 'user'
                native = user / '.codex'
                native.mkdir(parents=True)
                auth = json.dumps({'auth_mode': 'chatgpt', 'tokens': {
                    'access_token': native_access, 'account_id': native_account}}).encode()
                (native / 'auth.json').write_bytes(auth)
                work = root / 'work'
                work.mkdir()
                isolated = root / 'extension'
                (isolated / 'home').mkdir(parents=True)
                registration['api_base'] = str(upstream.make_url('/v1'))
                registry = ModelRegistry({'version': 2, 'models': [registration]},
                    json.loads((PLUGIN / 'scripts/operator_core/beeper_model_catalog.json').read_text('utf-8')))
                native_base = str(upstream.make_url('/native'))
                with patch.dict(os.environ, {'USERPROFILE': str(user)}), \
                        patch.object(router_module, 'NATIVE_BASE', native_base):
                    router = router_module.ModelRouter(registry, 'a' * 64, native_enabled=False,
                        native_base=native_base, native_search_home=native if standalone else None)
                    # Capture the original native declaration before adapter rejection in the negative case.
                    if not standalone:
                        async def capture(request):
                            calls.append({'body': await request.json()})
                            return web.json_response({'error': 'synthetic_capture_terminal'}, status=400)
                        capture_app = web.Application()
                        capture_app.router.add_post('/' + 'a' * 64 + '/v1/responses', capture)
                        gateway = TestServer(capture_app)
                    else:
                        gateway = TestServer(router.app())
                    await gateway.start_server()
                    (isolated / 'home/models.json').write_text(json.dumps(registry.extension_catalog()), encoding='utf-8')
                    configuration = mode.config_bytes(isolated, gateway.port, 'a' * 64, registration['slug'], 'low',
                        search_policy=mode.native_search.CONTRACT if standalone else None)
                    (isolated / 'home/config.toml').write_bytes(configuration)
                    environment = {k: v for k, v in os.environ.items() if k.upper() in {
                        'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
                        'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'HOMEDRIVE', 'HOMEPATH'}}
                    environment.update(CODEX_HOME=str(isolated / 'home'), HTTP_PROXY=str(upstream.make_url('/')),
                        HTTPS_PROXY=str(upstream.make_url('/')), ALL_PROXY=str(upstream.make_url('/')),
                        NO_PROXY='127.0.0.1,localhost,::1')
                    command = [str(executable), 'exec', '--ephemeral', '--ignore-rules', '--skip-git-repo-check',
                        '--color', 'never', '--sandbox', 'read-only', '-C', str(work), '-c', 'approval_policy="never"']
                    for key in ('shell_tool', 'plugins', 'remote_plugin', 'image_generation', 'multi_agent', 'goals'):
                        command += ['-c', 'features.' + key + '=false']
                    command += ['-c', 'analytics.enabled=false', 'Synthetic local fixture. Complete the provided search once.']
                    child = await asyncio.create_subprocess_exec(*command, cwd=work, env=environment,
                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        creationflags=0x08000000 if os.name == 'nt' else 0)
                    stdout, stderr = await asyncio.wait_for(child.communicate(), 35)
                details = {'exit': child.returncode, 'calls': len(calls), 'searches': len(searches),
                           'stderr_tail': stderr.decode('utf-8', errors='replace')[-1400:],
                           'tool_names': [t.get('name', t.get('type')) for t in calls[0]['body'].get('tools', [])] if calls else []}
                self.assertEqual(unexpected, [], details)
                self.assertEqual((native / 'auth.json').read_bytes(), auth)
                self.assertFalse((isolated / 'home/auth.json').exists())
                if standalone:
                    self.assertEqual(child.returncode, 0, details)
                    self.assertEqual(len(calls), 2, details)
                    self.assertEqual(len(searches), 1, details)
                    self.assertTrue(all(c['authorization'] is None and c['account'] is None for c in calls))
                    self.assertEqual(searches[0]['authorization'], 'Bearer ' + native_access)
                    self.assertEqual(searches[0]['account'], native_account)
                    self.assertEqual(searches[0]['body']['commands']['search_query'], [{'q': 'synthetic-query-29'}])
                    self.assertIn(b'SYNTHETIC_MODE_SEARCH_OK', stdout)
                else:
                    self.assertEqual(child.returncode, 1, details)
                    self.assertEqual(len(calls), 1, details)
                    self.assertEqual(searches, [], details)
                    self.assertIn('web_search', [t.get('type') for t in calls[0]['body'].get('tools', [])])
        finally:
            if child is not None and child.returncode is None:
                child.terminate()
                await child.wait()
            if gateway is not None:
                await gateway.close()
            await upstream.close()
