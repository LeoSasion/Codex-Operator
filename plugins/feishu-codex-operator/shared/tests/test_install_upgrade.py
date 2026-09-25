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
                for relative in ('operator_web_model.py', 'operator_web_service.py', 'operator_web_acceptance.py', 'operator_web_desktop.py', 'operator_web_entry.ps1', 'web_browser_host.cjs',
                        'web_browser_surface.cjs', 'web_browser_page.cjs',
                        'operator_core/web_browser_session.py',
                        'operator_core/web_openai_tunnel.py',
                        'operator_core/web_responses_provider.py',
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
                    'from operator_core.web_openai_tunnel import WebOpenAITunnel',
                    str(runtime)], cwd=project, capture_output=True, text=True, timeout=20)
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
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
            for name, value in preserved.items():
                self.assertEqual(value, (runtime / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
