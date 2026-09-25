"""Interpreter discovery uses isolated probes, never a model or channel job."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
class PythonRuntimeTests(unittest.TestCase):
    def run_ps(self, body):
        env = {**os.environ, 'OPERATOR_TEST_MODULE': str(PLUGIN / 'scripts/operator_python.psm1'),
               'OPERATOR_TEST_PYTHON': sys.executable}
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command',
            "$ErrorActionPreference='Stop'; $module=Import-Module $env:OPERATOR_TEST_MODULE -Force -PassThru; " + body],
            env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_real_interpreter_version_probe(self):
        value = self.run_ps("& $module { (Get-OperatorPythonVersion ([pscustomobject]@{Source=$env:OPERATOR_TEST_PYTHON;Prefix=@()})).ToString() } | ConvertTo-Json")
        self.assertEqual(value, f'{sys.version_info.major}.{sys.version_info.minor}')

    def test_unsupported_python_resolves_launcher_before_any_job(self):
        value = self.run_ps("""
& $module {
 function script:Get-OperatorPythonCandidates {
  [pscustomobject]@{Source='old-python';Prefix=@();Command='python.exe'}
  [pscustomobject]@{Source='py-launcher';Prefix=@();Command='py.exe'}
 }
 function script:Get-OperatorPythonFromLauncher($Candidate) {
  [pscustomobject]@{Source='resolved-python';Prefix=@();Command='py.exe'}
 }
 function script:Get-OperatorPythonVersion($Candidate) {
  if($Candidate.Source -eq 'old-python'){return [version]'3.10'}
  return [version]'3.11'
 }
}; Get-OperatorPython -Required | Select-Object Available,Source,Prefix | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(Available=True, Source='resolved-python', Prefix=[]))

    def test_missing_or_old_interpreter_fails_without_job(self):
        value = self.run_ps("""
& $module {
 function script:Get-OperatorPythonCandidates { [pscustomobject]@{Source='old';Prefix=@()} }
 function script:Get-OperatorPythonVersion($Candidate) { return [version]'3.10' }
}; $result=Get-OperatorPython; $failed=$false
try { Get-OperatorPython -Required | Out-Null } catch { $failed=$true }
@{available=$result.Available;required_failed=$failed;source=$result.Source} | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(available=False, required_failed=True, source=''))

    def test_probe_budget_stops_after_eight_candidates(self):
        value = self.run_ps("""
& $module {
 $script:probeCount=0
 function script:Get-OperatorPythonCandidates { 1..20 | ForEach-Object { [pscustomobject]@{Source="candidate-$_";Prefix=@()} } }
 function script:Get-OperatorPythonVersion($Candidate) { $script:probeCount++; return $null }
}; $result=Get-OperatorPython
@{available=$result.Available;probes=(& $module { $script:probeCount })} | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(available=False, probes=8))

    def test_py_only_support_does_not_claim_the_mcp_python_command_is_ready(self):
        value = self.run_ps("""
& $module {
 function script:Get-OperatorPythonCandidates {
  [pscustomobject]@{Source='old-python';Prefix=@();Command='python.exe'}
  [pscustomobject]@{Source='py-launcher';Prefix=@();Command='py.exe'}
 }
 function script:Get-OperatorPythonFromLauncher($Candidate) {
  [pscustomobject]@{Source='resolved-python';Prefix=@();Command='py.exe'}
 }
 function script:Get-OperatorPythonVersion($Candidate) {
  if($Candidate.Command -eq 'python.exe'){return [version]'3.10'}
  return [version]'3.14'
 }
}; @{entry=(Get-OperatorPython).Available;mcp=(Get-OperatorPython -McpCommand).Available} | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(entry=True, mcp=False))

    @unittest.skipUnless(os.name == 'nt', 'Windows executable aliases')
    def test_store_alias_is_not_launched_and_sources_are_deduplicated(self):
        value = self.run_ps(r"""
& $module {
 function script:Get-Command($Name) {
  if($Name -eq 'python.exe'){[pscustomobject]@{Source='C:\Users\Example\AppData\Local\Microsoft\WindowsApps\python.exe'}}
  if($Name -eq 'python3.exe'){[pscustomobject]@{Source='C:\Python\python.exe'};[pscustomobject]@{Source='c:\python\PYTHON.exe'}}
  if($Name -eq 'py.exe'){[pscustomobject]@{Source='C:\Windows\py.exe'}}
 }
 @(Get-OperatorPythonCandidates) | Select-Object Source,Prefix | ConvertTo-Json -Compress
}
""")
        self.assertEqual(value, [dict(Source=r'C:\Python\python.exe', Prefix=[]),
                                 dict(Source=r'C:\Windows\py.exe', Prefix=[])])

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher paths')
    def test_launcher_only_lists_installed_runtimes_and_returns_direct_paths(self):
        value = self.run_ps(r"""
& $module {
 $script:probeArgs=@()
 function script:Invoke-OperatorPythonProbe($Executable,$Argument) {
  $script:probeArgs+=@{executable=$Executable;argument=$Argument}
  return "Installed Pythons:`n -V:3.14 * C:\Existing Python\用户\python.exe`n -3.12-64 C:\Earlier\python.exe`n -V:3.15 C:\Missing\python.exe`n -V:3.16 C:\Existing\py.exe`n -V:3.11 relative\python.exe"
 }
 function script:Test-Path($LiteralPath) { return $LiteralPath -notlike '*Missing*' }
 $found=@(Get-OperatorPythonFromLauncher ([pscustomobject]@{Source='launcher'}))
 @{paths=@($found.Source);prefixes=@($found | ForEach-Object {$_.Prefix.Count});probes=$script:probeArgs} | ConvertTo-Json -Depth 5 -Compress
}
""")
        self.assertEqual(value, dict(paths=[r'C:\Existing Python\用户\python.exe', r'C:\Earlier\python.exe'],
            prefixes=[0, 0], probes=[dict(executable='launcher', argument='-0p')]))

    def test_launcher_rejects_oversized_output_without_partial_candidates(self):
        value = self.run_ps(r"""
& $module {
 $script:sample=" -V:3.14 C:\Present\python.exe`n" + ('x'*65536)
 function script:Invoke-OperatorPythonProbe { return $script:sample }
 function script:Test-Path { throw 'Should reject before checking any listed path' }
 $bytes=@(Get-OperatorPythonFromLauncher ([pscustomobject]@{Source='launcher'})).Count
 $script:sample=" -V:3.14 C:\Present\python.exe`n" + ("x`n"*64)
 @{bytes=$bytes;lines=@(Get-OperatorPythonFromLauncher ([pscustomobject]@{Source='launcher'})).Count} | ConvertTo-Json -Compress
}
""")
        self.assertEqual(value, dict(bytes=0, lines=0))

    @unittest.skipUnless(os.name == 'nt', 'Windows command precedence')
    def test_mcp_uses_first_command_instead_of_a_later_working_python(self):
        value = self.run_ps(r"""
& $module {
 function script:Get-Command($Name) {
  if($Name -eq 'python.exe') {
   [pscustomobject]@{Source='C:\Old\python.exe'}
   [pscustomobject]@{Source='C:\Working\python.exe'}
  }
 }
 function script:Get-OperatorPythonVersion($Candidate) {
  if($Candidate.Source -like '*Old*'){return [version]'3.10'}
  return [version]'3.14'
 }
}; @{entry=(Get-OperatorPython).Available;mcp=(Get-OperatorPython -McpCommand).Available} | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(entry=True, mcp=False))

    def test_existing_project_interpreter_keeps_priority_without_launcher_probe(self):
        value = self.run_ps("""
& $module {
 function script:Get-OperatorPythonCandidates { [pscustomobject]@{Source='launcher';Prefix=@();Command='py.exe'} }
 function script:Get-OperatorPythonFromLauncher { throw 'Preferred interpreter should have won' }
}; Get-OperatorPython -Required -PreferredExecutable $env:OPERATOR_TEST_PYTHON | Select-Object Source,Prefix | ConvertTo-Json -Compress
""")
        self.assertEqual(value, dict(Source=sys.executable, Prefix=[]))

    @unittest.skipUnless(os.name == 'nt' and Path(r'C:\Windows\py.exe').is_file(),
                         'Windows Python launcher required')
    def test_user_task_status_reaches_helper_without_python_on_path(self):
        entry = PLUGIN / 'scripts/codex-operator.ps1'
        with tempfile.TemporaryDirectory(prefix='operator-user-task-py-only-') as project:
            env = {**os.environ, 'PATH': r'C:\Windows\System32;C:\Windows'}
            self.assertIsNone(shutil.which('python', path=env['PATH']))
            result = subprocess.run(
                [shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File',
                 str(entry), 'channels', 'user-tasks-status', '-ProjectRoot', project],
                env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=20)
        # The disposable project has no installed runtime. Reaching its
        # structured error proves interpreter discovery got past the entry.
        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout.strip())
        self.assertIs(output['ok'], False)
        self.assertIn('runtime directory is unavailable', output['error'])

    @unittest.skipUnless(os.name == 'nt', 'Windows command precedence')
    def test_mcp_store_alias_shadowing_real_python_is_reported_unavailable(self):
        value = self.run_ps(r"""
& $module {
 function script:Get-Command($Name) {
  if($Name -eq 'python.exe') {
   [pscustomobject]@{Source='C:\Users\Example\AppData\Local\Microsoft\WindowsApps\python.exe'}
   [pscustomobject]@{Source='C:\Working\python.exe'}
  }
 }
 function script:Get-OperatorPythonVersion { throw 'Store alias must never be probed' }
}; (Get-OperatorPython -McpCommand).Available | ConvertTo-Json
""")
        self.assertFalse(value)


if __name__ == '__main__':
    unittest.main()
