"""Stopped backend changes preserve histories, native settings and Web secrets."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

from test_mode_entry import ModeEntryTests, mode
import operator_mode_backends as backends
import operator_mode_maintenance as maintenance
import operator_web_service as service
import operator_web_model as web_model

CAPS = {'protocol':'responses-tools-v1', 'function_tools':True,
    'custom_tools':{'exec':'wrap'}, 'tool_choice':['auto','none'], 'named_tool_choice':'reject',
    'parallel_tool_calls':False, 'tool_search':False, 'input_modalities':['text'],
    'structured_tool_outputs':False, 'developer_role':'native', 'reasoning_input':True,
    'reasoning_summary':True, 'previous_response_id':False, 'text_verbosity':False,
    'codex_tool_mode':'code_mode_only'}


class ModeBackendTests(ModeEntryTests):
    def setUp(self):
        super().setUp()
        self.registration = mode.decode(mode.read(self.registry))
        self.registration['version'] = 2
        self.registration['models'][0]['responses'] = deepcopy(CAPS)
        self.registry.write_bytes(mode.json_bytes(self.registration))

    def installed(self):
        self.prepare()
        bundle = self.project / '.codex/operator-desktop-entry'
        bundle.mkdir()
        mode.write_new(bundle / 'desktop-entry.json', {'mode':'isolated_mode',
            'startup_bundle':self.root.relative_to(self.project).as_posix()})

    def candidate(self):
        value = deepcopy(self.registration)
        value['models'][0]['responses'].update(codex_tool_mode='standard', upstream_response_mode='json')
        value['models'][0]['context_window'] = 16000
        path = self.project / '.codex/reviewed-registration.json'
        mode.write_new(path, value)
        return path, value

    def test_one_shot_contract_update_publishes_catalog_and_preserves_history_and_native(self):
        self.installed()
        candidate, value = self.candidate()
        history = self.root / 'home/retained-history.jsonl'
        mode.write_new(history, b'complete original failed and successful turns\n')
        old_registry = mode.read(self.root / 'router/registry.json')
        old_catalog = mode.read(self.root / 'home/models.json')
        protected = mode.read(self.root / 'home/config.toml')
        def publish(root, stage, action, sha=None):
            if action == 'preview':
                return {'preview_sha256':'1'*64}
            for name in mode.decode(mode.read(stage / 'prepared.json'))['files']:
                (root / name).write_bytes(mode.read(stage / 'staged' / name))
            return {'phase':'pair_refreshed', 'generation':stage.name}
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(maintenance, 'pair_powershell', side_effect=publish):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler,
                                                      registry_path=candidate)['stage'])
            self.assertEqual(mode.read(stage / 'originals/router/registry.json'), old_registry)
            self.assertEqual(mode.read(stage / 'originals/home/models.json'), old_catalog)
            self.assertEqual(mode.read(self.root / 'router/registry.json'), old_registry)
            maintenance.pair_apply(self.root, stage, '1'*64)
            self.assertEqual(mode.decode(mode.read(self.root / 'router/registry.json')), value)
            catalog = mode.decode(mode.read(self.root / 'home/models.json'))['models'][0]
            self.assertIsNone(catalog['tool_mode'])
            self.assertEqual(catalog['context_window'], 16000)
            with self.assertRaisesRegex(mode.ModeEntryError, 'stage_not_fresh'):
                maintenance.pair_apply(self.root, stage, '1'*64)
        self.assertEqual(mode.read(history), b'complete original failed and successful turns\n')
        self.assertEqual(mode.read(self.root / 'home/config.toml'), protected)
        self.assertEqual({p.name:p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_endpoint_changes_and_capacity_increases_are_rejected_before_staging(self):
        self.installed()
        path, value = self.candidate()
        with patch.object(mode, 'inspect_package', return_value=self.package):
            for field, replacement in [('api_base','http://127.0.0.1:3/v1'), ('context_window',64000)]:
                changed = deepcopy(value)
                changed['models'][0][field] = replacement
                path.write_bytes(mode.json_bytes(changed))
                with self.assertRaisesRegex(mode.ModeEntryError, 'registration_identity_changed'):
                    maintenance.pair_prepare(self.root, compiler=self.compiler, registry_path=path)
        self.assertFalse((self.root / 'pair-refreshes').exists())
        self.assertEqual(mode.decode(mode.read(self.root / 'router/registry.json')), self.registration)

    def test_changed_candidate_after_prepare_cannot_publish_or_replace_originals(self):
        self.installed()
        path, value = self.candidate()
        with patch.object(mode, 'inspect_package', return_value=self.package):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler,
                                                      registry_path=path)['stage'])
            before = {name:mode.read(self.root / name) for name in
                      mode.decode(mode.read(stage / 'prepared.json'))['files']}
            value['models'][0]['context_window'] = 12000
            path.write_bytes(mode.json_bytes(value))
            with self.assertRaisesRegex(mode.ModeEntryError, 'baseline_changed'):
                maintenance.pair_apply(self.root, stage, '1'*64)
        self.assertEqual({name:mode.read(self.root / name) for name in before}, before)
        self.assertFalse((stage / 'apply-intent.json').exists())

    def test_web_binding_is_exact_and_private_key_never_enters_staged_files(self):
        from operator_core.model_registry import WebServiceBinding
        self.installed()
        profile = self.project / '.codex/web-service'
        profile.mkdir()
        mode.write_new(profile / 'profile.json', {'synthetic':'profile'})
        settings = profile / 'settings.json'
        mode.write_new(settings, {'native_cancellation_mode':'app_server_metadata_v1',
                                 'native_cancellation_home':str(self.root / 'home')})
        expected = {'profile_sha256':mode.file_hash(profile / 'profile.json'), 'session_sha256':'2'*64}
        binding = WebServiceBinding(**expected, token='fixture-secret-only-in-memory')
        routes = tuple(replace(row, web_binding=binding) for row in web_model.text_routes(tools=True))
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(service, 'load_profile', return_value=(profile, {'settings':{'path':str(settings)}})), \
                patch.object(service, 'route_preview', return_value=expected), \
                patch.object(service, 'resolve_routes', return_value=routes):
            stage = mode.Path(maintenance.pair_prepare(self.root, compiler=self.compiler,
                                                      web_profile=profile)['stage'])
            maintenance.pair_stage(self.root, stage)
            descriptor = mode.decode(mode.read(stage / 'staged/entry.json'))
            self.assertEqual(descriptor['web'], {'profile':str(profile), **expected,
                                               'models':[r.slug for r in routes]})
            catalog = mode.decode(mode.read(stage / 'staged/home/models.json'))
            self.assertEqual([r['slug'] for r in catalog['models']], ['local/fixture', *[r.slug for r in routes]])
            for path in stage.rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'fixture-secret-only-in-memory', path.read_bytes())
            changed = {**expected, 'session_sha256':'3'*64}
            with patch.object(service, 'route_preview', return_value=changed):
                with self.assertRaisesRegex(mode.ModeEntryError, 'baseline_changed'):
                    maintenance.pair_stage(self.root, stage)
        self.assertEqual({p.name:p.read_bytes() for p in self.native.iterdir()}, self.originals)

    def test_wrong_native_home_for_web_cancellation_is_rejected_before_staging(self):
        self.installed()
        profile = self.project / '.codex/web-service'
        profile.mkdir()
        settings = profile / 'settings.json'
        mode.write_new(settings, {'native_cancellation_mode':'app_server_metadata_v1',
                                 'native_cancellation_home':str(self.native)})
        with patch.object(mode, 'inspect_package', return_value=self.package), \
                patch.object(service, 'load_profile', return_value=(profile, {'settings':{'path':str(settings)}})):
            with self.assertRaisesRegex(mode.ModeEntryError, 'cancellation_home_mismatch'):
                maintenance.pair_prepare(self.root, compiler=self.compiler, web_profile=profile)
        self.assertFalse((self.root / 'pair-refreshes').exists())


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames([name for name in ModeBackendTests.__dict__ if name.startswith('test_')],
                                    ModeBackendTests)
