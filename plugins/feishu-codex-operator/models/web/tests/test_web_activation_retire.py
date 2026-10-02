"""Legacy activation retirement; all writes stay inside disposable projects."""

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
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = _OPERATOR_PLUGIN_ROOT
sys.path.insert(0, str(ROOT / "scripts"))
import operator_web_activation_retire as retirement
import operator_web_startup as startup
import operator_unified_entry_preview as unified_preview
import operator_uninstall as uninstall


class LegacyActivationRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-web-activation-retire-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / ".codex").mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "config.toml").write_bytes(b'model = "native"\n')
        (self.home / "operator-native-route-only").write_bytes(b"native recovery lock\n")
        self.profile = self.root / ".codex/operator-web-service"
        self.profile.mkdir()
        (self.profile / "profile.json").write_text("{}", encoding="utf-8")
        mocked_profile = patch.object(startup.manager, "load_profile", return_value=(self.profile, {}))
        mocked_profile.start()
        self.addCleanup(mocked_profile.stop)
        mocked_process = patch.object(retirement.manager, "process_identity", return_value=None)
        mocked_process.start()
        self.addCleanup(mocked_process.stop)
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            self.port = candidate.getsockname()[1]
        startup.prepare(self.root, self.profile, self.home, self.port)
        self.bundle = self.root / ".codex/operator-web-startup"
        self.plan_path = self.bundle / "web-startup.json"
        self.plan = json.loads(self.plan_path.read_bytes())
        self.saved_original = b'model = "native"\n'
        (self.bundle / "config-before-activation.toml").write_bytes(self.saved_original)
        self.activation = {"version": 1, "phase": "activated",
            "plan_sha256": retirement.digest(self.plan_path.read_bytes()),
            "config_sha256": retirement.digest(self.saved_original)}
        self.write(self.bundle / "activation.json", self.activation)
        runtime = self.plan["runtime"]
        self.launch = {"version": 1, "phase": "stopped", "attempt": "a" * 32,
            "runtime": runtime, "pid": 210001,
            "process": {"pid": 210001, "birth": "111", "executable": runtime["python"]},
            "worker": {"pid": 210002, "birth": "222", "executable": runtime["worker_python"]},
            "service_pid": 210002}
        self.write(self.bundle / "router-launch.json", self.launch)
        self.desktop = self.root / ".codex/operator-desktop-entry"
        self.desktop.mkdir()
        script = (ROOT / "scripts/operator_desktop_entry.ps1").read_bytes()
        launcher = b"disposable launcher fixture"
        (self.desktop / "operator_desktop_entry.ps1").write_bytes(script)
        (self.desktop / "Codex拓展入口.exe").write_bytes(launcher)
        self.write(self.desktop / "launcher-manifest.json", {"schema_version": 1,
            "native_fallback": "native-only-v1", "entry_script_sha256": retirement.digest(script),
            "binary_sha256": retirement.digest(launcher)})
        self.entry = {"schema_version": 1, "mode": "native",
            "startup_bundle": ".codex/operator-web-startup",
            "entry_script_sha256": retirement.digest(script)}
        self.write(self.desktop / "desktop-entry.json", self.entry)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")

    def preview(self):
        return retirement.preview(self.plan_path)

    def retire(self, preview):
        return retirement.retire(self.plan_path, preview["plan_sha256"],
            preview["activation_sha256"], preview["snapshot_sha256"])

    def assert_no_retirement_writes(self):
        self.assertFalse((self.bundle / retirement.JOURNAL).exists())
        self.assertFalse((self.bundle / retirement.BACKUP).exists())
        self.assertFalse((self.bundle / retirement.ARCHIVE).exists())
        self.assertEqual(json.loads((self.bundle / "activation.json").read_bytes()), self.activation)

    def test_legacy_runtime_mismatch_can_be_previewed_and_retired_once(self):
        # The old status API rejects current source drift. This maintenance API
        # compares the old plan with its old launch receipt without rearming it.
        self.plan["runtime"]["startup_sources"]["operator_web_startup.py"] = "0" * 64
        self.write(self.plan_path, self.plan)
        self.activation["plan_sha256"] = retirement.digest(self.plan_path.read_bytes())
        self.write(self.bundle / "activation.json", self.activation)
        self.launch["runtime"] = self.plan["runtime"]
        self.write(self.bundle / "router-launch.json", self.launch)
        with self.assertRaisesRegex(ValueError, "web_startup_runtime_changed"):
            startup.load(self.plan_path)
        before = {p: p.read_bytes() for p in (self.plan_path, self.bundle / "router-launch.json",
            self.home / "config.toml", self.desktop / "desktop-entry.json")}
        preview = self.preview()
        self.assertEqual(preview["status"], "ready_to_retire")
        self.assert_no_retirement_writes()
        original = (self.bundle / "activation.json").read_bytes()
        self.assertIn("unified_old_activation_record_requires_review",
            unified_preview.inventory(self.root, self.home)["blockers"])
        self.assertEqual(self.retire(preview)["status"], "retired")
        self.assertEqual((self.bundle / retirement.BACKUP).read_bytes(), original)
        self.assertEqual((self.bundle / retirement.ARCHIVE).read_bytes(), original)
        self.assertFalse((self.bundle / "activation.json").exists())
        self.assertEqual(json.loads((self.bundle / retirement.JOURNAL).read_bytes())["phase"], "retired")
        self.assertEqual(retirement.retirement_status(self.plan_path), "retired")
        self.assertNotIn("unified_old_activation_record_requires_review",
            unified_preview.inventory(self.root, self.home)["blockers"])
        with patch.object(retirement.manager, "status",
                          return_value={"status": "configured", "start_available": True}):
            uninstall.inspect_web_startup(self.root, self.home / "config.toml")
        (self.home / "operator-native-route-only").unlink()
        self.assertEqual(retirement.retirement_status(self.plan_path), "retired")
        self.assertNotIn("unified_old_activation_record_requires_review",
            unified_preview.inventory(self.root, self.home)["blockers"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        with self.assertRaisesRegex(ValueError, "retire_transaction_already_recorded"):
            self.preview()

    def test_matching_process_birth_blocks_even_with_stopped_receipt(self):
        with patch.object(retirement.manager, "process_identity", side_effect=[
            self.launch["process"]]):
            with self.assertRaisesRegex(ValueError, "retire_router_process_live_or_unknown"):
                self.preview()
        self.assert_no_retirement_writes()
        with patch.object(retirement.manager, "process_identity", side_effect=[
            {**self.launch["process"], "birth": "333"}, None]):
            self.assertEqual(self.preview()["status"], "ready_to_retire")

    def test_entry_and_config_must_be_unambiguously_native(self):
        journal = self.bundle / "router/codex-entry.json"
        journal.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "retire_entry_active_or_unknown"):
            self.preview()
        journal.unlink()
        (self.home / "config.toml").write_bytes(b'openai_base_url = "http://127.0.0.1:4318/v1"\n')
        with self.assertRaisesRegex(ValueError, "retire_entry_active_or_unknown"):
            self.preview()
        (self.home / "config.toml").write_bytes(b'model = "native"\n')
        self.entry["mode"] = "reviewed_startup"
        self.write(self.desktop / "desktop-entry.json", self.entry)
        with self.assertRaisesRegex(ValueError, "retire_desktop_entry_changed"):
            self.preview()
        self.assert_no_retirement_writes()

    def test_busy_port_blocks_without_modifying_records(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.port))
            with self.assertRaisesRegex(ValueError, "retire_port_not_exclusive"):
                self.preview()
        self.assert_no_retirement_writes()

    def test_plan_original_and_launch_identity_are_required(self):
        self.activation["plan_sha256"] = "0" * 64
        self.write(self.bundle / "activation.json", self.activation)
        with self.assertRaisesRegex(ValueError, "retire_plan_digest_changed"):
            self.preview()
        self.activation["plan_sha256"] = retirement.digest(self.plan_path.read_bytes())
        self.write(self.bundle / "activation.json", self.activation)
        (self.bundle / "config-before-activation.toml").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "retire_original_config_changed"):
            self.preview()
        (self.bundle / "config-before-activation.toml").write_bytes(self.saved_original)
        self.launch["runtime"] = {}
        self.write(self.bundle / "router-launch.json", self.launch)
        with self.assertRaisesRegex(ValueError, "retire_router_record_invalid"):
            self.preview()
        self.assert_no_retirement_writes()

    def test_changed_preview_snapshot_never_creates_retirement_record(self):
        preview = self.preview()
        self.entry["unused"] = "new"
        self.write(self.desktop / "desktop-entry.json", self.entry)
        with self.assertRaisesRegex(ValueError, "retire_desktop_entry_changed"):
            self.retire(preview)
        self.assert_no_retirement_writes()

    def test_process_reappearing_after_backup_leaves_terminal_review_state(self):
        preview = self.preview()
        original = (self.bundle / "activation.json").read_bytes()
        with patch.object(retirement.manager, "process_identity", side_effect=[
            None, None, self.launch["process"]]):
            with self.assertRaisesRegex(ValueError, "retire_router_process_live_or_unknown"):
                self.retire(preview)
        self.assertEqual((self.bundle / retirement.BACKUP).read_bytes(), original)
        self.assertEqual((self.bundle / "activation.json").read_bytes(), original)
        self.assertFalse((self.bundle / retirement.ARCHIVE).exists())
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        with self.assertRaisesRegex(ValueError, "retire_transaction_already_recorded"):
            self.retire(preview)

    def test_failed_terminal_receipt_after_archive_blocks_preview_and_uninstall(self):
        preview = self.preview()
        original = (self.bundle / "activation.json").read_bytes()
        with patch.object(retirement.manager.service, "write_json",
                          side_effect=OSError("fixture terminal receipt failure")):
            with self.assertRaises(OSError):
                self.retire(preview)
        self.assertEqual((self.bundle / retirement.BACKUP).read_bytes(), original)
        self.assertEqual((self.bundle / retirement.ARCHIVE).read_bytes(), original)
        self.assertFalse((self.bundle / "activation.json").exists())
        self.assertEqual(json.loads((self.bundle / retirement.JOURNAL).read_bytes())["phase"],
            "may_have_retired")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        self.assertIn("unified_old_activation_record_requires_review",
            unified_preview.inventory(self.root, self.home)["blockers"])
        with patch.object(retirement.manager, "status",
                          return_value={"status": "configured", "start_available": True}):
            with self.assertRaisesRegex(ValueError, "review_web_activation_retirement_before_uninstall"):
                uninstall.inspect_web_startup(self.root, self.home / "config.toml")
        with self.assertRaisesRegex(ValueError, "retire_transaction_already_recorded"):
            self.retire(preview)

    def test_retired_status_rejects_tampered_archive_and_new_active_entry(self):
        preview = self.preview()
        self.retire(preview)
        (self.bundle / retirement.ARCHIVE).write_bytes(b"changed")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        self.assertIn("unified_old_activation_record_requires_review",
            unified_preview.inventory(self.root, self.home)["blockers"])
        (self.bundle / retirement.ARCHIVE).write_bytes((self.bundle / retirement.BACKUP).read_bytes())
        (self.bundle / "router/codex-entry.json").write_bytes(b"{}")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")

    def test_retired_status_accepts_only_owned_completed_unified_replacement(self):
        self.retire(self.preview())
        before = (self.desktop / "desktop-entry.json").read_bytes()
        workflow = self.root / ".codex/operator-unified-startup"
        workflow.mkdir()
        startup_script = b"# disposable reviewed workflow\n"
        (workflow / "start-codex-with-web.ps1").write_bytes(startup_script)
        self.write(workflow / "startup-sync-plan.json", {
            "schema_version": 2, "startup_script": "start-codex-with-web.ps1",
            "entry_files": {"start-codex-with-web.ps1": retirement.digest(startup_script)}})
        self.entry.update(mode="reviewed_startup",
                          startup_bundle=".codex/operator-unified-startup")
        self.write(self.desktop / "desktop-entry.json", self.entry)
        after = (self.desktop / "desktop-entry.json").read_bytes()
        migration = self.root / ".codex/operator-entry-migration"
        migration.mkdir()
        (migration / "journal.json").write_bytes(b'{"disposable":"migration"}')
        upgrade = self.root / ".codex/operator-entry-upgrade"
        upgrade.mkdir()
        (upgrade / "before.json").write_bytes(before)
        (upgrade / "after.json").write_bytes(after)
        plan = {"schema_version": 1, "scope": "entry_only_config_upgrade",
                "project": str(self.root), "runtime_ownership": "unresolved",
                "migration_sha256": retirement.digest((migration / "journal.json").read_bytes()),
                "before_sha256": retirement.digest(before),
                "codex_home": str(self.home), "startup_bundle": str(workflow),
                "startup_metadata_sha256": retirement.digest(
                    (workflow / "startup-sync-plan.json").read_bytes()),
                "startup_script_sha256": retirement.digest(startup_script),
                "entry_script_sha256": retirement.digest(
                    (self.desktop / "operator_desktop_entry.ps1").read_bytes()),
                "binary_sha256": retirement.digest(
                    (self.desktop / "Codex拓展入口.exe").read_bytes()),
                "after_sha256": retirement.digest(after)}
        self.write(upgrade / "intent.json", {"schema_version": 1,
            "phase": "may_have_updated", "plan": plan, "plan_sha256": "a" * 64})
        self.write(upgrade / "receipt.json", {"schema_version": 1, "phase": "applied",
            "plan_sha256": "a" * 64,
            "intent_sha256": retirement.digest((upgrade / "intent.json").read_bytes()),
            "before_sha256": retirement.digest(before),
            "after_sha256": retirement.digest(after)})

        with patch.object(unified_preview, "verify_owned_entry", return_value="b" * 64) as owned:
            self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
            self.assertEqual(retirement.retirement_status(self.plan_path,
                replacement_home=self.home), "retired")
            owned.assert_called_with(self.root, self.desktop)
            self.assertEqual(retirement.retirement_status(self.plan_path,
                replacement_home=self.root), "uncertain")
            for path in (workflow / "start-codex-with-web.ps1",
                         upgrade / "receipt.json", self.bundle / "router/registry.json"):
                with self.subTest(path=path):
                    original = path.read_bytes()
                    try:
                        changed = (original.replace(b'"applied"', b'"unknown"')
                            if path.name == "receipt.json" else original + b" ")
                        path.write_bytes(changed)
                        self.assertEqual(retirement.retirement_status(self.plan_path,
                            replacement_home=self.home), "uncertain")
                    finally:
                        path.write_bytes(original)
        with patch.object(unified_preview, "verify_owned_entry",
                          side_effect=unified_preview.PreviewError("unowned")):
            self.assertEqual(retirement.retirement_status(self.plan_path,
                replacement_home=self.home), "uncertain")


    def test_retired_status_rejects_changed_historical_files(self):
        preview = self.preview()
        self.retire(preview)
        paths = {
            "startup_workflow": self.bundle / "start-codex-with-web.ps1",
            "startup_sync": self.bundle / "startup-sync-plan.json",
            "registry": self.bundle / "router/registry.json",
            "token": self.bundle / "router/token",
        }
        for name, path in paths.items():
            with self.subTest(name=name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" ")
                    self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
                    self.assertIn("unified_old_activation_record_requires_review",
                        unified_preview.inventory(self.root, self.home)["blockers"])
                finally:
                    path.write_bytes(original)
                self.assertEqual(retirement.retirement_status(self.plan_path), "retired")

    def test_later_web_profile_update_does_not_reactivate_old_bundle(self):
        self.retire(self.preview())
        journal_path = self.bundle / retirement.JOURNAL
        journal_before = journal_path.read_bytes()
        original_profile = (self.profile / "profile.json").read_bytes()
        (self.profile / "profile.json").write_text(json.dumps({
            "version": 1, "settings": {"path": str(self.root / "new-settings.json")},
            "runtime": {"python": "new-explicit-interpreter"}}), encoding="utf-8")
        self.assertNotEqual((self.profile / "profile.json").read_bytes(), original_profile)
        self.assertEqual(json.loads(journal_before)["files_sha256"]["profile"],
                         retirement.digest(original_profile))
        self.assertEqual(retirement.retirement_status(self.plan_path), "retired")
        self.assertNotIn("unified_old_activation_record_requires_review",
                         unified_preview.inventory(self.root, self.home)["blockers"])
        self.assertEqual(journal_path.read_bytes(), journal_before)

        # The mutable profile exception cannot hide a changed old router bundle.
        registry = self.bundle / "router/registry.json"
        original_registry = registry.read_bytes()
        registry.write_bytes(original_registry + b" ")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        self.assertIn("unified_old_activation_record_requires_review",
                      unified_preview.inventory(self.root, self.home)["blockers"])
        registry.write_bytes(original_registry)
        self.assertEqual(retirement.retirement_status(self.plan_path), "retired")

        archive = self.bundle / retirement.ARCHIVE
        archived_activation = archive.read_bytes()
        archive.write_bytes(b"changed")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        archive.write_bytes(archived_activation)
        (self.bundle / "activation.json").write_bytes(archived_activation)
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        (self.bundle / "activation.json").unlink()
        entry = self.bundle / "router/codex-entry.json"
        entry.write_bytes(b"{}")
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        entry.unlink()
        self.assertEqual(retirement.retirement_status(self.plan_path), "retired")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
class LegacyPairRetirementStatusTests(unittest.TestCase):
    """Real COM migration, adoption, config upgrade and pair in temporary folders."""

    def setUp(self):
        from test_desktop_pair_legacy import LegacyPairTests
        self.fixture = LegacyPairTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        full = self.fixture
        self.root, self.home, self.desktop = full.root, full.home, full.bundle
        self.write = LegacyActivationRetirementTests.write
        profile = self.root / ".codex/operator-web-service"
        profile.mkdir()
        (profile / "profile.json").write_bytes(b"{}")
        (self.home / "operator-native-route-only").write_bytes(b"operator-native-route-only-v1\n")
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            self.port = candidate.getsockname()[1]
        with patch.object(startup.manager, "load_profile", return_value=(profile, {})):
            startup.prepare(self.root, profile, self.home, self.port)
        self.bundle = self.root / ".codex/operator-web-startup"
        self.plan_path = self.bundle / "web-startup.json"
        plan = json.loads(self.plan_path.read_bytes())
        original_config = (self.home / "config.toml").read_bytes()
        (self.bundle / "config-before-activation.toml").write_bytes(original_config)
        self.write(self.bundle / "activation.json", {"version": 1, "phase": "activated",
            "plan_sha256": retirement.digest(self.plan_path.read_bytes()),
            "config_sha256": retirement.digest(original_config)})
        runtime = plan["runtime"]
        self.launch = {"version": 1, "phase": "stopped", "attempt": "b" * 32,
            "runtime": runtime, "pid": 210001,
            "process": {"pid": 210001, "birth": "111", "executable": runtime["python"]},
            "worker": {"pid": 210002, "birth": "222", "executable": runtime["worker_python"]},
            "service_pid": 210002}
        self.write(self.bundle / "router-launch.json", self.launch)
        mocked_process = patch.object(retirement.manager, "process_identity", return_value=None)
        mocked_process.start()
        self.addCleanup(mocked_process.stop)
        # Create a real completed retirement while this disposable entry is
        # native, then retain its historical records through the later upgrades.
        entry_path = self.desktop / "desktop-entry.json"
        migrated_entry = entry_path.read_bytes()
        manifest_path = self.desktop / "launcher-manifest.json"
        migrated_manifest = manifest_path.read_bytes()
        manifest = json.loads(migrated_manifest)
        self.write(manifest_path, {key: manifest[key] for key in
            ("schema_version", "native_fallback", "entry_script_sha256", "binary_sha256")})
        native = json.loads(migrated_entry)
        native.update(mode="native", startup_bundle=".codex/operator-web-startup")
        self.write(entry_path, native)
        preview = retirement.preview(self.plan_path)
        retirement.retire(self.plan_path, preview["plan_sha256"],
            preview["activation_sha256"], preview["snapshot_sha256"])
        entry_path.write_bytes(migrated_entry)
        manifest_path.write_bytes(migrated_manifest)
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
        self.pair_path = full.pair_root / "ownership.json"
        self.pair = json.loads(self.pair_path.read_bytes())
        self.links = (full.desktop / "ChatGPT 原生入口.lnk",
            full.desktop / ("ChatGPT 拓展模型 " + self.pair["build_date"][5:] + " 入口.lnk"))
        verify = unified_preview.verify_owned_entry

        def real_owned(project, desktop):
            return verify(project, desktop, test_shortcuts=self.links)

        # Override only the current-user known folders. The production verifier
        # still reads real COM links, file identities, backups and transactions.
        owned = patch.object(unified_preview, "verify_owned_entry", side_effect=real_owned)
        self.owned = owned.start()
        self.addCleanup(owned.stop)

    def snapshot(self):
        return {str(path.relative_to(self.root)): retirement.digest(path.read_bytes())
            for path in self.root.rglob("*") if path.is_file()}

    def status(self):
        return retirement.retirement_status(self.plan_path, replacement_home=self.home)

    def assert_read_only_status(self, expected):
        before = self.snapshot()
        self.assertEqual(self.status(), expected)
        self.assertEqual(self.snapshot(), before)

    def test_completed_real_pair_recognizes_retained_retirement_without_writes(self):
        upgrade = self.root / ".codex/operator-entry-upgrade"
        intent = json.loads((upgrade / "intent.json").read_bytes())
        first = self.pair["steps"][0]["before"]
        self.assertEqual(first["desktop-entry.json"], intent["plan"]["after_sha256"])
        self.assertEqual(first["operator_desktop_entry.ps1"], intent["plan"]["entry_script_sha256"])
        self.assertEqual(first["Codex拓展入口.exe"], intent["plan"]["binary_sha256"])
        self.assertNotEqual(first["launcher-manifest.json"], self.pair["build"]["launcher-manifest.json"])
        self.assert_read_only_status("retired")
        self.assertEqual(self.owned.call_count, 2)
        self.assertEqual(retirement.retirement_status(self.plan_path), "uncertain")
        self.assertEqual(retirement.retirement_status(self.plan_path,
            replacement_home=self.root), "uncertain")

    def test_real_pair_chain_rejects_changed_evidence_and_current_files(self):
        pair_root = self.fixture.pair_root
        origin = json.loads((pair_root / "legacy-origin.json").read_bytes())
        retained = pair_root / "originals" / (origin["evidence"][0]["sha256"] + ".bin")
        paths = [self.pair_path, pair_root / "legacy-origin.json", retained,
            self.root / ".codex/operator-entry-migration/journal.json",
            self.root / ".codex/operator-entry-upgrade/intent.json",
            self.root / ".codex/operator-entry-upgrade/receipt.json",
            self.root / ".codex/operator-entry-upgrade/before.json",
            self.root / ".codex/operator-entry-upgrade/after.json",
            self.root / ".codex/operator-entry-shortcut-adoption/receipt.json",
            self.root / ".codex/operator-unified-startup/start-codex-with-web.ps1",
            self.root / ".codex/operator-unified-startup/startup-sync-plan.json",
            self.desktop / "desktop-entry.json", self.desktop / "launcher-manifest.json",
            self.desktop / "operator_desktop_entry.ps1", self.desktop / "Codex拓展入口.exe",
            self.desktop / "Codex拓展入口.ico", self.links[0], self.links[1], self.fixture.start]
        for path in paths:
            with self.subTest(path=path.relative_to(self.root)):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" ")
                    self.assert_read_only_status("uncertain")
                finally:
                    path.write_bytes(original)
        self.assert_read_only_status("retired")

    def test_pair_checks_historical_upgrade_after_witnessed_workflow_renewal(self):
        import operator_unified_workflow_renew as renewal
        workflow = self.root / '.codex/operator-unified-startup'
        retained = self.root / 'retained-workflow'
        shutil.copytree(workflow, retained)
        (workflow / 'start-codex-with-web.ps1').write_bytes(b'# new source-bound workflow\n')
        self.write(workflow / 'startup-sync-plan.json', {'schema_version': 2,
            'startup_script': 'start-codex-with-web.ps1', 'entry_files': {
                'start-codex-with-web.ps1': retirement.digest(
                    (workflow / 'start-codex-with-web.ps1').read_bytes())}})
        # Only the renewal locator is substituted here; its complete file-ID
        # proof is exercised by real Windows renewal tests. COM ownership,
        # historical upgrade, retirement and pair-chain checks remain real.
        with patch.object(renewal, 'retained_workflow', return_value=retained):
            self.assert_read_only_status('retired')
            old = retained / 'start-codex-with-web.ps1'
            old.write_bytes(b'changed-historical')
            self.assert_read_only_status('uncertain')
        with patch.object(renewal, 'retained_workflow', side_effect=ValueError('unverified')):
            self.assert_read_only_status('uncertain')

    def test_real_pair_preserves_old_retirement_process_and_port_gates(self):
        for name in (retirement.JOURNAL, retirement.BACKUP, retirement.ARCHIVE,
                     "router/registry.json", "router/token", "router-launch.json"):
            path = self.bundle / name
            original = path.read_bytes()
            with self.subTest(name=name):
                try:
                    path.write_bytes(original + b" ")
                    # The journal's serialized whitespace is not an identity;
                    # changing its phase is a substantive terminal-state change.
                    if name == retirement.JOURNAL:
                        value = json.loads(original)
                        value["phase"] = "may_have_retired"
                        self.write(path, value)
                    self.assert_read_only_status("uncertain")
                finally:
                    path.write_bytes(original)
        with patch.object(retirement.manager, "process_identity", return_value=self.launch["process"]):
            self.assert_read_only_status("uncertain")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.port))
            self.assert_read_only_status("uncertain")
        active = self.bundle / "router/codex-entry.json"
        active.write_bytes(b"{}")
        try:
            self.assert_read_only_status("uncertain")
        finally:
            active.unlink()
        self.assert_read_only_status("retired")


if __name__ == "__main__":
    unittest.main()
