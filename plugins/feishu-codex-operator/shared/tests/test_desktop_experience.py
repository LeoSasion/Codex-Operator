"""Exercise installation boundaries in a copied source and disposable desktop."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
PWSH = shutil.which('pwsh')


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows PowerShell required')
class DesktopExperienceTests(unittest.TestCase):
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
            if path.suffix not in ('.ps1', '.psm1', '.cs'):
                continue
            text = path.read_text(encoding='utf-8-sig')
            text = text.replace("[Environment]::GetFolderPath('DesktopDirectory')", q(self.desktop))
            text = text.replace("[Environment]::GetFolderPath('Programs')", q(self.programs))
            text = text.replace("Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'", q(self.home))
            (scripts / path.name).write_text(text, encoding='utf-8')
        (self.source / '.codex-plugin').mkdir()
        shutil.copyfile(ROOT / '.codex-plugin/plugin.json', self.source / '.codex-plugin/plugin.json')
        self.prefix = f"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$p={q(self.project)}
. {q(scripts / 'operator_desktop_setup.ps1')} -ProjectRoot $p -Library
$fixtureApp=Join-Path $p 'app-package'
[void][IO.Directory]::CreateDirectory((Join-Path $fixtureApp 'app'))
$fixtureSource=Join-Path $p 'fixture.cs'
[IO.File]::WriteAllText($fixtureSource,'class Fixture {{ static void Main() {{}} }}')
& (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe') /nologo /target:winexe (('/out:')+(Join-Path $fixtureApp 'app/ChatGPT.exe')) $fixtureSource
if($LASTEXITCODE -ne 0){{throw 'Fixture compilation failed'}}
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

    def test_fresh_pair_reuse_and_full_uninstall_keep_original_app_and_config(self):
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
        self.assertEqual(len(list(self.desktop.glob('*.lnk'))), 2)
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
        self.assertEqual(len(list(self.desktop.glob('*.lnk'))), 2)
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
        self.assertEqual(len(list(self.desktop.glob('*.lnk'))), 2)
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


if __name__ == '__main__':
    unittest.main()
