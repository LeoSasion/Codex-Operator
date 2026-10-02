"""Direct entry journal and real Windows config replacement in disposable homes."""
from pathlib import Path
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

from contextlib import closing, contextmanager
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import operator_direct_entry as subject
import operator_direct_profile as projection
import operator_native_models as native
from operator_core import windows_config_transaction as transaction
from test_native_models import manifest


@contextmanager
def isolated_guard(value):
    yield lambda: None


class DirectEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-direct-entry-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / '.codex').mkdir()
        self.home = self.root / 'home'; self.home.mkdir()
        self.before = b'# original\r\nmodel="native-owner"\r\nmodel_reasoning_effort="high"\r\n[features]\r\nshell_tool=true\r\n'
        self.config = self.home / 'config.toml'; self.config.write_bytes(self.before)
        (self.home / 'operator-native-route-only').write_bytes(subject.MARKER)
        self.state = self.root / 'registration'
        source = self.root / 'profile.json'; source.write_bytes(native.json_bytes(manifest()))
        native.prepare(self.state, self.home, source); native.install(self.state, self.home)
        self.plan = self.project / '.codex/operator-direct-startup/plans' / ('a' * 32) / 'plan.json'
        self.helper = self.root / 'native-helper.ps1'; self.helper.write_bytes(b'# fixture never executed\n')
        self.python = Path(sys.executable)
        self.addCleanup(patch.stopall)
        patch.object(subject, 'default_home', return_value=self.home).start()
        patch.dict(os.environ, {'CODEX_HOME': str(self.home)}).start()
        self.helper_check = patch.object(subject, 'helper_preview').start()
        patch.object(subject, 'lifecycle_guard', isolated_guard).start()

    def prepare(self):
        return subject.prepare(self.state, self.project, self.home, self.python, self.helper, self.plan)

    def activate(self, review):
        return subject.activate(self.plan, review['plan_sha256'], review['current_config_sha256'])

    def active(self):
        pointer = native.decode((self.home / 'operator-direct-entry/active.json').read_bytes())
        folder = self.home / 'operator-direct-entry/cycles' / pointer['cycle']
        return pointer, folder

    def test_prepare_and_preview_keep_config_credentials_cache_and_marker_exact(self):
        (self.home / 'auth.json').write_bytes(b'fixture auth untouched')
        (self.home / 'models_cache.json').write_bytes(b'fixture cache untouched')
        before = {path.name: path.read_bytes() for path in self.home.iterdir() if path.is_file()}
        prepared = self.prepare()
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(subject.preview(self.plan)['status'], 'preview')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.home.iterdir() if path.is_file()})
        self.assertFalse((self.home / 'operator-direct-entry').exists())
        self.assertEqual(prepared['model_requests'], 0)
        self.assertFalse(prepared['desktop_launch'])
        self.assertNotIn('provider', prepared)

    def test_fresh_cua_preferences_do_not_make_saved_profile_plan_stale(self):
        original = self.prepare()
        self.config.write_bytes(self.before + b'\n[cua]\npipe="later-owner-pipe"\n')
        fresh = subject.preview(self.plan)
        self.assertEqual(original['plan_sha256'], fresh['plan_sha256'])
        self.assertNotEqual(original['current_config_sha256'], fresh['current_config_sha256'])

    def test_changed_source_python_helper_or_profile_reject_before_cycle(self):
        self.prepare()
        with patch.object(subject, 'sources', return_value={}):
            with self.assertRaisesRegex(subject.DirectEntryError, 'source_changed'):
                subject.preview(self.plan)
        self.helper.write_bytes(b'# later-owner edit\n')
        with self.assertRaisesRegex(subject.DirectEntryError, 'dependency_changed'):
            subject.preview(self.plan)
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertFalse((self.home / 'operator-direct-entry').exists())

    def test_root_catalog_unknown_profile_and_overrides_are_rejected(self):
        for prefix in (b'model_catalog_json="other.json"\n', b'profile="other"\n',
                b'model_provider="unknown"\n', b'openai_base_url="https://api.openai.com/v1"\n'):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(subject.DirectEntryError, 'native_baseline_required'):
                    subject.native_baseline(prefix + self.before)

    def test_prepare_requires_default_home_native_protection_and_new_plan(self):
        self.prepare()
        with self.assertRaisesRegex(subject.DirectEntryError, 'new_plan_required'):
            self.prepare()
        (self.home / 'operator-native-route-only').write_bytes(b'changed')
        with self.assertRaisesRegex(subject.DirectEntryError, 'native_protection_required'):
            subject.preview(self.plan)
        self.assertEqual(self.config.read_bytes(), self.before)

    @unittest.skipUnless(os.name == 'nt', 'real Windows replacement required')
    def test_applied_cycle_retains_original_projection_manifest_and_exact_transaction(self):
        review = self.prepare()
        result = self.activate(review)
        self.assertEqual(result['status'], 'config_applied')
        pointer, folder = self.active()
        intent = native.decode((folder / 'intent.json').read_bytes())
        self.assertEqual(subject.digest((folder / 'intent.json').read_bytes()), pointer['intent_sha256'])
        self.assertEqual((folder / 'config-before.bin').read_bytes(), self.before)
        self.assertEqual((folder / 'profile.json').read_bytes(), (self.state / 'manifest.json').read_bytes())
        self.assertEqual(projection.restore(self.config.read_bytes(), native.decode((folder / 'projection.json').read_bytes())), self.before)
        self.assertEqual((self.home / 'operator-native-route-only').read_bytes(), subject.MARKER)
        receipt = native.decode((folder / 'applied.json').read_bytes())
        self.assertEqual(transaction.inspect_transaction(Path(receipt['transaction'])).status, 'applied_witnessed')
        self.assertEqual(set(intent['files']), subject.FILES)
        with self.assertRaisesRegex(subject.DirectEntryError, 'native_restore_required'):
            subject.preview(self.plan)

    @unittest.skipUnless(os.name == 'nt', 'real Windows snapshot required')
    def test_stale_config_preview_and_plan_hash_do_not_create_cycle(self):
        review = self.prepare()
        with self.assertRaisesRegex(subject.DirectEntryError, 'plan_preview_changed'):
            subject.activate(self.plan, '0' * 64, review['current_config_sha256'])
        self.config.write_bytes(self.before + b'\n# later edit\n')
        with self.assertRaisesRegex(subject.DirectEntryError, 'config_preview_changed'):
            self.activate(review)
        self.assertFalse((self.home / 'operator-direct-entry').exists())

    @unittest.skipUnless(os.name == 'nt', 'real Windows snapshot required')
    def test_uncertain_transaction_is_terminal_with_no_second_dispatch(self):
        review = self.prepare()
        with patch.object(transaction, 'replace_config_once', return_value=transaction.TransactionResult('uncertain', 'fixture_boundary_failure', None)) as replace:
            with self.assertRaisesRegex(subject.DirectEntryError, 'config_transaction_uncertain'):
                self.activate(review)
            pointer, folder = self.active()
            self.assertEqual(native.decode((folder / 'applied.json').read_bytes())['status'], 'uncertain')
            with self.assertRaisesRegex(subject.DirectEntryError, 'native_restore_required'):
                self.activate(review)
            self.assertEqual(replace.call_count, 1)
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertEqual(len(list((folder.parent).iterdir())), 1)

    def test_unreferenced_partial_cycle_blocks_without_creating_pointer(self):
        self.prepare()
        folder = self.home / 'operator-direct-entry/cycles' / ('b' * 32)
        folder.mkdir(parents=True)
        (folder / 'config-before.bin').write_bytes(self.before)
        with self.assertRaisesRegex(subject.DirectEntryError, 'unreferenced_cycle_requires_review'):
            subject.preview(self.plan)
        self.assertFalse((folder.parent.parent / 'active.json').exists())

    def test_maintenance_status_is_read_only_for_absent_and_malformed_cycles(self):
        before = {path.name: path.read_bytes() for path in self.home.iterdir() if path.is_file()}
        self.assertEqual(subject.maintenance_status(self.home), {'status': 'maintenance_ready',
            'configuration_changed': False, 'model_requests': 0, 'desktop_launch': False})
        root = self.home / 'operator-direct-entry'; root.mkdir()
        pointer = root / 'active.json'; pointer.write_bytes(b'{"unknown":true}\n')
        with self.assertRaisesRegex(subject.DirectEntryError, 'active_cycle_invalid'):
            subject.maintenance_status(self.home)
        self.assertEqual(pointer.read_bytes(), b'{"unknown":true}\n')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.home.iterdir() if path.is_file()})

    def test_child_only_api_credential_is_not_saved_scope(self):
        item = manifest(); item['kind'] = 'api'
        item['provider'].update(base_url='https://fixture.invalid/v1', env_key='OPERATOR_DIRECT_TEST_ONLY_KEY')
        with patch.dict(os.environ, {'OPERATOR_DIRECT_TEST_ONLY_KEY': 'fixture-do-not-print'}):
            with self.assertRaisesRegex(subject.DirectEntryError, 'saved_api_credential_unavailable'):
                subject.saved_api_credential(item)

    @unittest.skipUnless(os.name == 'nt', 'saved Windows scope required')
    def test_empty_user_credential_shadows_machine_without_exposing_value(self):
        import winreg
        item = manifest(); item['kind'] = 'api'
        item['provider'].update(base_url='https://fixture.invalid/v1', env_key='OPERATOR_DIRECT_TEST_ONLY_KEY')
        @contextmanager
        def key_scope(*args):
            yield object()
        with patch.object(winreg, 'OpenKey', side_effect=key_scope) as opened, \
                patch.object(winreg, 'QueryValueEx', return_value=('', winreg.REG_SZ)):
            with self.assertRaisesRegex(subject.DirectEntryError, 'saved_api_credential_unavailable'):
                subject.saved_api_credential(item)
            self.assertEqual(opened.call_count, 1)

    def test_lifecycle_allows_exact_idle_saved_web_and_held_failed_event(self):
        import operator_web_service as web
        from operator_core import responses_labels
        runtime = self.project / '.codex/feishu-codex-operator-runtime'; runtime.mkdir()
        (runtime / 'model-router').mkdir()
        (self.project / '.codex/operator-web-service').mkdir()
        database = runtime / 'state.sqlite3'
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE inbox_events(status TEXT,last_error TEXT)')
            connection.execute("INSERT INTO inbox_events VALUES('retryable_failed','producer_unavailable_no_retry')")
        value = {'project': str(self.project), 'home': str(self.home)}
        ready = {'configuration_current': True, 'status': 'ready', 'active': False, 'session_bound': True}
        with patch.object(web, 'windows_process_entries', return_value=[]), \
                patch.object(responses_labels, 'assert_registry_edit_stopped'), \
                patch.object(web, 'status', return_value=ready):
            subject._lifecycle_observe(value)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute('SELECT * FROM inbox_events').fetchall(),
                [('retryable_failed', 'producer_unavailable_no_retry')])

    def test_lifecycle_pending_web_unknown_desktop_and_legacy_plan_block(self):
        import operator_web_service as web
        from operator_core import responses_labels
        runtime = self.project / '.codex/feishu-codex-operator-runtime'; runtime.mkdir()
        (runtime / 'model-router').mkdir()
        (self.project / '.codex/operator-web-service').mkdir()
        database = runtime / 'state.sqlite3'
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE inbox_events(status TEXT,last_error TEXT)')
        value = {'project': str(self.project), 'home': str(self.home)}
        with patch.object(web, 'windows_process_entries', return_value=[]), \
                patch.object(responses_labels, 'assert_registry_edit_stopped'), \
                patch.object(web, 'status', return_value={'configuration_current': True, 'status': 'ready',
                    'active': True, 'session_bound': True}):
            with self.assertRaisesRegex(subject.DirectEntryError, 'web_service_busy_or_uncertain'):
                subject._lifecycle_observe(value)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("INSERT INTO inbox_events VALUES('queued',NULL)")
            with self.assertRaisesRegex(subject.DirectEntryError, 'operator_requests_pending'):
                subject._lifecycle_observe(value)
        with patch.object(web, 'windows_process_entries', return_value=[{'name': 'ChatGPT.exe'}]):
            with self.assertRaisesRegex(subject.DirectEntryError, 'normal_desktop_exit_required'):
                subject._lifecycle_observe(value)
        (self.home / 'operator-unified-activation').mkdir()
        with self.assertRaisesRegex(subject.DirectEntryError, 'legacy_activation_requires_review'):
            subject._lifecycle_observe(value)

    @unittest.skipUnless(os.name == 'nt', 'real Windows replacement required')
    def test_new_cycle_requires_bound_recovery_receipt_and_preserves_later_cua(self):
        review = self.prepare(); self.activate(review)
        pointer, folder = self.active()
        custom = self.config.read_bytes()
        self.config.write_bytes(self.before)
        backup = self.home / 'operator-route-recovery/fixture'; backup.mkdir(parents=True)
        receipt = {'schema_version': 1, 'contract': 'operator_direct_entry_recovered_v1',
            'cycle': folder.name, 'intent_sha256': pointer['intent_sha256'],
            'config_before_recovery_sha256': subject.digest(custom),
            'config_after_recovery_sha256': subject.digest(self.before), 'recovery_backup': str(backup)}
        receipt_raw = subject.encoded(receipt); (folder / 'recovered.json').write_bytes(receipt_raw)
        rows = [{'name': 'config.toml', 'target': str(self.config), 'before_sha256': subject.digest(custom),
            'after_sha256': subject.digest(self.before)}, {'name': 'direct-entry-recovered.json',
            'target': str(folder / 'recovered.json'), 'after_sha256': subject.digest(receipt_raw)}]
        (backup / 'intent.json').write_bytes(subject.encoded({'files': rows}))
        (backup / 'completed.json').write_bytes(subject.encoded({'completed': [row['name'] for row in rows]}))
        self.config.write_bytes(self.before + b'\n[cua]\npipe="new-owner"\n')
        new_review = subject.preview(self.plan)
        self.assertEqual(subject.maintenance_status(self.home)['status'], 'maintenance_ready')
        result = self.activate(new_review)
        self.assertNotEqual(result['cycle'], folder.name)
        self.assertTrue((folder / 'recovered.json').is_file())
        self.assertIn(b'pipe="new-owner"', self.config.read_bytes())
        with self.assertRaisesRegex(subject.DirectEntryError, 'native_restore_required'):
            subject.maintenance_status(self.home)

    @unittest.skipUnless(os.name == 'nt', 'real independent Windows recovery required')
    def test_controller_cycle_recovers_with_real_independent_powershell_and_reopens_admission(self):
        self.helper = ROOT / 'scripts/restore-codex-official-route.ps1'
        review = self.prepare(); self.activate(review)
        pointer, folder = self.active()
        applied_before = (folder / 'applied.json').read_bytes()
        chosen = self.config.read_bytes().replace(b'model_reasoning_effort = "none"\n',
            b'model_reasoning_effort = "low"\n', 1) + b'\n[cua]\npipe="later-owner"\n'
        self.config.write_bytes(chosen)
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(self.helper), '-CodexHome', str(self.home), '-ProjectRoot', str(self.project),
            '-Apply', '-Json'], capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        response = native.decode(result.stdout)
        self.assertEqual(result.returncode, 0, response)
        self.assertEqual(response['status'], 'completed', response)
        self.assertEqual(self.config.read_bytes(), self.before + b'\n[cua]\npipe="later-owner"\n')
        self.assertEqual((folder / 'applied.json').read_bytes(), applied_before)
        self.assertEqual(subject.preview(self.plan)['status'], 'preview')
        self.assertEqual(native.decode((folder / 'recovered.json').read_bytes())['intent_sha256'],
            pointer['intent_sha256'])


class SelectorMutationTests(unittest.TestCase):
    def test_v2_accepts_only_same_model_and_explicit_effort_while_v1_stays_strict(self):
        before = b'model="native"\nmodel_reasoning_effort="high"\n'
        home = Path(tempfile.gettempdir()).resolve()
        candidate = projection.render(before, manifest(), home, selector_mutation=True)
        chosen = candidate.data.replace(b'model_reasoning_effort = "none"\n', b'model_reasoning_effort = "low"\n', 1)
        self.assertEqual(projection.restore(chosen, candidate.recovery), before)
        strict = projection.render(before, manifest(), home)
        with self.assertRaises(projection.DirectProfileError):
            projection.restore(chosen, strict.recovery)
        for current in (chosen.replace(b'"low"\n', b'"max"\n', 1),
                chosen.replace(b'fixture/exact-model', b'fixture/other-model', 1)):
            with self.assertRaises(projection.DirectProfileError):
                projection.restore(current, candidate.recovery)

    def test_v2_forged_effort_contract_or_extra_prefix_changes_fail(self):
        candidate = projection.render(b'model="native"\n', manifest(), Path(tempfile.gettempdir()).resolve(), selector_mutation=True)
        invalid = deepcopy(candidate.recovery); invalid['selector_mutation']['efforts'] = ['max']
        with self.assertRaises(projection.DirectProfileError):
            projection.restore(candidate.data, invalid)
        with self.assertRaises(projection.DirectProfileError):
            projection.restore(candidate.data.replace(b'web_search = "disabled"', b'web_search = "live"', 1), candidate.recovery)
