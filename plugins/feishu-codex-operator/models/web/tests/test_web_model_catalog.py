"""Public picker selections and the shared native no-replay boundary."""
from pathlib import Path
import sys
from copy import deepcopy
from unittest.mock import patch
ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

import asyncio
from dataclasses import replace
import unittest
from test_web_model_protocol import message, BEEPER
from operator_core.model_registry import ModelRegistry, WebServiceBinding
from operator_core.responses_capabilities import RouterError
from operator_core.web_model_catalog import MODELS, CATALOG, browser_selection, matches_selection
from operator_core.web_model_protocol import WebModelProtocol
from operator_core.web_mcp_transport import WebResponsesBridge, WebMcpEndpoint
from operator_web_model import text_route, text_routes
from operator_web_desktop import catalogue


def payload(route, effort, identity):
    return {'model': route.slug, 'reasoning': {'effort': effort}, 'input': 'synthetic ' + identity,
        'tools': [], 'stream': True, 'client_metadata': {'thread_id': 'fixture', 'turn_id': identity}}


class WebModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_context_capacity_is_bound_to_exact_web_model_and_full_effort_set(self):
        for model in MODELS:
            self.assertEqual(MODELS[model]['context_window'], {'status': 'unverified'})
            route = text_route(model=model)
            self.assertEqual(route.context_window, 16000)
            self.assertFalse(route.web_context_window_verified)
            bound = replace(route, web_binding=WebServiceBinding('a'*64, 'b'*64, 'fixture'))
            row = catalogue(bound)['models'][0]
            self.assertNotIn('context_window', row)
            self.assertNotIn('max_context_window', row)
        for model, tokens in (('gpt-5.6-sol', 32768), ('gpt-6-pro', 65536)):
            definition = deepcopy(MODELS[model])
            definition['context_window'] = {
                'status': 'verified', 'model': model,
                'reasoning_efforts': definition['reasoning_efforts'], 'tokens': tokens,
                'source': {'kind': 'observed_web_account',
                    'reference': 'web-context-synthetic-case-20260928'}}
            with patch.dict(MODELS, {model: definition}):
                route = text_route(model=model)
                self.assertEqual(route.context_window, tokens)
                self.assertTrue(route.web_context_window_verified)
                bound = replace(route, web_binding=WebServiceBinding('a'*64, 'b'*64, 'fixture'))
                row = catalogue(bound)['models'][0]
                self.assertEqual(row['context_window'], tokens)
                self.assertEqual(row['max_context_window'], tokens)
                for other in MODELS:
                    if other != model:
                        self.assertEqual(text_route(model=other).context_window, 16000)

    def test_web_context_record_rejects_wrong_model_efforts_value_or_evidence(self):
        model = 'gpt-5.6-sol'
        definition = deepcopy(MODELS[model])
        valid = {'status': 'verified', 'model': model,
            'reasoning_efforts': definition['reasoning_efforts'], 'tokens': 32768,
            'source': {'kind': 'observed_web_account',
                'reference': 'web-context-synthetic-case-20260928'}}
        bad = [
            {**valid, 'model': 'gpt-6-pro'},
            {**valid, 'reasoning_efforts': ['high']},
            {**valid, 'tokens': True},
            {**valid, 'tokens': 2000001},
            {**valid, 'source': None},
            {**valid, 'source': {'kind': 'observed_web_account', 'reference': 'missing'}},
            {**valid, 'source': {'kind': 'official_web_documentation',
                'reference': 'https://example.org/api/model'}},
            {**valid, 'source': {'kind': 'official_web_documentation',
                'reference': 'https://help.openai.com:bad/model'}},
            {'status': 'unverified', 'tokens': 32768},
        ]
        for record in bad:
            with self.subTest(record=record), patch.dict(MODELS, {
                    model: {**definition, 'context_window': record}}):
                with self.assertRaisesRegex(RouterError, 'web_context_record_invalid'):
                    text_route(model=model)

    async def test_verified_selections_use_one_bridge_and_cannot_replay_through_another_model(self):
        routes = text_routes()
        seen = []
        async def browser(turn):
            seen.append(browser_selection(turn.protocol))
            turn.begin(turn.key)
            return message(['exact synthetic result'])
        bridge = WebResponsesBridge(routes[0], WebMcpEndpoint(), browser, routes=routes)
        try:
            for route in routes:
                for effort in route.reasoning_efforts:
                    body = payload(route, effort, str(len(seen)))
                    response, _ = await bridge.exchange(body)
                    self.assertEqual(response['model'], route.slug)
                    self.assertEqual(seen[-1], {'model': route.model, 'effort': effort})
                    observed = {'model': route.model, 'effortIndex': CATALOG['efforts'][effort]['index']}
                    self.assertTrue(matches_selection(observed, seen[-1]))
                    self.assertFalse(matches_selection({**observed, 'effortIndex': -1}, seen[-1]))
                    self.assertFalse(matches_selection({**observed, 'model': 'gpt-5.5'}, seen[-1]))
                    other = routes[-1]
                    with self.assertRaisesRegex(RouterError, 'consumed_no_retry'):
                        await bridge.exchange({**body, 'model': other.slug, 'reasoning': {'effort': 'max'}})
            self.assertEqual(len(seen), 6)
        finally:
            await bridge.stop()

    async def test_other_model_cannot_overlap_active_browser(self):
        routes = text_routes()
        ready, release = asyncio.Event(), asyncio.Event()
        async def browser(turn):
            turn.begin(turn.key); ready.set(); await release.wait()
            return message()
        bridge = WebResponsesBridge(routes[0], WebMcpEndpoint(), browser, routes=routes)
        active = asyncio.create_task(bridge.exchange(payload(routes[0], 'high', 'first')))
        try:
            await ready.wait()
            with self.assertRaisesRegex(RouterError, 'response_busy'):
                await bridge.exchange(payload(routes[-1], 'max', 'second'))
            release.set()
            await active
        finally:
            release.set(); await bridge.stop(); await asyncio.gather(active, return_exceptions=True)

    def test_unobserved_efforts_and_models_never_select_another_mode(self):
        with self.assertRaisesRegex(RouterError, 'web_explicit_model_required'):
            text_route(model='gpt-6-sol')
        for route in text_routes():
            for effort in ('low', 'minimal', 'ultra', *({'max'} if not route.model.endswith('-pro') else {'high', 'none'})):
                with self.assertRaises(RouterError):
                    WebModelProtocol(route, payload(route, effort, 'unsupported'))
        route = text_routes()[0]
        with self.assertRaisesRegex(RouterError, 'explicit_route'):
            WebModelProtocol(route, {**payload(route, 'high', 'unsupported'), 'model': 'gpt-6'})

    def test_absent_null_and_summary_only_reasoning_keep_the_registered_default(self):
        for route in text_routes():
            for reasoning in (None, {}, {'summary': 'detailed'}):
                protocol = WebModelProtocol(route, {**payload(route, 'high', 'default'), 'reasoning': reasoning})
                self.assertEqual(browser_selection(protocol)['effort'], route.reasoning_efforts[0])
            body = payload(route, 'high', 'absent'); del body['reasoning']
            self.assertEqual(browser_selection(WebModelProtocol(route, body))['effort'], route.reasoning_efforts[0])

    def test_native_catalog_and_atomic_rebinding_keep_native_rows_and_remove_old_service_models(self):
        binding = WebServiceBinding('a'*64, 'b'*64, 'private-fixture')
        routes = tuple(replace(r, model=r.slug, web_binding=binding) for r in text_routes())
        registry = ModelRegistry({'version': 2, 'models': []}, BEEPER)
        published = registry.with_web_routes(routes)
        self.assertFalse(registry.routes)
        self.assertEqual(len(published.routes), 3)
        native = {'models': [{**BEEPER['models'][0], 'slug': 'native-fixture'}]}
        self.assertEqual(published.merge(native)['models'][0], native['models'][0])
        rows = catalogue(routes)['models']
        self.assertEqual(sum(len(r['supported_reasoning_levels']) for r in rows), 6)
        reduced = published.with_web_routes(routes[:1])
        self.assertEqual(len(reduced.routes), 1)
        self.assertEqual(len(published.routes), 3)
        collision = ModelRegistry({'version': 2, 'models': []}, BEEPER)
        collision.routes = {routes[0].slug: replace(routes[0], web_binding=None)}
        with self.assertRaisesRegex(RouterError, 'collision'):
            collision.with_web_routes(routes)
        self.assertIsNone(collision.routes[routes[0].slug].web_binding)
