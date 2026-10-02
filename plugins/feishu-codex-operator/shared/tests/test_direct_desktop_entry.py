"""Disposable picker boundaries; no Desktop, real profile or model request."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
PWSH = shutil.which('pwsh')

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def q(value):
    return "'" + str(value).replace("'", "''") + "'"

@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows PowerShell required')
class DirectDesktopEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-direct-picker-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir()
        self.scripts = self.root / 'plugins/feishu-codex-operator/scripts'; self.scripts.mkdir(parents=True)
        self.entry = self.scripts / 'operator_desktop_entry.ps1'
        shutil.copyfile(SCRIPTS / self.entry.name, self.entry)
        self.controller = self.scripts / 'operator_direct_entry.py'
        self.controller.write_bytes(b'# fixture only, never executed\n')
        self.helper = self.root / 'native-helper.ps1'
        self.helper.write_text("param([switch]$Library)\nfunction Invoke-OfficialRouteRecovery {param($H,$P,$Commit)\n"
            f"Add-Content -LiteralPath {q(self.root/'recover-count')} -Value 'recover'\n"
            "return @{status='completed';warnings=@();config_changed=$false}}\n", encoding='utf-8')
        self.folder = self.root / '.codex/operator-direct-startup'
        self.plan = self.folder / ('plans/' + 'a'*32 + '/plan.json')
        self.plan.parent.mkdir(parents=True)
        profile_value={'schema_version':1,'contract':'operator_direct_entry_plan_v1',
            'project':str(self.root),'home':str(self.home),'profile':'operator-local-fixture','display_name':'Local fixture',
            'python':{'path':sys.executable,'sha256':sha(Path(sys.executable).read_bytes())},
            'native_helper':{'path':str(self.helper),'sha256':sha(self.helper.read_bytes())},
            'entry_script':{'path':str(self.entry),'sha256':sha(self.entry.read_bytes())}}
        self.plan.write_text(json.dumps(profile_value),encoding='utf8')
        self.index = self.folder / 'direct-entry-plan.json'
        self.value = {'schema_version': 1, 'contract': 'direct_profile_picker_v1',
            'project': str(self.root), 'home': str(self.home),
            'python': sys.executable, 'python_sha256': sha(Path(sys.executable).read_bytes()),
            'native_helper': str(self.helper), 'native_helper_sha256': sha(self.helper.read_bytes()),
            'controller': str(self.controller), 'controller_sha256': sha(self.controller.read_bytes()),
            'entry_script_sha256': sha(self.entry.read_bytes()),
            'profiles': [{'profile': 'operator-local-fixture', 'display_name': 'Local fixture',
                'plan': str(self.plan), 'plan_sha256': sha(self.plan.read_bytes())}]}
        self.save()
        self.package=self.root/'fake-package';self.package.mkdir()
        (self.package/'ChatGPT.exe').write_bytes(b'fixture package')

    def save(self):
        self.index.write_text(json.dumps(self.value), encoding='utf-8')
        self.index_sha = sha(self.index.read_bytes())

    def run_picker(self, *, select=1, inspect=False, running_call=0, failed=False, extra=''):
        driver = self.root / 'driver.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
            f". {q(self.entry)} -Library\n"
            f"$plan=Get-OperatorDirectPicker {q(self.root)} {q(self.home)} {q(self.index)} {q(self.index_sha)}\n"
            "$script:observations=0\nfunction Get-CimInstance {param($ClassName,$Filter)"
            f"$script:observations++;if($script:observations -eq {running_call}){{return @([pscustomobject]@{{ProcessId=1;ExecutablePath={q(self.package/'ChatGPT.exe')}}})}};return @()}}\n"
            f"function Select-OperatorDirectProfile {{param($Plan) return {select}}}\n"
            f"function Get-OperatorPackagedApplication {{return @{{executable={q(self.package/'ChatGPT.exe')}}}}}\n"
            f"function New-OperatorDirectLaunchIntent {{param($Plan,$Row,$PickerSha256,$Applied,$Application) return @{{directory={q(self.root)};sha256=('c'*64)}}}}\n"
            "function Open-OperatorPackagedApplication {param($Application)"
            f"Add-Content -LiteralPath {q(self.root/'open-count')} -Value 'open'}}\n"
            "function Invoke-OperatorDirectController {param($Plan,$Row,$Action,$CurrentConfigSha256)"
            f"Add-Content -LiteralPath {q(self.root/'controller-count')} -Value $Action;"
            + ("if($Action -ceq 'activate'){throw 'fixed_fixture_activation_failure'};" if failed else '') +
            "if($Action -ceq 'preview'){return @{status='preview';profile=$Row.profile;plan_sha256=$Row.plan_sha256;current_config_sha256=('b'*64);model_requests=0}};"
            "if($CurrentConfigSha256 -cne ('b'*64)){throw 'wrong_snapshot'};return @{status='config_applied';configuration_changed=$true;model_requests=0}}\n"
            + extra + "\n"
            f"$result=Invoke-OperatorDirectPicker $plan {q(self.index)} {q(self.index_sha)} (Get-OperatorPackagedApplication)"
            + (' -InspectOnly' if inspect else '') + "\n$result|ConvertTo-Json -Compress\n",
            encoding='utf-8')
        return subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(driver)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)

    def assert_no_actions(self):
        for name in ('open-count', 'controller-count', 'recover-count'):
            self.assertFalse((self.root / name).exists(), name)

    def test_check_only_has_no_choice_recovery_activation_or_launch(self):
        result = self.run_picker(inspect=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'], 'choose_provider')
        self.assert_no_actions()

    def test_explicit_custom_choice_recovers_then_activates_once_and_opens(self):
        result = self.run_picker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'launch_requested')
        self.assertEqual((self.root/'controller-count').read_text(encoding='utf-8-sig').splitlines(), ['preview', 'activate'])
        self.assertEqual((self.root/'recover-count').read_text(encoding='utf-8-sig').splitlines(), ['recover'])
        self.assertEqual((self.root/'open-count').read_text(encoding='utf-8-sig').splitlines(), ['open'])

    def test_cancel_does_not_recover_or_write(self):
        result = self.run_picker(select=-1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'cancelled')
        self.assert_no_actions()

    def test_native_choice_needs_no_controller_request(self):
        result = self.run_picker(select=0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root/'controller-count').exists())
        self.assertEqual(json.loads(result.stdout)['configuration_changed'], False)

    def test_running_app_only_opens_existing_without_choice(self):
        result = self.run_picker(running_call=1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'opened_existing')
        self.assertFalse((self.root/'recover-count').exists())
        self.assertFalse((self.root/'controller-count').exists())

    def test_app_appearing_after_choice_stops_before_recovery(self):
        result = self.run_picker(running_call=2)
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_actions()

    def test_unidentified_other_chatgpt_process_is_not_open_existing(self):
        result=self.run_picker(extra="function Get-CimInstance {return @([pscustomobject]@{ProcessId=1;ExecutablePath=$null})}")
        self.assertNotEqual(result.returncode,0)
        self.assert_no_actions()

    def test_failed_activation_is_not_retried_or_launched(self):
        result = self.run_picker(failed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'open-count').exists())
        self.assertEqual((self.root/'controller-count').read_text(encoding='utf-8-sig').splitlines(), ['preview', 'activate'])

    def test_changed_plan_or_helper_rejects_before_actions(self):
        for path in (self.plan, self.helper):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b'changed')
                result = self.run_picker()
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_actions()
            path.write_bytes(original)

    def test_duplicate_profile_and_control_label_are_rejected(self):
        original = json.loads(json.dumps(self.value))
        for invalid in ('duplicate', 'label'):
            with self.subTest(invalid=invalid):
                self.value = json.loads(json.dumps(original))
                if invalid == 'duplicate': self.value['profiles'] *= 2
                else: self.value['profiles'][0]['display_name'] = 'unsafe\nlabel'
                self.save()
                result = self.run_picker()
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_actions()

    def test_launch_intent_is_retained_once_and_never_replayed(self):
        cycle=self.home/'operator-direct-entry/cycles'/('e'*32);cycle.mkdir(parents=True)
        retained={name:(self.plan.read_bytes() if name=='plan.json' else ('fixture '+name).encode())
            for name in ('config-before.bin','config-candidate.bin','plan.json','profile.json','projection.json')}
        for name,raw in retained.items(): (cycle/name).write_bytes(raw)
        (self.home/'config.toml').write_bytes(retained['config-candidate.bin'])
        intent={'contract':'operator_direct_entry_cycle_v1','cycle':cycle.name,'home':str(self.home),
            'project':str(self.root),'plan_sha256':sha(self.plan.read_bytes()),'native_helper_sha256':self.value['native_helper_sha256'],
            'files':{name:sha(raw) for name,raw in retained.items()}}
        raw=json.dumps(intent).encode();(cycle/'intent.json').write_bytes(raw)
        transaction=cycle/('.operator-config-transaction-'+'f'*32);transaction.mkdir()
        (transaction/'verified.json').write_text(json.dumps({'status':'applied_witnessed'}),encoding='utf8')
        (transaction/'intent.json').write_text(json.dumps({'target':str(self.home/'config.toml'),
            'expected_sha256':intent['files']['config-before.bin'],'candidate_sha256':intent['files']['config-candidate.bin']}),encoding='utf8')
        (cycle/'applied.json').write_text(json.dumps({'schema_version':1,'contract':'operator_direct_entry_applied_v1',
            'cycle':cycle.name,'intent_sha256':sha(raw),'status':'applied','reason':'applied_witnessed','transaction':str(transaction)}),encoding='utf8')
        (cycle.parent.parent/'active.json').write_text(json.dumps({'schema_version':1,
            'contract':'operator_direct_entry_active_v1','cycle':cycle.name,'intent_sha256':sha(raw)}),encoding='utf8')
        app=self.root/'app';app.mkdir();(app/'ChatGPT.exe').write_bytes(b'fixture package');(app/'AppxManifest.xml').write_bytes(b'fixture manifest')
        driver=self.root/'launch.ps1'
        driver.write_text("$ErrorActionPreference='Stop'\n"
            f". {q(self.entry)} -Library\n$plan=Get-OperatorDirectPicker {q(self.root)} {q(self.home)} {q(self.index)} {q(self.index_sha)}\n"
            f"$application=@{{aumid='OpenAI.Codex_fixture!App';executable={q(app/'ChatGPT.exe')};root={q(app)}}}\n"
            f"$launch=New-OperatorDirectLaunchIntent $plan $plan.profiles[0] {q(self.index_sha)} @{{cycle={q(cycle.name)}}} $application\n"
            "Write-OperatorDirectLaunchResult $launch 'shell_failed'\n"
            f"try {{New-OperatorDirectLaunchIntent $plan $plan.profiles[0] {q(self.index_sha)} @{{cycle={q(cycle.name)}}} $application|Out-Null;exit 2}} catch {{}}\n",
            encoding='utf8')
        result=subprocess.run([PWSH,'-NoProfile','-File',str(driver)],capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        outcome=json.loads((cycle/'launch-result.json').read_bytes())
        self.assertEqual(outcome['outcome'],'shell_failed')
        self.assertEqual(outcome['desktop_acceptance'],'unverified')
        self.assertEqual(outcome['launch_intent_sha256'],sha((cycle/'launch-intent.json').read_bytes()))

if __name__ == '__main__':
    unittest.main()
