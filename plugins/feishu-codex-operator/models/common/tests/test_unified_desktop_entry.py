"""Disposable-only configuration transaction for a unified native picker candidate."""

from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)


import json
import io
import asyncio
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from operator_unified_desktop import (CandidateError, PROVIDER, apply, create_disposable_home,
    prepare, preview, render, revert, status)
import operator_unified_desktop as candidate


BASE = "http://127.0.0.1:4318/" + "a" * 64 + "/backend-api/codex"


class UnifiedDesktopCandidateTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.TemporaryDirectory(prefix="operator-unified-parent-")
        self.addCleanup(self.parent.cleanup)
        self.home = create_disposable_home(Path(self.parent.name))

    def test_preview_is_read_only_and_never_selects_real_codex_home(self):
        original = b'model = "gpt-6-sol"\r\n[features]\r\nplugins = false\r\n'
        (self.home / "config.toml").write_bytes(original)
        expected = preview(self.home, BASE)
        self.assertEqual(expected["status"], "preview")
        self.assertFalse(expected["configuration_changed"])
        self.assertFalse((self.home / candidate.STATE).exists())
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        with self.assertRaisesRegex(CandidateError, "candidate_temp_home_required"):
            preview(Path.home() / ".codex", BASE)
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            with self.assertRaisesRegex(CandidateError, "candidate_real_home_refused"):
                preview(self.home, BASE)

    def test_create_home_rejects_active_codex_parent_before_writing(self):
        parent = Path(self.parent.name)
        before = set(parent.iterdir())
        with patch.dict(os.environ, {"CODEX_HOME": str(parent)}):
            with self.assertRaisesRegex(CandidateError, "candidate_real_home_refused"):
                create_disposable_home(parent)
        self.assertEqual(set(parent.iterdir()), before)

    def test_native_route_marker_blocks_before_any_plan_or_config_write(self):
        original = b'model = "gpt-6-sol"\n'
        (self.home / "config.toml").write_bytes(original)
        (self.home / "operator-native-route-only").write_bytes(b"recovery lock")
        with self.assertRaisesRegex(CandidateError, "candidate_native_route_lock_active"):
            prepare(self.home, BASE)
        self.assertFalse((self.home / candidate.STATE).exists())
        self.assertEqual((self.home / "config.toml").read_bytes(), original)

    def test_provider_and_voice_scope_preserve_existing_independent_provider(self):
        original = (b'model = "gpt-6-sol"\n'
                    b'experimental_realtime_ws_base_url = "https://chatgpt.com/backend-api/codex"\n'
                    b'[model_providers.operator_web_existing]\nname = "Web existing"\n')
        prefix, suffix, rendered = render(original, BASE)
        self.assertIn(b'experimental_realtime_webrtc_call_base_url', prefix)
        self.assertNotIn(b'experimental_realtime_ws_base_url', prefix)
        self.assertIn(b'model_catalog_url', suffix)
        parsed = tomllib.loads(rendered.decode())
        self.assertEqual(parsed["model_provider"], PROVIDER)
        self.assertEqual(parsed["model_providers"][PROVIDER]["name"], "Codex Operator")
        self.assertEqual(parsed["model_providers"]["operator_web_existing"], {"name": "Web existing"})
        self.assertEqual(parsed["model_providers"][PROVIDER]["request_max_retries"], 0)
        self.assertEqual(parsed["model_providers"][PROVIDER]["stream_max_retries"], 0)

    def test_conflicting_routes_and_provider_are_rejected_before_plan(self):
        cases = (
            (b'model_provider = "openai"\n', "candidate_existing_route_conflict"),
            (b'openai_base_url = "https://example.com"\n', "candidate_existing_route_conflict"),
            (b'[model_providers.operator_unified_candidate]\nname = "other"\n', "candidate_provider_collision"),
            (b'experimental_realtime_ws_base_url = "https://other.example"\n',
             "candidate_voice_route_conflict"),
            (b'# BEGIN FEISHU OPERATOR MODEL ROUTER\n', "candidate_existing_managed_block"),
        )
        for original, reason in cases:
            with self.subTest(reason=reason):
                (self.home / "config.toml").write_bytes(original)
                with self.assertRaisesRegex(CandidateError, reason):
                    prepare(self.home, BASE)
                self.assertFalse((self.home / candidate.STATE).exists())

    def test_exact_leading_inert_legacy_block_survives_apply_and_revert(self):
        inert = (b'# BEGIN FEISHU OPERATOR MODEL ROUTER\r\n'
                 b'# openai_base_url = "http://127.0.0.1:4318/' + b'a' * 64 +
                 b'/v1"\r\n# END FEISHU OPERATOR MODEL ROUTER\r\n')
        original = inert + b'model = "gpt-6-sol"\r\n'
        (self.home / "config.toml").write_bytes(original)
        prepare(self.home, BASE)
        apply(self.home)
        self.assertIn(inert, (self.home / "config.toml").read_bytes())
        revert(self.home)
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        with self.assertRaisesRegex(CandidateError, "candidate_existing_managed_block"):
            render(inert + inert + b'model = "gpt-6-sol"\n', BASE)

    def test_bad_route_is_rejected_without_writes(self):
        with self.assertRaisesRegex(CandidateError, "candidate_exact_loopback_route_required"):
            prepare(self.home, "https://example.com/backend-api/codex")
        self.assertFalse((self.home / candidate.STATE).exists())

    def test_cli_preview_and_prepare_use_the_exact_backend_alias(self):
        router_state = Path(self.parent.name) / "router"
        router_state.mkdir()
        (router_state / "token").write_text("a" * 64, encoding="ascii")
        script = _OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_desktop.py"
        common = ["--home", str(self.home), "--router-state", str(router_state),
                  "--port", "4318"]
        for action in ("preview", "prepare"):
            result = subprocess.run([sys.executable, "-B", str(script), action, *common],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], action if action == "preview" else "prepared")
            self.assertNotIn("a" * 64, result.stdout)
        installed = tomllib.loads((self.home / candidate.STATE / "candidate.toml").read_text())
        self.assertEqual(installed["model_providers"][PROVIDER]["base_url"], BASE)
        self.assertFalse((self.home / "config.toml").exists())

    def test_apply_and_revert_preserve_later_unrelated_table_and_cache_backups(self):
        original = b'model = "gpt-6-sol"\r\n[features]\r\nplugins = false\r\n'
        (self.home / "config.toml").write_bytes(original)
        (self.home / "models_cache.json").write_bytes(b"original catalog")
        self.assertEqual(prepare(self.home, BASE)["status"], "prepared")
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        self.assertEqual(apply(self.home)["status"], "active")
        state = self.home / candidate.STATE
        self.assertEqual((state / "cache-retired.bin").read_bytes(), b"original catalog")
        self.assertFalse((self.home / "models_cache.json").exists())
        self.assertTrue(status(self.home)["configuration_matches_original_candidate"])
        (self.home / "models_cache.json").write_bytes(b"new catalog")
        later = b'\r\n[analytics]\r\nenabled = false\r\n'
        config = self.home / "config.toml"
        config.write_bytes(config.read_bytes() + later)
        self.assertEqual(revert(self.home)["status"], "reverted")
        self.assertEqual(config.read_bytes(), original + later)
        self.assertEqual((state / "cache-after-retired.bin").read_bytes(), b"new catalog")
        self.assertFalse((self.home / "models_cache.json").exists())
        with self.assertRaisesRegex(CandidateError, "candidate_transaction_requires_review"):
            apply(self.home)

    def test_original_missing_config_is_missing_after_revert(self):
        self.assertFalse((self.home / "config.toml").exists())
        prepare(self.home, BASE)
        apply(self.home)
        self.assertTrue((self.home / "config.toml").exists())
        outcome = revert(self.home)
        self.assertTrue(outcome["original_absence_restored"])
        self.assertFalse((self.home / "config.toml").exists())

    def test_legacy_openai_named_transaction_remains_recoverable(self):
        original = b'model = "gpt-6-sol"\n'
        (self.home / "config.toml").write_bytes(original)
        legacy = {**candidate._provider(BASE), "name": "OpenAI"}
        with patch.object(candidate, "_provider", return_value=legacy):
            prepare(self.home, BASE)
            apply(self.home)
        self.assertEqual(status(self.home)["status"], "active")
        self.assertEqual(revert(self.home)["status"], "reverted")
        self.assertEqual((self.home / "config.toml").read_bytes(), original)

    def test_native_only_marker_added_after_apply_does_not_block_revert(self):
        prepare(self.home, BASE)
        apply(self.home)
        (self.home / "operator-native-route-only").write_bytes(b"native recovery")
        self.assertEqual(status(self.home)["status"], "active")
        self.assertEqual(revert(self.home)["status"], "reverted")
        self.assertFalse((self.home / "config.toml").exists())
        with self.assertRaisesRegex(CandidateError, "candidate_native_route_lock_active"):
            prepare(self.home, BASE)

    def test_changed_managed_provider_refuses_revert_without_overwriting(self):
        prepare(self.home, BASE)
        apply(self.home)
        path = self.home / "config.toml"
        changed = path.read_bytes().replace(b'name = "Codex Operator"', b'name = "Other"')
        path.write_bytes(changed)
        with self.assertRaisesRegex(CandidateError, "candidate_owned_bytes_changed"):
            revert(self.home)
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(status(self.home)["status"], "active")

    def test_failed_apply_is_terminal_and_retains_original_and_plan(self):
        original = b'model = "gpt-6-sol"\n'
        (self.home / "config.toml").write_bytes(original)
        prepare(self.home, BASE)
        real_write = candidate._atomic_write

        def fail_config(path, replacement, *, expected):
            if path == self.home / "config.toml":
                raise OSError("synthetic write failure")
            return real_write(path, replacement, expected=expected)

        with patch.object(candidate, "_atomic_write", side_effect=fail_config):
            with self.assertRaises(OSError):
                apply(self.home)
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        self.assertEqual(status(self.home)["status"], "applying")
        with self.assertRaisesRegex(CandidateError, "candidate_transaction_requires_review"):
            apply(self.home)
        with self.assertRaisesRegex(CandidateError, "candidate_transaction_requires_review"):
            revert(self.home)

    def test_cache_created_during_apply_cannot_be_reported_active(self):
        prepare(self.home, BASE)
        real_journal = candidate._journal

        def create_cache_after_snapshot(state, phase, **extra):
            real_journal(state, phase, **extra)
            if phase == "applying":
                (self.home / "models_cache.json").write_bytes(b"concurrent catalog")

        with patch.object(candidate, "_journal", side_effect=create_cache_after_snapshot):
            with self.assertRaisesRegex(CandidateError, "candidate_cache_changed"):
                apply(self.home)
        self.assertEqual(status(self.home)["status"], "applying")
        self.assertEqual((self.home / "models_cache.json").read_bytes(), b"concurrent catalog")

    def test_parallel_apply_cannot_clobber_active_journal(self):
        prepare(self.home, BASE)
        entered, release = threading.Event(), threading.Event()
        errors = []
        real_load = candidate._load

        def pause_first(home, *, allow_locked=False):
            if threading.current_thread().name == "first-candidate-apply":
                entered.set()
                if not release.wait(5):
                    raise AssertionError("candidate concurrency fixture timed out")
            return real_load(home, allow_locked=allow_locked)

        def first_apply():
            try:
                apply(self.home)
            except Exception as exc:
                errors.append(exc)

        with patch.object(candidate, "_load", side_effect=pause_first):
            thread = threading.Thread(target=first_apply, name="first-candidate-apply")
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(CandidateError, "candidate_transaction_locked"):
                    apply(self.home)
            finally:
                release.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(status(self.home)["status"], "active")

    def test_post_write_failure_remains_uncertain_and_cli_never_claims_no_change(self):
        prepare(self.home, BASE)
        actual_journal = candidate._journal

        def fail_final_journal(state, phase, **extra):
            if phase == "active":
                raise OSError("synthetic final journal failure")
            return actual_journal(state, phase, **extra)

        with patch.object(candidate, "_journal", side_effect=fail_final_journal):
            with self.assertRaises(OSError):
                apply(self.home)
        self.assertTrue((self.home / "config.toml").exists())
        self.assertEqual(status(self.home)["status"], "applying")
        with self.assertRaisesRegex(CandidateError, "candidate_transaction_requires_review"):
            apply(self.home)
        output = io.StringIO()
        with patch.object(candidate, "apply", side_effect=OSError("synthetic")), \
                patch.object(sys, "argv", [str(_OPERATOR_PLUGIN_ROOT / "scripts/operator_unified_desktop.py"),
                                           "apply", "--home", str(self.home)]), redirect_stdout(output):
            self.assertEqual(candidate.main(), 1)
        report = json.loads(output.getvalue())
        self.assertIsNone(report["configuration_changed"])

    def test_plan_tamper_blocks_apply(self):
        prepare(self.home, BASE)
        path = self.home / candidate.STATE / "candidate.toml"
        path.write_bytes(path.read_bytes() + b"\n# tamper\n")
        with self.assertRaisesRegex(CandidateError, "candidate_plan_invalid"):
            apply(self.home)
        self.assertFalse((self.home / "config.toml").exists())


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI"), "explicit current CLI required")
class AppliedCandidateCliCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_config_loads_both_native_and_web_rows_without_a_model_turn(self):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        token = "a" * 64
        api_key = "synthetic-unified-candidate-key"
        template = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0]
        native = deepcopy(template)
        native.update(slug="gpt-6-sol", display_name="Synthetic native", comp_hash="synthetic-native")
        web = deepcopy(template)
        web.update(slug="api/chatgpt-web/gpt-5.6-sol", display_name="Synthetic Web",
                   comp_hash="synthetic-web")
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append((self.path, self.headers.get("Authorization")))
                if self.path.split("?", 1)[0] != f"/{token}/backend-api/codex/models":
                    self.send_error(404)
                    return
                body = json.dumps({"models": [native, web]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 2
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        child = None
        try:
            with tempfile.TemporaryDirectory(prefix="operator-unified-cli-") as parent:
                home = create_disposable_home(Path(parent))
                work = Path(parent) / "work"
                work.mkdir()
                (home / "config.toml").write_text(
                    'model = "gpt-6-sol"\n[features]\napi_key_model_discovery = true\n'
                    'plugins = false\nremote_plugin = false\n[analytics]\nenabled = false\n', encoding="utf-8")
                base = f"http://127.0.0.1:{server.server_address[1]}/{token}/backend-api/codex"
                prepare(home, base)
                apply(home)
                environment = {key: value for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
                        "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                        "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}}
                environment.update(CODEX_HOME=str(home),
                    HTTP_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
                    HTTPS_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
                    ALL_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
                    NO_PROXY="127.0.0.1,localhost,::1")
                flags = 0x08000000 if os.name == "nt" else 0
                login = subprocess.run([str(executable), "login", "--with-api-key"],
                    input=api_key + "\n", text=True, cwd=work, env=environment,
                    capture_output=True, timeout=10, creationflags=flags)
                self.assertEqual(login.returncode, 0, "synthetic key login failed in disposable home")
                child = await asyncio.create_subprocess_exec(str(executable), "app-server", "--listen", "stdio://",
                    cwd=str(work), env=environment, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    creationflags=flags)

                async def request(request_id, method, params):
                    child.stdin.write((json.dumps({"jsonrpc": "2.0", "id": request_id,
                        "method": method, "params": params}, separators=(",", ":")) + "\n").encode())
                    await child.stdin.drain()
                    for _ in range(100):
                        line = await asyncio.wait_for(child.stdout.readline(), timeout=30)
                        self.assertTrue(line, f"isolated App Server exited during {method}")
                        message = json.loads(line)
                        if message.get("id") == request_id:
                            self.assertNotIn("error", message, (method, message))
                            return message["result"]
                    self.fail(f"isolated App Server did not answer {method}")

                await request(1, "initialize", {"clientInfo": {"name": "operator_unified_candidate",
                    "title": "Unified candidate catalog", "version": "1"}})
                child.stdin.write(b'{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
                await child.stdin.drain()
                configuration = await request(2, "config/read", {"includeLayers": False})
                self.assertEqual(configuration["config"]["model_provider"], PROVIDER)
                listed = await request(3, "model/list", {"includeHidden": False, "limit": 100})
                names = [row.get("model") for row in listed["data"]]
                self.assertIn("gpt-6-sol", names)
                self.assertIn("api/chatgpt-web/gpt-5.6-sol", names)
                self.assertTrue(observed)
                self.assertTrue(all(path.split("?", 1)[0] == f"/{token}/backend-api/codex/models"
                    and auth == "Bearer " + api_key for path, auth in observed), observed)
                child.terminate()
                await asyncio.wait_for(child.wait(), timeout=5)
                child = None
                self.assertEqual(revert(home)["status"], "reverted")
        finally:
            if child is not None and child.returncode is None:
                child.terminate()
                try:
                    await asyncio.wait_for(child.wait(), timeout=5)
                except asyncio.TimeoutError:
                    child.kill()
                    await child.wait()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
