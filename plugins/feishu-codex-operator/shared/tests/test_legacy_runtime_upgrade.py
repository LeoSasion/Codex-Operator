"""Disposable legacy runtime cutover; never operate on the real installation."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
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
        self.assertEqual(len(self.names), 62)
        self.assertIn("operator_core/web_native_interruption.py", self.names)
        self.assertIn("operator_native_models.py", self.names)
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
        self.assertEqual(set(plan["code"]), set(self.names))
        changed = {name for name, row in plan["code"].items()
                   if row["before"] != row["after"]}
        self.assertEqual(changed, set(self.names) - {"operator_main.py"})
        result = self.apply(plan["preview_sha256"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["changed_code_files"], len(changed))
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


@unittest.skipUnless(os.name == "nt", "Windows explicit dead-Web retirement evidence")
class LegacyRetiredWebCutoverTests(unittest.TestCase):
    def setUp(self):
        LegacyRuntimeUpgradeTests.setUp(self)
        scripts = str(PLUGIN / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
            self.addCleanup(sys.path.remove, scripts)
        self.manager = importlib.import_module("operator_web_service")
        self.profile = self.project / ".codex/operator-web-service"
        self.fixture = self.project / "web-fixture"
        self.fixture.mkdir()
        browser = self.fixture / "browser"
        browser.mkdir()
        key = self.fixture / "key"
        key.write_bytes(b"fixture-private-key-never-read")
        electron, tunnel = self.fixture / "fixture-browser.exe", self.fixture / "fixture-tunnel.exe"
        electron.write_bytes(b"fixture executable")
        tunnel.write_bytes(b"fixture tunnel executable")
        settings = self.fixture / "settings.json"
        settings.write_text(json.dumps({"electron": str(electron),
            "profile_directory": str(browser), "session_partition": "persist:fixture",
            "transport": "mcp_v1", "mcp": {"mode": "openai_tunnel_v1",
                "tunnel_id": "tunnel_" + "a" * 32, "tunnel_client": str(tunnel),
                "tunnel_client_sha256": sha(tunnel.read_bytes()),
                "api_key_file": str(key), "binding_file": str(self.fixture / "binding.json")}}))
        self.manager.configure(self.profile, settings)
        config = self.manager.read_json(self.profile / "profile.json")
        identity = {"pid": 87654321, "birth": "12345", "executable": config["runtime"]["python"]}
        self.record = {"version": 1, "attempt": "b" * 32, "phase": "running",
                       "runtime": config["runtime"], "process": identity, "worker": identity,
                       "instance": "c" * 32}
        self.state = self.manager.state_path(self.profile, self.record)
        self.state.mkdir()
        with cutover.socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.manager.service.write_json(self.state / "session.json", {"version": 1,
            "pid": identity["pid"], "instance": "c" * 32,
            "base_url": "http://127.0.0.1:" + str(self.port) + "/v1", "token": "f" * 43})
        self.record["session_sha256"] = sha((self.state / "session.json").read_bytes())
        self.manager.save_record(self.profile, self.record)
        self.manager.service.write_json(self.profile / "current.json",
                                        {"version": 1, "attempt": "b" * 32})
        self.manager.service.write_json(self.state / "status.json",
                                        {"instance": "c" * 32, "state": "ready", "requests": 3})
        self.manager.service.write_json(self.state / "connection.json", {"instance": "c" * 32,
            "connection_id": "d" * 32, "tunnel_id": "tunnel_" + "a" * 32,
            "kind": "fixed_openai_tunnel"})
        self.marker = self.fixture / ("active-tunnel_" + "a" * 32 + ".json")
        self.manager.service.write_json(self.marker, {"version": 1, "instance": "d" * 32,
            "pid": identity["pid"], "state": str(self.state)})
        preview = self.manager.recover(self.profile)
        self.manager.recover(self.profile, expected_preview=preview["preview_sha256"])
        self.receipt = next((self.profile / "history").glob("recovery-*/receipt.json"))
        self.archived_marker = Path(self.manager.read_json(self.receipt)["archived_marker"])

    def evidence(self, receipt=None):
        return cutover.retired_web_evidence(self.profile, receipt or self.receipt)

    def checked_services(self, project, plugin, *, web_recovery_receipt):
        self.assertEqual(project, self.project)
        return self.evidence(web_recovery_receipt)

    def plan(self):
        return cutover.preview(self.project, self.plugin, process_check=self.processes,
            services_check=self.checked_services, web_recovery_receipt=self.receipt)

    def apply(self, plan, **kwargs):
        return cutover.apply(self.project, self.plugin, plan["preview_sha256"],
            process_check=self.processes, services_check=self.checked_services,
            web_recovery_receipt=self.receipt, **kwargs)

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def assert_rejected(self, receipt=None):
        before = self.snapshot()
        with self.assertRaises((cutover.CutoverError, ValueError, OSError)):
            self.evidence(receipt)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_receipt_is_read_only_and_default_stopped_gate_is_unchanged(self):
        before = self.snapshot()
        evidence = self.evidence()
        self.assertEqual(evidence["kind"], "explicit_dead_web_recovery_v1")
        self.assertEqual(self.manager.status(self.profile)["status"], "configured")
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_web_not_confirmed_stopped"):
            cutover.service_gate(self.project, PLUGIN)
        with mock.patch.object(cutover.socket, "socket"), mock.patch.object(self.manager, "spawn_child") as spawn:
            self.assertEqual(cutover.service_gate(self.project, PLUGIN,
                web_recovery_receipt=self.receipt), evidence)
            spawn.assert_not_called()
        self.assertEqual(self.manager.read_json(self.state / "status.json")["state"], "ready")
        self.assertEqual(self.snapshot(), before)

    def test_retired_large_status_retains_exact_original_and_other_record_limits(self):
        value = self.manager.read_status_json(self.state / 'status.json')
        value['browser'] = {'events': [
            {'kind': 'public_turn_state', 'counts': [0] * 150} for _ in range(64)]}
        value['unknown'] = {'exact': ['中文😀\r\n', None, 0, False]}
        value['padding'] = ''
        value['padding'] = 'x' * (65536 - len(json.dumps(value, ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')) - 100)
        raw = self.manager.service.json_bytes(value)
        self.assertGreater(len(raw), 65536)

        def retain_fixture_status(original):
            (self.state / 'status.json').write_bytes(original)
            (self.receipt.parent / '4.original').write_bytes(original)
            receipt = self.manager.read_json(self.receipt)
            receipt['files'][str(self.state / 'status.json')] = sha(original)
            preview = {key: receipt[key] for key in
                ('version', 'attempt', 'instance', 'session_sha256', 'files', 'marker')}
            receipt['preview_sha256'] = sha(json.dumps(preview, sort_keys=True).encode('utf-8'))
            self.manager.service.write_json(self.receipt, receipt)

        retain_fixture_status(raw)
        before = self.snapshot()
        self.assertEqual(self.evidence()['kind'], 'explicit_dead_web_recovery_v1')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.manager.read_status_json(self.state / 'status.json'), value)
        self.assertEqual((self.receipt.parent / '4.original').read_bytes(), raw)
        with self.assertRaisesRegex(cutover.CutoverError, 'cutover_invalid_file'):
            cutover.recovery_original_bytes(self.receipt.parent / '4.original')
        # Even a self-consistent synthetic receipt cannot authorize a different
        # oversized encoding; compatibility is for the exact historical writer.
        retain_fixture_status(raw + b'\n')
        self.assert_rejected()

    def test_missing_or_wrong_scope_receipt_never_admits_configured_state(self):
        self.assert_rejected(self.profile / "history/recovery-00000000000000000000000000000000/receipt.json")
        outside = self.fixture / "receipt.json"
        outside.write_bytes(self.receipt.read_bytes())
        self.assert_rejected(outside)

    def test_exact_receipt_schema_flags_phase_and_digest_are_required(self):
        original = self.receipt.read_bytes()
        for changes in ({"version": True}, {"phase": "prepared"}, {"phase": "marker_archived"},
                        {"launched": True}, {"replayed": True}, {"preview_sha256": "0" * 64},
                        {"outcome": "unbound_request_free_stopped_snapshot_retired"}, {"extra": True}):
            with self.subTest(changes=changes):
                self.manager.service.write_json(self.receipt, {**json.loads(original), **changes})
                self.assert_rejected()
                self.receipt.write_bytes(original)

    def test_every_retained_source_backup_pointer_and_marker_stays_bound(self):
        paths = [self.receipt.parent / "0.original", self.receipt.parent / "2.original",
                 self.receipt.parent / "current.json", self.profile / "profile.json",
                 self.profile / "instances" / ("b" * 32 + ".json"), self.state / "session.json",
                 self.state / "status.json", self.state / "connection.json", self.archived_marker]
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                self.assert_rejected()
                path.write_bytes(original)
        alias = self.fixture / "marker-alias"
        os.link(self.archived_marker, alias)
        self.assert_rejected()

    def test_older_selected_receipt_cannot_hide_another_incomplete_retirement(self):
        partial = self.profile / "history" / ("recovery-" + "e" * 32)
        shutil.copytree(self.receipt.parent, partial)
        original = (partial / "receipt.json").read_bytes()
        for phase in ("prepared", "marker_archived"):
            self.manager.service.write_json(partial / "receipt.json", {**json.loads(original), "phase": phase})
            self.assert_rejected()
        (partial / "receipt.json").write_bytes(original)
        (partial / "2.original").unlink()
        self.assert_rejected()

    def test_current_pointer_or_reappearing_marker_is_never_ignored(self):
        pointer = self.profile / "current.json"
        pointer.write_bytes((self.receipt.parent / "current.json").read_bytes())
        self.assert_rejected()
        pointer.unlink()
        self.marker.write_bytes(self.archived_marker.read_bytes())
        self.assert_rejected()

    def test_live_reused_or_unobservable_processes_and_dependencies_reject(self):
        for value in (self.record["worker"], {**self.record["worker"], "birth": "999"}):
            with mock.patch.object(self.manager, "process_identity", return_value=value):
                self.assert_rejected()
        with mock.patch.object(self.manager, "process_identity", side_effect=OSError("private fixture")):
            self.assert_rejected()
        executable = str(self.fixture / "fixture-browser.exe")
        with mock.patch.object(self.manager, "windows_process_entries",
                return_value=[{"pid": 123, "name": Path(executable).name}]), \
                mock.patch.object(self.manager, "process_identity",
                    side_effect=lambda pid: {"executable": executable} if pid == 123 else None):
            self.assert_rejected()

    def test_old_request_listener_must_be_exclusively_reservable(self):
        with cutover.socket.socket() as listener:
            listener.setsockopt(cutover.socket.SOL_SOCKET, cutover.socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", self.port))
            with self.assertRaisesRegex(cutover.CutoverError, "cutover_web_recovery_port_not_free"):
                self.evidence()

    def test_final_observation_rechecks_live_sources(self):
        def change_status(*args):
            path = self.state / "status.json"
            path.write_bytes(path.read_bytes() + b"\n")
        with mock.patch.object(cutover.socket, "socket") as socket_factory:
            socket_factory.return_value.__enter__.return_value.bind.side_effect = change_status
            with self.assertRaisesRegex(cutover.CutoverError, "cutover_web_recovery_changed"):
                self.evidence()

    def test_final_observation_rechecks_preinit_completion(self):
        def add_preinit(*args):
            (self.profile / "history" / ("preinit-recovery-" + "e" * 32 + "-" + "f" * 32)).mkdir()
        with mock.patch.object(cutover.socket, "socket") as socket_factory:
            socket_factory.return_value.__enter__.return_value.bind.side_effect = add_preinit
            with self.assertRaises(ValueError):
                self.evidence()

    def test_case_changed_incomplete_history_is_not_skipped_on_windows(self):
        (self.profile / "history" / ("Recovery-" + "e" * 32)).mkdir()
        self.assert_rejected()

    def test_complete_unbound_history_is_compatible_but_not_selected_as_dead_recovery(self):
        attempt, instance = "9" * 32, "8" * 32
        state = self.profile / "instances" / attempt
        state.mkdir()
        pointer = json.dumps({"version": 1, "attempt": attempt}).encode()
        record = {key: value for key, value in self.record.items()
                  if key not in ("worker", "instance", "session_sha256")}
        record.update(attempt=attempt, phase="starting")
        session = self.manager.read_json(self.state / "session.json")
        session["instance"] = instance
        sources = [self.profile / "profile.json", self.profile / "current.json",
                   self.profile / "instances" / (attempt + ".json"),
                   state / "session.json", state / "status.json"]
        originals = [(self.profile / "profile.json").read_bytes(), pointer,
                     json.dumps(record).encode(), json.dumps(session).encode(),
                     json.dumps({"instance": instance, "state": "stopped", "requests": 0,
                                 "browser": {"active": False}, "transport": {"active_turn": None}}).encode()]
        transaction = self.profile / "history" / ("recovery-" + "7" * 32)
        transaction.mkdir()
        for number, raw in enumerate(originals):
            (transaction / (str(number) + ".original")).write_bytes(raw)
            if number >= 2:
                sources[number].write_bytes(raw)
        (transaction / "current.json").write_bytes(pointer)
        value = {"version": 1, "attempt": attempt, "instance": instance,
                 "session_sha256": sha(originals[3]),
                 "files": {str(path): sha(raw) for path, raw in zip(sources, originals)},
                 "marker": None, "outcome": "unbound_request_free_stopped_snapshot_retired"}
        value["preview_sha256"] = sha(json.dumps(value, sort_keys=True).encode())
        value.update(phase="retired", launched=False, replayed=False)
        self.manager.service.write_json(transaction / "receipt.json", value)
        self.assertEqual(self.evidence()["kind"], "explicit_dead_web_recovery_v1")
        self.assert_rejected(transaction / "receipt.json")

    def test_preview_apply_and_restore_bind_same_receipt_without_new_stop_claim(self):
        before = cutover.runtime_snapshot(self.runtime)
        plan = self.plan()
        self.assertEqual(plan["web_recovery"], self.evidence())
        self.assertEqual(self.apply(plan)["status"], "applied")
        restored = cutover.restore(self.project, self.plugin, plan["preview_sha256"],
            process_check=self.processes, services_check=self.checked_services)
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertEqual(self.manager.status(self.profile)["status"], "configured")

    def test_receipt_change_after_backup_blocks_before_first_runtime_write(self):
        plan = self.plan()
        before = cutover.runtime_snapshot(self.runtime)
        original_backup = cutover.backup_runtime
        def change_after_backup(*args):
            original_backup(*args)
            value = self.manager.read_json(self.receipt)
            self.manager.service.write_json(self.receipt, {**value, "phase": "marker_archived"})
        writer = mock.Mock()
        with mock.patch.object(cutover, "backup_runtime", side_effect=change_after_backup):
            with self.assertRaises(cutover.CutoverError):
                self.apply(plan, writer=writer)
            writer.assert_not_called()
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")

    def test_new_partial_recovery_between_writes_stops_cutover_without_retry(self):
        plan = self.plan()
        writes = []
        def interleaved(path, raw):
            writes.append(path)
            cutover.atomic_bytes(path, raw)
            if len(writes) == 1:
                partial = self.profile / "history" / ("recovery-" + "e" * 32)
                partial.mkdir()
        with self.assertRaises((cutover.CutoverError, OSError)):
            self.apply(plan, writer=interleaved)
        self.assertEqual(len(writes), 1)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")

    def test_restore_cannot_substitute_receipt_or_ignore_current_evidence_drift(self):
        plan = self.plan()
        self.apply(plan)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_identity_invalid"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                process_check=self.processes, services_check=self.checked_services,
                web_recovery_receipt=self.fixture / "receipt.json")
        self.archived_marker.write_bytes(self.archived_marker.read_bytes() + b"\n")
        with self.assertRaises(cutover.CutoverError):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                process_check=self.processes, services_check=self.checked_services)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "applied")

    def test_partial_recovery_after_apply_manifest_write_prevents_completion(self):
        plan = self.plan()
        original_receipt = self.receipt.read_bytes()
        partial = self.profile / "history" / ("recovery-" + "e" * 32)
        manifest = self.runtime / "runtime-manifest.json"
        def interleaved(path, raw):
            cutover.atomic_bytes(path, raw)
            if path == manifest:
                partial.mkdir()
        with self.assertRaises((cutover.CutoverError, OSError)):
            self.apply(plan, writer=interleaved)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertTrue(partial.is_dir())
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")
        self.assertEqual(cutover.runtime_snapshot(transaction / "originals"), plan["runtime_snapshot"])
        self.assertEqual(self.receipt.read_bytes(), original_receipt)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_transaction_exists_no_retry"):
            self.apply(plan)

    def test_partial_recovery_after_restore_manifest_write_prevents_completion(self):
        plan = self.plan()
        self.apply(plan)
        original_receipt = self.receipt.read_bytes()
        partial = self.profile / "history" / ("recovery-" + "e" * 32)
        manifest = self.runtime / "runtime-manifest.json"
        def interleaved(path, raw):
            cutover.atomic_bytes(path, raw)
            if path == manifest:
                partial.mkdir()
        with self.assertRaises((cutover.CutoverError, OSError)):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                process_check=self.processes, services_check=self.checked_services, writer=interleaved)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertTrue(partial.is_dir())
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")
        self.assertEqual(cutover.runtime_snapshot(self.runtime), plan["runtime_snapshot"])
        self.assertEqual(cutover.runtime_snapshot(transaction / "originals"), plan["runtime_snapshot"])
        self.assertEqual(self.receipt.read_bytes(), original_receipt)

    def test_child_error_output_preserves_only_fixed_allowlisted_codes(self):
        for code, expected in (("cutover_web_recovery_port_not_free", "cutover_web_recovery_port_not_free"),
                               ("private fixture must not escape", "cutover_web_recovery_not_verified")):
            output = json.dumps({"status": "blocked", "code": code}).encode()
            with mock.patch.object(cutover.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout=output)):
                with self.assertRaisesRegex(cutover.CutoverError, "^" + expected + "$"):
                    cutover._retired_web_probe(sys.executable, PLUGIN, self.profile, self.receipt)


class LegacyInventoryAdditionTests(unittest.TestCase):
    # Exercise only the inventory-extension cases; the base class retains the
    # unchanged-inventory/schema-v1 compatibility suite.
    ADDITIONS = {"operator_core/web_native_interruption.py", "operator_native_models.py"}
    preview = LegacyRuntimeUpgradeTests.preview
    apply = LegacyRuntimeUpgradeTests.apply
    restore = LegacyRuntimeUpgradeTests.restore

    def setUp(self):
        LegacyRuntimeUpgradeTests.setUp(self)
        self.start_hook = self.project / ".codex/hooks/start-feishu-codex-operator.ps1"
        self.source_hook = self.plugin / "scripts/start-feishu-codex-operator.ps1"
        raw = b"# preserve startup logic\r\n" + self.start_hook.read_bytes() + b"# preserve end\r\n"
        self.source_hook.write_bytes(raw)
        for name in self.ADDITIONS:
            raw = raw.replace(("    '" + name + "',\n").encode(), b"")
            (self.runtime / name).unlink()
        self.start_hook.write_bytes(raw)
        path = self.runtime / "runtime-manifest.json"
        manifest = cutover.read_json(path)
        for name in self.ADDITIONS:
            del manifest["code_files"][name]
        manifest["start_hook_sha256"] = sha(raw)
        path.write_bytes(cutover.canonical_json(manifest))

    def test_added_inventory_apply_restore_preserves_absence_and_hook_bytes(self):
        before = cutover.runtime_snapshot(self.runtime)
        hook_before = self.start_hook.read_bytes()
        plan = self.preview()
        self.assertEqual(plan["schema_version"], 2)
        for name in self.ADDITIONS:
            self.assertEqual(plan["code"][name]["before"], {"sha256": "absent", "size": 0})
        self.apply(plan["preview_sha256"])
        self.assertEqual(cutover.startup_inventory(self.start_hook), set(self.names))
        self.assertEqual(cutover.read_json(self.runtime / "runtime-manifest.json")
                         ["start_hook_sha256"], sha(self.start_hook.read_bytes()))
        self.assertFalse((self.project / ".codex/operator-installation/ownership.json").exists())
        self.restore(plan["preview_sha256"])
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertEqual(self.start_hook.read_bytes(), hook_before)

    def test_unknown_addition_removal_and_partial_addition_remain_blocked(self):
        original = self.source_hook.read_bytes()
        for raw in (original.replace(b"$expectedFiles = @(\n", b"$expectedFiles = @(\n'unknown.py',\n"),
                    original.replace(b"    'operator_main.py',\n", b""),
                    original.replace(b"    'operator_native_models.py',\n", b"")):
            self.source_hook.write_bytes(raw)
            with self.assertRaisesRegex(cutover.CutoverError, "cutover_runtime_inventory_mismatch"):
                self.preview()
            self.assertFalse((self.project / cutover.MAINTENANCE_RELATIVE).exists())

    def test_different_hook_logic_is_not_migrated(self):
        self.source_hook.write_bytes(self.source_hook.read_bytes() + b"changed source logic\n")
        before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_hook_logic_requires_review"):
            self.preview()
        self.assertEqual((cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()), before)

    def test_existing_unowned_added_file_is_not_adopted(self):
        for name in self.ADDITIONS:
            target = self.runtime / name
            target.write_bytes(b"unowned current file")
            with self.assertRaisesRegex(cutover.CutoverError, "cutover_unowned_addition_exists"):
                self.preview()
            self.assertEqual(target.read_bytes(), b"unowned current file")
            target.unlink()

    def test_partial_added_write_restores_absence_without_retrying_apply(self):
        before, hook_before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        plan = self.preview()
        first, second = sorted(self.ADDITIONS)
        def interrupted(path, raw):
            if path == self.runtime / second:
                raise OSError("fixture interrupted new file")
            cutover.atomic_bytes(path, raw)
        with self.assertRaisesRegex(OSError, "fixture interrupted"):
            self.apply(plan["preview_sha256"], writer=interrupted)
        self.assertTrue((self.runtime / first).exists())
        self.assertFalse((self.runtime / second).exists())
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_transaction_exists_no_retry"):
            self.apply(plan["preview_sha256"])
        self.restore(plan["preview_sha256"])
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertEqual(self.start_hook.read_bytes(), hook_before)

    def test_partial_hook_write_is_retained_and_explicitly_restorable(self):
        before, hook_before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        plan = self.preview()
        def interrupted(path, raw):
            cutover.atomic_bytes(path, raw)
            if path == self.start_hook:
                raise OSError("fixture interrupted after hook")
        with self.assertRaisesRegex(OSError, "fixture interrupted"):
            self.apply(plan["preview_sha256"], writer=interrupted)
        self.assertEqual(cutover.startup_inventory(self.start_hook), set(self.names))
        self.restore(plan["preview_sha256"])
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)
        self.assertEqual(self.start_hook.read_bytes(), hook_before)

    def test_later_added_file_edit_blocks_restore_without_writes(self):
        plan = self.preview(); self.apply(plan["preview_sha256"])
        target = self.runtime / sorted(self.ADDITIONS)[0]
        target.write_bytes(b"later user edit")
        before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_target_changed"):
            self.restore(plan["preview_sha256"])
        self.assertEqual((cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()), before)

    def test_later_hook_edit_blocks_restore_without_writes(self):
        plan = self.preview(); self.apply(plan["preview_sha256"])
        self.start_hook.write_bytes(self.start_hook.read_bytes() + b"later user hook edit")
        before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_integration_changed"):
            self.restore(plan["preview_sha256"])
        self.assertEqual((cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()), before)

    def test_unknown_runtime_file_blocks_restore(self):
        plan = self.preview(); self.apply(plan["preview_sha256"])
        (self.runtime / "new-user-file.txt").write_bytes(b"keep this")
        before = cutover.runtime_snapshot(self.runtime)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_target_changed"):
            self.restore(plan["preview_sha256"])
        self.assertEqual(cutover.runtime_snapshot(self.runtime), before)

    def test_missing_and_altered_hook_backups_block_before_restore_writes(self):
        plan = self.preview(); result = self.apply(plan["preview_sha256"])
        transaction = Path(result["transaction"])
        before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        for name in ("startup-hook.original.ps1", "startup-hook.prepared.ps1"):
            backup = transaction / name
            original = backup.read_bytes()
            for damage in (None, b"altered backup"):
                if damage is None:
                    backup.unlink()
                else:
                    backup.write_bytes(damage)
                with self.assertRaisesRegex(cutover.CutoverError, "cutover_backup_changed"):
                    self.restore(plan["preview_sha256"])
                self.assertEqual((cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()), before)
                backup.write_bytes(original)

    def test_restore_interleaved_added_edit_is_terminal_and_preserves_edit(self):
        plan = self.preview(); result = self.apply(plan["preview_sha256"])
        target = self.runtime / sorted(self.ADDITIONS)[0]
        count = 0
        def interleaved(path, raw):
            nonlocal count
            cutover.atomic_bytes(path, raw)
            count += 1
            if count == 1:
                target.write_bytes(b"interleaved user edit")
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_target_changed"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                            process_check=self.processes, services_check=self.services, writer=interleaved)
        self.assertEqual(target.read_bytes(), b"interleaved user edit")
        intent = cutover.read_json(Path(result["transaction"]) / "intent.json")
        self.assertEqual(intent["state"], "failed")
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_terminal_no_retry"):
            self.restore(plan["preview_sha256"])

    def test_hook_edit_during_apply_stops_without_overwriting_it(self):
        plan = self.preview()
        edited = self.start_hook.read_bytes() + b"user edit during apply"
        count = 0
        def interleaved(path, raw):
            nonlocal count
            cutover.atomic_bytes(path, raw)
            count += 1
            if count == 1:
                self.start_hook.write_bytes(edited)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_integration_changed"):
            self.apply(plan["preview_sha256"], writer=interleaved)
        self.assertEqual(count, 1)
        self.assertEqual(self.start_hook.read_bytes(), edited)

    def test_hook_edit_during_restore_is_terminal_and_preserved(self):
        plan = self.preview(); self.apply(plan["preview_sha256"])
        edited = self.start_hook.read_bytes() + b"user edit during restore"
        count = 0
        def interleaved(path, raw):
            nonlocal count
            cutover.atomic_bytes(path, raw)
            count += 1
            if count == 1:
                self.start_hook.write_bytes(edited)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_integration_changed"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                            process_check=self.processes, services_check=self.services, writer=interleaved)
        self.assertEqual(count, 1)
        self.assertEqual(self.start_hook.read_bytes(), edited)
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_restore_terminal_no_retry"):
            self.restore(plan["preview_sha256"])

    def test_missing_and_altered_runtime_backup_prevent_restore_writes(self):
        plan = self.preview(); result = self.apply(plan["preview_sha256"])
        backup = Path(result["transaction"]) / "originals/operator_main.py"
        original = backup.read_bytes()
        before = cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()
        for damage in (None, b"damaged original"):
            if damage is None:
                backup.unlink()
            else:
                backup.write_bytes(damage)
            with self.assertRaisesRegex(cutover.CutoverError, "cutover_backup_changed"):
                self.restore(plan["preview_sha256"])
            self.assertEqual((cutover.runtime_snapshot(self.runtime), self.start_hook.read_bytes()), before)
            backup.write_bytes(original)


    def test_service_change_after_apply_hook_write_preserves_original_manifest(self):
        plan = self.preview()
        manifest = self.runtime / "runtime-manifest.json"
        original_manifest = manifest.read_bytes()
        changed = False
        def services(project, plugin):
            if changed:
                raise cutover.CutoverError("cutover_web_not_confirmed_stopped")
        def interleaved(path, raw):
            nonlocal changed
            cutover.atomic_bytes(path, raw)
            if path == self.start_hook:
                changed = True
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_web_not_confirmed_stopped"):
            cutover.apply(self.project, self.plugin, plan["preview_sha256"],
                process_check=self.processes, services_check=services, writer=interleaved)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        self.assertTrue(changed)
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertEqual(cutover.read_json(transaction / "intent.json")["state"], "failed")
        self.assertEqual(cutover.runtime_snapshot(transaction / "originals"), plan["runtime_snapshot"])

    def test_service_change_after_restore_hook_write_preserves_applied_manifest(self):
        plan = self.preview()
        self.apply(plan["preview_sha256"])
        manifest = self.runtime / "runtime-manifest.json"
        applied_manifest = manifest.read_bytes()
        changed = False
        def services(project, plugin):
            if changed:
                raise cutover.CutoverError("cutover_web_not_confirmed_stopped")
        def interleaved(path, raw):
            nonlocal changed
            cutover.atomic_bytes(path, raw)
            if path == self.start_hook:
                changed = True
        with self.assertRaisesRegex(cutover.CutoverError, "cutover_web_not_confirmed_stopped"):
            cutover.restore(self.project, self.plugin, plan["preview_sha256"],
                process_check=self.processes, services_check=services, writer=interleaved)
        transaction = self.project / cutover.MAINTENANCE_RELATIVE / plan["preview_sha256"]
        intent = cutover.read_json(transaction / "intent.json")
        self.assertTrue(changed)
        self.assertEqual(manifest.read_bytes(), applied_manifest)
        self.assertEqual(intent["state"], "failed")
        self.assertTrue(intent["restore_attempted"])
        self.assertEqual(cutover.runtime_snapshot(transaction / "originals"), plan["runtime_snapshot"])


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
