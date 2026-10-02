"""Independent PowerShell direct-cycle recovery in disposable homes only."""
from pathlib import Path
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(ROOT / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

from copy import deepcopy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest

import operator_direct_profile as projection

PS = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
SCRIPT = ROOT / 'scripts/restore-codex-official-route.ps1'


def raw(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True) + '\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


@unittest.skipUnless(os.name == 'nt' and PS.is_file(), 'Windows PowerShell 5.1 required')
class DirectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-direct-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'private home'; self.home.mkdir()
        self.project = self.root / 'project'; self.project.mkdir()
        self.config = self.home / 'config.toml'
        self.original = b'model = "native-fixture"\r\nmodel_reasoning_effort = "high"\r\n' \
            b'# owner bytes\r\n[features]\r\nplugins = false\r\n[mcp_servers.node_repl.env]\r\n' \
            b'SKY_CUA_NATIVE_PIPE_DIRECTORY = "original-pipe"\r\n'
        self.manifest = {'version': 1, 'contract': 'native_responses_v1', 'kind': 'local',
            'profile': 'operator-local-fixture', 'provider': {'name': 'Private fixture',
                'base_url': 'http://127.0.0.1:19432/v1', 'env_key': ''},
            'model': {'id': 'fixture/model', 'display_name': 'Fixture', 'context_window': 32768,
                'reasoning_efforts': ['low', 'high'], 'default_reasoning_effort': 'low',
                'input_modalities': ['text'], 'tool_mode': 'standard', 'supports_search_tool': False},
            'web_search': 'disabled'}
        self.active_root = self.home / 'operator-direct-entry'
        self.cycle = self.active_root / 'cycles' / ('a' * 32)
        self.cycle.mkdir(parents=True)
        self.helper_sha = sha(SCRIPT.read_bytes())
        self.sources = {name: 'b' * 64 for name in ('operator_direct_entry.py',
            'operator_direct_profile.py', 'operator_native_models.py',
            'operator_core/windows_config_transaction.py', 'operator_core/responses_labels.py')}
        self.env = {**os.environ, 'CODEX_HOME': str(self.home)}
        self.env.pop('OPENAI_BASE_URL', None)

    def save_cycle(self, *, original=None, variable=False):
        original = self.original if original is None else original
        value = projection.render(original, self.manifest, self.home)
        description = deepcopy(value.recovery)
        if variable:
            description.update(version=2, contract='direct_profile_projection_v2',
                selector_mutation={'contract': 'model_effort_v1', 'model': self.manifest['model']['id'],
                    'efforts': self.manifest['model']['reasoning_efforts']})
        manifest_bytes = raw(self.manifest)
        plan = {'schema_version': 1, 'contract': 'operator_direct_entry_plan_v1',
            'project': str(self.project), 'home': str(self.home), 'state': str(self.project / 'state'),
            'profile': self.manifest['profile'], 'model': self.manifest['model']['id'],
            'kind': self.manifest['kind'], 'display_name': self.manifest['model']['display_name'],
            'python': {'path': str(self.project / 'missing-python.exe'), 'sha256': 'b' * 64},
            'native_helper': {'path': str(self.project / 'retained-native-helper.ps1'), 'sha256': self.helper_sha},
            'entry_script': {'path': str(self.project / 'entry.ps1'), 'sha256': 'b' * 64},
            'source_sha256': self.sources, 'profile_binding': {name: 'b' * 64
                for name in ('manifest', 'plan', 'journal', 'profile', 'catalog')}, 'router_port': 4317}
        plan['profile_binding']['manifest'] = sha(manifest_bytes)
        files = {'config-before.bin': original, 'config-candidate.bin': value.data,
            'projection.json': raw(description), 'profile.json': manifest_bytes, 'plan.json': raw(plan)}
        for name, data in files.items():
            (self.cycle / name).write_bytes(data)
        self.intent = {'schema_version': 1, 'contract': 'operator_direct_entry_cycle_v1',
            'home': str(self.home), 'project': str(self.project), 'cycle': self.cycle.name,
            'plan_sha256': sha(files['plan.json']), 'native_helper_sha256': self.helper_sha,
            'source_sha256': self.sources, 'config_before_present': True,
            'before_identity': {'volume': 1, 'file_id': 'c' * 32},
            'files': {name: sha(data) for name, data in files.items()}}
        self.save_intent()
        self.config.write_bytes(value.data)
        return value

    def save_intent(self):
        data = raw(self.intent)
        (self.cycle / 'intent.json').write_bytes(data)
        (self.active_root / 'active.json').write_bytes(raw({'schema_version': 1,
            'contract': 'operator_direct_entry_active_v1', 'cycle': self.cycle.name,
            'intent_sha256': sha(data)}))

    def run_recovery(self, apply=False):
        command = [str(PS), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
            '-CodexHome', str(self.home), '-ProjectRoot', str(self.project), '-Json']
        if apply:
            command.append('-Apply')
        result = subprocess.run(command, capture_output=True, timeout=35, env=self.env)
        self.assertTrue(result.stdout.strip(), result.stderr.decode(errors='replace'))
        return result.returncode, json.loads(result.stdout.decode('utf-8-sig'))

    def assert_rejected_unchanged(self, expected=None):
        before = self.config.read_bytes()
        code, result = self.run_recovery(True)
        self.assertEqual(code, 1, result)
        self.assertEqual(result['status'], 'stopped')
        if expected:
            self.assertEqual(result['reason'], expected)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.home / 'operator-native-route-only').exists())
        self.assertFalse((self.home / 'operator-route-recovery').exists())
        self.assertFalse((self.cycle / 'recovered.json').exists())

    def save_chooser(self):
        bundle = self.project / '.codex/operator-desktop-entry'; bundle.mkdir(parents=True)
        script_bytes = b'retained entry fixture'; binary_bytes = b'retained launcher fixture'
        (bundle / 'operator_desktop_entry.ps1').write_bytes(script_bytes)
        (bundle / 'Codex拓展入口.exe').write_bytes(binary_bytes)
        (bundle / 'launcher-manifest.json').write_bytes(raw({'schema_version': 1,
            'native_fallback': 'native-only-v1', 'binary_sha256': sha(binary_bytes),
            'entry_script_sha256': sha(script_bytes)}))
        startup = self.project / '.codex/operator-direct-startup'; startup.mkdir()
        index = {'schema_version': 1, 'contract': 'direct_profile_picker_v1', 'project': str(self.project),
            'home': str(Path.home() / '.codex'), 'python': str(self.project / 'missing-python.exe'),
            'python_sha256': 'b' * 64, 'native_helper': str(self.project / 'missing-helper.ps1'),
            'native_helper_sha256': self.helper_sha, 'controller': str(self.project / 'missing-controller.py'),
            'controller_sha256': 'b' * 64, 'entry_script_sha256': sha(script_bytes),
            'profiles': [{'profile': self.manifest['profile'], 'display_name': 'Fixture',
                'plan': str(self.project / 'retained-plan.json'), 'plan_sha256': sha((self.cycle / 'plan.json').read_bytes())}]}
        index_path = startup / 'direct-entry-plan.json'; index_path.write_bytes(raw(index))
        config_path = bundle / 'desktop-entry.json'
        config_path.write_bytes(raw({'schema_version': 1, 'mode': 'direct_profile',
            'startup_bundle': '.codex/operator-direct-startup', 'entry_script_sha256': sha(script_bytes),
            'direct_entry_plan_sha256': sha(index_path.read_bytes())}))
        return config_path, index_path

    def test_independent_recovery_preserves_later_cua_owner_edits_and_original_uncertainty(self):
        value = self.save_cycle()
        later = value.data.replace(b'original-pipe', b'current-pipe').replace(b'plugins = false', b'plugins = true')
        later += b'\r\n[owner_later]\r\nsetting = "retained"\r\n'
        self.config.write_bytes(later)
        (self.cycle / 'failed.json').write_bytes(b'{"status":"uncertain"}\n')
        original_evidence = {name: (self.cycle / name).read_bytes() for name in self.intent['files']}
        code, preview = self.run_recovery()
        self.assertEqual((code, preview['status']), (0, 'preview'), preview)
        self.assertEqual(self.config.read_bytes(), later)
        self.assertFalse((self.cycle / 'recovered.json').exists())
        code, result = self.run_recovery(True)
        self.assertEqual((code, result['status']), (0, 'completed'), result)
        expected = self.original.replace(b'original-pipe', b'current-pipe').replace(b'plugins = false', b'plugins = true') \
            + b'\r\n[owner_later]\r\nsetting = "retained"\r\n'
        self.assertEqual(self.config.read_bytes(), expected)
        self.assertEqual((self.cycle / 'failed.json').read_bytes(), b'{"status":"uncertain"}\n')
        self.assertEqual(original_evidence, {name: (self.cycle / name).read_bytes() for name in self.intent['files']})
        receipt_raw = (self.cycle / 'recovered.json').read_bytes()
        receipt = json.loads(receipt_raw)
        backup = Path(result['backup'])
        self.assertEqual(receipt['recovery_backup'], str(backup))
        rows = json.loads((backup / 'intent.json').read_bytes())['files']
        saved = next(row for row in rows if row['target'] == str(self.cycle / 'recovered.json'))
        self.assertEqual(saved['after_sha256'], sha(receipt_raw))
        self.assertIn(saved['name'], json.loads((backup / 'completed.json').read_bytes())['completed'])
        epoch = json.loads((backup / 'completed.json').read_bytes())['native_epoch']
        self.assertEqual(set(epoch), {'contract', 'completed_utc', 'config_after_sha256',
            'native_helper_sha256', 'cycle', 'intent_sha256'})
        self.assertEqual(epoch['contract'], 'operator_direct_native_epoch_v1')
        self.assertEqual(epoch['native_helper_sha256'], self.helper_sha)
        self.assertEqual(epoch['cycle'], self.cycle.name)
        self.assertEqual(epoch['intent_sha256'], receipt['intent_sha256'])
        self.assertEqual(epoch['config_after_sha256'], sha(expected))
        self.assertRegex(epoch['completed_utc'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z$')
        self.assertEqual((backup / 'config.toml.after').read_bytes(), expected)
        self.assertEqual((backup / 'config.toml.before').read_bytes(), later)
        self.assertEqual(self.run_recovery(True)[1]['completed'], [])

    def test_bom_crlf_and_inert_leading_legacy_bytes_remain_exact(self):
        legacy = b'# BEGIN FEISHU OPERATOR MODEL ROUTER\r\n# openai_base_url = "http://127.0.0.1:4317/' \
            + b'd' * 64 + b'/v1"\r\n# END FEISHU OPERATOR MODEL ROUTER\r\n'
        before = projection.BOM + legacy + self.original
        self.save_cycle(original=before)
        code, result = self.run_recovery(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.config.read_bytes(), before)

    def test_owned_changes_duplicate_markers_and_extra_provider_assignments_stop(self):
        value = self.save_cycle()
        cases = (value.data.replace(b'fixture/model', b'changed/model', 1),
            value.data.replace(b'request_max_retries = 0', b'request_max_retries = 1'),
            value.data.replace(b'# OPERATOR DIRECT SAVED SELECTOR model = "native-fixture"',
                b'# OPERATOR DIRECT SAVED SELECTOR model = "changed-native"'),
            value.data + b'# BEGIN OPERATOR DIRECT DESKTOP\n',
            value.data + b'api_key = "never-owned"\n',
            value.data + b'\n[model_providers.operator_native_local_fixture]\nname="later"\n',
            value.data.replace(b'model_reasoning_effort = "low"\n', b'model_reasoning_effort = "high"\n', 1))
        for current in cases:
            with self.subTest(sha=sha(current)):
                self.config.write_bytes(current)
                self.assert_rejected_unchanged('direct_owned_changed')

    def test_v2_allows_only_finite_effort_variation_and_same_model(self):
        value = self.save_cycle(variable=True)
        allowed = value.data.replace(b'model_reasoning_effort = "low"\n', b'model_reasoning_effort = "high"\n', 1)
        self.config.write_bytes(allowed)
        code, result = self.run_recovery(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_v2_rejects_unlisted_effort_without_writes(self):
        value = self.save_cycle(variable=True)
        self.config.write_bytes(value.data.replace(b'model_reasoning_effort = "low"\n', b'model_reasoning_effort = "max"\n', 1))
        self.assert_rejected_unchanged('direct_owned_changed')

    def test_changed_retained_snapshot_helper_binding_and_unknown_fields_stop(self):
        self.save_cycle()
        (self.cycle / 'config-before.bin').write_bytes(self.original + b'# altered\n')
        self.assert_rejected_unchanged('direct_record_invalid')
        (self.cycle / 'config-before.bin').write_bytes(self.original)
        self.intent['native_helper_sha256'] = 'e' * 64; self.save_intent()
        self.assert_rejected_unchanged('direct_record_invalid')
        self.intent['native_helper_sha256'] = self.helper_sha
        self.intent['unrecognized'] = True; self.save_intent()
        self.assert_rejected_unchanged('direct_record_invalid')

    def test_complete_pending_cycle_preview_on_native_original_has_zero_writes(self):
        self.save_cycle()
        self.config.write_bytes(self.original)
        before = {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()}
        code, result = self.run_recovery()
        self.assertEqual((code, result['status'], result['route_before']), (0, 'preview', 'native'), result)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()})

    def test_missing_original_and_linked_projection_reject_before_backup(self):
        self.save_cycle()
        original_path = self.cycle / 'config-before.bin'
        original_path.unlink()
        self.assert_rejected_unchanged('direct_record_invalid')
        original_path.write_bytes(self.original)
        projection_path = self.cycle / 'projection.json'
        retained = self.root / 'retained-projection.json'; retained.write_bytes(projection_path.read_bytes())
        projection_path.unlink(); os.link(retained, projection_path)
        self.assert_rejected_unchanged('linked_path')

    def test_validated_chooser_stays_selected_when_runtime_and_python_are_unavailable(self):
        self.save_cycle()
        entry, _ = self.save_chooser()
        before = entry.read_bytes()
        code, result = self.run_recovery(True)
        self.assertEqual((code, result['status']), (0, 'completed'), result)
        self.assertEqual(result['entry_before'], 'direct_profile')
        self.assertEqual(entry.read_bytes(), before)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertNotIn('desktop-entry.json', result['completed'])

    def test_changed_optional_chooser_does_not_trap_known_direct_configuration(self):
        self.save_cycle()
        entry, index = self.save_chooser()
        before = entry.read_bytes()
        index.write_bytes(index.read_bytes() + b'\n')
        code, result = self.run_recovery(True)
        self.assertEqual((code, result['status']), (1, 'needs_review'), result)
        self.assertTrue(result['config_changed'])
        self.assertIn('entry_requires_review', result['warnings'])
        self.assertEqual(entry.read_bytes(), before)
        self.assertEqual(self.config.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
