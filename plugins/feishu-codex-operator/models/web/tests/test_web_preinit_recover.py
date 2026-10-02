"""Disposable, explicit recovery of a saved Web launch that never initialized."""
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file()
    and (parent / 'scripts/source_route_contract.py').is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / 'development'))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / 'scripts'))
import operator_web_service as manager
import operator_web_preinit_recover as recovery


@unittest.skipUnless(os.name == 'nt', 'Windows saved service process observation')
class PreinitRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operator-preinit-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = self.root / 'profile'
        browser = self.root / 'browser'
        browser.mkdir()
        key = self.root / 'key'
        key.write_text('private-key-never-read')
        self.settings = self.root / 'settings.json'
        tunnel_id = 'tunnel_' + 'a' * 32
        self.settings.write_text(json.dumps({'electron': str(Path(sys.executable).resolve()),
            'profile_directory': str(browser), 'session_partition': 'persist:fixture',
            'transport': 'mcp_v1', 'mcp': {'mode': 'openai_tunnel_v1',
                'tunnel_id': tunnel_id, 'tunnel_client': str(Path(sys.executable).resolve()),
                'tunnel_client_sha256': manager.file_digest(Path(sys.executable).resolve()),
                'api_key_file': str(key), 'binding_file': str(self.root / 'binding.json')}}))
        manager.configure(self.profile, self.settings)
        self.config = manager.read_json(self.profile / 'profile.json')
        self.owner = {'pid': 87654321, 'birth': '12345',
            'executable': self.config['runtime']['python']}
        self.record = {'version': 1, 'attempt': 'b' * 32, 'phase': 'uncertain',
            'pid': self.owner['pid'], 'process': self.owner,
            'runtime': self.config['runtime']}
        manager.save_record(self.profile, self.record)
        manager.service.write_json(self.profile / 'current.json',
            {'version': 1, 'attempt': self.record['attempt']})
        self.state = manager.state_path(self.profile, self.record)
        self.marker = self.root / ('active-' + tunnel_id + '.json')
        for name, value in [('process_identity', None), ('windows_process_entries', [])]:
            patcher = patch.object(manager, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.actual_probe = recovery._missing_aiohttp
        probe = patch.object(recovery, '_missing_aiohttp', return_value=None)
        probe.start()
        self.addCleanup(probe.stop)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob('*') if path.is_file()}

    def test_preview_then_one_apply_keeps_originals_without_launch(self):
        before = self.snapshot()
        preview = recovery.recover_preinit(self.profile)
        self.assertEqual(before, self.snapshot())
        with patch.object(manager, 'spawn_child') as spawn:
            result = recovery.recover_preinit(self.profile,
                expected_preview=preview['preview_sha256'])
            spawn.assert_not_called()
        self.assertEqual(result['status'], 'recovered_preinit')
        self.assertIsNone(manager.current_record(self.profile))
        self.assertFalse(self.state.exists())
        self.assertEqual(manager.read_json(self.profile / 'instances' /
            (self.record['attempt'] + '.json')), self.record)
        transaction = next((self.profile / 'history').glob('preinit-recovery-*'))
        receipt = manager.read_json(transaction / 'receipt.json')
        self.assertEqual(receipt['phase'], 'retired')
        self.assertFalse(receipt['launched'])
        self.assertFalse(receipt['replayed'])
        self.assertFalse(receipt['clean_stop_claimed'])
        manager.require_complete_preinit_recoveries(self.profile)
        originals = [path.read_bytes() for path in transaction.glob('*.original')]
        self.assertEqual(set(originals), {before[str(name)] for name in (
            Path('profile/profile.json'), Path('profile/current.json'),
            Path('profile/instances') / (self.record['attempt'] + '.json'),
            Path('settings.json'))})
        self.assertNotIn(b'private-key-never-read', b''.join(
            path.read_bytes() for path in transaction.rglob('*') if path.is_file()))
        after = self.snapshot()
        with self.assertRaises(Exception):
            recovery.recover_preinit(self.profile, expected_preview=preview['preview_sha256'])
        self.assertEqual(after, self.snapshot())

    def test_changed_preview_and_live_dependency_reject_without_write(self):
        preview = recovery.recover_preinit(self.profile)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'web_preinit_preview_changed'):
            recovery.recover_preinit(self.profile, expected_preview='0' * 64)
        self.assertEqual(before, self.snapshot())
        executable = self.config['settings']['dependencies']['electron']['path']
        with patch.object(manager, 'windows_process_entries',
                return_value=[{'pid': 123, 'name': Path(executable).name}]), \
                patch.object(manager, 'process_identity',
                side_effect=lambda pid: {'executable': executable} if pid == 123 else None):
            with self.assertRaisesRegex(ValueError, 'recovery_dependencies_live'):
                recovery.recover_preinit(self.profile)
        self.assertEqual(before, self.snapshot())
        self.state.mkdir()
        changed = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'web_preinit_state_present'):
            recovery.recover_preinit(self.profile)
        self.assertEqual(changed, self.snapshot())

    def test_import_failure_gate_rejects_when_import_succeeds(self):
        with patch.object(recovery, '_missing_aiohttp', self.actual_probe):
            with patch.object(recovery.subprocess, 'run', return_value=type('Result', (),
                    {'returncode': 0})()):
                with self.assertRaisesRegex(ValueError, 'web_preinit_import_unverified'):
                    recovery.recover_preinit(self.profile)

    def test_import_probe_uses_saved_script_import_path(self):
        result = type('Result', (), {'returncode': recovery.MISSING_AIOHTTP_EXIT})()
        with patch.object(recovery, '_missing_aiohttp', self.actual_probe), \
                patch.object(recovery.subprocess, 'run', return_value=result) as run:
            recovery.recover_preinit(self.profile)
        args = run.call_args.args[0]
        self.assertEqual(args[:5], [self.config['runtime']['python'],
            '-E', '-s', '-B', '-u'])
        self.assertEqual(args[-1], self.config['runtime']['source_root'])
        self.assertEqual(run.call_args.kwargs['cwd'], str(self.profile))

    def test_interruption_keeps_prepared_journal_and_blocks_reapply(self):
        preview = recovery.recover_preinit(self.profile)
        before = self.snapshot()
        original_rename = recovery.os.rename

        def fail_pointer(source, destination):
            if Path(source) == self.profile / 'current.json':
                raise OSError('fixture interruption')
            return original_rename(source, destination)

        with patch.object(recovery.os, 'rename', side_effect=fail_pointer):
            with self.assertRaises(OSError):
                recovery.recover_preinit(self.profile,
                    expected_preview=preview['preview_sha256'])
        self.assertEqual((self.profile / 'current.json').read_bytes(),
            before[str(Path('profile/current.json'))])
        transaction = next((self.profile / 'history').glob('preinit-recovery-*'))
        self.assertEqual(manager.read_json(transaction / 'receipt.json')['phase'], 'prepared')
        changed = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'web_preinit_transaction_exists'):
            recovery.recover_preinit(self.profile, expected_preview=preview['preview_sha256'])
        self.assertEqual(changed, self.snapshot())

    def test_terminal_receipt_failure_after_pointer_move_blocks_start(self):
        preview = recovery.recover_preinit(self.profile)
        original_write = manager.service.write_json

        def fail_terminal(path, value, *args, **kwargs):
            if Path(path).name == 'receipt.json' and value.get('phase') == 'retired':
                raise OSError('fixture terminal receipt interruption')
            return original_write(path, value, *args, **kwargs)

        with patch.object(manager.service, 'write_json', side_effect=fail_terminal):
            with self.assertRaises(OSError):
                recovery.recover_preinit(self.profile,
                    expected_preview=preview['preview_sha256'])
        self.assertFalse((self.profile / 'current.json').exists())
        transaction = next((self.profile / 'history').glob('preinit-recovery-*'))
        self.assertTrue((transaction / 'current.json').is_file())
        self.assertEqual(manager.read_json(transaction / 'receipt.json')['phase'], 'prepared')
        with patch.object(manager, 'spawn_child') as spawn:
            with self.assertRaisesRegex(ValueError, 'preinit_recovery_pending'):
                manager.start(self.profile)
            spawn.assert_not_called()

    def test_malformed_terminal_receipt_blocks_later_start(self):
        preview = recovery.recover_preinit(self.profile)
        recovery.recover_preinit(self.profile, expected_preview=preview['preview_sha256'])
        transaction = next((self.profile / 'history').glob('preinit-recovery-*'))
        receipt = manager.read_json(transaction / 'receipt.json')
        receipt['phase'] = 'unknown'
        manager.service.write_json(transaction / 'receipt.json', receipt)
        with patch.object(manager, 'spawn_child') as spawn:
            with self.assertRaisesRegex(ValueError, 'preinit_recovery_pending'):
                manager.start(self.profile)
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
