"""Disposable legacy runtime cutover; never operate on the real installation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


PLUGIN = next(parent for parent in Path(__file__).resolve().parents
              if (parent / ".codex-plugin/plugin.json").is_file())
SCRIPT = PLUGIN / "scripts/operator_legacy_runtime_upgrade.py"
SPEC = importlib.util.spec_from_file_location("operator_legacy_runtime_upgrade", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cutover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover)
RELEASE_SPEC = importlib.util.spec_from_file_location(
    "build_codex_operator_release", PLUGIN / "scripts/build_codex_operator_release.py")
assert RELEASE_SPEC is not None and RELEASE_SPEC.loader is not None
release = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(release)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


class LegacyRuntimeUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name).resolve()
        self.project = base / "project"
        self.plugin = base / "plugin"
        self.runtime = self.project / cutover.RUNTIME_RELATIVE
        self.runtime.mkdir(parents=True)
        self.plugin.mkdir()
        self.names = sorted(cutover.startup_inventory(
            PLUGIN / "scripts/start-feishu-codex-operator.ps1"))
        self.assertEqual(len(self.names), 60)
        inventory = b"$expectedFiles = @(\n" + b"\n".join(
            ("    '" + name + "',").encode() for name in self.names) + b"\n)\n"
        write(self.plugin / "scripts/start-feishu-codex-operator.ps1", inventory)
        start_hook = self.project / ".codex/hooks/start-feishu-codex-operator.ps1"
        stop_hook = self.project / ".codex/hooks/stop-feishu-codex-operator.ps1"
        write(start_hook, inventory)
        write(stop_hook, b"stopped legacy hook")
        write(self.plugin / "assets/release-inventory.json", json.dumps({
            "source_version": "4.2.0-alpha.138"}).encode())
        code = {}
        for name in self.names:
            source = cutover.expected_source(self.plugin, name)
            old = ("old:" + name).encode()
            new = ("new:" + name).encode()
            if name == "operator_core/config.py":
                old = b"OPERATOR_VERSION = '4.2.0-alpha.138'\nlegacy=True\n"
                new = b"OPERATOR_VERSION = '4.2.0-alpha.138'\nlegacy=False\n"
            if name == "operator_main.py":
                new = old  # Unchanged files must not be rewritten.
            write(self.runtime / name, old)
            write(source, new)
            code[name] = sha(old)
        manifest = {"schema_version": 1,
                    "operator_version": "4.2.0-alpha.138",
                    "public_entry": {"path": str(self.plugin / "scripts/codex-operator.ps1"),
                                     "sha256": sha(b"old public entry")},
                    "code_files": code,
                    "start_hook_sha256": sha(start_hook.read_bytes()),
                    "stop_hook_sha256": sha(stop_hook.read_bytes())}
        write(self.runtime / "runtime-manifest.json", cutover.canonical_json(manifest))
        write(self.runtime / "operator.env", b"private fixture config")
        write(self.runtime / "sessions.json", b'{"binding":"fixture"}')
        with closing(sqlite3.connect(self.runtime / "state.sqlite3")) as db:
            with db:
                db.execute("CREATE TABLE inbox_events(status TEXT, last_error TEXT)")
                db.execute("INSERT INTO inbox_events VALUES (?, ?)",
                           ("retryable_failed", cutover.HOLD_ERROR))
        with closing(sqlite3.connect(self.runtime / "callbacks.sqlite3")) as db:
            with db:
                db.execute("CREATE TABLE final_callback_requests(state TEXT)")
                db.execute("INSERT INTO final_callback_requests VALUES ('closed')")
        self.services = lambda project, plugin: None
        self.processes = lambda project, plugin: None

    def preview(self):
        return cutover.preview(self.project, self.plugin,
                               process_check=self.processes,
                               services_check=self.services)

    def apply(self, value, **kwargs):
        return cutover.apply(self.project, self.plugin, value,
                             process_check=self.processes,
                             services_check=self.services, **kwargs)

    def restore(self, value):
        return cutover.restore(self.project, self.plugin, value,
                               process_check=self.processes,
                               services_check=self.services)

    def test_preview_apply_restore_preserve_state_and_never_claim_ownership(self):
        before = cutover.runtime_snapshot(self.runtime)
        plan = self.preview()
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertFalse((self.project / cutover.MAINTENANCE_RELATIVE).exists())
        self.assertEqual(plan["queue"], {"actionable_inbox": 0, "open_callbacks": 0})
        self.assertEqual(len(plan["code"]), 60)
        result = self.apply(plan["preview_sha256"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["changed_code_files"], 59)
        self.assertEqual((self.runtime / "sessions.json").read_bytes(),
                         b'{"binding":"fixture"}')
        self.assertEqual((self.runtime / "operator.env").read_bytes(),
                         b"private fixture config")
        self.assertFalse((self.project / ".codex/operator-installation/ownership.json").exists())
        self.assertEqual(cutover.read_json(self.runtime / "runtime-manifest.json")
                         ["code_files"]["operator_core/config.py"],
                         sha((self.plugin / "scripts/operator_core/config.py").read_bytes()))
        restored = self.restore(plan["preview_sha256"])
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertEqual(cutover.read_json(Path(result["transaction"]) / "intent.json")
                         ["state"], "restored")

    def test_stale_source_blocks_before_transaction(self):
        plan = self.preview()
        write(self.plugin / "scripts/operator_main.py", b"changed after preview")
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_preview_changed"):
            self.apply(plan["preview_sha256"])
        maintenance = self.project / cutover.MAINTENANCE_RELATIVE
        self.assertEqual(sorted(p.name for p in maintenance.iterdir()), ["operation.lock"])

    def test_pending_callback_blocks_preview(self):
        with closing(sqlite3.connect(self.runtime / "callbacks.sqlite3")) as db:
            with db:
                db.execute("INSERT INTO final_callback_requests VALUES ('pending')")
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_pending_work"):
            self.preview()

    def test_unknown_inbox_state_and_null_error_block_preview(self):
        for status, error in (("unknown_new_state", None),
                              ("retryable_failed", None)):
            with self.subTest(status=status):
                with closing(sqlite3.connect(self.runtime / "state.sqlite3")) as db:
                    with db:
                        db.execute("DELETE FROM inbox_events WHERE NOT "
                                   "(status='retryable_failed' AND last_error=?)",
                                   (cutover.HOLD_ERROR,))
                        db.execute("INSERT INTO inbox_events VALUES (?, ?)",
                                   (status, error))
                with self.assertRaisesRegex(cutover.CutoverError,
                                            "cutover_pending_work"):
                    self.preview()

    def test_unknown_service_blocks_preview(self):
        def unknown(project, plugin):
            raise cutover.CutoverError("cutover_router_port_not_free")
        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_router_port_not_free"):
            cutover.preview(self.project, self.plugin,
                            process_check=self.processes, services_check=unknown)
        self.assertFalse((self.project / cutover.MAINTENANCE_RELATIVE).exists())

    def test_web_status_uses_utf8_for_localized_json(self):
        profile = self.project / ".codex/operator-web-service/profile.json"
        write(profile, json.dumps({"runtime": {
            "python": str(Path(sys.executable).resolve()),
            "python_sha256": cutover.file_fingerprint(
                Path(sys.executable).resolve())["sha256"]}}).encode())
        write(self.plugin / "scripts/operator_web_service.py", b"import json, os\n"
              b"print(json.dumps({'status':'stopped',"
              b"'configuration_current':os.environ.get('PYTHONIOENCODING')=='utf-8',"
              b"'summary':'\xe5\xb7\xb2\xe5\x81\x9c\xe6\xad\xa2'},ensure_ascii=False))\n")
        with mock.patch.object(cutover.socket, "socket"):
            cutover.service_gate(self.project, self.plugin)

    def test_interrupted_write_is_terminal_and_explicitly_restorable(self):
        before = cutover.runtime_snapshot(self.runtime)
        plan = self.preview()
        written = 0

        def interrupted(path: Path, raw: bytes) -> None:
            nonlocal written
            written += 1
            if written > 1:
                raise RuntimeError("fixture interrupted write")
            cutover.atomic_bytes(path, raw)

        with self.assertRaisesRegex(RuntimeError, "fixture interrupted write"):
            self.apply(plan["preview_sha256"], writer=interrupted)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")
        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_transaction_exists_no_retry"):
            self.apply(plan["preview_sha256"])
        self.assertEqual(self.restore(plan["preview_sha256"])["status"], "restored")
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)

    def test_restore_preserves_later_runtime_edits(self):
        plan = self.preview()
        self.apply(plan["preview_sha256"])
        write(self.runtime / "sessions.json", b"later user edit")
        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_restore_data_changed"):
            self.restore(plan["preview_sha256"])
        self.assertEqual((self.runtime / "sessions.json").read_bytes(),
                         b"later user edit")
        self.assertEqual(cutover.read_json(
            self.project / cutover.MAINTENANCE_RELATIVE /
            plan["preview_sha256"] / "intent.json")["state"], "applied")

    def test_restore_preserves_code_edit_between_file_writes(self):
        plan = self.preview()
        self.apply(plan["preview_sha256"])
        changed = [name for name, row in plan["code"].items()
                   if row["before"] != row["after"]]
        later = self.runtime / changed[1]
        edited = b"later user edit during restore"
        writes = 0

        def interleaved(path: Path, raw: bytes) -> None:
            nonlocal writes
            cutover.atomic_bytes(path, raw)
            writes += 1
            if writes == 1:
                later.write_bytes(edited)

        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_restore_target_changed"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                            process_check=self.processes,
                            services_check=self.services, writer=interleaved)
        self.assertEqual(later.read_bytes(), edited)
        self.assertEqual(cutover.read_json(
            self.project / cutover.MAINTENANCE_RELATIVE /
            plan["preview_sha256"] / "intent.json")["state"], "failed")

    def test_restore_preserves_manifest_edit_between_file_writes(self):
        plan = self.preview()
        self.apply(plan["preview_sha256"])
        manifest = self.runtime / "runtime-manifest.json"
        edited = b"later manifest edit during restore"
        writes = 0

        def interleaved(path: Path, raw: bytes) -> None:
            nonlocal writes
            cutover.atomic_bytes(path, raw)
            writes += 1
            if writes == 1:
                manifest.write_bytes(edited)

        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_restore_manifest_changed"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                            process_check=self.processes,
                            services_check=self.services, writer=interleaved)
        self.assertEqual(manifest.read_bytes(), edited)

    def test_startup_inventory_mismatch_blocks_before_transaction(self):
        start_hook = self.project / ".codex/hooks/start-feishu-codex-operator.ps1"
        raw = start_hook.read_bytes().replace(b"operator_main.py", b"unknown_main.py")
        write(start_hook, raw)
        with self.assertRaisesRegex(cutover.CutoverError,
                                    "cutover_runtime_inventory_mismatch"):
            self.preview()


class ReleaseInclusionTests(unittest.TestCase):
    def test_release_zip_includes_cutover_and_its_regression_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "operator-preview.zip"
            release.build(PLUGIN.parent.parent, output)
            with zipfile.ZipFile(output) as archive:
                for relative in ("scripts/operator_legacy_runtime_upgrade.py",
                                 "shared/tests/test_legacy_runtime_upgrade.py"):
                    source = PLUGIN / relative
                    self.assertEqual(archive.read(
                        f"plugins/feishu-codex-operator/{relative}"),
                        source.read_bytes())


if __name__ == "__main__":
    unittest.main()
