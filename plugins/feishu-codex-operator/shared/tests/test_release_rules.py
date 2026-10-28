from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = next(p for p in Path(__file__).resolve().parents
              if (p / '.codex-plugin/plugin.json').is_file())
START = '<!-- FEISHU_CODEX_OPERATOR_RULES_START -->'
END = '<!-- FEISHU_CODEX_OPERATOR_RULES_END -->'
sys.path.insert(0, str(PLUGIN / 'scripts'))
import build_codex_operator_release as release_builder


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
class ReleaseManagedRulesTests(unittest.TestCase):
    def check_pair(self, root: bytes, mirror: bytes, expected: bool) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'root.md').write_bytes(root)
            (base / 'mirror.md').write_bytes(mirror)
            # Read the actual audit function through the parser. No copied policy.
            script = r'''
param($Source, $Folder)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'parse_failed'}
$node=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ReleaseManagedRulesBytes'},$true))
if ($node.Count -ne 1) {throw 'missing_function'}
. ([scriptblock]::Create($node[0].Extent.Text))
try {
    $a=Get-ReleaseManagedRulesBytes (Join-Path $Folder 'root.md')
    $b=Get-ReleaseManagedRulesBytes (Join-Path $Folder 'mirror.md') -Mirror
    @{equal=([Convert]::ToBase64String($a) -ceq [Convert]::ToBase64String($b))}|ConvertTo-Json -Compress
} catch { @{equal=$false}|ConvertTo-Json -Compress }
'''
            driver = base / 'probe.ps1'
            driver.write_text(script, encoding='utf-8')
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File',
                                     str(driver), str(PLUGIN / 'scripts/audit-feishu-codex-release.ps1'),
                                     str(base)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=15, check=True)
            self.assertIs(json.loads(result.stdout)['equal'], expected, result.stderr)

    def test_private_surroundings_do_not_change_managed_rules(self):
        block = f'{START}\r\n规则 bytes\r\n{END}'.encode()
        self.check_pair(b'\xef\xbb\xbfprivate owner preference\r\n' + block + b'\r\nnotes',
                        block + b'\r\n', True)

    def test_content_and_line_endings_remain_exact(self):
        block = f'{START}\r\nrule\r\n{END}'.encode()
        self.check_pair(block.replace(b'rule', b'changed'), block, False)
        self.check_pair(block.replace(b'\r\n', b'\n'), block, False)

    def test_private_mirror_surroundings_are_rejected(self):
        block = f'{START}\nrule\n{END}'.encode()
        for mirror in (b'PRIVATE_SENTINEL\n' + block, block + b'\nPRIVATE_SENTINEL',
                       b'\xef\xbb\xbfPRIVATE_SENTINEL\n' + block):
            with self.subTest(mirror=mirror):
                self.check_pair(b'PRIVATE_SENTINEL\n' + block, mirror, False)

    def test_mirror_allows_only_optional_initial_bom_and_whitespace(self):
        block = f'{START}\nrule\n{END}'.encode()
        for mirror in (b'\xef\xbb\xbf\r\n \t\n' + block + b'\r\n\t ',
                       '\u2003\n'.encode() + block + '\n\u2003'.encode()):
            with self.subTest(mirror=mirror):
                self.check_pair(block, mirror, True)
        for mirror in (b'\n\xef\xbb\xbf' + block, b'\xef\xbb\xbf\xef\xbb\xbf' + block,
                       block + b'\n\xef\xbb\xbf'):
            with self.subTest(mirror=mirror):
                self.check_pair(block, mirror, False)

    def test_utf8_bom_before_first_marker_is_not_part_of_managed_block(self):
        block = f'{START}\nrule\n{END}'.encode()
        self.check_pair(b'\xef\xbb\xbf' + block, block, True)
        self.check_pair(block, b'\xef\xbb\xbf' + block, True)
        self.check_pair(b'\xef\xbb\xbf' + block, b'\xef\xbb\xbf' + block, True)

    def test_missing_duplicate_reversed_or_inline_markers_are_rejected(self):
        block = f'{START}\nrule\n{END}'.encode()
        for damaged in (b'rule', block + b'\n' + block,
                        f'{END}\nrule\n{START}'.encode(), b'inline ' + block):
            with self.subTest(damaged=damaged):
                self.check_pair(damaged, block, False)
                self.check_pair(block, damaged, False)

    def test_invalid_utf8_is_rejected(self):
        block = f'{START}\nrule\n{END}'.encode()
        self.check_pair(b'\xff' + block, block, False)


class ReleaseMirrorCollectorTests(unittest.TestCase):
    def collect(self, mirror):
        with tempfile.TemporaryDirectory(prefix='operator-release-mirror-') as folder:
            root = Path(folder).resolve()
            plugin = root / 'plugins/feishu-codex-operator'
            files = {'.codex-plugin/plugin.json': b'{"name":"codex-operator","version":"fixture"}',
                     'LICENSE': b'fixture plugin license',
                     'assets/AGENTS.feishu-codex-operator.md': mirror,
                     **{name: b'fixture public document\n' for name in release_builder.REVIEWED_DOCS}}
            for name, raw in files.items():
                target = plugin / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            (root / 'LICENSE').write_bytes(b'fixture repository license')
            # Root rules are private input even if someone previously copied
            # their entire contents to the public mirror by mistake.
            (root / 'AGENTS.md').write_bytes(b'PRIVATE_ROOT_ONLY\n' + mirror)
            inventory = {'schema_version': 1, 'repository_files': ['LICENSE'], 'development_paths': [],
                         'components': [{'root_role': 'plugin_root', 'paths': [*files, 'assets/release-inventory.json']}],
                         'reviewed_document_sha256': {name: hashlib.sha256(files[name]).hexdigest()
                                                     for name in release_builder.REVIEWED_DOCS}}
            (plugin / 'assets/release-inventory.json').write_text(json.dumps(inventory), encoding='utf8')
            original = release_builder.read_source

            def read_source(base, relative):
                self.assertNotEqual(relative.casefold(), 'agents.md', 'Private root rules must not be read.')
                return original(base, relative)

            with patch.object(release_builder, 'read_source', read_source):
                return release_builder.collect(root)

    def test_independent_collector_rejects_private_mirror_surroundings(self):
        block = f'{START}\nrule\n{END}'.encode()
        for mirror in (b'PRIVATE_SENTINEL\n' + block, block + b'\nPRIVATE_SENTINEL',
                       b'\xef\xbb\xbfPRIVATE_SENTINEL\n' + block):
            with self.subTest(mirror=mirror), self.assertRaisesRegex(ValueError, '^private_rules_mirror_surroundings$'):
                self.collect(mirror)

    def test_collector_preserves_public_bytes_without_reading_private_root(self):
        block = f'{START}\r\n规则 bytes\r\n{END}'.encode()
        for mirror in (block, b'\xef\xbb\xbf' + block,
                       b'\xef\xbb\xbf\r\n \t\n' + block + b'\n\t '):
            with self.subTest(mirror=mirror):
                data, provenance, _ = self.collect(mirror)
                self.assertEqual(data['AGENTS.md'], mirror)
                self.assertEqual(provenance['AGENTS.md'], 'plugins/feishu-codex-operator/assets/AGENTS.feishu-codex-operator.md')
                self.assertFalse(any(b'PRIVATE_ROOT_ONLY' in raw for raw in data.values()))

    def test_collector_rejects_malformed_or_duplicate_rule_markers(self):
        block = f'{START}\nrule\n{END}'.encode()
        for mirror in (b'rule', block + b'\n' + block,
                       f'{END}\nrule\n{START}'.encode(), b'inline ' + block,
                       b'\n\xef\xbb\xbf' + block, b'\xef\xbb\xbf\xef\xbb\xbf' + block,
                       block + b'\n\xef\xbb\xbf', b'\xff' + block):
            with self.subTest(mirror=mirror), self.assertRaises(ValueError):
                self.collect(mirror)


if __name__ == '__main__':
    unittest.main()
