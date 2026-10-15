"""Public pwsh -File transport and real setup parser; no real entry operations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class SingleEntryCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='operator-single-cli-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        for name in ('codex-operator.ps1', 'operator_desktop_setup.ps1'):
            shutil.copyfile(SCRIPTS / name, self.scripts / name)
        for name in ('feishu-codex-operator.ps1', 'operator_installation.psm1',
                     'operator_entry_migration.ps1', 'operator_entry_shortcut_adoption.ps1',
                     'operator_entry_upgrade.ps1'):
            (self.scripts / name).write_text('# inert dependency fixture\n', encoding='utf8')
        # Only the post-parse target is replaced. Both command entry points and
        # their separate PowerShell process/argument boundaries remain real.
        (self.scripts / 'operator_desktop_pair_legacy.psm1').write_text('''
function Get-OperatorDesktopSingleEntryPlan {
 param($ProjectRoot,$RetainedNativeShortcut,[string[]]$EvidenceFiles)
 return @{phase='fixture_preview';project=$ProjectRoot;retained=$RetainedNativeShortcut;evidence=@($EvidenceFiles)}
}
Export-ModuleMember -Function Get-OperatorDesktopSingleEntryPlan
''', encoding='utf8')
        self.paths = [str(self.root / '材料 一.json'), str(self.root / '材料 二.json')]

    def run_public(self, *arguments):
        return subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(self.scripts / 'codex-operator.ps1'), 'models', 'desktop-pair',
            '-ProjectRoot', str(self.root), 'single-entry-preview',
            '-RetainedNativeShortcut', str(self.root / 'retained-native.lnk'), *arguments],
            capture_output=True, text=True, encoding='utf8', timeout=30)

    def test_two_unicode_paths_cross_public_file_argument_boundary_unchanged(self):
        result = self.run_public('-EvidenceFilesJson', json.dumps(self.paths, ensure_ascii=False))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['phase'], 'fixture_preview')
        self.assertEqual(value['evidence'], self.paths)
        self.assertEqual(value['project'], str(self.root))

    def test_malformed_relative_scalar_and_mutually_exclusive_input_are_rejected(self):
        cases = [('-EvidenceFilesJson', '{malformed'),
                 ('-EvidenceFilesJson', json.dumps(self.paths[0])),
                 ('-EvidenceFilesJson', json.dumps(['relative.json'])),
                 ('-EvidenceFilesJson', json.dumps([None])),
                 ('-EvidenceFilesJson', json.dumps(self.paths * 9)),
                 ('-EvidenceFilesJson', json.dumps(self.paths), '-EvidenceFiles', self.paths[0])]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_public(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('fixture_preview', result.stdout)


if __name__ == '__main__':
    unittest.main()
