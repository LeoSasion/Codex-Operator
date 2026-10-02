"""Windows config replacement: isolated files, real Win32 races, no Codex home."""
from pathlib import Path as _TestPath
import sys as _test_sys

_ROOT = next(parent for parent in _TestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file())
_test_sys.path.insert(0, str(_ROOT / "scripts"))

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from operator_core import windows_config_transaction as transaction


@unittest.skipUnless(os.name == "nt", "requires real Windows file sharing and ReplaceFileW")
class WindowsConfigTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-config-transaction-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.target = self.root / "config.toml"
        self.assertNotEqual(self.target, Path.home() / ".codex" / "config.toml")
        self.state = self.root / "private-state"
        self.state.mkdir()
        self.before = b'model = "gpt-6-sol"\r\nprivate_key = "keep original bytes"\r\n'
        self.after = b'model = "operator_mixed"\r\nprivate_key = "keep original bytes"\r\n'
        self.target.write_bytes(self.before)
        self.expected = transaction.observe_config(self.target)

    def _attempt(self):
        return transaction.replace_config_once(self.target, self.expected, self.after, self.state)

    @staticmethod
    def _backup(result):
        intent = json.loads((result.directory / "intent.json").read_bytes())
        return result.directory / intent["backup"]

    def test_success_retains_original_and_checks_both_file_identities(self):
        result = self._attempt()
        self.assertEqual(result.status, "applied")
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertEqual((result.directory / "before.bin").read_bytes(), self.before)
        self.assertEqual((result.directory / "candidate.bin").read_bytes(), self.after)
        self.assertEqual(self._backup(result).read_bytes(), self.before)
        self.assertFalse((result.directory / "pending.toml").exists())
        self.assertTrue((result.directory / "verified.json").exists())
        self.assertEqual(transaction._snapshot(self._backup(result)).identity,
                         self.expected.identity)
        self.assertEqual(transaction.inspect_transaction(result.directory).status,
                         "applied_witnessed")
        intent = json.loads((result.directory / "intent.json").read_bytes())
        self.assertEqual(intent["expected_identity"], self.expected.identity.__dict__)
        self.assertNotIn("keep original bytes", (result.directory / "intent.json").read_text())
        self.assertEqual(self.root.stat().st_dev, result.directory.stat().st_dev)

    def test_existing_writer_prevents_guard_and_preserves_target(self):
        handle = transaction._kernel.CreateFileW(str(self.target), transaction._GENERIC_READ | 0x40000000,
            7, None, 3, 0x80, None)
        self.assertNotEqual(handle, transaction._INVALID_HANDLE)
        try:
            result = self._attempt()
        finally:
            transaction._kernel.CloseHandle(handle)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.reason, "open_32")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_new_writer_is_blocked_while_guard_is_held(self):
        real = transaction._replace_file
        observations = []

        def check_writer(target, stage, backup):
            handle = transaction._kernel.CreateFileW(str(target), 0x40000000, 7,
                None, 3, 0x80, None)
            observations.append((handle == transaction._INVALID_HANDLE,
                                 ctypes.get_last_error()))
            if handle != transaction._INVALID_HANDLE:
                transaction._kernel.CloseHandle(handle)
            return real(target, stage, backup)

        with patch.object(transaction, "_replace_file", side_effect=check_writer):
            result = self._attempt()
        self.assertEqual(observations, [(True, 32)])
        self.assertEqual(result.status, "applied")

    def test_rename_swap_between_final_check_and_replace_is_retained(self):
        real = transaction._replace_file
        for _ in range(20):
            moved = self.root / "external-moved.toml"
            if moved.exists():
                moved.unlink()
            self.target.write_bytes(self.before)
            self.expected = transaction.observe_config(self.target)

            def race(target, stage, backup):
                os.replace(target, moved)
                target.write_bytes(b'external editor bytes')
                return real(target, stage, backup)

            with patch.object(transaction, "_replace_file", side_effect=race):
                result = self._attempt()
            self.assertEqual(result.status, "uncertain")
            self.assertEqual(result.reason, "replacement_backup_mismatch")
            self.assertEqual(self._backup(result).read_bytes(), b'external editor bytes')
            self.assertEqual(moved.read_bytes(), self.before)
            self.assertEqual((result.directory / "before.bin").read_bytes(), self.before)
            self.assertFalse((result.directory / "verified.json").exists())
            self.assertEqual(transaction.inspect_transaction(result.directory).status,
                             "uncertain")

    def test_later_editor_change_never_counts_as_current_success(self):
        real = transaction._replace_file

        def later_edit(target, stage, backup):
            real(target, stage, backup)
            outside = self.root / "later.tmp"
            outside.write_bytes(b'later editor bytes')
            os.replace(outside, target)

        with patch.object(transaction, "_replace_file", side_effect=later_edit):
            result = self._attempt()
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.reason, "replacement_target_changed")
        self.assertEqual(self.target.read_bytes(), b'later editor bytes')
        self.assertEqual(self._backup(result).read_bytes(), self.before)
        self.assertEqual(transaction.inspect_transaction(result.directory).status,
                         "uncertain")

    def test_partial_native_failure_keeps_every_artifact(self):
        def partial(target, stage, backup):
            os.replace(target, backup)
            raise transaction.TransactionFailure("replacefile_1177")

        with patch.object(transaction, "_replace_file", side_effect=partial):
            result = self._attempt()
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.reason, "replacefile_1177")
        self.assertEqual((result.directory / "before.bin").read_bytes(), self.before)
        self.assertEqual((result.directory / "candidate.bin").read_bytes(), self.after)
        self.assertEqual((result.directory / "pending.toml").read_bytes(), self.after)
        self.assertEqual(self._backup(result).read_bytes(), self.before)
        self.assertFalse(self.target.exists())
        self.assertEqual(transaction.inspect_transaction(result.directory).status,
                         "uncertain")

    def test_process_exit_after_replace_has_read_only_witness(self):
        child = self.root / "crash_child.py"
        child.write_text("\n".join((
            "import os, sys",
            f"sys.path.insert(0, {str(_ROOT / 'scripts')!r})",
            "from pathlib import Path",
            "from operator_core import windows_config_transaction as txn",
            "target, state = map(Path, sys.argv[1:3])",
            "original = txn._replace_file",
            "def crash_after(target, stage, backup):",
            "    original(target, stage, backup)",
            "    os._exit(23)",
            "txn._replace_file = crash_after",
            f"txn.replace_config_once(target, txn.observe_config(target), {self.after!r}, state)",
        )), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(child), str(self.target), str(self.state)],
                              capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 23, proc.stderr)
        transactions = list(self.state.iterdir())
        self.assertEqual(len(transactions), 1)
        directory = transactions[0]
        self.assertFalse((directory / "verified.json").exists())
        self.assertEqual((directory / "before.bin").read_bytes(), self.before)
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertEqual(transaction.inspect_transaction(directory).status,
                         "applied_witnessed")

    def test_same_volume_gate_refuses_before_writing(self):
        with patch.object(transaction, "_same_volume",
                          side_effect=transaction.TransactionFailure("different_volume")):
            result = self._attempt()
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.reason, "different_volume")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(list(self.state.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
