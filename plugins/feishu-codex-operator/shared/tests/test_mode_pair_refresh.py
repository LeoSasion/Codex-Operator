"""Bound mode/pair publication in disposable Windows shortcut fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import unittest

from test_desktop_pair_legacy import LegacyPairTests, ROOT


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class ModePairRefreshTests(LegacyPairTests):
    def staged_refresh(self, package=None):
        self.apply()
        index = self.isolated_candidate()
        if package is not None:
            entry = json.loads(index.read_text('utf8'))
            entry.update(package=package, onboarding={'contract': 'operator_desktop_welcome_preference_20261002_v1',
                                                      'supported': False, 'preferences': {}})
            index.write_text(json.dumps(entry), encoding='utf8')
            self.assert_ok(self.run_ps(f"""
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p -IsolatedModePath {self.q(index)}
[IO.File]::WriteAllText((Join-Path $p 'candidate-path.txt'),$candidate.candidate_directory)
"""))
            self.candidate = Path((self.root / 'candidate-path.txt').read_text('utf8'))
        self.apply()
        root = index.parent
        stage = root / 'pair-refreshes' / ('e' * 32)
        (stage / 'originals').mkdir(parents=True)
        (stage / 'staged').mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        names = ('entry.json', 'entry.ps1', 'operator-mode-host.exe', 'operator-mode-native.exe', 'operator-mode-picker.exe')
        for name in names:
            path = root / name
            if not path.exists():
                path.write_bytes(('old fixture: ' + name).encode())
            (stage / 'originals' / name).write_bytes(path.read_bytes())
            (stage / 'staged' / name).write_bytes(path.read_bytes() if name == 'entry.json' else
                                               ('new fixture: ' + name).encode())
        entry = json.loads(index.read_text('utf8'))
        entry['entry_sha256'] = digest(stage / 'staged/entry.ps1')
        entry['compiled'] = {name: digest(stage / 'staged' / name) for name in names if name.endswith('.exe')}
        (stage / 'staged/entry.json').write_text(json.dumps(entry), encoding='utf8')
        manifest = {'contract': 'operator_mode_bound_pair_refresh_v1', 'root': str(root), 'generation': stage.name,
            'files': {name: {'before': digest(root / name), 'after': digest(stage / 'staged' / name)} for name in names},
            'protected_files': {str(self.home / 'config.toml'): digest(self.home / 'config.toml')}}
        (stage / 'prepared.json').write_text(json.dumps(manifest), encoding='utf8')
        return root, stage

    def staged_package_upgrade(self):
        family = 'OpenAI.Codex_fixturepublisher'
        old = {'full_name': 'OpenAI.Codex_26.928.3736.0_x64__fixturepublisher', 'family': family,
               'version': '26.928.3736.0', 'executable': 'retained-old-package-fixture', 'executable_sha256': 'a' * 64}
        root, stage = self.staged_refresh(old)
        install = self.root / 'official-package-fixture'
        (install / 'app').mkdir(parents=True)
        executable = install / 'app/ChatGPT.exe'
        executable.write_bytes(b'new official executable fixture; never run')
        (install / 'AppxManifest.xml').write_text(
            '<Package><Identity Name="OpenAI.Codex"/><Applications>'
            '<Application Id="App" Executable="app/ChatGPT.exe" EntryPoint="Windows.FullTrustApplication"/>'
            '</Applications></Package>', encoding='utf8')
        new = {'full_name': 'OpenAI.Codex_26.930.2377.0_x64__fixturepublisher', 'family': family,
               'version': '26.930.2377.0', 'executable': str(executable),
               'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
        onboarding = {'contract': 'operator_desktop_welcome_preference_20261002_v1', 'supported': False, 'preferences': {}}
        manifest = json.loads((stage / 'prepared.json').read_text('utf8'))
        manifest['package_update'] = {'contract': 'operator_mode_official_package_update_v1',
                                      'before': old, 'after': new, 'onboarding': onboarding}
        manifest['protected_files'][str(executable)] = new['executable_sha256']
        entry = json.loads((stage / 'staged/entry.json').read_text('utf8'))
        entry.update(package=new, onboarding=onboarding)
        (stage / 'staged/entry.json').write_text(json.dumps(entry), encoding='utf8')
        manifest['files']['entry.json']['after'] = hashlib.sha256((stage / 'staged/entry.json').read_bytes()).hexdigest()
        (stage / 'prepared.json').write_text(json.dumps(manifest), encoding='utf8')
        self.bootstrap += f"""
function Get-AppxPackage {{
 param($Name)
 if($Name -cne 'OpenAI.Codex') {{throw 'fixture_package_name_changed'}}
 return [pscustomobject]@{{PackageFullName='{new['full_name']}';PackageFamilyName='{family}';
   Version=[version]'26.930.2377.0';InstallLocation={self.q(install)}}}
}}
"""
        return root, stage, install

    def test_explicit_package_upgrade_preserves_shortcuts_native_config_and_legacy_receipts(self):
        root, stage, install = self.staged_package_upgrade()
        preserved = {p: p.read_bytes() for p in self.desktop.glob('*.lnk')}
        preserved[self.home / 'config.toml'] = (self.home / 'config.toml').read_bytes()
        receipt = json.loads((self.pair_root / 'ownership.json').read_text('utf8'))
        preview = self.invoke(root, stage, 'preview')
        self.assert_ok(preview)
        result = self.invoke(root, stage, 'apply', json.loads(preview.stdout)['preview_sha256'])
        self.assert_ok(result)
        self.assertEqual(json.loads((root / 'entry.json').read_text('utf8'))['package']['version'], '26.930.2377.0')
        self.assertEqual(json.loads((self.pair_root / 'ownership.json').read_text('utf8'))['steps'][:-1], receipt['steps'])
        self.assertEqual({p: p.read_bytes() for p in preserved}, preserved)
        self.assertEqual((stage / 'originals/entry.json').read_bytes(),
                         (self.pair_root / 'generations' / receipt['generation'] / 'isolated-entry.after.json').read_bytes())

    def test_installed_package_change_after_preview_rejects_before_entry_write(self):
        root, stage, install = self.staged_package_upgrade()
        preview = self.invoke(root, stage, 'preview')
        self.assert_ok(preview)
        before = (root / 'entry.json').read_bytes()
        (install / 'app/ChatGPT.exe').write_bytes(b'changed official package after preview')
        result = self.invoke(root, stage, 'apply', json.loads(preview.stdout)['preview_sha256'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mode_pair_package_update_changed', result.stdout)
        self.assertEqual((root / 'entry.json').read_bytes(), before)

    def test_package_rebinding_without_explicit_manifest_is_rejected(self):
        root, stage, install = self.staged_package_upgrade()
        manifest = json.loads((stage / 'prepared.json').read_text('utf8'))
        del manifest['package_update']
        (stage / 'prepared.json').write_text(json.dumps(manifest), encoding='utf8')
        before = (root / 'entry.json').read_bytes()
        result = self.invoke(root, stage, 'preview')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mode_pair_descriptor_changed', result.stdout)
        self.assertEqual((root / 'entry.json').read_bytes(), before)

    def invoke(self, root, stage, action, expected=None):
        arguments = f"-Action {action} -Root {self.q(root)} -StageDirectory {self.q(stage)}"
        if expected:
            arguments += f" -ExpectedPlanSha256 {expected}"
        return self.run_ps(f"& {self.q(ROOT / 'scripts/operator_mode_pair_refresh.ps1')} {arguments}\nexit $LASTEXITCODE")

    def test_bound_refresh_retains_every_legacy_step_and_shortcut_identity(self):
        root, stage = self.staged_refresh()
        receipt = json.loads((self.pair_root / 'ownership.json').read_text('utf8'))
        preserved = {p: p.read_bytes() for p in (self.start, self.home / 'config.toml',
            self.root / '.codex/operator-entry-migration/journal.json', self.pair_root / 'legacy-origin.json')}
        for path in self.desktop.glob('*.lnk'):
            preserved[path] = path.read_bytes()
        preview = self.invoke(root, stage, 'preview')
        self.assert_ok(preview)
        sha = json.loads(preview.stdout)['preview_sha256']
        denied = self.invoke(root, stage, 'apply', '0' * 64)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('mode_pair_preview_changed', denied.stdout)
        self.assertEqual(json.loads((self.pair_root / 'ownership.json').read_text('utf8')), receipt)
        applied = self.invoke(root, stage, 'apply', sha)
        self.assert_ok(applied)
        self.assertEqual(json.loads(applied.stdout)['phase'], 'pair_refreshed')
        after = json.loads((self.pair_root / 'ownership.json').read_text('utf8'))
        self.assertEqual(after['steps'][:-1], receipt['steps'])
        self.assertEqual(after['runtime_ownership'], 'unresolved')
        self.assertEqual({p: p.read_bytes() for p in preserved}, preserved)
        self.assertEqual((root / 'entry.json').read_bytes(), (stage / 'staged/entry.json').read_bytes())
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))
        self.assert_ok(self.run_ps('Restore-OperatorDesktopLegacyPair $p | Out-Null'))

    def test_later_native_edit_rejects_bound_publication_without_overwrite(self):
        root, stage = self.staged_refresh()
        preview = self.invoke(root, stage, 'preview')
        self.assert_ok(preview)
        sha = json.loads(preview.stdout)['preview_sha256']
        (self.home / 'config.toml').write_bytes(b'# later native owner edit\n')
        before = (root / 'entry.json').read_bytes()
        result = self.invoke(root, stage, 'apply', sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mode_pair_preview_changed', result.stdout)
        self.assertEqual((root / 'entry.json').read_bytes(), before)
        self.assertEqual((self.home / 'config.toml').read_bytes(), b'# later native owner edit\n')

    def test_backend_files_publish_with_bound_pair_and_keep_native_shortcuts(self):
        root, stage = self.staged_refresh()
        manifest = json.loads((stage / 'prepared.json').read_text('utf8'))
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        preserved = {p:p.read_bytes() for p in self.desktop.glob('*.lnk')}
        preserved[self.home / 'config.toml'] = (self.home / 'config.toml').read_bytes()
        for name in ('router/registry.json', 'home/models.json'):
            (root / name).parent.mkdir(exist_ok=True)
            (stage / 'originals' / name).parent.mkdir(exist_ok=True)
            (stage / 'staged' / name).parent.mkdir(exist_ok=True)
            (root / name).write_bytes(b'{"fixture":"original backend"}')
            (stage / 'originals' / name).write_bytes((root / name).read_bytes())
            (stage / 'staged' / name).write_bytes(b'{"fixture":"reviewed backend"}')
            manifest['files'][name] = {'before':digest(root / name), 'after':digest(stage / 'staged' / name)}
        manifest['backend_update'] = {'registry_file':str(root / 'router/registry.json'),
            'registry_sha256':manifest['files']['router/registry.json']['after'],
            'catalog_sha256':manifest['files']['home/models.json']['after'], 'web':None}
        entry = json.loads((stage / 'staged/entry.json').read_text('utf8'))
        entry['registry_sha256'] = manifest['backend_update']['registry_sha256']
        entry['catalog_sha256'] = manifest['backend_update']['catalog_sha256']
        (stage / 'staged/entry.json').write_text(json.dumps(entry), encoding='utf8')
        manifest['files']['entry.json']['after'] = digest(stage / 'staged/entry.json')
        (stage / 'prepared.json').write_text(json.dumps(manifest), encoding='utf8')
        preview = self.invoke(root, stage, 'preview')
        self.assert_ok(preview)
        self.assert_ok(self.invoke(root, stage, 'apply', json.loads(preview.stdout)['preview_sha256']))
        self.assertEqual({p:p.read_bytes() for p in preserved}, preserved)
        for name in ('router/registry.json', 'home/models.json', 'entry.json'):
            self.assertEqual((root / name).read_bytes(), (stage / 'staged' / name).read_bytes())
            self.assertEqual((stage / 'originals' / name).exists(), True)
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ModePairRefreshTests(name) for name in ModePairRefreshTests.__dict__
                              if name.startswith('test_'))
