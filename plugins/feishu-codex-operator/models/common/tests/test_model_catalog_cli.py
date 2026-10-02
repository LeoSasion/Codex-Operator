"""Opt-in current-CLI catalog test; isolated home, no credentials or task calls."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)


import json
import asyncio
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "scripts"))
from operator_core.app_server import AppServerSession
from operator_core.model_registry import ModelRegistry


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI") and
                     os.environ.get("CODEX_OPERATOR_TEST_CATALOG"),
                     "explicit current Desktop CLI and read-only catalog paths required")
class CurrentCliCatalogTests(unittest.TestCase):
    def test_current_cli_accepts_augmented_catalog_without_native_row_changes(self):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        cached = json.loads(Path(os.environ["CODEX_OPERATOR_TEST_CATALOG"]).read_text(encoding="utf-8"))
        beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
        from copy import deepcopy
        from test_responses_tools import ROUTE
        adapted = {**deepcopy(ROUTE), "slug": "local/adapted-catalog-check", "reasoning_efforts": ["none", "low"]}
        registry = ModelRegistry({"version": 2, "models": [{
            "slug": "api/catalog-check", "display_name": "Catalog check",
            "model": "catalog-check", "api_base": "http://127.0.0.1:1/v1",
            "api_key_env": "", "context_window": 32000, "reasoning_efforts": ["low"], "responses": None}, adapted]}, beeper)
        native = {"models": cached["models"]}
        merged = registry.merge(native)
        self.assertEqual(native["models"], merged["models"][:len(native["models"])])
        with tempfile.TemporaryDirectory(prefix="operator-catalog-check-") as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps(merged), encoding="utf-8")
            # No real home config, auth, caches, MCPs or plugins are loaded by this child.
            environment = {k: v for k, v in os.environ.items()
                if not k.upper().startswith(("CODEX_", "OPENAI_", "CHATGPT_"))}
            environment["CODEX_HOME"] = directory
            popen = subprocess.Popen

            def isolated_popen(args, **kwargs):
                return popen([*args, "-c", "model_catalog_json=" + json.dumps(str(catalog)),
                    "-c", "openai_base_url=\"http://127.0.0.1:1/v1\"",
                    "-c", "cli_auth_credentials_store=\"file\""],
                    **{**kwargs, "env": environment, "cwd": str(root.parent)})

            with patch("operator_core.app_server.subprocess.Popen", side_effect=isolated_popen):
                with AppServerSession(executable, 15) as session:
                    result = session.request("model/list", {"includeHidden": False, "limit": 100})
                session.process.stdout.close()
            models = {row["model"]: row for row in result["data"]}
            self.assertIn("beeper", models)
            self.assertIn("api/catalog-check", models)
            self.assertIn("local/adapted-catalog-check", models)
            self.assertEqual("none", models["local/adapted-catalog-check"]["defaultReasoningEffort"])
            self.assertEqual("low", models["beeper"]["defaultReasoningEffort"])
            self.assertFalse(models["beeper"]["hidden"])
            for row in native["models"]:
                if row.get("visibility") == "list" and row.get("supported_in_api"):
                    self.assertIn(row["slug"], models)


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI"),
                     "explicit current Desktop CLI required for isolated provider-switch probe")
class CurrentCliSameTaskModelSwitchTests(unittest.TestCase):
    def test_one_provider_routes_two_models_in_same_task(self):
        self._check_same_task_models(use_router=False)

    def test_unified_router_keeps_native_task_and_switches_model_endpoint(self):
        try:
            import aiohttp  # noqa: F401 - optional router dependency for this opt-in case
        except ImportError:
            self.skipTest("optional router environment is required")
        self._check_same_task_models(use_router=True)

    def test_unified_router_lists_and_switches_to_web_model_in_native_task(self):
        try:
            import aiohttp  # noqa: F401 - optional router dependency for this opt-in case
        except ImportError:
            self.skipTest("optional router environment is required")
        self._check_same_task_models(use_router=True, web_model=True)

    def test_unified_router_returns_from_web_to_native_in_same_task(self):
        try:
            import aiohttp  # noqa: F401 - optional router dependency for this opt-in case
        except ImportError:
            self.skipTest("optional router environment is required")
        self._check_same_task_models(use_router=True, web_model=True, round_trip=True)

    def _check_same_task_models(self, *, use_router, web_model=False, round_trip=False):
        """An exact model switch may run a native checkpoint on the old model first."""
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        template = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0]
        from copy import deepcopy
        rows = []
        second_slug = ("api/chatgpt-web/gpt-5.6-sol" if web_model else
                       "api/probe-b" if use_router else "probe-b")
        for name in ("a", "b"):
            row = deepcopy(template)
            row.update(slug="probe-a" if name == "a" else second_slug,
                       display_name="Synthetic Probe " + name.upper(),
                       description="Isolated provider-switch test.", comp_hash="synthetic-probe-" + name,
                       priority=10 if name == "a" else 9)
            if use_router:
                row.update(context_window=32000 if name == "a" else 16000,
                           max_context_window=32000 if name == "a" else 16000)
            rows.append(row)
        catalog = {"models": rows}
        if use_router:
            from operator_core.model_router import ModelRouter
            from aiohttp import web
            beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
                "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
            route = {"slug": second_slug, "display_name": "Synthetic Probe B",
                "model": "upstream-probe-b", "api_base": "", "api_key_env": "OPERATOR_SYNTHETIC_EXTERNAL_KEY",
                "context_window": 16000, "reasoning_efforts": ["low"]}
            native_catalog = {"models": [rows[0]]}
        prompt = "Synthetic endpoint routing test. Reply only with the fixture output."
        web_prompt = "WEB_TURN_ONLY: answer this second synthetic user request."
        return_prompt = "NATIVE_RETURN_ONLY: answer this third synthetic user request."
        prompts = (prompt, web_prompt, return_prompt) if round_trip else (prompt, prompt)
        models = ("probe-a", second_slug, "probe-a") if round_trip else ("probe-a", second_slug)
        size_prompt = "Synthetic 413 transport test; do not retry."
        checkpoint_prefix = "You are performing a CONTEXT CHECKPOINT COMPACTION."
        received, unexpected = [], []

        class FixtureHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_CONNECT(self):
                unexpected.append(("CONNECT", self.path))
                self.send_error(403)

            def do_GET(self):
                if self.path.split("?", 1)[0] not in ({"/native/v1/models"} if use_router else {"/v1/models"}):
                    unexpected.append(("GET", self.path))
                    self.send_error(404)
                    return
                data = json.dumps(native_catalog if use_router else catalog).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                valid_paths = ({"/native/v1/responses", "/external/v1/responses"}
                               if use_router else {"/v1/responses"})
                if self.path.split("?", 1)[0] not in valid_paths:
                    unexpected.append(("POST", self.path))
                    self.send_error(404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(size))
                source = body.get("input")
                last = source[-1] if isinstance(source, list) and source else {}
                parts = last.get("content", []) if isinstance(last, dict) else []
                last_text = parts[0].get("text") if parts and isinstance(parts[0], dict) else None
                kind = ("checkpoint" if isinstance(last_text, str) and last_text.startswith(checkpoint_prefix)
                        else "business" if last_text in prompts
                        else "size" if last_text == size_prompt else "other")
                model = body.get("model")
                received.append({"model": model, "turn_id": (body.get("client_metadata") or {}).get("turn_id"),
                                 "kind": kind, "auth": self.headers.get("Authorization"),
                                 "path": self.path, "stream": body.get("stream"),
                                 "request_text": last_text, "input": source})
                if kind == "size":
                    wire = json.dumps({"error": {"type": "invalid_request_error",
                        "code": "synthetic_request_too_large", "message": "Synthetic 413; no request was forwarded."}}).encode()
                    self.send_response(413)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(wire)))
                    self.end_headers()
                    self.wfile.write(wire)
                    return
                count = len(received)
                text = f"SYNTHETIC_{model}_{count}"
                received[-1]["reply"] = text
                item = {"id": f"msg_probe_{count}", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}
                final = {"id": f"resp_probe_{count}", "object": "response", "status": "completed",
                         "model": model, "output": [item],
                         "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                events = [
                    {"type": "response.created", "response": {**final, "status": "in_progress", "output": []}},
                    {"type": "response.output_item.added", "output_index": 0,
                     "item": {**item, "status": "in_progress", "content": []}},
                    {"type": "response.output_text.delta", "item_id": item["id"],
                     "output_index": 0, "content_index": 0, "delta": text},
                    {"type": "response.output_text.done", "item_id": item["id"],
                     "output_index": 0, "content_index": 0, "text": text},
                    {"type": "response.output_item.done", "output_index": 0, "item": item},
                    {"type": "response.completed", "response": final},
                ]
                wire = ("".join("event: " + event["type"] + "\ndata: " +
                                json.dumps(event, separators=(",", ":")) + "\n\n"
                                for event in events).encode("utf-8") + b"data: [DONE]\n\n")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        router_loop = router_thread = router_env = None
        try:
            if use_router:
                router_env = patch.dict(os.environ, {"OPERATOR_SYNTHETIC_EXTERNAL_KEY": "synthetic-external-key"})
                router_env.start()
                route["api_base"] = f"http://127.0.0.1:{server.server_port}/external/v1"
                if web_model:
                    from dataclasses import replace
                    from operator_web_model import text_route
                    from operator_core.model_registry import WebServiceBinding
                    registry = ModelRegistry({"version": 1, "models": []}, beeper)
                    web_route = replace(text_route(model="gpt-5.6-sol"),
                        api_base=route["api_base"],
                        web_binding=WebServiceBinding("a" * 64, "b" * 64,
                                                      "synthetic-external-key"))
                    registry = registry.with_web_route(web_route)
                else:
                    registry = ModelRegistry({"version": 1, "models": [route]}, beeper)
                catalog = registry.merge(native_catalog)
                router = ModelRouter(registry, "a" * 64,
                    native_base=f"http://127.0.0.1:{server.server_port}/native/v1")
                router_loop = asyncio.new_event_loop()
                ready = queue.Queue(maxsize=1)

                def run_router():
                    asyncio.set_event_loop(router_loop)
                    async def start():
                        runner = web.AppRunner(router.app())
                        await runner.setup()
                        site = web.TCPSite(runner, "127.0.0.1", 0)
                        await site.start()
                        return runner, site._server.sockets[0].getsockname()[1]
                    runner, port = router_loop.run_until_complete(start())
                    ready.put(port)
                    try:
                        router_loop.run_forever()
                    finally:
                        router_loop.run_until_complete(runner.cleanup())
                        router_loop.close()

                router_thread = threading.Thread(target=run_router, daemon=True)
                router_thread.start()
                router_port = ready.get(timeout=5)
            with tempfile.TemporaryDirectory(prefix="operator-provider-switch-") as directory:
                root = Path(directory)
                home, work = root / "home", root / "work"
                home.mkdir()
                work.mkdir()
                catalog_file = home / "catalog.json"
                catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
                provider_url = (f"http://127.0.0.1:{router_port}/{'a' * 64}/v1" if use_router
                                else f"http://127.0.0.1:{server.server_port}/v1")
                (home / "config.toml").write_text(
                    'model = "probe-a"\nmodel_provider = "operator_probe"\n'
                    'model_reasoning_effort = "low"\napproval_policy = "never"\n'
                    'sandbox_mode = "read-only"\nweb_search = "disabled"\n'
                    'model_catalog_json = ' + json.dumps(str(catalog_file)) + '\n'
                    '[features]\nplugins = false\nremote_plugin = false\n'
                    '[analytics]\nenabled = false\n'
                    '[model_providers.operator_probe]\nname = "Operator synthetic router"\n'
                    f'base_url = "{provider_url}"\n'
                    'wire_api = "responses"\nenv_key = "OPERATOR_SYNTHETIC_PROBE_KEY"\n'
                    'request_max_retries = 0\nstream_max_retries = 0\n'
                    'supports_websockets = false\n', encoding="utf-8")
                environment = {key: value for key, value in os.environ.items()
                    if not key.upper().startswith(("CODEX_", "OPENAI_", "CHATGPT_", "DEEPSEEK_", "GLM_"))
                    and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}}
                environment.update(CODEX_HOME=str(home), OPERATOR_SYNTHETIC_PROBE_KEY="synthetic-probe-key",
                                   OPERATOR_SYNTHETIC_EXTERNAL_KEY="synthetic-external-key",
                                   HTTP_PROXY=f"http://127.0.0.1:{server.server_port}",
                                   HTTPS_PROXY=f"http://127.0.0.1:{server.server_port}",
                                   ALL_PROXY=f"http://127.0.0.1:{server.server_port}",
                                   NO_PROXY="127.0.0.1,localhost,::1")
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen([str(executable), "app-server", "--listen", "stdio://"],
                    cwd=work, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                    creationflags=flags)
                messages, notifications = queue.Queue(), []

                def read_messages():
                    for line in process.stdout:
                        try:
                            messages.put(json.loads(line))
                        except ValueError:
                            messages.put({"error": "invalid_fixture_response"})
                    messages.put(None)

                threading.Thread(target=read_messages, daemon=True).start()
                next_id = 0

                def receive(deadline):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.fail("isolated App Server timed out")
                    try:
                        message = messages.get(timeout=remaining)
                    except queue.Empty:
                        self.fail("isolated App Server timed out")
                    self.assertIsNotNone(message, "isolated App Server exited early")
                    return message

                def send(message):
                    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                    process.stdin.flush()

                def request(method, params):
                    nonlocal next_id
                    next_id += 1
                    send({"jsonrpc": "2.0", "id": next_id, "method": method, "params": params})
                    deadline = time.monotonic() + 20
                    while True:
                        message = receive(deadline)
                        if message.get("id") == next_id:
                            self.assertNotIn("error", message, method)
                            return message["result"]
                        notifications.append(message)

                def wait_turn(thread_id, turn_id):
                    deadline = time.monotonic() + 20
                    while True:
                        for index, message in enumerate(notifications):
                            params = message.get("params") or {}
                            if (message.get("method") == "turn/completed" and
                                    params.get("threadId") == thread_id and
                                    (params.get("turn") or {}).get("id") == turn_id):
                                notifications.pop(index)
                                return params["turn"]
                        notifications.append(receive(deadline))

                try:
                    request("initialize", {"clientInfo": {"name": "operator_synthetic_probe",
                        "title": "Operator synthetic probe", "version": "1"}})
                    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
                    listed = request("model/list", {"includeHidden": False, "limit": 100})
                    listed_models = {row["model"] for row in listed["data"]}
                    self.assertEqual(listed_models, {"probe-a", second_slug, "beeper"}
                                     if use_router else {"probe-a", "probe-b"})
                    thread = request("thread/start", {"model": "probe-a", "cwd": str(work),
                        "approvalPolicy": "never", "sandbox": "read-only"})["thread"]
                    thread_id = thread["id"]
                    self.assertEqual(thread["modelProvider"], "operator_probe")
                    turn_ids = []
                    for model, turn_prompt in zip(models, prompts):
                        turn = request("turn/start", {"threadId": thread_id, "model": model,
                            "effort": "medium" if web_model and model == second_slug else "low",
                            "input": [{"type": "text", "text": turn_prompt}]})["turn"]
                        turn_ids.append(turn["id"])
                        completed = wait_turn(thread_id, turn["id"])
                        self.assertEqual(completed["status"], "completed",
                                         {"error": completed.get("error"),
                                          "router_failure": router.last_failure if use_router else None,
                                          "received_count": len(received)})
                        if use_router:
                            windows = [(message.get("params") or {}).get("tokenUsage", {}).get("modelContextWindow")
                                for message in notifications
                                if message.get("method") == "thread/tokenUsage/updated"
                                and (message.get("params") or {}).get("turnId") == turn["id"]]
                            if not web_model or model == "probe-a":
                                # The Web route has no verified context window.
                                self.assertIn(32000 if model == "probe-a" else 15200, windows,
                                              "current CLI must apply each verified context budget")
                    self.assertEqual(len(set(turn_ids)), len(turn_ids))
                    self.assertFalse(unexpected, "only the synthetic provider endpoint may be contacted")
                    self.assertTrue(received)
                    self.assertTrue(all(row["stream"] is True for row in received))
                    business_rows = []
                    for turn_id, chosen in zip(turn_ids, models):
                        calls = [row for row in received if row["turn_id"] == turn_id]
                        upstream_model = ("gpt-5.6-sol" if web_model and chosen == second_slug else
                                          "upstream-probe-b" if use_router and chosen == second_slug else chosen)
                        self.assertTrue(any(row["model"] == upstream_model and row["kind"] == "business"
                                            for row in calls), "new user input must reach the selected model")
                        self.assertFalse(any(row["model"] != upstream_model and row["kind"] == "business"
                                             for row in calls), "old model may only receive a checkpoint")
                        self.assertTrue(all(row["kind"] in {"business", "checkpoint"} for row in calls))
                        if round_trip:
                            business = [row for row in calls if row["kind"] == "business"]
                            self.assertEqual(len(business), 1,
                                             "one new input must cause exactly one business dispatch")
                            business_rows.append(business[0])
                    if round_trip:
                        self.assertEqual([row["request_text"] for row in business_rows], list(prompts))
                        for index in (1, 2):
                            submitted = json.dumps(business_rows[index]["input"], ensure_ascii=False)
                            for earlier in business_rows[:index]:
                                self.assertIn(earlier["request_text"], submitted,
                                              "new model must receive prior user context")
                                self.assertIn(earlier["reply"], submitted,
                                              "new model must receive prior assistant context")
                    expected_endpoints = ({"probe-a": ("/native/v1/responses", "Bearer synthetic-probe-key"),
                                           "gpt-5.6-sol" if web_model else "upstream-probe-b":
                                           ("/external/v1/responses", "Bearer synthetic-external-key")}
                                          if use_router else {"probe-a": ("/v1/responses", "Bearer synthetic-probe-key"),
                                                              "probe-b": ("/v1/responses", "Bearer synthetic-probe-key")})
                    self.assertTrue(all((row["path"], row["auth"]) == expected_endpoints[row["model"]]
                                        for row in received))
                    failed = request("turn/start", {"threadId": thread_id, "model": second_slug,
                        "effort": "medium" if web_model else "low",
                        "input": [{"type": "text", "text": size_prompt}]})["turn"]
                    failure = wait_turn(thread_id, failed["id"])
                    self.assertEqual(failure["status"], "failed")
                    self.assertIsNotNone(failure.get("error"))
                    self.assertEqual([row["kind"] for row in received if row["turn_id"] == failed["id"]],
                                     ["size"], "a custom provider's explicit zero retry budget must not replay 413")
                    retained = request("thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
                    self.assertEqual(retained["id"], thread_id)
                    if use_router:
                        self.assertTrue(all(any(row["id"] == turn_id and row["status"] == "completed"
                                                for row in retained["turns"]) for turn_id in turn_ids),
                                        "all model turns must remain visible in the same task")
                        self.assertIn(prompt, json.dumps(retained["turns"]),
                                      "previous user input must remain in native task history")
                    self.assertTrue(any(turn["id"] == failed["id"] and turn["status"] == "failed"
                                        for turn in retained["turns"]), "the failed synthetic turn must remain")
                    self.assertFalse(unexpected)
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=3)
                    process.stdout.close()
        finally:
            if router_loop is not None and router_thread is not None:
                router_loop.call_soon_threadsafe(router_loop.stop)
                router_thread.join(timeout=5)
            if router_env is not None:
                router_env.stop()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
