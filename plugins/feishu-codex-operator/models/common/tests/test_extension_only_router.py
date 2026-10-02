"""The separate extension home must not discover or forward native traffic."""
import json
from pathlib import Path
import sys
import unittest

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'scripts'))

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from operator_core.model_registry import ModelRegistry
from operator_core.model_router import ModelRouter

BEEPER = json.loads((PLUGIN / 'scripts/operator_core/beeper_model_catalog.json').read_text('utf-8'))


class ExtensionOnlyRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []

        async def endpoint(request):
            self.received.append((request.path, await request.json()))
            return web.json_response({'id': 'response_fixture', 'status': 'completed',
                                      'output': [], 'model': 'fixture'})

        upstream = web.Application()
        upstream.router.add_route('*', '/{tail:.*}', endpoint)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.registry = ModelRegistry({'version': 1, 'models': [{
            'slug': 'local/fixture', 'display_name': 'Fixture', 'model': 'fixture',
            'api_base': str(self.upstream.make_url('/v1')), 'api_key_env': '',
            'context_window': 32000, 'reasoning_efforts': ['low']} ]}, BEEPER)
        self.router = ModelRouter(self.registry, 'a' * 64, native_enabled=False,
                                 native_base=str(self.upstream.make_url('/native')))
        self.client = TestClient(TestServer(self.router.app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()

    async def test_catalog_needs_no_native_auth_or_network_and_retains_registered_metadata(self):
        response = await self.client.get(self.router.prefix + '/models')
        self.assertEqual(response.status, 200)
        catalog = await response.json()
        self.assertEqual([r['slug'] for r in catalog['models']], ['local/fixture'])
        self.assertEqual(catalog['models'][0]['context_window'], 32000)
        self.assertEqual(catalog['models'][0]['supported_reasoning_levels'],
                         [{'effort': 'low', 'description': 'low'}])
        self.assertEqual(self.received, [])

    async def test_native_beeper_unknown_and_auxiliary_requests_never_reach_an_upstream(self):
        for model in ('gpt-native-fixture', 'beeper', 'local/missing'):
            response = await self.client.post(self.router.prefix + '/responses',
                json={'model': model, 'input': 'synthetic'})
            self.assertEqual(response.status, 400)
            self.assertIn('model_not_registered', await response.text())
        for endpoint in ('alpha/search', 'images/generations', 'images/edits'):
            response = await self.client.post(self.router.codex_backend_prefix + '/' + endpoint,
                                               json={'synthetic': True})
            self.assertEqual(response.status, 400)
            self.assertIn('native_route_disabled', await response.text())
        self.assertEqual(self.received, [])

    async def test_native_websocket_is_rejected_before_network(self):
        async with self.client.ws_connect(self.router.prefix + '/responses') as socket:
            await socket.send_json({'type': 'response.create', 'model': 'gpt-native-fixture',
                                    'input': 'synthetic'})
            message = await socket.receive()
            # The existing protocol closes ordinary failures. Only a bound
            # managed-Web terminal 400 is projected as a WS error event.
            self.assertEqual(message.type, aiohttp.WSMsgType.CLOSE)
            self.assertEqual(message.data, 1011)
        self.assertEqual(self.received, [])

    async def test_registered_custom_request_is_forwarded_once_with_its_exact_model(self):
        payload = {'model': 'local/fixture', 'input': 'synthetic whitespace\n  保留', 'stream': False}
        response = await self.client.post(self.router.prefix + '/responses', json=payload)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.received, [('/v1/responses', {**payload, 'model': 'fixture'})])
