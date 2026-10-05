"""Disposable fixture verification and real CLI/fake model evaluation contracts."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import asyncio
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_responses_tools import ROUTE
from test_responses_events import events_for, wire
import operator_responses_eval as evaluator_module
from operator_responses_eval import (
    EXPECTED, SOURCE, STOP_CASES, Fixture, evaluate, isolated_environment, verify_final_message,
    prompt_for, json_output_summary, cancellation_observed, parse_cli_version,
    collect_child, child_output_observation,
)
from operator_core.responses_tool_adapter import dumps, tool_alias


# Native CLI tools unrelated to this synthetic MCP fixture, including names
# exposed inside code-mode discovery rather than the upstream tool declaration.
UNRELATED_FIXTURE_TOOLS = (
    "exec_command", "write_stdin", "view_image", "image_generation", "imagegen",
    "get_goal", "create_goal", "update_goal", "spawn_agent", "send_input",
    "resume_agent", "close_agent", "followup_task", "interrupt_agent",
    "list_agents", "send_message", "wait_agent", "spawn_agents_on_csv",
    "report_agent_job_result",
)


class EvalFixtureTests(unittest.TestCase):
    def test_cli_version_preserves_prerelease_identity_and_rejects_invalid_output(self):
        from operator_core.responses_capabilities import RouterError
        for version in ('0.153.4', '0.154.0-alpha.6.2', '1.2.3-rc.1+build.42'):
            for ending in (b'', b'\n', b'\r\n'):
                self.assertEqual(parse_cli_version(b'codex-cli '+version.encode()+ending, 0), version)
        for output in (b'codex-cli none', b'codex-cli 0.154.0-alpha..6', b'codex-cli 0.154.0-',
                       b'codex-cli 0.154.0\nextra', b' codex-cli 0.154.0', b'codex-cli 0.154.0 alpha.6',
                       b'codex-cli 0.154.0-\xff', b'codex-cli 0.154.0-'+b'a'*81):
            with self.subTest(output=output), self.assertRaisesRegex(RouterError, 'explicit_cli_version_unavailable'):
                parse_cli_version(output, 0)
        with self.assertRaises(RouterError):
            parse_cli_version(b'codex-cli 0.154.0-alpha.6.2\n', 1)

    def test_cancel_requires_cancelled_dispatch_and_outcome_not_just_inactivity(self):
        dispatches = [{"transport_result": "cancelled", "request_body_write_started": True}]
        outcomes = {"cancelled": 1, "completed": 0, "failed": 0}
        self.assertTrue(cancellation_observed(True, 0, 1, dispatches, outcomes))
        for field, value in (("transport_result", "returned"), ("transport_result", "raised"),
                             ("request_body_write_started", False)):
            self.assertFalse(cancellation_observed(True, 0, 1, [{**dispatches[0], field: value}], outcomes))
        for outcome in ("completed", "failed"):
            self.assertFalse(cancellation_observed(True, 0, 1, dispatches,
                             {**outcomes, "cancelled": 0, outcome: 1}))
        for was_active, active, requests in ((False, 0, 1), (True, 1, 1), (True, 0, 2)):
            self.assertFalse(cancellation_observed(was_active, active, requests, dispatches, outcomes))

    def test_json_diagnostics_retain_only_fixed_counts(self):
        value = {"output": [{"type": kind, "name": "PRIVATE_TOOL_NAME", "id": "PRIVATE_ID",
                  "arguments": "PRIVATE_ARGUMENTS", "content": [{"text": "PRIVATE_TEXT"}]}
                 for kind in ("message", "reasoning", "custom_tool_call", "function_call", "PROVIDER_DEFINED_TYPE")]}
        before = deepcopy(value)
        summary = json_output_summary(value)
        self.assertEqual(summary, {"scope": "validated_json_snapshot_not_call_release",
            "output_counts": {"message": 1, "reasoning": 1, "function_call": 1, "custom_tool_call": 1, "other": 1}})
        self.assertEqual(value, before)

    def test_marker_line_policy_is_bounded_and_preserves_exact_bytes(self):
        from operator_core.responses_capabilities import RouterError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.txt"
            self.assertFalse(verify_final_message(path, "TOKEN", "marker_line_v1")["verification_accepted"])
            for value, accepted in (("TOKEN", True), ("\n\nTOKEN", True), ("\r\nTOKEN\r\n", True),
                    ("\n" * 8 + "TOKEN" + "\n" * 8, True), ("\n" * 9 + "TOKEN", False),
                    (" TOKEN", False), ("TOKEN\t", False), ("\rTOKEN", False),
                    ("TOKEN\u00a0", False), ("TOKEN\nexplanation", False), ("TO\nKEN", False),
                    ("TOKEN\nTOKEN", False), ("\ufeffTOKEN", False)):
                with self.subTest(value=value):
                    path.write_bytes(value.encode("utf-8"))
                    report = verify_final_message(path, "TOKEN", "marker_line_v1")
                    self.assertEqual(report["verification_accepted"], accepted)
                    self.assertEqual(report["verification_exact"], value == "TOKEN")
                    self.assertEqual(path.read_bytes(), value.encode("utf-8"))
            with self.assertRaises(RouterError):
                verify_final_message(path, "TOKEN", "trim_everything")
        self.assertNotIn("eight empty", prompt_for("cli_nested"))
        self.assertIn("eight empty", prompt_for("cli_nested", "marker_line_v1"))

    def test_mcp_stdio_is_utf8_even_with_legacy_windows_encoding(self):
        import subprocess
        import sys
        import operator_responses_eval as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work").mkdir()
            (root / "work/currency.py").write_bytes(SOURCE.encode("utf-8"))
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "fixture_step", "arguments": {"action": "read"}}}
            result = subprocess.run([sys.executable, module.__file__, "fixture", "--fixture-root", str(root),
                "--case", "cli_patchplan"], input=(dumps(request) + "\n").encode("utf-8"), capture_output=True,
                env={**os.environ, "PYTHONIOENCODING": "gbk"}, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["result"]["content"][0]["text"], SOURCE)

    def test_file_patch_preserves_all_other_bytes_and_does_not_execute_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "work").mkdir()
            path = root / "work/currency.py"
            path.write_bytes(SOURCE.encode())
            fixture = Fixture(root, "cli_workspace")
            self.assertTrue(fixture.call({"action": "verify"})["isError"])
            self.assertEqual(fixture.call({"action": "read"})["content"][0]["text"], SOURCE)
            self.assertFalse(fixture.call({"action": "replace", "old": "* 10)", "new": "* 100)"})["isError"])
            self.assertFalse(fixture.call({"action": "verify"})["isError"])
            self.assertEqual(path.read_bytes(), EXPECTED.encode())

    def test_error_requires_exact_returned_recovery_value(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory), "cli_tool_error")
            result = fixture.call({"action": "fail"})
            self.assertTrue(result["isError"])
            self.assertTrue(fixture.call({"action": "recover", "value": "guessed"})["isError"])
            self.assertFalse(fixture.call({"action": "recover", "value": fixture.challenge})["isError"])

    def test_cli_child_receives_no_inference_credentials(self):
        with patch.dict(os.environ, {"UNRELATED_API_KEY": "secret", "ACCESS_TOKEN": "secret", "GLM_API_KEY": "secret"}):
            environment = isolated_environment(Path("synthetic-home"))
        for name in ("UNRELATED_API_KEY", "ACCESS_TOKEN", "GLM_API_KEY"):
            self.assertNotIn(name, environment)

    def test_stop_fixtures_refuse_recovery_and_preserve_source(self):
        for case in STOP_CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "untouched.py"
                source.write_bytes(SOURCE.encode("utf-8"))
                fixture = Fixture(root, case)
                result = fixture.call({"action": "fail"})
                self.assertEqual(result["isError"], case == "cli_error_stop")
                failure = json.loads(result["content"][0]["text"])
                self.assertEqual(failure["error"], "synthetic_expected_error")
                if case == "cli_exit_stop":
                    self.assertEqual(failure["exit_code"], 1)
                self.assertTrue(fixture.call({"action": "recover", "value": fixture.challenge})["isError"])
                self.assertTrue(fixture.call({"action": "fail"})["isError"])
                audit = [json.loads(line) for line in (root / "fixture-audit.jsonl").read_text().splitlines()]
                self.assertEqual([r["accepted"] for r in audit], [True, False, False])
                self.assertEqual(source.read_bytes(), SOURCE.encode("utf-8"))
                self.assertEqual((root / "expected-marker").read_text(),
                                 "STOPPED synthetic_expected_error " + failure["marker"])

    def test_exact_verification_does_not_hide_whitespace_or_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.txt"
            self.assertFalse(verify_final_message(path, "TOKEN")["verification_exact"])
            for value in ("TOKEN", "\n\nTOKEN", "TOKEN\n", " TOKEN ", "WRONG"):
                with self.subTest(value=value):
                    path.write_bytes(value.encode("utf-8"))
                    report = verify_final_message(path, "TOKEN")
                    self.assertEqual(report["verification_exact"], value == "TOKEN")
                    self.assertEqual(report["verification_matched_after_trim"], value.strip() == "TOKEN")
                    self.assertEqual(path.read_bytes(), value.encode("utf-8"))
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                verify_final_message(path, "TOKEN")


class ObservedStreamReader(asyncio.StreamReader):
    """Exercise real in-memory streams and observe reads without another consumer."""
    def __init__(self):
        super().__init__()
        self.read_calls = self.active_reads = self.max_active_reads = 0
        self.data_observed = asyncio.Event()

    async def read(self, size):
        self.read_calls += 1
        self.active_reads += 1
        self.max_active_reads = max(self.max_active_reads, self.active_reads)
        try:
            value = await super().read(size)
            if value:
                self.data_observed.set()
            return value
        finally:
            self.active_reads -= 1


def observed_reader(data=b"", *, eof=False):
    reader = ObservedStreamReader()
    if data:
        reader.feed_data(data)
    if eof:
        reader.feed_eof()
    return reader


class FixtureChild:
    """Process boundary fixture only; never starts a native executable."""
    def __init__(self, stdout, stderr, *, exited=False):
        self.stdout, self.stderr = stdout, stderr
        self.returncode = 0 if exited else None
        self.kill_calls = 0
        self.exit = asyncio.Event()
        if exited:
            self.exit.set()

    async def wait(self):
        await self.exit.wait()
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self.exit.set()


class FixtureEvaluationRouter:
    def __init__(self, registry, token):
        self.registry, self.last_failure, self.prefix = registry, None, "/fixture"
        self.metrics = SimpleNamespace(stages={}, snapshot=lambda: {})

    def app(self):
        return SimpleNamespace(middlewares=[])


class FixtureEvaluationRunner:
    def __init__(self, *args, **kwargs):
        self.addresses = [("127.0.0.1", 1)]

    async def setup(self):
        pass

    async def cleanup(self):
        pass


class FixtureEvaluationSite:
    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        pass


class CliOutputObservationTests(unittest.IsolatedAsyncioTestCase):
    def assert_summary(self, observation, name, data, complete):
        self.assertEqual(observation[name]["observed_bytes"], len(data))
        self.assertEqual(observation[name]["observed_prefix_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(observation[name]["complete"], complete)

    async def timeout_after_data(self, child, observation):
        task = asyncio.create_task(collect_child(child, observation=observation))
        await asyncio.wait_for(asyncio.gather(child.stdout.data_observed.wait(),
                                             child.stderr.data_observed.wait()), 1)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(task, 0.01)

    async def evaluate_without_process_or_service(self, case, child, *, row=None, terminal_shell=None):
        from aiohttp import web
        import operator_core.model_router as router_module
        async def spawn(*args, **kwargs):
            return child
        with patch.object(evaluator_module, "preflight", return_value=None), \
             patch.object(evaluator_module.subprocess, "run", return_value=SimpleNamespace(
                 stdout=b"codex-cli 0.160.0\n", returncode=0)), \
             patch.object(evaluator_module.asyncio, "create_subprocess_exec", spawn), \
             patch.object(router_module, "ModelRouter", FixtureEvaluationRouter), \
             patch.object(web, "AppRunner", FixtureEvaluationRunner), \
             patch.object(web, "TCPSite", FixtureEvaluationSite):
            return await evaluate(deepcopy(ROUTE if row is None else row), case,
                Path("fixture-never-executed.exe"), timeout=0.03, terminal_shell=terminal_shell)

    async def test_timeout_retains_bounded_hashes_without_second_stream_reader(self):
        observation = child_output_observation()
        child = FixtureChild(observed_reader(b"PRIVATE_STDOUT"), observed_reader(b"PRIVATE_STDERR"))
        await self.timeout_after_data(child, observation)
        self.assert_summary(observation, "stdout", b"PRIVATE_STDOUT", False)
        self.assert_summary(observation, "stderr", b"PRIVATE_STDERR", False)
        reads = (child.stdout.read_calls, child.stderr.read_calls)
        child.kill()
        await child.wait()
        await asyncio.sleep(0)
        self.assertEqual(reads, (child.stdout.read_calls, child.stderr.read_calls))
        self.assertEqual((child.stdout.max_active_reads, child.stderr.max_active_reads), (1, 1))
        self.assertNotIn("PRIVATE_", json.dumps(observation))

    async def test_eof_complete_is_independent_of_other_stream_and_process_exit(self):
        observation = child_output_observation()
        child = FixtureChild(observed_reader(eof=True), observed_reader(b"partial"))
        task = asyncio.create_task(collect_child(child, observation=observation))
        await asyncio.wait_for(child.stderr.data_observed.wait(), 1)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(task, 0.01)
        self.assert_summary(observation, "stdout", b"", True)
        self.assert_summary(observation, "stderr", b"partial", False)
        self.assertIsNone(child.returncode)

    async def test_success_preserves_raw_bytes_and_existing_tuple_interface(self):
        values = (b" \r\n\xffstdout\n", b"\x00stderr\r\n")
        observation = child_output_observation()
        child = FixtureChild(observed_reader(values[0], eof=True), observed_reader(values[1], eof=True), exited=True)
        self.assertEqual(await collect_child(child, observation=observation), values)
        self.assert_summary(observation, "stdout", values[0], True)
        self.assert_summary(observation, "stderr", values[1], True)
        other = FixtureChild(observed_reader(b"a", eof=True), observed_reader(b"b", eof=True), exited=True)
        self.assertEqual(await collect_child(other), (b"a", b"b"))

    async def test_16_MiB_boundary_rejects_next_byte_without_expanding_diagnostics(self):
        from operator_core.responses_capabilities import RouterError
        raw = b"x" * (16 * 1024 * 1024)
        observation = child_output_observation()
        child = FixtureChild(observed_reader(raw, eof=True), observed_reader(eof=True), exited=True)
        self.assertEqual(await collect_child(child, observation=observation), (raw, b""))
        self.assert_summary(observation, "stdout", raw, True)
        overflow = child_output_observation()
        child = FixtureChild(observed_reader(raw + b"y", eof=True), observed_reader(eof=True), exited=True)
        with self.assertRaisesRegex(RouterError, "evaluation_cli_output_too_large"):
            await collect_child(child, observation=overflow)
        self.assert_summary(overflow, "stdout", raw, False)
        self.assertTrue(overflow["stdout"]["output_limit_exceeded"])

    async def test_reader_failure_preserves_peer_observation_and_cancels_pending_readers(self):
        observation = child_output_observation()
        child = FixtureChild(observed_reader(b"observed"), observed_reader(b"other"))
        task = asyncio.create_task(collect_child(child, observation=observation))
        await asyncio.wait_for(asyncio.gather(child.stdout.data_observed.wait(),
                                             child.stderr.data_observed.wait()), 1)
        child.stdout.set_exception(OSError("synthetic read failure"))
        with self.assertRaises(OSError):
            await task
        self.assert_summary(observation, "stdout", b"observed", False)
        self.assert_summary(observation, "stderr", b"other", False)
        self.assertEqual((child.stdout.active_reads, child.stderr.active_reads), (0, 0))

    async def test_evaluate_timeout_keeps_failure_and_budget_and_records_actual_postkill_exit(self):
        child = FixtureChild(observed_reader(b"observed-out"), observed_reader(b"observed-err"))
        report = await self.evaluate_without_process_or_service("cli_nested", child)
        self.assertEqual((report["status"], report["error_category"], report["exit_code"]), ("failed", "timeout", -9))
        self.assertEqual(report["cli_process"], {"started": True, "kill_requested_by_harness": True, "exit_observed": True})
        self.assertEqual((report["requests"], report["upstream_dispatch_attempts"], report["request_limit"]), (0, 0, 2))
        self.assert_summary(report["cli_output"], "stdout", b"observed-out", False)
        self.assert_summary(report["cli_output"], "stderr", b"observed-err", False)
        self.assertEqual(child.kill_calls, 1)

    async def test_cancel_case_timeout_never_becomes_successful_cancellation(self):
        child = FixtureChild(observed_reader(b"observed"), observed_reader())
        report = await self.evaluate_without_process_or_service("cli_cancel", child)
        self.assertEqual((report["status"], report["error_category"], report["exit_code"]), ("failed", "timeout", -9))
        self.assertFalse(report.get("cancel_observed", False))
        self.assertEqual((report["requests"], report["upstream_dispatch_attempts"], report["request_limit"]), (0, 0, 1))


class CleanupFixtureChild(FixtureChild):
    """Configurable in-memory process boundary; no native command is executed."""
    def __init__(self, *, kill_mode="exit", wait_error=None, stdout=None):
        super().__init__(stdout or observed_reader(b"observed-out"), observed_reader(b"observed-err"))
        self.kill_mode, self.wait_error = kill_mode, wait_error

    def kill(self):
        self.kill_calls += 1
        if self.kill_mode == "exit":
            self.returncode = -9
            self.exit.set()
        elif self.kill_mode == "lookup_observed":
            self.returncode = 0
            self.exit.set()
            raise ProcessLookupError("PRIVATE_PROCESS_LOOKUP")
        elif self.kill_mode == "lookup_unknown":
            raise ProcessLookupError("PRIVATE_PROCESS_LOOKUP")
        elif self.kill_mode == "denied":
            raise PermissionError("PRIVATE_KILL_DENIAL")
        elif self.kill_mode == "wait_unknown":
            self.exit.set()
        elif self.kill_mode != "request_only":
            raise AssertionError("invalid_fake_kill_mode")

    async def wait(self):
        await self.exit.wait()
        if self.wait_error is not None:
            raise self.wait_error
        return 0 if self.returncode is None else self.returncode


class DelayedCancelReader(ObservedStreamReader):
    """One explicit release keeps this exceptional fake from leaking into teardown."""
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()
        self.feed_data(b"observed-delayed")

    async def read(self, size):
        try:
            return await super().read(size)
        except asyncio.CancelledError:
            await self.release.wait()
            return b""


class CliCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, child, *, runner_error=None):
        from unittest.mock import AsyncMock
        cleanup = AsyncMock(side_effect=runner_error)
        with patch.object(evaluator_module, "CLI_CLEANUP_TIMEOUT_SECONDS", 0.02), \
             patch.object(FixtureEvaluationRunner, "cleanup", cleanup):
            report = await CliOutputObservationTests.evaluate_without_process_or_service(self, "cli_nested", child)
        self.assertEqual(cleanup.await_count, 1)
        self.assertEqual((report["status"], report["error_category"], report["request_limit"]), ("failed", "timeout", 2))
        self.assertEqual((report["requests"], report["upstream_dispatch_attempts"], report["configured_retry_count"]), (0, 0, 0))
        self.assertNotIn("PRIVATE_", json.dumps(report))
        if report.get("fixture_retained"):
            paths = report["retained_fixture_paths"]
            root, work = Path(paths["root"]), Path(paths["work"])
            if work.parent != root and work.exists():
                self.addCleanup(evaluator_module._remove_fixture_directory, work, work.parent)
            self.addCleanup(evaluator_module._remove_fixture_directory, root, root.parent)
        return report

    async def test_successful_kill_records_observed_exit_and_keeps_timeout_failed(self):
        child = CleanupFixtureChild()
        report = await self.run_fixture(child)
        self.assertEqual(report["exit_code"], -9)
        self.assertEqual(report["cli_process"], {"started": True, "kill_requested_by_harness": True, "exit_observed": True})
        self.assertEqual((report["cli_cleanup"]["kill_result"], report["cli_cleanup"]["wait_result"]), ("requested", "exit_observed"))
        self.assertFalse(report["cli_cleanup"]["failed"])
        self.assertFalse(report.get("fixture_retained", False))
        self.assertEqual((child.stdout.active_reads, child.stderr.active_reads), (0, 0))

    async def test_lookup_error_with_observed_exit_preserves_actual_code_and_failed_report(self):
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="lookup_observed"))
        self.assertEqual(report["exit_code"], 0)
        self.assertTrue(report["cli_process"]["exit_observed"])
        self.assertEqual(report["cli_cleanup"]["kill_result"], "process_lookup_error")
        self.assertTrue(report["cleanup_failed"])

    async def test_lookup_error_without_exit_retains_unknown_and_fixture_after_gc(self):
        import gc
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="lookup_unknown"))
        self.assertIsNone(report["exit_code"])
        self.assertFalse(report["cli_process"]["exit_observed"])
        self.assertEqual(report["cli_cleanup"]["wait_result"], "timeout")
        gc.collect()
        self.assertTrue(all(Path(value).is_dir() for value in report["retained_fixture_paths"].values()))

    async def test_os_error_denial_does_not_skip_output_runner_or_private_report(self):
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="denied"))
        self.assertEqual(report["cli_cleanup"]["kill_result"], "os_error")
        self.assertEqual(report["cli_cleanup"]["runner_result"], "completed")
        self.assertTrue(report["fixture_retained"])
        self.assertEqual(report["cli_output"]["stdout"]["observed_prefix_sha256"], hashlib.sha256(b"observed-out").hexdigest())

    async def test_kill_request_without_exit_has_shared_bounded_wait_and_no_inferred_code(self):
        import time
        begin = time.monotonic()
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="request_only"))
        self.assertLess(time.monotonic() - begin, 0.5)
        self.assertIsNone(report["exit_code"])
        self.assertTrue(report["cli_process"]["kill_requested_by_harness"])
        self.assertFalse(report["cli_process"]["exit_observed"])
        self.assertEqual(report["cli_cleanup"]["wait_result"], "timeout")

    async def test_wait_value_without_observed_returncode_remains_unknown_and_failed(self):
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="wait_unknown"))
        self.assertIsNone(report["exit_code"])
        self.assertEqual(report["cli_cleanup"]["wait_result"], "exit_unobserved")
        self.assertTrue(report["fixture_retained"])

    async def test_wait_os_error_is_fixed_and_keeps_report_and_unknown_exit(self):
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="wait_unknown", wait_error=PermissionError("PRIVATE_WAIT_DENIAL")))
        self.assertIsNone(report["exit_code"])
        self.assertEqual(report["cli_cleanup"]["wait_result"], "os_error")
        self.assertEqual(report["cli_cleanup"]["runner_result"], "completed")

    async def test_wait_task_cancel_is_fixed_failure_and_does_not_drop_report(self):
        report = await self.run_fixture(CleanupFixtureChild(kill_mode="wait_unknown", wait_error=asyncio.CancelledError()))
        self.assertEqual(report["cli_cleanup"]["wait_result"], "cancelled")
        self.assertIsNone(report["exit_code"])

    async def test_pending_output_cancel_is_bounded_and_diagnostic_snapshot_cannot_change(self):
        reader = DelayedCancelReader()
        child = CleanupFixtureChild(stdout=reader)
        try:
            report = await self.run_fixture(child)
            snapshot = deepcopy(report["cli_output"])
            self.assertGreater(report["cli_cleanup"]["reader_pending_tasks"], 0)
            self.assertTrue(report["fixture_retained"])
            self.assertFalse(report["cli_output"]["stdout"]["complete"])
        finally:
            reader.release.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertEqual(report["cli_output"], snapshot)

    async def test_runner_error_keeps_prior_failure_evidence_and_private_fixture(self):
        report = await self.run_fixture(CleanupFixtureChild(), runner_error=OSError("PRIVATE_RUNNER_ERROR"))
        self.assertEqual(report["exit_code"], -9)
        self.assertEqual(report["cli_cleanup"]["runner_result"], "error")
        self.assertTrue(report["cleanup_failed"])
        self.assertTrue(report["fixture_retained"])

    async def test_runner_self_cancel_is_fixed_failure_and_keeps_report(self):
        report = await self.run_fixture(CleanupFixtureChild(), runner_error=asyncio.CancelledError())
        self.assertEqual(report["cli_cleanup"]["runner_result"], "cancelled")
        self.assertTrue(report["cleanup_failed"])
        self.assertEqual(report["exit_code"], -9)

    async def test_parent_evaluate_cancel_stays_cancelled_and_still_cleans_child_and_runner(self):
        from unittest.mock import AsyncMock
        child = CleanupFixtureChild()
        cleanup = AsyncMock()
        with patch.object(FixtureEvaluationRunner, "cleanup", cleanup):
            task = asyncio.create_task(CliOutputObservationTests.evaluate_without_process_or_service(self, "cli_nested", child))
            await asyncio.wait_for(asyncio.gather(child.stdout.data_observed.wait(), child.stderr.data_observed.wait()), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
        self.assertEqual((child.kill_calls, child.returncode, cleanup.await_count), (1, -9, 1))

    async def test_primary_collector_child_self_cancel_returns_fixed_failed_report(self):
        from unittest.mock import AsyncMock
        class Child(CleanupFixtureChild):
            async def wait(self):
                if self.kill_calls == 0:
                    raise asyncio.CancelledError
                return await super().wait()
        cleanup = AsyncMock()
        with patch.object(FixtureEvaluationRunner, "cleanup", cleanup), \
             patch.object(evaluator_module, "CLI_CLEANUP_TIMEOUT_SECONDS", 0.02):
            report = await CliOutputObservationTests.evaluate_without_process_or_service(self,
                "cli_nested", Child(kill_mode="request_only"))
        self.assertEqual((report["status"], report["error_category"]), ("failed", "harness_error"))
        self.assertEqual(report["cli_output"]["collection_error"], "evaluation_cli_output_task_cancelled")
        self.assertEqual((report["requests"], report["upstream_dispatch_attempts"], report["request_limit"]), (0, 0, 2))
        self.assertEqual((report["exit_code"], cleanup.await_count), (None, 1))
        self.assertTrue(report["fixture_retained"])
        root = Path(report["retained_fixture_paths"]["root"])
        self.addCleanup(evaluator_module._remove_fixture_directory, root, root.parent)
        self.assertNotIn("PRIVATE_", json.dumps(report))

    async def test_cleanup_fence_rejects_late_request_without_handler_or_upstream(self):
        from unittest.mock import AsyncMock
        captured = {}
        initial = FixtureEvaluationRunner.__init__
        def capture(runner, app, **kwargs):
            initial(runner, app, **kwargs)
            captured["app"] = app
        handler = AsyncMock()
        async def cleanup(runner):
            response = await captured["app"].middlewares[0](SimpleNamespace(path="/fixture/responses"), handler)
            self.assertEqual((response.status, json.loads(response.text)), (400, {"error": "cleanup_started_no_retry"}))
        with patch.object(FixtureEvaluationRunner, "__init__", capture), \
             patch.object(FixtureEvaluationRunner, "cleanup", cleanup), \
             patch.object(evaluator_module, "CLI_CLEANUP_TIMEOUT_SECONDS", 0.02):
            report = await CliOutputObservationTests.evaluate_without_process_or_service(self, "cli_nested", CleanupFixtureChild())
        handler.assert_not_awaited()
        self.assertEqual((report["requests"], report["client_requests"], report["cleanup_rejected_client_requests"]), (0, 1, 1))
        self.assertEqual((report["admitted_client_requests"], report["upstream_dispatch_attempts"], report["request_limit"]), (0, 0, 2))
        self.assertEqual((report["status"], report["error_category"]), ("failed", "timeout"))

    async def test_returned_report_freezes_late_dispatch_timing_and_failure_mutations(self):
        captured = {}
        initial = FixtureEvaluationRouter.__init__
        def capture(router, registry, token):
            initial(router, registry, token)
            closure = dict(zip(type(router).proxy.__code__.co_freevars,
                               (cell.cell_contents for cell in type(router).proxy.__closure__)))
            captured["dispatches"] = closure["dispatches"]
            captured["record"] = {"dispatch_index": 1, "transport_result": "raised"}
            captured["dispatches"].append(captured["record"])
            captured["timing"] = {"outcomes": {"failed": 0}}
            captured["failure"] = {"reason": "observed_failure"}
            router.metrics.snapshot = lambda: captured["timing"]
            router.last_failure = captured["failure"]
        with patch.object(FixtureEvaluationRouter, "__init__", capture), \
             patch.object(evaluator_module, "CLI_CLEANUP_TIMEOUT_SECONDS", 0.02):
            report = await CliOutputObservationTests.evaluate_without_process_or_service(self, "cli_nested", CleanupFixtureChild())
        snapshot = deepcopy(report)
        captured["record"].update(transport_result="returned", http_status=200)
        captured["dispatches"].append({"dispatch_index": 2})
        captured["timing"]["outcomes"]["failed"] = 1
        captured["failure"]["reason"] = "late_failure"
        self.assertEqual(report, snapshot)
        self.assertEqual((report["status"], report["error_category"]), ("failed", "timeout"))

    async def test_terminal_mkdir_collision_never_removes_preexisting_directory(self):
        import gc
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory(prefix="operator-eval-collision-test-") as directory:
            parent = Path(directory).resolve()
            existing = parent / "operator-terminal-work-collision"
            existing.mkdir()
            sentinel = existing / "owner-sentinel.txt"
            sentinel.write_bytes(b"UNCHANGED_OWNER_BYTES")
            row = deepcopy(ROUTE)
            row["responses"].update(codex_tool_mode="standard", upstream_response_mode="json")
            child = CleanupFixtureChild()
            cleanup = AsyncMock()
            with patch.object(evaluator_module.tempfile, "gettempdir", return_value=str(parent)), \
                 patch.object(evaluator_module.secrets, "token_hex", return_value="collision"), \
                 patch.object(evaluator_module, "executable_digest", return_value="fixture_digest"), \
                 patch.object(FixtureEvaluationRunner, "cleanup", cleanup):
                report = await CliOutputObservationTests.evaluate_without_process_or_service(self,
                    "cli_powershell", child, row=row, terminal_shell=Path("C:/fixture/powershell.exe"))
            gc.collect()
            self.assertEqual(sentinel.read_bytes(), b"UNCHANGED_OWNER_BYTES")
            self.assertTrue(existing.is_dir())
            self.assertEqual(cleanup.await_count, 1)
            self.assertEqual((report["status"], report["error_category"]), ("failed", "harness_error"))
            self.assertFalse(report["cli_process"]["started"])
            self.assertIsNone(report["cli_output"]["cleanup"]["pending_tasks"])

    async def test_unknown_terminal_exit_keeps_private_home_and_normal_work_after_gc(self):
        import gc
        from unittest.mock import AsyncMock
        class Terminal:
            def __init__(self, work, case, executable, marker, **kwargs):
                self.family, self.marker, self.arguments = "powershell", marker, {"cmd": "fixture_never_executed"}
            def report(self):
                return {}
        row = deepcopy(ROUTE)
        row["responses"].update(codex_tool_mode="standard", upstream_response_mode="json")
        cleanup = AsyncMock()
        original_mkdir = Path.mkdir
        with patch.object(evaluator_module, "CLI_CLEANUP_TIMEOUT_SECONDS", 0.02), \
             patch.object(evaluator_module, "executable_digest", return_value="fixture_digest"), \
             patch.object(evaluator_module, "TerminalFixture", Terminal), \
             patch.object(FixtureEvaluationRunner, "cleanup", cleanup), \
             patch.object(Path, "mkdir", autospec=True, side_effect=original_mkdir) as mkdir:
            report = await CliOutputObservationTests.evaluate_without_process_or_service(self,
                "cli_powershell", CleanupFixtureChild(kill_mode="request_only"), row=row,
                terminal_shell=Path("C:/fixture/powershell.exe"))
        paths = report["retained_fixture_paths"]
        root, work = Path(paths["root"]), Path(paths["work"])
        self.addCleanup(evaluator_module._remove_fixture_directory, root, root.parent)
        self.addCleanup(evaluator_module._remove_fixture_directory, work, work.parent)
        gc.collect()
        self.assertTrue(all(Path(value).is_dir() for value in paths.values()))
        self.assertNotEqual(work.parent, root)
        self.assertTrue(any(call.args[0] == work and call.kwargs.get("mode") == 0o755 for call in mkdir.call_args_list))
        self.assertEqual((report["status"], report["error_category"], report["exit_code"]), ("failed", "timeout", None))
        self.assertEqual(cleanup.await_count, 1)


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI"), "explicit current Desktop CLI required")
class CurrentCliEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_app_server_bootstrap_checks_actual_untrusted_thread_without_turn(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        calls = []
        async def unexpected_request(request):
            calls.append((request.method, request.path))
            return web.json_response({"error": "no_model_request_allowed"}, status=400)
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", unexpected_request)
        server = TestServer(app)
        await server.start_server()
        retained = os.environ.get("CODEX_OPERATOR_TEST_NATIVE_CAPTURE")
        audit = Path(retained) if retained else Path(tempfile.mkdtemp(prefix="operator-native-startup-test-")).resolve()
        client, result, cleanup = None, None, None
        try:
            if retained:
                self.assertTrue(audit.is_absolute())
                self.assertFalse(audit.exists())
                audit.mkdir()
            root = audit / "private"
            root.mkdir(mode=0o700)
            home, work, capture = (root / name for name in ("home", "work", "capture"))
            for path in (home, work, capture):
                path.mkdir()
            catalog = json.loads((Path(evaluator_module.__file__).parent /
                "operator_core/beeper_model_catalog.json").read_bytes())
            catalog["models"] = [{**catalog["models"][0], "slug": "synthetic-native"}]
            catalog_path = root / "catalog.json"
            catalog_path.write_text(dumps(catalog), encoding="utf-8")
            settings = {"model": "synthetic-native", "model_provider": "operator_fixture",
                "model_catalog_json": str(catalog_path),
                "model_providers.operator_fixture.name": "No-model native startup fixture",
                "model_providers.operator_fixture.base_url": str(server.make_url("/v1")),
                "model_providers.operator_fixture.wire_api": "responses",
                "model_providers.operator_fixture.request_max_retries": 0,
                "model_providers.operator_fixture.stream_max_retries": 0,
                "model_providers.operator_fixture.supports_websockets": False}
            (home / "config.toml").write_text("".join(key + "=" + dumps(value) + "\n"
                for key, value in settings.items()), encoding="utf-8")
            try:
                client = evaluator_module.NativeApprovalCapture(
                    Path(os.environ["CODEX_OPERATOR_TEST_CLI"]), home, work, capture,
                    model="synthetic-native", provider="operator_fixture", timeout_seconds=30)
                await asyncio.to_thread(client.request, "initialize", {
                    "clientInfo": {"name": "operator_no_model_fixture", "version": "1"},
                    "capabilities": {"experimentalApi": True}})
                await asyncio.to_thread(client.notify, "initialized")
                result = await asyncio.to_thread(client.request, "thread/start", {
                    "model": client.model, "modelProvider": client.provider, "cwd": str(work),
                    "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
                    "ephemeral": True, "allowProviderModelFallback": False})
                self.assertEqual((result["approvalPolicy"], result["approvalsReviewer"]), ("untrusted", "user"))
                self.assertEqual(result["sandbox"]["type"], "readOnly")
                self.assertIs(result["sandbox"].get("networkAccess", False), False)
                self.assertEqual(result["runtimeWorkspaceRoots"], [str(work)])
                self.assertEqual(result["thread"]["id"], client._thread_id)
                self.assertIsNone(client._turn_id)
            finally:
                if client is not None:
                    client._admission_closed = True
                    client._cleanup_deadline = time.monotonic() + evaluator_module.CLI_CLEANUP_TIMEOUT_SECONDS
                    try:
                        client.process.stdin.close()  # EOF requests normal App Server exit; no turn or tool.
                        await asyncio.to_thread(client.process.wait, timeout=max(0,
                            client._cleanup_deadline - time.monotonic()))
                    except (OSError, evaluator_module.subprocess.TimeoutExpired):
                        pass  # The original close report keeps unknown/forced exit as failed evidence.
                    cleanup = await asyncio.to_thread(client.close)
                raw = {name: (capture / (name + ".raw")).read_bytes()
                       for name in ("client", "server", "stderr") if (capture / (name + ".raw")).exists()}
                sent = [json.loads(line) for line in raw.get("client", b"").splitlines()]
                received = [json.loads(line) for line in raw.get("server", b"").splitlines()]
                turns = sum(message.get("method") == "turn/started" for message in received)
                tools = sum(message.get("method") == "item/started"
                    and message.get("params", {}).get("item", {}).get("type") not in {"userMessage", "agentMessage", "reasoning"}
                    for message in received)
                approvals = sum(message.get("method", "").endswith("/requestApproval") for message in received)
                observation = {"thread_response": result, "cleanup": cleanup,
                    "fixture_root": str(root),
                    "http_requests": len(calls), "client_turn_starts": sum(message.get("method") == "turn/start" for message in sent),
                    "observed_turn_starts": turns, "observed_tool_items": tools, "observed_approval_requests": approvals,
                    "actual_child_pid": client.process.pid if client is not None else None,
                    "raw_files": {name: {"path": str(capture / (name + ".raw")),
                                         "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                                  for name, value in raw.items()}}
                with (audit / "observation.json").open("xb") as handle:
                    handle.write((dumps(observation) + "\n").encode("utf-8"))
            self.assertEqual(calls, [])
            self.assertEqual((turns, tools, approvals), (0, 0, 0), observation)
            self.assertTrue(cleanup["cleanup_complete"], observation)
            self.assertFalse(cleanup["cleanup_error"], observation)
            self.assertFalse(cleanup["capture_failed"], observation)
            self.assertEqual(cleanup["exit_code"], 0, observation)
            self.assertTrue(all(stream["complete"] for stream in cleanup["streams"].values()), observation)
            self.assertEqual([message.get("method") for message in sent],
                             ["initialize", "initialized", "thread/start"])
            self.assertTrue(all("result" not in message for message in sent))
            self.assertTrue(all(message.get("method") != "turn/start" for message in sent))
        finally:
            await server.close()

    async def test_json_cancellation_reaches_upstream_without_waiting_for_headers(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        received, disconnected = asyncio.Event(), asyncio.Event()
        calls = 0
        async def upstream(request):
            nonlocal calls
            await request.read()
            calls += 1
            received.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                disconnected.set()
                raise
        app = web.Application(handler_args={"handler_cancellation": True})
        app.router.add_post("/v1/responses", upstream)
        server = TestServer(app)
        await server.start_server()
        row = deepcopy(ROUTE)
        row.update(api_base=str(server.make_url("/v1")), reasoning_efforts=["low"])
        row["responses"].update(parallel_tool_calls=False, text_tool_outputs="json_string",
                                upstream_response_mode="json")
        try:
            report = await evaluate(row, "cli_cancel", Path(os.environ["CODEX_OPERATOR_TEST_CLI"]))
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(received.is_set())
            await asyncio.wait_for(disconnected.wait(), 2)
            self.assertEqual(calls, 1)
            self.assertTrue(report["cancel_observed"])
            self.assertEqual(report["upstream_header_responses"], 0)
            self.assertFalse(report["upstream_headers_observed_before_cancel"])
            self.assertFalse(report["provider_cancellation_verified"])
            self.assertEqual(report["timing"]["outcomes"], {"cancelled": 1, "completed": 0, "failed": 0})
        finally:
            await server.close()

    async def test_multiround_error_and_readonly_patch_plan_use_actual_cli(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        cases = [(case, "correct", "exact") for case in ("cli_multiround", "cli_tool_error", "cli_patchplan",
                                                "cli_error_stop", "cli_exit_stop")]
        # Boundary permutations live in EvalFixtureTests. Keep one real-CLI
        # policy comparison and exercise each stop violation under the more
        # permissive format policy so whitespace compatibility cannot mask it.
        cases += [("cli_exit_stop", "leading_lf", policy) for policy in ("exact", "marker_line_v1")]
        cases += [("cli_exit_stop", behavior, "marker_line_v1") for behavior in ("retry", "omit_error", "extra_round")]
        cases.append(("cli_tool_error", "standard", "exact"))
        for case, behavior, policy in cases:
            with self.subTest(case=case, behavior=behavior, policy=policy):
                received = []
                async def upstream(request):
                    body = await request.json()
                    received.append(body)
                    # The CLI must send only the synthetic fixture context, without
                    # the automatically discovered host skill catalog/instructions.
                    context = dumps([body.get("instructions"), body["input"]])
                    for marker in ("<skills_instructions>", "## Skills", "### Available skills"):
                        self.assertNotIn(marker, context)
                    previous = [item for item in body["input"] if item.get("type") == "function_call_output"]
                    count = len(previous)
                    if case == "cli_patchplan":
                        operations = [{"action": "read"}, {"action": "propose", "old": "* 10)", "new": "* 100)"}, {"action": "verify"}]
                    elif case in STOP_CASES:
                        operations = [{"action": "fail"}]
                    else:
                        operations = [{"action": "challenge" if case == "cli_multiround" else "fail"}, None]
                        if count == 1:
                            # Only this fake upstream's synthetic fixture result is inspected.
                            raw = dumps(previous[-1]["output"])
                            import re
                            challenge = re.search(r"[a-f0-9]{16}", raw).group()
                            operations[1] = {"action": "answer" if case == "cli_multiround" else "recover", "value": challenge}
                    if count < len(operations):
                        code = ('const forbidden = ' + dumps(list(UNRELATED_FIXTURE_TOOLS)) + '; '
                                'if (ALL_TOOLS.some(t => forbidden.includes(t.name.split(/__|\\./).pop()))) '
                                'throw new Error("unrelated_fixture_tool_visible"); '
                                'const t = ALL_TOOLS.find(t => t.name.endsWith("__fixture_step")); text(await tools[t.name]('
                                + dumps(operations[count]) + '));')
                        if behavior == "retry":
                            code += ' text(await tools[t.name]({action:"fail"}));'
                        item = {"id": "fc_" + str(count), "type": "function_call", "call_id": "call_" + str(count),
                                "name": "exec", "status": "completed", "arguments": dumps({"input": code})}
                        if behavior == "standard":
                            names = [tool["name"] for tool in body["tools"]
                                     if tool["type"] == "function" and tool["name"] ==
                                     tool_alias("function", "mcp__operator_fixture", "fixture_step")]
                            self.assertEqual(len(names), 1)
                            self.assertTrue(all(tool["type"] == "function" for tool in body["tools"]))
                            self.assertTrue(all(tool["name"] not in UNRELATED_FIXTURE_TOOLS
                                                for tool in body["tools"]),
                                            [tool["name"] for tool in body["tools"]])
                            item.update(name=names[0], arguments=dumps(operations[count]))
                    else:
                        import re
                        marker = re.search(r"OPERATOR_EVAL_[a-f0-9]{16}", dumps(previous[-1]["output"])).group()
                        if case in STOP_CASES and behavior != "omit_error":
                            marker = "STOPPED synthetic_expected_error " + marker
                        if behavior == "leading_lf":
                            marker = "\n\n" + marker
                        item = {"id": "msg_end", "type": "message", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": marker, "annotations": []}]}
                        if behavior == "extra_round":
                            item = {"id": "fc_extra", "type": "function_call", "call_id": "call_extra",
                                    "name": "exec", "status": "completed",
                                    "arguments": dumps({"input": "text('synthetic extra round');"})}
                    if item["type"] == "function_call":
                        events = events_for(item)
                    else:
                        response = {"id": "resp_end", "object": "response", "status": "completed", "output": [item]}
                        events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                                  {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
                                  {"type": "response.output_text.delta", "output_index": 0, "item_id": item["id"], "content_index": 0, "delta": marker},
                                  {"type": "response.output_item.done", "output_index": 0, "item": item},
                                  {"type": "response.completed", "response": response}]
                    if body.get("stream") is False:
                        return web.json_response(events[-1]["response"])
                    return web.Response(body=wire(events), content_type="text/event-stream")
                app = web.Application()
                app.router.add_post("/v1/responses", upstream)
                server = TestServer(app)
                await server.start_server()
                row = deepcopy(ROUTE)
                row.update(api_base=str(server.make_url("/v1")), reasoning_efforts=["low"])
                row["responses"].update(parallel_tool_calls=False, text_tool_outputs="json_string")
                if behavior == "standard":
                    row["responses"].update(codex_tool_mode="standard", custom_tools={})
                if behavior == "extra_round":
                    row["responses"]["upstream_response_mode"] = "json"
                try:
                    report = await evaluate(row, case, Path(os.environ["CODEX_OPERATOR_TEST_CLI"]), final_text_policy=policy)
                    accepted = behavior in {"correct", "standard"} or (policy == "marker_line_v1" and behavior == "leading_lf")
                    self.assertEqual(report["codex_tool_mode"], "standard" if behavior == "standard" else "code_mode_only")
                    self.assertEqual(report["status"], "passed" if accepted else "failed", {"report": report, "synthetic_outputs": [
                        item["output"] for body in received for item in body["input"]
                        if item.get("type") == "function_call_output"]})
                    if case in STOP_CASES:
                        self.assertEqual(report["stopped_after_fixture_error"], behavior not in {"retry", "extra_round"})
                        self.assertEqual(report["fixture_calls_after_error"], 1 if behavior == "retry" else 0)
                        self.assertEqual(report["failure_report_verified"], behavior not in {"omit_error", "extra_round"})
                        self.assertEqual(report["request_budget_exceeded"], behavior == "extra_round")
                    if behavior == "leading_lf":
                        self.assertFalse(report["verification_exact"])
                        self.assertTrue(report["verification_matched_after_trim"])
                    self.assertEqual(report["client_requests"], report["requests"])
                    self.assertEqual(report["upstream_dispatch_attempts"], len(received))
                    self.assertEqual(report["upstream_header_responses"], len(received))
                    self.assertEqual(report["budget_rejected_client_requests"], 1 if behavior == "extra_round" else 0)
                    self.assertEqual(report["admitted_client_requests"], len(received))
                    if behavior == "extra_round":
                        self.assertEqual(report["client_requests"], len(received) + 1)
                        for dispatch in report["upstream_dispatches"]:
                            self.assertEqual(dispatch["transport_result"], "returned")
                            self.assertEqual(dispatch["json_snapshot"]["output_counts"], {
                                "message": 0, "reasoning": 0, "function_call": 0, "custom_tool_call": 1, "other": 0})
                    else:
                        self.assertTrue(all(d["json_snapshot"] is None for d in report["upstream_dispatches"]))
                finally:
                    await server.close()


class NativeApprovalCaptureTests(unittest.TestCase):
    """No model/CLI: exercise actual wire identity, owner gate and bounded teardown."""
    @staticmethod
    def approval(rpc_id=17, method="item/commandExecution/requestApproval", **overrides):
        params = {"threadId": "fixture-thread", "turnId": "fixture-turn", "itemId": "fixture-item",
                  "startedAtMs": 42, "command": "Get-Content exact-fixture.txt", "cwd": "C:/fixture"}
        if method == "item/fileChange/requestApproval":
            params.pop("command")
            params.pop("cwd")
        params.update(overrides)
        return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}

    def gate(self, request):
        return evaluator_module.NativeApprovalGate((json.dumps(request) + "\r\n").encode("utf-8"),
            thread_id="fixture-thread", turn_id="fixture-turn",
            command="Get-Content exact-fixture.txt", cwd="C:/fixture")

    @contextmanager
    def capture(self, messages=(), *, stderr=b"", exit_observed=True, approval_contract=None):
        class Process:
            def __init__(self):
                self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(b"".join(messages)), io.BytesIO(stderr)
                self.returncode = None
                self.actions = []
            def poll(self):
                return self.returncode
            def terminate(self):
                self.actions.append("terminate")
                if exit_observed:
                    self.returncode = 0
            def kill(self):
                self.actions.append("kill")
                if exit_observed:
                    self.returncode = 0
            def wait(self, timeout):
                if self.returncode is None:
                    raise evaluator_module.subprocess.TimeoutExpired("synthetic", timeout)
                return self.returncode
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("home", "work", "capture")]
            for path in paths:
                path.mkdir()
            process = Process()
            with patch.object(evaluator_module.subprocess, "Popen", return_value=process) as launch:
                client = evaluator_module.NativeApprovalCapture(Path(directory) / "codex.exe", *paths,
                    model="synthetic-model", provider="fixture-provider", approval_contract=approval_contract)
            try:
                yield client, process, launch.call_args
            finally:
                client._cleanup_deadline = time.monotonic()
                process.returncode = 0  # Release this fake only, including the unknown-exit test.
                client.close()

    def test_single_owner_reply_preserves_integer_and_string_rpc_ids_and_raw_hash(self):
        for rpc_id in (17, "17"):
            with self.subTest(rpc_id=rpc_id):
                gate = self.gate(self.approval(rpc_id))
                ticket = gate.ticket()
                self.assertEqual(ticket["request_sha256"], hashlib.sha256(gate.raw).hexdigest())
                self.assertEqual(gate.response({**ticket, "decision": "decline"}),
                    {"jsonrpc": "2.0", "id": rpc_id, "result": {"decision": "decline"}})
                with self.assertRaisesRegex(evaluator_module.RouterError, "owner_decision_rejected"):
                    gate.response({**ticket, "decision": "accept"})

    def test_unissued_stale_or_broad_owner_decisions_are_rejected_without_consuming_gate(self):
        for changed in ({}, {"id": "17"}, {"nonce": "old"}, {"request_sha256": "0" * 64},
                        {"threadId": "other"}, {"turnId": "other"}, {"itemId": "other"},
                        {"decision": "acceptForSession"}, {"decision": "cancel"},
                        {"decision": {"acceptWithExecpolicyAmendment": {}}}, {"extra": True}):
            with self.subTest(changed=changed):
                gate = self.gate(self.approval())
                candidate = {**gate.ticket(), "decision": "accept", **changed}
                if not changed:
                    candidate = {"decision": "accept"}
                with self.assertRaisesRegex(evaluator_module.RouterError, "owner_decision_rejected"):
                    gate.response(candidate)
                self.assertFalse(gate.used)

    def test_command_scope_rejects_subcallbacks_stdin_and_changed_command_or_cwd(self):
        for change in ({"approvalId": "subcallback"}, {"kind": "writeStdin"},
                       {"command": "Get-Content another.txt"}, {"cwd": "C:/other"},
                       {"additionalPermissions": {}}, {"networkApprovalContext": {}},
                       {"proposedExecpolicyAmendment": []}, {"proposedNetworkPolicyAmendments": []}):
            with self.subTest(change=change), self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
                self.gate(self.approval(**change))
        self.assertIsNotNone(self.gate(self.approval(approvalId=None)))

    def test_file_single_action_gate_rejects_session_root_grant(self):
        self.assertIsNotNone(self.gate(self.approval(method="item/fileChange/requestApproval", grantRoot=None)))
        with self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
            self.gate(self.approval(method="item/fileChange/requestApproval", grantRoot="C:/fixture"))

    def dated_gate(self, request, argv):
        raw = (dumps(request) + "\r\n").encode("utf-8")
        return evaluator_module.NativeApprovalGate(raw,
            thread_id="fixture-thread", turn_id="fixture-turn",
            command="Get-Content exact-fixture.txt", cwd="C:/fixture",
            approval_contract=evaluator_module.NATIVE_APPROVAL_CONTRACT_0160, command_argv=argv)

    def proposed_request(self, rpc_id=17):
        argv = ["C:/fixture/pwsh.exe", "-NoProfile", "-Command", "Get-Content exact-fixture.txt\r\n# 原件🙂"]
        request = self.approval(rpc_id, environmentId="local", proposedExecpolicyAmendment=argv,
            availableDecisions=["accept", {"acceptWithExecpolicyAmendment": {
                "execpolicy_amendment": argv}}, "cancel"])
        return request, argv

    def test_dated_proposal_is_inert_and_only_exact_single_action_replies_preserve_raw(self):
        for rpc_id in (17, "17"):
            for decision in ("accept", "cancel"):
                with self.subTest(rpc_id=rpc_id, decision=decision):
                    request, argv = self.proposed_request(rpc_id)
                    gate = self.dated_gate(request, argv)
                    self.assertEqual(gate.request, request)
                    self.assertEqual(gate.raw, (dumps(request) + "\r\n").encode("utf-8"))
                    ticket = gate.ticket()
                    self.assertEqual(ticket["request_sha256"], hashlib.sha256(gate.raw).hexdigest())
                    self.assertEqual(gate.response({**ticket, "decision": decision}),
                        {"jsonrpc": "2.0", "id": rpc_id, "result": {"decision": decision}})
                    with self.assertRaisesRegex(evaluator_module.RouterError, "owner_decision_rejected"):
                        gate.response({**ticket, "decision": decision})
                    with self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
                        self.gate(request)  # Default contract still rejects the same proposal.

    def test_dated_proposal_rejects_broad_changed_malformed_or_unbound_argv_and_permissions(self):
        request, argv = self.proposed_request()
        for candidate in (None, [], argv[:1], argv + ["extra"], [*argv[:-1], "another command"],
                          [*argv[:-1], argv[-1].replace("\r\n", "\n")],
                          [True], ["bad\x00arg"], ["\ud800"]):
            with self.subTest(candidate=repr(candidate)), self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
                self.dated_gate(request, candidate)
        for change in ({"proposedExecpolicyAmendment": argv[:1]}, {"proposedExecpolicyAmendment": "wrong"},
                       {"approvalId": "child"}, {"kind": "writeStdin"}, {"additionalPermissions": {}},
                       {"networkApprovalContext": {}}, {"proposedNetworkPolicyAmendments": []},
                       {"environmentId": "remote"}, {"environmentId": None}, {"unknownGrant": True}, {"command": "another command"},
                       {"cwd": "C:/other"}):
            with self.subTest(change=change), self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
                self.dated_gate({**request, "params": {**request["params"], **change}}, argv)
        invalid = ["\ud800"]
        broken = {**request, "params": {**request["params"], "proposedExecpolicyAmendment": invalid,
            "availableDecisions": ["accept", {"acceptWithExecpolicyAmendment": {
                "execpolicy_amendment": invalid}}, "cancel"]}}
        with self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
            evaluator_module.NativeApprovalGate((json.dumps(broken, ensure_ascii=True) + "\r\n").encode("utf-8"),
                thread_id="fixture-thread", turn_id="fixture-turn", command="Get-Content exact-fixture.txt",
                cwd="C:/fixture", approval_contract=evaluator_module.NATIVE_APPROVAL_CONTRACT_0160,
                command_argv=invalid)

    def test_dated_advertised_choices_never_authorize_grants_or_unoffered_decline(self):
        request, argv = self.proposed_request()
        for offered in (None, [], ["accept", "decline"], ["accept", "cancel", "cancel"],
                        ["acceptForSession", "cancel"], ["accept", {"acceptWithExecpolicyAmendment": {
                            "execpolicy_amendment": argv[:1]}}, "cancel"],
                        ["accept", {"unknown": True}, "cancel"]):
            with self.subTest(offered=offered), self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
                self.dated_gate({**request, "params": {**request["params"], "availableDecisions": offered}}, argv)
        gate = self.dated_gate(request, argv)
        for decision in ("decline", "acceptForSession", request["params"]["availableDecisions"][1],
                         {"grantRoot": "C:/fixture"}, {"applyNetworkPolicyAmendment": {}}):
            with self.subTest(decision=decision), self.assertRaisesRegex(evaluator_module.RouterError, "owner_decision_rejected"):
                gate.response({**gate.ticket(), "decision": decision})
            self.assertFalse(gate.used)
        plain = self.approval(environmentId="local", availableDecisions=["accept", "cancel"])
        single = self.dated_gate(plain, None)
        self.assertEqual(single.response({**single.ticket(), "decision": "accept"})["result"], {"decision": "accept"})
        legacy = self.dated_gate(self.approval(environmentId="local"), None)
        self.assertEqual(legacy.response({**legacy.ticket(), "decision": "decline"})["result"], {"decision": "decline"})

    def test_capture_propagates_dated_contract_and_rejects_a_foreign_contract_before_reply(self):
        request, argv = self.proposed_request("17")
        raw = (dumps(request) + "\r\n").encode("utf-8")
        with self.capture([raw], approval_contract=evaluator_module.NATIVE_APPROVAL_CONTRACT_0160) as (client, process, _):
            client._thread_id, client._turn_id = "fixture-thread", "fixture-turn"
            observed = client.next_message()
            gate = client.approval_gate(observed, command="Get-Content exact-fixture.txt",
                                        cwd="C:/fixture", command_argv=argv)
            self.assertEqual(process.stdin.getvalue(), b"")
            pair = client.reply_approval(gate, {**gate.ticket(), "decision": "cancel"})
            self.assertEqual(pair["pairs"][0]["request"], request)
            self.assertEqual(json.loads(process.stdin.getvalue())["result"], {"decision": "cancel"})
        request = self.approval(environmentId="local")
        raw = (dumps(request) + "\n").encode("utf-8")
        with self.capture([raw]) as (client, process, _):
            client._thread_id, client._turn_id = "fixture-thread", "fixture-turn"
            client.next_message()
            foreign = self.dated_gate(request, None)
            with self.assertRaisesRegex(evaluator_module.RouterError, "unobserved_approval"):
                client.reply_approval(foreign, {**foreign.ticket(), "decision": "accept"})
            self.assertEqual(process.stdin.getvalue(), b"")
            self.assertFalse(foreign.used)

    def test_dated_contract_is_explicit_and_file_root_grants_remain_rejected(self):
        request = self.approval(method="item/fileChange/requestApproval", grantRoot="C:/fixture")
        with self.assertRaisesRegex(evaluator_module.RouterError, "scope_rejected"):
            self.dated_gate(request, None)
        with self.assertRaisesRegex(evaluator_module.RouterError, "contract_rejected"):
            evaluator_module.NativeApprovalGate((dumps(self.approval()) + "\n").encode("utf-8"),
                thread_id="fixture-thread", turn_id="fixture-turn", approval_contract="unknown")
        with tempfile.TemporaryDirectory() as directory, patch.object(evaluator_module.subprocess, "Popen") as launch:
            paths = [Path(directory) / name for name in ("home", "work", "capture")]
            for path in paths:
                path.mkdir()
            with self.assertRaisesRegex(evaluator_module.RouterError, "configuration_rejected"):
                evaluator_module.NativeApprovalCapture(Path(directory) / "codex.exe", *paths,
                    model="synthetic-model", provider="fixture-provider", approval_contract="unknown")
            launch.assert_not_called()

    def test_malformed_wire_or_approval_identity_never_creates_a_ticket(self):
        for raw in (b'{"id":1,"id":2}\n', b'{"id":NaN}\n', b'\xff\n', b'[]\n'):
            with self.subTest(raw=raw), self.assertRaises(evaluator_module.RouterError):
                evaluator_module.NativeApprovalGate(raw, thread_id="fixture-thread", turn_id="fixture-turn")
        for rpc_id in (True, None, [], "", 2 ** 63, "\ud800"):
            with self.subTest(rpc_id=repr(rpc_id)), self.assertRaises(evaluator_module.RouterError):
                self.gate(self.approval(rpc_id))
        for change in ({"threadId": "other"}, {"turnId": "other"}, {"itemId": ""},
                       {"startedAtMs": True}, {"startedAtMs": -1}):
            with self.subTest(change=change), self.assertRaises(evaluator_module.RouterError):
                self.gate(self.approval(**change))

    def test_capture_retains_notifications_callback_unicode_crlf_and_exact_id_types(self):
        notification = {"method": "item/started", "params": {"text": "原件\r\n🙂"}}
        integer_response = {"id": 1, "result": {"unrelated": True}}
        callback = self.approval("1")
        response = {"id": "1", "result": {"server": "synthetic"}}
        raws = [(dumps(value) + "\r\n").encode("utf-8") for value in
                (notification, integer_response, callback, response)]
        with self.capture(raws, stderr="原始诊断\r\n".encode("utf-8")) as (client, process, _):
            self.assertEqual(client.request("initialize", {}), response["result"])
            self.assertEqual([client.next_message() for _ in range(3)],
                             [notification, integer_response, callback])
            self.assertEqual((client.capture_root / "server.raw").read_bytes(), b"".join(raws))
            self.assertEqual((client.capture_root / "stderr.raw").read_bytes(), "原始诊断\r\n".encode("utf-8"))
            self.assertEqual(process.stdin.getvalue(), b'{"jsonrpc":"2.0","id":"1","method":"initialize","params":{}}\n')

    def test_only_observed_pending_request_can_pair_with_explicit_reply(self):
        request = self.approval()
        raw = (dumps(request) + "\r\n").encode("utf-8")
        with self.capture([raw]) as (client, process, _):
            client._thread_id, client._turn_id = "fixture-thread", "fixture-turn"
            observed = client.next_message()
            gate = client.approval_gate(observed, command="Get-Content exact-fixture.txt", cwd="C:/fixture")
            self.assertEqual(process.stdin.getvalue(), b"")  # Receiving a prompt supplies no decision.
            pair = client.reply_approval(gate, {**gate.ticket(), "decision": "accept"})
            self.assertEqual(pair["pairs"][0]["request"], request)
            self.assertEqual(json.loads(process.stdin.getvalue())["result"], {"decision": "accept"})
            with self.assertRaisesRegex(evaluator_module.RouterError, "unobserved_approval"):
                client.reply_approval(gate, {**gate.ticket(), "decision": "accept"})
            for forged in ({**request, "id": "17"}, {**request, "params": {}}):
                with self.assertRaisesRegex(evaluator_module.RouterError, "unobserved_approval"):
                    client.approval_gate(forged)

    def test_fixture_launch_strips_credentials_and_keeps_readonly_never_bootstrap(self):
        with patch.dict(os.environ, {"GLM_API_KEY": "private", "BUSINESS_TOKEN": "private"}):
            with self.capture() as (client, _, args):
                self.assertEqual(args.args[0][1:4], ["app-server", "--listen", "stdio://"])
                self.assertIn('approval_policy="never"', args.args[0])
                self.assertIn('sandbox_mode="read-only"', args.args[0])
                self.assertIn('approvals_reviewer="user"', args.args[0])
                self.assertIn('project_doc_max_bytes=0', args.args[0])
                self.assertEqual(args.kwargs["cwd"], str(client.work))
                self.assertNotIn("GLM_API_KEY", args.kwargs["env"])
                self.assertNotIn("BUSINESS_TOKEN", args.kwargs["env"])
                self.assertEqual(args.kwargs["env"]["CODEX_HOME"], str(client.home))
                self.assertNotIn("text", args.kwargs)
                self.assertEqual(args.kwargs["stderr"], evaluator_module.subprocess.PIPE)

    def test_thread_and_turn_overrides_cannot_widen_fixture_permissions(self):
        with self.capture() as (client, process, _):
            required = {"model": client.model, "modelProvider": client.provider, "cwd": str(client.work),
                "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
                "ephemeral": True, "allowProviderModelFallback": False}
            client._validate_request("thread/start", required)
            for change in ({"sandbox": "danger-full-access"}, {"approvalPolicy": "never"},
                           {"approvalsReviewer": "auto_review"}, {"cwd": "C:/business"},
                           {"allowProviderModelFallback": True}, {"config": {}}, {"dynamicTools": []}):
                with self.subTest(change=change), self.assertRaises(evaluator_module.RouterError):
                    client.request("thread/start", {**required, **change})
            client._thread_id = "fixture-thread"
            turn = {"threadId": client._thread_id, "input": [{"type": "text", "text": "synthetic", "text_elements": []}]}
            client._validate_request("turn/start", turn)
            with self.assertRaises(evaluator_module.RouterError):
                client.request("turn/start", {**turn, "sandboxPolicy": {"type": "dangerFullAccess"}})
            self.assertEqual(process.stdin.getvalue(), b"")

    def test_capture_byte_budget_rejects_before_rpc_delivery_and_retains_failure(self):
        raw = (dumps({"method": "notice", "params": {"text": "x" * 70}}) + "\n").encode()
        with patch.object(evaluator_module, "NATIVE_RPC_BYTES", 64):
            with self.capture([raw]) as (client, _, _):
                with self.assertRaisesRegex(evaluator_module.RouterError, "capture_failed"):
                    client.next_message()
                report = client.close()
                self.assertTrue(report["capture_failed"])
                self.assertLessEqual(report["capture_bytes"], 64)

    def test_start_error_or_missing_identity_is_consumed_and_cannot_dispatch_again(self):
        for method in ("thread/start", "turn/start"):
            for payload in ({"error": {"code": -1, "message": "private upstream error"}}, {"result": {}}):
                raw = (dumps({"id": "1", **payload}) + "\n").encode()
                with self.subTest(method=method, payload=payload), self.capture([raw]) as (client, process, _):
                    if method == "thread/start":
                        params = {"model": client.model, "modelProvider": client.provider, "cwd": str(client.work),
                            "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
                            "ephemeral": True, "allowProviderModelFallback": False}
                    else:
                        client._thread_id = "fixture-thread"
                        params = {"threadId": client._thread_id,
                                  "input": [{"type": "text", "text": "synthetic", "text_elements": []}]}
                    with self.assertRaises(evaluator_module.RouterError) as raised:
                        client.request(method, params)
                    self.assertNotIn("private upstream error", str(raised.exception))
                    original = process.stdin.getvalue()
                    with self.assertRaisesRegex(evaluator_module.RouterError, "method_rejected"):
                        client.request(method, params)
                    self.assertEqual(process.stdin.getvalue(), original)
                    self.assertEqual(len(original.splitlines()), 1)

    def test_native_thread_echo_conflicts_stop_before_turn_dispatch(self):
        conflicts = ({"model": "different-model"}, {"modelProvider": "different-provider"},
                     {"approvalPolicy": "never"}, {"approvalsReviewer": "auto_review"},
                     {"cwd": "C:/business"}, {"sandbox": {"type": "dangerFullAccess"}},
                     {"sandbox": {"type": "readOnly", "networkAccess": True}},
                     {"runtimeWorkspaceRoots": []}, {"runtimeWorkspaceRoots": ["C:/business"]},
                     {"instructionSources": ["business/AGENTS.md"]})
        for conflict in ({}, *conflicts, "extra_workspace_root"):
            with self.subTest(conflict=conflict), self.capture() as (client, process, _):
                if conflict == "extra_workspace_root":
                    conflict = {"runtimeWorkspaceRoots": [str(client.work), "C:/business"]}
                params = {"model": client.model, "modelProvider": client.provider, "cwd": str(client.work),
                    "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": "read-only",
                    "ephemeral": True, "allowProviderModelFallback": False}
                result = {**{key: params[key] for key in ("model", "modelProvider", "cwd", "approvalPolicy", "approvalsReviewer")},
                          "sandbox": {"type": "readOnly", "networkAccess": False}, "thread": {"id": "fixture-thread"},
                          "runtimeWorkspaceRoots": [str(client.work)],
                          **conflict}
                # This is a scripted transport response, not a synthesized live echo.
                client._deferred = [{"id": "1", "result": result}]
                if conflict:
                    with self.assertRaisesRegex(evaluator_module.RouterError, "thread_contract_conflict"):
                        client.request("thread/start", params)
                    original = process.stdin.getvalue()
                    with self.assertRaises(evaluator_module.RouterError):
                        client.request("turn/start", {"threadId": "fixture-thread", "input": []})
                    self.assertEqual(process.stdin.getvalue(), original)
                    self.assertIsNone(client._thread_id)
                else:
                    self.assertEqual(client.request("thread/start", params), result)
                    self.assertEqual(client._thread_id, "fixture-thread")

    def test_expired_owner_wait_sends_no_denial_and_exact_interrupt_is_once_only(self):
        response = (dumps({"id": "1", "result": {}}) + "\n").encode()
        with self.capture([response]) as (client, process, _):
            client._thread_id, client._turn_id = "fixture-thread", "fixture-turn"
            client.deadline = time.monotonic() - 1
            with self.assertRaises(evaluator_module.RouterError):
                client._write({"id": 17, "result": {"decision": "decline"}})
            self.assertEqual(process.stdin.getvalue(), b"")
            self.assertEqual(client.interrupt_turn(), {})
            self.assertEqual(json.loads(process.stdin.getvalue())["params"],
                             {"threadId": "fixture-thread", "turnId": "fixture-turn"})
            self.assertEqual(json.loads(process.stdin.getvalue())["method"], "turn/interrupt")
            self.assertLessEqual(client._cleanup_deadline - time.monotonic(), 5)
            with self.assertRaisesRegex(evaluator_module.RouterError, "interrupt_identity_rejected"):
                client.interrupt_turn()

    def test_unobserved_process_exit_is_not_success_and_all_raw_paths_remain(self):
        with self.capture(exit_observed=False) as (client, process, _):
            client._thread_id, client._turn_id = "fixture-thread", "fixture-turn"
            gate = self.gate(self.approval())
            client._observed[(int, 17)] = gate.raw
            client._cleanup_deadline = time.monotonic()
            report = client.close()
            self.assertIsNone(report["exit_code"])
            self.assertFalse(report["cleanup_complete"])
            self.assertTrue(report["cleanup_error"])
            self.assertEqual(process.actions, ["terminate", "kill"])
            self.assertTrue(all((client.capture_root / (name + ".raw")).is_file()
                                for name in ("client", "server", "stderr")))
            with self.assertRaisesRegex(evaluator_module.RouterError, "admission_closed"):
                client.reply_approval(gate, {**gate.ticket(), "decision": "accept"})
            with self.assertRaisesRegex(evaluator_module.RouterError, "admission_closed"):
                client.request("turn/start", {})
            with self.assertRaises(evaluator_module.RouterError):
                client._write({"method": "turn/start"})
            self.assertEqual(process.stdin.getvalue(), b"")
            self.assertFalse(gate.used)

    def test_deferred_messages_do_not_bypass_deadline_or_capture_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed), self.capture() as (client, _, _):
                client._deferred = [self.approval()]
                if failed:
                    client._capture_failed = True
                else:
                    client.deadline = time.monotonic() - 1
                with self.assertRaises(evaluator_module.RouterError):
                    client.next_message()
                self.assertEqual(len(client._deferred), 1)

    def test_cleanup_io_error_or_busy_metadata_lock_preserves_fixed_failed_observation(self):
        with self.capture() as (client, _, _):
            original = client._handles["server"]
            class FailedClose:
                def close(self):
                    raise OSError("private filesystem exception")
            client._handles["server"] = FailedClose()
            try:
                report = client.close()
                self.assertTrue(report["cleanup_error"])
                self.assertEqual(report["exit_code"], 0)
                self.assertNotIn("private filesystem exception", dumps(report))
            finally:
                client._handles["server"] = original
                original.close()
        with self.capture() as (client, _, _):
            client._cleanup_deadline = time.monotonic()
            client._lock.acquire()
            try:
                report = client.close()
                self.assertFalse(report["capture_metadata_complete"])
                self.assertFalse(report["cleanup_complete"])
                self.assertIsNone(report["capture_bytes"])
                self.assertEqual(report["streams"], {})
            finally:
                client._lock.release()

    def test_second_reader_start_failure_cleans_child_and_retains_fixed_failure_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("home", "work", "capture")]
            for path in paths:
                path.mkdir()
            process = SimpleNamespace(returncode=None, stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=io.BytesIO())
            process.poll = lambda: process.returncode
            process.terminate = process.kill = lambda: setattr(process, "returncode", 0)
            process.wait = lambda timeout: process.returncode
            original_start = evaluator_module.threading.Thread.start
            calls = []
            def start(reader):
                calls.append(reader)
                if len(calls) == 2:
                    raise RuntimeError("private resource exception")
                return original_start(reader)
            with patch.object(evaluator_module.subprocess, "Popen", return_value=process), \
                    patch.object(evaluator_module.threading.Thread, "start", start):
                with self.assertRaisesRegex(evaluator_module.RouterError, "native_fixture_reader_start_failed"):
                    evaluator_module.NativeApprovalCapture(Path(directory) / "codex.exe", *paths,
                        model="synthetic-model", provider="fixture-provider")
            report = json.loads((paths[2] / "reader-start-failure.json").read_bytes())
            self.assertEqual(report["state"], "failed")
            self.assertEqual(report["cleanup"]["exit_code"], 0)
            self.assertTrue(report["cleanup"]["capture_failed"])
            self.assertTrue(process.stdin.closed)
            self.assertNotIn("private resource exception", dumps(report))
            self.assertTrue(all((paths[2] / (name + ".raw")).is_file()
                                for name in ("client", "server", "stderr")))


if __name__ == "__main__":
    unittest.main()
