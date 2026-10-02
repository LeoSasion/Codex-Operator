"""A read-only real-home preview exercised against disposable file fixtures."""

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

import operator_unified_desktop as candidate
import operator_unified_entry_preview as entry_preview


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows shortcut inspection required")
class DesktopPairEntryOwnershipTests(unittest.TestCase):
    def setUp(self):
        # Reuse the pair's actual COM-link fixture. Its Desktop, native home and
        # helper generations all live below one disposable project directory.
        import test_desktop_pair as pair_fixture
        self.fixture = pair_fixture.DesktopPairTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.install()
        self.project = self.fixture.project
        self.bundle = self.fixture.bundle
        self.receipt = self.fixture.root / "ownership.json"
        self.links = (self.fixture.desktop / "ChatGPT 原生入口.lnk",
                      self.fixture.desktop / "ChatGPT 拓展模型 09-30 入口.lnk")

    def verify(self, **kwargs):
        return entry_preview.verify_owned_entry(self.project, self.bundle,
            test_shortcuts=self.links, **kwargs)

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def test_pair_is_verified_without_legacy_links_or_writes(self):
        before = self.snapshot()
        result = self.verify()
        self.assertRegex(result, r"^[a-f0-9]{64}$")
        self.assertEqual(result, self.verify())
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.fixture.desktop / "Codex拓展入口.lnk").exists())

    def test_utf8_python_child_preserves_chinese_shortcut_identity_without_writes(self):
        before = self.snapshot()
        expected = self.verify()
        child = r'''
import json
from pathlib import Path
import sys
request = json.load(sys.stdin)
sys.path.insert(0, request["scripts"])
from operator_unified_entry_preview import verify_owned_entry
fingerprint = verify_owned_entry(Path(request["project"]), Path(request["bundle"]),
    test_shortcuts=tuple(Path(value) for value in request["links"]))
print(json.dumps({"utf8_mode": sys.flags.utf8_mode, "fingerprint": fingerprint}))
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", child],
            input=json.dumps({"scripts": str(_OPERATOR_PLUGIN_ROOT / "scripts"),
                              "project": str(self.project), "bundle": str(self.bundle),
                              "links": [str(path) for path in self.links]}),
            text=True, encoding="utf-8", capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"utf8_mode": 1, "fingerprint": expected})
        self.assertEqual(before, self.snapshot())

    def test_pair_and_normal_ownership_both_bind_the_private_fingerprint(self):
        first = self.verify()
        raw = self.receipt.read_bytes()
        self.receipt.write_bytes(raw + b"\n")
        second = self.verify()
        self.assertNotEqual(first, second)
        owner = self.project / ".codex/operator-installation/ownership.json"
        owner.write_bytes(owner.read_bytes() + b"\n")
        self.assertNotEqual(second, self.verify())

    def test_changed_helper_and_extension_build_are_rejected(self):
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        folder = self.fixture.root / "generations" / receipt["generation"]
        for path in [*(folder / name for name in receipt["files"]),
                     *(self.bundle / name for name in receipt["build"])]:
            with self.subTest(file=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                try:
                    with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
                        self.verify()
                finally:
                    path.write_bytes(original)

    def test_even_receipt_matching_links_must_target_exact_native_and_extension_entries(self):
        import test_desktop_pair as pair_fixture
        for index, link in enumerate(self.links):
            with self.subTest(shortcut=index):
                original_link, original_receipt = link.read_bytes(), self.receipt.read_bytes()
                code = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + pair_fixture.q(link) + ")\n"
                code += "$s.TargetPath=" + pair_fixture.q(self.bundle / "incorrect.exe") + ";$s.Save()"
                changed = self.fixture.ps(code, imports=False)
                self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)
                receipt = json.loads(original_receipt)
                receipt["links"][str(link)]["after"] = candidate.digest(link.read_bytes())
                self.receipt.write_text(json.dumps(receipt), encoding="utf-8")
                try:
                    with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
                        self.verify()
                finally:
                    link.write_bytes(original_link)
                    self.receipt.write_bytes(original_receipt)

    def test_fixture_links_must_match_record_and_cannot_replace_real_desktop_check(self):
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            entry_preview.verify_owned_entry(self.project, self.bundle)
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            entry_preview.verify_owned_entry(self.project, self.bundle,
                test_shortcuts=(self.links[0], self.fixture.desktop / "other.lnk"))
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            entry_preview.verify_owned_entry(self.project, self.bundle,
                test_shortcuts=(self.links[0], self.links[0]))
        with patch.object(entry_preview.tempfile, "gettempdir", return_value=str(self.fixture.home)):
            with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
                self.verify()

    def test_pair_never_reinterprets_migration_recovery_or_pending_ownership(self):
        before = self.snapshot()
        for recovered in ({}, {"before_sha256": "a" * 64, "after_sha256": "b" * 64}):
            with self.subTest(recovered=recovered):
                with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
                    self.verify(recovered_config=recovered)
        self.assertEqual(before, self.snapshot())
        migration = self.project / ".codex/operator-entry-migration"
        migration.mkdir()
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            self.verify()
        migration.rmdir()
        pending = self.fixture.root / "pending.json"
        pending.write_bytes(b"{}")
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            self.verify()
        pending.unlink()
        import test_desktop_pair as pair_fixture
        restored = self.fixture.ps("Restore-OperatorDesktopPair -ProjectRoot " + pair_fixture.q(self.project))
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            self.verify()


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows shortcut inspection required")
class LegacyPairEntryOwnershipTests(unittest.TestCase):
    def setUp(self):
        import test_desktop_pair_legacy as pair_fixture
        self.fixture = pair_fixture.LegacyPairTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.apply()
        self.project = self.fixture.root
        self.bundle = self.project / ".codex/operator-desktop-entry"
        self.pair_root = self.project / ".codex/operator-desktop-pair"
        self.receipt = self.pair_root / "ownership.json"
        self.record = json.loads(self.receipt.read_bytes())
        desktop = Path(self.record["desktop"])
        self.links = (desktop / "ChatGPT 原生入口.lnk",
                      desktop / ("ChatGPT 拓展模型 " + self.record["build_date"][5:] + " 入口.lnk"))
        self.legacy_desktop = Path(self.record["legacy"]["desktop"])
        self.legacy_start = Path(self.record["legacy"]["start"])

    def verify(self, **kwargs):
        return entry_preview.verify_owned_entry(self.project, self.bundle,
            test_shortcuts=self.links, **kwargs)

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def reject(self, **kwargs):
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            self.verify(**kwargs)

    def test_legacy_pair_preserves_entry_only_ownership_and_is_read_only(self):
        before = self.snapshot()
        self.assertFalse(self.legacy_desktop.exists())
        self.assertTrue(self.legacy_start.is_file())
        self.assertFalse((self.project / ".codex/operator-installation/ownership.json").exists())
        fingerprint = self.verify()
        self.assertRegex(fingerprint, r"^[a-f0-9]{64}$")
        self.assertEqual(fingerprint, self.verify())
        self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            entry_preview.verify_owned_entry(self.project, self.bundle)

    def test_witnessed_native_config_keeps_same_fingerprint_without_accepting_other_changes(self):
        fingerprint = self.verify()
        config = self.bundle / "desktop-entry.json"
        original = config.read_bytes()
        native = json.loads(original)
        native["mode"] = "native"
        config.write_text(json.dumps(native), encoding="utf-8")
        recovered = {"name": "desktop-entry.json", "target": str(config),
                     "before_sha256": candidate.digest(original),
                     "after_sha256": candidate.digest(config.read_bytes())}
        before = self.snapshot()
        self.assertEqual(fingerprint, self.verify(recovered_config=recovered))
        self.assertEqual(before, self.snapshot())
        self.reject()
        for invalid in ({}, {**recovered, "before_sha256": "0" * 64},
                        {**recovered, "after_sha256": "0" * 64},
                        {**recovered, "target": str(self.project / "unrelated.json")},
                        {**recovered, "name": "unrelated.json"},
                        {**recovered, "target": [str(config)]}):
            with self.subTest(recovery=invalid):
                self.reject(recovered_config=invalid)
        script = self.bundle / "operator_desktop_entry.ps1"
        script.write_bytes(script.read_bytes() + b"changed")
        self.reject(recovered_config=recovered)

    def test_build_helpers_legacy_evidence_and_start_link_remain_bound(self):
        self.verify()
        generation = self.pair_root / "generations" / self.record["generation"]
        paths = [*(self.bundle / name for name in self.record["build"]),
                 *(generation / name for name in self.record["files"]),
                 self.receipt, self.pair_root / "legacy-origin.json", self.legacy_start,
                 self.project / ".codex/operator-entry-migration/journal.json",
                 self.project / ".codex/operator-entry-upgrade/receipt.json",
                 self.project / ".codex/operator-entry-shortcut-adoption/receipt.json"]
        for path in paths:
            if not path.exists():
                continue
            with self.subTest(file=str(path.relative_to(self.project))):
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                try:
                    self.reject()
                finally:
                    path.write_bytes(original)

    def test_same_bytes_cannot_replace_the_renamed_desktop_or_original_start_entity(self):
        fingerprint = self.verify()
        for link in (self.links[1], self.legacy_start):
            with self.subTest(shortcut=link.name):
                retained = link.with_suffix(".retained-identity")
                original = link.read_bytes()
                link.replace(retained)
                try:
                    link.write_bytes(original)
                    self.assertEqual(candidate.digest(link.read_bytes()), candidate.digest(original))
                    self.reject()
                finally:
                    link.unlink(missing_ok=True)
                    retained.replace(link)
        self.assertEqual(fingerprint, self.verify())

    def test_normal_owner_old_name_and_unfinished_transaction_are_conflicts(self):
        self.verify()
        owner = self.project / ".codex/operator-installation/ownership.json"
        owner.parent.mkdir(exist_ok=True)
        pending = self.pair_root / "upgrades" / ("f" * 32) / "pending.json"
        for path, raw in ((owner, b"{}"), (self.legacy_desktop, b"later user entry"),
                          (pending, b"{}")):
            with self.subTest(conflict=path.name):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                try:
                    before = self.snapshot()
                    self.reject()
                    self.assertEqual(before, self.snapshot())
                finally:
                    path.unlink()

    def test_temporary_override_does_not_accept_arbitrary_legacy_or_new_paths(self):
        original = self.receipt.read_bytes()
        changed = json.loads(original)
        changed["legacy"]["start"] = str(self.project.parent / "unowned-start.lnk")
        self.receipt.write_text(json.dumps(changed), encoding="utf-8")
        try:
            self.reject()
        finally:
            self.receipt.write_bytes(original)
        with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
            entry_preview.verify_owned_entry(self.project, self.bundle,
                test_shortcuts=(self.links[0], self.links[1].with_name("unowned-new.lnk")))
        self.verify()

    def test_preexisting_config_upgrade_and_shortcut_adoption_remain_required(self):
        # Model the current legacy installation: an explicit Desktop adoption
        # and config-only upgrade both precede the separately reviewed pair.
        full = type(self.fixture)()
        self.addCleanup(full.doCleanups)
        full.setUp()
        full.assert_ok(full.run_ps(r'''
$state=Get-OperatorEntryMigrationState $p
$desktop=@(Get-OperatorDesktopPaths)[0];$start=@(Get-OperatorDesktopPaths)[1]
$shell=New-Object -ComObject WScript.Shell
$changed=$shell.CreateShortcut($desktop);$changed.Description='Reviewed later Desktop description';$changed.Save()
$audit=Join-Path $p '.codex/audit/web-startup-comment-fix-20260919'
New-Item -ItemType Directory -Path $audit -Force|Out-Null
Copy-Item -LiteralPath $desktop -Destination (Join-Path $audit 'desktop-link-at-review.lnk')
$rows=@()
foreach($path in @($desktop,$start)){
  $link=$shell.CreateShortcut($path)
  $rows+=@{path=$path;sha256=(Get-OperatorFingerprint $path);installed_sha256=$state.entries[$path].after;
    target=$link.TargetPath;arguments=$link.Arguments;working_directory=$link.WorkingDirectory;
    icon=$link.IconLocation;window_style=$link.WindowStyle}
}
$rows|ConvertTo-Json -Depth 5|Set-Content (Join-Path $audit 'shortcuts-review.json') -Encoding utf8
[IO.File]::WriteAllText((Join-Path $audit 'report.md'),'Later Desktop bytes retained for separate review.')
$selectedHome=Join-Path $p 'disposable-home'
[IO.File]::WriteAllText((Join-Path $selectedHome 'operator-native-route-only'),"operator-native-route-only-v1`n")
$adoption=Get-OperatorEntryShortcutAdoptionPlan $p $selectedHome
Invoke-OperatorEntryShortcutAdoption $p $selectedHome $adoption.sha256 -OwnerApprovedShortcutAdoption|Out-Null
$unified=Join-Path $p '.codex/operator-unified-startup';New-Item -ItemType Directory -Path $unified|Out-Null
[IO.File]::WriteAllText((Join-Path $unified 'start-codex-with-web.ps1'),'exit 0')
$workflowHash=Get-OperatorFingerprint (Join-Path $unified 'start-codex-with-web.ps1')
@{schema_version=2;startup_script='start-codex-with-web.ps1';entry_files=@{'start-codex-with-web.ps1'=$workflowHash}}|
  ConvertTo-Json -Depth 5|Set-Content (Join-Path $unified 'startup-sync-plan.json') -Encoding utf8
$upgrade=Get-OperatorEntryUpgradePlan $p $unified $selectedHome
Invoke-OperatorEntryUpgrade $p $unified $upgrade.sha256 $selectedHome|Out-Null
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p
[IO.File]::WriteAllText((Join-Path $p 'candidate-path.txt'),$candidate.candidate_directory)
'''))
        full.apply()
        record = json.loads((full.pair_root / "ownership.json").read_bytes())
        links = (full.desktop / "ChatGPT 原生入口.lnk",
                 full.desktop / ("ChatGPT 拓展模型 " + record["build_date"][5:] + " 入口.lnk"))
        def verify():
            return entry_preview.verify_owned_entry(full.root, full.bundle, test_shortcuts=links)

        self.assertRegex(verify(), r"^[a-f0-9]{64}$")
        for relative in ("operator-entry-upgrade/receipt.json",
                         "operator-entry-shortcut-adoption/receipt.json"):
            path = full.root / ".codex" / relative
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            try:
                with self.assertRaisesRegex(entry_preview.PreviewError, "unified_entry_shortcuts_unverified"):
                    verify()
            finally:
                path.write_bytes(original)


class UnifiedEntryPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-unified-entry-preview-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / ".codex").mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.router = self.root / "router"
        self.router.mkdir()
        (self.router / "token").write_text("a" * 64, encoding="ascii")
        self.config = self.home / "config.toml"
        self.original = b'model = "gpt-6-sol"\ncustom_value = "private credential"\n'
        self.config.write_bytes(self.original)
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "OPENAI_BASE_URL": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self._recovery_fixture()
        # The fixture has no real Windows .lnk. Its injected read-only inspector
        # accepts only the exact disposable Desktop path created below.
        verifier = patch.object(entry_preview, "_verify_shortcut",
            side_effect=lambda project, link: project == self.project and link == self.link)
        verifier.start()
        self.addCleanup(verifier.stop)

    def _recovery_fixture(self, *, stale_source=False):
        bundle = self.project / ".codex/operator-native-recovery"
        bundle.mkdir(exist_ok=True)
        installed = {}
        for name in entry_preview.RECOVERY_FILES:
            raw = (_OPERATOR_PLUGIN_ROOT / "scripts" / name).read_bytes()
            if stale_source and name == entry_preview.RECOVERY_FILES[0]:
                raw += b"\n# older fixture\n"
            (bundle / name).write_bytes(raw)
            installed[name] = candidate.digest(raw)
        desktop = self.root / "desktop"
        desktop.mkdir(exist_ok=True)
        link = desktop / "恢复官方默认路由.lnk"
        self.link = link
        link.write_bytes(b"disposable shortcut fixture")
        receipt = {"schema_version": 1, "project": str(self.project),
                   "shortcut": str(link), "shortcut_sha256": candidate.digest(link.read_bytes()),
                   "files": installed}
        (bundle / "ownership.json").write_text(json.dumps(receipt), encoding="utf-8")

    def _snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_real_home_preview_uses_render_without_writing_or_exposing_source(self):
        with self.assertRaisesRegex(candidate.CandidateError, "candidate_temp_home_required"):
            candidate.preview(self.home, "http://127.0.0.1:4318/" + "a" * 64 + "/backend-api/codex")
        before = self._snapshot()
        report = entry_preview.preview(self.project, self.home, self.router, 4318)
        self.assertEqual(report["status"], "candidate_preview")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["current_sha256"], candidate.digest(self.original))
        self.assertRegex(report["candidate_sha256"], r"^[a-f0-9]{64}$")
        self.assertFalse(report["configuration_changed"])
        self.assertFalse(report["activation_available"])
        self.assertEqual(before, self._snapshot())
        public = json.dumps(report)
        for private in ("a" * 64, "private credential", str(self.project), str(self.home)):
            self.assertNotIn(private, public)

    def test_inventory_needs_no_router_identity_and_reports_all_current_blockers(self):
        (self.router / "token").unlink()
        (self.home / "operator-native-route-only").write_bytes(b"native recovery")
        startup = self.project / ".codex/operator-web-startup"
        startup.mkdir()
        (startup / "activation.json").write_bytes(b'{"phase":"may_have_activated"}')
        self._recovery_fixture(stale_source=True)
        before = self._snapshot()
        report = entry_preview.inventory(self.project, self.home)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["blockers"], [
            "unified_native_route_lock_active",
            "unified_old_activation_record_requires_review",
            "unified_recovery_source_mismatch",
        ])
        self.assertIsNone(report["candidate_sha256"])
        self.assertEqual(before, self._snapshot())

    def test_blocked_preview_still_hashes_candidate_without_activation(self):
        (self.home / "operator-native-route-only").write_bytes(b"native recovery")
        startup = self.project / ".codex/operator-web-startup"
        startup.mkdir()
        (startup / "activation.json").write_bytes(b'{"phase":"cancelled"}')
        report = entry_preview.preview(self.project, self.home, self.router, 4318)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["blockers"], ["unified_native_route_lock_active",
                                               "unified_old_activation_record_requires_review"])
        self.assertRegex(report["candidate_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_existing_route_conflict_has_fixed_code_and_no_candidate_digest(self):
        self.config.write_bytes(b'openai_base_url = "https://example.invalid/private"\n')
        report = entry_preview.preview(self.project, self.home, self.router, 4318)
        self.assertEqual(report["blockers"], ["unified_existing_route_conflict"])
        self.assertIsNone(report["candidate_sha256"])
        self.assertNotIn("example.invalid", json.dumps(report))

    def test_recovery_shortcut_absence_is_unverified_without_source_assumptions(self):
        (self.project / ".codex/operator-native-recovery/ownership.json").unlink()
        report = entry_preview.inventory(self.project, self.home)
        self.assertEqual(report["blockers"], ["unified_recovery_shortcut_unverified"])

    def test_receipt_cannot_substitute_a_link_outside_the_checked_desktop(self):
        other = self.root / "other"
        other.mkdir()
        fake = other / "恢复官方默认路由.lnk"
        fake.write_bytes(self.link.read_bytes())
        receipt_path = self.project / ".codex/operator-native-recovery/ownership.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["shortcut"] = str(fake)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        report = entry_preview.inventory(self.project, self.home)
        self.assertEqual(report["blockers"], ["unified_recovery_shortcut_unverified"])

    def test_shortcut_inspector_failure_blocks_even_when_hash_matches(self):
        with patch.object(entry_preview, "_verify_shortcut", return_value=False):
            report = entry_preview.inventory(self.project, self.home)
        self.assertEqual(report["blockers"], ["unified_recovery_shortcut_unverified"])

    def test_cli_inventory_is_read_only_and_does_not_need_router(self):
        before = self._snapshot()
        script = _OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_entry_preview.py"
        result = subprocess.run([sys.executable, "-B", str(script), "inventory",
            "--project-root", str(self.project), "--codex-home", str(self.home)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        self.assertEqual(json.loads(result.stdout)["blockers"],
                         ["unified_recovery_shortcut_unverified"])
        self.assertEqual(before, self._snapshot())

    def test_cli_preview_reports_blockers_without_paths_or_secrets(self):
        (self.home / "operator-native-route-only").write_bytes(b"native recovery")
        before = self._snapshot()
        script = _OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_entry_preview.py"
        result = subprocess.run([sys.executable, "-B", str(script), "preview",
            "--project-root", str(self.project), "--codex-home", str(self.home),
            "--router-state", str(self.router), "--port", "4318"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["blockers"],
                         ["unified_native_route_lock_active", "unified_recovery_shortcut_unverified"])
        for private in ("a" * 64, "private credential", str(self.project), str(self.home)):
            self.assertNotIn(private, result.stdout)
        self.assertEqual(before, self._snapshot())

    def test_invalid_router_token_has_fixed_public_failure(self):
        (self.router / "token").write_bytes(b"private unexpected token")
        script = _OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_entry_preview.py"
        result = subprocess.run([sys.executable, "-B", str(script), "preview",
            "--project-root", str(self.project), "--codex-home", str(self.home),
            "--router-state", str(self.router), "--port", "4318"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["reason"], "unified_preview_router_identity_unavailable")
        self.assertNotIn("private unexpected token", result.stdout)


if __name__ == "__main__":
    unittest.main()
