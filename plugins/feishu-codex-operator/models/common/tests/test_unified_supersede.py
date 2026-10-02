"""Disposable prepared-only unified plan supersession and crash gates."""

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
from contextlib import nullcontext
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_unified_cold_start as cold_tests
import operator_unified_prepare as preparation
import operator_unified_supersede as supersede
import operator_model_router as router
import operator_uninstall as uninstall


@unittest.skipUnless(os.name == "nt", "Windows file identity required")
class UnifiedSupersedeTests(unittest.TestCase):
    def fixture(self, *, cua_pipe=False):
        value = cold_tests.UnifiedColdStartTests(
            "test_planned_marker_release_allows_one_cold_launch")
        value.with_cua_pipe = cua_pipe
        value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def test_one_cua_pipe_change_archives_old_plan_and_preserves_current_config(self):
        fixture = self.fixture(cua_pipe=True)
        changed = fixture.original.replace(b"'one'", b"'two'")
        replacement = fixture.config.with_suffix(".new")
        replacement.write_bytes(changed)
        os.replace(replacement, fixture.config)
        review = supersede.preview(fixture.plan, Path(sys.executable))
        self.assertEqual(review["status"], "reviewed_preview")
        result = supersede.supersede(fixture.plan, Path(sys.executable),
                                     review["review_sha256"])
        self.assertEqual(result["status"], "superseded_witnessed")
        self.assertEqual(fixture.config.read_bytes(), changed)
        archived = next((fixture.home / supersede.ROOT).iterdir()) / "activation"
        self.assertEqual((archived / "before.toml").read_bytes(), fixture.original)
        fresh = preparation.preview(fixture.project, fixture.home,
                                    fixture.router_state, fixture.profile, 4318)
        self.assertEqual(fresh["blockers"], ["unified_native_route_lock_active"])
        preparation.prepare(fixture.project, fixture.home, fixture.router_state,
                            fixture.profile, 4318, fresh["review_sha256"])
        self.assertEqual((fixture.plan.parent / "before.toml").read_bytes(), changed)

    def test_other_config_change_still_blocks_before_archive(self):
        fixture = self.fixture(cua_pipe=True)
        fixture.config.write_bytes(fixture.original.replace(b"keep me", b"changed"))
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_native_state_changed"):
            supersede.preview(fixture.plan, Path(sys.executable))
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_cua_delta_rejects_duplicate_or_format_changes(self):
        saved = b"model = 'native'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'one'\n"
        self.assertEqual(supersede._config_delta(saved,
            saved.replace(b"'one'", b"'two'")), "cua_pipe_only")
        for changed in (
            saved + b"SKY_CUA_NATIVE_PIPE_DIRECTORY = 'two'\n",
            saved.replace(b"'one'", b'"two"'),
            saved.replace(b"'one'", b"'two'").replace(b"native", b"other"),
            saved.replace(b"'one'", b"''"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(supersede.SupersedeError,
                                            "unified_supersede_native_state_changed"):
                    supersede._config_delta(saved, changed)

    def test_cua_pipe_change_after_preview_blocks_before_archive(self):
        fixture = self.fixture(cua_pipe=True)
        fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'two'"))
        review = supersede.preview(fixture.plan, Path(sys.executable))
        fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'three'"))
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_review_changed"):
            supersede.supersede(fixture.plan, Path(sys.executable),
                                review["review_sha256"])
        self.assertTrue(fixture.plan.exists())

    def test_dead_exact_router_can_archive_only_prepared_plan(self):
        fixture = self.fixture(cua_pipe=True)
        fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'two'"))
        with patch.object(router, "control", side_effect=OSError("stopped")), \
                patch.object(preparation.web_service, "process_identity", return_value=None), \
                patch.object(router, "reserve_inactive_port", side_effect=lambda _: nullcontext()):
            review = supersede.preview(fixture.plan, Path(sys.executable))
            self.assertEqual(review["status"], "reviewed_preview")
            result = supersede.supersede(fixture.plan, Path(sys.executable),
                                         review["review_sha256"])
        self.assertEqual(result["status"], "superseded_witnessed")
        self.assertFalse(fixture.plan.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"],
                         "superseded_witnessed")
        self.assertEqual(fixture.config.read_bytes(),
                         fixture.original.replace(b"'one'", b"'two'"))

    def test_stopped_router_archives_stale_router_and_renderer_source(self):
        fixture = self.fixture(cua_pipe=True)
        fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'two'"))
        old = json.loads(fixture.plan.read_bytes())
        old["source_sha256"]["router"] = "0" * 64
        old["source_sha256"]["renderer"] = "1" * 64
        raw = supersede._json(old)
        fixture.plan.write_bytes(raw)
        journal_path = fixture.plan.parent / "journal.json"
        journal = json.loads(journal_path.read_bytes())
        journal["plan_sha256"] = supersede._hash(raw)
        journal_path.write_bytes(supersede._json(journal))
        with patch.object(router, "control", side_effect=OSError("stopped")), \
                patch.object(preparation.web_service, "process_identity", return_value=None), \
                patch.object(router, "reserve_inactive_port", side_effect=lambda _: nullcontext()):
            review = supersede._inspect(fixture.plan, Path(sys.executable))
            self.assertEqual(review["source_drift"], ["renderer", "router"])
            result = supersede.supersede(fixture.plan, Path(sys.executable),
                                         supersede._hash(supersede._json(review)))
        self.assertEqual(result["status"], "superseded_witnessed")

    def test_stopped_router_rejects_unrelated_source_drift(self):
        self.assertEqual(supersede._source_drift({"source_sha256": {
            "preparer": "a", "router": "a", "renderer": "a"}},
            {"preparer": "b", "router": "b", "renderer": "b"},
            "stopped_exact_process_absent"), ["preparer", "renderer", "router"])
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_source_changed"):
            supersede._source_drift({"source_sha256": {"preview": "a"}},
                                    {"preview": "b"}, "stopped_exact_process_absent")

    def test_dead_router_requires_absent_exact_process_and_free_port(self):
        fixture = self.fixture()
        with patch.object(router, "control", side_effect=OSError("stopped")):
            with patch.object(preparation.web_service, "process_identity",
                              return_value={"pid": 4321}):
                with self.assertRaisesRegex(supersede.SupersedeError,
                                            "unified_supersede_router_changed"):
                    supersede.preview(fixture.plan, Path(sys.executable))
            with patch.object(preparation.web_service, "process_identity", return_value=None), \
                    patch.object(router, "reserve_inactive_port", side_effect=OSError("busy")):
                with self.assertRaisesRegex(supersede.SupersedeError,
                                            "unified_supersede_router_changed"):
                    supersede.preview(fixture.plan, Path(sys.executable))
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_channels_only_uninstall_skips_optional_archive_module(self):
        with tempfile.TemporaryDirectory(prefix="operator-channels-only-") as temporary:
            config = Path(temporary) / "config.toml"
            config.write_bytes(b'model = "gpt-6-sol"\n')
            with patch.dict(sys.modules, {"operator_unified_supersede": None}):
                uninstall.inspect_unified_candidate(config)
            (Path(temporary) / supersede.ROOT).write_bytes(b"invalid archive")
            with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict,
                                        "unified_prepared_archive_requires_review_before_uninstall"):
                uninstall.inspect_unified_candidate(config)

    def test_superseded_prepared_plan_retains_original_and_allows_new_prepare(self):
        fixture = self.fixture()
        old_plan = fixture.plan.read_bytes()
        old_cache = fixture.cache.read_bytes()
        current_cache = b'{"new":"catalog-refresh"}\n'
        fixture.cache.write_bytes(current_cache)
        review = supersede.preview(fixture.plan, Path(sys.executable))
        self.assertEqual(review["status"], "reviewed_preview")
        result = supersede.supersede(fixture.plan, Path(sys.executable),
                                     review["review_sha256"])
        self.assertEqual(result["status"], "superseded_witnessed")
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual(fixture.cache.read_bytes(), current_cache)
        self.assertEqual(json.loads((fixture.entry / "desktop-entry.json").read_bytes())["mode"],
                         "reviewed_startup")
        self.assertEqual(supersede.archive_status(fixture.home)["status"],
                         "superseded_witnessed")
        archived = next((fixture.home / supersede.ROOT).iterdir()) / "activation"
        self.assertEqual((archived / "plan.json").read_bytes(), old_plan)
        self.assertEqual((archived / "cache-before.bin").read_bytes(), old_cache)
        new_review = preparation.preview(fixture.project, fixture.home,
                                         fixture.router_state, fixture.profile, 4318)
        self.assertEqual(new_review["blockers"], ["unified_native_route_lock_active"])
        preparation.prepare(fixture.project, fixture.home, fixture.router_state,
                            fixture.profile, 4318, new_review["review_sha256"])
        new_plan = json.loads(fixture.plan.read_bytes())
        self.assertNotEqual(fixture.plan.read_bytes(), old_plan)
        self.assertEqual(new_plan["cache"]["sha256"], preparation._hash(current_cache))
        self.assertEqual(supersede.archive_status(fixture.home)["status"],
                         "superseded_witnessed")
        second = supersede.preview(fixture.plan, Path(sys.executable))
        supersede.supersede(fixture.plan, Path(sys.executable), second["review_sha256"])
        self.assertEqual(supersede.archive_status(fixture.home)["generations"], 2)
        command = subprocess.run([sys.executable, "-B",
            str(_OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_supersede.py"),
            "status", "--plan", str(fixture.plan)], capture_output=True,
            encoding="utf-8", timeout=15)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(json.loads(command.stdout)["generations"], 2)

    def test_cache_change_after_preview_blocks_before_intent(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        fixture.cache.write_bytes(b'{"changed":"again"}\n')
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_review_changed"):
            supersede.supersede(fixture.plan, Path(sys.executable), review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_source_change_after_preview_blocks_before_intent(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        changed = {**supersede._source_sha256(),
                   "operator_unified_supersede.py": "0" * 64}
        with patch.object(supersede, "_source_sha256", return_value=changed):
            with self.assertRaisesRegex(supersede.SupersedeError,
                                        "unified_supersede_review_changed"):
                supersede.supersede(fixture.plan, Path(sys.executable),
                                    review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertFalse((fixture.home / supersede.ROOT).exists())

    def test_marker_release_or_arm_artifact_blocks_supersede(self):
        fixture = self.fixture()
        (fixture.plan.parent / "marker-release").mkdir()
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_unexpected_plan_artifact"):
            supersede.preview(fixture.plan, Path(sys.executable))
        (fixture.plan.parent / "marker-release").rmdir()
        (fixture.plan.parent / "arm.json").write_bytes(b"{}")
        with self.assertRaisesRegex(supersede.SupersedeError,
                                    "unified_supersede_unexpected_plan_artifact"):
            supersede.preview(fixture.plan, Path(sys.executable))

    def test_failed_move_leaves_terminal_intent_and_blocks_prepare(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        with patch.object(supersede.os, "rename", side_effect=OSError("synthetic move failure")):
            with self.assertRaises(OSError):
                supersede.supersede(fixture.plan, Path(sys.executable),
                                    review["review_sha256"])
        self.assertTrue(fixture.plan.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        report = preparation.preview(fixture.project, fixture.home,
                                     fixture.router_state, fixture.profile, 4318)
        self.assertIn("unified_prepared_archive_requires_review", report["blockers"])

    def test_failed_receipt_after_move_blocks_prepare_and_uninstall(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        original_record = supersede.records._record
        def fail_receipt(path, value):
            if path.name == "receipt.json":
                raise OSError("synthetic receipt failure")
            return original_record(path, value)
        with patch.object(supersede.records, "_record", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                supersede.supersede(fixture.plan, Path(sys.executable),
                                    review["review_sha256"])
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        report = preparation.preview(fixture.project, fixture.home,
                                     fixture.router_state, fixture.profile, 4318)
        self.assertIn("unified_prepared_archive_requires_review", report["blockers"])
        with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict,
                                    "unified_prepared_archive_requires_review_before_uninstall"):
            uninstall.inspect_unified_candidate(fixture.config)

    def test_cache_change_at_move_cannot_receive_witness(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        original_rename = supersede.os.rename
        def move_then_edit(source, target):
            original_rename(source, target)
            fixture.cache.write_bytes(b'{"changed":"during-move"}\n')
        with patch.object(supersede.os, "rename", side_effect=move_then_edit):
            with self.assertRaisesRegex(supersede.SupersedeError,
                                        "unified_supersede_cache_changed"):
                supersede.supersede(fixture.plan, Path(sys.executable),
                                    review["review_sha256"])
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        self.assertFalse(fixture.plan.parent.exists())

    def test_prepare_rechecks_new_pending_archive_after_first_review(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        supersede.supersede(fixture.plan, Path(sys.executable), review["review_sha256"])
        # A distinct future plan reaches the later pending-archive boundary.
        fixture.cache.write_bytes(b'{"fresh":"catalog"}\n')
        new_review = preparation.preview(fixture.project, fixture.home,
                                         fixture.router_state, fixture.profile, 4318)
        original_private = preparation.private_directory
        def create_pending(path):
            original_private(path)
            pending = fixture.home / supersede.ROOT / ("generation-" + "a" * 32)
            pending.mkdir()
            (pending / "intent.json").write_bytes(b"{}")
        with patch.object(preparation, "private_directory", side_effect=create_pending):
            with self.assertRaisesRegex(preparation.PrepareError,
                                        "unified_review_changed_after_directory_creation"):
                preparation.prepare(fixture.project, fixture.home,
                    fixture.router_state, fixture.profile, 4318,
                    new_review["review_sha256"])
        self.assertTrue(fixture.plan.parent.exists())
        self.assertFalse(fixture.plan.exists())
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")

    def test_schema_one_archive_cannot_claim_another_review_version_or_scope(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        supersede.supersede(fixture.plan, Path(sys.executable), review["review_sha256"])
        generation = next((fixture.home / supersede.ROOT).iterdir())
        intent_path, receipt_path = generation / "intent.json", generation / "receipt.json"
        original_intent, original_receipt = intent_path.read_bytes(), receipt_path.read_bytes()
        for field, value in (("schema_version", 2), ("scope", "unused_prepared_plan_withdrawal")):
            with self.subTest(field=field):
                intent = json.loads(original_intent)
                intent["review"][field] = value
                intent["review_sha256"] = supersede._hash(supersede._json(intent["review"]))
                changed = supersede._json(intent)
                intent_path.write_bytes(changed)
                receipt = json.loads(original_receipt)
                receipt["intent_sha256"] = supersede._hash(changed)
                receipt_path.write_bytes(supersede._json(receipt))
                self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
                intent_path.write_bytes(original_intent)
                receipt_path.write_bytes(original_receipt)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "superseded_witnessed")

    def test_full_archive_rejects_supersede_before_creating_a_generation(self):
        fixture = self.fixture()
        archive_root = fixture.home / supersede.ROOT
        archive_root.mkdir()
        original_plan = fixture.plan.read_bytes()
        for index in range(supersede.MAX_GENERATIONS):
            generation = archive_root / ("generation-" + format(index, "032x"))
            archived = generation / "activation"
            shutil.copytree(fixture.plan.parent, archived)
            plan_raw = original_plan + b"\n" * (index + 1)
            (archived / "plan.json").write_bytes(plan_raw)
            plan_sha = supersede._hash(plan_raw)
            (archived / "journal.json").write_bytes(supersede._json({"schema_version": 1,
                "phase": "prepared_not_armed", "plan_sha256": plan_sha}))
            review = {"schema_version": 1, "scope": "prepared_plan_supersede", "plan_sha256": plan_sha}
            intent = {"schema_version": 1, "phase": "may_have_superseded", "home": str(fixture.home),
                      "source": str(fixture.plan.parent), "target": str(archived), "plan_sha256": plan_sha,
                      "review": review, "review_sha256": supersede._hash(supersede._json(review)),
                      "manifest": supersede._manifest(archived)}
            raw = supersede._json(intent)
            (generation / "intent.json").write_bytes(raw)
            (generation / "receipt.json").write_bytes(supersede._json({"schema_version": 1,
                "phase": "superseded_witnessed", "intent_sha256": supersede._hash(raw), "plan_sha256": plan_sha}))
        self.assertEqual(supersede.archive_status(fixture.home),
                         {"status": "superseded_witnessed", "generations": supersede.MAX_GENERATIONS})
        before = {str(path.relative_to(fixture.home)): path.read_bytes()
                  for path in fixture.home.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(supersede.SupersedeError, "unified_supersede_archive_capacity"):
            supersede.supersede(fixture.plan, Path(sys.executable), "a" * 64)
        self.assertEqual(len(list(archive_root.iterdir())), supersede.MAX_GENERATIONS)
        self.assertEqual(before, {str(path.relative_to(fixture.home)): path.read_bytes()
                                 for path in fixture.home.rglob("*") if path.is_file()})

    def test_changed_archive_or_old_plan_reappearance_blocks_new_prepare(self):
        fixture = self.fixture()
        review = supersede.preview(fixture.plan, Path(sys.executable))
        supersede.supersede(fixture.plan, Path(sys.executable), review["review_sha256"])
        archived = next((fixture.home / supersede.ROOT).iterdir()) / "activation"
        shutil.copytree(archived, fixture.plan.parent)
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        shutil.rmtree(fixture.plan.parent)
        (archived / "before.toml").write_bytes(b"changed archive")
        self.assertEqual(supersede.archive_status(fixture.home)["status"], "uncertain")
        report = preparation.preview(fixture.project, fixture.home,
                                     fixture.router_state, fixture.profile, 4318)
        self.assertIn("unified_prepared_archive_requires_review", report["blockers"])


if __name__ == "__main__":
    unittest.main()
