"""Opt-in local probe for an OpenAI-named provider with Codex backend paths.

Uses a disposable Codex home, synthetic API-key auth and loopback endpoints only.
It does not inspect or modify the signed-in Desktop account.
"""

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
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_responses_events import events_for, wire
from operator_core.responses_events import completed_response_events

_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "scripts"))
from operator_core.model_registry import ModelRegistry

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from operator_core.model_router import ModelRouter
except ImportError:
    web = None


TOKEN = "a" * 64
BASE_PATH = f"/{TOKEN}/backend-api/codex"
MODEL = "synthetic-native-aux"
ACCESS_TOKEN = "synthetic-api-key"


@unittest.skipUnless(web is not None and os.environ.get("CODEX_OPERATOR_TEST_CLI"),
                     "explicit installed CLI and optional aiohttp required")
class NamedOpenAiProviderAuxCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_key_auth_and_standalone_search_use_named_provider_path(self):
        await self._exercise("search")

    async def test_named_provider_keeps_capacity_413_single_attempt(self):
        await self._exercise("capacity")

    async def test_compatible_provider_preserves_standalone_search(self):
        await self._exercise("search", provider_name="Codex Operator")

    async def test_compatible_provider_keeps_capacity_413_single_attempt(self):
        await self._exercise("capacity", provider_name="Codex Operator")

    async def test_client_compaction_and_continuation_through_adapted_route(self):
        await self._exercise_client_compaction(auto=False)

    async def test_client_compaction_retains_paired_function_history_without_current_tools(self):
        await self._exercise_client_compaction(auto=False, function_history=True)

    async def test_automatic_client_compaction_before_adapted_continuation(self):
        await self._exercise_client_compaction(auto=True)

    async def test_automatic_client_compaction_preserves_native_route(self):
        await self._exercise_client_compaction(auto=True, native=True)

    async def _exercise_client_compaction(self, *, auto, native=False, function_history=False):
        """The installed official client owns summarization and history replacement."""
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        calls, unexpected, notifications = [], [], []
        answers = ["57", "SYNTHETIC_SUMMARY: The user asked 23 + 34; the answer was 57.", "48"]
        registration = json.loads((_OPERATOR_PLUGIN_ROOT /
            "models/api/examples/glm-5.3-flash.candidate.json").read_text(encoding="utf-8"))
        registration.update(slug="local/compact-fixture", model="compact-fixture", api_key_env="",
                            context_window=131072)
        if function_history:
            registration["responses"]["history_function_tools"] = {"compact_probe": "json_object_v1"}
        selected_model = MODEL if native else registration["slug"]
        row = deepcopy(json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0])
        row.update(slug=selected_model, display_name="Synthetic compaction", comp_hash="compact-fixture",
                   context_window=131072, max_context_window=131072, tool_mode="standard",
                   apply_patch_tool_type=None)

        async def endpoint(request):
            if request.method == "GET" and request.path == "/models":
                return web.json_response({"models": [row]})
            if request.method != "POST" or request.path != "/responses":
                unexpected.append((request.method, request.path))
                return web.Response(status=404)
            calls.append(await request.json())
            answer_index = len(calls) - (2 if function_history else 1)
            if function_history and len(calls) == 1:
                result = {"id": "resp_history_tool", "object": "response", "status": "completed",
                    "output": [{"id": "fc_history_tool", "type": "function_call", "name": "compact_probe",
                        "call_id": "call_compact_probe", "arguments": '{ "label": "synthetic-only" }',
                        "status": "completed"}]}
                return web.json_response(result)
            if answer_index >= len(answers):
                return web.json_response({"error": "unexpected_fixture_request"}, status=400)
            response = {"id": f"resp_compact_{len(calls)}", "object": "response",
                "usage": {"input_tokens": 2000 if auto and len(calls) == 1 else 100,
                          "output_tokens": 1, "total_tokens": 2001 if auto and len(calls) == 1 else 101},
                "status": "completed", "output": [{"id": f"msg_compact_{len(calls)}",
                    "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": answers[answer_index],
                                 "annotations": []}]}]}
            if native:
                return web.Response(body=wire(list(completed_response_events(response))),
                                    content_type="text/event-stream")
            return web.json_response(response)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", endpoint)
        server = TestServer(app)
        await server.start_server()
        registration["api_base"] = str(server.make_url("/")).rstrip("/")
        beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
        router = ModelRouter(ModelRegistry({"version": 2, "models": [registration]}, beeper), TOKEN,
                             native_base=str(server.make_url("/")).rstrip("/"))
        gateway = TestServer(router.app())
        await gateway.start_server()
        child = None
        temporary = tempfile.TemporaryDirectory(prefix="operator-client-compact-")
        try:
            root = Path(temporary.name)
            work, isolated_home = root / "work", root / "home"
            work.mkdir()
            isolated_home.mkdir()
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"models": [row]}), encoding="utf-8")
            settings = {
                "model": selected_model, "model_provider": "operator_compact_probe",
                "model_reasoning_effort": "low", "model_catalog_json": str(catalog),
                "model_auto_compact_token_limit": 1000 if auto else 120000,
                "approval_policy": "never", "web_search": "disabled",
                "cli_auth_credentials_store": "file", "analytics.enabled": False,
                "features.plugins": False, "features.remote_plugin": False,
                "model_providers.operator_compact_probe.name": "Codex Operator",
                "model_providers.operator_compact_probe.base_url": str(gateway.make_url(BASE_PATH)).rstrip("/"),
                "model_providers.operator_compact_probe.wire_api": "responses",
                "model_providers.operator_compact_probe.requires_openai_auth": True,
                "model_providers.operator_compact_probe.request_max_retries": 0,
                "model_providers.operator_compact_probe.stream_max_retries": 0,
                "model_providers.operator_compact_probe.supports_websockets": False,
            }
            command = [str(executable), "app-server", "--listen", "stdio://"]
            for key, value in settings.items():
                command += ["-c", key + "=" + json.dumps(value)]
            environment = {key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
                                   "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                   "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}}
            environment.update(CODEX_HOME=str(isolated_home),
                HTTP_PROXY=str(server.make_url("/")), HTTPS_PROXY=str(server.make_url("/")),
                ALL_PROXY=str(server.make_url("/")), NO_PROXY="127.0.0.1,localhost,::1")
            flags = 0x08000000 if os.name == "nt" else 0
            login = subprocess.run([str(executable), "login", "--with-api-key"],
                input=ACCESS_TOKEN + "\n", text=True, cwd=work, env=environment,
                capture_output=True, timeout=10, creationflags=flags)
            self.assertEqual(login.returncode, 0, "synthetic key setup failed in disposable home")
            child = await asyncio.create_subprocess_exec(*command, cwd=str(work), env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, creationflags=flags)

            async def read_message():
                line = await asyncio.wait_for(child.stdout.readline(), timeout=15)
                self.assertTrue(line, "isolated client exited")
                message = json.loads(line)
                if "method" in message:
                    notifications.append(message)
                if function_history and message.get("method") == "item/tool/call":
                    params = message["params"]
                    self.assertEqual((params["tool"], params.get("namespace"), params["callId"], params["arguments"]),
                                     ("compact_probe", None, "call_compact_probe", {"label": "synthetic-only"}))
                    # A synthetic client result; no terminal, file or external tool runs.
                    reply = {"id": message["id"], "result": {"success": True,
                        "contentItems": [{"type": "inputText", "text": "SYNTHETIC_RESULT: 57"}]}}
                    child.stdin.write((json.dumps(reply) + "\n").encode())
                    await child.stdin.drain()
                return message

            async def request(request_id, method, params):
                child.stdin.write((json.dumps({"jsonrpc": "2.0", "id": request_id,
                    "method": method, "params": params}) + "\n").encode())
                await child.stdin.drain()
                for _ in range(200):
                    message = await read_message()
                    if message.get("id") == request_id:
                        self.assertNotIn("error", message, (method, message))
                        return message["result"]
                self.fail(f"no response to {method}")

            async def completed_since(offset):
                for _ in range(200):
                    completed = [message for message in notifications[offset:]
                                 if message.get("method") == "turn/completed"]
                    if completed:
                        self.assertEqual(completed[-1]["params"]["turn"]["status"], "completed", completed)
                        return
                    await read_message()
                self.fail("no completed turn")

            await request(1, "initialize", {"clientInfo": {"name": "operator_compact_probe", "version": "1"},
                **({"capabilities": {"experimentalApi": True}} if function_history else {})})
            child.stdin.write(b'{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
            await child.stdin.drain()
            started = await request(2, "thread/start", {"cwd": str(work), "approvalPolicy": "never",
                "sandbox": "read-only", "model": selected_model,
                **({"dynamicTools": [{"type": "function", "name": "compact_probe",
                    "description": "Synthetic protocol record only.",
                    "inputSchema": {"type": "object", "properties": {"label": {"type": "string"}},
                                    "required": ["label"], "additionalProperties": False}}]}
                   if function_history else {})})
            thread_id = started["thread"]["id"]
            for request_id, text in ((3, "SYNTHETIC_G1: 23 + 34?"), (5, "SYNTHETIC_G2: subtract 9 from the previous answer.")):
                offset = len(notifications)
                await request(request_id, "turn/start", {"threadId": thread_id,
                    "input": [{"type": "text", "text": text}]})
                await completed_since(offset)
                if request_id == 3 and not auto:
                    offset = len(notifications)
                    await request(4, "thread/compact/start", {"threadId": thread_id})
                    await completed_since(offset)
            self.assertEqual(len(calls), 4 if function_history else 3)
            self.assertTrue(all(body["model"] == (MODEL if native else registration["model"])
                                for body in calls))
            self.assertEqual(unexpected, [])
            self.assertTrue(all(item.get("type") not in {"compaction", "compaction_trigger"}
                                for body in calls for item in body["input"]))
            summary_index = 2 if function_history else 1
            self.assertIn("SYNTHETIC_G1", json.dumps(calls[summary_index]["input"]))
            self.assertIn(answers[1], json.dumps(calls[summary_index + 1]["input"]))
            self.assertIn("SYNTHETIC_G2", json.dumps(calls[summary_index + 1]["input"]))
            if function_history:
                summary = calls[summary_index]
                self.assertFalse(summary.get("tools"))
                paired = [item for item in summary["input"]
                          if item.get("type") in ("function_call", "function_call_output")]
                self.assertEqual(len(paired), 2)
                self.assertEqual([item["call_id"] for item in paired], ["call_compact_probe"] * 2)
                self.assertEqual(paired[0]["arguments"], '{ "label": "synthetic-only" }')
                self.assertIn("SYNTHETIC_RESULT: 57", str(paired[1]["output"]))
            compactions = [message for message in notifications if message.get("method") == "item/completed"
                           and message["params"]["item"].get("type") == "contextCompaction"]
            self.assertEqual(len(compactions), 1)
            messages = [message["params"]["item"] for message in notifications
                        if message.get("method") == "item/completed"
                        and message["params"]["item"].get("type") == "agentMessage"]
            self.assertEqual(messages[-1]["text"], "48")
        finally:
            if child is not None and child.returncode is None:
                child.terminate()
                try:
                    await asyncio.wait_for(child.wait(), timeout=5)
                except asyncio.TimeoutError:
                    child.kill()
                    await child.wait()
            await gateway.close()
            await server.close()
            temporary.cleanup()

    async def test_model_catalog_url_reads_router_alias_without_model_turn(self):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        catalog_calls = []
        unexpected = []
        row = deepcopy(json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0])
        row.update(slug=MODEL, display_name="Synthetic Native Auxiliary", description="Local fixture only",
                   comp_hash=MODEL, context_window=32000, max_context_window=32000,
                   tool_mode="standard", supports_search_tool=True)

        async def endpoint(request):
            if request.method == "GET" and request.path == "/models":
                catalog_calls.append({"authorized": request.headers.get("Authorization") ==
                                      "Bearer " + ACCESS_TOKEN, "query": request.query_string})
                return web.json_response({"models": [row]})
            unexpected.append((request.method, request.path))
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", endpoint)
        server = TestServer(app)
        await server.start_server()
        beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
        router = ModelRouter(ModelRegistry({"version": 1, "models": []}, beeper), TOKEN,
                             native_base=str(server.make_url("/")).rstrip("/"))
        gateway = TestServer(router.app())
        await gateway.start_server()
        child = None
        try:
            with tempfile.TemporaryDirectory(prefix="operator-named-provider-catalog-") as directory:
                root = Path(directory)
                work, isolated_home = root / "work", root / "home"
                work.mkdir()
                isolated_home.mkdir()
                base_url = str(gateway.make_url(BASE_PATH)).rstrip("/")
                (isolated_home / "config.toml").write_text(
                    'model = ' + json.dumps(MODEL) + '\n'
                    'model_provider = "operator_named_probe"\n'
                    'cli_auth_credentials_store = "file"\n'
                    '[features]\napi_key_model_discovery = true\nplugins = false\nremote_plugin = false\n'
                    '[analytics]\nenabled = false\n'
                    '[model_providers.operator_named_probe]\n'
                    'name = "OpenAI"\nbase_url = ' + json.dumps(base_url) + '\n'
                    'model_catalog_url = ' + json.dumps(base_url + "/models") + '\n'
                    'wire_api = "responses"\nrequires_openai_auth = true\n'
                    'request_max_retries = 0\nstream_max_retries = 0\nsupports_websockets = false\n',
                    encoding="utf-8")
                environment = {key: value for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
                                       "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                       "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}}
                environment.update(CODEX_HOME=str(isolated_home),
                    HTTP_PROXY=str(server.make_url("/")), HTTPS_PROXY=str(server.make_url("/")),
                    ALL_PROXY=str(server.make_url("/")), NO_PROXY="127.0.0.1,localhost,::1")
                flags = 0x08000000 if os.name == "nt" else 0
                login = subprocess.run([str(executable), "login", "--with-api-key"],
                    input=ACCESS_TOKEN + "\n", text=True, cwd=work, env=environment,
                    capture_output=True, timeout=10, creationflags=flags)
                self.assertEqual(login.returncode, 0, "synthetic key setup failed in disposable home")
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

                try:
                    await request(1, "initialize", {"clientInfo": {"name": "operator_catalog_probe",
                        "title": "Operator catalog probe", "version": "1"}})
                    child.stdin.write(b'{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
                    await child.stdin.drain()
                    listed = await request(2, "model/list", {"includeHidden": False, "limit": 100})
                    details = {"catalog_calls": catalog_calls, "unexpected": unexpected,
                               "listed_models": [entry.get("model") for entry in listed["data"]]}
                    self.assertIn(MODEL, details["listed_models"], details)
                    self.assertGreaterEqual(len(catalog_calls), 1, details)
                    self.assertTrue(all(call["authorized"] and "client_version=" in call["query"]
                                        for call in catalog_calls), details)
                    self.assertEqual(unexpected, [], details)
                finally:
                    if child.returncode is None:
                        child.terminate()
                        try:
                            await asyncio.wait_for(child.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            child.kill()
                            await child.wait()
        finally:
            if child is not None and child.returncode is None:
                child.terminate()
                try:
                    await asyncio.wait_for(child.wait(), timeout=5)
                except asyncio.TimeoutError:
                    child.kill()
                    await child.wait()
            await gateway.close()
            await server.close()

    async def _exercise(self, case, *, provider_name="OpenAI"):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        calls = []
        search_calls = []
        catalog_calls = []
        unexpected = []
        search_output = "SYNTHETIC_NATIVE_SEARCH_RESULT"

        row = deepcopy(json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0])
        row.update(slug=MODEL, display_name="Synthetic Native Auxiliary", description="Local fixture only",
                   comp_hash=MODEL, context_window=32000, max_context_window=32000,
                   tool_mode="standard", supports_search_tool=True)

        async def endpoint(request):
            path = request.path
            authorized = (request.headers.get("Authorization") == "Bearer " + ACCESS_TOKEN
                and request.headers.get("ChatGPT-Account-ID") is None)
            if request.method == "GET" and path == "/models":
                catalog_calls.append({"authorized": authorized, "query": request.query_string})
                return web.json_response({"models": [row]})
            if request.method != "POST":
                unexpected.append((request.method, path))
                return web.Response(status=404)
            if path == "/alpha/search" and case == "search":
                search_calls.append({"authorized": authorized, "body": await request.json()})
                return web.json_response({"output": search_output,
                                          "encrypted_output": None, "results": []})
            if path != "/responses":
                unexpected.append((request.method, path))
                return web.Response(status=404)
            payload = await request.json()
            calls.append({"authorized": authorized, "path": path, "body": payload})
            if case == "capacity":
                return web.json_response({"error": {"type": "invalid_request_error",
                    "code": "synthetic_capacity_413", "message": "Synthetic capacity limit"}}, status=413)
            if len(calls) == 1:
                tools = [tool for tool in payload.get("tools", [])
                    if tool.get("type") == "namespace" and tool.get("name") == "web"
                    and any(child.get("name") == "run" for child in tool.get("tools", []))]
                if len(tools) != 1:
                    return web.json_response({"error": "synthetic_web_run_missing"}, status=400)
                item = {"id": "fc_native_aux", "type": "function_call", "call_id": "call_native_aux",
                    "name": "run", "namespace": "web", "status": "completed",
                    "arguments": json.dumps({"search_query": [{"q": "synthetic-native-query"}],
                                             "response_length": "short"}, separators=(",", ":"))}
                return web.Response(body=wire(events_for(item)), content_type="text/event-stream")
            outputs = [item for item in payload.get("input", [])
                if item.get("type") == "function_call_output"
                and item.get("call_id") == "call_native_aux"]
            if len(outputs) != 1 or search_output not in json.dumps(outputs[0]):
                return web.json_response({"error": "synthetic_search_result_missing"}, status=400)
            item = {"id": "msg_native_aux", "type": "message", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text",
                    "text": "SYNTHETIC_NATIVE_AUX_VERIFIED", "annotations": []}]}
            response = {"id": "resp_native_aux", "object": "response", "status": "completed",
                        "output": [item]}
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                {"type": "response.output_item.added", "output_index": 0,
                 "item": {**item, "status": "in_progress", "content": []}},
                {"type": "response.output_text.delta", "item_id": item["id"],
                 "output_index": 0, "content_index": 0, "delta": "SYNTHETIC_NATIVE_AUX_VERIFIED"},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            return web.Response(body=wire(events), content_type="text/event-stream")

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", endpoint)
        server = TestServer(app)
        await server.start_server()
        beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
        router = ModelRouter(ModelRegistry({"version": 1, "models": []}, beeper), TOKEN,
                             native_base=str(server.make_url("/")).rstrip("/"))
        gateway = TestServer(router.app())
        await gateway.start_server()
        child = None
        try:
            with tempfile.TemporaryDirectory(prefix="operator-named-provider-aux-") as directory:
                root = Path(directory)
                work, isolated_home = root / "work", root / "home"
                work.mkdir()
                isolated_home.mkdir()
                catalog = root / "catalog.json"
                catalog.write_text(json.dumps({"models": [row]}), encoding="utf-8")
                settings = {
                    "model": MODEL, "model_provider": "operator_named_probe",
                    "model_reasoning_effort": "low", "model_catalog_json": str(catalog),
                    "approval_policy": "never", "web_search": "cached" if case == "search" else "disabled",
                    "cli_auth_credentials_store": "file", "analytics.enabled": False,
                    "features.plugins": False, "features.remote_plugin": False,
                    "features.standalone_web_search": case == "search",
                    "model_providers.operator_named_probe.name": provider_name,
                    "model_providers.operator_named_probe.base_url": str(gateway.make_url(BASE_PATH)).rstrip("/"),
                    "model_providers.operator_named_probe.wire_api": "responses",
                    "model_providers.operator_named_probe.requires_openai_auth": True,
                    "model_providers.operator_named_probe.request_max_retries": 0,
                    "model_providers.operator_named_probe.stream_max_retries": 0,
                    "model_providers.operator_named_probe.supports_websockets": False,
                    "model_providers.operator_named_probe.supports_standalone_web_search": case == "search",
                }
                command = [str(executable), "exec", "--ephemeral", "--ignore-user-config",
                    "--ignore-rules", "--skip-git-repo-check", "--color", "never",
                    "--sandbox", "read-only", "-C", str(work)]
                for key, value in settings.items():
                    command += ["-c", key + "=" + json.dumps(value)]
                command += ["Synthetic native auxiliary fixture. Complete the requested test once."]
                environment = {key: value for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
                                       "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                       "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}}
                environment.update(CODEX_HOME=str(isolated_home),
                    HTTP_PROXY=str(server.make_url("/")), HTTPS_PROXY=str(server.make_url("/")),
                    ALL_PROXY=str(server.make_url("/")), NO_PROXY="127.0.0.1,localhost,::1")
                login = subprocess.run([str(executable), "login", "--with-api-key"],
                    input=ACCESS_TOKEN + "\n", text=True, cwd=work, env=environment,
                    capture_output=True, timeout=10,
                    creationflags=0x08000000 if os.name == "nt" else 0)
                self.assertEqual(login.returncode, 0, "synthetic key setup failed in disposable home")
                child = await asyncio.create_subprocess_exec(*command, cwd=str(work), env=environment,
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=0x08000000 if os.name == "nt" else 0)
                try:
                    stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=35)
                finally:
                    if child.returncode is None:
                        child.kill()
                        await child.wait()
                details = {"exit_code": child.returncode, "calls": len(calls),
                           "search_calls": len(search_calls), "catalog_calls": len(catalog_calls),
                           "unexpected": unexpected,
                           "first_tools": [{"type": tool.get("type"), "name": tool.get("name"),
                                            "description_prefix": tool.get("description", "")[:48],
                                            "nested_tools": [{"type": nested.get("type"), "name": nested.get("name")}
                                                             for nested in tool.get("tools", [])]}
                                           for tool in (calls[0]["body"].get("tools", []) if calls else [])],
                           "stderr_tail": stderr.decode("utf-8", errors="replace")[-1500:]}
                self.assertFalse(unexpected, details)
                self.assertTrue(all(call["authorized"] and call["path"] == "/responses"
                                    for call in calls), details)
                self.assertGreaterEqual(len(catalog_calls), 1, details)
                self.assertTrue(all(call["authorized"] for call in catalog_calls), details)
                if case == "capacity":
                    self.assertEqual(len(calls), 1, details)
                    self.assertEqual(child.returncode, 1, details)
                    self.assertEqual(search_calls, [], details)
                else:
                    self.assertEqual(child.returncode, 0, details)
                    self.assertEqual(len(calls), 2, details)
                    self.assertEqual(len(search_calls), 1, details)
                    self.assertTrue(search_calls[0]["authorized"], details)
                    self.assertEqual(search_calls[0]["body"]["commands"]["search_query"],
                                     [{"q": "synthetic-native-query"}])
                    self.assertIn(b"SYNTHETIC_NATIVE_AUX_VERIFIED", stdout)
        finally:
            if child is not None and child.returncode is None:
                child.kill()
                await child.wait()
            await gateway.close()
            await server.close()


if __name__ == "__main__":
    unittest.main()
