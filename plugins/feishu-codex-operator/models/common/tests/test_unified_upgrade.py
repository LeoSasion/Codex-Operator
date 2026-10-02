"""Disposable end-to-end maintenance; process/services are synthetic, file witnesses real."""
from pathlib import Path
import json
import os
import sys
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import test_unified_retire as fixtures
import operator_unified_upgrade as upgrade
import operator_unified_handoff as handoff
import operator_unified_cold_start as cold
import operator_unified_retire as records
import operator_model_router as router
import operator_web_service as web_service
from operator_core import model_router_config as settings


@unittest.skipUnless(os.name == "nt", "Windows config witnesses required")
class UpgradeTests(unittest.TestCase):
    fixture = fixtures.UnifiedRetirementTests.fixture
    recover = fixtures.UnifiedRetirementTests.recover
    retirement = fixtures.UnifiedRetirementTests.retirement
    def fixture_active(self):
        fixture = self.fixture(locked=True, pipe=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        cold.consume(fixture.plan)
        fixture.config.write_bytes(fixture.config.read_bytes().replace(b"'one'", b"'two'"))
        return fixture

    def run_upgrade(self, *, web_changed=False, stop_failure=False):
        fixture = self.fixture_active()
        official = fixture.project / "ChatGPT.exe"
        official.write_bytes(b"synthetic packaged application; never execute")
        runtime = {"runtime_sha256": "a" * 64, "web_runtime_changed": web_changed}
        original = records._tree(fixture.plan.parent)
        commands, events = [], []

        def powershell(script, args, **kwargs):
            commands.append(script)
            if script == "restore-codex-official-route.ps1":
                intent = self.recover(fixture)
                return {"status": "completed", "warnings": [], "backup": str(intent.parent)}
            self.assertEqual(script, "operator_desktop_setup.ps1")
            fixture._select_entry()

        old_control = router.control

        def control(state, port, *, stop=False):
            if stop:
                if stop_failure:
                    raise handoff.HandoffError("synthetic_stop_failure")
                return {"status": "stopping", "pid": 4321}
            return old_control(state, port)

        with patch.object(handoff, "_fixed_paths", return_value=(fixture.project, Path(handoff.__file__).parent)), \
             patch.object(upgrade, "bound_runtime", return_value=runtime), \
             patch.object(upgrade, "_powershell", side_effect=powershell), \
             patch.object(settings, "ensure_recovery_shortcut"), \
             patch.object(records, "_stopped"), \
             patch.object(router, "reserve_inactive_port", return_value=nullcontext()), \
             patch.object(router, "control", side_effect=control), \
             patch.object(router, "start", return_value={"status": "ready", "pid": 4321, "service": "fixture"}) as start, \
             patch.object(router, "bind_web", return_value={"pid": 4321, "service": "fixture"}), \
             patch.object(web_service, "load_profile", return_value=(fixture.profile, {"settings": {"path": "fixture"}})), \
             patch.object(web_service, "configure") as configure, \
             patch.object(web_service, "control") as web_stop, \
             patch.object(web_service, "status", return_value={"status": "stopped"}), \
             patch.object(web_service, "start", return_value={"status": "ready", "active": False, "reused": True}) as web_start:
            prepared = handoff.prepare(fixture.project, fixture.home, Path(sys.executable), official,
                                       upgrade_witnessed=True)
            path = Path(prepared["manifest"])
            manifest = handoff._load_manifest(path)
            # The fake old service is absent only during the explicit stop wait;
            # other file/config witnesses continue to use fixture process identities.
            original_identity = web_service.process_identity
            stopped = False

            def progress(stage):
                nonlocal stopped
                events.append(stage)
                stopped = stage == "stop_router"

            def identity(pid):
                return None if stopped and pid == 4321 else original_identity(pid)

            with patch.object(web_service, "process_identity", side_effect=identity):
                if stop_failure:
                    with self.assertRaisesRegex(handoff.HandoffError, "synthetic_stop_failure"):
                        handoff.execute(manifest, progress, path.parent)
                    self.assertTrue(upgrade.native_reopen_safe(manifest, path.parent))
                    self.assertTrue(fixture.plan.exists())
                    start.assert_not_called()
                    web_start.assert_not_called()
                    return
                handoff.execute(manifest, progress, path.parent)
            self.assertEqual(cold.status(fixture.plan)["status"], "armed")
            self.assertEqual(cold.consume(fixture.plan)["status"], "config_switch_witnessed")
            self.assertFalse(upgrade.native_reopen_safe(manifest, path.parent))
            archive = next((fixture.home / records.ARCHIVE).iterdir()) / "evidence"
            archived = records._tree(archive)
            self.assertTrue(all(archived[k] == v for k, v in original.items()))
            self.assertEqual(records.archive_status(fixture.home)["status"], "retained")
            self.assertEqual(events.count("stop_router"), 1)
            self.assertEqual(events.count("prepare"), 1)
            start.assert_called_once()
            self.assertEqual(commands, ["restore-codex-official-route.ps1"])
            reselection = path.parent / "entry-reselection"
            self.assertTrue((reselection / "completed.json").is_file())
            self.assertEqual((reselection / "boundary.bak").read_bytes(), (reselection / "before.json").read_bytes())
            self.assertEqual(web_stop.call_count, int(web_changed))
            self.assertEqual(configure.call_count, int(web_changed))
            self.assertEqual(web_start.call_count, 2 if web_changed else 0)

    def test_completed_entry_replaced_with_new_witness_preserving_old_evidence(self):
        self.run_upgrade()

    def test_saved_web_source_upgrade_stops_once_and_registers_same_ready_generation(self):
        self.run_upgrade(web_changed=True)

    def test_stop_failure_keeps_original_and_allows_witnessed_native_reopen(self):
        self.run_upgrade(stop_failure=True)

    def test_uncertain_prior_attempt_cannot_be_upgraded(self):
        fixture = self.fixture_active()
        (fixture.plan.parent / "completion.json").unlink()
        with self.assertRaises((records.RetireError, OSError)):
            upgrade.inspect(fixture.plan, Path(sys.executable), None)
        self.assertFalse((fixture.home / records.ARCHIVE).exists())

    def test_plan_claim_prevents_another_upgrade_handoff(self):
        fixture = self.fixture_active()
        root = fixture.project / ".codex/operator-unified-handoff"
        root.mkdir()
        digest = "e" * 64
        (root / ("upgrade-" + digest + ".claim")).write_bytes(b"retained uncertain launch")
        with self.assertRaisesRegex(handoff.HandoffError, "prior_upgrade_requires_review"):
            handoff._no_prior_upgrade(fixture.project, digest)
        handoff._no_prior_upgrade(fixture.project, "f" * 64)

    def test_entry_reselection_preserves_later_edits_and_never_repeats(self):
        fixture = self.fixture_active()
        plan, _, _ = cold._plan(fixture.plan)
        arm, _ = records._load(fixture.plan.parent / "arm.json")
        recovery = self.recover(fixture)
        self.retirement(fixture, recovery)
        with patch.object(records, "_stopped"):
            review = records.archive_preview(fixture.plan)
            records.archive_retired(fixture.plan, review["review_sha256"])
        run = fixture.project / ".codex/reselection-test"
        run.mkdir()
        target = fixture.entry / "desktop-entry.json"
        current = target.read_bytes()
        target.write_bytes(current + b" ")
        with self.assertRaisesRegex(handoff.HandoffError, "recovered_bytes_changed"):
            upgrade.reselect_entry(plan, arm["entry"], recovery, run)
        self.assertEqual(target.read_bytes(), current + b" ")
        self.assertFalse((run / "entry-reselection").exists())
        target.write_bytes(current)
        upgrade.reselect_entry(plan, arm["entry"], recovery, run)
        after = target.read_bytes()
        with self.assertRaises(handoff.HandoffError):
            upgrade.reselect_entry(plan, arm["entry"], recovery, run)
        self.assertEqual(target.read_bytes(), after)

    def test_bound_runtime_rejects_changed_sessions_busy_requests_and_settings(self):
        fixture = self.fixture_active()
        plan, _, _ = cold._plan(fixture.plan)
        binding = plan["router"]
        profile_config = {"settings": {"path": "synthetic-settings"}, "runtime": {"old": True}}
        live = ({}, binding["web_route"]["session_sha256"], {}, {})
        result = fixture._router_control(fixture.router_state, 4318)
        with patch.object(web_service, "load_profile", return_value=(fixture.profile, profile_config)), \
             patch.object(web_service, "current_record", return_value={}), \
             patch.object(web_service, "observe", return_value=({"status": "ready", "active": False}, live)), \
             patch.object(web_service, "settings_identity", return_value=profile_config["settings"]) as settings_id, \
             patch.object(web_service, "read_bytes", return_value=b"synthetic profile"), \
             patch.object(web_service, "digest", return_value=binding["web_route"]["profile_sha256"]), \
             patch.object(web_service, "runtime_identity", return_value={"new": True}), \
             patch.object(router, "control", return_value=result):
            self.assertTrue(upgrade.bound_runtime(plan)["web_runtime_changed"])
            result["diagnostics"]["timing"]["active"] = 1
            with self.assertRaisesRegex(handoff.HandoffError, "router_not_idle"):
                upgrade.bound_runtime(plan)
            result["diagnostics"]["timing"]["active"] = 0
            result["diagnostics"]["web_route_session_sha256"] = "f" * 64
            with self.assertRaisesRegex(handoff.HandoffError, "router_not_idle"):
                upgrade.bound_runtime(plan)
            result["diagnostics"]["web_route_session_sha256"] = binding["web_route"]["session_sha256"]
            settings_id.return_value = {"path": "changed"}
            with self.assertRaisesRegex(handoff.HandoffError, "saved_web_not_idle"):
                upgrade.bound_runtime(plan)


if __name__ == "__main__":
    unittest.main()
