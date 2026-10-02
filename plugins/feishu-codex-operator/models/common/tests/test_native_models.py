"""Disposable native-profile transactions; never contact a provider or native task."""
from pathlib import Path
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
import tempfile
from threading import Event
import tomllib
import unittest
from unittest.mock import patch
import operator_native_models as subject


def manifest():
    return {'version': 1, 'contract': 'native_responses_v1', 'kind': 'local',
        'profile': 'operator-native-fixture',
        'provider': {'name': 'Disposable fixture', 'base_url': 'http://127.0.0.1:1/v1', 'env_key': ''},
        'model': {'id': 'fixture/exact-model', 'display_name': 'Explicit fixture',
            'context_window': 32768, 'reasoning_efforts': ['none', 'low'],
            'default_reasoning_effort': 'none', 'input_modalities': ['text'],
            'tool_mode': 'standard', 'supports_search_tool': False}, 'web_search': 'disabled'}


class NativeModelsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='operator-native-profile-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir()
        self.state = self.root / 'registration'
        self.manifest = self.root / 'native.json'
        self.manifest.write_bytes(subject.json_bytes(manifest()))
        self.config = self.home / 'config.toml'
        self.config.write_bytes(b'# exact defaults\r\nmodel="native-owner"\r\n')
        self.profile = self.home / 'operator-native-fixture.config.toml'
        self.catalog = self.home / 'operator-native-fixture.catalog.json'

    def prepare(self):
        return subject.prepare(self.state, self.home, self.manifest)

    def target_lock_path(self):
        return self.home / '.operator-native-fixture.operation.lock'

    def test_local_preview_and_status_show_bound_identity_without_writing_targets(self):
        original_config = self.config.read_bytes()
        expected = {'model_id': 'fixture/exact-model', 'kind': 'local',
            'codex_home': str(self.home),
            'original_files': {'profile': False, 'catalog': False}}
        preview = self.prepare()
        self.assertEqual({key: preview[key] for key in expected}, expected)
        reused = self.prepare()
        self.assertTrue(reused['reused'])
        self.assertEqual({key: reused[key] for key in expected}, expected)
        self.assertEqual({key: subject.status(self.state, self.home)[key]
            for key in expected}, expected)
        self.assertEqual(self.config.read_bytes(), original_config)
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())

    def test_api_preview_excludes_endpoint_and_key_reference(self):
        source = manifest()
        source['kind'] = 'api'
        source['provider']['base_url'] = 'https://api.example.test/v1'
        source['provider']['env_key'] = 'PRIVATE_API_KEY'
        source['model']['id'] = 'api/exact-model'
        self.manifest.write_bytes(subject.json_bytes(source))
        preview = self.prepare()
        self.assertEqual(preview['model_id'], 'api/exact-model')
        self.assertEqual(preview['kind'], 'api')
        self.assertEqual(preview['codex_home'], str(self.home))
        self.assertEqual(preview['original_files'], {'profile': False, 'catalog': False})
        self.assertEqual({key: subject.status(self.state, self.home)[key]
            for key in ('model_id', 'kind', 'codex_home', 'original_files')},
            {key: preview[key] for key in ('model_id', 'kind', 'codex_home', 'original_files')})
        public = json.dumps(preview)
        self.assertNotIn('api.example.test', public)
        self.assertNotIn('PRIVATE_API_KEY', public)
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())

    def test_two_states_cannot_install_the_same_profile_concurrently(self):
        self.prepare()
        other = self.root / 'registration-other'
        subject.prepare(other, self.home, self.manifest)
        entered, release = Event(), Event()
        replace = subject.replace_file
        def pause_catalog(path, expected, replacement):
            if path == self.catalog:
                entered.set()
                if not release.wait(10): raise AssertionError('fixture release missing')
            return replace(path, expected, replacement)
        with patch.object(subject, 'replace_file', side_effect=pause_catalog):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(subject.install, self.state, self.home)
                try:
                    self.assertTrue(entered.wait(10))
                    with self.assertRaisesRegex(subject.NativeModelsError, 'target_operation_in_progress'):
                        subject.install(other, self.home)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)['status'], 'installed')
        self.assertEqual(subject.status(self.state, self.home)['status'], 'installed')
        self.assertEqual(subject.decode((other / 'journal.json').read_bytes())['phase'], 'prepared')
        current = self.profile.read_bytes(), self.catalog.read_bytes()
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_changed'):
            subject.restore(other, self.home)
        self.assertEqual((self.profile.read_bytes(), self.catalog.read_bytes()), current)

    def test_install_cannot_take_files_while_another_state_is_restoring(self):
        self.prepare()
        other = self.root / 'registration-other'
        subject.prepare(other, self.home, self.manifest)
        subject.install(self.state, self.home)
        entered, release = Event(), Event()
        write = subject.write_record
        def pause_restored(path, value):
            if path == self.state / 'journal.json' and value == {'phase': 'restored'}:
                entered.set()
                if not release.wait(10): raise AssertionError('fixture release missing')
            return write(path, value)
        with patch.object(subject, 'write_record', side_effect=pause_restored):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(subject.restore, self.state, self.home)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
                    with self.assertRaisesRegex(subject.NativeModelsError, 'target_operation_in_progress'):
                        subject.install(other, self.home)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)['status'], 'restored')
        self.assertEqual(subject.install(other, self.home)['status'], 'installed')

    def test_occupied_target_lock_rejects_without_overwriting_or_phase_change(self):
        self.prepare()
        before = (self.state / 'journal.json').read_bytes()
        self.target_lock_path().write_bytes(b'unknown retained operation')
        for operation in (subject.install, subject.restore):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(subject.NativeModelsError, 'target_operation_in_progress'):
                    operation(self.state, self.home)
                self.assertEqual((self.state / 'journal.json').read_bytes(), before)
                self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
                self.assertEqual(self.target_lock_path().read_bytes(), b'unknown retained operation')

    def test_failed_install_keeps_claim_until_its_explicit_restore(self):
        self.prepare()
        other = self.root / 'registration-other'
        subject.prepare(other, self.home, self.manifest)
        replace = subject.replace_file
        def fail_catalog(path, expected, replacement):
            if path == self.catalog: raise OSError('fixture before first target')
            return replace(path, expected, replacement)
        with patch.object(subject, 'replace_file', side_effect=fail_catalog):
            with self.assertRaises(OSError): subject.install(self.state, self.home)
        marker = self.target_lock_path().read_bytes()
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_operation_in_progress'):
            subject.install(other, self.home)
        self.assertEqual(self.target_lock_path().read_bytes(), marker)
        self.assertEqual(subject.restore(self.state, self.home)['status'], 'restored')
        self.assertFalse(self.target_lock_path().exists())
        subject.install(other, self.home)
        current = self.profile.read_bytes(), self.catalog.read_bytes()
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_changed'):
            subject.restore(self.state, self.home)
        self.assertEqual((self.profile.read_bytes(), self.catalog.read_bytes()), current)
        self.assertFalse(self.target_lock_path().exists())
        self.assertEqual(subject.restore(other, self.home)['status'], 'restored')

    def test_old_uncertain_install_without_target_claim_cannot_adopt_new_files(self):
        self.prepare()
        other = self.root / 'registration-other'
        subject.prepare(other, self.home, self.manifest)
        subject.write_record(self.state / 'journal.json', {'phase': 'installing'})
        subject.install(other, self.home)
        current = self.profile.read_bytes(), self.catalog.read_bytes()
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_recovery_ownership_missing'):
            subject.restore(self.state, self.home)
        self.assertEqual((self.profile.read_bytes(), self.catalog.read_bytes()), current)
        self.assertFalse(self.target_lock_path().exists())
        self.assertEqual(subject.restore(other, self.home)['status'], 'restored')

    def test_changed_target_lock_is_preserved_and_stops_remaining_publication(self):
        self.prepare()
        replace = subject.replace_file
        def change_claim_after_catalog(path, expected, replacement):
            result = replace(path, expected, replacement)
            if path == self.catalog:
                self.target_lock_path().write_bytes(b'later independent lock edit')
            return result
        with patch.object(subject, 'replace_file', side_effect=change_claim_after_catalog):
            with self.assertRaisesRegex(subject.NativeModelsError, 'target_lock_changed'):
                subject.install(self.state, self.home)
        self.assertTrue(self.catalog.exists()); self.assertFalse(self.profile.exists())
        self.assertEqual(self.target_lock_path().read_bytes(), b'later independent lock edit')
        self.assertEqual(subject.status(self.state, self.home)['status'], 'uncertain')
        with self.assertRaises(subject.NativeModelsError): subject.restore(self.state, self.home)
        self.assertEqual(self.target_lock_path().read_bytes(), b'later independent lock edit')

    def test_partial_restore_retains_target_lock_and_never_retries(self):
        self.prepare(); subject.install(self.state, self.home)
        replace = subject.replace_file
        def fail_catalog_remove(path, expected, replacement):
            if path == self.catalog: raise OSError('fixture interrupted restore')
            return replace(path, expected, replacement)
        with patch.object(subject, 'replace_file', side_effect=fail_catalog_remove):
            with self.assertRaises(OSError): subject.restore(self.state, self.home)
        marker = self.target_lock_path().read_bytes()
        self.assertFalse(self.profile.exists()); self.assertTrue(self.catalog.exists())
        self.assertEqual(subject.status(self.state, self.home)['status'], 'uncertain')
        with self.assertRaisesRegex(subject.NativeModelsError, 'uncertain_transaction'):
            subject.restore(self.state, self.home)
        self.assertEqual(self.target_lock_path().read_bytes(), marker)

    def test_unknown_preflight_journal_keeps_claim_and_original_error(self):
        self.prepare()
        def invalid_journal(*args):
            (self.state / 'journal.json').write_bytes(b'{partial fixture')
            raise OSError('fixture preflight failure')
        with patch.object(subject, 'artifacts', side_effect=invalid_journal):
            with self.assertRaisesRegex(OSError, 'fixture preflight failure'):
                subject.install(self.state, self.home)
        self.assertTrue(self.target_lock_path().is_file())
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows directory reparse point')
    def test_junction_ancestor_rejected_without_python312_path_helper(self):
        import _winapi
        junction = self.root / 'home-junction'
        _winapi.CreateJunction(str(self.home), str(junction))
        try:
            self.assertFalse(junction.is_symlink())
            self.assertTrue(junction.lstat().st_file_attributes & 0x400)
            # Python 3.11 has no is_junction helper; its fallback returned False.
            with patch.object(Path, 'is_junction', return_value=False, create=True):
                with self.assertRaisesRegex(subject.NativeModelsError, 'linked_path_rejected'):
                    subject.checked_path(junction / 'new-profile.config.toml', exists=False)
        finally:
            os.rmdir(junction)

    def test_prepare_install_and_restore_keep_default_bytes_and_bound_model(self):
        before = self.config.read_bytes()
        self.assertEqual(subject.status(self.state, self.home)['status'], 'absent')
        self.assertFalse(self.state.exists())
        self.assertEqual(self.prepare()['status'], 'prepared')
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
        self.assertTrue(self.prepare()['reused'])
        result = subject.install(self.state, self.home)
        self.assertEqual(result['status'], 'installed')
        self.assertFalse(result['desktop_verified'])
        profile = tomllib.loads(self.profile.read_text(encoding='utf-8'))
        catalog = json.loads(self.catalog.read_text(encoding='utf-8'))
        row = catalog['models'][0]
        self.assertEqual(profile['model'], row['slug'])
        self.assertEqual(profile['model'], manifest()['model']['id'])
        self.assertEqual(profile['model_catalog_json'], str(self.catalog))
        provider = profile['model_providers'][profile['model_provider']]
        self.assertEqual(provider['base_url'], manifest()['provider']['base_url'])
        self.assertEqual(provider['request_max_retries'], 0)
        self.assertEqual(provider['stream_max_retries'], 0)
        self.assertFalse(provider['requires_openai_auth'])
        self.assertEqual(row['supported_reasoning_levels'], [
            {'effort': 'none', 'description': 'none'}, {'effort': 'low', 'description': 'low'}])
        self.assertIsNone(row['apply_patch_tool_type'])
        self.assertTrue(row['node_repl_auto_review_required'])
        self.assertEqual(row['base_instructions'], '')
        self.assertEqual(row['multi_agent_version'], 'disabled')
        self.assertFalse(row['use_responses_lite'])
        self.assertTrue(subject.install(self.state, self.home)['reused'])
        self.assertEqual(subject.restore(self.state, self.home)['status'], 'restored')
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
        self.assertTrue(subject.restore(self.state, self.home)['reused'])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue((self.state / 'original.profile').exists())

    def test_legacy_originals_still_restore_empty_and_nonempty_files_exactly(self):
        old = b'# original profile\r\nmodel="old"\r\n'
        self.prepare(); subject.install(self.state, self.home)
        # Legacy receipts may own pre-existing files. New preparation no longer
        # adopts them, but explicit restoration must retain old recovery support.
        plan_path = self.state / 'plan.json'
        plan = json.loads(plan_path.read_text())
        for kind, raw in (('profile', old), ('catalog', b'')):
            (self.state / ('original.' + kind)).write_bytes(raw)
            plan['files'][kind].update(existed=True, original_sha256=subject.digest(raw))
        plan_path.write_bytes(subject.json_bytes(plan))
        subject.restore(self.state, self.home)
        self.assertEqual(self.profile.read_bytes(), old)
        self.assertTrue(self.catalog.is_file()); self.assertEqual(self.catalog.read_bytes(), b'')

    def test_new_prepare_cannot_adopt_unknown_profile_or_catalog(self):
        for target, raw in ((self.profile, b'approval_policy="never"\nsandbox_mode="read-only"\n'),
                (self.catalog, b'{"models":[]}')):
            with self.subTest(target=target.name):
                target.write_bytes(raw)
                with self.assertRaisesRegex(subject.NativeModelsError, 'unowned_target_exists'):
                    self.prepare()
                self.assertEqual(target.read_bytes(), raw)
                self.assertFalse(self.state.exists())
                target.unlink()

    def test_base_provider_collision_rejected_at_prepare_and_after_preparation(self):
        collision = (b'\n[model_providers.operator_native_native_fixture]\n'
            b'http_headers={Authorization="synthetic fixture"}\n')
        original = self.config.read_bytes()
        self.config.write_bytes(original + collision)
        with self.assertRaisesRegex(subject.NativeModelsError, 'base_provider_collision'):
            self.prepare()
        self.assertFalse(self.state.exists())
        self.config.write_bytes(original)
        self.prepare()
        self.config.write_bytes(original + collision)
        with self.assertRaisesRegex(subject.NativeModelsError, 'base_provider_collision'):
            subject.install(self.state, self.home)
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
        self.assertEqual(self.config.read_bytes(), original + collision)
        self.assertEqual(subject.status(self.state, self.home)['reason'], 'base_provider_collision')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = subject.main(['status', '--state', str(self.state), '--home', str(self.home)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'changed')

    def test_base_collision_after_install_does_not_block_own_file_restore(self):
        self.prepare(); subject.install(self.state, self.home)
        base = self.config.read_bytes() + b'\n[model_providers.operator_native_native_fixture]\nname="new owner"\n'
        self.config.write_bytes(base)
        self.assertEqual(subject.status(self.state, self.home)['status'], 'changed')
        subject.restore(self.state, self.home)
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())
        self.assertEqual(self.config.read_bytes(), base)

    def test_later_user_edits_block_install_and_restore_without_writes(self):
        self.prepare()
        self.catalog.write_bytes(b'created after preview')
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_changed'):
            subject.install(self.state, self.home)
        self.assertFalse(self.profile.exists())
        self.assertEqual(self.catalog.read_bytes(), b'created after preview')
        self.assertEqual(subject.status(self.state, self.home)['status'], 'changed')
        self.catalog.unlink()
        subject.install(self.state, self.home)
        self.profile.write_bytes(self.profile.read_bytes() + b'# user edit\n')
        current = self.profile.read_bytes(), self.catalog.read_bytes()
        with self.assertRaisesRegex(subject.NativeModelsError, 'target_changed'):
            subject.restore(self.state, self.home)
        self.assertEqual((self.profile.read_bytes(), self.catalog.read_bytes()), current)

    def test_partial_install_is_terminal_until_explicit_checked_restore(self):
        self.prepare()
        replace = subject.replace_file
        def fail_profile(path, expected, replacement):
            if path == self.profile: raise OSError('simulated interrupted write')
            return replace(path, expected, replacement)
        with patch.object(subject, 'replace_file', side_effect=fail_profile):
            with self.assertRaises(OSError): subject.install(self.state, self.home)
        self.assertTrue(self.catalog.exists()); self.assertFalse(self.profile.exists())
        self.assertEqual(subject.status(self.state, self.home)['status'], 'uncertain')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(subject.main(['status', '--state', str(self.state), '--home', str(self.home)]), 2)
        with self.assertRaisesRegex(subject.NativeModelsError, 'uncertain_transaction'):
            subject.install(self.state, self.home)
        subject.restore(self.state, self.home)
        self.assertFalse(self.catalog.exists()); self.assertFalse(self.profile.exists())

    def test_changed_source_blocks_install_but_does_not_block_exact_restore(self):
        self.prepare()
        plan_path = self.state / 'plan.json'
        plan = json.loads(plan_path.read_text())
        plan['source_sha256'] = 'f' * 64
        plan_path.write_bytes(subject.json_bytes(plan))
        with self.assertRaisesRegex(subject.NativeModelsError, 'source_changed'):
            subject.install(self.state, self.home)
        with patch.object(subject, 'artifacts', side_effect=AssertionError('must not rebuild during recovery')):
            self.assertEqual(subject.restore(self.state, self.home)['status'], 'restored')

    def test_preparation_tamper_and_home_switch_fail_before_any_target_write(self):
        self.prepare()
        other = self.root / 'other'; other.mkdir()
        with self.assertRaisesRegex(subject.NativeModelsError, 'plan_identity_changed'):
            subject.install(self.state, other)
        (self.state / 'prepared.catalog').write_bytes(b'changed')
        with self.assertRaisesRegex(subject.NativeModelsError, 'preparation_changed'):
            subject.install(self.state, self.home)
        self.assertFalse(self.profile.exists()); self.assertFalse(self.catalog.exists())

    def test_manifest_rejects_adapted_routes_credentials_and_remote_http(self):
        wrong = [{'version': 2, 'models': []}]
        for patcher in (
            lambda value: value.update(contract='responses_adapter_v1'),
            lambda value: value['provider'].update(token='must not save'),
            lambda value: value['provider'].update(base_url='https://user:password@example.test/v1'),
            lambda value: value['provider'].update(base_url='http://example.test/v1'),
            lambda value: value['provider'].update(base_url='https://127.0.0.1/v1?key=secret'),
            lambda value: value['provider'].update(base_url='https://127.0.0.1/v1#secret'),
            lambda value: value.update(profile='../escape'),
            lambda value: value['model'].update(reasoning_efforts=['none', 'none']),
            lambda value: value['model'].update(context_window=True),
        ):
            value = manifest(); patcher(value); wrong.append(value)
        for value in wrong:
            with self.subTest(value=value), self.assertRaises(subject.NativeModelsError):
                subject.validate_manifest(value)
        with self.assertRaisesRegex(subject.NativeModelsError, 'duplicate_json_field'):
            subject.decode(b'{"version":1,"version":2}')

    def test_api_profile_keeps_only_environment_reference_without_reading_secret(self):
        value = manifest(); value['kind'] = 'api'
        value['provider'].update(base_url='https://provider.example/v1', env_key='FIXTURE_API_KEY')
        with patch.dict(os.environ, {'FIXTURE_API_KEY': 'private-value-never-read'}):
            files, _ = subject.artifacts(value, self.home)
        joined = b''.join(files.values())
        self.assertIn(b'FIXTURE_API_KEY', joined)
        self.assertNotIn(b'private-value-never-read', joined)

    def test_changed_or_linked_targets_and_occupied_lock_remain_untouched(self):
        self.prepare()
        (self.state / 'operation.lock').write_bytes(b'other operation')
        with self.assertRaisesRegex(subject.NativeModelsError, 'operation_in_progress'):
            subject.install(self.state, self.home)
        self.assertEqual((self.state / 'operation.lock').read_bytes(), b'other operation')
        (self.state / 'operation.lock').unlink()
        self.profile.write_bytes(b'linked original')
        twin = self.home / 'twin'; os.link(self.profile, twin)
        with self.assertRaisesRegex(subject.NativeModelsError, 'regular_file_required'):
            subject.install(self.state, self.home)
        self.assertEqual(twin.read_bytes(), b'linked original')

    def test_cli_default_is_readonly_and_errors_do_not_print_manifest_content(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = subject.main(['--state', str(self.state), '--home', str(self.home)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'absent')
        self.assertFalse(self.state.exists())
        self.manifest.write_bytes(b'{"private-value":')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = subject.main(['prepare', '--state', str(self.state), '--home', str(self.home),
                '--manifest', str(self.manifest)])
        self.assertEqual(result, 1)
        self.assertNotIn('private-value', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'], 'native_models_invalid_json')


if __name__ == '__main__':
    unittest.main()
