"""The Desktop-exit handoff is one-shot and keeps failed stages visible."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import operator_unified_handoff as handoff
import operator_unified_supersede as supersede
import operator_unified_prepare as preparation
import operator_unified_marker_release as marker
import operator_unified_cold_start as cold
import operator_web_startup as web_startup
import operator_model_router as router
import operator_web_service as web_service
from operator_core.model_registry import RouterError


class HandoffTests(unittest.TestCase):
    def prepared_fixture(self):
        import test_unified_cold_start as cold_tests

        fixture = cold_tests.UnifiedColdStartTests("test_planned_marker_release_allows_one_cold_launch")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        official = fixture.project / "ChatGPT.exe"
        official.write_bytes(b"disposable official executable")
        return fixture, official

    def change_activation_entry(self, fixture, failure):
        if failure == "workflow":
            script = fixture.project / ".codex" / cold.BUNDLE / cold.SCRIPT
            script.write_bytes(script.read_bytes() + b"# stale saved wrapper\n")
            return "unified_workflow_changed"
        config = fixture.entry / "desktop-entry.json"
        value = json.loads(config.read_bytes())
        value["mode"] = "native"
        config.write_text(json.dumps(value), encoding="utf8")
        return "unified_entry_not_selected_or_changed"

    @unittest.skipUnless(sys.platform == "win32", "Windows prepared-plan file identity")
    def test_complete_prepared_rejects_stale_workflow_or_wrong_entry_before_manifest(self):
        for failure in ("workflow", "entry"):
            with self.subTest(failure=failure):
                fixture, official = self.prepared_fixture()
                reason = self.change_activation_entry(fixture, failure)
                original_marker = (fixture.home / "operator-native-route-only").read_bytes()
                with mock.patch.object(handoff, "_fixed_paths", return_value=(fixture.project, SCRIPTS)), \
                        mock.patch.object(marker, "release") as release, \
                        mock.patch.object(cold, "arm") as arm:
                    with self.assertRaisesRegex(handoff.HandoffError, reason):
                        handoff.prepare(fixture.project, fixture.home, Path(sys.executable), official,
                                        complete_prepared=True)
                self.assertFalse((fixture.project / ".codex/operator-unified-handoff").exists())
                self.assertEqual((fixture.home / "operator-native-route-only").read_bytes(), original_marker)
                release.assert_not_called()
                arm.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows prepared-plan file identity")
    def test_every_execute_branch_rereads_entry_checks_after_preview_before_marker_release(self):
        import operator_unified_upgrade as upgrade

        for action in ("complete_prepared", "supersede", "upgrade_witnessed"):
            for failure in ("workflow", "entry"):
                with self.subTest(action=action, failure=failure):
                    fixture, official = self.prepared_fixture()
                    with mock.patch.object(handoff, "_fixed_paths", return_value=(fixture.project, SCRIPTS)):
                        prepared = handoff.prepare(fixture.project, fixture.home, Path(sys.executable),
                                                   official, complete_prepared=True)
                    manifest_path = Path(prepared["manifest"])
                    original_manifest = manifest_path.read_bytes()
                    manifest = json.loads(original_manifest)
                    manifest["plan_action"] = action
                    observed = {"previewed": False, "reread_after_preview": False}
                    original_plan = cold._plan
                    expected_reason = ("unified_workflow_changed" if failure == "workflow"
                                       else "unified_entry_not_selected_or_changed")

                    def preview(path):
                        self.assertEqual(path, fixture.plan)
                        self.change_activation_entry(fixture, failure)
                        observed["previewed"] = True
                        return {"status": "reviewed_preview", "review_sha256": "m"}

                    def read_plan(path):
                        if observed["previewed"]:
                            observed["reread_after_preview"] = True
                        return original_plan(path)

                    with mock.patch.object(cold, "_plan", side_effect=read_plan), \
                            mock.patch.object(supersede, "preview", return_value={
                                "status": "reviewed_preview", "review_sha256": "s"}), \
                            mock.patch.object(supersede, "supersede", return_value={"status": "superseded_witnessed"}), \
                            mock.patch.object(preparation, "preview", return_value={
                                "status": "reviewed_preview", "review_sha256": "p", "prepare_available": True,
                                "blockers": ["unified_native_route_lock_active"]}), \
                            mock.patch.object(preparation, "prepare", return_value={"status": "prepared_not_armed"}), \
                            mock.patch.object(upgrade, "execute"), \
                            mock.patch.object(marker, "preview", side_effect=preview), \
                            mock.patch.object(marker, "release") as release, \
                            mock.patch.object(cold, "arm") as arm:
                        with self.assertRaisesRegex(handoff.HandoffError, expected_reason):
                            handoff.execute(manifest, lambda _: None, manifest_path.parent)
                    self.assertTrue(observed["reread_after_preview"])
                    self.assertEqual((fixture.home / "operator-native-route-only").read_bytes(), handoff.MARKER)
                    self.assertEqual(manifest_path.read_bytes(), original_manifest)
                    self.assertFalse((fixture.plan.parent / "marker-release").exists())
                    release.assert_not_called()
                    arm.assert_not_called()

    def test_activation_entry_fixed_failure_survives_public_prepare_redaction(self):
        import contextlib
        import io

        output = io.StringIO()
        with mock.patch.object(cold, "_verify_workflow", side_effect=cold.ColdStartError("unified_workflow_changed")), \
                mock.patch.object(cold, "_selected_entry") as selected:
            with self.assertRaisesRegex(handoff.HandoffError, "unified_workflow_changed") as stopped:
                handoff._verify_activation_entry({}, Path(sys.executable))
        selected.assert_not_called()
        with mock.patch.object(sys, "argv", ["handoff", "prepare-current", "--project-root", "project",
                "--codex-home", "home", "--python", sys.executable, "--official-exe", "ChatGPT.exe"]), \
                mock.patch.object(handoff, "prepare", side_effect=stopped.exception), contextlib.redirect_stdout(output):
            self.assertEqual(handoff.main(), 1)
        self.assertEqual(json.loads(output.getvalue())["reason"], "unified_workflow_changed")

    def test_script_entry_uses_canonical_error_class_and_runner(self):
        import runpy
        with mock.patch.object(handoff, "main", return_value=0) as main:
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(Path(handoff.__file__)), run_name="__main__")
            self.assertEqual(stopped.exception.code, 0)
            main.assert_called_once_with()

    def test_package_launch_uses_exact_codex_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "OpenAI.Codex_26.924.2738.0_x64__2p2nqsd0c76g0"
            official = package / "app/ChatGPT.exe"
            official.parent.mkdir(parents=True)
            official.write_bytes(b"app")
            (package / "AppxManifest.xml").write_text(
                '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
                '<Identity Name="OpenAI.Codex"/><Applications>'
                '<Application Id="App" Executable="app/ChatGPT.exe" '
                'EntryPoint="Windows.FullTrustApplication"/></Applications></Package>',
                encoding="utf8")
            self.assertEqual(handoff._package_launch_target(official),
                             ("OpenAI.Codex_2p2nqsd0c76g0!App", package.name))
            other = root / "Other_26.924.2738.0_x64__2p2nqsd0c76g0" / "app/ChatGPT.exe"
            with self.assertRaisesRegex(handoff.HandoffError,
                                        "handoff_package_identity_changed"):
                handoff._package_launch_target(other)

    @unittest.skipUnless(sys.platform == "win32", "Windows package activation")
    def test_activation_brokers_through_explorer_and_witnesses_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explorer = root / "explorer.exe"
            explorer.write_bytes(b"shell")
            official = root / "ChatGPT.exe"
            identity = {"pid": 123, "birth": "456", "executable": str(official)}
            child = mock.Mock()
            # Explorer may delegate successfully and return a nonzero status;
            # its lifetime is not the lifetime of the packaged application.
            child.wait.return_value = 1
            with mock.patch.dict(os.environ, {"SystemRoot": str(root)}), \
                    mock.patch.object(handoff, "_package_launch_target", return_value=(
                        "OpenAI.Codex_test!App", "OpenAI.Codex_test")), \
                    mock.patch.object(web_startup, "assert_desktop_closed"), \
                    mock.patch.object(handoff.subprocess, "Popen", return_value=child) as launch, \
                    mock.patch.object(web_service, "windows_process_entries", return_value=[
                        {"pid": 123, "name": "ChatGPT.exe"}]), \
                    mock.patch.object(web_service, "process_identity", return_value=identity), \
                    mock.patch.object(handoff, "_process_package_full_name",
                                      return_value="OpenAI.Codex_test"), \
                    mock.patch.object(handoff.time, "sleep"):
                handoff.activate_official(official)
            self.assertEqual(launch.call_args.args[0], [str(explorer),
                "shell:AppsFolder\\OpenAI.Codex_test!App"])
            launch.assert_called_once()
            child.wait.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows package activation")
    def test_activation_requires_stable_exact_package_without_relaunch(self):
        for failure in ("wrong_package", "process_changed", "wrong_executable"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "explorer.exe").write_bytes(b"shell")
                official = root / "ChatGPT.exe"
                identity = {"pid": 123, "birth": "456", "executable": str(
                    root / "other.exe" if failure == "wrong_executable" else official)}
                ticks = iter([0, 0, 31])
                with mock.patch.dict(os.environ, {"SystemRoot": str(root)}), \
                        mock.patch.object(handoff, "_package_launch_target", return_value=(
                            "OpenAI.Codex_test!App", "OpenAI.Codex_test")), \
                        mock.patch.object(web_startup, "assert_desktop_closed"), \
                        mock.patch.object(handoff.subprocess, "Popen") as launch, \
                        mock.patch.object(web_service, "windows_process_entries", return_value=[
                            {"pid": 123, "name": "ChatGPT.exe"}]), \
                        mock.patch.object(web_service, "process_identity", side_effect=[
                            identity, {**identity, "birth": "789"}]), \
                        mock.patch.object(handoff, "_process_package_full_name", return_value=(
                            "other_package" if failure == "wrong_package" else "OpenAI.Codex_test")), \
                        mock.patch.object(handoff.time, "monotonic", side_effect=lambda: next(ticks)), \
                        mock.patch.object(handoff.time, "sleep"):
                    with self.assertRaisesRegex(handoff.HandoffError,
                                                "handoff_package_activation_unwitnessed"):
                        handoff.activate_official(official)
                    launch.assert_called_once()

    def test_manifest_binds_source_and_owned_entry(self):
        self.assertEqual(handoff._sources()["operator_web_activation_retire.py"],
            handoff._sha((SCRIPTS / "operator_web_activation_retire.py").read_bytes()))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            run = project / ".codex/operator-unified-handoff" / ("run-" + "a" * 32)
            run.mkdir(parents=True)
            entry = project / ".codex/operator-desktop-entry/Codex拓展入口.exe"
            entry.parent.mkdir()
            entry.write_bytes(b"owned entry")
            official = project / "ChatGPT.exe"
            official.write_bytes(b"official")
            home = project / "home"
            home.mkdir()
            sources = {name: "a" * 64 for name in handoff.SOURCES}
            manifest = {"schema_version": 1, "project": str(project), "home": str(home),
                        "python": sys.executable, "official": str(official),
                        "official_sha256": handoff._sha(b"official"),
                        "entry": str(entry), "entry_sha256": handoff._sha(b"owned entry"),
                        "plan": str(home / "operator-unified-activation/plan.json"),
                        "plan_sha256": "b" * 64, "config_sha256": "c" * 64,
                        "router_mode": "bound_idle",
                        "router_state": str(project / "router"),
                        "web_profile": str(project / "web"), "port": 4317,
                        "wait_seconds": 600, "source_sha256": sources}
            path = run / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf8")
            with mock.patch.object(handoff, "_fixed_paths", return_value=(project, project)), \
                    mock.patch.object(handoff, "_sources", return_value=sources):
                self.assertEqual(handoff._load_manifest(path), manifest)
                current = {**manifest, "schema_version": 2,
                           "plan_action": "complete_prepared"}
                path.write_text(json.dumps(current), encoding="utf8")
                self.assertEqual(handoff._load_manifest(path), current)
                changed_sources = {**sources, "operator_web_activation_retire.py": "d" * 64}
                with mock.patch.object(handoff, "_sources", return_value=changed_sources):
                    with self.assertRaisesRegex(handoff.HandoffError, "handoff_source_changed"):
                        handoff._load_manifest(path)
                path.write_text(json.dumps({**current,
                    "router_mode": "stopped_exact_process_absent"}), encoding="utf8")
                with self.assertRaisesRegex(handoff.HandoffError, "handoff_manifest_invalid"):
                    handoff._load_manifest(path)
                path.write_text(json.dumps(current), encoding="utf8")
                entry.write_bytes(b"later edit")
                with self.assertRaisesRegex(handoff.HandoffError, "handoff_source_changed"):
                    handoff._load_manifest(path)

    def test_wait_requires_two_closed_observations(self):
        ticks = [0]
        calls = [0]

        def clock():
            return ticks[0]

        def sleep(seconds):
            ticks[0] += seconds

        def check():
            calls[0] += 1
            if calls[0] == 1:
                raise RouterError("web_startup_close_desktop_before_activation")

        beats = []
        handoff.wait_for_normal_exit(check, seconds=30, clock=clock, sleep=sleep,
                                     heartbeat=lambda: beats.append(ticks[0]))
        self.assertEqual(calls[0], 3)
        self.assertEqual(ticks[0], 5)
        self.assertEqual(beats, [0, 2])

    @unittest.skipUnless(sys.platform == "win32", "Windows independent launcher")
    def test_launch_witnesses_wmi_process_lineage_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "manifest.json"
            path.write_bytes(b"manifest")
            manifest = {"python": sys.executable, "project": str(root), "wait_seconds": 120}
            def spawn(*args):
                (root / "started.json").write_text(json.dumps({
                    "schema_version": 1, "phase": "may_have_handed_off",
                    "manifest_sha256": handoff._sha(b"manifest"), "pid": 333}),
                    encoding="utf8")
                (root / "feedback-ready.json").write_text(json.dumps({"schema_version": 1,
                    "session": handoff._sha(b"manifest"), "pid": 444}), encoding="utf8")
                return 222

            with mock.patch.object(handoff, "_load_manifest", return_value=manifest), \
                    mock.patch.object(handoff, "_wmi_spawn", side_effect=spawn) as created, \
                    mock.patch.object(web_service, "process_identity", return_value={"pid": 222}), \
                    mock.patch.object(web_service, "parent_pid", side_effect=lambda pid: 333 if pid == 444 else 222):
                result = handoff.launch(path)
                self.assertEqual(result["status"], "handoff_running")
                with self.assertRaisesRegex(handoff.HandoffError,
                                            "handoff_already_started_or_uncertain"):
                    handoff.launch(path)
            created.assert_called_once_with(Path(sys.executable), path, root)
            self.assertTrue((root / "launch-intent.json").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows independent launcher")
    def test_launch_rejects_unrelated_started_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "manifest.json"
            path.write_bytes(b"manifest")
            manifest = {"python": sys.executable, "project": str(root)}

            def spawn(*args):
                (root / "started.json").write_text(json.dumps({
                    "schema_version": 1, "phase": "may_have_handed_off",
                    "manifest_sha256": handoff._sha(b"manifest"), "pid": 333}),
                    encoding="utf8")
                return 222

            with mock.patch.object(handoff, "_load_manifest", return_value=manifest), \
                    mock.patch.object(handoff, "_wmi_spawn", side_effect=spawn), \
                    mock.patch.object(web_service, "process_identity", return_value={"pid": 222}), \
                    mock.patch.object(web_service, "parent_pid", return_value=999):
                with self.assertRaisesRegex(handoff.HandoffError,
                                            "handoff_independent_process_unverified"):
                    handoff.launch(path)
            self.assertTrue((root / "launch-intent.json").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows independent launcher")
    def test_wmi_launch_uses_hidden_local_controller_and_bounded_result(self):
        import base64

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python.exe"
            manifest = root / "manifest.json"
            completed = mock.Mock(returncode=0, stdout=b'{"code":0,"pid":1234}')
            with mock.patch.object(handoff.subprocess, "run", return_value=completed) as run:
                self.assertEqual(handoff._wmi_spawn(python, manifest, root), 1234)
            args = run.call_args.args[0]
            self.assertEqual(args[1:5], ["-NoProfile", "-NonInteractive",
                                         "-WindowStyle", "Hidden"])
            controller = base64.b64decode(args[6]).decode("utf-16le")
            self.assertIn("Invoke-CimMethod -ClassName Win32_Process", controller)
            self.assertIn("CurrentDirectory=", controller)
            self.assertEqual(run.call_args.kwargs["timeout"], 20)
            self.assertEqual(run.call_args.kwargs["creationflags"],
                             handoff.subprocess.CREATE_NO_WINDOW)
            with mock.patch.object(handoff.subprocess, "run", return_value=
                                   mock.Mock(returncode=0, stdout=b'{"code":5,"pid":0}')):
                with self.assertRaisesRegex(handoff.HandoffError,
                                            "handoff_independent_launch_failed"):
                    handoff._wmi_spawn(python, manifest, root)

    def test_status_flags_missing_result_without_restarting(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            run = project / ".codex/operator-unified-handoff" / ("run-" + "b" * 32)
            run.mkdir(parents=True)
            path = run / "manifest.json"
            path.write_bytes(b"manifest")
            with mock.patch.object(handoff, "_fixed_paths", return_value=(project, project)):
                self.assertEqual(handoff.status(path)["status"], "handoff_prepared")
                started = run / "started.json"
                started.write_bytes(b"started")
                os.utime(started, (100, 100))
                self.assertEqual(handoff.status(path, clock=lambda: 999)["status"],
                                 "waiting_or_unknown")
                self.assertEqual(handoff.status(path, clock=lambda: 1001)["status"],
                                 "handoff_result_missing_review")

    def test_prepare_binds_current_config_only_for_scoped_cua_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            saved = b"model = 'native'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'one'\n"
            before = home / "operator-unified-activation/before.toml"
            before.parent.mkdir()
            before.write_bytes(saved)
            current = home / "config.toml"
            changed = saved.replace(b"'one'", b"'two'")
            current.write_bytes(changed)
            plan = {"config_sha256": handoff._sha(saved)}
            self.assertEqual(handoff._current_native_config_sha(home, plan),
                             handoff._sha(changed))
            current.write_bytes(saved.replace(b"'native'", b"'other'"))
            with self.assertRaisesRegex(handoff.HandoffError,
                                        "handoff_native_config_changed"):
                handoff._current_native_config_sha(home, plan)

    def test_prepare_refuses_dead_saved_router_before_creating_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            home = Path(temporary) / "home"
            project.mkdir()
            home.mkdir()
            project = project.resolve(strict=True)
            home = home.resolve(strict=True)
            entry = project / ".codex/operator-desktop-entry/Codex拓展入口.exe"
            entry.parent.mkdir(parents=True)
            entry.write_bytes(b"entry")
            official = project / "ChatGPT.exe"
            official.write_bytes(b"official")
            plan_dir = home / "operator-unified-activation"
            plan_dir.mkdir()
            (plan_dir / "plan.json").write_bytes(b"plan")
            (plan_dir / "before.toml").write_bytes(b"native")
            (home / "config.toml").write_bytes(b"native")
            (home / "operator-native-route-only").write_bytes(handoff.MARKER)
            plan = {"project": str(project), "home": str(home),
                    "config_sha256": handoff._sha(b"native")}
            with mock.patch.object(handoff, "_fixed_paths", return_value=(project, project)), \
                    mock.patch.object(cold, "_plan", return_value=(plan, b"plan", plan_dir)), \
                    mock.patch.object(cold, "status", return_value={"status": "prepared_not_armed"}), \
                    mock.patch.object(supersede, "_router_mode", side_effect=OSError("service gone")):
                with self.assertRaisesRegex(handoff.HandoffError,
                                            "handoff_router_unverified"):
                    handoff.prepare(project, home, Path(sys.executable), official)
            self.assertFalse((project / ".codex/operator-unified-handoff").exists())

    def test_prepared_current_pipeline_does_not_archive_or_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.json"
            config = root / "config.toml"
            manifest = {"plan": str(plan), "python": str(root / "python.exe"),
                        "project": str(root), "home": str(root),
                        "router_state": str(root / "router"),
                        "web_profile": str(root / "web"), "port": 4317,
                        "plan_sha256": handoff._sha(b"plan"),
                        "config_sha256": handoff._sha(b"config"),
                        "router_mode": "bound_idle", "plan_action": "complete_prepared",
                        "source_sha256": {}}
            def read(path, limit=65536):
                return b"plan" if path == plan else b"config"
            with mock.patch.object(handoff, "_read", side_effect=read), \
                    mock.patch.object(handoff, "_sources", return_value={}), \
                    mock.patch.object(handoff, "_verify_activation_entry") as verify, \
                    mock.patch.object(cold, "_plan", return_value=({}, b"plan", root)), \
                    mock.patch.object(cold, "status", return_value={"status": "prepared_not_armed"}), \
                    mock.patch.object(supersede, "_router_mode", return_value="bound_idle"), \
                    mock.patch.object(supersede, "supersede") as archive, \
                    mock.patch.object(preparation, "prepare") as prepare, \
                    mock.patch.object(router, "start") as start, \
                    mock.patch.object(marker, "preview", return_value={
                        "status": "reviewed_preview", "review_sha256": "m"}), \
                    mock.patch.object(marker, "release", return_value={
                        "status": "released_witnessed"}) as release, \
                    mock.patch.object(cold, "arm", return_value={
                        "status": "armed_for_one_cold_launch"}) as arm:
                stages = []
                handoff.execute(manifest, stages.append)
            self.assertEqual(stages, ["prepared_current", "marker_release", "arm", "consume"])
            archive.assert_not_called()
            prepare.assert_not_called()
            start.assert_not_called()
            release.assert_called_once_with(plan, "m")
            verify.assert_called_once_with({}, Path(manifest["python"]))
            arm.assert_called_once_with(plan, Path(manifest["python"]))

    def test_pipeline_uses_fresh_preview_digests_once_and_stops_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, config = root / "plan.json", root / "config.toml"
            manifest = {"plan": str(plan), "python": str(root / "python.exe"),
                        "project": str(root), "home": str(root),
                        "router_state": str(root / "router"),
                        "web_profile": str(root / "web"), "port": 4317,
                        "plan_sha256": handoff._sha(b"plan"),
                        "config_sha256": handoff._sha(b"config"),
                        "router_mode": "bound_idle",
                        "source_sha256": {}}
            calls = []

            def read(path, limit=65536):
                return b"plan" if path == plan else b"config"

            def preview(label, result):
                def invoke(*args):
                    calls.append(label + ":preview")
                    return {"status": "reviewed_preview", "review_sha256": result,
                            "prepare_available": True,
                            "blockers": ["unified_native_route_lock_active"]}
                return invoke

            def apply(label, expected, status):
                def invoke(*args):
                    calls.append(label + ":apply")
                    self.assertEqual(args[-1], expected)
                    return {"status": status}
                return invoke

            with mock.patch.object(handoff, "_read", side_effect=read), \
                    mock.patch.object(handoff, "_sources", return_value={}), \
                    mock.patch.object(handoff, "_verify_activation_entry") as verify, \
                    mock.patch.object(cold, "_plan", return_value=({}, b"plan", root)), \
                    mock.patch.object(supersede, "_router_mode", return_value="bound_idle"), \
                    mock.patch.object(supersede, "preview", side_effect=preview("supersede", "s")), \
                    mock.patch.object(supersede, "supersede", side_effect=apply("supersede", "s", "superseded_witnessed")), \
                    mock.patch.object(preparation, "preview", side_effect=preview("prepare", "p")), \
                    mock.patch.object(preparation, "prepare", side_effect=apply("prepare", "p", "prepared_not_armed")), \
                    mock.patch.object(marker, "preview", side_effect=preview("marker", "m")), \
                    mock.patch.object(marker, "release", side_effect=apply("marker", "m", "released_witnessed")), \
                    mock.patch.object(cold, "arm", return_value={"status": "armed_for_one_cold_launch"}) as arm:
                stages = []
                handoff.execute(manifest, stages.append)
            self.assertEqual(calls, ["supersede:preview", "supersede:apply",
                                     "prepare:preview", "prepare:apply",
                                     "marker:preview", "marker:apply"])
            self.assertEqual(stages, ["supersede", "prepare", "marker_release", "arm", "consume"])
            arm.assert_called_once_with(plan, Path(manifest["python"]))
            verify.assert_called_once_with({}, Path(manifest["python"]))

    def test_stopped_router_starts_fresh_only_after_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, config = root / "plan.json", root / "config.toml"
            manifest = {"plan": str(plan), "python": str(root / "python.exe"),
                        "project": str(root), "home": str(root),
                        "router_state": str(root / "router"),
                        "web_profile": str(root / "web"), "port": 4317,
                        "plan_sha256": handoff._sha(b"plan"),
                        "config_sha256": handoff._sha(b"config"),
                        "router_mode": "stopped_exact_process_absent",
                        "source_sha256": {}}
            calls = []

            def preview(*args):
                calls.append("prepare")
                return {"status": "reviewed_preview", "prepare_available": True,
                        "blockers": ["unified_native_route_lock_active"],
                        "review_sha256": "p"}

            with mock.patch.object(handoff, "_read", side_effect=lambda path, limit=65536:
                                   b"plan" if path == plan else b"config"), \
                    mock.patch.object(handoff, "_sources", return_value={}), \
                    mock.patch.object(handoff, "_verify_activation_entry") as verify, \
                    mock.patch.object(cold, "_plan", return_value=({}, b"plan", root)), \
                    mock.patch.object(supersede, "_router_mode", return_value="stopped_exact_process_absent"), \
                    mock.patch.object(supersede, "preview", return_value={"status": "reviewed_preview", "review_sha256": "s"}), \
                    mock.patch.object(supersede, "supersede", side_effect=lambda *args:
                                      calls.append("archive") or {"status": "superseded_witnessed"}), \
                    mock.patch.object(router, "start", side_effect=lambda *args, **kwargs:
                                      calls.append("start") or {"status": "ready", "pid": 123,
                                                               "service": "exact"}) as start, \
                    mock.patch.object(router, "bind_web", side_effect=lambda *args:
                                      calls.append("bind") or {"pid": 123, "service": "exact"}) as bind, \
                    mock.patch.object(preparation, "preview", side_effect=preview), \
                    mock.patch.object(preparation, "prepare", return_value={"status": "prepared_not_armed"}), \
                    mock.patch.object(marker, "preview", return_value={"status": "reviewed_preview", "review_sha256": "m"}), \
                    mock.patch.object(marker, "release", return_value={"status": "released_witnessed"}), \
                    mock.patch.object(cold, "arm", return_value={"status": "armed_for_one_cold_launch"}):
                handoff.execute(manifest, lambda _: None)
            self.assertEqual(calls, ["archive", "start", "bind", "prepare"])
            start.assert_called_once_with(root / "router", 4317,
                                          web_profile=root / "web", require_fresh=True)
            bind.assert_called_once_with(root / "router", 4317, root / "web")
            verify.assert_called_once_with({}, Path(manifest["python"]))

    def test_router_change_after_archive_stops_before_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.json"
            manifest = {"plan": str(plan), "python": str(root / "python.exe"),
                        "project": str(root), "home": str(root),
                        "router_state": str(root / "router"),
                        "web_profile": str(root / "web"), "port": 4317,
                        "plan_sha256": handoff._sha(b"plan"),
                        "config_sha256": handoff._sha(b"config"),
                        "router_mode": "stopped_exact_process_absent",
                        "source_sha256": {}}
            with mock.patch.object(handoff, "_read", side_effect=lambda path, limit=65536:
                                   b"plan" if path == plan else b"config"), \
                    mock.patch.object(handoff, "_sources", return_value={}), \
                    mock.patch.object(cold, "_plan", return_value=({}, b"plan", root)), \
                    mock.patch.object(supersede, "_router_mode", side_effect=[
                        "stopped_exact_process_absent", "bound_idle"]), \
                    mock.patch.object(supersede, "preview", return_value={
                        "status": "reviewed_preview", "review_sha256": "s"}), \
                    mock.patch.object(supersede, "supersede", return_value={
                        "status": "superseded_witnessed"}), \
                    mock.patch.object(router, "start") as start, \
                    mock.patch.object(preparation, "preview") as prepare:
                with self.assertRaisesRegex(handoff.HandoffError,
                                            "handoff_router_changed"):
                    handoff.execute(manifest, lambda _: None)
            start.assert_not_called()
            prepare.assert_not_called()

    def test_marker_block_never_arms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {"plan": str(root / "plan.json"), "python": str(root / "python.exe"),
                        "project": str(root), "home": str(root),
                        "router_state": str(root / "router"),
                        "web_profile": str(root / "web"), "port": 4317,
                        "plan_sha256": handoff._sha(b"plan"),
                        "config_sha256": handoff._sha(b"config"),
                        "router_mode": "bound_idle",
                        "source_sha256": {}}
            with mock.patch.object(handoff, "_read", side_effect=lambda path, limit=65536:
                                   b"plan" if path.name == "plan.json" else b"config"), \
                    mock.patch.object(handoff, "_sources", return_value={}), \
                    mock.patch.object(cold, "_plan", return_value=({}, b"plan", root)), \
                    mock.patch.object(supersede, "_router_mode", return_value="bound_idle"), \
                    mock.patch.object(supersede, "preview", return_value={"status": "reviewed_preview", "review_sha256": "s"}), \
                    mock.patch.object(supersede, "supersede", return_value={"status": "superseded_witnessed"}), \
                    mock.patch.object(preparation, "preview", return_value={"status": "reviewed_preview", "review_sha256": "p", "prepare_available": True, "blockers": ["unified_native_route_lock_active"]}), \
                    mock.patch.object(preparation, "prepare", return_value={"status": "prepared_not_armed"}), \
                    mock.patch.object(marker, "preview", return_value={"status": "unavailable"}), \
                    mock.patch.object(marker, "release") as release, \
                    mock.patch.object(cold, "arm") as arm:
                with self.assertRaisesRegex(handoff.HandoffError, "handoff_marker_blocked"):
                    handoff.execute(manifest, lambda _: None)
            release.assert_not_called()
            arm.assert_not_called()

    def test_run_consumes_once_then_activates_packaged_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "manifest.json"
            path.write_bytes(b"manifest")
            official = root / "ChatGPT.exe"
            manifest = {"wait_seconds": 30, "source_sha256": {},
                        "official": str(official), "plan": str(root / "plan.json")}
            with mock.patch.object(handoff, "_load_manifest", return_value=manifest), \
                    mock.patch.object(handoff, "Feedback") as feedback, \
                    mock.patch.object(handoff, "wait_for_normal_exit") as wait, \
                    mock.patch.object(handoff, "execute") as execute, \
                    mock.patch.object(cold, "consume", return_value={
                        "status": "config_switch_witnessed"}) as consume, \
                    mock.patch.object(handoff, "activate_official") as launch:
                feedback.return_value.finish.side_effect = OSError('synthetic display failure')
                result = handoff.run(path)
            self.assertEqual(result["status"], "config_switch_witnessed")
            self.assertEqual(result["desktop_acceptance"], "unverified")
            self.assertEqual(result["model_requests"], 0)
            wait.assert_called_once()
            execute.assert_called_once()
            consume.assert_called_once_with(root / "plan.json")
            launch.assert_called_once_with(official)
            self.assertEqual(result["package_activation"], "witnessed")
            feedback.return_value.applying.assert_called_once()
            feedback.return_value.finish.assert_called_once_with(result)
            self.assertEqual(json.loads((root / "result.json").read_text())["status"],
                             "config_switch_witnessed")

    def test_failure_reopens_native_only_with_original_config_and_no_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "manifest.json"
            path.write_bytes(b"manifest")
            official = root / "ChatGPT.exe"
            official.write_bytes(b"official")
            manifest = {"wait_seconds": 30, "source_sha256": {},
                        "entry": str(root / "entry.exe"), "official": str(official),
                        "official_sha256": handoff._sha(b"official"),
                        "home": str(root), "config_sha256": handoff._sha(b"native"),
                        "plan": str(root / "operator-unified-activation/plan.json")}

            def fail(_, progress, run_directory):
                progress("prepare")
                raise handoff.HandoffError("handoff_preparation_blocked")

            def read(path, limit=65536):
                return b"native" if path.name == "config.toml" else b"official"

            with mock.patch.object(handoff, "_load_manifest", return_value=manifest), \
                    mock.patch.object(handoff, "Feedback"), \
                    mock.patch.object(handoff, "wait_for_normal_exit"), \
                    mock.patch.object(handoff, "execute", side_effect=fail), \
                    mock.patch.object(handoff, "_read", side_effect=read), \
                    mock.patch.object(web_startup, "assert_desktop_closed"), \
                    mock.patch.object(handoff, "activate_official") as launch:
                result = handoff.run(path)
            self.assertEqual(result["status"], "stopped_for_review")
            self.assertTrue(result["native_reopen_attempted"])
            self.assertTrue(result["native_reopen_witnessed"])
            launch.assert_called_once_with(official)

    def test_unknown_exit_observation_is_not_silently_polled_until_timeout(self):
        sleep = mock.Mock()
        with self.assertRaisesRegex(handoff.HandoffError, "exit_observation_unavailable"):
            handoff.wait_for_normal_exit(mock.Mock(side_effect=RouterError('web_manager_process_observation_unavailable')),
                seconds=120, sleep=sleep)
        sleep.assert_not_called()

    def test_local_preflight_failure_codes_survive_terminal_redaction_once(self):
        from operator_core.windows_config_transaction import TransactionFailure
        for error in (supersede.SupersedeError('unified_supersede_native_state_changed'),
                      supersede.SupersedeError('unified_supersede_preflight_changed'),
                      preparation.PrepareError('unified_review_changed'),
                      TransactionFailure('open_32')):
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);path=root/'manifest.json';path.write_bytes(b'manifest')
                manifest={'wait_seconds':120,'plan':str(root/'plan.json')}
                with mock.patch.object(handoff,'_load_manifest',return_value=manifest), \
                     mock.patch.object(handoff,'Feedback'), \
                     mock.patch.object(handoff,'wait_for_normal_exit'), \
                     mock.patch.object(handoff,'execute',side_effect=error) as execute, \
                     mock.patch.object(cold,'status',return_value={'status':'prepared_not_armed'}), \
                     mock.patch.object(handoff,'activate_official') as activate:
                    result=handoff.run(path)
                execute.assert_called_once();activate.assert_not_called()
                self.assertEqual(result['reason'],str(error))
                self.assertEqual(result['status'],'stopped_for_review')
                self.assertEqual(json.loads((root/'result.json').read_bytes())['reason'],str(error))

    def test_local_failure_diagnostics_reject_untyped_unknown_and_private_text(self):
        from operator_core.windows_config_transaction import TransactionFailure
        for error in (ValueError('unified_supersede_preflight_changed'),
                      supersede.SupersedeError('private request content'),
                      supersede.SupersedeError('unified_supersede_unknown'),
                      TransactionFailure('open_4294967296'),
                      TransactionFailure('open_32 secret'),
                      preparation.PrepareError('unknown path or config')):
            with self.subTest(error_type=type(error).__name__):
                self.assertIsNone(handoff._local_failure_reason(error))

    def test_defer_after_first_closed_observation_prevents_dispatch(self):
        guard = mock.Mock(side_effect=[None, handoff.FeedbackError('handoff_deferred')])
        check = mock.Mock()
        with self.assertRaisesRegex(handoff.FeedbackError, 'handoff_deferred'):
            handoff.wait_for_normal_exit(check, seconds=120, sleep=mock.Mock(), guard=guard)
        check.assert_called_once()

    def test_wait_failure_never_changes_settings_or_reopens_application(self):
        for reason in ('handoff_wait_expired', 'handoff_deferred', 'handoff_feedback_closed'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'manifest.json'
                path.write_bytes(b'manifest')
                manifest = {'wait_seconds':120,'plan':str(root/'plan.json')}
                with mock.patch.object(handoff, '_load_manifest', return_value=manifest), \
                     mock.patch.object(handoff, 'Feedback') as feedback, \
                     mock.patch.object(handoff, 'wait_for_normal_exit', side_effect=handoff.HandoffError(reason)), \
                     mock.patch.object(handoff, 'execute') as execute, \
                     mock.patch.object(handoff, 'activate_official') as activate, \
                     mock.patch.object(cold, 'status', return_value={'status':'prepared_not_armed'}):
                    result = handoff.run(path)
                execute.assert_not_called()
                activate.assert_not_called()
                self.assertFalse(result['configuration_changed'])
                self.assertEqual(result['reason'],reason)
                feedback.return_value.finish.assert_called_once_with(result)

    def test_status_reads_only_current_feedback_and_keeps_terminal_result_authoritative(self):
        from operator_handoff_feedback import write_state
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary)
            root=project/'.codex/operator-unified-handoff'/('run-'+'c'*32)
            root.mkdir(parents=True)
            path=root/'manifest.json';path.write_bytes(b'manifest')
            value={'schema_version':1,'session':handoff._sha(b'manifest'),
                   'updated_at':100,'phase':'waiting','remaining_seconds':75}
            with mock.patch.object(handoff,'_fixed_paths',return_value=(project,project)):
                write_state(root,value)
                self.assertEqual(handoff.status(path,clock=lambda:101)['remaining_seconds'],75)
                write_state(root,{**value,'phase':'applying'})
                self.assertNotIn('configuration_changed',handoff.status(path,clock=lambda:101))
                (root/'result.json').write_text(json.dumps({'status':'stopped_for_review','reason':'handoff_wait_expired'}))
                self.assertEqual(handoff.status(path,clock=lambda:101)['reason'],'handoff_wait_expired')

    def test_unavailable_feedback_stops_before_exit_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'manifest.json';path.write_bytes(b'manifest')
            manifest={'wait_seconds':120,'plan':str(root/'plan.json')}
            with mock.patch.object(handoff,'_load_manifest',return_value=manifest), \
                 mock.patch.object(handoff,'Feedback') as feedback, \
                 mock.patch.object(handoff,'wait_for_normal_exit') as wait, \
                 mock.patch.object(handoff,'execute') as execute, \
                 mock.patch.object(cold,'status',return_value={'status':'prepared_not_armed'}):
                feedback.return_value.start.side_effect=handoff.FeedbackError('handoff_feedback_unavailable')
                result=handoff.run(path)
            wait.assert_not_called();execute.assert_not_called()
            self.assertEqual(result['reason'],'handoff_feedback_unavailable')


if __name__ == "__main__":
    unittest.main()
