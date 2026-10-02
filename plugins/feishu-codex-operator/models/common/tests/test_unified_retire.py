"""Disposable recovery and retirement evidence for unified cold launch."""

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
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_unified_cold_start as cold_tests
import operator_unified_cold_start as cold
import operator_unified_marker_release as marker_release
import operator_unified_retire as retire
import operator_uninstall as uninstall


POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(),
                     "Windows recovery transaction required")
class UnifiedRetirementTests(unittest.TestCase):
    def test_current_desktop_blocks_retirement_with_fixed_local_code(self):
        from operator_core.responses_capabilities import RouterError
        with patch("operator_web_startup.assert_desktop_closed",
                   side_effect=RouterError("web_startup_close_desktop_before_activation")), \
                patch("operator_web_service.process_identity") as process:
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_desktop_not_closed"):
                retire._stopped({"router": {"process": {"pid": 1234}, "port": 4318}},
                                require_desktop_closed=True)
            process.assert_not_called()

    def test_reviewed_preference_delta_checks_exact_toml_scope_and_values(self):
        original = (b'model = "native-before"\n[desktop]\nconversationDetailMode = "STEPS_PROSE"\n'
                    b"[mcp_servers.node_repl.env]\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'one'\n")
        current = original.replace(b'native-before', b'native-after').replace(b'STEPS_PROSE', b'STEPS_COMMANDS').replace(b"'one'", b"'two'")
        self.assertEqual(retire._config_delta(original, current), "desktop_preferences_only")
        for before, after in ((original.replace(b'[desktop]', b'[unrelated]'), current.replace(b'[desktop]', b'[unrelated]')),
                              (original, current + b'approval_policy="never"\n'),
                              (original, current.replace(b'[desktop]', b'[different]'))):
            with self.assertRaises(retire.RetireError):
                retire._config_delta(before, after)

    def fixture(self, *, locked=False, pipe=False):
        name = ("test_planned_marker_release_allows_one_cold_launch" if locked
                else "test_arm_then_one_witnessed_config_switch")
        value = cold_tests.UnifiedColdStartTests(name)
        value.with_cua_pipe = pipe
        value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def recover(self, fixture):
        script = _OPERATOR_PLUGIN_ROOT / "scripts/restore-codex-official-route.ps1"
        env = {**os.environ, "CODEX_HOME": str(fixture.home)}
        env.pop("OPENAI_BASE_URL", None)
        result = subprocess.run([str(POWERSHELL), "-NoLogo", "-NoProfile",
            "-ExecutionPolicy", "Bypass", "-File", str(script), "-CodexHome",
            str(fixture.home), "-ProjectRoot", str(fixture.project), "-Apply", "-Json"],
            env=env, capture_output=True, timeout=30)
        value = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(result.returncode, 0, value)
        self.assertEqual(value["status"], "completed", value)
        self.assertEqual(value["warnings"], [])
        return Path(value["backup"]) / "intent.json"

    def retirement(self, fixture, recovery):
        # The fake router birth used by the cold-launch fixture is explicitly
        # treated as stopped here; all file and receipt checks remain real.
        with patch.object(retire, "_stopped") as stopped:
            review = retire.preview(fixture.plan, recovery)
            result = retire.retire(fixture.plan, recovery, review["review_sha256"])
            status = retire.verify_retired(fixture.plan)
            self.assertTrue(stopped.called)
        return review, result, status

    def test_prepared_locked_plan_retired_after_entry_recovery(self):
        fixture = self.fixture(locked=True)
        old_cache = fixture.cache.read_bytes()
        recovery = self.recover(fixture)
        self.assertEqual(json.loads(recovery.read_bytes())["files"][0]["name"],
                         "desktop-entry.json")
        review, result, status = self.retirement(fixture, recovery)
        self.assertEqual(review["phase"], "prepared_recovered")
        self.assertEqual(result["status"], "retired_witnessed")
        self.assertEqual(status["phase"], "prepared_recovered")
        self.assertEqual(fixture.cache.read_bytes(), old_cache)
        self.assertEqual(fixture.config.read_bytes(), fixture.original)
        self.assertEqual((fixture.home / marker_release.MARKER).read_bytes(),
                         marker_release.MARKER_BYTES)
        with patch.object(retire, "_stopped"):
            uninstall.inspect_unified_candidate(fixture.config)
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_already_recorded"):
                retire.preview(fixture.plan, recovery)

    def test_armed_plan_retired_after_marker_and_entry_recovery(self):
        fixture = self.fixture(locked=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        recovery = self.recover(fixture)
        review, _, _ = self.retirement(fixture, recovery)
        self.assertEqual(review["phase"], "armed_recovered")
        self.assertEqual(fixture.cache.read_bytes(), b'{"old":"catalog"}\n')
        self.assertEqual(fixture.config.read_bytes(), fixture.original)

    def test_witnessed_switch_retired_without_restoring_edited_cache(self):
        fixture = self.fixture(locked=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        edited = b'{"new":"user-edited-catalog"}\n'
        fixture.cache.write_bytes(edited)
        recovery = self.recover(fixture)
        review, _, status = self.retirement(fixture, recovery)
        self.assertEqual(review["phase"], "active_witnessed_recovered")
        self.assertEqual(status["phase"], "active_witnessed_recovered")
        self.assertEqual(fixture.cache.read_bytes(), edited)
        attempt = json.loads((fixture.plan.parent / "attempt.json").read_bytes())
        self.assertEqual((fixture.plan.parent / attempt["cache_backup"]).read_bytes(),
                         b'{"old":"catalog"}\n')
        self.assertEqual(fixture.config.read_bytes(), fixture.original)

    def test_uncertain_attempt_remains_terminal_after_recovery(self):
        fixture = self.fixture(locked=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        with patch.object(cold, "_retire_cache", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                cold.consume(fixture.plan)
        recovery = self.recover(fixture)
        with patch.object(retire, "_stopped"):
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_attempt_unwitnessed"):
                retire.preview(fixture.plan, recovery)
        self.assertFalse((fixture.plan.parent / "retirement").exists())

    def test_completed_recovery_retains_reviewed_desktop_pipe_change(self):
        fixture = self.fixture(locked=True, pipe=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        saved = (fixture.plan.parent / "candidate.toml").read_bytes()
        changed = saved.replace(b"DIRECTORY = 'one'", b"DIRECTORY = 'two'")
        fixture.config.write_bytes(changed)
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        intent = json.loads((fixture.plan.parent / "retirement/intent.json").read_bytes())
        self.assertEqual(intent["review"]["config_delta"], "cua_pipe_only")
        self.assertEqual(fixture.config.read_bytes(), fixture.original.replace(b"'one'", b"'two'"))
        self.assertEqual((fixture.plan.parent / "candidate.toml").read_bytes(), saved)
        self.assertEqual((recovery.parent / "config.toml.before").read_bytes(), changed)

    def test_later_native_pipe_has_new_review_without_rewriting_recovery(self):
        fixture = self.fixture(locked=True, pipe=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        candidate = (fixture.plan.parent / "candidate.toml").read_bytes()
        fixture.config.write_bytes(candidate.replace(b"'one'", b"'two'"))
        recovery = self.recover(fixture)
        historical = {path.name: path.read_bytes() for path in recovery.parent.iterdir()}
        recovered = fixture.config.read_bytes()
        current = recovered.replace(b"'two'", b"'three'")
        fixture.config.write_bytes(current)
        review, _, status = self.retirement(fixture, recovery)
        intent = json.loads((fixture.plan.parent / "retirement/intent.json").read_bytes())
        self.assertEqual(intent["review"]["config_sha256"], retire._hash(current))
        self.assertEqual(intent["review"]["recovery"]["config_recovered_sha256"],
                         retire._hash(recovered))
        self.assertEqual(intent["review"]["recovery"]["post_recovery_config_delta"],
                         "cua_pipe_only")
        self.assertEqual(status["recovery"], intent["review"]["recovery"])
        self.assertEqual(review["phase"], "active_witnessed_recovered")
        self.assertEqual(fixture.config.read_bytes(), current)
        self.assertEqual({path.name: path.read_bytes() for path in recovery.parent.iterdir()}, historical)
        self.assertEqual((fixture.plan.parent / "candidate.toml").read_bytes(), candidate)
        with patch.object(retire, "_stopped"):
            archival = retire.archive_preview(fixture.plan)
            retire.archive_retired(fixture.plan, archival["review_sha256"])
        self.assertEqual(fixture.config.read_bytes(), current)
        self.assertEqual(retire.archive_status(fixture.home)["status"], "retained")

    def test_later_pipe_review_does_not_admit_a_model_preference(self):
        fixture = self.fixture(pipe=True)
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        recovery = self.recover(fixture)
        current = fixture.config.read_bytes().replace(b"'one'", b"'two'")
        current = current.replace(b'gpt-6-sol', b'gpt-6-luna')
        fixture.config.write_bytes(current)
        with patch.object(retire, "_stopped"):
            with self.assertRaisesRegex(retire.RetireError, "post_recovery_config_changed"):
                retire.preview(fixture.plan, recovery)
        self.assertFalse((fixture.plan.parent / "retirement").exists())
        self.assertEqual(fixture.config.read_bytes(), current)

    def test_later_pipe_still_requires_exact_completed_recovery_after_hash(self):
        fixture = self.fixture(pipe=True)
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        recovery = self.recover(fixture)
        receipt = json.loads(recovery.read_bytes())
        row = next(row for row in receipt["files"] if row["name"] == "config.toml")
        row["after_sha256"] = "e" * 64
        recovery.write_text(json.dumps(receipt), encoding="utf-8")
        fixture.config.write_bytes(fixture.config.read_bytes().replace(b"'one'", b"'two'"))
        with patch.object(retire, "_stopped"):
            with self.assertRaisesRegex(retire.RetireError, "config_recovery_invalid"):
                retire.preview(fixture.plan, recovery)
        self.assertFalse((fixture.plan.parent / "retirement").exists())

    def test_later_pipe_change_after_intent_remains_terminal(self):
        fixture = self.fixture(pipe=True)
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        recovery = self.recover(fixture)
        fixture.config.write_bytes(fixture.config.read_bytes().replace(b"'one'", b"'two'"))
        record = retire._record

        def change_after_intent(path, value):
            record(path, value)
            if path == fixture.plan.parent / "retirement/intent.json":
                fixture.config.write_bytes(fixture.config.read_bytes().replace(b"'two'", b"'three'"))

        with patch.object(retire, "_stopped"):
            review = retire.preview(fixture.plan, recovery)
            with patch.object(retire, "_record", side_effect=change_after_intent):
                with self.assertRaisesRegex(retire.RetireError, "changed_after_intent"):
                    retire.retire(fixture.plan, recovery, review["review_sha256"])
            with self.assertRaisesRegex(retire.RetireError, "already_recorded"):
                retire.preview(fixture.plan, recovery)
        self.assertTrue((fixture.plan.parent / "retirement/intent.json").exists())
        self.assertFalse((fixture.plan.parent / "retirement/receipt.json").exists())
        self.assertEqual(fixture.config.read_bytes(), fixture.original.replace(b"'one'", b"'three'"))

    def test_pipe_exception_does_not_admit_other_changes(self):
        fixture = self.fixture(pipe=True)
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        fixture.config.write_bytes(fixture.config.read_bytes().replace(b"'one'", b"'two'")
                                   + b'\n[analytics]\nenabled=false\n')
        recovery = self.recover(fixture)
        with patch.object(retire, "_stopped"):
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_config_changed"):
                retire.preview(fixture.plan, recovery)
        self.assertFalse((fixture.plan.parent / "retirement").exists())

    def test_pipe_change_after_review_invalidates_commit(self):
        fixture = self.fixture(pipe=True)
        recovery = self.recover(fixture)
        with patch.object(retire, "_stopped"):
            review = retire.preview(fixture.plan, recovery)
            fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'two'"))
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_review_changed"):
                retire.retire(fixture.plan, recovery, review["review_sha256"])
        self.assertFalse((fixture.plan.parent / "retirement").exists())

    def test_changed_recovery_receipt_and_native_config_fail_closed(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        with patch.object(retire, "_stopped"):
            review = retire.preview(fixture.plan, recovery)
            receipt = recovery.parent / "completed.json"
            original_receipt = receipt.read_bytes()
            receipt.write_bytes(original_receipt.replace(b"desktop-entry.json", b"other-entry.json"))
            with self.assertRaises(retire.RetireError):
                retire.preview(fixture.plan, recovery)
            receipt.write_bytes(original_receipt)
            fixture.config.write_bytes(fixture.original + b"# later edit\n")
            with self.assertRaisesRegex(retire.RetireError, "unified_retire_config_changed"):
                retire.retire(fixture.plan, recovery, review["review_sha256"])
        self.assertFalse((fixture.plan.parent / "retirement").exists())

    def test_archive_preserves_all_retired_evidence_and_allows_fresh_preparation(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        before = retire._tree(fixture.plan.parent)
        with patch.object(retire, "_stopped"):
            review = retire.archive_preview(fixture.plan)
            result = retire.archive_retired(fixture.plan, review["review_sha256"])
        self.assertEqual(result["status"], "archived_witnessed")
        self.assertFalse(fixture.plan.parent.exists())
        root = fixture.home / retire.ARCHIVE
        archived = next(root.iterdir()) / "evidence"
        self.assertEqual(retire._tree(archived), before)
        self.assertEqual(retire.archive_status(fixture.home), {"status": "retained", "generations": 1})
        self.assertEqual(fixture.config.read_bytes(), fixture.original)
        uninstall.inspect_unified_candidate(fixture.config)
        (archived / "before.toml").write_bytes(b"altered")
        self.assertEqual(retire.archive_status(fixture.home)["status"], "uncertain")
        with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict, "retired_archive_requires_review"):
            uninstall.inspect_unified_candidate(fixture.config)

    def test_archived_entry_lookup_keeps_current_and_historical_evidence_distinct(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        rows = json.loads(recovery.read_bytes())["files"]
        row = next(row for row in rows if row["name"] == "desktop-entry.json")
        with patch.object(retire, "_stopped"):
            archival = retire.archive_preview(fixture.plan)
            retire.archive_retired(fixture.plan, archival["review_sha256"])
        status = retire.archived_entry_status(fixture.plan, fixture.project,
            row["before_sha256"], row["after_sha256"])
        self.assertEqual(status["status"], "archived_retired_entry_witnessed")
        self.assertFalse(status["historical_entry_only"])
        entry = fixture.entry / "desktop-entry.json"
        original = entry.read_bytes()
        entry.write_bytes(original + b" ")
        with self.assertRaisesRegex(retire.RetireError, "current_changed"):
            retire.archived_entry_status(fixture.plan, fixture.project,
                row["before_sha256"], row["after_sha256"])
        historical = retire.archived_entry_status(fixture.plan, fixture.project,
            row["before_sha256"], row["after_sha256"], historical=True)
        self.assertEqual(historical["archive_witness_sha256"], status["archive_witness_sha256"])
        self.assertTrue(historical["historical_entry_only"])
        fixture.plan.parent.mkdir()
        with self.assertRaisesRegex(retire.RetireError, "active_plan_conflict"):
            retire.archived_entry_status(fixture.plan, fixture.project,
                row["before_sha256"], row["after_sha256"], historical=True)
        self.assertEqual(entry.read_bytes(), original + b" ")

    def test_failed_archive_move_blocks_new_attempt_and_keeps_original(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        before = retire._tree(fixture.plan.parent)
        with patch.object(retire, "_stopped"):
            review = retire.archive_preview(fixture.plan)
            with patch.object(retire.os, "rename", side_effect=OSError("synthetic move failure")):
                with self.assertRaises(OSError):
                    retire.archive_retired(fixture.plan, review["review_sha256"])
            with self.assertRaisesRegex(retire.RetireError, "retired_archive_requires_review"):
                retire.archive_retired(fixture.plan, review["review_sha256"])
        self.assertEqual(retire._tree(fixture.plan.parent), before)
        self.assertEqual(retire.archive_status(fixture.home)["status"], "uncertain")

    def test_changed_archive_preview_does_not_move_any_evidence(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        with patch.object(retire, "_stopped"):
            review = retire.archive_preview(fixture.plan)
            (fixture.plan.parent / "extra-reviewed-note.txt").write_bytes(b"new evidence")
            with self.assertRaisesRegex(retire.RetireError, "retired_archive_review_changed"):
                retire.archive_retired(fixture.plan, review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / retire.ARCHIVE).exists())

    def test_uninstall_requires_terminal_retirement_receipt(self):
        fixture = self.fixture()
        recovery = self.recover(fixture)
        with patch.object(retire, "_stopped"):
            with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict,
                                        "unified_activation_requires_review_before_uninstall"):
                uninstall.inspect_unified_candidate(fixture.config)
            review = retire.preview(fixture.plan, recovery)
            retire.retire(fixture.plan, recovery, review["review_sha256"])
            uninstall.inspect_unified_candidate(fixture.config)
            entry = fixture.entry / "desktop-entry.json"
            native = entry.read_bytes()
            changed = json.loads(native)
            changed["mode"] = "reviewed_startup"
            entry.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict,
                                        "unified_activation_requires_review_before_uninstall"):
                uninstall.inspect_unified_candidate(fixture.config)
            entry.write_bytes(native)
            (fixture.plan.parent / "retirement/receipt.json").write_bytes(b"{}")
            with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict,
                                        "unified_activation_requires_review_before_uninstall"):
                uninstall.inspect_unified_candidate(fixture.config)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 command facade required")
    def test_public_status_command_is_read_only_for_missing_plan(self):
        with tempfile.TemporaryDirectory(prefix="operator-retire-cli-") as temporary:
            root = Path(temporary)
            plan = root / "operator-unified-activation/plan.json"
            before = list(root.rglob("*"))
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File",
                str(_OPERATOR_PLUGIN_ROOT / "scripts/codex-operator.ps1"), "models",
                "unified-retire", "status", "--plan", str(plan)],
                capture_output=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "unavailable")
            self.assertEqual(list(root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
