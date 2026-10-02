"""Credential scope and refusal boundaries for the opt-in official search relay."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'scripts'))
from operator_core import native_search
from operator_core.model_registry import ModelRegistry, RouterError
from operator_core.model_router import ModelRouter
from aiohttp.test_utils import TestClient, TestServer


class NativeSearchTests(unittest.TestCase):
    def test_only_exact_current_user_home_and_chatgpt_access_fields_are_read(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'USERPROFILE': directory}):
            home = Path(directory) / '.codex'
            home.mkdir()
            record = {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'access-only',
                'account_id': 'account-only', 'refresh_token': 'never-return', 'id_token': 'never-return'}}
            raw = json.dumps(record).encode()
            (home / 'auth.json').write_bytes(raw)
            self.assertEqual(native_search.load_headers(home), {
                'Authorization': 'Bearer access-only', 'ChatGPT-Account-Id': 'account-only'})
            self.assertEqual((home / 'auth.json').read_bytes(), raw)
            other = Path(directory) / 'other'
            other.mkdir()
            with self.assertRaisesRegex(RouterError, 'home_invalid'):
                native_search.checked_home(other)
            for invalid in (b'broken json', b'{}', b'{"auth_mode":"apikey"}',
                            b'{"auth_mode":"chatgpt","tokens":{"access_token":"x\\r\\ny","account_id":"z"}}'):
                (home / 'auth.json').write_bytes(invalid)
                with self.assertRaisesRegex(RouterError, '^native_search_sign_in_unavailable$'):
                    native_search.load_headers(home)
                self.assertEqual((home / 'auth.json').read_bytes(), invalid)

    def test_search_policy_rejects_external_destination_or_native_inference_combination(self):
        registry = ModelRegistry({'version': 1, 'models': []}, json.loads(
            (PLUGIN / 'scripts/operator_core/beeper_model_catalog.json').read_text('utf-8')))
        for settings in ({'native_enabled': True},
                         {'native_enabled': False, 'native_base': 'https://example.invalid/v1'}):
            with self.assertRaisesRegex(RouterError, 'fixed_endpoint_required'):
                ModelRouter(registry, 'a' * 64, native_search_home=Path('unused'), **settings)


class NativeSearchAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_does_not_enable_native_models_images_or_refresh_and_errors_are_fixed(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'USERPROFILE': directory}):
            home = Path(directory) / '.codex'
            home.mkdir()
            registry = ModelRegistry({'version': 1, 'models': []}, json.loads(
                (PLUGIN / 'scripts/operator_core/beeper_model_catalog.json').read_text('utf-8')))
            router = ModelRouter(registry, 'a' * 64, native_enabled=False, native_search_home=home)
            async with TestClient(TestServer(router.app())) as client:
                with patch.object(router, 'proxy') as outgoing:
                    for endpoint in ('images/generations', 'images/edits'):
                        response = await client.post(router.prefix + '/' + endpoint, json={})
                        self.assertEqual(response.status, 400)
                    for model in ('gpt-native', 'beeper'):
                        response = await client.post(router.prefix + '/responses', json={'model': model})
                        self.assertEqual(response.status, 400)
                    response = await client.post(router.prefix + '/alpha/search', json={'commands': {}})
                    self.assertEqual(response.status, 400)
                    self.assertIn('native_search_sign_in_unavailable', await response.text())
                    outgoing.assert_not_called()
                self.assertFalse((home / 'auth.json').exists())
