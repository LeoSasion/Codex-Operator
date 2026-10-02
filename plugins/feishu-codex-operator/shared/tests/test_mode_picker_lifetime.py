"""The entry waits for its picker, not the picker's background descendants."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class ModePickerLifetimeTests(unittest.TestCase):
    def test_picker_exit_releases_entry_while_its_owned_background_child_is_alive(self):
        with tempfile.TemporaryDirectory(prefix='operator-picker-lifetime-') as temporary:
            root = Path(temporary).resolve()
            source = root / 'fixture.cs'
            source.write_text(r'''
using System; using System.Diagnostics; using System.IO; using System.Reflection; using System.Threading;
internal static class Fixture {
    private static int Main(string[] args) {
        string root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if(args.Length==1 && args[0]=="--child") {
            File.WriteAllText(Path.Combine(root,"ready"),"ready");
            DateTime end=DateTime.UtcNow.AddSeconds(20);
            while(!File.Exists(Path.Combine(root,"release")) && DateTime.UtcNow<end) Thread.Sleep(30);
            File.WriteAllText(Path.Combine(root,"child-exited"),"exited");
            return 0;
        }
        ProcessStartInfo start=new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,"--child");
        start.UseShellExecute=false; start.CreateNoWindow=true; start.WindowStyle=ProcessWindowStyle.Hidden;
        using(Process child=Process.Start(start)) {
            DateTime end=DateTime.UtcNow.AddSeconds(5);
            while(!File.Exists(Path.Combine(root,"ready")) && DateTime.UtcNow<end) Thread.Sleep(30);
            return File.Exists(Path.Combine(root,"ready")) ? 0 : 2;
        }
    }
}
''', encoding='utf8')
            executable = root / 'operator-mode-picker.exe'
            compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            built = subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(executable), str(source)],
                                    capture_output=True, timeout=20)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            entry = root / 'entry.ps1'
            entry.write_bytes((PLUGIN / 'scripts/operator_mode_entry.ps1').read_bytes())
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            (root / 'entry.json').write_text(json.dumps({'contract': 'operator_isolated_mode_entry_v1',
                'root': str(root), 'native_enabled': False, 'entry_sha256': digest(entry),
                'compiled': {'operator-mode-picker.exe': digest(executable)}}), encoding='utf8')
            package = root / 'package'
            package.mkdir()
            (package / 'AppxManifest.xml').write_text('<Package><Identity Name="OpenAI.Codex"/>'
                '<Applications><Application Id="App" Executable="app/ChatGPT.exe" '
                'EntryPoint="Windows.FullTrustApplication"/></Applications></Package>', encoding='utf8')
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            driver = root / 'driver.ps1'
            driver.write_text('function Get-AppxPackage {param($Name) [pscustomobject]@{InstallLocation=' +
                quote(package) + ";PackageFamilyName='OpenAI.Codex_fixture'}}\n& " + quote(entry) +
                ' -Action choose -Root ' + quote(root) + '\nexit $LASTEXITCODE\n', encoding='utf8')
            try:
                result = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive',
                                         '-File', str(driver)], capture_output=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((root / 'ready').is_file())
                self.assertFalse((root / 'child-exited').exists())
            finally:
                (root / 'release').write_text('release', encoding='ascii')
                deadline = time.monotonic() + 5
                while (root / 'ready').exists() and not (root / 'child-exited').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
            self.assertTrue((root / 'child-exited').is_file())
