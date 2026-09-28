"""Private provider preparation/reversal; no real account, task or model call."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / 'scripts'))
import operator_web_desktop as desktop
import operator_web_service as manager
from operator_core.model_registry import WebServiceBinding


class WebDesktopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='operator-web-desktop-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.profile = self.root / 'web'; self.profile.mkdir()
        (self.profile / 'manager.lock').write_bytes(manager.LOCK_BYTES)
        (self.profile / 'profile.json').write_bytes(b'{}')
        self.home = self.root / 'home'; self.home.mkdir()
        self.target = self.home / 'config.toml'
        self.original = b'\xef\xbb\xbfmodel = "native-example"\r\n# preserved comment\r\n[features]\r\nplugins = true\r\n'
        self.target.write_bytes(self.original)
        self.binding = {'profile_sha256': desktop.digest(b'{}'), 'session_sha256': 'a' * 64}
        self.route = replace(manager.service.text_route(tools=True), api_base='http://127.0.0.1:54321/v1',
            web_binding=WebServiceBinding(**self.binding, token='private-local-test-token'))
        for name, value in (
                ('load_profile', lambda profile: (profile, {})),
                ('route_preview', lambda profile: self.binding),
                ('resolve_route', lambda profile, expected: self.route),
                ('resolve_routes', lambda profile, expected: (self.route,)),
                ('current_record', lambda profile: {'attempt': 'fixture'}),
                ('state_path', lambda profile, record: profile),
                ('session_snapshot', lambda state, record: (None, self.binding['session_sha256'])),
                ('check_binding_files', lambda profile, expected: None)):
            mock = patch.object(desktop, name, side_effect=value)
            mock.start(); self.addCleanup(mock.stop)

    def prepare(self):
        return desktop.prepare(self.profile, self.home)

    def test_prepare_has_no_host_mutation_and_repeat_reuses_one_trial(self):
        first = self.prepare()
        self.assertEqual(first['status'], 'prepared')
        self.assertEqual(self.target.read_bytes(), self.original)
        files = sorted((self.profile / 'desktop').rglob('*'))
        second = self.prepare()
        self.assertTrue(second['reused'])
        self.assertEqual(sorted((self.profile / 'desktop').rglob('*')), files)
        self.assertNotIn('private-local-test-token', json.dumps(first))
        _, plan, raw, _ = desktop.load_trial(self.profile, self.home)
        self.assertNotIn('private-local-test-token', json.dumps(plan))
        parsed = desktop.parse(raw['addition.toml'])
        provider = parsed['model_providers'][first['provider']]
        self.assertEqual(provider['request_max_retries'], 0)
        self.assertEqual(provider['stream_max_retries'], 0)
        self.assertFalse(provider['requires_openai_auth'])
        self.assertFalse(provider['supports_websockets'])
        self.assertEqual(set(parsed), {'model_providers'})
        catalog = json.loads(raw['catalog.json'])
        self.assertEqual(len(catalog['models']), 1)
        self.assertEqual(catalog['models'][0]['slug'], self.route.slug)
        self.assertIsNone(catalog['models'][0]['tool_mode'])
        self.assertIsNone(catalog['models'][0]['apply_patch_tool_type'])

    def test_connect_and_restore_preserve_exact_original_and_later_user_edits(self):
        first = self.prepare()
        report = desktop.connect(self.profile, self.home)
        self.assertEqual(report['status'], 'connected')
        registered = self.target.read_bytes()
        self.assertTrue(registered.startswith(self.original))
        before = desktop.parse(self.original)
        current = desktop.parse(registered)
        self.assertEqual(current['model'], before['model'])
        self.assertEqual(current['features'], before['features'])
        self.assertNotIn('model_provider', current)
        self.assertNotIn('model_catalog_json', current)
        self.assertNotIn('approval_policy', current)
        self.assertEqual(desktop.connect(self.profile, self.home)['reused'], True)
        with patch.object(desktop, 'file_digest', return_value='new-source'):
            self.assertTrue(desktop.connect(self.profile, self.home)['reused'])
        self.assertEqual(self.target.read_bytes(), registered)
        later = b'\r\n[projects."C:/unrelated"]\r\ntrust_level="trusted"\r\n'
        self.target.write_bytes(registered + later)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'connected')
        self.assertEqual(desktop.disconnect(self.profile, self.home)['status'], 'disconnected')
        self.assertEqual(self.target.read_bytes(), self.original + later)
        self.assertTrue(desktop.disconnect(self.profile, self.home)['reused'])
        self.assertFalse(report['desktop_acceptance'])
        self.assertIn(first['provider'], current['model_providers'])
        self.assertNotIn('profiles', current)

    def test_explicit_rebind_keeps_provider_and_restores_original_after_service_restart(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        old_folder, old_plan, old_files, _ = desktop.load_trial(self.profile, self.home)
        old_registered = self.target.read_bytes()
        later = b'\n# later owner comment\n'
        self.target.write_bytes(old_registered + later)
        self.binding = {'profile_sha256': self.binding['profile_sha256'],
            'session_sha256': 'b' * 64}
        self.route = replace(self.route, api_base='http://127.0.0.1:54322/v1',
            web_binding=WebServiceBinding(**self.binding, token='new-private-local-token'))
        status = desktop.status(self.profile, self.home)
        self.assertEqual(status['status'], 'stale')
        self.assertEqual(status['reason'], 'service_generation_changed')
        report = desktop.rebind(self.profile, self.home)
        self.assertEqual(report['status'], 'connected')
        self.assertTrue(report['live_desktop_adoption_unverified'])
        self.assertEqual(report['provider'], old_plan['provider'])
        current_folder, plan, files, _ = desktop.load_trial(self.profile, self.home)
        self.assertNotEqual(current_folder, old_folder)
        self.assertEqual(plan['rebind_from'], old_folder.name)
        self.assertEqual((current_folder / 'before-rebind.toml').read_bytes(), old_registered + later)
        self.assertEqual(old_files['addition.toml'], (old_folder / 'addition.toml').read_bytes())
        self.assertEqual(desktop.parse(self.target.read_bytes())['model_providers'][plan['provider']]['base_url'],
            self.route.api_base)
        self.assertNotIn(b'private-local-test-token', self.target.read_bytes())
        self.assertTrue(desktop.rebind(self.profile, self.home)['reused'])
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'connected')
        desktop.disconnect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), self.original + later)

    def test_rebind_rejects_modified_owned_block_or_uncertain_transaction(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        self.binding = {'profile_sha256': self.binding['profile_sha256'],
            'session_sha256': 'b' * 64}
        self.route = replace(self.route, api_base='http://127.0.0.1:54322/v1',
            web_binding=WebServiceBinding(**self.binding, token='new-private-local-token'))
        changed = self.target.read_bytes().replace(b'request_max_retries = 0', b'request_max_retries = 3')
        self.target.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, 'config_changed'):
            desktop.rebind(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), changed)
        self.assertFalse((self.profile / 'desktop/rebind.json').exists())
        self.target.write_bytes(changed.replace(b'request_max_retries = 3', b'request_max_retries = 0'))
        with patch.object(desktop, 'replace_config', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): desktop.rebind(self.profile, self.home)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'changed')
        with self.assertRaisesRegex(ValueError, 'rebind_uncertain'):
            desktop.rebind(self.profile, self.home)
        self.binding = {'profile_sha256': self.binding['profile_sha256'],
            'session_sha256': 'a' * 64}
        with self.assertRaisesRegex(ValueError, 'rebind_uncertain'):
            desktop.rebind(self.profile, self.home)

    def test_native_appended_tables_inside_markers_survive_rebind_and_disconnect(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        old_folder, old_plan, old_files, _ = desktop.load_trial(self.profile, self.home)
        inserted = b'\n# native-owned addition\n[hooks]\nconfigured = true\n'
        later = b'\r\n[projects."C:/unrelated"]\r\ntrust_level="trusted"\r\n'
        changed = self.target.read_bytes().replace(desktop.END, inserted + desktop.END) + later
        self.target.write_bytes(changed)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'connected')
        self.assertTrue(desktop.connect(self.profile, self.home)['reused'])
        self.assertEqual(self.target.read_bytes(), changed)
        self.binding = {'profile_sha256': self.binding['profile_sha256'], 'session_sha256': 'b' * 64}
        self.route = replace(self.route, api_base='http://127.0.0.1:54322/v1',
            web_binding=WebServiceBinding(**self.binding, token='new-private-local-token'))
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'stale')
        self.assertEqual(desktop.rebind(self.profile, self.home)['provider'], old_plan['provider'])
        folder, _, files, _ = desktop.load_trial(self.profile, self.home)
        self.assertEqual((folder / 'before-rebind.toml').read_bytes(), changed)
        self.assertEqual((old_folder / 'addition.toml').read_bytes(), old_files['addition.toml'])
        expected = self.original + files['addition.toml'].replace(desktop.END, inserted + desktop.END) + later
        self.assertEqual(self.target.read_bytes(), expected)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'connected')
        desktop.disconnect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), self.original + inserted + later)

    def test_additions_to_owned_provider_or_marker_conflicts_remain_rejected(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        registered = self.target.read_bytes()
        _, plan, _, _ = desktop.load_trial(self.profile, self.home)
        additions = (
            b'unknown_provider_setting = true\n',
            ('[model_providers.' + plan['provider'] + '.extra]\nvalue = true\n').encode(),
            desktop.BEGIN,
            desktop.END,
        )
        for addition in additions:
            with self.subTest(addition=addition):
                changed = registered.replace(desktop.END, addition + desktop.END)
                self.target.write_bytes(changed)
                for action in (desktop.rebind, desktop.disconnect):
                    with self.assertRaises(ValueError):
                        action(self.profile, self.home)
                    self.assertEqual(self.target.read_bytes(), changed)
                self.assertFalse((self.profile / 'desktop/rebind.json').exists())

    def test_changed_snapshot_stops_connect_without_overwriting_user_bytes(self):
        self.prepare()
        changed = self.original + b'\n# concurrent owner edit\n'
        self.target.write_bytes(changed)
        with self.assertRaises(ValueError): desktop.connect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), changed)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'changed')

    def test_changed_managed_block_is_never_replaced_or_removed(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        changed = self.target.read_bytes().replace(b'request_max_retries = 0', b'request_max_retries = 3')
        self.target.write_bytes(changed)
        for action in (desktop.connect, desktop.disconnect, desktop.prepare):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError): action(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), changed)

    def test_stale_service_or_changed_source_stops_before_connect(self):
        self.prepare()
        with patch.object(desktop, 'resolve_routes', side_effect=ValueError('stale')):
            with self.assertRaises(ValueError): desktop.connect(self.profile, self.home)
            with self.assertRaises(ValueError): self.prepare()
        with patch.object(desktop, 'file_digest', return_value='changed'):
            with self.assertRaises(ValueError): desktop.connect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_recovery_needs_no_service_and_new_prepare_preserves_first_original(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        old = desktop.load_trial(self.profile, self.home)[0]
        with patch.object(desktop, 'resolve_route', side_effect=ValueError('stopped')):
            desktop.disconnect(self.profile, self.home)
        self.assertEqual((old / 'before.toml').read_bytes(), self.original)
        self.assertFalse(self.prepare()['reused'])
        self.assertNotEqual(desktop.load_trial(self.profile, self.home)[0], old)

    def test_interrupted_connect_never_reapplies_but_exact_bytes_can_be_removed(self):
        self.prepare()
        trial, _, files, _ = desktop.load_trial(self.profile, self.home)
        self.target.write_bytes(self.original + files['addition.toml'])
        desktop.service.write_json(trial / 'journal.json', {'phase': 'connecting'})
        with self.assertRaises(ValueError): desktop.connect(self.profile, self.home)
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'changed')
        desktop.disconnect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_changed_preparation_and_foreign_home_are_rejected(self):
        self.prepare()
        trial, _, _, _ = desktop.load_trial(self.profile, self.home)
        (trial / 'addition.toml').write_bytes(b'# replaced')
        with self.assertRaises(ValueError): desktop.connect(self.profile, self.home)
        foreign = self.root / 'foreign'; foreign.mkdir()
        with self.assertRaises(ValueError): desktop.status(self.profile, foreign)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_interrupted_disconnect_recognizes_exact_removed_bytes_without_rewriting(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        real_write = desktop.service.write_json
        def interrupted(path, value):
            if path.name == 'journal.json' and value == {'phase': 'disconnected'}:
                raise OSError('fixture interruption')
            return real_write(path, value)
        with patch.object(desktop.service, 'write_json', side_effect=interrupted):
            with self.assertRaises(OSError): desktop.disconnect(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), self.original)
        with patch.object(desktop, 'replace_config', side_effect=AssertionError('must not rewrite')):
            self.assertEqual(desktop.disconnect(self.profile, self.home)['status'], 'disconnected')

    def test_uninstall_requires_explicit_trial_detachment_before_other_operations(self):
        import operator_uninstall
        actual_profile = self.root / '.codex/operator-web-service'
        actual_profile.parent.mkdir()
        self.profile.rename(actual_profile); self.profile = actual_profile
        self.prepare(); desktop.connect(self.profile, self.home)
        with patch('operator_web_service.status', return_value={'status':'stopped'}), \
                self.assertRaisesRegex(ValueError, 'disconnect_web_desktop_trial_before_uninstall'):
            operator_uninstall.inspect(self.root, self.target, 4317)

    def test_absent_config_restored_to_absence(self):
        self.target.unlink()
        self.prepare(); desktop.connect(self.profile, self.home)
        self.assertTrue(self.target.exists())
        desktop.disconnect(self.profile, self.home)
        self.assertFalse(self.target.exists())

    def test_read_only_absent_status_and_unowned_markers(self):
        before = sorted(self.root.rglob('*'))
        self.assertEqual(desktop.status(self.profile, self.home)['status'], 'absent')
        self.assertEqual(sorted(self.root.rglob('*')), before)
        self.target.write_bytes(self.original + desktop.BEGIN + desktop.END)
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse((self.profile / 'desktop').exists())

    def test_added_settings_cannot_change_default_or_existing_table(self):
        for fragment in (b'\nmodel="changed"\n', b'\n[features]\nplugins=false\n'):
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                desktop.check_scope(self.original, self.original + fragment, fragment)

    def test_check_distinguishes_registered_provider_from_missing_native_menu(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        config = desktop.parse(self.target.read_bytes())
        rows = [{'model': 'native-example', 'hidden': False}]
        with patch.object(desktop, 'native_models', return_value=(config, rows, 'a' * 64)):
            report = desktop.check(self.profile, self.home)
        self.assertTrue(report['provider_registered'])
        self.assertFalse(report['web_model_listed'])
        self.assertTrue(report['default_provider_is_native'])
        self.assertIn('web_model_not_listed', report['missing_checks'])
        self.assertIn('per_model_route_not_verified', report['missing_checks'])
        self.assertFalse(report['restart_alone_sufficient'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_catalog_visibility_never_proves_provider_route_or_live_desktop(self):
        rows = [{'model': self.route.slug, 'hidden': False}]
        config = {'model_catalog_json': 'isolated.json', 'model_providers': {'web': {}}}
        first = desktop.assess_models(config, rows, 'web', self.route.slug)
        self.assertTrue(first['web_model_listed'])
        self.assertIn('per_model_route_not_verified', first['missing_checks'])
        second = desktop.assess_models({**config, 'model_provider': 'web'}, rows, 'web', self.route.slug)
        self.assertTrue(second['default_provider_is_trial'])
        self.assertFalse(second['native_picker_acceptance'])
        self.assertFalse(second['live_desktop_checked'])
        self.assertEqual(second['missing_checks'], ['live_desktop_menu_not_verified'])
        mixed = desktop.assess_models({**config, 'model_provider': 'web'},
            rows + [{'model': 'native-example', 'hidden': False}], 'web', self.route.slug)
        self.assertIn('mixed_catalog_route_not_verified', mixed['missing_checks'])
        self.assertEqual(mixed['other_models_listed'], 1)

    def test_hidden_missing_and_ambiguous_rows_remain_distinct(self):
        config = {'model_providers': {'web': {}}}
        hidden = desktop.assess_models(config, [{'model': self.route.slug, 'hidden': True}], 'web', self.route.slug)
        self.assertIn('web_model_hidden', hidden['missing_checks'])
        self.assertNotIn('web_model_not_listed', hidden['missing_checks'])
        for rows in ([{'model': self.route.slug}],
                [{'model': self.route.slug, 'hidden': False}] * 2,
                [{'model': self.route.slug, 'hidden': 0}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                desktop.assess_models(config, rows, 'web', self.route.slug)

    def test_check_rejects_concurrent_config_edit_without_restoring_it(self):
        self.prepare(); desktop.connect(self.profile, self.home)
        newer = self.target.read_bytes() + b'\n# concurrent user edit\n'
        def read(_home):
            self.target.write_bytes(newer)
            return desktop.parse(newer), [], 'a' * 64
        with patch.object(desktop, 'native_models', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'snapshot_changed'):
                desktop.check(self.profile, self.home)
        self.assertEqual(self.target.read_bytes(), newer)

    def test_check_without_registration_never_starts_native_child(self):
        with patch.object(desktop, 'native_models', side_effect=AssertionError('must not start')):
            self.assertEqual(desktop.check(self.profile, self.home)['status'], 'absent')
            self.prepare()
            self.assertEqual(desktop.check(self.profile, self.home)['status'], 'prepared')

    def test_native_model_read_uses_only_bounded_metadata_methods(self):
        from operator_core import app_server, beeper_relay
        import os
        calls = []
        class Client:
            def __init__(self, *_): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def request(self, method, params):
                calls.append((method, params))
                if method == 'config/read': return {'config': {}}
                if params['cursor'] is None:
                    return {'data': [{'model': 'native-example', 'hidden': False}], 'nextCursor': 'page2'}
                return {'data': [{'model': 'web', 'hidden': False}], 'nextCursor': None}
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home)}), \
                patch.object(app_server, 'AppServerSession', Client), \
                patch.object(beeper_relay, 'discover_codex_executable', return_value=self.target):
            config, rows, _ = desktop.native_models(self.home)
        self.assertEqual([m for m, _ in calls], ['config/read', 'model/list', 'model/list'])
        self.assertEqual([r['model'] for r in rows], ['native-example', 'web'])
        self.assertEqual(calls[1][1], {'includeHidden': True, 'cursor': None, 'limit': 100})
        self.assertEqual(calls[2][1]['cursor'], 'page2')

    def test_model_cursor_loop_and_foreign_home_stop_without_retry(self):
        from operator_core import app_server, beeper_relay
        import os
        calls = []
        class Client:
            def __init__(self, *_): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def request(self, method, params):
                calls.append(method)
                return {'config': {}} if method == 'config/read' else {'data': [], 'nextCursor': 'same'}
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home)}), \
                patch.object(app_server, 'AppServerSession', Client), \
                patch.object(beeper_relay, 'discover_codex_executable', return_value=self.target):
            with self.assertRaisesRegex(ValueError, 'model_cursor'):
                desktop.native_models(self.home)
            self.assertEqual(calls, ['config/read', 'model/list', 'model/list'])
            with self.assertRaisesRegex(ValueError, 'home_mismatch'):
                desktop.native_models(self.profile)
            self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
