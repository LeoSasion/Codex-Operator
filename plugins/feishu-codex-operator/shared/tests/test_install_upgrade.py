"""Exercise the naming upgrade without a real project, task, or chat."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)


import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = _OPERATOR_PLUGIN_ROOT
PWSH = shutil.which("pwsh")


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell installer")
class InstallUpgradeTests(unittest.TestCase):
    @staticmethod
    def ps_quote(value: Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    @staticmethod
    def project_snapshot(root: Path) -> dict:
        """Include directories and links, without traversing linked destinations."""
        result = {}
        for directory, children, files in os.walk(root, followlinks=False):
            current = Path(directory)
            for name in list(children):
                path = current / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or (
                        getattr(path.lstat(), 'st_file_attributes', 0)
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    result[relative] = ('link', str(path.readlink()))
                    children.remove(name)
                else:
                    result[relative] = ('directory',)
            for name in files:
                path = current / name
                result[path.relative_to(root).as_posix()] = (
                    ('link', str(path.readlink())) if path.is_symlink()
                    else ('file', path.read_bytes()))
        return result

    @staticmethod
    def source_fixture(base: Path, *, licenses: bool = True) -> Path:
        source = base / 'source'
        shutil.copytree(ROOT / 'scripts', source / 'scripts',
                        ignore=shutil.ignore_patterns('__pycache__', '.tmp'))
        (source / 'assets').mkdir()
        shutil.copyfile(ROOT / 'assets/release-inventory.json',
                        source / 'assets/release-inventory.json')
        (source / 'models/web').mkdir(parents=True)
        if licenses:
            shutil.copytree(ROOT / 'models/web/licenses', source / 'models/web/licenses')
        return source

    @staticmethod
    def install_fixture(source: Path, project: Path, *options: str) -> subprocess.CompletedProcess:
        return subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File',
            str(source / 'scripts/install-feishu-codex-operator.ps1'),
            '-ProjectRoot', str(project), '-SkipHooks', '-SkipRuntimeConfig',
            '-SkipDesktopEntry', *options], capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)

    def test_install_plan_rejects_missing_late_source_before_any_project_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.source_fixture(base)
            (source / 'scripts/operator_core/state.py').unlink()
            project = base / 'project'
            project.mkdir()
            (project / 'AGENTS.md').write_bytes(b'original user rules\r\n')
            before = self.project_snapshot(project)
            result = self.install_fixture(source, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Source file is missing:', result.stderr)
            self.assertEqual(self.project_snapshot(project), before)

    def test_install_plan_rejects_late_conflict_before_copying_or_backing_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.source_fixture(base)
            project = base / 'project'
            runtime = project / '.codex/feishu-codex-operator-runtime'
            (runtime / 'operator_core').mkdir(parents=True)
            # An early matching file would otherwise be backed up, while the
            # conflicting late file is not inspected until almost all copies.
            shutil.copyfile(source / 'scripts/operator_main.py', runtime / 'operator_main.py')
            (runtime / 'operator_core/state.py').write_bytes(b'owner reviewed local edit\r\n')
            before = self.project_snapshot(project)
            result = self.install_fixture(source, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Installed file differs;', result.stderr)
            self.assertEqual(self.project_snapshot(project), before)

    def test_install_plan_rejects_linked_late_source_before_any_project_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.source_fixture(base, licenses=False)
            outside = base / 'outside'
            shutil.copytree(ROOT / 'models/web/licenses', outside)
            link = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command',
                f"New-Item -ItemType Junction -Path {self.ps_quote(source / 'models/web/licenses')} "
                f"-Target {self.ps_quote(outside)} | Out-Null"], capture_output=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(link.returncode, 0, link.stderr)
            project = base / 'project'
            project.mkdir()
            before = self.project_snapshot(project)
            outside_before = self.project_snapshot(outside)
            result = self.install_fixture(source, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Installation path contains a link or reparse point', result.stderr)
            self.assertEqual(self.project_snapshot(project), before)
            self.assertEqual(self.project_snapshot(outside), outside_before)

    def test_hooks_only_does_not_require_runtime_copy_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'source'
            (source / 'scripts/operator_core').mkdir(parents=True)
            (source / 'assets').mkdir()
            for relative in ('scripts/install-feishu-codex-operator.ps1',
                    'scripts/operator_installation.psm1', 'scripts/operator_core/config.py',
                    'scripts/start-feishu-codex-operator.ps1',
                    'scripts/stop-feishu-codex-operator.ps1', 'assets/release-inventory.json'):
                shutil.copyfile(ROOT / relative, source / relative)
            project = base / 'project'
            project.mkdir()
            result = self.install_fixture(source, project, '-HooksOnly')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(b'Lifecycle Hooks were refreshed', result.stdout)
            for name in ('start-feishu-codex-operator.ps1', 'stop-feishu-codex-operator.ps1'):
                self.assertEqual((project / '.codex/hooks' / name).read_bytes(),
                                 (source / 'scripts' / name).read_bytes())
            self.assertFalse((project / '.codex/feishu-codex-operator-runtime/operator_main.py').exists())

    def test_install_plan_rejects_file_parent_or_directory_target_before_writes(self):
        for damage in ('file_parent', 'directory_target', 'generated_directory'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                source = self.source_fixture(base)
                project = base / 'project'
                runtime = project / '.codex/feishu-codex-operator-runtime'
                runtime.mkdir(parents=True)
                if damage == 'file_parent':
                    (runtime / 'operator_core').write_bytes(b'not a directory\r\n')
                    expected = b'Installation parent is not a directory:'
                else:
                    target = runtime / ('operator_main.py' if damage == 'directory_target'
                                        else 'runtime-manifest.json')
                    target.mkdir()
                    expected = b'Installation target is not a file:'
                before = self.project_snapshot(project)
                result = self.install_fixture(source, project)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertEqual(self.project_snapshot(project), before)

    def test_source_version_mismatch_or_duplicate_stops_before_runtime_writes(self):
        original = (ROOT / 'scripts/install-feishu-codex-operator.ps1').read_bytes()
        for config, inventory_version, schema, expected in (
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\n', '4.2.0-alpha.2', 1, 'operator_source_version_mismatch'),
            ('OPERATOR_VERSION = "a"\nOPERATOR_VERSION = "b"\n', 'a', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = str(1)\n', '1', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\nOPERATOR_VERSION = str(2)\n', '4.2.0-alpha.1', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\nOPERATOR_VERSION: str = "4.2.0-alpha.2"\n', '4.2.0-alpha.1', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1\'\n', '4.2.0-alpha.1', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = "4.2.0-alpha.\\x31"\n', '4.2.0-alpha.\\x31', 1, 'operator_source_version_invalid'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\n', ['4.2.0-alpha.1'], 1, 'operator_source_version_mismatch'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\n', '4.2.0-alpha.1', True, 'operator_source_version_mismatch'),
            ('OPERATOR_VERSION = "4.2.0-alpha.1"\n', '4.2.0-alpha.1', '1', 'operator_source_version_mismatch'),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                source = base / 'source'
                scripts = source / 'scripts'
                (scripts / 'operator_core').mkdir(parents=True)
                (source / 'assets').mkdir()
                (scripts / 'install-feishu-codex-operator.ps1').write_bytes(original)
                (scripts / 'operator_core/config.py').write_text(config, encoding='utf8')
                (source / 'assets/release-inventory.json').write_text(json.dumps(
                    {'schema_version': schema, 'source_version': inventory_version}), encoding='utf8')
                # Import succeeds, but reaching a runtime path before version
                # refusal is an observable fixture failure, not a stubbed pass.
                (scripts / 'operator_installation.psm1').write_text('''
function Assert-OperatorPlainPath($Path) {
 if ($Path -like '*feishu-codex-operator-runtime*') {throw 'fixture_unexpected_runtime_boundary'}
}
Export-ModuleMember -Function Assert-OperatorPlainPath
''', encoding='utf8')
                project = base / 'project'
                project.mkdir()
                before = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob('*') if p.is_file()}
                result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File',
                    str(scripts / 'install-feishu-codex-operator.ps1'), '-ProjectRoot', str(project)],
                    capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr.decode('utf8', errors='replace'))
                self.assertNotIn(b'fixture_unexpected_runtime_boundary', result.stderr)
                self.assertFalse((project / '.codex').exists())
                self.assertEqual(before, {str(p.relative_to(base)): p.read_bytes()
                                         for p in base.rglob('*') if p.is_file()})

    def test_managed_upgrade_stops_when_original_backup_is_missing_or_changed(self) -> None:
        for damage in ("missing", "changed"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                target = project / "AGENTS.md"
                target.write_bytes(b"user original\r\n")
                module = ROOT / "scripts" / "operator_installation.psm1"

                def managed_write(contents: str) -> subprocess.CompletedProcess[str]:
                    command = (
                        f"Import-Module {self.ps_quote(module)} -Force; "
                        f"$p = {self.ps_quote(project)}; "
                        "Set-OperatorManagedFile -ProjectRoot $p "
                        "-Path (Join-Path $p 'AGENTS.md') "
                        f"-Bytes ([Text.Encoding]::UTF8.GetBytes('{contents}'))"
                    )
                    return subprocess.run(
                        [PWSH, "-NoProfile", "-Command", command],
                        capture_output=True, text=True, timeout=20,
                    )

                initial = managed_write("installed")
                self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                backup = next((project / ".codex/operator-installation/originals").glob("*.bin"))
                if damage == "missing":
                    backup.unlink()
                else:
                    backup.write_bytes(b"not the original")
                journal = project / ".codex/operator-installation/ownership.json"
                journal_before = journal.read_bytes()
                upgrade = managed_write("upgraded")
                self.assertNotEqual(upgrade.returncode, 0, upgrade.stdout + upgrade.stderr)
                self.assertEqual(target.read_bytes(), b"installed")
                self.assertEqual(journal.read_bytes(), journal_before)

    def test_managed_upgrade_rejects_invalid_existing_ownership_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "AGENTS.md"
            target.write_bytes(b"user original\n")
            module = ROOT / "scripts" / "operator_installation.psm1"
            command = (
                f"Import-Module {self.ps_quote(module)} -Force; "
                f"$p = {self.ps_quote(project)}; "
                "Set-OperatorManagedFile -ProjectRoot $p "
                "-Path (Join-Path $p 'AGENTS.md') "
                "-Bytes ([Text.Encoding]::UTF8.GetBytes($env:MANAGED_BYTES))"
            )

            def write(contents: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [PWSH, "-NoProfile", "-Command", command],
                    capture_output=True, text=True, timeout=20,
                    env={**os.environ, "MANAGED_BYTES": contents},
                )

            initial = write("installed")
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            journal = project / ".codex/operator-installation/ownership.json"
            state = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(len(state["entries"]), 1)
            next(iter(state["entries"].values()))["before"] = "invalid"
            journal.write_text(json.dumps(state), encoding="utf-8")
            journal_before = journal.read_bytes()
            upgrade = write("upgraded")
            self.assertNotEqual(upgrade.returncode, 0, upgrade.stdout + upgrade.stderr)
            self.assertEqual(target.read_bytes(), b"installed")
            self.assertEqual(journal.read_bytes(), journal_before)

    def test_installer_rejects_linked_runtime_before_copying_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            (project / ".codex").mkdir(parents=True)
            outside = base / "outside"
            outside.mkdir()
            runtime = project / ".codex/feishu-codex-operator-runtime"
            link = subprocess.run(
                [PWSH, "-NoProfile", "-Command",
                 f"New-Item -ItemType Junction -Path {self.ps_quote(runtime)} "
                 f"-Target {self.ps_quote(outside)} | Out-Null"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(link.returncode, 0, link.stdout + link.stderr)
            before = self.project_snapshot(project)
            result = subprocess.run(
                [PWSH, "-NoProfile", "-File",
                 str(ROOT / "scripts/install-feishu-codex-operator.ps1"),
                 "-ProjectRoot", str(project), "-Force", "-SkipHooks",
                 "-SkipRuntimeConfig", "-SkipDesktopEntry"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Installation path contains a link or reparse point", result.stderr)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(self.project_snapshot(project), before)

    def test_installer_rejects_linked_runtime_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            runtime = project / ".codex/feishu-codex-operator-runtime"
            runtime.mkdir(parents=True)
            outside = base / "outside"
            outside.mkdir()
            link = subprocess.run(
                [PWSH, "-NoProfile", "-Command",
                 f"New-Item -ItemType Junction -Path {self.ps_quote(runtime / 'operator_core')} "
                 f"-Target {self.ps_quote(outside)} | Out-Null"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(link.returncode, 0, link.stdout + link.stderr)
            before = self.project_snapshot(project)
            result = subprocess.run(
                [PWSH, "-NoProfile", "-File",
                 str(ROOT / "scripts/install-feishu-codex-operator.ps1"),
                 "-ProjectRoot", str(project), "-Force", "-SkipHooks",
                 "-SkipRuntimeConfig", "-SkipDesktopEntry"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Installation path contains a link or reparse point", result.stderr)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(self.project_snapshot(project), before)
            self.assertFalse((runtime / "operator_main.py").exists())

    def test_repeated_upgrade_preserves_state_and_checks_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            runtime = project / ".codex" / "feishu-codex-operator-runtime"
            runtime.mkdir(parents=True)
            preserved = {
                "operator.env": b"CODEX_OPERATOR_LIFECYCLE_MODE=manual\n",
                "sessions.json": b'{"fixture": "binding"}',
                "state.sqlite3": b"isolated inbox fixture",
                "callbacks.sqlite3": b"isolated callback fixture",
            }
            for name, value in preserved.items():
                (runtime / name).write_bytes(value)
            command = [
                PWSH, "-NoProfile", "-File",
                str(ROOT / "scripts" / "install-feishu-codex-operator.ps1"),
                "-ProjectRoot", str(project), "-Force", "-SkipHooks",
                "-SkipRuntimeConfig", "-SkipDesktopEntry",
            ]
            for _ in range(2):
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertTrue((runtime / "operator_core" / "runtime.py").is_file())
                self.assertTrue((runtime / "operator_core" / "beeper_provider.py").is_file())
                catalog = json.loads(
                    (runtime / "operator_core" / "beeper_model_catalog.json").read_text()
                )
                self.assertEqual("beeper", catalog["models"][0]["slug"])
                self.assertEqual("list", catalog["models"][0]["visibility"])
                for name, value in preserved.items():
                    self.assertEqual(value, (runtime / name).read_bytes(), name)
                manifest = json.loads((runtime / "runtime-manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest['public_entry'], {
                    'path': str(ROOT / 'scripts/codex-operator.ps1'),
                    'sha256': hashlib.sha256((ROOT / 'scripts/codex-operator.ps1').read_bytes()).hexdigest()})
                startup = (ROOT / 'scripts' / 'start-feishu-codex-operator.ps1').read_text(encoding='utf-8')
                manifest_check = startup.split('function Assert-OperatorRuntimeManifest {', 1)[1]
                expected_block = re.search(r'\$expectedFiles = @\((.*?)\n\s*\)', manifest_check, re.S).group(1)
                startup_files = re.findall(r"'([^']+)'", expected_block)
                self.assertEqual(set(manifest['code_files']), set(startup_files),
                                 'The startup guard must accept exactly the installed inventory')
                self.assertIn("operator_core/runtime.py", manifest["code_files"])
                for relative in ('operator_web_model.py', 'operator_web_service.py', 'operator_web_acceptance.py', 'operator_web_desktop.py', 'operator_web_entry.ps1', 'operator_native_models.py', 'web_browser_host.cjs',
                        'web_browser_surface.cjs', 'web_browser_page.cjs',
                        'operator_core/web_browser_session.py',
                        'operator_core/web_openai_tunnel.py',
                        'operator_core/web_responses_provider.py',
                        'operator_core/web_native_interruption.py',
                        'operator_core/native_search.py',
                        'licenses/codex-chatgpt-web-MIT.txt', 'licenses/webcodex-Apache-2.0.txt'):
                    self.assertIn(relative, manifest['code_files'])
                    source = ROOT / 'scripts' / relative
                    if relative in ('licenses/codex-chatgpt-web-MIT.txt', 'licenses/webcodex-Apache-2.0.txt'):
                        source = ROOT / 'models/web' / relative
                    self.assertEqual(source.read_bytes(),
                        (runtime / relative).read_bytes())
                for relative, digest in manifest["code_files"].items():
                    self.assertEqual(
                        hashlib.sha256((runtime / relative).read_bytes()).hexdigest(),
                        digest,
                    )
                self.assertFalse((runtime / "operator.pid").exists())
                # Isolated Python excludes the source tree and PYTHONPATH. A
                # manifest can be internally consistent while missing an import.
                imported = subprocess.run([sys.executable, '-I', '-B', '-c',
                    'import sys; sys.path.insert(0, sys.argv[1]); '
                    'import operator_web_model, operator_web_service; '
                    'from operator_core.web_openai_tunnel import WebOpenAITunnel; '
                    'from operator_core.web_native_interruption import read_interruption; '
                    'from operator_core.model_router import ModelRouter; '
                    'from operator_core.model_registry import ModelRegistry; '
                    'import json; from pathlib import Path; '
                    'registry = ModelRegistry({"version":1,"models":[]}, json.loads('
                    '(Path(sys.argv[1])/"operator_core/beeper_model_catalog.json").read_text())); '
                    'router = ModelRouter(registry, "a"*64); '
                    'assert router.native_search_identity is None; '
                    'assert router.native_enabled is True; '
                    'assert ModelRouter(registry, "b"*64, native_enabled=False).native_enabled is False',
                    str(runtime)], cwd=project, capture_output=True, text=True, timeout=20)
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
                native_help = subprocess.run([sys.executable, '-I', '-B', '-c',
                    'import runpy, sys; from pathlib import Path; '
                    'runtime = Path(sys.argv[1]); sys.path.insert(0, str(runtime)); '
                    'sys.argv = [str(runtime / "operator_native_models.py"), "--help"]; '
                    'runpy.run_path(sys.argv[0], run_name="__main__")', str(runtime)],
                    cwd=project, capture_output=True, text=True, timeout=20)
                self.assertEqual(native_help.returncode, 0, native_help.stdout + native_help.stderr)
                self.assertIn('--manifest', native_help.stdout)
            self.assertTrue((runtime / "backups").is_dir())
            installed_entry = subprocess.run([PWSH, '-NoProfile', '-File', str(runtime/'codex-operator.ps1'),
                'status', '-ProjectRoot', str(project), '-Json'], capture_output=True, text=True, timeout=60)
            self.assertEqual(installed_entry.returncode, 0, installed_entry.stderr)
            installed_report = json.loads(installed_entry.stdout)
            self.assertEqual(installed_report['schema_version'], 2)
            self.assertEqual(set(installed_report['components']), {'channels', 'models'})
            # Test the installed status output, not spelling in its PowerShell source.
            public_rate = {
                "status": "cached", "limit_id": "fixture-limit", "remaining_percent": 80,
                "window_duration_minutes": 300, "reset_at": 2000000000,
                "beeper_model": "gpt-5.6-luna", "beeper_reasoning_effort": "low",
                "beeper_limit_id": None, "beeper_remaining_percent": None,
                "beeper_window_duration_minutes": None, "beeper_reset_at": None,
            }
            health = {
                "status": "stopped", "operator_version": manifest["operator_version"],
                "session_owner": "responder", "responder_writer": "beeper-task-send",
                "responder_transport": "beeper-relay", "responder_status_observer": "app-server-metadata-readonly",
                "catalog_transport": "app-server-readonly", "event_consumer": False, "pid": os.getpid(),
                "beeper_wake_signal": {"lease_active": False, "lease_seconds": 1800, "fallback_delay_seconds": 30},
                "active_turns": 0, "unknown_status_timeout_seconds": 300, "callback_grace_seconds": 20,
                "callback_queue": {"pending": 0}, "started_at": time.time(), "updated_at": time.time(),
                "account_rate_limits": {**public_rate, "account_id": "private-fixture-value",
                                        "unexpected_data": "private-fixture-value"},
            }
            (runtime / "health.json").write_text(json.dumps(health), encoding="utf-8")
            status = subprocess.run(
                [PWSH, "-NoProfile", "-File",
                 str(ROOT / "scripts" / "feishu-codex-operator.ps1"),
                 "operator", "status", "-ProjectRoot", str(project), "-Json"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(0, status.returncode, status.stdout + status.stderr)
            report = json.loads(status.stdout)
            self.assertTrue(report["installed_manifest"]["valid"], report)
            self.assertFalse(report["runtime"]["running"], report)
            snapshot = report["health_snapshot"]
            self.assertTrue(snapshot["valid"], report)
            self.assertEqual(snapshot["account_rate_limits"], public_rate)
            self.assertEqual(snapshot["beeper_wake_signal"], health["beeper_wake_signal"])
            for key in ("unknown_status_timeout_seconds", "callback_grace_seconds", "responder_status_observer"):
                self.assertEqual(snapshot[key], health[key])
            self.assertNotIn("private-fixture-value", status.stdout)
            for model, effort, valid in (("gpt-6-luna", "low", True),
                                        ("gpt-6-luna", "high", False), ("gpt-5.6-luna", "high", False)):
                with self.subTest(model=model, effort=effort):
                    health["account_rate_limits"].update(beeper_model=model, beeper_reasoning_effort=effort)
                    (runtime / "health.json").write_text(json.dumps(health), encoding="utf-8")
                    current = subprocess.run([PWSH, "-NoProfile", "-File",
                        str(ROOT / "scripts" / "feishu-codex-operator.ps1"), "operator", "status",
                        "-ProjectRoot", str(project), "-Json"], capture_output=True, text=True, timeout=60)
                    self.assertEqual(0, current.returncode, current.stdout + current.stderr)
                    current_snapshot = json.loads(current.stdout)["health_snapshot"]
                    self.assertEqual(valid, current_snapshot["valid"])
                    if valid:
                        self.assertEqual(model, current_snapshot["account_rate_limits"]["beeper_model"])
                        self.assertEqual(effort, current_snapshot["account_rate_limits"]["beeper_reasoning_effort"])
                    else:
                        self.assertIn("invalid_health_snapshot", json.loads(current.stdout)["issue_codes"])
                    self.assertNotIn("private-fixture-value", current.stdout)
            for name, value in preserved.items():
                self.assertEqual(value, (runtime / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
