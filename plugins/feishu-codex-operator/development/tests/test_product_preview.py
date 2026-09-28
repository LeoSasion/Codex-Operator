# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = _OPERATOR_PLUGIN_ROOT


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


product = module('operator_product')
release = module('build_codex_operator_release')


class ProductOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir()

    def test_fresh_project_is_readonly_without_services(self):
        def forbidden(*a): raise AssertionError('No service needed')
        before = list(self.root.rglob('*'))
        value = product.project_overview(self.root, self.home, forbidden)
        self.assertEqual(value['schema_version'], 2)
        self.assertEqual(set(value['components']), {'channels', 'models'})
        self.assertEqual(set(value['components']['models']['providers']), {'api', 'local', 'web'})
        self.assertEqual(value['components']['channels']['implemented'], ['feishu'])
        self.assertEqual(list(self.root.rglob('*')), before)

    def configured(self):
        for relative in ['.codex/feishu-codex-operator-runtime/runtime-manifest.json',
                '.codex/operator-installation/ownership.json', '.codex/operator-web-service/profile.json']:
            p = self.root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{}')

    def test_stopped_legacy_runtime_without_ownership_requires_review(self):
        self.configured()
        (self.root / '.codex/operator-installation/ownership.json').unlink()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        gates = dict.fromkeys(product.READINESS_GATES, False)
        value = product.project_overview(self.root, self.home,
            lambda *args: {'status': 'not_ready', 'ready': False, 'gates': gates})
        channel = value['components']['channels']
        self.assertEqual(channel['state'], 'needs_review')
        self.assertIn('旧通道安装缺少归属记录', channel['summary'])
        self.assertNotIn('install', channel['next_action'])
        self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_ready_only_projects_fixed_status_not_private_output(self):
        self.configured()
        def inspect(p, scope, action):
            if scope == 'operator': return {'status': 'ready', 'ready': True, 'gates': {
                'runtime_running': True, 'runtime_manifest': True, 'health_current': True, 'feishu_consumer': True,
                'access_configured': True, 'minimal_beeper_relay': True, 'init_catalog': True, 'final_callback': True},
                'secret': 'PRIVATE'}
            if action == 'status': return {'status': 'ready', 'active': False, 'configuration_current': True}
            return {'status': 'connected', 'summary': 'PRIVATE'}
        value = product.project_overview(self.root, self.home, inspect)
        self.assertEqual(value['components']['models']['providers']['web']['state'], 'ready')
        self.assertEqual(value['components']['models']['state'], 'configured')
        self.assertEqual(value['components']['models']['registry_state'], 'not_configured')
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_ready_web_service_with_stale_desktop_route_requests_rebind(self):
        self.configured()
        def inspect(p, scope, action):
            if action == 'status':
                return {'status': 'ready', 'active': False, 'configuration_current': True}
            return {'status': 'stale', 'reason': 'service_generation_changed'}
        value = product.project_overview(self.root, self.home, inspect)
        web = value['components']['models']['providers']['web']
        self.assertEqual(web['state'], 'needs_review')
        self.assertEqual(web['next_action'], 'models web desktop-rebind')

    def test_changed_and_active_states_do_not_suggest_restart(self):
        self.configured()
        for state, expected in [({'status': 'ready', 'active': False, 'configuration_current': False}, 'changed'),
                ({'status': 'ready', 'active': True}, 'busy'),
                ({'status': 'stopped', 'start_available': False}, 'needs_review')]:
            value = product.project_overview(self.root, self.home,
                lambda *a: {'configuration_current': True, **state})
            self.assertEqual(value['components']['models']['providers']['web']['state'], expected)
            self.assertNotEqual(value['components']['models']['providers']['web']['next_action'], 'models web start')

    def test_assistance_and_transitions_are_not_reported_as_ready_or_broken(self):
        self.configured()
        for state, expected in [({'status': 'ready', 'active': False, 'needs_assistance': True}, 'needs_review'),
                ({'status': 'assistance', 'active': False, 'needs_assistance': False}, 'assistance_open'),
                ({'status': 'assistance', 'active': True, 'needs_assistance': True}, 'busy'),
                ({'status': 'starting'}, 'starting'), ({'status': 'preparing', 'active': False}, 'preparing'),
                ({'status': 'connection', 'active': False}, 'connecting'),
                ({'status': 'reconnecting', 'active': False}, 'connecting'),
                ({'status': 'draining', 'active': True}, 'stopping')]:
            with self.subTest(state=state):
                calls = []
                def inspect(p, scope, action):
                    calls.append((scope, action))
                    return {**state, 'configuration_current': True}
                value = product.project_overview(self.root, self.home, inspect)
                web = value['components']['models']['providers']['web']
                self.assertEqual(web['state'], expected)
                self.assertNotIn(('web', 'desktop-status'), calls)
                self.assertNotIn('start', web['next_action'])

    def test_manifest_review_requires_every_other_channel_gate(self):
        self.configured()
        for failed_gate in [None, *sorted(product.READINESS_GATES - {'runtime_manifest'})]:
            with self.subTest(failed_gate=failed_gate):
                gates = dict.fromkeys(product.READINESS_GATES, True)
                gates['runtime_manifest'] = False
                if failed_gate:
                    gates[failed_gate] = False
                calls = []
                def inspect(p, scope, action):
                    calls.append((scope, action))
                    return {'status': 'not_ready', 'ready': False, 'gates': gates, 'detail': 'PRIVATE'}
                before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                value = product.project_overview(self.root, self.home, inspect)
                channel = value['components']['channels']
                self.assertEqual(channel['state'], 'needs_setup' if failed_gate else 'needs_review')
                self.assertNotEqual(channel['state'], 'ready')
                self.assertEqual(calls.count(('operator', 'readiness')), 1)
                self.assertNotIn('PRIVATE', json.dumps(value))
                self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_assistance_flag_requires_page_review_without_opening_or_probing(self):
        self.configured()
        for state in ('ready', 'assistance', 'connection'):
            with self.subTest(state=state):
                calls = []
                def inspect(p, scope, action):
                    calls.append((scope, action))
                    return {'status': state, 'active': False, 'configuration_current': True,
                        'needs_assistance': True, 'detail': 'PRIVATE challenge'}
                value = product.project_overview(self.root, self.home, inspect)
                web = value['components']['models']['providers']['web']
                self.assertEqual(web['state'], 'needs_review')
                self.assertNotIn(web['next_action'], ('web assist', 'models web assist'))
                self.assertEqual(calls, [('operator', 'readiness'), ('web', 'status')])
                self.assertEqual(value['model_requests'], 0)
                self.assertNotIn('PRIVATE', json.dumps(value))

    def test_failed_observation_does_not_ask_to_configure_again(self):
        self.configured()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for observed in [{'status': 'unavailable', 'summary': 'PRIVATE'}, None, {},
                {'ready': True, 'gates': {'invented': True}, 'status': 'ready'}]:
            value = product.project_overview(self.root, self.home, lambda *a: observed)
            self.assertEqual(value['components']['channels']['state'], 'unavailable')
            self.assertNotEqual(value['components']['models']['providers']['web']['state'], 'ready')
            self.assertEqual(value['status'], 'partial')
            self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_permission_failure_is_not_missing_configuration(self):
        self.configured()
        original = Path.lstat
        profile = self.root / '.codex/operator-web-service/profile.json'
        def denied(path, *a, **kw):
            if path == profile:
                raise PermissionError('PRIVATE')
            return original(path, *a, **kw)
        with patch.object(Path, 'lstat', denied):
            value = product.project_overview(self.root, self.home, lambda *a: {'status': 'unavailable'})
        web = value['components']['models']['providers']['web']
        self.assertEqual(web['state'], 'unavailable')
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_fixed_entry_failures_survive_overview_without_private_details(self):
        self.configured()
        for reason, expected in [('web_entry_access_denied', 'unavailable'),
                ('web_entry_runtime_mismatch', 'needs_review'),
                ('web_entry_python_changed', 'needs_review'),
                ('web_entry_profile_invalid', 'needs_review')]:
            with self.subTest(reason=reason):
                value = product.project_overview(self.root, self.home, lambda *args: {
                    'status': 'unavailable', 'code': 'web_entry_unavailable', 'reason': reason,
                    'stage': 'profile', 'profile_state': 'present', 'summary': 'PRIVATE', 'path': 'PRIVATE'})
                web = value['components']['models']['providers']['web']
                self.assertEqual(web['state'], expected)
                self.assertEqual(web['diagnostic']['reason'], reason)
                self.assertNotIn(web['next_action'], ('models web start', 'models web assist', 'models web configure'))
                self.assertNotIn('PRIVATE', json.dumps(value))

    def test_nonzero_child_diagnostic_is_preserved_but_cannot_claim_ready(self):
        import subprocess
        safe = {'status': 'unavailable', 'code': 'web_entry_unavailable',
            'reason': 'web_entry_access_denied', 'stage': 'profile', 'profile_state': 'present'}
        for payload, expected in [({**safe, 'summary': 'PRIVATE'}, safe),
                ({**safe, 'reason': 'PRIVATE'}, product.check_failure('check_failed')),
                ({**safe, 'status': 'ready'}, product.check_failure('check_failed'))]:
            with patch.object(product.shutil, 'which', return_value='pwsh'), patch.object(product.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 1, json.dumps(payload).encode(), b'PRIVATE')) as run:
                self.assertEqual(product.inspect_entry(self.root, 'web', 'status'), expected)
                self.assertEqual(run.call_count, 1)

    def test_status_timeout_and_invalid_output_do_not_trigger_second_check(self):
        from subprocess import CompletedProcess, TimeoutExpired
        outcomes = [TimeoutExpired('PRIVATE', 25), OSError('PRIVATE'),
            CompletedProcess([], 0, b'PRIVATE', b''), CompletedProcess([], 0, b'x'*65537, b'')]
        reasons = ['check_timed_out', 'check_launcher_unavailable', 'check_result_invalid', 'check_result_invalid']
        for outcome, reason in zip(outcomes, reasons):
            with self.subTest(reason=reason), patch.object(product.shutil, 'which', return_value='pwsh'), \
                    patch.object(product.subprocess, 'run', **({'side_effect': outcome} if isinstance(outcome, Exception)
                        else {'return_value': outcome})) as run:
                value = product.inspect_entry(self.root, 'web', 'status')
                self.assertEqual(value, product.check_failure(reason))
                self.assertNotIn('PRIVATE', json.dumps(value))
                self.assertEqual(run.call_count, 1)

    def test_binding_check_failure_keeps_ready_backend_and_exact_next_step(self):
        self.configured()
        calls = []
        def inspect(p, scope, action):
            calls.append((scope, action))
            if action == 'status':
                return {'status': 'ready', 'active': False, 'configuration_current': True}
            return {'status': 'unavailable', 'code': 'web_entry_unavailable',
                'reason': 'web_entry_python_changed', 'stage': ['PRIVATE'], 'summary': 'PRIVATE'}
        value = product.project_overview(self.root, self.home, inspect)
        web = value['components']['models']['providers']['web']
        self.assertIn('后台就绪', web['summary'])
        self.assertEqual(web['state'], 'needs_review')
        self.assertEqual(web['diagnostic']['reason'], 'web_entry_python_changed')
        self.assertNotIn('stage', web['diagnostic'])
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertEqual(calls.count(('web', 'desktop-status')), 1)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_status_rejects_ignored_subcommands_without_state_changes(self):
        before = list(self.root.rglob('*'))
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(ROOT/'scripts/codex-operator.ps1'),
            'status', 'start', '-ProjectRoot', str(self.root), '-Json'],
            capture_output=True, encoding='utf8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('without a subcommand', result.stderr)
        self.assertEqual(list(self.root.rglob('*')), before)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_installed_facade_uses_saved_entry_and_rejects_changes_without_fallback(self):
        source = self.root/'plugin 中文/scripts'; source.mkdir(parents=True)
        entry = source/'codex-operator.ps1'
        shutil.copy2(ROOT/'scripts/codex-operator.ps1', entry)
        (source/'feishu-codex-operator.ps1').write_text("""
param([string]$Scope,[string]$Action,[string]$ProjectRoot,[switch]$Json)
@{scope=$Scope;action=$Action;project=$ProjectRoot;json=$Json.IsPresent}|ConvertTo-Json -Compress
""", encoding='utf8')
        runtime = self.root/'runtime'; runtime.mkdir()
        installed = runtime/entry.name; shutil.copy2(entry, installed)
        manifest = runtime/'runtime-manifest.json'
        saved = {'schema_version': 1, 'public_entry': {
            'path': str(entry), 'sha256': hashlib.sha256(entry.read_bytes()).hexdigest()}}
        manifest.write_text(json.dumps(saved), encoding='utf8')
        prefix = [shutil.which('pwsh'), '-NoProfile', '-File', str(installed)]
        for command, expected in [(['status'], ('product','status')),
                (['models','web','status'], ('web','status')), (['channels','readiness'], ('operator','readiness'))]:
            result = subprocess.run([*prefix,*command,'-ProjectRoot',str(self.root),'-Json'],
                capture_output=True, encoding='utf8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'scope':expected[0], 'action':expected[1],
                'project':str(self.root), 'json':True})
        original = entry.read_bytes()
        entry.write_bytes(original + b'\n# changed fixture\n')
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([*prefix,'status','-ProjectRoot',str(self.root),'-Json'],
            capture_output=True, encoding='utf8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('existing settings were preserved', result.stderr)
        self.assertEqual({str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_public_facade_runs_actual_fresh_status(self):
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(ROOT/'scripts/codex-operator.ps1'),
            'status', '-ProjectRoot', str(self.root), '-Json'], capture_output=True, encoding='utf8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout)['components']), {'channels', 'models'})

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_nested_web_status_leaves_fresh_project_unchanged(self):
        before = list(self.root.rglob('*'))
        for command in [['models', 'web', 'status'], ['models', 'web']]:
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(ROOT/'scripts/codex-operator.ps1'),
                *command, '-ProjectRoot', str(self.root), '-Json'],
                capture_output=True, encoding='utf8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'not_configured')
        self.assertEqual(list(self.root.rglob('*')), before)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_channel_uninstall_cannot_remove_the_product(self):
        sentinel = self.root/'keep.txt'; sentinel.write_text('preserve')
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(ROOT/'scripts/codex-operator.ps1'),
            'channels', 'uninstall', '-ProjectRoot', str(self.root)],
            capture_output=True, encoding='utf8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Uninstall removes the whole product.', result.stderr)
        self.assertIn('channels stop', result.stderr)
        self.assertEqual({str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows entry')
    def test_detached_overview_reads_saved_unicode_status_without_starting(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import operator_web_service as manager
        profile = self.root / '.codex/operator-web-service'
        profile.parent.mkdir()
        browser = self.root / 'browser'; browser.mkdir()
        settings = self.root / 'settings.json'
        settings.write_text(json.dumps({'electron': str(Path(sys.executable).resolve()),
            'profile_directory': str(browser), 'session_partition': 'persist:fixture'}))
        manager.configure(profile, settings)
        before = {str(p): p.read_bytes() for p in profile.rglob('*') if p.is_file()}
        observation = product.inspect_entry(self.root, 'web', 'status')
        self.assertEqual(observation['status'], 'configured')
        value = product.project_overview(self.root, self.home)
        self.assertEqual(value['components']['models']['providers']['web']['state'], 'stopped')
        self.assertEqual(value['components']['models']['providers']['web']['next_action'], 'models web start')
        self.assertEqual({str(p): p.read_bytes() for p in profile.rglob('*') if p.is_file()}, before)
        self.assertFalse((profile / 'current.json').exists())


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.repo = self.base/'repo'; self.repo.mkdir()
        self.plugin = self.repo / str(release.PLUGIN)
        def write(relative, text):
            p = self.repo/relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding='utf8')
        self.write = write
        files = ['.codex-plugin/plugin.json','assets/release-inventory.json','LICENSE',
            'assets/AGENTS.feishu-codex-operator.md', *sorted(release.REVIEWED_DOCS)]
        self.inventory = {'schema_version': 1, 'repository_files': ['LICENSE'],
            'reviewed_document_sha256': {name: hashlib.sha256(b'public documentation\n').hexdigest()
                for name in release.REVIEWED_DOCS},
            'components': [{'root_role': 'plugin_root', 'paths': files}]}
        write('LICENSE', 'MIT License')
        write(str(release.PLUGIN/'LICENSE'), 'MIT License')
        write(str(release.PLUGIN/'.codex-plugin/plugin.json'), json.dumps({'name': 'codex-operator', 'version': '1.2.0-preview.1'}))
        write(str(release.PLUGIN/'assets/AGENTS.feishu-codex-operator.md'), 'public rules')
        for name in release.REVIEWED_DOCS:
            path = self.plugin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'public documentation\n')
        self.save_inventory()

    def save_inventory(self):
        self.write(str(release.PLUGIN/'assets/release-inventory.json'), json.dumps(self.inventory))

    def test_archive_uses_allowlist_and_reviewed_docs_preserves_source(self):
        self.write('.codex/runtime.key', 'sk-'+'K'*30)
        original = (self.plugin/'README.md').read_bytes()
        output = self.base/'preview.zip'; receipt = release.build(self.repo, output)
        with zipfile.ZipFile(output) as z:
            self.assertNotIn('.codex/runtime.key', z.namelist())
            self.assertFalse(any('/assets/public-docs/' in name for name in z.namelist()))
            for relative in release.REVIEWED_DOCS:
                self.assertEqual(z.read(str(release.PLUGIN/relative)), b'public documentation\n')
            self.assertEqual(z.read('AGENTS.md'), b'public rules')
        self.assertEqual((self.plugin/'README.md').read_bytes(), original)
        self.assertFalse(receipt['published'])
        self.assertEqual(receipt['reviewed_documents'], len(release.REVIEWED_DOCS))
        with self.assertRaises(ValueError): release.build(self.repo, output)

    def test_review_digest_accepts_checkout_line_endings_without_rewriting_release_bytes(self):
        source = self.plugin / 'README.md'
        source.write_bytes(b'public documentation\r\n')
        data, _, _ = release.collect(self.repo)
        self.assertEqual(data[str(release.PLUGIN / 'README.md')], source.read_bytes())

    def test_changed_reviewed_doc_requires_new_digest_and_still_passes_content_screen(self):
        relative = 'README.md'
        source = str(release.PLUGIN / relative)
        secret = 'sk-' + 'Z'*30
        self.write(source, 'private journal ' + secret)
        with self.assertRaisesRegex(ValueError, 'reviewed_document_changed'):
            release.collect(self.repo)
        self.inventory['reviewed_document_sha256'][relative] = hashlib.sha256(
            (self.plugin / relative).read_bytes()).hexdigest()
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, 'release_content_findings') as caught:
            release.collect(self.repo)
        self.assertNotIn(secret, str(caught.exception))

    def test_credential_finding_does_not_echo_value_or_write_archive(self):
        secret = 'sk-' + 'Q'*31
        self.write('LICENSE', secret)
        with self.assertRaises(ValueError) as caught: release.build(self.repo, self.base/'preview.zip')
        self.assertIn('credential', str(caught.exception)); self.assertNotIn(secret, str(caught.exception))
        self.assertFalse((self.base/'preview.zip').exists())

    def test_inventory_escape_and_duplicates_fail_closed(self):
        for relative in ['../outside.txt', '.codex/runtime.key', '/absolute.txt',
                'models/web/_quarantine/old.py', 'channels/feishu/_QUARANTINE/note.md']:
            with self.assertRaises(ValueError): release.safe_path(relative)
        self.inventory['repository_files'].append('LICENSE'); self.save_inventory()
        with self.assertRaisesRegex(ValueError, 'duplicate_inventory'): release.collect(self.repo)

    def test_quarantine_is_not_a_release_or_test_source(self):
        from run_tests import test_files
        quarantine = self.plugin / 'models/web/_quarantine/tests/test_do_not_run.py'
        self.write(str(quarantine.relative_to(self.repo)), "raise RuntimeError('must not import')")
        self.assertEqual(test_files(self.plugin, 'test_*.py'), [])
        data, _, _ = release.collect(self.repo)
        self.assertFalse(any('_quarantine' in path for path in data))
        self.inventory['components'][0]['paths'].append('models/web/_quarantine/tests/test_do_not_run.py')
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, 'unsafe_inventory_path'):
            release.collect(self.repo)

    def test_windows_path_aliases_cannot_include_quarantine_or_collide(self):
        for relative in ['models/web/_quarantine./old.md', '.codex /private.md',
                'notes./document.md', 'aux.md', 'COM1.py', 'dir/name?.md', 'dir/line\nname.md']:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'unsafe_inventory_path'):
                release.safe_path(relative)
        self.inventory['repository_files'].extend(['notes.md', 'NOTES.md']); self.save_inventory()
        with self.assertRaisesRegex(ValueError, 'duplicate_inventory_path'):
            release.collect(self.repo)
        for generated in ['AGENTS.md', 'agents.md', 'RELEASE-MANIFEST.json']:
            self.inventory['repository_files'] = ['LICENSE', generated]; self.save_inventory()
            with self.assertRaisesRegex(ValueError, 'generated_inventory_path'):
                release.collect(self.repo)

    def test_fixture_exception_requires_exact_value_and_exact_file(self):
        relative = str(release.PLUGIN / 'models/web/tests/test_web_service_manager.py')
        self.inventory['components'][0]['paths'].append('models/web/tests/test_web_service_manager.py')
        self.save_inventory()
        fixture = 'sk-' + 'fixture-private-never-copy'
        self.write(relative, fixture)
        release.collect(self.repo)
        self.write(relative, fixture + '-changed')
        with self.assertRaisesRegex(ValueError, 'release_content_findings'): release.collect(self.repo)
        self.write(relative, fixture)
        self.write('LICENSE', fixture)
        with self.assertRaisesRegex(ValueError, 'release_content_findings'): release.collect(self.repo)


if __name__ == '__main__': unittest.main()
