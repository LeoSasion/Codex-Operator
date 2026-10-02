"""Windows-only disposable evidence for the reviewed marker release."""
from pathlib import Path as _TestPath
import sys as _test_sys
_ROOT = next(parent for parent in _TestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_test_sys.path.insert(0, str(_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_ROOT)

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import operator_model_router as router
import operator_unified_cold_start as cold
import operator_unified_entry_preview as entry_preview
import operator_unified_marker_release as marker_release
import operator_unified_prepare as preparation
from operator_core import windows_config_transaction as transaction


@unittest.skipUnless(os.name == "nt", "Windows file identity required")
class UnifiedMarkerReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="operator-marker-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        (self.project / ".codex").mkdir(parents=True)
        self.home = self.root / "codex-home"
        self.home.mkdir()
        self.config = self.home / "config.toml"
        self.config.write_bytes(b'model = "gpt-6-sol"\nuser_setting = "keep"\n')
        self.cache = self.home / "models_cache.json"
        self.cache.write_bytes(b'{"old":"catalog"}\n')
        self.marker = self.home / marker_release.MARKER
        self.marker.write_bytes(marker_release.MARKER_BYTES)
        self.original_marker = transaction._snapshot(self.marker)
        self.profile = self.project / ".codex/operator-web-service"
        self.profile.mkdir()
        self.router_state = self.project / ".codex/existing-router"
        self.router_state.mkdir()
        (self.router_state / "token").write_text("a" * 64, encoding="ascii")
        (self.router_state / "registry.json").write_text(json.dumps({"version": 2,
            "models": [{"slug": "api/test"}, {"slug": "local/test"}]}), encoding="utf-8")
        self._recovery()
        self._entry()
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "OPENAI_BASE_URL": ""})
        env.start()
        self.addCleanup(env.stop)
        patches = [
            patch.object(entry_preview, "_verify_shortcut", return_value=True),
            patch.object(entry_preview, "verify_owned_entry", return_value="d" * 64),
            patch.object(preparation.web_startup, "assert_desktop_closed"),
            patch.object(preparation.web_service, "route_preview", return_value={
                "profile_sha256": "b" * 64, "session_sha256": "c" * 64}),
            patch.object(preparation.web_service, "process_identity",
                side_effect=lambda pid: {"pid": pid, "birth": "123456789",
                                         "executable": str(Path(sys.executable).resolve())}),
            patch.object(router, "control", side_effect=self._router_control),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        cold.create_workflow(self.project, self.home, Path(sys.executable))
        self._select_entry()
        reviewed = preparation.preview(self.project, self.home, self.router_state,
                                       self.profile, 4318)
        self.assertEqual(reviewed["blockers"], ["unified_native_route_lock_active"])
        preparation.prepare(self.project, self.home, self.router_state,
                            self.profile, 4318, reviewed["review_sha256"])
        self.plan = self.home / preparation.STATE / "plan.json"

    def _router_control(self, state, port):
        self.assertEqual((Path(state), port), (self.router_state, 4318))
        raw = (self.router_state / "registry.json").read_bytes()
        return {"status": "ready", "service": router.service_identity(self.router_state),
                "pid": 4321, "diagnostics": {
                    "registry_sha256": preparation._hash(raw),
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
            raw = (_ROOT / "scripts" / name).read_bytes()
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
        script = (_ROOT / "scripts/operator_desktop_entry.ps1").read_bytes()
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

    def _release(self):
        review = marker_release.preview(self.plan)
        self.assertEqual(review["status"], "reviewed_preview")
        return marker_release.release(self.plan, review["review_sha256"])

    def test_exact_release_retains_original_identity_and_receipt(self):
        before_config = self.config.read_bytes()
        before_cache = self.cache.read_bytes()
        result = self._release()
        self.assertEqual(result["status"], "released_witnessed")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertEqual(self.cache.read_bytes(), before_cache)
        directory = self.home / preparation.STATE / marker_release.STATE
        intent = json.loads((directory / "intent.json").read_bytes())
        retired = transaction._snapshot(directory / intent["backup"])
        self.assertEqual(retired.data, self.original_marker.data)
        self.assertEqual(retired.identity, self.original_marker.identity)
        self.assertEqual(marker_release.verify_release(self.plan, require_released=True),
                         result["receipt_sha256"])
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_attempt_requires_review"):
            marker_release.release(self.plan, "0" * 64)

    def test_marker_release_requires_effective_launcher_home(self):
        other_home = self.root / "other-home"
        other_home.mkdir()
        with patch.dict(os.environ, {"CODEX_HOME": str(other_home)}):
            with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                        "unified_marker_plan_unavailable"):
                marker_release.preview(self.plan)
        self.assertEqual(self.marker.read_bytes(), marker_release.MARKER_BYTES)

    def test_manual_marker_deletion_has_no_receipt(self):
        self.marker.unlink()
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_release_unverified"):
            marker_release.verify_release(self.plan, require_released=True)

    def test_changed_marker_or_entry_blocks_without_transaction(self):
        self.marker.write_bytes(b"changed marker\n")
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_preflight_blocked"):
            marker_release.preview(self.plan)
        self.assertFalse((self.home / preparation.STATE / marker_release.STATE).exists())
        self.marker.write_bytes(marker_release.MARKER_BYTES)
        entry = self.entry / "desktop-entry.json"
        raw = entry.read_bytes()
        entry.write_bytes(raw.replace(b'reviewed_startup', b'native'))
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_entry_unverified"):
            marker_release.preview(self.plan)
        self.assertFalse((self.home / preparation.STATE / marker_release.STATE).exists())

    def test_open_desktop_or_busy_router_blocks_without_transaction(self):
        with patch.object(preparation.web_startup, "assert_desktop_closed",
                          side_effect=ValueError("desktop open")):
            with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                        "unified_marker_preflight_blocked"):
                marker_release.preview(self.plan)
        original = self._router_control
        def busy(state, port):
            value = original(state, port)
            value["diagnostics"]["timing"]["active"] = 1
            return value
        with patch.object(router, "control", side_effect=busy):
            with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                        "unified_marker_router_not_idle_or_changed"):
                marker_release.preview(self.plan)
        self.assertFalse((self.home / preparation.STATE / marker_release.STATE).exists())

    def test_failure_after_rename_is_terminal_with_original_retained(self):
        review = marker_release.preview(self.plan)
        actual_replace = marker_release.os.replace
        def after_rename(source, target):
            actual_replace(source, target)
            raise OSError("injected exit after marker rename")
        with patch.object(marker_release.os, "replace", side_effect=after_rename):
            with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                        "unified_marker_attempt_requires_review"):
                marker_release.release(self.plan, review["review_sha256"])
        directory = self.home / preparation.STATE / marker_release.STATE
        intent = json.loads((directory / "intent.json").read_bytes())
        self.assertEqual((directory / "before.bin").read_bytes(), marker_release.MARKER_BYTES)
        self.assertEqual((directory / intent["backup"]).read_bytes(), marker_release.MARKER_BYTES)
        self.assertFalse((directory / "receipt.json").exists())
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_release_unverified"):
            marker_release.verify_release(self.plan, require_released=True)
        with self.assertRaises(marker_release.MarkerReleaseError):
            marker_release.release(self.plan, review["review_sha256"])

    def test_backup_tamper_and_recreated_marker_fail_closed(self):
        self._release()
        directory = self.home / preparation.STATE / marker_release.STATE
        intent = json.loads((directory / "intent.json").read_bytes())
        backup = directory / intent["backup"]
        backup.write_bytes(b"tampered")
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_release_unverified"):
            marker_release.verify_release(self.plan, require_released=True)
        backup.write_bytes(marker_release.MARKER_BYTES)
        self.marker.write_bytes(marker_release.MARKER_BYTES)
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_release_unverified"):
            marker_release.verify_release(self.plan, require_released=True)

    def test_entry_change_after_release_invalidates_receipt(self):
        self._release()
        entry_file = self.entry / "desktop-entry.json"
        value = json.loads(entry_file.read_bytes())
        entry_file.write_text(json.dumps({**value, "mode": "native"}), encoding="utf-8")
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_release_unverified"):
            marker_release.verify_release(self.plan, require_released=True)

    def test_changed_marker_identity_after_preview_blocks_release(self):
        reviewed = marker_release.preview(self.plan)
        replacement = self.home / "different-marker"
        replacement.write_bytes(marker_release.MARKER_BYTES)
        os.replace(replacement, self.marker)
        with self.assertRaisesRegex(marker_release.MarkerReleaseError,
                                    "unified_marker_review_changed"):
            marker_release.release(self.plan, reviewed["review_sha256"])
        self.assertFalse((self.home / preparation.STATE / marker_release.STATE).exists())


if __name__ == "__main__":
    unittest.main()
