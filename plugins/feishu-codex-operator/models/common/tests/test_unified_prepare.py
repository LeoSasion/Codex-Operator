"""Disposable Windows preparation tests; never target the real Codex home."""
from pathlib import Path as _TestPath
import sys as _test_sys

_ROOT = next(parent for parent in _TestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file())
_test_sys.path.insert(0, str(_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_ROOT)

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import operator_model_router as router
import operator_unified_entry_preview as entry_preview
import operator_unified_prepare as prepare
import operator_unified_supersede as supersede
import operator_web_activation_retire as retirement


def digest(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(os.name == "nt", "requires Windows config file identity")
class UnifiedPrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-unified-prepare-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / ".codex").mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.config = self.home / "config.toml"
        self.original = b'model = "gpt-6-sol"\nprivate_key = "retain exact bytes"\n'
        self.config.write_bytes(self.original)
        self.cache = self.home / "models_cache.json"
        self.cache.write_bytes(b'{"existing":"catalog"}\n')
        self.bundle = self.project / ".codex/operator-unified-startup"
        self.state = self.project / ".codex/existing-api-local-router"
        self.state.mkdir(parents=True)
        self.bundle.mkdir()
        self.token = "a" * 64
        (self.state / "token").write_text(self.token, encoding="ascii")
        self.registry = b'{"version":2,"models":[]}\n'
        (self.state / "registry.json").write_bytes(self.registry)
        self.profile = self.project / ".codex/operator-web-service"
        self.profile.mkdir()
        script = b"# reviewed disposable startup workflow\n"
        (self.bundle / "start-codex-with-web.ps1").write_bytes(script)
        (self.bundle / "startup-sync-plan.json").write_text(json.dumps({
            "schema_version": 2, "startup_script": "start-codex-with-web.ps1",
            "entry_files": {"start-codex-with-web.ps1": digest(script)}}), encoding="utf-8")
        self._recovery_fixture()
        self._patch(entry_preview, "_verify_shortcut",
            side_effect=lambda project, link: project == self.project and link == self.link)
        self._patch(prepare.web_startup, "assert_desktop_closed", return_value=None)
        self._patch(prepare.router, "control", side_effect=self._router_control)
        self._patch(prepare.web_service, "route_preview", return_value={
            "profile_sha256": "b" * 64, "session_sha256": "c" * 64})
        self._patch(prepare.web_service, "process_identity", return_value={
            "pid": 4567, "birth": "123456789", "executable": str(self.root / "python.exe")})

    def _patch(self, target, name, **kwargs):
        opened = patch.object(target, name, **kwargs)
        opened.start()
        self.addCleanup(opened.stop)

    def _recovery_fixture(self):
        bundle = self.project / ".codex/operator-native-recovery"
        bundle.mkdir()
        installed = {}
        for name in entry_preview.RECOVERY_FILES:
            raw = (_ROOT / "scripts" / name).read_bytes()
            (bundle / name).write_bytes(raw)
            installed[name] = digest(raw)
        desktop = self.root / "desktop"
        desktop.mkdir()
        self.link = desktop / "恢复官方默认路由.lnk"
        self.link.write_bytes(b"disposable shortcut")
        (bundle / "ownership.json").write_text(json.dumps({
            "schema_version": 1, "project": str(self.project),
            "shortcut": str(self.link), "shortcut_sha256": digest(self.link.read_bytes()),
            "files": installed}), encoding="utf-8")

    def _router_control(self, state, port):
        self.assertEqual((state, port), (self.state, 4318))
        return {"status": "ready", "service": router.service_identity(state),
                "pid": 4567, "diagnostics": {
                    "registry_sha256": digest(self.registry),
                    "web_profile_identity": router.web_profile_identity(self.profile),
                    "web_route_bound": True,
                    "web_route_profile_sha256": "b" * 64,
                    "web_route_session_sha256": "c" * 64}}

    def test_old_or_changed_router_web_binding_blocks_preparation(self):
        original = self._router_control
        def old_router(state, port):
            value = original(state, port)
            value["diagnostics"].pop("web_route_session_sha256")
            return value
        with patch.object(prepare.router, "control", side_effect=old_router):
            old = prepare.preview(*self._args())
        self.assertIn("unified_router_service_unverified", old["blockers"])
        self.assertFalse(old["prepare_available"])
        def changed_router(state, port):
            value = original(state, port)
            value["diagnostics"]["web_route_session_sha256"] = "d" * 64
            return value
        with patch.object(prepare.router, "control", side_effect=changed_router):
            changed = prepare.preview(*self._args())
        self.assertIn("unified_router_service_unverified", changed["blockers"])
        self.assertFalse(changed["prepare_available"])
        self.assertFalse((self.home / prepare.STATE).exists())

    def test_completed_old_activation_uses_owned_replacement_read_only_check(self):
        old = self.project / ".codex/operator-web-startup"
        old.mkdir()
        (old / "legacy-activation-retirement.json").write_bytes(b"disposable marker")
        before = self._files()

        def status(path, *, replacement_home=None):
            self.assertEqual(path, old / "web-startup.json")
            return "retired" if replacement_home == self.home else "uncertain"

        with patch.object(retirement, "retirement_status", side_effect=status):
            report = prepare.preview(*self._args())
        self.assertEqual(before, self._files())
        self.assertTrue(report["prepare_available"])
        self.assertNotIn("unified_old_activation_record_requires_review", report["blockers"])
        with patch.object(retirement, "retirement_status", return_value="uncertain"):
            rejected = prepare.preview(*self._args())
        self.assertFalse(rejected["prepare_available"])
        self.assertIn("unified_old_activation_record_requires_review", rejected["blockers"])

    def _args(self):
        return self.project, self.home, self.state, self.profile, 4318

    def _files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_preview_is_read_only_and_marker_desktop_do_not_prevent_snapshot(self):
        marker = self.home / "operator-native-route-only"
        marker.write_bytes(b"must remain")
        with patch.object(prepare.web_startup, "assert_desktop_closed",
                          side_effect=ValueError("desktop open")):
            before = self._files()
            report = prepare.preview(*self._args())
            self.assertEqual(before, self._files())
            self.assertEqual(report["status"], "reviewed_preview")
            self.assertTrue(report["prepare_available"])
            self.assertIn("unified_native_route_lock_active", report["blockers"])
            self.assertIn("unified_desktop_open_or_unknown", report["blockers"])
            result = prepare.prepare(*self._args(), report["review_sha256"])
        self.assertEqual(result["status"], "prepared_not_armed")
        self.assertFalse(result["activation_available"])
        self.assertEqual(marker.read_bytes(), b"must remain")
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.cache.read_bytes(), b'{"existing":"catalog"}\n')
        saved = self.home / prepare.STATE
        self.assertEqual((saved / "before.toml").read_bytes(), self.original)
        self.assertEqual((saved / "cache-before.bin").read_bytes(), self.cache.read_bytes())
        plan_raw = (saved / "plan.json").read_bytes()
        plan = json.loads(plan_raw)
        journal = json.loads((saved / "journal.json").read_bytes())
        self.assertEqual(journal, {"schema_version": 1,
                                  "phase": "prepared_not_armed", "plan_sha256": digest(plan_raw)})
        self.assertEqual(plan["startup_bundle"]["path"], str(self.bundle))
        self.assertEqual(plan["candidate_sha256"], digest((saved / "candidate.toml").read_bytes()))
        self.assertEqual(plan["config_sha256"], digest(self.original))
        self.assertEqual(plan["cache"]["sha256"], digest(self.cache.read_bytes()))
        self.assertEqual(set(result["future_arm_blockers"]),
                         {"unified_native_route_lock_active", "unified_desktop_open_or_unknown"})
        self.assertNotIn(self.token, json.dumps(report))
        self.assertNotIn("retain exact bytes", json.dumps(report))
        self.assertEqual(set(prepare.preview(*self._args())["blockers"]),
                         {"unified_native_route_lock_active", "unified_existing_preparation_requires_review"})

    def test_review_digest_and_config_change_reject_without_writes(self):
        report = prepare.preview(*self._args())
        self.assertTrue(report["prepare_available"])
        with self.assertRaisesRegex(prepare.PrepareError, "unified_review_changed"):
            prepare.prepare(*self._args(), "0" * 64)
        self.config.write_bytes(self.original + b"# external edit\n")
        with self.assertRaisesRegex(prepare.PrepareError, "unified_review_changed"):
            prepare.prepare(*self._args(), report["review_sha256"])
        self.assertFalse((self.home / prepare.STATE).exists())
        self.assertTrue(self.config.read_bytes().endswith(b"# external edit\n"))

    def test_retirement_verifier_change_rejects_review_before_snapshot_writes(self):
        report = prepare.preview(*self._args())
        before = self._files()
        verifier = Path(retirement.__file__)
        read_bytes = Path.read_bytes

        def changed_read(path):
            raw = read_bytes(path)
            return raw + b"# changed verifier\n" if path == verifier else raw

        with patch.object(Path, "read_bytes", changed_read):
            changed = prepare.preview(*self._args())
            self.assertNotEqual(changed["review_sha256"], report["review_sha256"])
            with self.assertRaisesRegex(prepare.PrepareError, "unified_review_changed"):
                prepare.prepare(*self._args(), report["review_sha256"])
        self.assertEqual(before, self._files())
        self.assertFalse((self.home / prepare.STATE).exists())

    def test_unverified_service_blocks_persistence(self):
        with patch.object(prepare.router, "control", side_effect=OSError("unavailable")):
            before = self._files()
            report = prepare.preview(*self._args())
            self.assertFalse(report["prepare_available"])
            self.assertIn("unified_router_service_unverified", report["blockers"])
            with self.assertRaisesRegex(prepare.PrepareError, "unified_preparation_blocked"):
                prepare.prepare(*self._args(), report["review_sha256"])
            self.assertEqual(before, self._files())

    def test_partial_snapshot_is_terminal_and_never_reused(self):
        report = prepare.preview(*self._args())
        original_write = prepare._write_new

        def fail_after_before(path, data):
            if path.name == "candidate.toml":
                raise OSError("injected write failure")
            return original_write(path, data)

        with patch.object(prepare, "_write_new", side_effect=fail_after_before):
            with self.assertRaises(OSError):
                prepare.prepare(*self._args(), report["review_sha256"])
        saved = self.home / prepare.STATE
        self.assertEqual((saved / "before.toml").read_bytes(), self.original)
        self.assertFalse((saved / "journal.json").exists())
        after = prepare.preview(*self._args())
        self.assertIn("unified_existing_preparation_requires_review", after["blockers"])
        with self.assertRaisesRegex(prepare.PrepareError, "unified_review_changed"):
            prepare.prepare(*self._args(), report["review_sha256"])
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_bundle_mismatch_blocks_persistence_until_it_can_be_bound(self):
        (self.bundle / "startup-sync-plan.json").write_bytes(b'{}')
        report = prepare.preview(*self._args())
        self.assertFalse(report["prepare_available"])
        self.assertIn("unified_startup_bundle_unverified", report["blockers"])
        with self.assertRaisesRegex(prepare.PrepareError, "unified_preparation_blocked"):
            prepare.prepare(*self._args(), report["review_sha256"])
        self.assertFalse((self.home / prepare.STATE).exists())

    def test_identical_archived_plan_is_rejected_before_creating_a_new_directory(self):
        review = prepare.preview(*self._args())
        prepare.prepare(*self._args(), review["review_sha256"])
        source = self.home / prepare.STATE
        plan_sha = digest((source / "plan.json").read_bytes())
        manifest = supersede._manifest(source)
        generation = self.home / supersede.ROOT / ("generation-" + "a" * 32)
        generation.mkdir(parents=True)
        archived_review = {"schema_version": 1, "scope": "prepared_plan_supersede",
                           "plan_sha256": plan_sha}
        intent = {"schema_version": 1, "phase": "may_have_superseded", "home": str(self.home),
                  "source": str(source), "target": str(generation / "activation"),
                  "plan_sha256": plan_sha, "review": archived_review,
                  "review_sha256": digest(supersede._json(archived_review)), "manifest": manifest}
        intent_raw = supersede._json(intent)
        (generation / "intent.json").write_bytes(intent_raw)
        os.rename(source, generation / "activation")
        (generation / "receipt.json").write_bytes(supersede._json({"schema_version": 1,
            "phase": "superseded_witnessed", "intent_sha256": digest(intent_raw), "plan_sha256": plan_sha}))
        self.assertEqual(supersede.archive_status(self.home)["status"], "superseded_witnessed")
        fresh = prepare.preview(*self._args())
        self.assertEqual(fresh["review_sha256"], review["review_sha256"])
        before = self._files()
        with self.assertRaisesRegex(prepare.PrepareError, "unified_prepared_plan_already_archived"):
            prepare.prepare(*self._args(), fresh["review_sha256"])
        self.assertFalse(source.exists())
        self.assertEqual(before, self._files())
        self.assertEqual(supersede.archive_status(self.home)["status"], "superseded_witnessed")

    def test_exact_config_and_cache_are_frozen_through_final_check_and_journal(self):
        cache_raw = b'{ "fetched_at": "2026-09-30T10:00:00Z", "models": [], "extra": [1, null] }\r\n'
        self.cache.write_bytes(cache_raw)
        review = prepare.preview(*self._args())
        before_config = prepare.transaction.observe_config(self.config)
        before_cache = prepare.transaction._snapshot(self.cache)
        replacements = {}
        for path in (self.config, self.cache):
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(b"later owner replacement")
            replacements[path] = replacement
        observed_stages = []

        def assert_frozen(stage):
            observed_stages.append(stage)
            for path in (self.config, self.cache):
                with self.subTest(stage=stage, path=path.name):
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b"concurrent overwrite")
                    with self.assertRaises(PermissionError):
                        path.rename(path.with_name(path.name + ".renamed"))
                    with self.assertRaises(PermissionError):
                        os.replace(replacements[path], path)

        original_directory = prepare.private_directory
        original_write = prepare._write_new
        original_readiness = prepare._readiness
        reads = 0

        def create(path):
            assert_frozen("directory")
            return original_directory(path)

        def write(path, raw):
            assert_frozen(path.name)
            return original_write(path, raw)

        def readiness(*args, **kwargs):
            nonlocal reads
            value = original_readiness(*args, **kwargs)
            reads += 1
            if reads > 1:
                assert_frozen("readiness-" + str(reads))
            return value

        with patch.object(prepare, "private_directory", side_effect=create), \
                patch.object(prepare, "_write_new", side_effect=write), \
                patch.object(prepare, "_readiness", side_effect=readiness):
            result = prepare.prepare(*self._args(), review["review_sha256"])
        self.assertEqual(result["status"], "prepared_not_armed")
        self.assertEqual(reads, 4)
        self.assertIn("journal.json", observed_stages)
        self.assertEqual(observed_stages[-1], "journal.json")
        saved = self.home / prepare.STATE
        plan = json.loads((saved / "plan.json").read_bytes())
        self.assertEqual(plan["review_sha256"], review["review_sha256"])
        self.assertEqual(plan["config_identity"], prepare._identity(before_config.identity))
        self.assertEqual(plan["cache"], {"existed": True, "sha256": digest(cache_raw),
            "identity": prepare._identity(before_cache.identity)})
        self.assertEqual((saved / "cache-before.bin").read_bytes(), cache_raw)
        self.assertEqual(plan["source_sha256"]["transaction"],
                         digest(Path(prepare.transaction.__file__).read_bytes()))
        self.assertEqual(prepare.transaction.observe_config(self.config), before_config)
        self.assertEqual(prepare.transaction._snapshot(self.cache), before_cache)
        # The temporary freeze ends with the operation, for both writes and
        # file replacement. No permanent attributes or permissions are applied.
        for path in (self.config, self.cache):
            path.write_bytes(b"allowed after preparation")
            renamed = path.with_name(path.name + ".after")
            path.rename(renamed)
            renamed.rename(path)
            os.replace(replacements[path], path)
            self.assertEqual(path.read_bytes(), b"later owner replacement")

    def test_snapshot_bytes_or_identity_race_rejects_before_directory_allocation(self):
        original_proof = supersede._assert_unarchived_plan
        for path, same_bytes in ((self.config, True), (self.cache, True), (self.cache, False)):
            with self.subTest(path=path.name, same_bytes=same_bytes):
                review = prepare.preview(*self._args())
                previous = prepare.transaction._snapshot(path)

                def change_after_proof(*args):
                    original_proof(*args)
                    if same_bytes:
                        replacement = path.with_name(path.name + ".new-identity")
                        replacement.write_bytes(previous.data)
                        os.replace(replacement, path)
                    else:
                        path.write_bytes(previous.data + b" ")

                with patch.object(supersede, "_assert_unarchived_plan", side_effect=change_after_proof):
                    with self.assertRaisesRegex(prepare.PrepareError, "^unified_review_changed$"):
                        prepare.prepare(*self._args(), review["review_sha256"])
                self.assertFalse((self.home / prepare.STATE).exists())
                current = prepare.transaction._snapshot(path)
                if same_bytes:
                    self.assertEqual(current.data, previous.data)
                    self.assertNotEqual(current.identity, previous.identity)
                else:
                    self.assertEqual(current.identity, previous.identity)
                    self.assertEqual(current.data, previous.data + b" ")

    def test_freezer_source_or_router_change_is_rechecked_before_allocation(self):
        original_proof = supersede._assert_unarchived_plan
        original_read = Path.read_bytes
        source = Path(prepare.transaction.__file__)
        process = {"pid": 4567, "birth": "123456789", "executable": str(self.root / "python.exe")}
        for gate in ("source", "router"):
            with self.subTest(gate=gate):
                changed = False
                review = prepare.preview(*self._args())
                before = self._files()

                def change_after_proof(*args):
                    nonlocal changed
                    original_proof(*args)
                    changed = True

                def read(path):
                    raw = original_read(path)
                    return raw + b"# changed freeze helper\n" if changed and gate == "source" and path == source else raw

                def identity(_pid):
                    return {**process, "birth": "987654321"} if changed and gate == "router" else process

                with patch.object(supersede, "_assert_unarchived_plan", side_effect=change_after_proof), \
                        patch.object(Path, "read_bytes", read), \
                        patch.object(prepare.web_service, "process_identity", side_effect=identity):
                    with self.assertRaisesRegex(prepare.PrepareError, "^unified_review_changed$"):
                        prepare.prepare(*self._args(), review["review_sha256"])
                self.assertFalse((self.home / prepare.STATE).exists())
                self.assertEqual(self._files(), before)
                self.config.write_bytes(self.original)

    def test_existing_writer_prevents_freeze_without_allocating_or_retrying(self):
        review = prepare.preview(*self._args())
        original_readiness = prepare._readiness
        writer = None
        reads = 0

        def readiness(*args, **kwargs):
            nonlocal writer, reads
            result = original_readiness(*args, **kwargs)
            reads += 1
            writer = self.cache.open("r+b")
            return result

        try:
            with patch.object(prepare, "_readiness", side_effect=readiness):
                with self.assertRaises(prepare.transaction.TransactionFailure):
                    prepare.prepare(*self._args(), review["review_sha256"])
            self.assertEqual(reads, 1)
            self.assertFalse((self.home / prepare.STATE).exists())
        finally:
            if writer is not None:
                writer.close()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.cache.read_bytes(), b'{"existing":"catalog"}\n')
        # Config was frozen before cache failed to open; the failure must also
        # release that earlier handle rather than leaving the user's file busy.
        self.config.write_bytes(self.original + b"# unlocked after rejection\n")

    def test_missing_cache_stays_absent_and_plan_does_not_invent_a_snapshot(self):
        self.cache.unlink()
        review = prepare.preview(*self._args())
        result = prepare.prepare(*self._args(), review["review_sha256"])
        self.assertEqual(result["status"], "prepared_not_armed")
        saved = self.home / prepare.STATE
        plan = json.loads((saved / "plan.json").read_bytes())
        self.assertEqual(plan["cache"], {"existed": False, "sha256": None, "identity": None})
        self.assertFalse(self.cache.exists())
        self.assertFalse((saved / "cache-before.bin").exists())

    def test_missing_cache_appearing_before_freeze_rejects_before_allocation(self):
        self.cache.unlink()
        review = prepare.preview(*self._args())
        original_proof = supersede._assert_unarchived_plan

        def appeared(*args):
            original_proof(*args)
            self.cache.write_bytes(b"new external cache")

        with patch.object(supersede, "_assert_unarchived_plan", side_effect=appeared):
            with self.assertRaisesRegex(prepare.PrepareError, "^unified_review_changed$"):
                prepare.prepare(*self._args(), review["review_sha256"])
        self.assertFalse((self.home / prepare.STATE).exists())
        self.assertEqual(self.cache.read_bytes(), b"new external cache")

    def test_missing_cache_appearing_after_snapshot_write_is_terminal_and_retained(self):
        self.cache.unlink()
        review = prepare.preview(*self._args())
        original_write = prepare._write_new

        def appeared(path, raw):
            original_write(path, raw)
            if path.name == "plan.json":
                self.cache.write_bytes(b"new external cache")

        with patch.object(prepare, "_write_new", side_effect=appeared):
            with self.assertRaisesRegex(prepare.PrepareError,
                                       "^unified_review_changed_after_snapshot_write$"):
                prepare.prepare(*self._args(), review["review_sha256"])
        saved = self.home / prepare.STATE
        self.assertTrue((saved / "plan.json").is_file())
        self.assertFalse((saved / "journal.json").exists())
        self.assertFalse((saved / "cache-before.bin").exists())
        self.assertEqual(self.cache.read_bytes(), b"new external cache")
        before = self._files()
        with self.assertRaisesRegex(prepare.PrepareError, "^unified_review_changed$"):
            prepare.prepare(*self._args(), review["review_sha256"])
        self.assertEqual(self._files(), before)


if __name__ == "__main__":
    unittest.main()
