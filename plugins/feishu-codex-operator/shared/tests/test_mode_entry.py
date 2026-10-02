"""Isolated entry preparation uses new files and preserves native state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'scripts'))
import operator_mode_entry as mode
import operator_mode_onboarding as onboarding


class ModeEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / 'project'
        (self.project / '.codex').mkdir(parents=True)
        self.native = self.base / 'native'
        self.native.mkdir()
        (self.native / 'config.toml').write_bytes(b'# native original\nmodel="native-fixture"\n')
        (self.native / 'auth.json').write_bytes(b'private-fixture-do-not-copy')
        (self.native / 'history.jsonl').write_bytes(b'original-history-do-not-copy')
        self.root = self.project / '.codex/operator-mode-entry' / ('a' * 32)
        self.registry = self.base / 'registry.json'
        self.registry.write_text(json.dumps({'version': 1, 'models': [{
            'slug': 'local/fixture', 'display_name': 'Fixture', 'model': 'fixture',
            'api_base': 'http://127.0.0.1:1/v1', 'api_key_env': '',
            'context_window': 32000, 'reasoning_efforts': ['low']}]}), encoding='utf-8')
        self.package = {'full_name': 'OpenAI.Codex_fixture', 'family': 'fixture',
                        'version': 'fixture', 'executable': 'fixture', 'executable_sha256': 'a' * 64}
        self.originals = {p.name: p.read_bytes() for p in self.native.iterdir()}

    def compiler(self, root):
        result = {}
        for name in ('operator-mode-host.exe', 'operator-mode-picker.exe', 'operator-mode-native.exe'):
            (root / name).write_bytes(b'isolated-compiler-fixture')
            result[name] = mode.file_hash(root / name)
        return result

    def prepare(self, compiler=None):
        runtime = {'path': str(Path(sys.executable).resolve()),
                   'sha256': mode.file_hash(Path(sys.executable).resolve())}
        with patch.object(mode, 'inspect_runtime', return_value=runtime):
            return mode.prepare(self.project, self.root, self.registry, 51417, 'local/fixture',
                                package=self.package, native=self.native, compiler=compiler or self.compiler)

    def test_new_home_contains_no_native_login_history_or_settings(self):
        result = self.prepare()
        self.assertEqual(result['phase'], 'prepared')
        self.assertFalse(result['native_enabled'])
        self.assertEqual({p.name for p in (self.root / 'home').iterdir()}, {'config.toml', 'models.json'})
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)
        self.assertEqual(mode.load(self.root)['native_home'], str(self.native))
        catalog = json.loads((self.root / 'home/models.json').read_text('utf-8'))
        self.assertEqual([r['slug'] for r in catalog['models']], ['local/fixture'])

    def test_search_refresh_preserves_settings_history_and_native_credentials(self):
        self.prepare()
        path = self.root / 'home/config.toml'
        with path.open('ab') as stream:
            stream.write(b'\n[notice]\nhide_model_warning = true\n')
        before = path.read_bytes()
        history = self.root / 'home/history.jsonl'
        history.write_bytes(b'failed turn retained\n')
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode.native_search, 'load_headers', return_value={'Authorization': 'synthetic'}):
            preview = mode.refresh_preview(self.root, enable_native_search=True)
            self.assertEqual(path.read_bytes(), before)
            mode.refresh(self.root, preview['preview_sha256'], compiler=self.compiler, enable_native_search=True)
        self.assertEqual(mode.load(self.root)['search_policy'], mode.native_search.CONTRACT)
        self.assertEqual(history.read_bytes(), b'failed turn retained\n')
        self.assertIn(b'hide_model_warning = true', path.read_bytes())
        self.assertIn(b'web_search = "live"', path.read_bytes())
        attempt = next((self.root / 'refreshes').iterdir())
        self.assertEqual((attempt / 'originals/home/config.toml').read_bytes(), before)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)
        self.assertFalse((self.root / 'home/auth.json').exists())

    def test_installed_pair_blocks_independent_refresh_before_writes(self):
        self.prepare()
        directory = self.project / '.codex/operator-desktop-entry'
        directory.mkdir()
        (directory / 'desktop-entry.json').write_text(json.dumps({'mode': 'isolated_mode',
            'startup_bundle': self.root.relative_to(self.project).as_posix()}), encoding='utf-8')
        with self.assertRaisesRegex(mode.ModeEntryError, 'installed_pair_requires_bound_upgrade'):
            mode.refresh_preview(self.root)
        self.assertFalse((self.root / 'refreshes').exists())

    def test_uninstall_checks_each_isolated_process_and_uncertain_preparation(self):
        import operator_uninstall
        self.prepare()
        with patch.object(operator_uninstall, 'assert_port_free') as port:
            operator_uninstall.inspect_mode_entries(self.project)
            port.assert_called_once_with(51417)
        with patch.object(mode, 'active_desktop', return_value=('attempt', {})):
            with self.assertRaisesRegex(ValueError, 'isolated_mode_requires_stopped_review'):
                operator_uninstall.inspect_mode_entries(self.project)
        other = self.root.parent / ('c' * 32)
        other.mkdir()
        (other / 'preparing.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'isolated_mode_requires_stopped_review'):
            operator_uninstall.inspect_mode_entries(self.project)

    def test_later_unrelated_extension_settings_are_preserved_but_route_changes_stop_launch(self):
        self.prepare()
        path = self.root / 'home/config.toml'
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n[notice]\nhide_model_warning = true\n')
        self.assertEqual(mode.load(self.root)['contract'], mode.CONTRACT)
        path.write_text(path.read_text('utf-8').replace('stream_max_retries = 0', 'stream_max_retries = 1'),
                        encoding='utf-8')
        with self.assertRaisesRegex(mode.ModeEntryError, 'route_settings_changed'):
            mode.load(self.root)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_failed_preparation_is_retained_and_cannot_be_reused(self):
        def broken(root):
            raise ValueError('synthetic compiler failure')
        with self.assertRaisesRegex(ValueError, 'synthetic compiler failure'):
            self.prepare(compiler=broken)
        self.assertTrue((self.root / 'preparation-failed.json').is_file())
        with self.assertRaisesRegex(mode.ModeEntryError, 'existing_preparation_retained'):
            self.prepare()

    def test_native_and_linked_destinations_are_rejected_before_writes(self):
        with self.assertRaises(mode.ModeEntryError):
            mode.validate_scope(self.project, self.native, self.native)
        other = self.base / 'elsewhere'
        other.mkdir()
        self.root.parent.mkdir()
        try:
            self.root.symlink_to(other, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(list(other.iterdir()), [])

    def test_unknown_or_failed_attempt_blocks_another_launch_before_service_start(self):
        self.prepare()
        attempt = self.root / 'launches' / ('b' * 32)
        attempt.mkdir()
        (attempt / 'intent.json').write_text('{}', encoding='utf-8')
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'start_router') as start:
            with self.assertRaisesRegex(mode.ModeEntryError, 'previous_launch_running_or_uncertain'):
                mode.launch(self.root)
            start.assert_not_called()
        self.assertEqual(len(list((self.root / 'launches').iterdir())), 1)

    def test_known_welcome_seed_has_only_the_local_completion_preference(self):
        contract = {'contract': onboarding.CONTRACT, 'supported': True,
                    'asset': onboarding.ASSET, 'asset_sha256': onboarding.REVIEWED_SHA256,
                    'preferences': {onboarding.PREFERENCE: True}}
        with patch.object(mode, 'inspect_contract', return_value=contract):
            self.prepare()
        saved = json.loads((self.root / 'home/.codex-global-state.json').read_text('utf-8'))
        self.assertEqual(saved, {'electron-persisted-atom-state': {onboarding.PREFERENCE: True}})
        self.assertEqual(mode.load(self.root)['onboarding'], contract)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)
        self.assertFalse((self.root / 'home/auth.json').exists())

    def test_unknown_onboarding_version_keeps_the_official_flow(self):
        with patch.object(onboarding, 'asset_bytes') as reader:
            contract = onboarding.inspect_contract(self.package)
        reader.assert_not_called()
        self.assertIsNone(onboarding.initial_state(contract))
        changed = dict(self.package, version=onboarding.REVIEWED_VERSION)
        with patch.object(onboarding, 'asset_bytes', return_value=b'changed official source'):
            self.assertFalse(onboarding.inspect_contract(changed)['supported'])

    def started_attempt(self):
        attempt = self.root / 'launches' / ('b' * 32)
        attempt.mkdir()
        process = {'pid': 99, 'birth': '123', 'executable': 'fixture'}
        mode.write_new(attempt / 'desktop-started.json', {'pid': 99, 'process': process})
        mode.write_new(attempt / 'windows-bound.json', {'pid': 99, 'native_config_unchanged': True})
        mode.write_new(attempt / 'dispatched.json', {'accepted': True})
        return attempt, process

    def test_repeated_launch_reuses_the_exact_live_desktop(self):
        self.prepare()
        attempt, process = self.started_attempt()
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=True), \
                patch.object(mode, 'start_router') as service, \
                patch.object(mode, 'activate_desktop', return_value={'phase': 'opened_existing'}) as activate:
            result = mode.launch(self.root)
        self.assertEqual(result['phase'], 'opened_existing')
        service.assert_called_once()
        self.assertEqual(activate.call_args.args[2][0], attempt)
        self.assertEqual(len(list((self.root / 'launches').iterdir())), 1)

    def test_dead_or_reused_desktop_pid_never_starts_or_activates(self):
        self.prepare()
        self.started_attempt()
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(mode, 'process_matches', return_value=False), \
                patch.object(mode, 'start_router') as service, \
                patch.object(mode, 'activate_desktop') as activate:
            with self.assertRaisesRegex(mode.ModeEntryError, 'previous_launch_running_or_uncertain'):
                mode.launch(self.root)
        service.assert_not_called()
        activate.assert_not_called()

    def test_concurrent_launch_is_rejected_without_service_or_desktop_action(self):
        self.prepare()
        with mode.lock(self.root), patch.object(mode, 'start_router') as service:
            with self.assertRaisesRegex(mode.NativeModelsError, 'operation_in_progress'):
                mode.launch(self.root)
        service.assert_not_called()
        self.assertEqual(list((self.root / 'launches').iterdir()), [])

    def test_live_desktop_blocks_service_stop(self):
        self.prepare()
        self.started_attempt()
        with patch.object(mode, 'process_matches', return_value=True):
            with self.assertRaisesRegex(mode.ModeEntryError, 'close_extension_before_service_stop'):
                mode.stop_router(self.root)
        self.assertEqual(list((self.root / 'router-launches').iterdir()), [])

    def test_missing_router_runtime_stops_before_allocating_a_home_or_launch_intent(self):
        with patch.object(mode, 'inspect_runtime', side_effect=mode.ModeEntryError('mode_router_runtime_dependencies_missing')):
            with self.assertRaisesRegex(mode.ModeEntryError, 'router_runtime_dependencies_missing'):
                mode.prepare(self.project, self.root, self.registry, 51417, 'local/fixture',
                             package=self.package, native=self.native, compiler=self.compiler)
        self.assertFalse(self.root.exists())
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_stopped_refresh_preserves_home_and_retains_original_launch_files(self):
        self.prepare()
        (self.root / 'home/history.jsonl').write_bytes(b'own extension history\n')
        originals = {p.name: p.read_bytes() for p in (self.root / 'home').iterdir()}
        old = (self.root / 'entry.json').read_bytes()
        with patch.object(mode, 'inspect_package', return_value=self.package):
            preview = mode.refresh_preview(self.root)
            result = mode.refresh(self.root, preview['preview_sha256'], compiler=self.compiler)
        self.assertEqual(result['phase'], 'refreshed')
        self.assertEqual((self.root / 'refreshes' / result['refresh'] / 'originals/entry.json').read_bytes(), old)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / 'home').iterdir()}, originals)
        self.assertEqual({p.name: p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_refresh_rejects_live_desktop_before_build_or_writes(self):
        self.prepare()
        self.started_attempt()
        with patch.object(mode, 'process_matches', return_value=True):
            with self.assertRaisesRegex(mode.ModeEntryError, 'close_extension_before_refresh'):
                mode.refresh_preview(self.root)
        self.assertFalse((self.root / 'refreshes').exists())

    def test_changed_source_after_preview_stops_before_allocating_refresh(self):
        self.prepare()
        with patch.object(mode, 'inspect_package', return_value=self.package):
            preview = mode.refresh_preview(self.root)
            with patch.object(mode, 'source_bindings', return_value={'changed.py': 'b' * 64}):
                with self.assertRaisesRegex(mode.ModeEntryError, 'refresh_preview_changed'):
                    mode.refresh(self.root, preview['preview_sha256'], compiler=self.compiler)
        self.assertFalse((self.root / 'refreshes').exists())

    def test_failed_refresh_keeps_originals_and_never_retries(self):
        self.prepare()
        def broken(stage):
            raise ValueError('synthetic compile failure')
        with patch.object(mode, 'inspect_package', return_value=self.package):
            preview = mode.refresh_preview(self.root)
            with self.assertRaisesRegex(ValueError, 'synthetic compile failure'):
                mode.refresh(self.root, preview['preview_sha256'], compiler=broken)
            with self.assertRaisesRegex(mode.ModeEntryError, 'previous_refresh_uncertain_no_retry'):
                mode.refresh_preview(self.root)
        attempts = list((self.root / 'refreshes').iterdir())
        self.assertEqual(len(attempts), 1)
        self.assertTrue((attempts[0] / 'originals/entry.json').is_file())
        self.assertTrue((attempts[0] / 'failed.json').is_file())

    def test_native_edit_during_refresh_is_preserved_without_replacing_launch_files(self):
        self.prepare()
        old = (self.root / 'entry.json').read_bytes()
        def concurrent(stage):
            (self.native / 'config.toml').write_bytes(b'# owner changed native settings\n')
            return self.compiler(stage)
        with patch.object(mode, 'inspect_package', return_value=self.package):
            preview = mode.refresh_preview(self.root)
            with self.assertRaisesRegex(mode.ModeEntryError, 'protected_file_changed_during_refresh'):
                mode.refresh(self.root, preview['preview_sha256'], compiler=concurrent)
        self.assertEqual((self.root / 'entry.json').read_bytes(), old)
        self.assertEqual((self.native / 'config.toml').read_bytes(), b'# owner changed native settings\n')

    def test_unconfirmed_service_stop_blocks_refresh(self):
        self.prepare()
        attempt = self.root / 'router-launches' / ('c' * 32)
        attempt.mkdir()
        mode.write_new(attempt / 'intent.json', {'started_utc': mode.utc()})
        mode.write_new(attempt / 'running.json', {'process': {'pid': 12}})
        with patch.object(mode, 'inspect_package', return_value=self.package):
            with self.assertRaisesRegex(mode.ModeEntryError, 'stop_router_before_refresh'):
                mode.refresh_preview(self.root)
        self.assertFalse((self.root / 'refreshes').exists())
