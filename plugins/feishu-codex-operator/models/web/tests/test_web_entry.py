"""Project Web entry using a real private manager, never a browser or account."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = _OPERATOR_PLUGIN_ROOT
PWSH = shutil.which('pwsh')


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows PowerShell entry')
class WebEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-web-entry-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = self.root / '.codex/operator-web-service'
        self.settings = self.root / 'existing-settings.json'
        browser = self.root / 'browser'; browser.mkdir()
        self.settings.write_text(json.dumps({'electron':str(Path(sys.executable).resolve()),
            'profile_directory':str(browser), 'session_partition':'persist:fixture'}))

    def run_entry(self, action, *arguments, facade=False, as_json=True):
        entry = 'feishu-codex-operator.ps1' if facade else 'operator_web_entry.ps1'
        command = [PWSH,'-NoLogo','-NoProfile','-File',str(ROOT/'scripts'/entry)]
        command += ['web',action] if facade else ['-Action',action]
        command += ['-ProjectRoot',str(self.root),*map(str,arguments)]
        if as_json: command += ['-Json']
        return subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20)

    def configure(self, *, facade=False):
        result = self.run_entry('configure','-WebSettings' if facade else '-Settings',self.settings,
            '-PythonExecutable',Path(sys.executable).resolve(),facade=facade)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def test_unconfigured_status_is_read_only_and_plain_summary_is_available(self):
        before = sorted(self.root.rglob('*'))
        result = self.run_entry('status',facade=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'not_configured')
        result = self.run_entry('status',as_json=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('尚未保存',result.stdout)
        self.assertEqual(sorted(self.root.rglob('*')),before)

    def test_hidden_direct_entry_decodes_helper_json_as_utf8_after_legacy_codepage(self):
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        wrapper = self.root / 'hidden-direct-entry.ps1'
        wrapper.write_text('''
[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(936)
$OutputEncoding = [Console]::OutputEncoding
& ENTRY -Action configure -ProjectRoot PROJECT -Settings SETTINGS -PythonExecutable PYTHON -Json
exit $LASTEXITCODE
'''.replace('ENTRY', quote(ROOT/'scripts/operator_web_entry.ps1'))
            .replace('PROJECT', quote(self.root)).replace('SETTINGS', quote(self.settings))
            .replace('PYTHON', quote(Path(sys.executable).resolve())), encoding='utf-8')
        original = self.settings.read_bytes()
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(wrapper)],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(result.stdout.isascii())
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'configured')
        self.assertEqual(report['summary'], '已保存现有配置引用；以后沿用该入口，无需重复填写固定连接或密钥。')
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertFalse((self.profile/'current.json').exists())
        self.assertEqual(list((self.profile/'instances').iterdir()), [])

    def test_facade_saves_once_and_daily_status_needs_no_python_or_settings(self):
        self.assertEqual(self.configure(facade=True)['status'],'configured')
        original=(self.profile/'profile.json').read_bytes()
        result=self.run_entry('status',facade=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['status'],'configured')
        self.assertTrue(report['configuration_current'])
        self.assertNotIn(str(self.settings),result.stdout)
        self.assertNotIn('token',result.stdout)
        self.assertEqual((self.profile/'profile.json').read_bytes(),original)
        self.assertTrue(self.configure(facade=True)['reused'])
        self.assertFalse((self.profile/'current.json').exists())

    def test_changed_interpreter_identity_rejected_without_launch_or_private_output(self):
        self.configure()
        path=self.profile/'profile.json';value=json.loads(path.read_bytes())
        value['runtime']['python_sha256']='a'*64
        path.write_text(json.dumps(value))
        result=self.run_entry('status')
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['code'],'web_entry_unavailable')
        self.assertEqual(json.loads(result.stdout)['reason'],'web_entry_python_changed')
        self.assertNotIn(str(Path(sys.executable).resolve()),result.stdout+result.stderr)
        self.assertFalse((self.profile/'current.json').exists())

    def test_profile_from_other_source_cannot_select_executable(self):
        self.configure()
        path=self.profile/'profile.json';value=json.loads(path.read_bytes())
        value['runtime']['source_root']=str(self.root/'other-source')
        value['runtime']['python']=str(self.root/'private-unknown.exe')
        path.write_text(json.dumps(value))
        result=self.run_entry('start')
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['code'],'web_entry_unavailable')
        self.assertEqual(json.loads(result.stdout)['reason'],'web_entry_runtime_mismatch')
        self.assertNotIn('private-unknown',result.stdout+result.stderr)
        self.assertFalse((self.profile/'current.json').exists())

    def test_malformed_or_nonfile_profile_is_reviewed_without_setup_or_launch(self):
        self.profile.mkdir(parents=True)
        path = self.profile/'profile.json'
        for content in ('{"private":"PRIVATE",', '[]', '{}'):
            path.write_text(content, encoding='utf8')
            result = self.run_entry('status', facade=True)
            report = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(report['reason'], 'web_entry_profile_invalid')
            self.assertEqual(report['profile_state'], 'present')
            self.assertNotIn('PRIVATE', result.stdout+result.stderr)
            self.assertEqual(path.read_text(encoding='utf8'), content)
        path.unlink(); path.mkdir()
        report = json.loads(self.run_entry('status').stdout)
        self.assertEqual(report['reason'], 'web_entry_profile_invalid')
        self.assertNotEqual(report['status'], 'not_configured')
        self.assertEqual(list(self.profile.iterdir()), [path])

    def test_denied_profile_read_is_distinct_from_error_text_and_preserves_config(self):
        self.configure()
        profile_file = self.profile/'profile.json'
        original = profile_file.read_bytes()
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        for exception, reason in [('UnauthorizedAccessException', 'web_entry_access_denied'),
                ('InvalidOperationException', 'web_entry_profile_invalid')]:
            with self.subTest(exception=exception):
                # Fail only this child process's profile read; no ACL changes on the host.
                wrapper = self.root/'read-failure.ps1'
                wrapper.write_text(r'''
function Get-Content {
    [CmdletBinding()]
    param([string]$LiteralPath,[switch]$Raw,[string]$Encoding)
    if ([IO.Path]::GetFullPath($LiteralPath) -eq PROFILE) {
        throw [EXCEPTION]::new('PRIVATE Access denied token=not-for-output')
    }
    Microsoft.PowerShell.Management\Get-Content @PSBoundParameters
}
& ENTRY -Action status -ProjectRoot PROJECT -Json
exit $LASTEXITCODE
'''.replace('PROFILE', quote(profile_file)).replace('EXCEPTION', exception)
                    .replace('ENTRY', quote(ROOT/'scripts/operator_web_entry.ps1'))
                    .replace('PROJECT', quote(self.root)), encoding='utf8')
                result = subprocess.run([PWSH, '-NoProfile', '-File', str(wrapper)],
                    capture_output=True, encoding='utf8', timeout=20)
                report = json.loads(result.stdout)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(report['reason'], reason)
                self.assertEqual(report['stage'], 'profile')
                self.assertEqual(report['profile_state'], 'present')
                self.assertNotIn('PRIVATE', result.stdout+result.stderr)
                self.assertNotIn(str(self.root), result.stdout+result.stderr)
                self.assertTrue(result.stdout.isascii())
                self.assertEqual(profile_file.read_bytes(), original)
                self.assertFalse((self.profile/'current.json').exists())

    def test_missing_saved_python_does_not_select_another_interpreter(self):
        self.configure()
        path = self.profile/'profile.json'
        value = json.loads(path.read_bytes())
        value['runtime']['python'] = str(self.root/'PRIVATE-python.exe')
        path.write_text(json.dumps(value), encoding='utf8')
        original = path.read_bytes()
        report = json.loads(self.run_entry('status', facade=True).stdout)
        self.assertEqual(report['reason'], 'web_entry_python_unavailable')
        self.assertEqual(report['stage'], 'python')
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.profile/'current.json').exists())

    def test_explicit_configure_reuses_saved_settings_without_rewriting_or_launching(self):
        self.configure()
        before = {str(p.relative_to(self.profile)): p.read_bytes()
            for p in self.profile.rglob('*') if p.is_file()}
        for _ in range(2):
            result = self.run_entry('configure', facade=True)
            report = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(report['status'], 'configured')
            self.assertTrue(report['reused'])
            self.assertNotIn(str(self.settings), result.stdout+result.stderr)
            self.assertEqual(before, {str(p.relative_to(self.profile)): p.read_bytes()
                for p in self.profile.rglob('*') if p.is_file()})
            self.assertFalse((self.profile/'current.json').exists())

    def test_saved_configure_cannot_adopt_changed_settings(self):
        self.configure()
        saved_profile = (self.profile/'profile.json').read_bytes()
        settings = json.loads(self.settings.read_bytes())
        settings['session_partition'] = 'persist:changed'
        self.settings.write_text(json.dumps(settings), encoding='utf8')
        result = self.run_entry('configure', facade=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['reason'], 'web_entry_settings_changed')
        self.assertEqual((self.profile/'profile.json').read_bytes(), saved_profile)
        self.assertFalse((self.profile/'current.json').exists())
        self.assertEqual(list((self.profile/'history').iterdir()), [])

    def test_first_configure_still_requires_settings_without_guessing(self):
        result = self.run_entry('configure', facade=True)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['reason'], 'web_entry_settings_required')
        self.assertFalse(self.profile.exists())

    def test_saved_configure_is_readonly_even_if_runtime_registration_changed(self):
        self.configure()
        path = self.profile/'profile.json'
        value = json.loads(path.read_bytes())
        value['runtime']['python_version'] = 'PRIVATE changed generation'
        path.write_text(json.dumps(value), encoding='utf8')
        before = {str(p.relative_to(self.profile)): p.read_bytes()
            for p in self.profile.rglob('*') if p.is_file()}
        result = self.run_entry('configure', facade=True)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report['reason'], 'web_entry_reuse_unverified')
        self.assertNotIn('PRIVATE', result.stdout+result.stderr)
        self.assertEqual(before, {str(p.relative_to(self.profile)): p.read_bytes()
            for p in self.profile.rglob('*') if p.is_file()})
        self.assertFalse((self.profile/'current.json').exists())

    def test_verify_without_configuration_does_not_start_or_write(self):
        before=sorted(self.root.rglob('*'))
        result=self.run_entry('verify',facade=True)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'not_configured')
        self.assertEqual(sorted(self.root.rglob('*')),before)

    def test_desktop_preparation_requires_ready_service_without_config_mutation(self):
        self.configure()
        before=sorted(self.profile.rglob('*'))
        result=self.run_entry('desktop-prepare',facade=True)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'unavailable')
        self.assertEqual(sorted(self.profile.rglob('*')),before)
        result=self.run_entry('desktop-status',facade=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'absent')
        result=self.run_entry('desktop-check',facade=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'absent')
        self.assertEqual(sorted(self.profile.rglob('*')),before)

    def test_verify_requires_ready_service_and_preserves_saved_configuration(self):
        self.configure()
        before={str(p.relative_to(self.profile)):p.read_bytes() for p in self.profile.rglob('*') if p.is_file()}
        result=self.run_entry('verify',facade=True)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'unavailable')
        self.assertEqual(before,{str(p.relative_to(self.profile)):p.read_bytes() for p in self.profile.rglob('*') if p.is_file()})
        self.assertFalse((self.profile/'checks').exists())

    def test_irrelevant_control_options_rejected_before_config_or_launch(self):
        for action,options in [('status',['-ReplaceClosedBrowser']),
            ('inspect',['-ReplaceClosedBrowser']), ('inspect',['-DrainSeconds','1']),
            ('assist',['-DrainSeconds','1']),('start',['-PythonExecutable',sys.executable]),
            ('status',['-RecoveryDigest','a'*64]),('recover',['-RecoveryDigest','not-a-digest']),
            ('stop',['-DrainSeconds','31'])]:
            with self.subTest(action=action):
                result=self.run_entry(action,*options,facade=True)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout)['code'],'web_entry_unavailable')
                self.assertFalse(self.profile.exists())

    def test_recovery_preview_requires_dead_owned_instance_and_does_not_launch(self):
        self.configure()
        before={str(p):p.read_bytes() for p in self.profile.rglob('*') if p.is_file()}
        for args in [[],['-RecoveryDigest','a'*64]]:
            result=self.run_entry('recover',*args,facade=True)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['code'],'web_manager_recovery_required')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.profile.rglob('*') if p.is_file()})

    def test_inspect_facade_requires_existing_service_without_launching_one(self):
        self.configure()
        original = (self.profile/'profile.json').read_bytes()
        result = self.run_entry('inspect', facade=True)
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['code'], 'web_manager_service_not_started')
        self.assertEqual((self.profile/'profile.json').read_bytes(), original)
        self.assertFalse((self.profile/'current.json').exists())


if __name__ == '__main__':
    unittest.main()
