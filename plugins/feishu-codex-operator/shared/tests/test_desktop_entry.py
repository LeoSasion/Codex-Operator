"""Desktop entry against isolated projects and fake process observations only."""

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
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = _OPERATOR_PLUGIN_ROOT


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
class DesktopEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="operator-desktop-entry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scripts = self.root / 'plugins/feishu-codex-operator/scripts'
        self.scripts.mkdir(parents=True)
        self.entry = self.scripts / 'operator_desktop_entry.ps1'
        shutil.copyfile(ROOT / 'scripts/operator_desktop_entry.ps1', self.entry)
        self.bundle = self.root / '.codex/startup-bundle'; self.bundle.mkdir(parents=True)
        self.app = self.root / 'fake-app'; (self.app/'app').mkdir(parents=True)
        (self.app/'app/ChatGPT.exe').write_bytes(b'fixture only')
        (self.app/'AppxManifest.xml').write_text('''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OpenAI.Codex"/><Applications><Application Id="App" Executable="app/ChatGPT.exe" EntryPoint="Windows.FullTrustApplication"/></Applications></Package>''', encoding='utf-8')
        self.startup = self.bundle / 'start-codex-with-lmstudio.ps1'
        self.set_startup("Add-Content -LiteralPath " + self.q(self.root/'sync-count') + " -Value 'sync'\nexit 0\n")

    @staticmethod
    def q(path): return "'" + str(path).replace("'", "''") + "'"

    def set_startup(self, code):
        self.startup.write_text(code, encoding='utf-8')
        (self.bundle/'startup-sync-plan.json').write_text(json.dumps({'entry_files':{
            self.startup.name:hashlib.sha256(self.startup.read_bytes()).hexdigest()}}), encoding='utf-8')

    def run_entry(self, *, running=False, check=False):
        process = "[pscustomobject]@{ExecutablePath="+self.q(self.app/'app/ChatGPT.exe')+"}" if running else '@()'
        code = (
            "Add-Type -TypeDefinition @'\n"
            "using System; using System.IO; public static class OperatorRegisteredActivation {\n"
            " public static void Open(string app) {\n"
            "  File.AppendAllText(Environment.GetEnvironmentVariable(\"OPERATOR_TEST_ATTEMPT_COUNT\"),\"attempt\\n\");\n"
            "  if(app != \"OpenAI.Codex_fixture!App\") throw new InvalidOperationException(\"Unexpected registered activation\");\n"
            "  File.AppendAllText(Environment.GetEnvironmentVariable(\"OPERATOR_TEST_OPEN_COUNT\"),\"open\\n\");\n"
            " } }\n'@\n"
            "function Get-AppxPackage { param($Name) [pscustomobject]@{InstallLocation="+self.q(self.app)+"; PackageFamilyName='OpenAI.Codex_fixture'} }\n"
            "function Get-CimInstance { param($ClassName,$Filter) "+process+" }\n"
            "function Start-Process { param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle) "
            "Add-Content -LiteralPath "+self.q(self.root/'attempt-count')+" -Value 'attempt'; "
            "if ($FilePath -ne (Join-Path $env:SystemRoot 'explorer.exe') -or $WindowStyle -ne 'Hidden' -or "
            "@($ArgumentList).Count -ne 1 -or $ArgumentList[0] -cne 'shell:AppsFolder\\OpenAI.Codex_fixture!App') { throw 'Unexpected packaged activation' }; "
            "Add-Content -LiteralPath "+self.q(self.root/'open-count')+" -Value 'open' }\n"
            "& "+self.q(self.entry)+" -StartupBundle "+self.q(self.bundle)+(' -CheckOnly' if check else '')+"\nexit $LASTEXITCODE\n")
        driver = self.root/'driver.ps1'; driver.write_text(code, encoding='utf-8')
        return subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-File',str(driver)],
                              capture_output=True,text=True,encoding='utf-8',timeout=15,
                              env={**os.environ, 'CODEX_HOME':str(self.root/'.codex'),
                                   'OPERATOR_TEST_ATTEMPT_COUNT':str(self.root/'attempt-count'),
                                   'OPERATOR_TEST_OPEN_COUNT':str(self.root/'open-count')})

    def test_recovery_lock_opens_native_without_running_startup(self):
        (self.root/'.codex/operator-native-route-only').write_bytes(b'owner selected native')
        self.startup.write_text("throw 'Must not run'", encoding='utf-8')
        result = self.run_entry()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse((self.root/'sync-count').exists())
        self.assertEqual((self.root/'open-count').read_text(encoding='utf-8-sig').splitlines(), ['open'])

    def test_changed_package_manifest_stops_before_activation(self):
        manifest = self.app/'AppxManifest.xml'
        original = manifest.read_text(encoding='utf-8')
        for before, after in (('OpenAI.Codex', 'Other.App'), ('Id="App"', 'Id="Other"'),
                              ('app/ChatGPT.exe', 'app/Other.exe'),
                              ('Windows.FullTrustApplication', 'Other.EntryPoint')):
            with self.subTest(after=after):
                manifest.write_text(original.replace(before, after), encoding='utf-8')
                result = self.run_entry(running=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root/'attempt-count').exists())
                self.assertFalse((self.root/'open-count').exists())
                self.assertFalse((self.root/'sync-count').exists())

    def test_library_import_is_read_only_without_startup_bundle(self):
        driver = self.root/'library.ps1'
        driver.write_text(
            "function Get-AppxPackage { throw 'No package observation during import' }\n"
            "function Start-Process { throw 'No launch during import' }\n"
            ". "+self.q(self.entry)+" -Library\n"
            "if(-not(Get-Command Get-OperatorPackagedApplication) -or "
            "-not(Get-Command Open-OperatorPackagedApplication)){exit 2}\n",
            encoding='utf-8')
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(driver)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def run_fallback(self, *, check=False, family='OpenAI.Codex_fixture'):
        """Execute the compiled launcher's exact embedded PS with fake OS calls."""
        library = self.root/'launcher.dll'
        if not library.exists():
            compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            result = subprocess.run([str(compiler), '/nologo', '/target:library',
                '/reference:System.Windows.Forms.dll', '/out:'+str(library),
                str(ROOT/'scripts/operator_desktop_entry.cs')], capture_output=True,
                text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        driver = self.root/'fallback.ps1'
        driver.write_text(
            "function Get-AppxPackage { param($Name) [pscustomobject]@{InstallLocation="+self.q(self.app)+
            "; PackageFamilyName="+self.q(family)+"} }\n"
            "function Start-Process { param($FilePath,$ArgumentList,$WindowStyle) "
            "Add-Content -LiteralPath "+self.q(self.root/'fallback-attempts')+" -Value 'attempt'; "
            "if($FilePath -cne (Join-Path $env:SystemRoot 'explorer.exe') -or "
            "$WindowStyle -cne 'Hidden' -or @($ArgumentList).Count -ne 1 -or "
            "$ArgumentList[0] -cne 'shell:AppsFolder\\OpenAI.Codex_fixture!App'){throw 'Wrong activation'} }\n"
            "$assembly=[Reflection.Assembly]::LoadFrom("+self.q(library)+")\n"
            "$method=$assembly.GetType('OperatorDesktopEntry').GetMethod('BuildNativeActivationCommand',"
            "[Reflection.BindingFlags]'NonPublic,Static')\n"
            "$command=$method.Invoke($null,[object[]]@("+('$true' if check else '$false')+"))\n"
            "& ([scriptblock]::Create($command))\n",
            encoding='utf-8')
        return subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(driver)],
                              capture_output=True, text=True, timeout=15)

    def test_uninstalled_csharp_fallback_uses_verified_package_activation(self):
        result = self.run_fallback()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'fallback-attempts').read_text(encoding='utf-8-sig').splitlines(), ['attempt'])

    def test_csharp_fallback_check_only_and_invalid_package_never_launch(self):
        result = self.run_fallback(check=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse((self.root/'fallback-attempts').exists())
        result = self.run_fallback(family='Other.App_fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'fallback-attempts').exists())
        manifest = self.app/'AppxManifest.xml'
        manifest.write_text(manifest.read_text(encoding='utf-8').replace('app/ChatGPT.exe', 'app/Other.exe'), encoding='utf-8')
        result = self.run_fallback()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'fallback-attempts').exists())

    def test_closed_desktop_runs_reviewed_sync_once(self):
        result = self.run_entry()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((self.root/'sync-count').read_text(encoding='utf-8-sig').splitlines(),['sync'])
        self.assertFalse((self.root/'open-count').exists(), "The reviewed sync workflow owns the cold launch")

    def test_running_desktop_only_opens_existing_app(self):
        self.startup.write_text("throw 'Must not run'", encoding='utf-8')
        result = self.run_entry(running=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse((self.root/'sync-count').exists())
        self.assertEqual((self.root/'open-count').read_text(encoding='utf-8-sig').splitlines(),['open'])

    def web_startup(self, code):
        self.startup = self.bundle/'start-codex-with-web.ps1'
        self.set_startup(code)
        path = self.bundle/'startup-sync-plan.json'
        plan = json.loads(path.read_text(encoding='utf-8'))
        plan.update(schema_version=2, startup_script=self.startup.name)
        path.write_text(json.dumps(plan), encoding='utf-8')

    def test_web_services_ready_then_open_native_once(self):
        self.web_startup("if (Test-Path -LiteralPath " + self.q(self.root/'open-count') +
            ") { throw 'Opened before ready' }; Add-Content -LiteralPath " + self.q(self.root/'sync-count') +
            " -Value 'ready'\nexit 0\n")
        result = self.run_entry()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'sync-count').read_text(encoding='utf-8-sig').splitlines(), ['ready'])
        self.assertEqual((self.root/'open-count').read_text(encoding='utf-8-sig').splitlines(), ['open'])

    def test_failed_web_startup_never_opens_or_retries(self):
        self.web_startup("Add-Content -LiteralPath " + self.q(self.root/'sync-count') + " -Value 'failed'\nexit 9\n")
        result = self.run_entry()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root/'sync-count').read_text(encoding='utf-8-sig').splitlines(), ['failed'])
        self.assertFalse((self.root/'open-count').exists())

    def test_web_unknown_plan_and_path_stop_before_execution(self):
        self.web_startup("throw 'Must not execute'")
        path = self.bundle/'startup-sync-plan.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for changes in ({'schema_version':3}, {'startup_script':'../start-codex-with-web.ps1'},
                        {'startup_script':'start-codex-with-lmstudio.ps1'}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**original, **changes}), encoding='utf-8')
                result = self.run_entry()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root/'open-count').exists())

    def test_check_only_does_not_create_logs_launch_or_sync(self):
        before = sorted(str(p.relative_to(self.bundle)) for p in self.bundle.rglob('*'))
        for running, action in ((False,'synchronize_then_open'),(True,'open_existing')):
            result = self.run_entry(running=running,check=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['action'],action)
        self.assertEqual(sorted(str(p.relative_to(self.bundle)) for p in self.bundle.rglob('*')),before)
        self.assertFalse((self.root/'sync-count').exists()); self.assertFalse((self.root/'open-count').exists())

    def test_installed_entry_without_plugin_source_opens_native(self):
        installed = self.bundle/'operator_desktop_entry.ps1'
        shutil.copyfile(self.entry,installed)
        self.entry = installed
        (self.bundle/'desktop-entry.json').write_text(json.dumps({'schema_version':1,'mode':'native',
            'entry_script_sha256':hashlib.sha256(installed.read_bytes()).hexdigest()}),encoding='utf-8')
        # The source copy can disappear without affecting the installed launcher.
        (self.scripts/'operator_desktop_entry.ps1').unlink()
        result = self.run_entry(check=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'],'open_native')
        result = self.run_entry()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse((self.root/'sync-count').exists())
        self.assertEqual((self.root/'open-count').read_text(encoding='utf-8-sig').splitlines(),['open'])

    def test_installed_entry_digest_change_stops(self):
        installed = self.bundle/'operator_desktop_entry.ps1'; shutil.copyfile(self.entry,installed); self.entry=installed
        (self.bundle/'desktop-entry.json').write_text(json.dumps({'schema_version':1,'mode':'native',
            'entry_script_sha256':'a'*64}),encoding='utf-8')
        result = self.run_entry()
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'open-count').exists()); self.assertFalse((self.root/'sync-count').exists())

    def test_changed_workflow_stops_and_records_fresh_failure(self):
        (self.bundle/'unified-startup-last-log.txt').write_text('obsolete log',encoding='utf-8')
        self.startup.write_text("throw 'Must not run'", encoding='utf-8')
        result = self.run_entry()
        self.assertNotEqual(result.returncode,0)
        log = Path((self.bundle/'unified-startup-last-log.txt').read_text(encoding='utf-8-sig').strip())
        self.assertTrue(log.resolve().is_relative_to(self.bundle.resolve()))
        self.assertIn('workflow changed',log.read_text(encoding='utf-8-sig'))
        self.assertFalse((self.root/'sync-count').exists())

    def test_failed_workflow_is_not_retried(self):
        self.set_startup("Add-Content -LiteralPath " + self.q(self.root/'sync-count') + " -Value 'failed'\nWrite-Output 'fixture failure'\nexit 7\n")
        result = self.run_entry()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.root/'sync-count').read_text(encoding='utf-8-sig').splitlines(),['failed'])
        log = Path((self.bundle/'unified-startup-last-log.txt').read_text(encoding='utf-8-sig').strip())
        self.assertIn('fixture failure',log.read_text(encoding='utf-8-sig'))

    def test_concurrent_launches_coalesce_without_replacing_active_log(self):
        self.set_startup("Add-Content -LiteralPath " + self.q(self.root/'sync-count') +
                         " -Value 'sync'\nStart-Sleep -Seconds 2\nexit 0\n")
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.run_entry)
            deadline = time.monotonic() + 5
            while not (self.root/'sync-count').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue((self.root/'sync-count').exists())
            pointer = (self.bundle/'unified-startup-last-log.txt').read_bytes()
            second = self.run_entry()
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertIn('already in progress',second.stdout)
            self.assertEqual((self.bundle/'unified-startup-last-log.txt').read_bytes(),pointer)
            result = first.result(timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((self.root/'sync-count').read_text(encoding='utf-8-sig').splitlines(),['sync'])


if __name__ == '__main__': unittest.main()
