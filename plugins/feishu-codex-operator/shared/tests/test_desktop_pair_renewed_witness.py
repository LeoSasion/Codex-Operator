"""Legacy selector and boundary checks; native verifier replies are mocked.

Real renewal journals/file identities are covered by test_unified_workflow_renew.
These tests never use the current user's Desktop or configuration.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class RenewedWitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-renewed-witness-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root/'project'
        self.home = self.root/'home'
        self.bundle = self.project/'.codex/operator-unified-startup'
        self.evidence = self.home/'operator-unified-workflow-renewal'/('generation-'+'a'*32)/'evidence'
        self.bundle.mkdir(parents=True)
        self.evidence.mkdir(parents=True)
        self.reply = self.root/'reply.json'
        self.calls = self.root/'calls.jsonl'
        self.stub = self.root/'mock-interpreter.ps1'
        # A script mock preserves multiline -c arguments without cmd.exe parsing.
        # Its explicit LASTEXITCODE is the native process boundary being mocked.
        self.stub.write_text('''$value=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'reply.json') -Raw | ConvertFrom-Json -AsHashtable
$renew=$args -ccontains '-c'
$call=@{renew=$renew;arguments=@($args)} | ConvertTo-Json -Compress
[IO.File]::AppendAllText((Join-Path $PSScriptRoot 'calls.jsonl'),$call+"`n")
$fixtureStage=if($renew){'renew'}else{'archive'}
if($value.mutate -ceq $fixtureStage){[IO.File]::WriteAllText($value.script,'changed during verification')}
if($value.fail -ceq $fixtureStage){$global:LASTEXITCODE=1;return}
$global:LASTEXITCODE=0
$value[$fixtureStage] | ConvertTo-Json -Compress
''', encoding='utf8')
        old_script = ("$python = "+quote(self.stub)+"\n"
            "if ((Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant() -cne '"+
            sha(self.stub.read_bytes())+"') { throw 'Saved Python changed.' }\n").encode()
        old_metadata = b'{"retained":"original"}'
        (self.evidence/'start-codex-with-web.ps1').write_bytes(old_script)
        (self.evidence/'startup-sync-plan.json').write_bytes(old_metadata)
        self.script = self.bundle/'start-codex-with-web.ps1'
        self.metadata = self.bundle/'startup-sync-plan.json'
        self.script.write_bytes(b'# reviewed new workflow')
        self.metadata.write_bytes(b'{"current":"renewed"}')
        self.workflow = {'path':str(self.bundle),'startup_script_sha256':sha(old_script),
            'startup_metadata_sha256':sha(old_metadata)}
        self.workflow_path = self.root/'workflow.json'
        self.workflow_path.write_text(json.dumps(self.workflow), encoding='utf8')
        self.values = {'renew':{'status':'retained_workflow_witnessed','path':str(self.evidence)},
            'archive':{'status':'archived_retired_entry_witnessed',
                'recovery':{'entry_before_sha256':'1'*64,'entry_recovered_sha256':'2'*64},
                'startup_bundle':{'path':str(self.bundle),'startup_script_sha256':sha(self.script.read_bytes()),
                    'sync_plan_sha256':sha(self.metadata.read_bytes())},
                'archive_witness_sha256':'3'*64,'retirement_intent_sha256':'4'*64},
            'script':str(self.script)}

    def invoke(self, historical=False):
        self.reply.write_text(json.dumps(self.values), encoding='utf8')
        code = f"""$ErrorActionPreference='Stop'
$module=Import-Module {quote(ROOT/'scripts/operator_desktop_pair_legacy.psm1')} -PassThru -DisableNameChecking
$workflow=Get-Content -LiteralPath {quote(self.workflow_path)} -Raw | ConvertFrom-Json -AsHashtable
& $module {{param($P,$H,$W)
 Get-LegacyArchivedEntryWitness $P $H '{'1'*64}' '{'2'*64}' $W {'-Historical' if historical else ''} | ConvertTo-Json -Compress
}} {quote(self.project)} {quote(self.home)} $workflow
"""
        return subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',code],
            capture_output=True,text=True,encoding='utf8',timeout=30)

    def assert_rejected(self, code, count):
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(code, result.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()) if self.calls.exists() else 0, count)

    def test_retained_selection_keeps_original_bytes_and_historical_argument(self):
        before = {p:p.read_bytes() for folder in (self.project,self.home)
            for p in folder.rglob('*') if p.is_file()}
        result = self.invoke(historical=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['contract'],'archived_unified_entry_recovery_v1')
        self.assertEqual({p:p.read_bytes() for p in before},before)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([row['renew'] for row in calls],[True,False])
        self.assertIn('--historical-entry',calls[-1]['arguments'])

    def test_original_workflow_does_not_need_renewal(self):
        self.script.write_bytes((self.evidence/self.script.name).read_bytes())
        self.metadata.write_bytes((self.evidence/self.metadata.name).read_bytes())
        self.values['archive']['startup_bundle']['startup_script_sha256']=sha(self.script.read_bytes())
        self.values['archive']['startup_bundle']['sync_plan_sha256']=sha(self.metadata.read_bytes())
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([json.loads(line)['renew'] for line in self.calls.read_text().splitlines()],[False])

    def test_changed_retained_original_cannot_select_interpreter(self):
        (self.evidence/self.script.name).write_bytes(b'changed original')
        self.assert_rejected('legacy_pair_recovery_workflow_changed',0)

    def test_missing_renewal_cannot_accept_changed_workflow(self):
        shutil.rmtree(self.home/'operator-unified-workflow-renewal')
        self.assert_rejected('legacy_pair_recovery_workflow_changed',0)

    def test_ambiguous_retained_originals_cannot_select_interpreter(self):
        shutil.copytree(self.evidence,self.evidence.parent.parent/('generation-'+'b'*32)/'evidence')
        self.assert_rejected('legacy_pair_recovery_workflow_changed',0)

    def test_verifier_failure_cannot_bypass_retained_chain(self):
        self.values['fail']='renew'
        self.assert_rejected('legacy_pair_retained_workflow_not_witnessed',1)

    def test_wrong_verified_retained_path_rejected(self):
        self.values['renew']['path']=str(self.bundle)
        self.assert_rejected('legacy_pair_retained_workflow_not_witnessed',1)

    def test_current_change_during_renewal_stops_archive_verification(self):
        self.values['mutate']='renew'
        self.assert_rejected('legacy_pair_retained_workflow_not_witnessed',1)

    def test_current_change_during_archive_rejects_witness(self):
        self.values['mutate']='archive'
        self.assert_rejected('legacy_pair_archived_recovery_not_witnessed',2)

    def test_archive_recovery_digest_mismatch_rejected(self):
        self.values['archive']['recovery']['entry_recovered_sha256']='9'*64
        self.assert_rejected('legacy_pair_archived_recovery_not_witnessed',2)

    def test_retained_interpreter_change_rejected_before_execution(self):
        self.stub.write_bytes(b'changed interpreter')
        self.assert_rejected('legacy_pair_recovery_interpreter_changed',0)


if __name__ == '__main__':
    unittest.main()
