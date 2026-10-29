"""Exercise installation boundaries in a copied source and disposable desktop."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import hashlib
import tempfile
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
PWSH = shutil.which('pwsh')


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows PowerShell required')
class DesktopExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Immutable stand-in only. Each case still owns its app file, shortcuts,
        # receipts and real production launcher builds. Nothing survives this run.
        with tempfile.TemporaryDirectory(prefix='operator-fixture-app-') as directory:
            source = Path(directory) / 'fixture.cs'
            binary = Path(directory) / 'ChatGPT.exe'
            source.write_text('class Fixture { static void Main() {} }', encoding='utf-8')
            compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            result = subprocess.run([str(compiler), '/nologo', '/target:winexe',
                '/out:' + str(binary), str(source)], capture_output=True,
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(f'Fixture compilation failed: {result.stdout!r} {result.stderr!r}')
            cls.fixture_app_bytes = binary.read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-desktop-experience-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        (self.home / 'config.toml').write_text('model = "fixture"\n')
        self.desktop = self.root / 'desktop'
        self.programs = self.root / 'programs'
        self.desktop.mkdir()
        self.programs.mkdir()
        self.source = self.root / 'source'
        scripts = self.source / 'scripts'
        scripts.mkdir(parents=True)
        # No live shell-folder paths remain in this disposable copy. The
        # production implementation has no fixture-home command-line option.
        for path in (ROOT / 'scripts').iterdir():
            if path.suffix not in ('.ps1', '.psm1', '.cs', '.py'):
                continue
            text = path.read_text(encoding='utf-8-sig')
            text = text.replace("[Environment]::GetFolderPath('DesktopDirectory')", q(self.desktop))
            text = text.replace("[Environment]::GetFolderPath('Programs')", q(self.programs))
            text = text.replace("Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'", q(self.home))
            (scripts / path.name).write_text(text, encoding='utf-8')
        (scripts / 'operator_core').mkdir()
        shutil.copyfile(ROOT / 'scripts/operator_core/windows_config_transaction.py',
                        scripts / 'operator_core/windows_config_transaction.py')
        (self.source / '.codex-plugin').mkdir()
        shutil.copyfile(ROOT / '.codex-plugin/plugin.json', self.source / '.codex-plugin/plugin.json')
        fixture_app = self.project / 'app-package/app/ChatGPT.exe'
        fixture_app.parent.mkdir(parents=True)
        fixture_app.write_bytes(self.fixture_app_bytes)
        self.prefix = f"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$p={q(self.project)}
. {q(scripts / 'operator_desktop_setup.ps1')} -ProjectRoot $p -Library
$fixtureApp=Join-Path $p 'app-package'
function Get-AppxPackage {{param($Name) [pscustomobject]@{{InstallLocation=$fixtureApp}}}}
"""

    def ps(self, code):
        driver = self.root / 'driver.ps1'
        driver.write_text(self.prefix + code, encoding='utf-8')
        return subprocess.run([PWSH, '-NoProfile', '-File', str(driver)], capture_output=True,
            text=True, encoding='utf-8', timeout=75,
            env={**os.environ, 'CODEX_HOME':str(self.home)}, creationflags=subprocess.CREATE_NO_WINDOW)

    def uninstall(self, config, port):
        command = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); & " +
            q(ROOT / 'scripts/uninstall-feishu-codex-operator.ps1') + ' -ProjectRoot ' + q(self.project) +
            ' -CodexConfig ' + q(config) + ' -RouterPort ' + str(port) + ' -Apply')
        return subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True,
            text=True, encoding='utf-8', timeout=45, env={**os.environ, 'CODEX_HOME':str(self.home)},
            creationflags=subprocess.CREATE_NO_WINDOW)

    def test_fresh_launcher_reuse_and_full_uninstall_keep_original_app_and_config(self):
        result = self.ps(f"""
Assert-OperatorDesktopExperiencePreflight -ProjectRoot $p -CodexHome {q(self.home)}
$first=Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)}
$before=@{{}}
foreach($path in @(Get-ChildItem -LiteralPath {q(self.desktop)} -File)){{$before[$path.FullName]=Get-OperatorFingerprint $path.FullName}}
$second=Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)}
foreach($path in $before.Keys){{if((Get-OperatorFingerprint $path) -cne $before[$path]){{throw 'Repeated install rewrote shortcut'}}}}
@{{first=$first;second=$second}} | ConvertTo-Json -Depth 6 -Compress
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['first']['changed'])
        self.assertFalse(json.loads(result.stdout)['second']['changed'])
        self.assertEqual([p.name for p in self.desktop.glob('*.lnk')], ['ChatGPT 自定义启动.lnk'])
        bundle = self.project / '.codex/operator-desktop-entry'
        self.assertEqual(json.loads((bundle / 'launcher-manifest.json').read_text())['shortcut_layout'], 'single')
        self.assertEqual(json.loads((bundle / 'desktop-entry.json').read_text())['launch_selection'], 'native_or_extension_v1')
        self.assertEqual(list(self.programs.iterdir()), [])
        self.assertFalse((self.desktop / 'Codex拓展入口.lnk').exists())
        config = (self.home / 'config.toml').read_bytes()
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        rejected = self.uninstall(self.root / 'wrong-config.toml', port)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('another native home', rejected.stderr)
        self.assertEqual([p.name for p in self.desktop.glob('*.lnk')], ['ChatGPT 自定义启动.lnk'])
        self.assertFalse((self.project / '.codex/operator-installation/uninstall-receipt.json').exists())
        removed = self.uninstall(self.home / 'config.toml', port)
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertTrue(json.loads(removed.stdout)['uninstalled'])
        self.assertEqual(list(self.desktop.glob('*.lnk')), [])
        self.assertEqual((self.home / 'config.toml').read_bytes(), config)
        self.assertTrue((self.project / '.codex/operator-desktop-entry/native-only').is_file())
        self.assertTrue((self.project / 'app-package/app/ChatGPT.exe').is_file())
        prior_owner = (self.project / '.codex/operator-installation/ownership.json').read_bytes()
        reinstalled = self.ps(f"Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)} | ConvertTo-Json -Compress")
        self.assertEqual(reinstalled.returncode, 0, reinstalled.stdout + reinstalled.stderr)
        self.assertEqual([p.name for p in self.desktop.glob('*.lnk')], ['ChatGPT 自定义启动.lnk'])
        self.assertFalse((self.project / '.codex/operator-desktop-entry/native-only').exists())
        old_owners = list((self.project / '.codex/operator-installation/history').glob('*/ownership.json'))
        self.assertEqual(len(old_owners), 1)
        self.assertEqual(old_owners[0].read_bytes(), prior_owner)

    def test_preflight_failure_has_no_build_and_prepared_pair_never_becomes_legacy(self):
        other_home = self.root / 'wrong-home'
        other_home.mkdir()
        result = self.ps(f"""
$blocked=$false
try {{Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(other_home)} | Out-Null}} catch {{$blocked=$true}}
if(-not $blocked -or (Test-Path -LiteralPath (Join-Path $p '.codex'))){{throw 'Home rejection occurred after installation writes'}}
Install-OperatorDesktopEntry -ProjectRoot $p -NoShortcuts | Out-Null
if(-not (Test-OperatorPairedBuild $p)){{throw 'Prepared pair identity missing'}}
$built=Get-OperatorFingerprint (Join-Path $p '.codex/operator-desktop-entry/launcher-manifest.json')
$link=Join-Path {q(self.desktop)} 'ChatGPT 原生入口.lnk'
[IO.File]::WriteAllText($link,'later unrelated shortcut')
$blocked=$false
try {{Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)} | Out-Null}} catch {{$blocked=$true}}
if(-not $blocked){{throw 'Unknown shortcut was adopted'}}
if((Get-OperatorFingerprint (Join-Path $p '.codex/operator-desktop-entry/launcher-manifest.json')) -cne $built){{throw 'Prepared build replaced'}}
if([IO.File]::ReadAllText($link) -cne 'later unrelated shortcut'){{throw 'Unknown shortcut changed'}}
if(Test-Path -LiteralPath (Join-Path {q(self.desktop)} 'Codex拓展入口.lnk')){{throw 'Failed pair fell back to legacy'}}
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_custom_shortcut_stops_before_build_and_keeps_original(self):
        target = self.desktop / 'ChatGPT 自定义启动.lnk'
        target.write_bytes(b'unrelated owner bytes')
        result = self.ps(f'Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pair_shortcut_name_conflict', result.stderr)
        self.assertEqual(target.read_bytes(), b'unrelated owner bytes')
        self.assertFalse((self.project / '.codex').exists())

    def test_unowned_old_dated_shortcut_is_preserved_before_new_install(self):
        target = self.desktop / 'ChatGPT 拓展模型 01-01 入口.lnk'
        target.write_bytes(b'unknown historical shortcut')
        result = self.ps(f'Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pair_legacy_migration_required', result.stderr)
        self.assertEqual(target.read_bytes(), b'unknown historical shortcut')
        self.assertFalse((self.project / '.codex').exists())

    def test_fresh_preflight_rejects_legacy_workflow_before_initialization_writes(self):
        result = self.ps(f'Assert-OperatorDesktopExperiencePreflight -ProjectRoot $p '
            f'-CodexHome {q(self.home)} -StartupBundle {q(self.project / "legacy-workflow")}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unified_launcher_requires_fresh_isolated_setup', result.stderr)
        self.assertFalse((self.project / '.codex').exists())
        self.assertEqual(list(self.desktop.iterdir()), [])

    def test_single_layout_binds_isolated_mode_without_recreating_second_shortcut(self):
        # Only the binding/receipt path is under test. This explicit status-only
        # controller cannot launch an application, service or model request.
        scripts = self.project / 'plugins/feishu-codex-operator/scripts'
        scripts.mkdir(parents=True)
        controller = scripts / 'operator_mode_entry.py'
        controller.write_text('import json\nprint(json.dumps({"phase":"checked",'
            '"official_package_matches":True,"native_enabled":False,'
            '"native_config_writes":0,"model_requests_sent_by_controller":0}))\n', encoding='utf-8')
        mode_root = self.project / '.codex/operator-mode-entry' / ('a' * 32)
        mode_root.mkdir(parents=True)
        entry = mode_root / 'entry.ps1'
        entry.write_text("throw 'Fixture must never launch'", encoding='utf-8')
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        descriptor = {'schema_version':1,'contract':'operator_isolated_mode_entry_v1',
            'project':str(self.project),'root':str(mode_root),'native_home':str(self.home),
            'native_enabled':False,'entry_sha256':sha(entry),'python':sys.executable,
            'python_sha256':sha(Path(sys.executable)),
            'source_bindings':{'operator_mode_entry.py':sha(controller)}}
        selected = mode_root / 'entry.json'
        selected.write_text(json.dumps(descriptor), encoding='utf-8')
        result = self.ps(f'''
Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)} | Out-Null
Import-Module {q(self.source / 'scripts/operator_desktop_pair_upgrade.psm1')} -DisableNameChecking
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p -IsolatedModePath {q(selected)}
$review=Get-OperatorDesktopPairUpgrade -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory
Invoke-OperatorDesktopPairUpgrade -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory -ExpectedPlanSha256 $review.sha256 | Out-Null
$state=Get-OperatorDesktopPairRestorePlan -ProjectRoot $p
$next=New-OperatorEntryBuildCandidate -ProjectRoot $p -IsolatedModePath {q(selected)}
Get-OperatorDesktopPairUpgrade -ProjectRoot $p -CandidateDirectory $next.candidate_directory | Out-Null
@{{layout=$state.record.shortcut_layout;links=@($state.record.links.Keys)}} | ConvertTo-Json -Compress
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['layout'], 'single')
        self.assertEqual([p.name for p in self.desktop.glob('*.lnk')], ['ChatGPT 自定义启动.lnk'])
        config = json.loads((self.project / '.codex/operator-desktop-entry/desktop-entry.json').read_text())
        self.assertEqual(config['mode'], 'isolated_mode')
        self.assertEqual(config['mode_entry_sha256'], sha(selected))
        self.assertEqual((self.home / 'config.toml').read_text(), 'model = "fixture"\n')

    def test_single_launcher_build_upgrade_keeps_name_and_retained_originals(self):
        result = self.ps(f'''
Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)} | Out-Null
$old=[IO.File]::ReadAllBytes((Join-Path $p '.codex/operator-desktop-pair/ownership.json'))
Import-Module {q(self.source / 'scripts/operator_desktop_pair_upgrade.psm1')} -DisableNameChecking
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p
$review=Get-OperatorDesktopPairUpgrade -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory
$result=Invoke-OperatorDesktopPairUpgrade -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory -ExpectedPlanSha256 $review.sha256
$state=Get-OperatorDesktopPairRestorePlan -ProjectRoot $p
$oldReceipt=Get-ChildItem -LiteralPath (Join-Path $p '.codex/operator-desktop-pair/upgrades') -Filter '*.before' -Recurse |
    Where-Object {{[Convert]::ToBase64String([IO.File]::ReadAllBytes($_.FullName)) -ceq [Convert]::ToBase64String($old)}}
if(-not $oldReceipt){{throw 'Original ownership was not retained'}}
@{{result=$result;layout=$state.record.shortcut_layout;links=@($state.record.links.Keys)}} | ConvertTo-Json -Depth 5 -Compress
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['layout'], 'single')
        self.assertEqual(value['links'], [str(self.desktop / 'ChatGPT 自定义启动.lnk')])
        self.assertEqual([p.name for p in self.desktop.glob('*.lnk')], ['ChatGPT 自定义启动.lnk'])
        self.assertEqual((self.home / 'config.toml').read_text(), 'model = "fixture"\n')

    def test_failed_single_publication_retains_terminal_record_and_later_edit(self):
        result = self.ps(f'''
Install-OperatorDesktopEntry -ProjectRoot $p -NoShortcuts -UnifiedLauncher | Out-Null
Import-Module {q(self.source / 'scripts/operator_desktop_pair.psm1')} -DisableNameChecking
& (Get-Module operator_desktop_pair) {{
    $script:originalWrite=(Get-Command Write-RecoveryChange).ScriptBlock
    function script:Write-RecoveryChange($Change) {{
        if ($Change.path -like '*ChatGPT 自定义启动.lnk') {{
            [IO.File]::WriteAllText($Change.path,'later user edit')
            throw 'synthetic_single_publication_failure'
        }}
        & $script:originalWrite $Change
    }}
}}
$arguments=Get-OperatorPairArguments $p {q(self.home)}
Install-OperatorDesktopPair @arguments
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('synthetic_single_publication_failure', result.stderr)
        self.assertEqual((self.desktop / 'ChatGPT 自定义启动.lnk').read_text(), 'later user edit')
        self.assertTrue((self.project / '.codex/operator-desktop-pair/pending.json').is_file())
        again = self.ps(f'Install-OperatorDesktopExperience -ProjectRoot $p -CodexHome {q(self.home)}')
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('pair_pending_requires_review', again.stderr)
        self.assertEqual((self.desktop / 'ChatGPT 自定义启动.lnk').read_text(), 'later user edit')


if __name__ == '__main__':
    unittest.main()
