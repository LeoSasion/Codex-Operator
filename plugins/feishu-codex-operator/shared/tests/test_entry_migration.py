"""Reviewed legacy entry migration in disposable shell folders only."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=_OPERATOR_PLUGIN_ROOT

@unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class EntryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='operator-entry-migration-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        (self.root/'.codex/legacy').mkdir(parents=True)
        (self.root/'.codex/feishu-codex-operator-runtime').mkdir()
        (self.root/'.codex/feishu-codex-operator-runtime/runtime-manifest.json').write_bytes(b'unknown legacy origin')
        (self.root/'AGENTS.md').write_bytes(b'existing owner rules\r\n')
        (self.root/'.codex/hooks.json').write_bytes(b'existing hooks')
        self.startup=self.root/'.codex/startup';self.startup.mkdir()
        raw=b'exit 0\n';(self.startup/'start-codex-with-web.ps1').write_bytes(raw)
        (self.startup/'startup-sync-plan.json').write_text(json.dumps({'schema_version':2,
            'startup_script':'start-codex-with-web.ps1','entry_files':{
            'start-codex-with-web.ps1':hashlib.sha256(raw).hexdigest()}}),encoding='utf8')
        self.bootstrap="""
$ErrorActionPreference='Stop'
. SETUP -ProjectRoot PROJECT -Library
$p=PROJECT;$startup=Join-Path $p '.codex/startup';$receipt=Join-Path $p '.codex/legacy/receipt.json'
$fixtureDesktop=Join-Path $p 'fake-desktop';$fixturePrograms=Join-Path $p 'fake-programs';$fixtureApp=Join-Path $p 'fake-app'
function Get-OperatorDesktopPaths { @((Join-Path $fixtureDesktop 'Codex拓展入口.lnk'),(Join-Path $fixturePrograms 'Codex拓展入口.lnk')) }
function Get-AppxPackage { param($Name) [pscustomobject]@{InstallLocation=$fixtureApp} }
""".replace('SETUP',self.q(ROOT/'scripts/operator_desktop_setup.ps1')).replace('PROJECT',self.q(self.root))
        setup="""
New-Item -ItemType Directory -Path $fixtureDesktop,$fixturePrograms,(Join-Path $fixtureApp 'app') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSHOME 'pwsh.exe') -Destination (Join-Path $fixtureApp 'app/ChatGPT.exe')
$old=Join-Path $p '.codex/legacy/Codex拓展入口.exe'
[IO.File]::WriteAllText($old,'never executed fixture')
$wsh=New-Object -ComObject WScript.Shell
$link=$wsh.CreateShortcut((Join-Path $fixturePrograms 'Codex拓展入口.lnk'));$link.TargetPath=$old;$link.Save()
$rows=@(Get-OperatorDesktopPaths | ForEach-Object { @{path=$_;target=$old;sha256=(Get-OperatorFingerprint $_)} })
@{status='completed';operation='owner_requested_reviewed_legacy_entry_rename';new_executable=$old;
launcher_sha256=(Get-OperatorFingerprint $old);installed_links=$rows}|ConvertTo-Json -Depth 5|Set-Content $receipt -Encoding utf8
"""
        self.assert_ok(self.run_ps(setup))

    @staticmethod
    def q(value):return "'"+str(value).replace("'","''")+"'"

    def run_ps(self,code):
        script=self.root/'driver.ps1';script.write_text(self.bootstrap+code,encoding='utf8')
        return subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(script)],capture_output=True,text=True,encoding='utf8',timeout=40)

    def assert_ok(self,result):self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_entry_build_roundtrip_preserves_unknown_runtime_and_missing_shortcut(self):
        result=self.run_ps("""
$review=Get-OperatorEntryMigrationPlan $p $receipt $startup
if(Test-Path (Join-Path $p '.codex/operator-entry-migration')){throw 'Preview wrote state'}
$blocked=$false;try{Get-OperatorOwnership $p | Out-Null}catch{$blocked=$true};if(-not $blocked){throw 'Unknown legacy runtime accepted'}
$oldLink=Join-Path $fixturePrograms 'Codex拓展入口.lnk';$oldHash=Get-OperatorFingerprint $oldLink
Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256 | Out-Null
if(Test-Path (Join-Path $p '.codex/operator-installation/ownership.json')){throw 'Project ownership fabricated'}
$state=Get-OperatorEntryMigrationState $p
if($state.phase -cne 'installed' -or $state.entries[$oldLink].before -cne $oldHash){throw 'Missing migration baseline'}
foreach($path in @(Get-OperatorDesktopPaths)) {
    $link=(New-Object -ComObject WScript.Shell).CreateShortcut($path)
    if($link.TargetPath -ine (Join-Path $p '.codex/operator-desktop-entry/Codex拓展入口.exe')){throw 'Wrong target'}
}
$blocked=$false;try{Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256 | Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Repeated transaction accepted'}
$backup=[IO.File]::ReadAllBytes($oldLink);[IO.File]::WriteAllText($oldLink,'later user edit')
$blocked=$false;try{Restore-OperatorEntryMigration $p | Out-Null}catch{$blocked=$true};if(-not $blocked){throw 'Edited shortcut restored'}
if(Test-Path (Join-Path $p '.codex/operator-desktop-entry/native-only')){throw 'Rejected restore changed launcher'}
[IO.File]::WriteAllBytes($oldLink,$backup)
Restore-OperatorEntryMigration $p | Out-Null
if((Get-OperatorFingerprint $oldLink) -cne $oldHash){throw 'Original bytes lost'}
if(Test-Path (Join-Path $fixtureDesktop 'Codex拓展入口.lnk')){throw 'Original absence lost'}
if(-not(Test-Path (Join-Path $p '.codex/operator-desktop-entry/native-only'))){throw 'Pins lost native fallback'}
""")
        self.assert_ok(result)
        self.assertEqual((self.root/'AGENTS.md').read_bytes(),b'existing owner rules\r\n')
        self.assertEqual((self.root/'.codex/hooks.json').read_bytes(),b'existing hooks')
        self.assertEqual((self.root/'.codex/feishu-codex-operator-runtime/runtime-manifest.json').read_bytes(),b'unknown legacy origin')

    def test_changed_preview_stops_before_writing_journal_or_build(self):
        self.assert_ok(self.run_ps("""
$review=Get-OperatorEntryMigrationPlan $p $receipt $startup
$path=Join-Path $fixturePrograms 'Codex拓展入口.lnk';[IO.File]::WriteAllText($path,'changed after preview')
$blocked=$false;try{Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256}catch{$blocked=$true}
if(-not $blocked -or (Test-Path (Join-Path $p '.codex/operator-entry-migration')) -or
    (Test-Path (Join-Path $p '.codex/operator-desktop-entry'))){throw 'Changed preview wrote state'}
"""))

    def test_incomplete_migration_is_never_retried_or_given_global_ownership(self):
        self.assert_ok(self.run_ps("""
$review=Get-OperatorEntryMigrationPlan $p $receipt $startup
New-Item -ItemType Directory -Path (Join-Path $p '.codex/operator-entry-migration') | Out-Null
$blocked=$false;try{Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256}catch{$blocked=$true}
if(-not $blocked -or (Test-Path (Join-Path $p '.codex/operator-desktop-entry')) -or
    (Test-Path (Join-Path $p '.codex/operator-installation/ownership.json'))){throw 'Uncertain migration retried'}
"""))
