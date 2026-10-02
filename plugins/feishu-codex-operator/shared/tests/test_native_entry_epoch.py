"""A new recovery epoch tolerates only the exact later CUA pipe leaf."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import test_direct_entry as direct_fixture

SCRIPTS=Path(__file__).resolve().parents[2]/'scripts'
PWSH=shutil.which('pwsh')

def q(value): return "'"+str(value).replace("'","''")+"'"

@unittest.skipUnless(os.name=='nt' and PWSH, 'Windows recovery required')
class NativeEntryEpochTests(unittest.TestCase):
    def setUp(self):
        self.fixture=direct_fixture.DirectEntryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        f.before += b'\r\n[mcp_servers.node_repl.env]\r\nSKY_CUA_NATIVE_PIPE_DIRECTORY = "old-pipe"\r\n'
        f.config.write_bytes(f.before)
        f.helper.write_bytes((SCRIPTS/'restore-codex-official-route.ps1').read_bytes())
        review=f.prepare(); f.activate(review)
        self.pointer,self.cycle=f.active()
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',str(f.helper),
            '-CodexHome',str(f.home),'-ProjectRoot',str(f.project),'-Apply','-Json'],
            capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'completed')
        self.receipt=json.loads((self.cycle/'recovered.json').read_bytes())
        self.backup=Path(self.receipt['recovery_backup'])

    def epoch(self):
        f=self.fixture
        driver=f.root/'epoch.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n"
            f". {q(f.helper)} -Library\n. {q(SCRIPTS/'operator_native_entry.ps1')} -Library\n"
            f"$epoch=Get-OperatorNativeRecoveryEpoch {q(f.home)}\n"
            "@{verified=($null -ne $epoch);epoch=$(if($null -ne $epoch){$epoch.ToString('o')}else{$null})}|ConvertTo-Json -Compress\n",
            encoding='utf8')
        result=subprocess.run([PWSH,'-NoProfile','-File',str(driver)],capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_completed_direct_recovery_has_native_epoch(self):
        self.assertTrue(self.epoch()['verified'])
        self.assertEqual((self.backup/'config.toml.after').read_bytes(),self.fixture.before)

    def test_only_cua_pipe_change_is_allowed(self):
        f=self.fixture
        f.config.write_bytes(f.before.replace(b'"old-pipe"',b'"new-pipe"'))
        self.assertTrue(self.epoch()['verified'])
        f.config.write_bytes(f.config.read_bytes().replace(b'shell_tool=true',b'shell_tool=false'))
        self.assertFalse(self.epoch()['verified'])

    def test_changed_epoch_or_retained_after_snapshot_is_rejected(self):
        (self.backup/'config.toml.after').write_bytes(self.fixture.before+b'# changed\n')
        self.assertFalse(self.epoch()['verified'])

    def test_absent_legacy_epoch_is_not_inferred_from_dates(self):
        path=self.backup/'completed.json'
        value=json.loads(path.read_bytes()); del value['native_epoch']
        path.write_text(json.dumps(value),encoding='utf8')
        self.assertFalse(self.epoch()['verified'])

    def test_isolated_native_activation_never_runs_legacy_recovery_or_process_gates(self):
        f=self.fixture
        driver=f.root/'isolated-native.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n"
            f". {q(SCRIPTS/'operator_native_entry.ps1')} -Library\n"
            f"function Get-OperatorNativeDefaultHome {{return {q(f.home)}}}\n"
            "function Get-OperatorPackagedApplication {return @{fixture=$true}}\n"
            "function Invoke-OfficialRouteRecovery {throw 'legacy recovery must not run'}\n"
            "function Get-CimInstance {throw 'unrelated running Desktop must not be blocked'}\n"
            "$script:launches=0\nfunction Open-OperatorPackagedApplication {$script:launches++}\n"
            f"$preview=Invoke-OperatorNativeEntryChecked {q(f.project)} {q(f.home)} -InspectOnly -ActivationMode registered_application_v1\n"
            f"$opened=Invoke-OperatorNativeEntryChecked {q(f.project)} {q(f.home)} -ActivationMode registered_application_v1\n"
            "@{preview=$preview.status;opened=$opened.status;launches=$script:launches}|ConvertTo-Json -Compress\n",
            encoding='utf8')
        before=f.config.read_bytes()
        result=subprocess.run([PWSH,'-NoProfile','-File',str(driver)],capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'preview':'ready','opened':'launch_requested','launches':1})
        self.assertEqual(f.config.read_bytes(),before)

    def test_running_native_guard_uses_epoch_instead_of_later_pipe_mtime(self):
        f=self.fixture
        f.config.write_bytes(f.before.replace(b'"old-pipe"',b'"later-pipe"'))
        driver=f.root/'guard.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n"
            f". {q(f.helper)} -Library\n. {q(SCRIPTS/'operator_native_entry.ps1')} -Library\n"
            f"function Get-OperatorNativeDefaultHome {{return {q(f.home)}}}\n"
            "function Get-OperatorPackagedApplication {return @{fixture=$true}}\n"
            "function Open-OperatorPackagedApplication {throw 'check-only must not launch'}\n"
            f"$epoch=Get-OperatorNativeRecoveryEpoch {q(f.home)}\n"
            f"[IO.File]::SetLastWriteTimeUtc({q(f.config)},$epoch.AddSeconds(10))\n"
            "$script:birth=$epoch.AddSeconds(1)\n"
            "function Get-CimInstance {param($ClassName,$Filter) return @([pscustomobject]@{CreationDate=$script:birth})}\n"
            f"$fresh=Invoke-OperatorNativeEntryChecked {q(f.project)} {q(f.home)} -InspectOnly\n"
            "$script:birth=$epoch.AddSeconds(-1)\n"
            f"$old=Invoke-OperatorNativeEntryChecked {q(f.project)} {q(f.home)} -InspectOnly\n"
            "$script:birth=$null\n"
            f"$unknown=Invoke-OperatorNativeEntryChecked {q(f.project)} {q(f.home)} -InspectOnly\n"
            "@{fresh=$fresh.status;old=$old.status;unknown=$unknown.status}|ConvertTo-Json -Compress\n",
            encoding='utf8')
        before=f.config.read_bytes()
        result=subprocess.run([PWSH,'-NoProfile','-File',str(driver)],capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'fresh':'ready','old':'normal_exit_required','unknown':'normal_exit_required'})
        self.assertEqual(f.config.read_bytes(),before)

if __name__=='__main__': unittest.main()
