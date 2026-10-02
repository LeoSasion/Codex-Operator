"""Disposable exact-plan withdrawal, current-setting retention and crash gates."""
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import json
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_unified_cold_start as cold_tests
import operator_model_router as router
import operator_unified_prepare as preparation
import operator_unified_supersede as supersede
import operator_unified_withdraw as withdraw


@unittest.skipUnless(os.name == "nt", "Windows file identity and sharing required")
class UnifiedWithdrawTests(unittest.TestCase):
    def fixture(self):
        fixture = cold_tests.UnifiedColdStartTests("test_planned_marker_release_allows_one_cold_launch")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def rewrite_plan(self, fixture, edit):
        plan = json.loads(fixture.plan.read_bytes())
        edit(plan)
        raw = supersede._json(plan)
        fixture.plan.write_bytes(raw)
        (fixture.plan.parent / "journal.json").write_bytes(supersede._json({
            "schema_version": 1, "phase": "prepared_not_armed", "plan_sha256": supersede._hash(raw)}))

    def generation(self, fixture):
        return next((fixture.home / supersede.ROOT).iterdir())

    def empty_fixture(self):
        fixture = self.fixture()
        # Only the disposable fixture's known preparation files are removed.
        self.assertEqual({p.name for p in fixture.plan.parent.iterdir()},
                         {"plan.json", "journal.json", "before.toml", "candidate.toml", "cache-before.bin"})
        for name in ("plan.json", "journal.json", "before.toml", "candidate.toml", "cache-before.bin"):
            (fixture.plan.parent / name).unlink()
        fixture.failure = fixture.project / "failed-prepare.json"
        fixture.failure.write_bytes(json.dumps(withdraw.EMPTY_FAILURE, indent=2).encode() + b"\n")
        fixture.failure_sha = supersede._hash(fixture.failure.read_bytes())
        return fixture

    def empty_preview(self, fixture):
        return withdraw.preview_empty_allocation(fixture.project, fixture.home,
                                                fixture.failure, fixture.failure_sha)

    def empty_withdraw(self, fixture, preview):
        return withdraw.withdraw_empty_allocation(fixture.project, fixture.home,
            fixture.failure, fixture.failure_sha, preview["review_sha256"])

    def test_empty_allocation_preserves_exact_directory_failure_bytes_and_current_settings(self):
        fixture = self.empty_fixture()
        fixture.config.write_bytes(b'model="gpt-6.1-sol"\nmodel_reasoning_effort="ultra"\n')
        original = {p: p.read_bytes() for p in [fixture.config, fixture.cache, fixture.failure,
                    fixture.home / "operator-native-route-only", *fixture.entry.iterdir()]}
        identity = withdraw.empty_allocation_directory_identity(fixture.plan.parent)
        with patch.object(router, "control", side_effect=AssertionError("no service probe")), \
                patch.object(preparation, "_readiness", side_effect=AssertionError("no prepare")), \
                patch.object(preparation.web_startup, "assert_desktop_closed", side_effect=AssertionError("no Desktop")), \
                patch.object(withdraw.os, "rename", side_effect=AssertionError("no path rename fallback")):
            preview = self.empty_preview(fixture)
            self.assertFalse((fixture.home / supersede.ROOT).exists())
            result = self.empty_withdraw(fixture, preview)
        self.assertEqual(result["status"], "empty_allocation_withdrawn_witnessed")
        self.assertEqual(result["model_requests"], 0)
        generation = self.generation(fixture)
        self.assertEqual({p.name for p in generation.iterdir()},
                         {"intent.json", "failure-evidence.json", "activation", "receipt.json"})
        self.assertEqual(withdraw.empty_allocation_directory_identity(generation / "activation"), identity)
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual((generation / "failure-evidence.json").read_bytes(), original[fixture.failure])
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)
        intent = json.loads((generation / "intent.json").read_bytes())
        self.assertEqual(intent["manifest"], {})
        self.assertNotIn("plan_sha256", intent)
        self.assertEqual(supersede.archive_status(fixture.home),
                         {"status": "superseded_witnessed", "generations": 1})
        self.assertEqual(supersede._archive_state(fixture.home)[1], frozenset())

    def test_empty_preview_rejects_nonempty_or_changed_failure_evidence_without_writes(self):
        fixture = self.empty_fixture()
        for name in ("plan.json", "journal.json", "unknown", "attempt.json"):
            with self.subTest(name=name):
                artifact = fixture.plan.parent / name
                artifact.write_bytes(b"retained")
                with self.assertRaisesRegex(withdraw.WithdrawError, "allocation_not_empty"):
                    self.empty_preview(fixture)
                artifact.unlink()
        for edit in ({"reason": "unified_review_changed"}, {"configuration_changed": True},
                     {"model_requests": False}, {"extra": "unknown"}):
            with self.subTest(edit=edit):
                failure = dict(withdraw.EMPTY_FAILURE, **edit)
                fixture.failure.write_bytes(supersede._json(failure))
                fixture.failure_sha = supersede._hash(fixture.failure.read_bytes())
                with self.assertRaisesRegex(withdraw.WithdrawError, "failure_evidence_invalid"):
                    self.empty_preview(fixture)
        fixture.failure.write_bytes(supersede._json(withdraw.EMPTY_FAILURE))
        fixture.failure_sha = "0" * 64
        with self.assertRaisesRegex(withdraw.WithdrawError, "failure_evidence_changed"):
            self.empty_preview(fixture)
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_empty_source_replacement_after_preview_is_rejected_with_both_directories_retained(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        old = fixture.home / "retained-original"
        original_identity = withdraw.empty_allocation_directory_identity(fixture.plan.parent)
        fixture.plan.parent.rename(old)
        fixture.plan.parent.mkdir()
        with self.assertRaisesRegex(withdraw.WithdrawError, "review_changed"):
            self.empty_withdraw(fixture, preview)
        self.assertEqual(withdraw.empty_allocation_directory_identity(old), original_identity)
        self.assertTrue(fixture.plan.parent.is_dir())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_empty_current_files_failure_and_source_are_locked_through_native_move(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        original_move = withdraw._rename_empty_allocation_handle
        observed = []
        def check_move(source_handle, target_handle, target, expected):
            files = [fixture.config, fixture.cache, fixture.failure,
                     fixture.home / "operator-native-route-only", *fixture.entry.iterdir(),
                     target.parent / "intent.json", target.parent / "failure-evidence.json"]
            for path in files:
                with self.assertRaises(OSError):
                    path.write_bytes(b"changed")
                with self.assertRaises(OSError):
                    path.rename(path.with_suffix(".changed"))
            for directory in (fixture.plan.parent, target.parent, target.parent.parent, fixture.home):
                with self.assertRaises(OSError):
                    directory.rename(directory.with_name(directory.name + "-changed"))
            observed.append(supersede.archive_status(fixture.home, pending=target.parent))
            return original_move(source_handle, target_handle, target, expected)
        with patch.object(withdraw, "_rename_empty_allocation_handle", side_effect=check_move) as move:
            self.empty_withdraw(fixture, preview)
        self.assertEqual(move.call_count, 1)
        self.assertEqual(observed, [{"status": "pending_internal", "generations": 1}])

    def test_empty_child_added_after_native_move_is_retained_and_terminal(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        original_move = withdraw._rename_empty_allocation_handle
        def move_then_add(*args):
            original_move(*args)
            (args[2] / "concurrent-child").write_bytes(b"retained concurrent bytes")
        with patch.object(withdraw, "_rename_empty_allocation_handle", side_effect=move_then_add):
            with self.assertRaisesRegex(withdraw.WithdrawError, "allocation_not_empty"):
                self.empty_withdraw(fixture, preview)
        generation = self.generation(fixture)
        self.assertEqual((generation / "activation/concurrent-child").read_bytes(), b"retained concurrent bytes")
        self.assertFalse((generation / "receipt.json").exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        with self.assertRaisesRegex(withdraw.WithdrawError, "archive_requires_review"):
            self.empty_withdraw(fixture, preview)

    def test_empty_child_added_before_native_call_prevents_move_without_deleting_it(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        original_move = withdraw._rename_empty_allocation_handle
        def add_then_move(*args):
            (fixture.plan.parent / "concurrent-child").write_bytes(b"preserve")
            return original_move(*args)
        with patch.object(withdraw, "_rename_empty_allocation_handle", side_effect=add_then_move):
            with self.assertRaisesRegex(withdraw.WithdrawError, "allocation_not_empty"):
                self.empty_withdraw(fixture, preview)
        self.assertEqual((fixture.plan.parent / "concurrent-child").read_bytes(), b"preserve")
        self.assertFalse((self.generation(fixture) / "activation").exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_empty_target_collision_and_native_failure_never_overwrite_or_retry(self):
        for collision in (True, False):
            with self.subTest(collision=collision):
                fixture = self.empty_fixture()
                preview = self.empty_preview(fixture)
                original_move = withdraw._rename_empty_allocation_handle
                def fail_move(*args):
                    if collision:
                        args[2].mkdir()
                        (args[2] / "retain").write_bytes(b"preexisting target")
                        return original_move(*args)
                    raise withdraw.WithdrawError("unified_withdraw_move_failed")
                with patch.object(withdraw, "_rename_empty_allocation_handle", side_effect=fail_move) as move:
                    with self.assertRaisesRegex(withdraw.WithdrawError, "move_failed"):
                        self.empty_withdraw(fixture, preview)
                self.assertEqual(move.call_count, 1)
                self.assertTrue(fixture.plan.parent.is_dir())
                self.assertFalse((self.generation(fixture) / "receipt.json").exists())
                self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
                if collision:
                    self.assertEqual((self.generation(fixture) / "activation/retain").read_bytes(), b"preexisting target")
                with self.assertRaisesRegex(withdraw.WithdrawError, "archive_requires_review"):
                    self.empty_withdraw(fixture, preview)

    def test_empty_optional_cache_and_source_reappearance_stop_before_receipt(self):
        for change in ("cache", "source"):
            with self.subTest(change=change):
                fixture = self.empty_fixture()
                fixture.cache.unlink()
                preview = self.empty_preview(fixture)
                original_current = withdraw._current
                def current(review):
                    if not fixture.plan.parent.exists():
                        if change == "cache":
                            fixture.cache.write_bytes(b'{"new":"keep"}')
                        else:
                            fixture.plan.parent.mkdir()
                    return original_current(review)
                with patch.object(withdraw, "_current", side_effect=current):
                    with self.assertRaisesRegex(withdraw.WithdrawError, "current_state_changed"):
                        self.empty_withdraw(fixture, preview)
                self.assertFalse((self.generation(fixture) / "receipt.json").exists())
                self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
                if change == "cache":
                    self.assertEqual(fixture.cache.read_bytes(), b'{"new":"keep"}')
                else:
                    self.assertTrue(fixture.plan.parent.is_dir())

    def test_empty_source_code_change_after_move_is_terminal(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        original = withdraw._source_sha256
        def changed():
            hashes = original()
            if not fixture.plan.parent.exists():
                hashes["operator_unified_withdraw.py"] = "0" * 64
            return hashes
        with patch.object(withdraw, "_source_sha256", side_effect=changed):
            with self.assertRaisesRegex(withdraw.WithdrawError, "current_state_changed"):
                self.empty_withdraw(fixture, preview)
        self.assertFalse((self.generation(fixture) / "receipt.json").exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_empty_receipt_failure_retains_full_archive_and_blocks_prepare(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        original = withdraw.records._record
        def record(path, value):
            if path.name == "receipt.json":
                raise OSError("disposable failed receipt")
            original(path, value)
        with patch.object(withdraw.records, "_record", side_effect=record):
            with self.assertRaises(OSError):
                self.empty_withdraw(fixture, preview)
        generation = self.generation(fixture)
        self.assertTrue((generation / "activation").is_dir())
        self.assertEqual((generation / "failure-evidence.json").read_bytes(), fixture.failure.read_bytes())
        report = preparation.preview(fixture.project, fixture.home, fixture.router_state, fixture.profile, 4318)
        self.assertIn("unified_prepared_archive_requires_review", report["blockers"])

    def test_empty_receipt_boundary_changes_leave_a_terminal_completion_fence(self):
        for change in ("cache", "source", "child", "source_code", "receipt"):
            with self.subTest(change=change):
                fixture = self.empty_fixture()
                fixture.cache.unlink()
                preview = self.empty_preview(fixture)
                original_record = withdraw.records._record
                original_sources = withdraw._source_sha256
                changed = False
                def record(path, value):
                    nonlocal changed
                    original_record(path, value)
                    if path.name == "receipt.json":
                        changed = True
                        if change == "cache":
                            fixture.cache.write_bytes(b"new retained cache")
                        elif change == "source":
                            fixture.plan.parent.mkdir()
                        elif change == "child":
                            (path.parent / "activation/retain").write_bytes(b"new child")
                        elif change == "receipt":
                            path.write_bytes(path.read_bytes() + b" ")
                def sources():
                    values = original_sources()
                    if changed and change == "source_code":
                        values["operator_unified_withdraw.py"] = "0" * 64
                    return values
                with patch.object(withdraw.records, "_record", side_effect=record), \
                        patch.object(withdraw, "_source_sha256", side_effect=sources):
                    with self.assertRaises(withdraw.WithdrawError):
                        self.empty_withdraw(fixture, preview)
                generation = self.generation(fixture)
                self.assertTrue((generation / "completion-pending.json").is_file())
                self.assertTrue((generation / "receipt.json").is_file())
                self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
                with self.assertRaisesRegex(withdraw.WithdrawError, "archive_requires_review"):
                    self.empty_withdraw(fixture, preview)

    def test_empty_fence_commit_failure_never_publishes_a_completed_archive(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        with patch.object(withdraw, "_commit_completion_fence", side_effect=OSError("disposable failure")) as commit:
            with self.assertRaises(OSError):
                self.empty_withdraw(fixture, preview)
        self.assertEqual(commit.call_count, 1)
        self.assertTrue((self.generation(fixture) / "completion-pending.json").exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_empty_archive_validator_rejects_shapes_without_fabricating_a_plan(self):
        fixture = self.empty_fixture()
        self.empty_withdraw(fixture, self.empty_preview(fixture))
        generation = self.generation(fixture)
        raw = (generation / "intent.json").read_bytes()
        intent = json.loads(raw)
        receipt = json.loads((generation / "receipt.json").read_bytes())
        withdraw.validate_empty_allocation_intent(intent)
        withdraw.validate_empty_allocation_archive(intent, receipt, raw)
        edits = [lambda x: x.update(plan_sha256="a" * 64),
                 lambda x: x.update(schema_version=True),
                 lambda x: x.update(manifest={"plan.json": {}}),
                 lambda x: x["review"].update(scope="unused_prepared_plan_withdrawal"),
                 lambda x: x["review"].update(directory_identity={"volume": True, "file_id": "a" * 32}),
                 lambda x: x["review"].update(source_sha256={}),
                 lambda x: x["review"]["failure_evidence"].update(path="relative.json"),
                 lambda x: x["review"].update(config=None),
                 lambda x: x["review"]["marker"].update(sha256="0" * 64),
                 lambda x: x["review"]["entry"].pop("Codex拓展入口.exe")]
        for edit in edits:
            altered = deepcopy(intent)
            edit(altered)
            altered["review_sha256"] = supersede._hash(supersede._json(altered["review"]))
            with self.assertRaises(withdraw.WithdrawError):
                withdraw.validate_empty_allocation_intent(altered)
        with self.assertRaises(withdraw.WithdrawError):
            withdraw.validate_empty_allocation_archive(intent, dict(receipt, plan_sha256="a" * 64), raw)

    def test_empty_completed_archive_rejects_changed_bytes_children_and_directory_identity(self):
        fixture = self.empty_fixture()
        self.empty_withdraw(fixture, self.empty_preview(fixture))
        generation = self.generation(fixture)
        failure = generation / "failure-evidence.json"
        raw = failure.read_bytes()
        failure.write_bytes(raw + b" ")
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        failure.write_bytes(raw)
        child = generation / "activation/unknown"
        child.write_bytes(b"keep")
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        child.unlink()
        archived = generation / "activation"
        archived.rename(generation / "original")
        archived.mkdir()
        (generation / "original").rename(fixture.home / "retained-original-allocation")
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_empty_pending_reader_validates_full_intent_and_original_failure_bytes(self):
        fixture = self.empty_fixture()
        preview = self.empty_preview(fixture)
        with patch.object(withdraw, "_rename_empty_allocation_handle", side_effect=OSError("stop before move")):
            with self.assertRaises(OSError):
                self.empty_withdraw(fixture, preview)
        generation = self.generation(fixture)
        self.assertEqual(supersede.archive_status(fixture.home, pending=generation)["status"], "pending_internal")
        intent_path = generation / "intent.json"
        original = intent_path.read_bytes()
        intent = json.loads(original)
        intent["review"]["cache"] = {"invalid": True}
        intent["review_sha256"] = supersede._hash(supersede._json(intent["review"]))
        intent_path.write_bytes(supersede._json(intent))
        self.assertEqual(supersede.archive_status(fixture.home, pending=generation)["status"], "uncertain")
        intent_path.write_bytes(original)
        (generation / "failure-evidence.json").write_bytes(b"changed")
        self.assertEqual(supersede.archive_status(fixture.home, pending=generation)["status"], "uncertain")
        (generation / "failure-evidence.json").unlink()
        self.assertEqual(supersede.archive_status(fixture.home, pending=generation)["status"], "uncertain")

    def test_empty_32_generation_limit_and_invalid_current_native_state_stop_before_writes(self):
        fixture = self.empty_fixture()
        with patch.object(supersede, "archive_status", return_value={"status": "superseded_witnessed", "generations": 32}):
            with self.assertRaisesRegex(withdraw.WithdrawError, "archive_capacity"):
                self.empty_preview(fixture)
        fixture.config.write_bytes(b'model_provider="unknown"\n')
        with self.assertRaisesRegex(withdraw.WithdrawError, "native_route_unverified"):
            self.empty_preview(fixture)
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_empty_and_prepared_withdrawal_coexist_and_permit_a_distinct_new_preparation(self):
        fixture = self.fixture()
        old_digest = supersede._hash(fixture.plan.read_bytes())
        withdraw.withdraw(fixture.plan, withdraw.preview(fixture.plan)["review_sha256"])
        fixture.plan.parent.mkdir()
        fixture.failure = fixture.project / "failed-prepare.json"
        fixture.failure.write_bytes(supersede._json(withdraw.EMPTY_FAILURE))
        fixture.failure_sha = supersede._hash(fixture.failure.read_bytes())
        self.empty_withdraw(fixture, self.empty_preview(fixture))
        report, old = supersede._archive_state(fixture.home)
        self.assertEqual(report, {"status": "superseded_witnessed", "generations": 2})
        self.assertEqual(old, frozenset({old_digest}))
        phases = {json.loads((path / "receipt.json").read_bytes())["phase"]
                  for path in (fixture.home / supersede.ROOT).iterdir()}
        self.assertEqual(phases, {"withdrawn_witnessed", "empty_allocation_withdrawn_witnessed"})
        fixture.config.write_bytes(b'model="gpt-6.1-sol"\nmodel_reasoning_effort="ultra"\n')
        current = preparation.preview(fixture.project, fixture.home, fixture.router_state, fixture.profile, 4318)
        preparation.prepare(fixture.project, fixture.home, fixture.router_state,
                            fixture.profile, 4318, current["review_sha256"])
        self.assertNotEqual(supersede._hash(fixture.plan.read_bytes()), old_digest)
        self.assertEqual(supersede.archive_status(fixture.home), report)

    def test_changed_native_model_hooks_and_cache_are_retained_without_service_or_desktop_checks(self):
        fixture = self.fixture()
        original = {p.name: p.read_bytes() for p in fixture.plan.parent.iterdir()}
        changed = (b'model = "gpt-6-astra"\nmodel_reasoning_effort = "high"\n'
                   b'user_setting = "new setting"\n[features]\nrealtime_conversation = true\n'
                   b'[hooks]\nSessionStart = []\n')
        fixture.config.write_bytes(changed)
        fixture.cache.write_bytes(b'{"current":"catalog"}\n')
        entry = {p.name: p.read_bytes() for p in fixture.entry.iterdir()}
        before_directory = withdraw._directory_identity(fixture.plan.parent)
        with patch.object(router, "control", side_effect=AssertionError("no service probe")), \
                patch.object(preparation, "_readiness", side_effect=AssertionError("no preparation")), \
                patch.object(preparation.web_startup, "assert_desktop_closed", side_effect=AssertionError("Desktop may stay open")):
            review = withdraw.preview(fixture.plan)
            result = withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual(result["status"], "withdrawn_witnessed")
        self.assertEqual(result["model_requests"], 0)
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual(fixture.config.read_bytes(), changed)
        self.assertEqual(fixture.cache.read_bytes(), b'{"current":"catalog"}\n')
        self.assertEqual({p.name: p.read_bytes() for p in fixture.entry.iterdir()}, entry)
        archived = self.generation(fixture) / "activation"
        self.assertEqual({p.name: p.read_bytes() for p in archived.iterdir()}, original)
        self.assertEqual(withdraw._directory_identity(archived), before_directory)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "superseded_witnessed")

    def test_original_plan_native_lock_is_required_even_with_current_marker(self):
        fixture = self.fixture()
        for blockers in ([], ["unknown"], ["unified_native_route_lock_active", "unknown"],
                         ["unified_native_route_lock_active"] * 2):
            with self.subTest(blockers=blockers):
                self.rewrite_plan(fixture, lambda plan: plan.update(future_arm_blockers=blockers))
                with self.assertRaisesRegex(withdraw.WithdrawError, "original_native_lock_required"):
                    withdraw.preview(fixture.plan)
                self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_armed_attempted_or_marker_release_artifacts_are_never_withdrawable(self):
        fixture = self.fixture()
        for name in ("arm.json", "attempt.json", "marker-release", "retirement"):
            with self.subTest(name=name):
                item = fixture.plan.parent / name
                item.write_bytes(b"{}")
                try:
                    with self.assertRaisesRegex(withdraw.WithdrawError, "not_unused_preparation"):
                        withdraw.preview(fixture.plan)
                finally:
                    item.unlink()
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_unknown_native_routes_invalid_toml_and_process_override_are_rejected(self):
        fixture = self.fixture()
        for value in (b'model_provider = "other"\n', b'openai_base_url = "https://example.invalid"\n',
                      b'profile = "other"\n', b'[model_providers.openai]\nbase_url="https://example.invalid"\n',
                      b'model = "unterminated\n'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(withdraw.WithdrawError, "native_route_unverified"):
                    withdraw._native_config(value)
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://example.invalid"}):
            with self.assertRaisesRegex(withdraw.WithdrawError, "native_route_unverified"):
                withdraw.preview(fixture.plan)
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_current_marker_must_be_exact_and_prepared_copies_must_be_intact(self):
        fixture = self.fixture()
        marker = fixture.home / "operator-native-route-only"
        marker.write_bytes(b"different")
        with self.assertRaisesRegex(withdraw.WithdrawError, "native_marker_changed"):
            withdraw.preview(fixture.plan)
        marker.write_bytes(supersede.MARKER)
        (fixture.plan.parent / "candidate.toml").write_bytes(b"changed")
        with self.assertRaisesRegex(withdraw.WithdrawError, "prepared_copy_changed"):
            withdraw.preview(fixture.plan)
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_realtime_url_overrides_require_official_value_without_rejecting_model_settings(self):
        self.fixture()
        withdraw._native_config(b'experimental_realtime_model = "gpt-realtime"\n')
        for key in ("experimental_realtime_webrtc_call_base_url", "experimental_realtime_ws_base_url"):
            with self.subTest(key=key):
                withdraw._native_config((key + ' = "https://chatgpt.com/backend-api/codex"\n').encode())
                for value in ("http://127.0.0.1:4318", "https://example.invalid", ""):
                    with self.assertRaisesRegex(withdraw.WithdrawError, "native_route_unverified"):
                        withdraw._native_config((key + ' = "' + value + '"\n').encode())

    def test_snapshot_change_after_preview_stops_before_intent(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        fixture.config.write_bytes(fixture.original.replace(b"gpt-6-sol", b"gpt-6-astra"))
        with self.assertRaisesRegex(withdraw.WithdrawError, "review_changed"):
            withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_current_files_and_intent_are_frozen_during_move(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        original_rename = os.rename
        attempts = []
        def check_then_move(source, target):
            files = [fixture.config, fixture.cache, fixture.home / "operator-native-route-only",
                     fixture.entry / "desktop-entry.json", target.parent / "intent.json"]
            for path in files:
                with self.assertRaises(OSError):
                    path.write_bytes(b"changed")
                with self.assertRaises(OSError):
                    original_rename(path, path.with_suffix(".moved"))
                attempts.append(path.name)
            original_rename(source, target)
        with patch.object(withdraw.os, "rename", side_effect=check_then_move):
            withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual(len(attempts), 5)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "superseded_witnessed")

    def test_concurrent_marker_release_artifact_at_move_is_terminal(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        original_rename = os.rename
        def add_artifact_then_move(source, target):
            (source / "marker-release").mkdir()
            original_rename(source, target)
        with patch.object(withdraw.os, "rename", side_effect=add_artifact_then_move):
            with self.assertRaises(supersede.SupersedeError):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        self.assertTrue((self.generation(fixture) / "activation/marker-release").is_dir())
        self.assertFalse((self.generation(fixture) / "receipt.json").exists())

    def test_old_source_directory_reappearance_after_move_is_terminal(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        original_current = withdraw._current
        def current_with_reappearance(plan):
            result = original_current(plan)
            if not fixture.plan.parent.exists():
                fixture.plan.parent.mkdir()
            return result
        with patch.object(withdraw, "_current", side_effect=current_with_reappearance):
            with self.assertRaisesRegex(withdraw.WithdrawError, "current_state_changed"):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        self.assertFalse((self.generation(fixture) / "receipt.json").exists())

    def test_move_failure_retains_intent_and_cannot_retry(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        with patch.object(withdraw.os, "rename", side_effect=OSError("synthetic failed rename")):
            with self.assertRaises(OSError):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        with self.assertRaisesRegex(withdraw.WithdrawError, "archive_requires_review"):
            withdraw.withdraw(fixture.plan, review["review_sha256"])

    def test_receipt_failure_retains_moved_original_and_blocks_new_prepare(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        original_record = withdraw.records._record
        def fail_receipt(path, value):
            if path.name == "receipt.json":
                raise OSError("synthetic failed receipt")
            return original_record(path, value)
        with patch.object(withdraw.records, "_record", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        report = preparation.preview(fixture.project, fixture.home, fixture.router_state, fixture.profile, 4318)
        self.assertIn("unified_prepared_archive_requires_review", report["blockers"])

    def test_changed_intent_before_final_preflight_is_terminal(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        original_record = withdraw.records._record
        def change_intent(path, value):
            original_record(path, value)
            if path.name == "intent.json":
                path.write_bytes(path.read_bytes() + b" ")
        with patch.object(withdraw.records, "_record", side_effect=change_intent):
            with self.assertRaisesRegex(withdraw.WithdrawError, "intent_changed"):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_absent_cache_appearing_at_move_is_terminal(self):
        fixture = self.fixture()
        fixture.cache.unlink()
        review = withdraw.preview(fixture.plan)
        original_rename = os.rename
        def move_then_create_cache(source, target):
            original_rename(source, target)
            fixture.cache.write_bytes(b'{"new":"cache"}')
        with patch.object(withdraw.os, "rename", side_effect=move_then_create_cache):
            with self.assertRaisesRegex(withdraw.WithdrawError, "current_state_changed"):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual(fixture.cache.read_bytes(), b'{"new":"cache"}')
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_reappearing_original_plan_is_blocked_even_after_valid_withdrawal(self):
        fixture = self.fixture()
        old_plan = fixture.plan.read_bytes()
        review = withdraw.preview(fixture.plan)
        withdraw.withdraw(fixture.plan, review["review_sha256"])
        fixture.plan.parent.mkdir()
        fixture.plan.write_bytes(old_plan)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_strict_withdraw_scope_cannot_be_relabelled_as_supersede(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        withdraw.withdraw(fixture.plan, review["review_sha256"])
        generation = self.generation(fixture)
        intent_path = generation / "intent.json"
        intent = json.loads(intent_path.read_bytes())
        intent["review"]["scope"] = "prepared_plan_supersede"
        intent["review_sha256"] = supersede._hash(supersede._json(intent["review"]))
        intent_path.write_bytes(supersede._json(intent))
        receipt_path = generation / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["intent_sha256"] = supersede._hash(intent_path.read_bytes())
        receipt_path.write_bytes(supersede._json(receipt))
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_changed_directory_identity_in_archive_is_rejected(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        withdraw.withdraw(fixture.plan, review["review_sha256"])
        generation = self.generation(fixture)
        original = generation / "activation"
        replacement = generation / "replacement"
        replacement.mkdir()
        for path in original.iterdir():
            os.rename(path, replacement / path.name)
        original.rmdir()
        os.rename(replacement, original)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_mixed_old_supersede_and_new_withdraw_archives_remain_distinct(self):
        fixture = self.fixture()
        first = supersede.preview(fixture.plan, Path(sys.executable))
        supersede.supersede(fixture.plan, Path(sys.executable), first["review_sha256"])
        # A distinct new plan is required; re-creating the exact archived plan
        # digest is intentionally rejected by the common replay gate.
        fixture.config.write_bytes(fixture.original.replace(b"gpt-6-sol", b"gpt-6-astra"))
        fresh = preparation.preview(fixture.project, fixture.home, fixture.router_state, fixture.profile, 4318)
        preparation.prepare(fixture.project, fixture.home, fixture.router_state,
                            fixture.profile, 4318, fresh["review_sha256"])
        fixture.config.write_bytes(fixture.config.read_bytes() + b'model_reasoning_effort = "high"\n')
        second = withdraw.preview(fixture.plan)
        withdraw.withdraw(fixture.plan, second["review_sha256"])
        result = supersede.archive_status(fixture.home)
        self.assertEqual(result, {"status": "superseded_witnessed", "generations": 2})
        phases = {json.loads((p / "receipt.json").read_bytes())["phase"]
                  for p in (fixture.home / supersede.ROOT).iterdir()}
        self.assertEqual(phases, {"superseded_witnessed", "withdrawn_witnessed"})

    def test_uncertain_retired_archive_blocks_without_writes(self):
        fixture = self.fixture()
        (fixture.home / withdraw.records.ARCHIVE).write_bytes(b"unknown")
        with self.assertRaisesRegex(withdraw.WithdrawError, "retired_archive_requires_review"):
            withdraw.preview(fixture.plan)
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_archive_capacity_stops_before_creating_a_new_generation(self):
        fixture = self.fixture()
        review = withdraw.preview(fixture.plan)
        before = {p.name: p.read_bytes() for p in fixture.plan.parent.iterdir()}
        with patch.object(supersede, "archive_status", return_value={
                "status": "superseded_witnessed", "generations": 32}):
            with self.assertRaisesRegex(withdraw.WithdrawError, "archive_capacity"):
                withdraw.withdraw(fixture.plan, review["review_sha256"])
        self.assertEqual({p.name: p.read_bytes() for p in fixture.plan.parent.iterdir()}, before)
        self.assertFalse((fixture.home / supersede.ROOT).exists())


if __name__ == "__main__":
    unittest.main()
