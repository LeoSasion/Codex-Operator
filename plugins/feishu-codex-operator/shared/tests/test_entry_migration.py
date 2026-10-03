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
import sys
import tempfile
import unittest
from unittest.mock import patch

import operator_unified_entry_preview as entry_preview
import operator_unified_cold_start as cold_start

ROOT=_OPERATOR_PLUGIN_ROOT

@unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class EntryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='operator-entry-migration-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        launcher_home = patch.dict(os.environ, {'CODEX_HOME': str(self.root/'disposable-home')})
        launcher_home.start()
        self.addCleanup(launcher_home.stop)
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
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
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

    def test_selected_shortcuts_require_exact_ownership_and_target(self):
        self.assert_ok(self.run_ps("""
$review=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256 | Out-Null
"""))
        bundle = self.root / '.codex/operator-desktop-entry'
        links = (self.root / 'fake-desktop/Codex拓展入口.lnk',
                 self.root / 'fake-programs/Codex拓展入口.lnk')
        fingerprint = entry_preview.verify_owned_entry(self.root, bundle, test_shortcuts=links)
        self.assertEqual(len(fingerprint), 64)
        self.assert_ok(self.run_ps("""
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$review=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
Invoke-OperatorEntryUpgrade $p $unified $review.sha256 $selectedHome | Out-Null
"""))
        upgraded = entry_preview.verify_owned_entry(self.root, bundle, test_shortcuts=links)
        self.assertNotEqual(fingerprint, upgraded)
        config = bundle / 'desktop-entry.json'
        original = config.read_bytes()
        native = json.loads(original)
        native['mode'] = 'native'
        config.write_text(json.dumps(native), encoding='utf8')
        recovered = {'before_sha256': hashlib.sha256(original).hexdigest(),
                     'after_sha256': hashlib.sha256(config.read_bytes()).hexdigest()}
        self.assertEqual(entry_preview.verify_owned_entry(self.root, bundle,
            test_shortcuts=links, recovered_config=recovered), upgraded)
        with self.assertRaises(entry_preview.PreviewError):
            entry_preview.verify_owned_entry(self.root, bundle, test_shortcuts=links)
        with self.assertRaises(entry_preview.PreviewError):
            entry_preview.verify_owned_entry(self.root, bundle, test_shortcuts=links,
                recovered_config={**recovered, 'before_sha256': '0' * 64})
        config.write_bytes(original)
        links[0].write_bytes(b'changed disposable shortcut')
        with self.assertRaisesRegex(entry_preview.PreviewError, 'unified_entry_shortcuts_unverified'):
            entry_preview.verify_owned_entry(self.root, bundle, test_shortcuts=links)

    def test_entry_upgrade_requires_native_marker_and_no_activation_plan(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$blocked=$false;try{Get-OperatorEntryUpgradePlan $p $unified $selectedHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Upgrade allowed without native marker'}
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$wrongHome=Join-Path $p 'wrong-launcher-home';New-Item -ItemType Directory -Path $wrongHome|Out-Null
[IO.File]::WriteAllText((Join-Path $wrongHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$blocked=$false;try{Get-OperatorEntryUpgradePlan $p $unified $wrongHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Upgrade accepted another launcher home'}
New-Item -ItemType Directory -Path (Join-Path $selectedHome 'operator-unified-activation') | Out-Null
$blocked=$false;try{Get-OperatorEntryUpgradePlan $p $unified $selectedHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Upgrade allowed after activation plan'}
if(Test-Path (Join-Path $p '.codex/operator-entry-upgrade')){throw 'Blocked preview wrote upgrade'}
"""))

    def test_changed_desktop_link_adoption_is_separate_and_restorable(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$state=Get-OperatorEntryMigrationState $p
$journal=Join-Path $p '.codex/operator-entry-migration/journal.json';$journalHash=Get-OperatorFingerprint $journal
$desktop=@(Get-OperatorDesktopPaths)[0];$start=@(Get-OperatorDesktopPaths)[1]
$oldAfter=$state.entries[$desktop].after
$shell=New-Object -ComObject WScript.Shell
$changed=$shell.CreateShortcut($desktop);$changed.Description='Reviewed later Desktop description';$changed.Save()
$current=Get-OperatorFingerprint $desktop
if($current -ceq $oldAfter){throw 'Fixture did not change Desktop bytes'}
$identity=Get-OperatorShortcutFileIdentity $desktop
$audit=Join-Path $p '.codex/audit/web-startup-comment-fix-20260919'
New-Item -ItemType Directory -Path $audit -Force|Out-Null
Copy-Item -LiteralPath $desktop -Destination (Join-Path $audit 'desktop-link-at-review.lnk')
$rows=@()
foreach($path in @($desktop,$start)){
  $link=$shell.CreateShortcut($path)
  $rows+=@{path=$path;sha256=(Get-OperatorFingerprint $path);installed_sha256=$state.entries[$path].after;
    target=$link.TargetPath;arguments=$link.Arguments;working_directory=$link.WorkingDirectory;
    icon=$link.IconLocation;window_style=$link.WindowStyle}
}
$rows|ConvertTo-Json -Depth 5|Set-Content (Join-Path $audit 'shortcuts-review.json') -Encoding utf8
[IO.File]::WriteAllText((Join-Path $audit 'report.md'),'Later Desktop bytes retained for separate review.')
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome|Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$wrongHome=Join-Path $p 'wrong-launcher-home';New-Item -ItemType Directory -Path $wrongHome|Out-Null
[IO.File]::WriteAllText((Join-Path $wrongHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$blocked=$false;try{Get-OperatorEntryShortcutAdoptionPlan $p $wrongHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Adoption accepted another launcher home'}
$legacyPath=$state.plan.legacy_executable
$legacyBytes=[IO.File]::ReadAllBytes($legacyPath)
[IO.File]::WriteAllText($legacyPath,'changed old launcher')
$blocked=$false;try{Get-OperatorEntryShortcutAdoptionPlan $p $selectedHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Adoption accepted changed rollback launcher'}
[IO.File]::WriteAllBytes($legacyPath,$legacyBytes)
$review=Get-OperatorEntryShortcutAdoptionPlan $p $selectedHome
if(Test-Path (Join-Path $p '.codex/operator-entry-shortcut-adoption')){throw 'Adoption preview wrote files'}
if($review.summary.current_sha256 -cne $current -or -not $review.summary.archived_copy_matches){throw 'Bad preview summary'}
$replacement=Join-Path $fixtureDesktop 'same-bytes-new-identity.lnk'
[IO.File]::WriteAllBytes($replacement,[IO.File]::ReadAllBytes($desktop))
[IO.File]::Move($replacement,$desktop,$true)
if((Get-OperatorFingerprint $desktop) -cne $current -or
   (Get-OperatorShortcutFileIdentity $desktop) -ceq $identity){throw 'Identity replacement fixture failed'}
$blocked=$false;try{Invoke-OperatorEntryShortcutAdoption $p $selectedHome $review.sha256 -OwnerApprovedShortcutAdoption|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Test-Path (Join-Path $p '.codex/operator-entry-shortcut-adoption'))){
  throw 'Changed identity accepted after preview'
}
$identity=Get-OperatorShortcutFileIdentity $desktop
$review=Get-OperatorEntryShortcutAdoptionPlan $p $selectedHome
$blocked=$false;try{Invoke-OperatorEntryShortcutAdoption $p $selectedHome $review.sha256|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Adoption did not require owner approval'}
Invoke-OperatorEntryShortcutAdoption $p $selectedHome $review.sha256 -OwnerApprovedShortcutAdoption|Out-Null
if((Get-OperatorFingerprint $journal) -cne $journalHash -or
   (Get-OperatorFingerprint $desktop) -cne $current -or
   (Get-OperatorShortcutFileIdentity $desktop) -cne $identity -or
   $state.entries[$desktop].after -cne $oldAfter){throw 'Adoption rewrote entry or baseline'}
$owned=Get-OperatorEntryAdoptionAfter $p (Get-OperatorEntryMigrationState $p) $desktop -CheckCurrent
if($owned -cne $current){throw 'Completed adoption was not verified'}
$archivePath=Join-Path $audit 'desktop-link-at-review.lnk'
$savedArchive=[IO.File]::ReadAllBytes($archivePath)
[IO.File]::WriteAllText($archivePath,'changed historical copy')
$blocked=$false;try{Get-OperatorEntryAdoptionAfter $p (Get-OperatorEntryMigrationState $p) $desktop -CheckCurrent|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Changed historical copy accepted'}
[IO.File]::WriteAllBytes($archivePath,$savedArchive)
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified|Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}}|
  ConvertTo-Json -Depth 5|Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$upgrade=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
Invoke-OperatorEntryUpgrade $p $unified $upgrade.sha256 $selectedHome|Out-Null
$adoptionReceipt=Join-Path $p '.codex/operator-entry-shortcut-adoption/receipt.json'
$savedReceipt=[IO.File]::ReadAllBytes($adoptionReceipt)
[IO.File]::WriteAllText($adoptionReceipt,'{}')
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Get-OperatorEntryMigrationState $p).phase -cne 'installed'){
  throw 'Altered adoption receipt allowed restoration'
}
[IO.File]::WriteAllBytes($adoptionReceipt,$savedReceipt)
Restore-OperatorEntryMigration $p|Out-Null
if((Get-OperatorEntryMigrationState $p).phase -cne 'restored'){throw 'Adopted link could not restore'}
"""))

    def test_incomplete_shortcut_adoption_is_terminal(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$desktop=@(Get-OperatorDesktopPaths)[0]
$original=Get-OperatorFingerprint $desktop
$folder=Join-Path $p '.codex/operator-entry-shortcut-adoption'
New-Item -ItemType Directory -Path $folder|Out-Null
[IO.File]::WriteAllText((Join-Path $folder 'intent.json'),'{}')
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Incomplete adoption allowed restoration'}
$blocked=$false;try{Get-OperatorEntryShortcutAdoptionPlan $p (Join-Path $p 'disposable-home')|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Incomplete adoption retried'}
if((Get-OperatorEntryMigrationState $p).phase -cne 'installed' -or
   (Get-OperatorFingerprint $desktop) -cne $original){throw 'Incomplete adoption changed migration'}
"""))

    def test_interrupted_restore_accepts_only_exact_restored_start_original(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$state=Get-OperatorEntryMigrationState $p
$desktop=@(Get-OperatorDesktopPaths)[0];$start=@(Get-OperatorDesktopPaths)[1]
$shell=New-Object -ComObject WScript.Shell
$changed=$shell.CreateShortcut($desktop);$changed.Description='Later review copy';$changed.Save()
$adopted=Get-OperatorFingerprint $desktop
$audit=Join-Path $p '.codex/audit/web-startup-comment-fix-20260919'
New-Item -ItemType Directory -Path $audit -Force|Out-Null
Copy-Item -LiteralPath $desktop -Destination (Join-Path $audit 'desktop-link-at-review.lnk')
$rows=@()
foreach($path in @($desktop,$start)){
  $link=$shell.CreateShortcut($path)
  $rows+=@{path=$path;sha256=(Get-OperatorFingerprint $path);installed_sha256=$state.entries[$path].after;
    target=$link.TargetPath;arguments=$link.Arguments;working_directory=$link.WorkingDirectory;
    icon=$link.IconLocation;window_style=$link.WindowStyle}
}
$rows|ConvertTo-Json -Depth 5|Set-Content (Join-Path $audit 'shortcuts-review.json') -Encoding utf8
[IO.File]::WriteAllText((Join-Path $audit 'report.md'),'Exact later Desktop bytes require separate review.')
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome|Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$review=Get-OperatorEntryShortcutAdoptionPlan $p $selectedHome
Invoke-OperatorEntryShortcutAdoption $p $selectedHome $review.sha256 -OwnerApprovedShortcutAdoption|Out-Null
$state=Get-OperatorEntryMigrationState $p
$originalHash=$state.entries[$start].before
$original=Join-Path $p ('.codex/operator-entry-migration/originals/'+$originalHash+'.bin')
$state.phase='restoring';Save-OperatorEntryMigrationState $p $state
[IO.File]::WriteAllBytes((Join-Path $p '.codex/operator-desktop-entry/native-only'),[byte[]]@(1))
Write-OperatorAtomicBytes $start ([IO.File]::ReadAllBytes($original))
if((Get-OperatorFingerprint $start) -cne $originalHash -or
   (Get-OperatorFingerprint $desktop) -cne $adopted){throw 'Interrupted restore fixture failed'}
[void](Get-OperatorEntryAdoptionAfter $p (Get-OperatorEntryMigrationState $p) $desktop -CheckCurrent)
[IO.File]::WriteAllText($start,'unrelated later Start edit')
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Get-OperatorFingerprint $desktop) -cne $adopted -or
   (Get-OperatorEntryMigrationState $p).phase -cne 'restoring'){
  throw 'Unrelated Start edit was accepted during resumed restoration'
}
Write-OperatorAtomicBytes $start ([IO.File]::ReadAllBytes($original))
Restore-OperatorEntryMigration $p|Out-Null
if((Get-OperatorEntryMigrationState $p).phase -cne 'restored' -or
   (Get-OperatorFingerprint $start) -cne $originalHash -or
   (Get-OperatorFingerprint $desktop) -cne 'absent'){
  throw 'Exact interrupted restoration could not complete'
}
"""))

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

    def test_entry_only_config_upgrade_retains_original_migration_restore(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$oldState=Get-OperatorEntryMigrationState $p
$originalBuild=$oldState.build['desktop-entry.json']
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$review=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
if(Test-Path (Join-Path $p '.codex/operator-entry-upgrade')){throw 'Upgrade preview wrote files'}
Invoke-OperatorEntryUpgrade $p $unified $review.sha256 $selectedHome | Out-Null
$config=Get-Content (Join-Path $p '.codex/operator-desktop-entry/desktop-entry.json') -Raw | ConvertFrom-Json
if($config.mode -cne 'reviewed_startup' -or
   $config.startup_bundle -ine '.codex/operator-unified-startup'){throw 'Wrong startup selected'}
$state=Get-OperatorEntryMigrationState $p
if($state.phase -cne 'installed' -or $state.build['desktop-entry.json'] -cne $originalBuild -or
   $state.runtime_ownership -cne 'unresolved'){throw 'Migration baseline rewritten'}
$blocked=$false;try{Invoke-OperatorEntryUpgrade $p $unified $review.sha256 $selectedHome | Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Upgrade retried'}
Restore-OperatorEntryMigration $p | Out-Null
if((Get-OperatorEntryMigrationState $p).phase -cne 'restored' -or
   -not(Test-Path (Join-Path $p '.codex/operator-desktop-entry/native-only'))){throw 'Migration restore failed'}
if(Test-Path (Join-Path $p '.codex/operator-installation/ownership.json')){throw 'Runtime ownership fabricated'}
"""))

    def test_post_unified_recovery_restore_requires_exact_retirement_witness(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$upgrade=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
Invoke-OperatorEntryUpgrade $p $unified $upgrade.sha256 $selectedHome | Out-Null
$bundle=Join-Path $p '.codex/operator-desktop-entry'
$configPath=Join-Path $bundle 'desktop-entry.json'
$reviewedHash=Get-OperatorFingerprint $configPath
$native=Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
$native.mode='native'
[IO.File]::WriteAllText($configPath,($native|ConvertTo-Json -Depth 30))
$nativeHash=Get-OperatorFingerprint $configPath
$activation=Join-Path $selectedHome 'operator-unified-activation';New-Item -ItemType Directory -Path $activation|Out-Null
@{schema_version=1;project=$p;home=$selectedHome;startup_bundle=@{path=$unified;
  startup_script_sha256=$workflowHash;
  sync_plan_sha256=(Get-OperatorFingerprint (Join-Path $unified 'startup-sync-plan.json'))}}|
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $activation 'plan.json') -Encoding utf8
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Get-OperatorEntryMigrationState $p).phase -cne 'installed' -or
   (Test-Path (Join-Path $bundle 'native-only'))){throw 'Unwitnessed recovery restored migration'}
function Get-OperatorUnifiedRetirementStatus {param($PlanPath,$WorkflowPath)
  @{status='retired_witnessed';recovery=@{entry_before_sha256=('0'*64);entry_recovered_sha256=$nativeHash}}}
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Wrong retirement before hash accepted'}
function Get-OperatorUnifiedRetirementStatus {param($PlanPath,$WorkflowPath)
  @{status='retired_witnessed';recovery=@{entry_before_sha256=$reviewedHash;entry_recovered_sha256=('0'*64)}}}
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Wrong retirement after hash accepted'}
function Get-OperatorUnifiedRetirementStatus {param($PlanPath,$WorkflowPath)
  if($PlanPath -ine (Join-Path $selectedHome 'operator-unified-activation/plan.json') -or
     $WorkflowPath -ine $unified){throw 'Wrong retirement scope'}
  @{status='retired_witnessed';recovery=@{entry_before_sha256=$reviewedHash;entry_recovered_sha256=$nativeHash}}}
[IO.File]::AppendAllText($configPath,"`n")
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Changed recovered entry accepted'}
[IO.File]::WriteAllText($configPath,($native|ConvertTo-Json -Depth 30))
if((Get-OperatorFingerprint $configPath) -cne $nativeHash){throw 'Fixture native entry changed'}
Restore-OperatorEntryMigration $p|Out-Null
if((Get-OperatorEntryMigrationState $p).phase -cne 'restored' -or
   -not(Test-Path (Join-Path $bundle 'native-only')) -or
   (Test-Path (Join-Path $p '.codex/operator-installation/ownership.json'))){
  throw 'Witnessed native migration restore failed or invented runtime owner'}
"""))

    def test_pair_attachment_follows_old_upgrade_and_uses_new_retirement_baseline(self):
        # The pair module owns its receipt validation. This test isolates its
        # validated attachment boundary while retaining a real old migration,
        # config-only upgrade and every legacy restoration check.
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$upgrade=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
Invoke-OperatorEntryUpgrade $p $unified $upgrade.sha256 $selectedHome | Out-Null
$state=Get-OperatorEntryMigrationState $p
$script:fixtureBefore=Get-OperatorEntryConfigUpgradeBuild $p $state
$journal=Join-Path $p '.codex/operator-entry-migration/journal.json'
$journalHash=Get-OperatorFingerprint $journal
$upgradeFolder=Join-Path $p '.codex/operator-entry-upgrade'
$upgradeReceipt=Join-Path $upgradeFolder 'receipt.json'
$receiptBytes=[IO.File]::ReadAllBytes($upgradeReceipt)
$oldAfterHash=Get-OperatorFingerprint (Join-Path $upgradeFolder 'after.json')
$bundle=Join-Path $p '.codex/operator-desktop-entry'
$configPath=Join-Path $bundle 'desktop-entry.json'
$entryPath=Join-Path $bundle 'operator_desktop_entry.ps1'
[IO.File]::AppendAllText($entryPath,"`n# Separate reviewed pair build fixture.`n")
$newConfig=Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
$newConfig.entry_script_sha256=Get-OperatorFingerprint $entryPath
Write-OperatorAtomicBytes $configPath ([Text.UTF8Encoding]::new($false).GetBytes(($newConfig|ConvertTo-Json -Depth 30)))
$manifestPath=Join-Path $bundle 'launcher-manifest.json'
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
$manifest.entry_script_sha256=$newConfig.entry_script_sha256
Write-OperatorAtomicBytes $manifestPath ([Text.UTF8Encoding]::new($false).GetBytes(($manifest|ConvertTo-Json -Depth 30)))
$pairBaseline=Join-Path $p 'pair-config-after.json'
[IO.File]::WriteAllBytes($pairBaseline,[IO.File]::ReadAllBytes($configPath))
$script:fixtureAfter=@{}
foreach($name in $script:fixtureBefore.Keys){$script:fixtureAfter[$name]=Get-OperatorFingerprint (Join-Path $bundle $name)}
$script:fixturePair=@{before=$script:fixtureBefore;after=$script:fixtureAfter;phase='installed';
  config_after_path=$pairBaseline;codex_home=$selectedHome;startup_bundle=$unified;
  startup_script_sha256=$workflowHash;startup_metadata_sha256=(Get-OperatorFingerprint (Join-Path $unified 'startup-sync-plan.json'));
  origin_sha256=('a'*64);receipt_sha256=('b'*64)}
$script:attachmentCalls=0
$script:changeAttachmentOnRecheck=$false
function Get-OperatorEntryPairAttachment {param($ProjectRoot,$Migration,$BeforeBuild)
  $script:attachmentCalls++
  if($ProjectRoot -ine $p -or $BeforeBuild.Count -ne 5 -or
    @($script:fixtureBefore.Keys|Where-Object {$BeforeBuild[$_] -cne $script:fixtureBefore[$_]}).Count){
    throw 'Pair received an unverified predecessor build'}
  $result=$script:fixturePair.Clone()
  if($script:changeAttachmentOnRecheck -and $script:attachmentCalls -eq 2){$result.receipt_sha256='c'*64}
  return $result
}
$effective=Get-OperatorEntryUpgradeBuild $p $state
if($effective['desktop-entry.json'] -cne $script:fixtureAfter['desktop-entry.json'] -or
   $effective['desktop-entry.json'] -ceq $oldAfterHash){throw 'Pair after build was not selected'}
$script:attachmentCalls=0
[IO.File]::WriteAllText($upgradeReceipt,'{}')
$blocked=$false;try{Get-OperatorEntryUpgradeBuild $p $state|Out-Null}catch{$blocked=$true}
if(-not $blocked -or $script:attachmentCalls -ne 0){throw 'Pair bypassed incomplete old upgrade'}
[IO.File]::WriteAllBytes($upgradeReceipt,$receiptBytes)
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Get-OperatorFingerprint $journal) -cne $journalHash -or
  (Test-Path (Join-Path $bundle 'native-only'))){throw 'Installed pair allowed legacy restoration'}
$script:fixturePair.phase='restored'
$script:attachmentCalls=0;$script:changeAttachmentOnRecheck=$true
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or $script:attachmentCalls -ne 2 -or
  (Get-OperatorFingerprint $journal) -cne $journalHash -or
  (Test-Path (Join-Path $bundle 'native-only'))){throw 'Changed pair proof allowed restoration writes'}
$script:changeAttachmentOnRecheck=$false
$native=$newConfig.Clone();$native.mode='native'
Write-OperatorAtomicBytes $configPath ([Text.UTF8Encoding]::new($false).GetBytes(($native|ConvertTo-Json -Depth 30)))
$nativeBytes=[IO.File]::ReadAllBytes($configPath);$nativeHash=Get-OperatorFingerprint $configPath
$activation=Join-Path $selectedHome 'operator-unified-activation';New-Item -ItemType Directory -Path $activation|Out-Null
$plan=@{schema_version=1;project=$p;home=$selectedHome;startup_bundle=@{path=$unified;
  startup_script_sha256=$workflowHash;sync_plan_sha256=$script:fixturePair.startup_metadata_sha256}}
$planPath=Join-Path $activation 'plan.json'
$plan | ConvertTo-Json -Depth 5 | Set-Content $planPath -Encoding utf8
$script:retirementBefore=$oldAfterHash
function Get-OperatorUnifiedRetirementStatus {param($PlanPath,$WorkflowPath)
  if($PlanPath -ine (Join-Path $selectedHome 'operator-unified-activation/plan.json') -or
    $WorkflowPath -ine $unified){throw 'Wrong pair retirement scope'}
  @{status='retired_witnessed';recovery=@{entry_before_sha256=$script:retirementBefore;entry_recovered_sha256=$nativeHash}}
}
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked -or (Get-OperatorFingerprint $journal) -cne $journalHash){throw 'Old upgrade retirement hash authorized pair restoration'}
$script:retirementBefore=$script:fixtureAfter['desktop-entry.json']
$plan.home=Join-Path $p 'other-home'
$plan | ConvertTo-Json -Depth 5 | Set-Content $planPath -Encoding utf8
$blocked=$false;try{Get-OperatorUnifiedRetiredEntryHash $p $effective|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Wrong native home accepted for pair retirement'}
$plan.home=$selectedHome
$plan | ConvertTo-Json -Depth 5 | Set-Content $planPath -Encoding utf8
[IO.File]::AppendAllText($configPath,"`n")
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Changed recovered pair config accepted'}
[IO.File]::WriteAllBytes($configPath,$nativeBytes)
Restore-OperatorEntryMigration $p|Out-Null
$restored=Get-OperatorEntryMigrationState $p
if($restored.phase -cne 'restored' -or $restored.build['desktop-entry.json'] -cne $state.build['desktop-entry.json'] -or
  (Get-OperatorFingerprint (Join-Path $upgradeFolder 'after.json')) -cne $oldAfterHash -or
  (Get-OperatorFingerprint $upgradeReceipt) -cne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($receiptBytes)).ToLowerInvariant() -or
  (Test-Path (Join-Path $p '.codex/operator-installation/ownership.json'))){throw 'Pair restoration rewrote old ownership evidence'}
"""))

    def test_retirement_verifier_reads_exact_workflow_python(self):
        workflow = self.root / ".codex/operator-unified-startup"
        workflow.mkdir()
        script = cold_start.render_workflow(Path(sys.executable),
            self.root / "disposable-home/operator-unified-activation/plan.json")
        (workflow / "start-codex-with-web.ps1").write_bytes(script)
        self.assert_ok(self.run_ps("""
$workflow=Join-Path $p '.codex/operator-unified-startup'
$planPath=Join-Path $p 'disposable-home/operator-unified-activation/plan.json'
$blocked=$false
try { Get-OperatorUnifiedRetirementStatus $planPath $workflow | Out-Null }
catch { $blocked=$_.Exception.Message -ceq 'Unified retirement is not witnessed.' }
if(-not $blocked){throw 'Saved workflow Python was not used for read-only status'}
"""))
        (workflow / "start-codex-with-web.ps1").write_bytes(script.replace(
            b"Saved Python changed.", b"Different Python hash."))
        self.assert_ok(self.run_ps("""
$workflow=Join-Path $p '.codex/operator-unified-startup'
$planPath=Join-Path $p 'disposable-home/operator-unified-activation/plan.json'
$blocked=$false
try { Get-OperatorUnifiedRetirementStatus $planPath $workflow | Out-Null }
catch { $blocked=$_.Exception.Message -ceq 'Reviewed unified workflow interpreter unavailable.' }
if(-not $blocked){throw 'Changed workflow Python guard accepted'}
"""))

    def test_recovered_native_entry_requires_exact_receipt_before_upgrade(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$configPath=Join-Path $p '.codex/operator-desktop-entry/desktop-entry.json'
$oldBytes=[IO.File]::ReadAllBytes($configPath);$oldHash=Get-OperatorFingerprint $configPath
$native=[Text.UTF8Encoding]::new($false).GetString($oldBytes)|ConvertFrom-Json
$native.mode='native'
[IO.File]::WriteAllBytes($configPath,[Text.UTF8Encoding]::new($false).GetBytes(($native|ConvertTo-Json -Depth 30)))
$newHash=Get-OperatorFingerprint $configPath
$recovery=Join-Path $selectedHome 'operator-route-recovery/synthetic';New-Item -ItemType Directory -Path $recovery -Force|Out-Null
[IO.File]::WriteAllBytes((Join-Path $recovery 'desktop-entry.json.before'),$oldBytes)
$intent=Join-Path $recovery 'intent.json'
@{schema_version=1;purpose='operator_official_route_recovery';files=@(@{name='desktop-entry.json';
  target=$configPath;before_sha256=$oldHash;after_sha256=$newHash})}|ConvertTo-Json -Depth 6|Set-Content $intent -Encoding utf8
@{schema_version=1;completed=@('desktop-entry.json')}|ConvertTo-Json -Depth 3|
  Set-Content (Join-Path $recovery 'completed.json') -Encoding utf8
$blocked=$false;try{Get-OperatorEntryUpgradePlan $p $unified $selectedHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Unreviewed native entry accepted'}
$review=Get-OperatorEntryUpgradePlan $p $unified $selectedHome $intent
Invoke-OperatorEntryUpgrade $p $unified $review.sha256 $selectedHome $intent|Out-Null
$receiptPath=Join-Path $recovery 'completed.json';$saved=[IO.File]::ReadAllBytes($receiptPath)
[IO.File]::WriteAllText($receiptPath,'{}')
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Changed native recovery evidence accepted'}
[IO.File]::WriteAllBytes($receiptPath,$saved)
Restore-OperatorEntryMigration $p|Out-Null
"""))

    def test_uncertain_entry_upgrade_blocks_restore_and_never_retries(self):
        self.assert_ok(self.run_ps("""
$migration=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $migration.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified | Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}} |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$review=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
$folder=Join-Path $p '.codex/operator-entry-upgrade';New-Item -ItemType Directory -Path $folder | Out-Null
[IO.File]::WriteAllText((Join-Path $folder 'intent.json'),'{}')
$blocked=$false;try{Invoke-OperatorEntryUpgrade $p $unified $review.sha256 $selectedHome|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Uncertain upgrade retried'}
$blocked=$false;try{Restore-OperatorEntryMigration $p|Out-Null}catch{$blocked=$true}
if(-not $blocked){throw 'Uncertain upgrade allowed restoration'}
if((Get-OperatorEntryMigrationState $p).phase -cne 'installed' -or
   (Get-OperatorFingerprint (Join-Path $p '.codex/operator-desktop-entry/desktop-entry.json')) -cne
     (Get-OperatorEntryMigrationState $p).build['desktop-entry.json']){throw 'Uncertain upgrade changed entry'}
"""))
