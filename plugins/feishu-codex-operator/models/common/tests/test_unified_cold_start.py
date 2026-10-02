"""Disposable Windows evidence for the one-shot unified cold launch."""

from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

import operator_model_router as router
import operator_unified_cold_start as cold
import operator_unified_entry_preview as entry_preview
import operator_unified_marker_release as marker_release
import operator_unified_prepare as preparation
from operator_core import windows_config_transaction as transaction


@unittest.skipUnless(os.name == "nt", "Windows identity and ReplaceFileW required")
class UnifiedColdStartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-unified-cold-start-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / ".codex").mkdir(parents=True)
        self.home = self.root / "codex-home"
        self.home.mkdir()
        self.profile = self.project / ".codex/operator-web-service"
        self.profile.mkdir()
        self.router_state = self.project / ".codex/router-with-api-local"
        self.router_state.mkdir()
        (self.router_state / "token").write_text("a" * 64, encoding="ascii")
        (self.router_state / "registry.json").write_text(json.dumps({"version": 2,
            "models": [{"slug": "api/test"}, {"slug": "local/test"}]}), encoding="utf-8")
        self.original = b'model = "gpt-6-sol"\nuser_setting = "keep me"\n'
        if getattr(self, "with_cua_pipe", False):
            self.original += b"[mcp_servers.node_repl.env]\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'one'\n"
        self.config = self.home / "config.toml"
        self.config.write_bytes(self.original)
        self.cache = self.home / "models_cache.json"
        if self._testMethodName not in {
                "test_missing_cache_remains_absent_through_successful_switch",
                "test_cache_created_after_missing_cache_preflight_is_terminal"}:
            self.cache.write_bytes(b'{"old":"catalog"}\n')
        self._recovery()
        self._entry()
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home),
                                           "OPENAI_BASE_URL": ""})
        environment.start()
        self.addCleanup(environment.stop)
        patches = [
            patch.object(entry_preview, "_verify_shortcut", return_value=True),
            patch.object(entry_preview, "verify_owned_entry", return_value="d" * 64),
            patch.object(preparation.web_startup, "assert_desktop_closed"),
            patch.object(preparation.web_service, "route_preview",
                         return_value={"profile_sha256": "b" * 64,
                                       "session_sha256": "c" * 64}),
            patch.object(preparation.web_service, "process_identity",
                         side_effect=lambda pid: {"pid": pid, "birth": "123456789",
                                                  "executable": str(Path(sys.executable).resolve())}),
            patch.object(router, "control", side_effect=self._router_control),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        locked = self._testMethodName in {"test_planned_marker_release_allows_one_cold_launch",
            "test_changed_release_receipt_blocks_consume_before_attempt",
            "test_recreated_native_marker_after_cache_retirement_is_terminal"}
        if locked:
            (self.home / marker_release.MARKER).write_bytes(marker_release.MARKER_BYTES)
        cold.create_workflow(self.project, self.home, Path(sys.executable))
        self._select_entry()
        review = preparation.preview(self.project, self.home, self.router_state,
                                      self.profile, 4318)
        self.assertEqual(review["blockers"],
                         ["unified_native_route_lock_active"] if locked else [])
        preparation.prepare(self.project, self.home, self.router_state,
                            self.profile, 4318, review["review_sha256"])
        self.plan = self.home / preparation.STATE / "plan.json"

    def _release_planned_marker(self):
        review = marker_release.preview(self.plan)
        result = marker_release.release(self.plan, review["review_sha256"])
        self.assertEqual(result["status"], "released_witnessed")
        self.assertFalse((self.home / marker_release.MARKER).exists())
        return result["receipt_sha256"]

    def _router_control(self, state, port):
        self.assertEqual(Path(state), self.router_state)
        self.assertEqual(port, 4318)
        raw = (self.router_state / "registry.json").read_bytes()
        return {"status": "ready", "service": router.service_identity(self.router_state),
                "pid": 4321, "diagnostics": {"registry_sha256": preparation._hash(raw),
                    "web_profile_identity": router.web_profile_identity(self.profile),
                    "web_route_bound": True,
                    "web_route_profile_sha256": "b" * 64,
                    "web_route_session_sha256": "c" * 64,
                    "timing": {"active": 0}}}

    def _recovery(self):
        bundle = self.project / ".codex/operator-native-recovery"
        bundle.mkdir()
        files = {}
        for name in entry_preview.RECOVERY_FILES:
            raw = (_OPERATOR_PLUGIN_ROOT / "scripts" / name).read_bytes()
            (bundle / name).write_bytes(raw)
            files[name] = preparation._hash(raw)
        desktop = self.root / "desktop"
        desktop.mkdir()
        shortcut = desktop / "恢复官方默认路由.lnk"
        shortcut.write_bytes(b"disposable shortcut")
        (bundle / "ownership.json").write_text(json.dumps({"schema_version": 1,
            "project": str(self.project), "shortcut": str(shortcut),
            "shortcut_sha256": preparation._hash(shortcut.read_bytes()),
            "files": files}), encoding="utf-8")

    def _entry(self):
        self.entry = self.project / ".codex/operator-desktop-entry"
        self.entry.mkdir()

    def _select_entry(self):
        script = (_OPERATOR_PLUGIN_ROOT / "scripts/operator_desktop_entry.ps1").read_bytes()
        binary = b"disposable launcher fixture"
        (self.entry / "operator_desktop_entry.ps1").write_bytes(script)
        (self.entry / "Codex拓展入口.exe").write_bytes(binary)
        script_hash = preparation._hash(script)
        (self.entry / "launcher-manifest.json").write_text(json.dumps({
            "schema_version": 1, "native_fallback": "native-only-v1",
            "entry_script_sha256": script_hash,
            "binary_sha256": preparation._hash(binary)}), encoding="utf-8")
        (self.entry / "desktop-entry.json").write_text(json.dumps({
            "schema_version": 1, "mode": "reviewed_startup",
            "startup_bundle": ".codex/operator-unified-startup",
            "entry_script_sha256": script_hash}), encoding="utf-8")

    def test_arm_then_one_witnessed_config_switch(self):
        original_cache = transaction._snapshot(self.cache)
        self.assertEqual(cold.arm(self.plan, Path(sys.executable))["status"],
                         "armed_for_one_cold_launch")
        result = cold.consume(self.plan)
        self.assertEqual(result["status"], "config_switch_witnessed")
        self.assertEqual(result["desktop_acceptance"], "unverified")
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.config.read_bytes(),
                         (self.home / preparation.STATE / "candidate.toml").read_bytes())
        attempt = json.loads((self.home / preparation.STATE / "attempt.json").read_bytes())
        backup = self.home / preparation.STATE / attempt["cache_backup"]
        retired = transaction._snapshot(backup)
        self.assertEqual(retired.data, original_cache.data)
        self.assertEqual(retired.identity, original_cache.identity)
        self.assertEqual(cold.status(self.plan)["status"], "config_switch_witnessed")
        with self.assertRaisesRegex(cold.ColdStartError, "unified_attempt_requires_review"):
            cold.consume(self.plan)

    def test_planned_marker_release_allows_one_cold_launch(self):
        self.assertIn("unified_native_route_lock_active",
                      json.loads(self.plan.read_bytes())["future_arm_blockers"])
        with self.assertRaisesRegex(cold.ColdStartError, "unified_cold_launch_blocked"):
            cold.arm(self.plan, Path(sys.executable))
        receipt = self._release_planned_marker()
        self.assertEqual(cold.arm(self.plan, Path(sys.executable))["status"],
                         "armed_for_one_cold_launch")
        armed = json.loads((self.home / preparation.STATE / "arm.json").read_bytes())
        self.assertEqual(armed["marker_release_sha256"], receipt)
        self.assertEqual(cold.consume(self.plan)["status"], "config_switch_witnessed")

    def test_changed_release_receipt_blocks_consume_before_attempt(self):
        self._release_planned_marker()
        cold.arm(self.plan, Path(sys.executable))
        receipt = self.home / preparation.STATE / marker_release.STATE / "receipt.json"
        receipt.write_bytes(receipt.read_bytes() + b" ")
        with self.assertRaisesRegex(cold.ColdStartError, "unified_arm_changed"):
            cold.consume(self.plan)
        value = json.loads(receipt.read_bytes())
        receipt.write_text(json.dumps({**value, "backup_sha256": "0" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(cold.ColdStartError,
                                    "unified_marker_release_unverified"):
            cold.consume(self.plan)
        self.assertFalse((self.home / preparation.STATE / "attempt.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_recreated_native_marker_after_cache_retirement_is_terminal(self):
        self._release_planned_marker()
        cold.arm(self.plan, Path(sys.executable))
        original_rename = cold.os.rename
        def reintroduce_marker(source, target):
            original_rename(source, target)
            (self.home / marker_release.MARKER).write_bytes(marker_release.MARKER_BYTES)
        with patch.object(cold.os, "rename", side_effect=reintroduce_marker):
            with self.assertRaisesRegex(cold.ColdStartError,
                                        "unified_marker_release_unverified"):
                cold.consume(self.plan)
        self.assertTrue((self.home / preparation.STATE / "attempt.json").exists())
        self.assertFalse((self.home / preparation.STATE / "completion.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.cache.exists())

    def test_changed_consumer_source_blocks_before_attempt(self):
        cold.arm(self.plan, Path(sys.executable))
        original_hash = cold._hash_file
        def changed(path):
            if Path(path).name == "operator_unified_cold_start.py":
                return "0" * 64
            return original_hash(path)
        with patch.object(cold, "_hash_file", side_effect=changed):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_arm_changed"):
                cold.consume(self.plan)
        self.assertFalse((self.home / preparation.STATE / "attempt.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue(self.cache.exists())

    def test_workflow_pins_consumer_source_and_native_entry_cannot_arm(self):
        entry_file = self.entry / "desktop-entry.json"
        selected = json.loads(entry_file.read_bytes())
        entry_file.write_text(json.dumps({**selected, "mode": "native"}), encoding="utf-8")
        with self.assertRaisesRegex(cold.ColdStartError,
                                    "unified_entry_not_selected_or_changed"):
            cold.arm(self.plan, Path(sys.executable))
        entry_file.write_text(json.dumps(selected), encoding="utf-8")
        original_hash = cold._hash_file
        def changed(path):
            if Path(path).name == "operator_unified_cold_start.py":
                return "0" * 64
            return original_hash(path)
        with patch.object(cold, "_hash_file", side_effect=changed):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_workflow_changed"):
                cold.arm(self.plan, Path(sys.executable))
        self.assertFalse((self.home / preparation.STATE / "arm.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_changed_cache_after_arm_blocks_without_retirement(self):
        cold.arm(self.plan, Path(sys.executable))
        self.cache.write_bytes(b'{"different":"catalog"}')
        with self.assertRaisesRegex(cold.ColdStartError, "unified_prepared_evidence_changed"):
            cold.consume(self.plan)
        self.assertFalse((self.home / preparation.STATE / "attempt.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)

    def _child_cache_writer(self, path):
        code = ("import pathlib,sys\n"
                "try:\n"
                " with pathlib.Path(sys.argv[1]).open('r+b') as f:\n"
                "  first=f.read(1); f.seek(0); f.write(first)\n"
                "except OSError as exc:\n"
                " print(exc.errno); sys.exit(2)\n")
        return subprocess.run([sys.executable, "-B", "-c", code, str(path)],
            capture_output=True, text=True, timeout=10)

    def test_cache_writer_is_denied_in_preflight_retirement_gap_and_until_completion(self):
        original_cache = transaction._snapshot(self.cache)
        cold.arm(self.plan, Path(sys.executable))
        original_record = cold._record
        writer_results = []
        def observe_boundary(path, value):
            if path.name == "completion.json":
                backup = path.parent / value["cache_backup"]
                writer_results.append(self._child_cache_writer(backup))
            original_record(path, value)
            if path.name == "attempt.json":
                writer_results.append(self._child_cache_writer(self.cache))
        with patch.object(cold, "_record", side_effect=observe_boundary):
            self.assertEqual(cold.consume(self.plan)["status"], "config_switch_witnessed")
        self.assertEqual(len(writer_results), 2)
        for result in writer_results:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout.strip(), "13")
        attempt = json.loads((self.plan.parent / "attempt.json").read_bytes())
        backup = self.plan.parent / attempt["cache_backup"]
        snapshot = transaction._snapshot(backup)
        self.assertEqual(snapshot.data, original_cache.data)
        self.assertEqual(snapshot.identity, original_cache.identity)
        # No guard survives the completed invocation.
        self.assertEqual(self._child_cache_writer(backup).returncode, 0)

    def test_existing_cache_writer_blocks_before_attempt_and_leaves_config_untouched(self):
        cold.arm(self.plan, Path(sys.executable))
        with self.cache.open("r+b"):
            with self.assertRaisesRegex(transaction.TransactionFailure, "open_32"):
                cold.consume(self.plan)
        self.assertFalse((self.plan.parent / "attempt.json").exists())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.cache.read_bytes(), b'{"old":"catalog"}\n')

    def test_missing_cache_remains_absent_through_successful_switch(self):
        self.assertFalse(json.loads(self.plan.read_bytes())["cache"]["existed"])
        cold.arm(self.plan, Path(sys.executable))
        self.assertEqual(cold.consume(self.plan)["status"], "config_switch_witnessed")
        self.assertFalse(self.cache.exists())
        attempt = json.loads((self.plan.parent / "attempt.json").read_bytes())
        self.assertFalse((self.plan.parent / attempt["cache_backup"]).exists())

    def test_cache_created_after_missing_cache_preflight_is_terminal(self):
        cold.arm(self.plan, Path(sys.executable))
        original_record = cold._record
        def create_after_preflight(path, value):
            original_record(path, value)
            if path.name == "attempt.json":
                self.cache.write_bytes(b'{"appeared":"catalog"}\n')
        with patch.object(cold, "_record", side_effect=create_after_preflight):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_cache_changed"):
                cold.consume(self.plan)
        self.assertEqual(self.cache.read_bytes(), b'{"appeared":"catalog"}\n')
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue((self.plan.parent / "attempt.json").exists())
        self.assertFalse((self.plan.parent / "completion.json").exists())
        self.assertEqual(cold.status(self.plan)["status"], "attempt_requires_review")

    def test_equal_cache_bytes_with_replaced_identity_after_preflight_are_terminal(self):
        original_cache = transaction._snapshot(self.cache)
        cold.arm(self.plan, Path(sys.executable))
        old_path = self.root / "original-cache.json"
        original_record = cold._record
        def replace_after_preflight(path, value):
            original_record(path, value)
            if path.name == "attempt.json":
                os.rename(self.cache, old_path)
                self.cache.write_bytes(original_cache.data)
        with patch.object(cold, "_record", side_effect=replace_after_preflight):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_cache_changed"):
                cold.consume(self.plan)
        self.assertEqual(transaction._snapshot(old_path).identity, original_cache.identity)
        self.assertNotEqual(transaction._snapshot(self.cache).identity, original_cache.identity)
        self.assertEqual(self.cache.read_bytes(), original_cache.data)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue((self.plan.parent / "attempt.json").exists())
        self.assertFalse((self.plan.parent / "completion.json").exists())
        with self.assertRaisesRegex(cold.ColdStartError, "unified_attempt_requires_review"):
            cold.consume(self.plan)

    def test_cache_path_swap_at_rename_preserves_both_files_and_stops_before_config_write(self):
        original_cache = transaction._snapshot(self.cache)
        cold.arm(self.plan, Path(sys.executable))
        old_path = self.root / "original-cache.json"
        original_rename = cold.os.rename
        def replace_at_move(source, target):
            original_rename(source, old_path)
            self.cache.write_bytes(b'{"new":"catalog"}\n')
            original_rename(source, target)
        with patch.object(cold.os, "rename", side_effect=replace_at_move):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_cache_move_uncertain"):
                cold.consume(self.plan)
        attempt = json.loads((self.plan.parent / "attempt.json").read_bytes())
        self.assertEqual((self.plan.parent / attempt["cache_backup"]).read_bytes(),
                         b'{"new":"catalog"}\n')
        self.assertEqual(transaction._snapshot(old_path).identity, original_cache.identity)
        self.assertEqual(old_path.read_bytes(), original_cache.data)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(cold.status(self.plan)["status"], "attempt_requires_review")
        self.assertFalse((self.plan.parent / "completion.json").exists())

    def test_crash_after_cache_move_is_terminal_and_preserves_evidence(self):
        cold.arm(self.plan, Path(sys.executable))
        original_rename = cold.os.rename
        def crash_after_move(source, target):
            original_rename(source, target)
            raise OSError("simulated process exit after cache retirement")
        with patch.object(cold.os, "rename", side_effect=crash_after_move):
            with self.assertRaises(OSError):
                cold.consume(self.plan)
        attempt = self.home / preparation.STATE / "attempt.json"
        self.assertTrue(attempt.exists())
        backup = self.home / preparation.STATE / json.loads(attempt.read_bytes())["cache_backup"]
        self.assertTrue(backup.exists())
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(cold.status(self.plan)["status"], "attempt_requires_review")
        with self.assertRaisesRegex(cold.ColdStartError, "unified_attempt_requires_review"):
            cold.consume(self.plan)
        command = subprocess.run([sys.executable, "-B", str(_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_unified_cold_start.py"), "consume", "--plan", str(self.plan)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(command.returncode, 1)
        public = json.loads(command.stdout)
        self.assertEqual(public["change_state"], "uncertain")
        self.assertIsNone(public["configuration_changed"])
        self.assertEqual(public["next_action"], "inspect_status")

    def test_native_marker_and_changed_router_birth_block_arm(self):
        marker = self.home / "operator-native-route-only"
        marker.write_bytes(b"recovery lock")
        with self.assertRaisesRegex(cold.ColdStartError, "unified_cold_launch_blocked"):
            cold.arm(self.plan, Path(sys.executable))
        marker.unlink()
        original_identity = preparation.web_service.process_identity
        with patch.object(preparation.web_service, "process_identity",
                          side_effect=lambda pid: {**original_identity(pid), "birth": "987654321"}):
            with self.assertRaisesRegex(cold.ColdStartError, "unified_prepared_evidence_changed"):
                cold.arm(self.plan, Path(sys.executable))
        self.assertFalse((self.home / preparation.STATE / "arm.json").exists())

    def test_old_router_without_exact_binding_digests_and_changed_binding_block_arm(self):
        original_control = self._router_control
        def old_control(state, port):
            value = original_control(state, port)
            value["diagnostics"].pop("web_route_session_sha256")
            return value
        with patch.object(router, "control", side_effect=old_control):
            with self.assertRaisesRegex(cold.ColdStartError,
                                        "unified_cold_launch_blocked"):
                cold.arm(self.plan, Path(sys.executable))
        def different_control(state, port):
            value = original_control(state, port)
            value["diagnostics"]["web_route_session_sha256"] = "d" * 64
            return value
        with patch.object(router, "control", side_effect=different_control):
            with self.assertRaisesRegex(cold.ColdStartError,
                                        "unified_cold_launch_blocked"):
                cold.arm(self.plan, Path(sys.executable))
        self.assertFalse((self.home / preparation.STATE / "arm.json").exists())

    def test_windows_venv_launcher_parent_and_base_child_are_bound(self):
        venv_root = self.root / "disposable-venv"
        venv.EnvBuilder(with_pip=False).create(venv_root)
        venv_python = venv_root / "Scripts/python.exe"
        result = subprocess.run([str(venv_python), "-B", "-c",
            "import json,sys; print(json.dumps([sys.executable,sys._base_executable]))"],
            capture_output=True, text=True, timeout=15, check=True)
        observed_python, observed_base = map(Path, json.loads(result.stdout))
        self.assertEqual(observed_python, venv_python)
        self.assertNotEqual(observed_python, observed_base)
        worker = {"pid": 5678, "birth": "200", "executable": str(observed_base)}
        launcher = {"pid": 1234, "birth": "100", "executable": str(venv_python)}
        def identity(pid):
            return {5678: worker, 1234: launcher}.get(pid)
        with patch.object(cold.sys, "executable", str(venv_python)), \
                patch.object(cold.sys, "_base_executable", str(observed_base)), \
                patch.object(cold.web_service, "process_identity", side_effect=identity), \
                patch.object(cold.web_service, "parent_pid", return_value=1234):
            lineage = cold._launcher_identity({"router": {"process": worker}}, venv_python)
            self.assertEqual(lineage["mode"], "venv_launcher_child")
            self.assertEqual(lineage["launcher"], launcher)
            self.assertEqual(lineage["worker"], worker)
            self.assertRegex(lineage["python_sha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(lineage["base_python_sha256"], r"^[a-f0-9]{64}$")
            with patch.object(cold.web_service, "parent_pid", return_value=9999):
                with self.assertRaisesRegex(cold.ColdStartError,
                                            "unified_python_process_lineage_changed"):
                    cold._launcher_identity({"router": {"process": worker}}, venv_python)


if __name__ == "__main__":
    unittest.main()
