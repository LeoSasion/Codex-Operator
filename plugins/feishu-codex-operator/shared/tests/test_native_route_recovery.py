"""Real Windows PowerShell recovery in disposable homes, never a live router."""

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
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = _OPERATOR_PLUGIN_ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from operator_core import model_router_config as routing
from operator_core.model_registry import RouterError

POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
TOKEN = 'a' * 64  # Synthetic fixture only.
BLOCK = f'# BEGIN FEISHU OPERATOR MODEL ROUTER\nopenai_base_url = "http://127.0.0.1:4317/{TOKEN}/v1"\n# END FEISHU OPERATOR MODEL ROUTER\n'
VOICE_BLOCK = BLOCK.replace('# END FEISHU OPERATOR MODEL ROUTER\n',
    'experimental_realtime_webrtc_call_base_url = "https://chatgpt.com/backend-api/codex"\n'
    '# END FEISHU OPERATOR MODEL ROUTER\n')
VOICE_WS_BLOCK = BLOCK.replace('# END FEISHU OPERATOR MODEL ROUTER\n',
    'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n'
    '# END FEISHU OPERATOR MODEL ROUTER\n')
VOICE_BOTH_BLOCK = VOICE_BLOCK.replace('# END FEISHU OPERATOR MODEL ROUTER\n',
    'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n'
    '# END FEISHU OPERATOR MODEL ROUTER\n')
UNIFIED_BASE = f'http://127.0.0.1:4318/{TOKEN}/backend-api/codex'
UNIFIED_TOP = ('# BEGIN OPERATOR UNIFIED CANDIDATE\n'
    'model_provider = "operator_unified_candidate"\n'
    'experimental_realtime_webrtc_call_base_url = "https://chatgpt.com/backend-api/codex"\n'
    'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n'
    '# END OPERATOR UNIFIED CANDIDATE\n')
UNIFIED_PROVIDER = ('\n# BEGIN OPERATOR UNIFIED PROVIDER CANDIDATE\n'
    '[model_providers.operator_unified_candidate]\n'
    'name = "OpenAI"\n'
    f'base_url = "{UNIFIED_BASE}"\n'
    f'model_catalog_url = "{UNIFIED_BASE}/models"\n'
    'wire_api = "responses"\n'
    'requires_openai_auth = true\n'
    'request_max_retries = 0\n'
    'stream_max_retries = 0\n'
    'supports_websockets = false\n'
    'supports_standalone_web_search = true\n'
    '# END OPERATOR UNIFIED PROVIDER CANDIDATE\n')


@unittest.skipUnless(os.name == 'nt' and POWERSHELL.is_file(), 'Windows PowerShell 5.1 required')
class NativeRouteRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'private home'
        self.home.mkdir()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.config = self.home / 'config.toml'
        self.marker = self.home / 'operator-native-route-only'
        self.script = SCRIPTS / 'restore-codex-official-route.ps1'
        self.env = {**os.environ, 'CODEX_HOME': str(self.home)}
        self.env.pop('OPENAI_BASE_URL', None)

    def run_script(self, apply=False):
        result = subprocess.run([str(POWERSHELL), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(self.script), '-CodexHome', str(self.home), '-ProjectRoot', str(self.project),
            '-Json', *(['-Apply'] if apply else [])], capture_output=True, timeout=30, env=self.env)
        output = result.stdout.decode('utf-8-sig')
        self.assertNotIn(TOKEN, output + result.stderr.decode('utf-8', errors='replace'))
        self.assertTrue(output.strip(), result.stderr)
        return result.returncode, json.loads(output)

    def test_missing_runtime_journal_and_changed_token_do_not_block_exact_recovery(self):
        tail = 'model = "gpt-5.6-sol"\r\n# 保留用户设置\r\n[features]\r\nstandalone_web_search = true\r\n'.encode()
        before = b'\xef\xbb\xbf# user comment\r\n' + BLOCK.replace('\n', '\r\n').encode() + tail
        self.config.write_bytes(before)
        (self.home / 'auth.json').write_bytes(b'private synthetic auth')
        (self.home / 'models_cache.json').write_bytes(b'keep cache')
        self.assertEqual(self.run_script()[1]['status'], 'preview')
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.config.read_bytes(), before)
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['completed'], ['operator-native-route-only', 'config.toml'])
        self.assertEqual(self.config.read_bytes(), b'\xef\xbb\xbf# user comment\r\n' + tail)
        backup = Path(result['backup'])
        self.assertEqual((backup / 'config.toml.before').read_bytes(), before)
        self.assertTrue((backup / 'completed.json').exists())
        self.assertEqual((self.home / 'auth.json').read_bytes(), b'private synthetic auth')
        self.assertEqual((self.home / 'models_cache.json').read_bytes(), b'keep cache')
        again = self.run_script(True)[1]
        self.assertEqual(again['completed'], [])
        self.assertIsNone(again['backup'])
        self.assertEqual(len(list((self.home / 'operator-route-recovery').iterdir())), 1)

    def test_already_commented_route_is_preserved_and_explicit_apply_adds_only_lock(self):
        before = BLOCK.replace('openai_base_url', '# openai_base_url').encode() + b'model="gpt-5.6-sol"\n'
        self.config.write_bytes(before)
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertFalse(result['config_changed'])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(result['completed'], ['operator-native-route-only'])
        # The documented maintenance command must pass its top-level argument
        # gate too; its default remains read-only even after a completed recovery.
        if shutil.which('pwsh'):
            command = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File',
                str(SCRIPTS / 'feishu-codex-operator.ps1'), 'operator', 'recover-native',
                '-ProjectRoot', str(self.project), '-Json'], capture_output=True, timeout=30, env=self.env)
            self.assertEqual(command.returncode, 0, command.stderr)
            self.assertEqual(json.loads(command.stdout)['status'], 'preview')
            self.assertEqual(self.config.read_bytes(), before)

    def test_voice_protected_route_recovers_exact_prefix_and_preserves_tail(self):
        tail = b'model = "native"\r\n# keep bytes\r\n'
        before = VOICE_BOTH_BLOCK.replace('\n', '\r\n').encode() + tail
        self.config.write_bytes(before)
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['completed'], ['operator-native-route-only', 'config.toml'])
        self.assertEqual(self.config.read_bytes(), tail)
        self.assertEqual((Path(result['backup']) / 'config.toml.before').read_bytes(), before)

    def test_older_call_only_and_new_ws_only_blocks_remain_removable(self):
        for block in (VOICE_BLOCK, VOICE_WS_BLOCK):
            with self.subTest(block=block):
                self.config.write_bytes(block.encode() + b'model="native"\n')
                code, result = self.run_script(True)
                self.assertEqual(code, 0, result)
                self.assertEqual(self.config.read_bytes(), b'model="native"\n')
                self.marker.unlink()

    def test_recovery_preserves_one_following_commented_legacy_block(self):
        commented = BLOCK.replace('openai_base_url', '# openai_base_url').replace('\n', '\r\n').encode()
        tail = b'model="native"\r\n# keep trailing bytes\r\n'
        before = VOICE_BOTH_BLOCK.encode() + commented + tail
        self.config.write_bytes(before)
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['completed'], ['operator-native-route-only', 'config.toml'])
        self.assertEqual(self.config.read_bytes(), commented + tail)
        self.assertEqual((Path(result['backup']) / 'config.toml.before').read_bytes(), before)

    def test_unified_recovery_preserves_inert_legacy_block_and_later_table(self):
        inert = BLOCK.replace('openai_base_url', '# openai_base_url').encode()
        original = inert + b'model="native"\r\n[features]\r\nplugins=false\r\n'
        later = b'\r\n[analytics]\r\nenabled=false\r\n'
        before = UNIFIED_TOP.encode() + original + UNIFIED_PROVIDER.encode() + later
        self.config.write_bytes(before)
        self.assertEqual(self.run_script()[1]['would_change'], ['operator-native-route-only', 'config.toml'])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse(self.marker.exists())
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['route_before'], 'plugin_route')
        self.assertEqual(self.config.read_bytes(), original + later)
        self.assertEqual((Path(result['backup']) / 'config.toml.before').read_bytes(), before)
        self.assertTrue(self.marker.exists())
        again = self.run_script(True)[1]
        self.assertEqual(again['completed'], [])
        self.assertEqual(self.config.read_bytes(), original + later)

    def test_unified_recovery_preserves_existing_official_voice_settings(self):
        top = UNIFIED_TOP.replace(
            'experimental_realtime_webrtc_call_base_url = "https://chatgpt.com/backend-api/codex"\n', '').replace(
            'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n', '')
        original = (b'experimental_realtime_webrtc_call_base_url = "https://chatgpt.com/backend-api/codex"\n'
            b'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n'
            b'model="native"\n')
        self.config.write_bytes(top.encode() + original + UNIFIED_PROVIDER.encode())
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.config.read_bytes(), original)

    def test_client_compaction_provider_recovery_preserves_original_and_backup(self):
        original = b'model="native"\n[features]\nplugins=false\n'
        provider = UNIFIED_PROVIDER.replace('name = "OpenAI"', 'name = "Codex Operator"')
        before = UNIFIED_TOP.encode() + original + provider.encode()
        self.config.write_bytes(before)
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual((Path(result['backup']) / 'config.toml.before').read_bytes(), before)

    def test_changed_or_ambiguous_unified_blocks_stop_without_writes(self):
        original = b'model="native"\n'
        good = UNIFIED_TOP.encode() + original + UNIFIED_PROVIDER.encode()
        cases = (
            good.replace(b'name = "OpenAI"', b'name = "Other"'),
            good.replace(b'request_max_retries = 0', b'request_max_retries = 1'),
            good.replace(b'/models"', b'/other"'),
            good.replace(b'# END OPERATOR UNIFIED CANDIDATE\n', b''),
            good + UNIFIED_PROVIDER.encode(),
            b'# unrelated\n' + good,
            good + b'other_key = true\n',
            UNIFIED_TOP.encode() + b'model="native"' + UNIFIED_PROVIDER.encode() + b'[analytics]\nenabled=false\n',
            good + b'\n[model_providers.operator_unified_candidate]\nname="Other"\n',
            good.replace(b'model="native"\n',
                BLOCK.replace('openai_base_url', '# openai_base_url').encode() * 2 + original),
            good.replace(b'model="native"\n', VOICE_BOTH_BLOCK.encode() + original),
        )
        for before in cases:
            with self.subTest(before_sha256=hashlib.sha256(before).hexdigest()):
                self.config.write_bytes(before)
                code, result = self.run_script(True)
                self.assertEqual(code, 1, result)
                self.assertEqual(result['status'], 'stopped')
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.home / 'operator-route-recovery').exists())

    def test_changed_voice_route_is_not_guessed_during_recovery(self):
        for block in (VOICE_BLOCK, VOICE_WS_BLOCK):
            with self.subTest(block=block):
                before = block.replace('chatgpt.com', 'example.com').encode() + b'model="native"\n'
                self.config.write_bytes(before)
                code, result = self.run_script(True)
                self.assertEqual(code, 1, result)
                self.assertEqual(result['status'], 'stopped')
                self.assertEqual(self.config.read_bytes(), before)
                self.assertFalse(self.marker.exists())

    def test_unknown_edited_or_embedded_route_is_not_overwritten(self):
        cases = [BLOCK.replace('127.0.0.1', 'example.com'), BLOCK + BLOCK,
            VOICE_BOTH_BLOCK + VOICE_BOTH_BLOCK,
            'description="""\n' + BLOCK + '"""\n', '[other]\n' + BLOCK,
            BLOCK + 'openai_base_url="https://example.com/v1"\n',
            BLOCK + 'model_provider="custom"\n', BLOCK + '[model_providers.openai]\nbase_url="https://example.com"\n']
        for text in cases:
            with self.subTest(text=text[:40]):
                self.config.write_bytes(text.encode())
                code, result = self.run_script(True)
                self.assertEqual(code, 1, result)
                self.assertEqual(result['status'], 'stopped')
                self.assertEqual(self.config.read_bytes(), text.encode())
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.home / 'operator-route-recovery').exists())

    def make_entry(self):
        bundle = self.project / '.codex/operator-desktop-entry'
        bundle.mkdir(parents=True)
        entry = bundle / 'operator_desktop_entry.ps1'
        entry.write_bytes(b'exact owned fixture script')
        binary = bundle / 'Codex拓展入口.exe'
        binary.write_bytes(b'exact owned fixture launcher')
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        (bundle / 'launcher-manifest.json').write_text(json.dumps({'schema_version': 1,
            'native_fallback': 'native-only-v1', 'binary_sha256': digest(binary), 'entry_script_sha256': digest(entry)}))
        config = bundle / 'desktop-entry.json'
        config.write_text(json.dumps({'schema_version': 1, 'mode': 'reviewed_startup',
            'entry_script_sha256': digest(entry), 'startup_bundle': '.codex/fixture', 'retained_note': '用户备注'}))
        return bundle, config

    def test_verified_entry_returns_to_native_without_modifying_launcher_or_shortcuts(self):
        self.config.write_bytes((BLOCK + 'model="gpt-5.6-sol"\n').encode())
        bundle, config = self.make_entry()
        before = config.read_bytes()
        code, result = self.run_script(True)
        self.assertEqual(code, 0, result)
        changed = json.loads(config.read_bytes())
        old = json.loads(before)
        self.assertEqual(changed, {**old, 'mode': 'native'})
        self.assertEqual((Path(result['backup']) / 'desktop-entry.json.before').read_bytes(), before)
        self.assertEqual((bundle / 'Codex拓展入口.exe').read_bytes(), b'exact owned fixture launcher')

    def test_changed_entry_is_preserved_but_does_not_trap_the_global_route(self):
        self.config.write_bytes((BLOCK + 'model="gpt-5.6-sol"\n').encode())
        bundle, config = self.make_entry()
        before = config.read_bytes()
        (bundle / 'operator_desktop_entry.ps1').write_bytes(b'user modification')
        code, result = self.run_script(True)
        self.assertEqual(code, 1, result)
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(result['config_changed'])
        self.assertEqual(self.config.read_bytes(), b'model="gpt-5.6-sol"\n')
        self.assertEqual(config.read_bytes(), before)

    def test_hard_link_and_oversized_config_are_rejected_without_writes(self):
        target = self.root / 'retained-original'
        target.write_bytes(BLOCK.encode())
        os.link(target, self.config)
        self.assertEqual(self.run_script(True)[0], 1)
        self.assertFalse(self.marker.exists())
        self.assertEqual(target.read_bytes(), BLOCK.encode())
        self.config.unlink()
        self.config.write_bytes(b'x' * 1048577)
        self.assertEqual(self.run_script(True)[0], 1)
        self.assertFalse(self.marker.exists())

    def test_stale_snapshot_and_backup_failure_do_not_overwrite_original(self):
        self.config.write_text(BLOCK)
        q = lambda p: "'" + str(p).replace("'", "''") + "'"
        driver = self.root / 'failure.ps1'
        driver.write_text('. ' + q(self.script) + ' -Library\n'
            '$path=' + q(self.config) + '\n$before=Read-RecoveryBytes $path\n'
            '[IO.File]::WriteAllBytes($path, [Text.Encoding]::UTF8.GetBytes("user edit"))\n'
            '$stale=$false\ntry { Write-RecoveryChange @{path=$path; before=$before; after=[byte[]]@(1)} } catch { $stale=$true }\n'
            'function New-RecoveryBackup { throw "fixture backup failure" }\n'
            '$result=Invoke-OfficialRouteRecovery ' + q(self.home) + ' ' + q(self.project) + ' $true\n'
            '@{stale=$stale; result=$result} | ConvertTo-Json -Depth 6 -Compress\n', encoding='utf-8-sig')
        result = subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(driver)],
            capture_output=True, timeout=30, env=self.env)
        value = json.loads(result.stdout)
        self.assertTrue(value['stale'])
        self.assertEqual(value['result']['status'], 'stopped')
        self.assertEqual(self.config.read_bytes(), b'user edit')
        self.assertFalse(self.marker.exists())


class NativeRouteActivationGuardTests(unittest.TestCase):
    def test_recovery_lock_blocks_activation_before_network_or_state_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'operator-native-route-only').write_bytes(b'owner selected native')
            config = root / 'config.toml'
            config.write_bytes(b'model="native"\n')
            with patch.object(routing, 'health') as health:
                with self.assertRaisesRegex(RouterError, 'official_route_recovery_lock_active'):
                    routing.activate(root / 'missing-runtime', 4317, config)
                health.assert_not_called()
            self.assertEqual(config.read_bytes(), b'model="native"\n')


if __name__ == '__main__':
    unittest.main()
