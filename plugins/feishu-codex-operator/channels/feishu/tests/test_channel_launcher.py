"""Real Windows process tests; no Feishu credentials or business tasks."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
PWSH = shutil.which('pwsh')


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows launch contract')
class ChannelLauncherTests(unittest.TestCase):
    def run_probe(self, invalid_directory=False):
        with tempfile.TemporaryDirectory(prefix='operator launch ') as temporary:
            directory = Path(temporary)
            child = directory / 'fixture.ps1'
            child.write_text('''param([switch]$DetachedLaunch,[string]$LeaseId)
Start-Sleep -Milliseconds 700
Add-Type -AssemblyName System.Security
$bytes=[Convert]::FromBase64String($env:OPERATOR_LAUNCH_TEST_CIPHER)
$plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$digest=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256 -ErrorAction Stop).Hash
@{lease=$LeaseId;detached=[bool]$DetachedLaunch;pid=$PID;digest=$digest;edition=$PSVersionTable.PSEdition;credential_ok=([Text.Encoding]::UTF8.GetString($plain) -ceq 'synthetic canary')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'result.json') -Encoding utf8
''', encoding='utf-8-sig')
            driver = directory / 'parent.ps1'
            driver.write_text('''param([string]$Source,[string]$Fixture,[string]$Directory)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'invalid source'}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Start-DetachedLaunchHelper'},$true)
Invoke-Expression $function.Extent.Text
$startHookScript=$Fixture;$projectRoot=$Directory
Add-Type -AssemblyName System.Security
$env:OPERATOR_LAUNCH_TEST_CIPHER=[Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes('synthetic canary'),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
Start-DetachedLaunchHelper '0123456789abcdef01234567'
''', encoding='utf-8-sig')
            target = directory / 'missing' if invalid_directory else directory
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(driver),
                '-Source', str(ROOT/'scripts/start-feishu-codex-operator.ps1'),
                '-Fixture', str(child), '-Directory', str(target)],
                capture_output=True, text=True, encoding='utf-8', timeout=20)
            output = directory / 'result.json'
            if invalid_directory:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())
                return
            self.assertEqual(result.returncode, 0, result.stderr)
            process_id = int(result.stdout.strip())
            deadline = time.monotonic()+10
            while not output.exists() and time.monotonic()<deadline:
                time.sleep(.1)
            self.assertTrue(output.exists(), 'child did not outlive parent')
            data=json.loads(output.read_text(encoding='utf-8-sig'))
            # The receipt is written before PowerShell releases its working
            # directory. Wait for this exact child before TemporaryDirectory
            # cleanup; do not race process exit or kill unrelated processes.
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, process_id)
            if handle:
                try:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
                finally:
                    kernel.CloseHandle(handle)
            else:
                self.assertEqual(ctypes.get_last_error(), 87, 'child exit could not be checked')
            self.assertEqual(data['pid'], process_id)
            self.assertEqual(data['lease'], '0123456789abcdef01234567')
            self.assertTrue(data['detached'])
            self.assertTrue(data['credential_ok'])
            self.assertEqual(len(data['digest']), 64)
            self.assertEqual(data['edition'], 'Core')

    def test_hidden_child_outlives_parent_and_retains_user_dpapi(self):
        self.run_probe()

    def test_failed_creation_does_not_fall_back(self):
        self.run_probe(invalid_directory=True)


if __name__ == '__main__':
    unittest.main()
