"""Opt-in current CLI exec contract, isolated home and synthetic loopback only."""

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
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_responses_tools import BEEPER, ROUTE
from test_responses_events import events_for, wire
from operator_core.model_registry import ModelRegistry
from operator_core.responses_tool_adapter import dumps

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from operator_core.model_router import ModelRouter, prepare_request
except ImportError:
    web = None


MCP_FIXTURE = r'''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method, params = request.get("method"), request.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "operator-synthetic-fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "fixture_add", "description": "Add two synthetic small integers.",
            "inputSchema": {"type": "object", "properties": {"left": {"type": "integer"},
                            "right": {"type": "integer"}}, "required": ["left", "right"],
                            "additionalProperties": False}, "annotations": {"readOnlyHint": True}}]}
    elif method == "tools/call" and params.get("name") == "fixture_add":
        args = params.get("arguments", {})
        valid = set(args) == {"left", "right"} and all(type(v) is int and 0 <= v <= 99 for v in args.values())
        result = {"isError": not valid, "content": [{"type": "text", "text":
            "SYNTHETIC_NESTED_SUM_" + str(args["left"] + args["right"]) if valid else "invalid_fixture_input"}]}
    elif method == "ping":
        result = {}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                          "error": {"code": -32601, "message": "fixture_method_not_found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


@unittest.skipUnless(web is not None and os.environ.get("CODEX_OPERATOR_TEST_CLI"),
                     "explicit current Desktop CLI and optional router environment required")
class CurrentCliExecTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_cli_standalone_search_standard_and_code_mode(self):
        for mode in ("standard", "code_mode_only"):
            with self.subTest(mode=mode):
                await self.exercise(' 中文😀 C:\\new\\file\r\n"query" ', "SYNTHETIC_CODEX_SEARCH",
                                    serial_only=True, json_mode=True, standalone_search=mode)

    async def test_current_cli_nested_tool_capability_rejection_roundtrip(self):
        await self.exercise(
            'await tools.view_image({path: FIXTURE_PATH});',
            "view_image is not allowed because you do not support image inputs")

    async def test_current_cli_exec_nested_mcp_and_serial_capability_roundtrip(self):
        await self.exercise(
            'const tool = ALL_TOOLS.find(tool => tool.name.endsWith("__fixture_add")); '
            'if (!tool) throw new Error("synthetic_nested_tool_missing"); '
            'text(await tools[tool.name]({left:17, right:25}));',
            "SYNTHETIC_NESTED_SUM_42", nested_mcp=True, serial_only=True, json_mode=True)

    async def exercise(self, code, expected, nested_mcp=False, serial_only=False, json_mode=False, standalone_search=None):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        received, wire_tools = [], []
        request_retries = 0
        searches = []
        search_commands = {"search_query": [{"q": code, "domains": ["example.invalid"], "recency": 3}],
                           "response_length": "short"}
        search_output = "SYNTHETIC_CODEX_SEARCH\r\n中文 https://example.invalid/source\n  "

        async def search(request):
            searches.append(await request.json())
            self.assertEqual(request.headers.get("Authorization"), "Bearer synthetic-key")
            if len(searches) != 1:
                return web.json_response({"error": "synthetic_no_retry"}, status=409)
            return web.json_response({"output": search_output, "encrypted_output": None, "results": []})

        async def upstream(request):
            nonlocal request_retries
            body = await request.json()
            received.append(body)
            if len(received) > 2:
                request_retries += 1
                return web.json_response({"error": "synthetic_no_retry"}, status=409)
            if len(received) == 1:
                tools = [tool for tool in body.get("tools", [])
                         if tool.get("description", "").startswith(
                             "Tool web.run." if standalone_search == "standard" else "Tool exec.")]
                if len(tools) != 1:
                    return web.json_response({"error": "synthetic_exec_missing"}, status=400)
                arguments = search_commands if standalone_search == "standard" else {"input": (
                    "text(await tools.web__run(" + dumps(search_commands) + "));" if standalone_search else code)}
                item = {"id": "fc_cli", "type": "function_call", "call_id": "call_cli",
                        "name": tools[0]["name"], "status": "completed",
                        "arguments": dumps(arguments)}
                if json_mode:
                    return web.json_response({"id": "resp_cli_call", "object": "response",
                                              "status": "completed", "output": [item]})
                return web.Response(body=wire(events_for(item)), content_type="text/event-stream")
            outputs = [item for item in body.get("input", [])
                       if item.get("type") == "function_call_output" and item.get("call_id") == "call_cli"]
            if len(outputs) != 1 or expected not in dumps(outputs[0].get("output")):
                return web.json_response({"error": "synthetic_exec_output_missing"}, status=400)
            if standalone_search == "standard":
                parts = json.loads(outputs[0]["output"])
                self.assertEqual(parts, [{"type": "input_text", "text": search_output}])
            # This assistant output belongs only to the disposable synthetic CLI
            # test. It is never an Operator/Feishu final-answer transport.
            item = {"id": "msg_cli", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "SYNTHETIC_EXEC_VERIFIED", "annotations": []}]}
            response = {"id": "resp_cli_done", "object": "response", "status": "completed", "output": [item]}
            if json_mode:
                return web.json_response(response)
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                {"type": "response.output_item.added", "output_index": 0,
                 "item": {**item, "status": "in_progress", "content": []}},
                {"type": "response.output_text.delta", "item_id": "msg_cli", "output_index": 0,
                 "content_index": 0, "delta": "SYNTHETIC_EXEC_VERIFIED"},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            return web.Response(body=wire(events), content_type="text/event-stream")

        app = web.Application()
        app.router.add_post("/v1/responses", upstream)
        app.router.add_post("/v1/alpha/search", search)
        server = TestServer(app)
        await server.start_server()
        row = {**deepcopy(ROUTE), "api_base": str(server.make_url("/v1")).rstrip("/")}
        row["responses"].update(structured_tool_outputs=True)
        if standalone_search:
            row["slug"] = "api/search-fixture" if standalone_search == "standard" else "local/search-fixture"
            row["responses"].update(codex_tool_mode=standalone_search, structured_tool_outputs=False,
                                     text_tool_outputs="json_string")
            if standalone_search == "standard":
                row["responses"]["custom_tools"] = {}
        if nested_mcp:
            # Real CLI returns a content-part list; the string-only fixture uses
            # the same explicit compatibility mode needed by local endpoints.
            row["responses"].update(structured_tool_outputs=False, text_tool_outputs="json_string")
        if serial_only:
            row["responses"]["parallel_tool_calls"] = False
        if json_mode:
            row["responses"]["upstream_response_mode"] = "json"
        registry = ModelRegistry({"version": 2, "models": [row]}, BEEPER)
        router = ModelRouter(registry, "c" * 64, native_base=str(server.make_url("/v1")).rstrip("/"))
        gateway = TestServer(router.app())
        await gateway.start_server()
        child = None
        try:
            with tempfile.TemporaryDirectory(prefix="operator-cli-exec-") as directory:
                root = Path(directory)
                work, isolated_home = root / "work", root / "home"
                work.mkdir()
                isolated_home.mkdir()
                fixture = work / "synthetic.png"
                code = code.replace("FIXTURE_PATH", dumps(str(fixture)))
                native = {"models": [{**BEEPER["models"][0], "slug": "synthetic-native"}]}
                catalog = root / "catalog.json"
                catalog.write_text(dumps(registry.merge(native)), encoding="utf-8")
                endpoint = str(gateway.make_url(router.prefix)).rstrip("/")
                settings = {
                    "model": row["slug"], "model_provider": "operator_fixture",
                    "model_reasoning_effort": "low", "model_catalog_json": str(catalog),
                    "approval_policy": "never",
                    "web_search": ("cached" if standalone_search == "standard" else "live") if standalone_search else "disabled",
                    "features.plugins": False,
                    "features.remote_plugin": False,
                    "model_providers.operator_fixture.name": "Operator synthetic fixture",
                    "model_providers.operator_fixture.base_url": endpoint,
                    "model_providers.operator_fixture.wire_api": "responses",
                    "model_providers.operator_fixture.env_key": "OPERATOR_FIXTURE_API_KEY",
                    "model_providers.operator_fixture.request_max_retries": 0,
                    "model_providers.operator_fixture.stream_max_retries": 0,
                    "model_providers.operator_fixture.supports_websockets": False,
                }
                if standalone_search:
                    settings.update({"features.standalone_web_search": True,
                                     "model_providers.operator_fixture.supports_standalone_web_search": True})
                if nested_mcp:
                    settings.update({
                        "mcp_servers.operator_fixture.command": sys.executable,
                        "mcp_servers.operator_fixture.args": ["-u", "-c", MCP_FIXTURE],
                    })
                command = [str(executable), "exec", "--ephemeral", "--ignore-user-config",
                           "--ignore-rules", "--skip-git-repo-check", "--color", "never",
                           "--sandbox", "read-only", "-C", str(work)]
                for key, value in settings.items():
                    command += ["-c", key + "=" + dumps(value)]
                command += ["Synthetic protocol fixture. Execute exactly this code once using exec, then stop: " + code]
                environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(
                    ("CODEX_", "OPENAI_", "CHATGPT_", "DEEPSEEK_", "GLM_"))}
                environment.update(CODEX_HOME=str(isolated_home), OPERATOR_FIXTURE_API_KEY="synthetic-key")
                # These fixtures have only loopback backends. Make that routing
                # explicit for the disposable child, independent of OS proxies.
                environment.update(NO_PROXY="127.0.0.1,localhost,::1", no_proxy="127.0.0.1,localhost,::1")

                def inspect(payload, *args):
                    # Tool definitions only; no prompt, history, paths, auth or output.
                    wire_tools.append([{"type": t.get("type"), "name": t.get("name"),
                                        "format": t.get("format")} for t in payload.get("tools", [])])
                    try:
                        return prepare_request(payload, *args)
                    except ValueError as error:
                        wire_tools.append({"validation_reason": str(error),
                                           "parallel": payload.get("parallel_tool_calls")})
                        raise

                with patch("operator_core.model_router.prepare_request", side_effect=inspect):
                    child = await asyncio.create_subprocess_exec(*command, cwd=str(work), env=environment,
                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        creationflags=0x08000000 if os.name == "nt" else 0)
                    try:
                        stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=45)
                    finally:
                        # Stop the exact disposable child before its home is cleaned.
                        if child.returncode is None:
                            child.kill()
                            await child.wait()
                details = {"exit_code": child.returncode, "request_count": len(received),
                           "wire_tools": wire_tools, "diagnostics": router.last_failure,
                           "synthetic_outputs": [item.get("output") for body in received[1:]
                               for item in body.get("input", []) if item.get("call_id") == "call_cli"
                               and item.get("type") == "function_call_output"],
                           "stderr_tail": stderr.decode("utf-8", errors="replace")[-2500:]}
                self.assertEqual(child.returncode, 0, details)
                self.assertEqual(request_retries, 0)
                self.assertEqual(len(received), 2, details)
                if standalone_search:
                    self.assertEqual(len(searches), 1, details)
                    self.assertEqual(searches[0]["commands"], search_commands)
                    self.assertIs(searches[0]["settings"]["external_web_access"], standalone_search != "standard")
                    self.assertTrue(all(t["type"] != "web_search" for body in received for t in body.get("tools", [])))
                self.assertTrue(all(body["stream"] is (not json_mode) for body in received))
                if serial_only:
                    self.assertTrue(all(body["parallel_tool_calls"] is False for body in received))
                self.assertIn(b"SYNTHETIC_EXEC_VERIFIED", stdout)
        finally:
            if child is not None and child.returncode is None:
                child.kill()
                await child.wait()
            await gateway.close()
            await server.close()


CANCELLATION_MCP_FIXTURE = r'''
import json, os, sys
from pathlib import Path
events = Path(__file__).with_name('mcp-events.jsonl')
def record(value):
    with events.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value) + '\n')
record({'kind': 'started', 'pid': os.getpid()})
for line in sys.stdin:
    request = json.loads(line)
    record({'kind': 'request', 'method': request.get('method'),
            'id': request.get('id'), 'params': request.get('params')})
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'operator-cancel-fixture', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'description': 'Synthetic read-only ' + name,
            'inputSchema': {'type': 'object', 'properties': {'marker': {'type': 'string'}},
                            'required': ['marker'], 'additionalProperties': False},
            'annotations': {'readOnlyHint': True}} for name in ('fixture_wait', 'fixture_next')]}
    elif method == 'tools/call' and params['name'] == 'fixture_wait':
        continue
    elif method == 'tools/call' and params['name'] == 'fixture_next':
        result = {'content': [{'type': 'text', 'text': 'NEW_SYNTHETIC_RESULT'}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


@unittest.skipUnless(web is not None and os.environ.get("CODEX_OPERATOR_TEST_CLI"),
                     "explicit current Desktop CLI and optional router environment required")
class CurrentCliCancellationTests(unittest.IsolatedAsyncioTestCase):
    """Actual native cancellation; synthetic inference, tools and private home only."""

    @asynccontextmanager
    async def native_fixture(self, model, catalog, endpoint, *, tool_timeout=1):
        retained = os.environ.get('CODEX_OPERATOR_TEST_NATIVE_CANCELLATION_CAPTURE')
        temporary = None if retained else tempfile.TemporaryDirectory(prefix='operator-native-cancel-')
        # SQLite in the Windows native child can reject a deeply nested home.
        # Keep exact case attribution in a receipt instead of in a long path.
        case = 'case-' + hashlib.sha256(self._testMethodName.encode()).hexdigest()[:12]
        root = Path(retained).resolve() / case if retained else Path(temporary.name).resolve()
        if retained:
            root.mkdir(parents=True, exist_ok=False)
            (root / 'case.json').write_text(dumps({'test': self._testMethodName}), encoding='utf-8')
        home, work = root / 'home', root / 'work'
        home.mkdir(); work.mkdir()
        fixture = work / 'mcp_fixture.py'
        fixture.write_text(CANCELLATION_MCP_FIXTURE, encoding='utf-8')
        catalog_path = root / 'catalog.json'
        catalog_path.write_text(dumps(catalog), encoding='utf-8')
        settings = {'model': model, 'model_provider': 'operator_fixture',
            'model_catalog_json': str(catalog_path), 'approval_policy': 'never',
            'approvals_reviewer': 'user', 'sandbox_mode': 'read-only', 'analytics.enabled': False,
            'skills.include_instructions': False, 'project_doc_max_bytes': 0,
            'features.plugins': False, 'features.remote_plugin': False,
            'features.goals': False, 'features.multi_agent': False, 'web_search': 'disabled',
            'model_providers.operator_fixture.name': 'Synthetic cancellation fixture',
            'model_providers.operator_fixture.base_url': endpoint,
            'model_providers.operator_fixture.wire_api': 'responses',
            'model_providers.operator_fixture.env_key': 'OPERATOR_FIXTURE_API_KEY',
            'model_providers.operator_fixture.request_max_retries': 0,
            'model_providers.operator_fixture.stream_max_retries': 0,
            'model_providers.operator_fixture.supports_websockets': False,
            'mcp_servers.operator_fixture.command': str(Path(sys._base_executable)),
            'mcp_servers.operator_fixture.args': ['-u', str(fixture)],
            'mcp_servers.operator_fixture.tool_timeout_sec': tool_timeout}
        (home / 'config.toml').write_text(''.join(k + '=' + dumps(v) + '\n'
            for k, v in settings.items()), encoding='utf-8')
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(
            ('CODEX_', 'OPENAI_', 'CHATGPT_', 'DEEPSEEK_', 'GLM_'))}
        environment.update(CODEX_HOME=str(home), OPERATOR_FIXTURE_API_KEY='synthetic-key',
            NO_PROXY='127.0.0.1,localhost,::1', no_proxy='127.0.0.1,localhost,::1')
        child = None
        tasks, received, waiting = [], [], {}
        raw_bytes, sequence = 0, 0

        def retain(name, raw):
            nonlocal raw_bytes
            raw_bytes += len(raw)
            if raw_bytes > 16 * 1024 * 1024:
                raise AssertionError('native cancellation fixture capture bound')
            with (root / (name + '.raw')).open('ab') as stream:
                stream.write(raw)

        async def read():
            try:
                while raw := await child.stdout.readline():
                    retain('server', raw)
                    message = json.loads(raw)
                    received.append(message)
                    self.assertFalse('id' in message and 'method' in message,
                        'unexpected native request: fixture never grants approval')
                    if 'id' in message and message['id'] in waiting:
                        waiting[message['id']].set_result(message)
            finally:
                for future in waiting.values():
                    if not future.done():
                        future.set_exception(RuntimeError('native fixture closed before RPC reply'))

        async def read_errors():
            while raw := await child.stderr.read(65536):
                retain('stderr', raw)

        async def rpc(method, params=None):
            nonlocal sequence
            self.assertIn(method, ('initialize', 'initialized', 'thread/start',
                'mcpServer/tool/call', 'turn/start', 'turn/interrupt'))
            request = {'jsonrpc': '2.0', 'method': method}
            if params is not None:
                request['params'] = params
            identity = None
            if method != 'initialized':
                sequence += 1; identity = sequence
                request['id'] = identity
                waiting[identity] = asyncio.get_running_loop().create_future()
            raw = (dumps(request) + '\n').encode()
            retain('client', raw)
            child.stdin.write(raw)
            await child.stdin.drain()
            return None if identity is None else await asyncio.wait_for(waiting[identity], 20)

        def events():
            path = work / 'mcp-events.jsonl'
            return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

        async def until(check):
            async def observe():
                while not check():
                    self.assertIsNone(child.returncode, 'native fixture exited before observation')
                    for task in tasks:
                        if task.done():
                            task.result()
                    failed = [m for m in received if m.get('method') == 'turn/completed'
                        and m.get('params', {}).get('turn', {}).get('status') == 'failed']
                    self.assertFalse(failed, failed)
                    await asyncio.sleep(.01)
            await asyncio.wait_for(observe(), 20)

        try:
            child = await asyncio.create_subprocess_exec(os.environ['CODEX_OPERATOR_TEST_CLI'],
                'app-server', '--listen', 'stdio://', cwd=work, env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=2 * 1024 * 1024,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            tasks = [asyncio.create_task(read()), asyncio.create_task(read_errors())]
            async with asyncio.timeout(45):
                initialized = await rpc('initialize', {'clientInfo': {'name': 'operator_cancellation_fixture',
                    'version': '1'}, 'capabilities': {'experimentalApi': True}})
                self.assertIn('result', initialized)
                self.assertEqual(Path(initialized['result']['codexHome']), home)
                await rpc('initialized')
                started = await rpc('thread/start', {'model': model, 'modelProvider': 'operator_fixture',
                    'cwd': str(work), 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                    'sandbox': 'read-only', 'ephemeral': True, 'allowProviderModelFallback': False})
                self.assertIn('result', started, started)
                self.assertEqual(started['result']['approvalPolicy'], 'never')
                self.assertEqual(started['result']['sandbox']['type'], 'readOnly')
                self.assertFalse(started['result']['sandbox'].get('networkAccess', False))
                yield SimpleNamespace(rpc=rpc, received=received, events=events, until=until,
                    thread=started['result']['thread']['id'], root=root)
        finally:
            if child is not None:
                child.stdin.close()
                try:
                    await asyncio.wait_for(child.wait(), 8)
                except asyncio.TimeoutError:
                    child.kill(); await child.wait()
                    self.fail('native fixture needed forced cleanup')
                finally:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            raise result
            if temporary is not None:
                temporary.cleanup()
        self.assertEqual(child.returncode, 0)

    def assert_exact_cancellation(self, events):
        notices = [e for e in events if e.get('method') == 'notifications/cancelled']
        calls = [e for e in events if e.get('method') == 'tools/call']
        self.assertEqual(len(notices), 1, events)
        self.assertEqual(len(calls), 1, events)
        self.assertEqual(notices[0]['params']['requestId'], calls[0]['id'])
        self.assertIs(type(notices[0]['params']['requestId']), type(calls[0]['id']))
        self.assertLess(events.index(calls[0]), events.index(notices[0]))

    async def test_current_cli_tool_timeout_cancels_exact_call_and_reuses_mcp_process(self):
        requests = []
        async def unexpected(request):
            requests.append(request.path)
            return web.json_response({'error': 'no_model_request_allowed'}, status=400)
        app = web.Application(); app.router.add_route('*', '/{path:.*}', unexpected)
        server = TestServer(app); await server.start_server()
        try:
            catalog = {'models': [{**BEEPER['models'][0], 'slug': 'synthetic-native'}]}
            async with self.native_fixture('synthetic-native', catalog, str(server.make_url('/v1'))) as native:
                result = await native.rpc('mcpServer/tool/call', {'threadId': native.thread,
                    'server': 'operator_fixture', 'tool': 'fixture_wait', 'arguments': {'marker': 'TIMEOUT_ONCE'}})
                self.assertEqual(result.get('error', {}).get('code'), -32603, result)
                self.assertIn('timed out awaiting tools/call', result['error']['message'])
                await native.until(lambda: any(e.get('method') == 'notifications/cancelled' for e in native.events()))
                self.assert_exact_cancellation(native.events())
                result = await native.rpc('mcpServer/tool/call', {'threadId': native.thread,
                    'server': 'operator_fixture', 'tool': 'fixture_next', 'arguments': {'marker': 'DIFFERENT_NEW_CALL'}})
                self.assertIn('NEW_SYNTHETIC_RESULT', dumps(result))
                self.assertEqual(sum(e['kind'] == 'started' for e in native.events()), 1)
                self.assertEqual(sum(e.get('method') == 'tools/call' for e in native.events()), 2)
                self.assertFalse(any(m.get('method') == 'turn/started' for m in native.received))
                self.assertEqual(requests, [])
        finally:
            await server.close()

    async def test_current_cli_turn_interrupt_cancels_released_mcp_and_new_turn_completes(self):
        requests = []
        async def upstream(request):
            body = await request.json(); requests.append(body)
            index = len(requests)
            if index in (1, 2):
                tools = [t for t in body.get('tools', []) if t.get('description', '').startswith('Tool exec.')]
                self.assertEqual(len(tools), 1, body.get('tools'))
                name = 'fixture_wait' if index == 1 else 'fixture_next'
                code = ('const found = ALL_TOOLS.filter(t => t.name.endsWith("__' + name + '")); '
                    'if (found.length !== 1) throw Error("synthetic_tool_identity"); '
                    'text(await tools[found[0].name]({marker:"' + ('STOP_ONCE' if index == 1 else 'NEW_TURN') + '"}));')
                output = [{'id': 'fc_cancel_' + str(index), 'type': 'function_call',
                    'call_id': 'call_cancel_' + str(index), 'name': tools[0]['name'],
                    'arguments': dumps({'input': code}), 'status': 'completed'}]
            else:
                self.assertEqual(index, 3, 'unexpected extra synthetic dispatch')
                self.assertIn('NEW_SYNTHETIC_RESULT', dumps(body['input']))
                output = [{'id': 'msg_cancel_done', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': 'SYNTHETIC_STOP_NEXT_VERIFIED', 'annotations': []}]}]
            return web.json_response({'id': 'resp_cancel_' + str(index), 'object': 'response',
                'status': 'completed', 'output': output})
        app = web.Application(); app.router.add_post('/v1/responses', upstream)
        server = TestServer(app); await server.start_server()
        row = deepcopy(ROUTE); row['api_base'] = str(server.make_url('/v1')).rstrip('/')
        row['responses'].update(upstream_response_mode='json', structured_tool_outputs=False,
            text_tool_outputs='json_string', parallel_tool_calls=False)
        registry = ModelRegistry({'version': 2, 'models': [row]}, BEEPER)
        router = ModelRouter(registry, 'c' * 64, native_base=str(server.make_url('/v1')).rstrip('/'))
        gateway = TestServer(router.app()); await gateway.start_server()
        try:
            catalog = registry.merge({'models': [{**BEEPER['models'][0], 'slug': 'synthetic-native'}]})
            async with self.native_fixture(row['slug'], catalog,
                    str(gateway.make_url(router.prefix)).rstrip('/'), tool_timeout=30) as native:
                first = await native.rpc('turn/start', {'threadId': native.thread, 'input': [
                    {'type': 'text', 'text': 'Synthetic native Stop fixture: wait for the declared read-only tool.'}]})
                self.assertIn('result', first, first)
                turn = first['result']['turn']['id']
                await native.until(lambda: any(e.get('method') == 'tools/call' for e in native.events()))
                interrupted = await native.rpc('turn/interrupt', {'threadId': native.thread, 'turnId': turn})
                self.assertIn('result', interrupted, interrupted)
                await native.until(lambda: any(e.get('method') == 'notifications/cancelled' for e in native.events()))
                self.assert_exact_cancellation(native.events())
                def terminal(identity):
                    return next((m['params']['turn'] for m in native.received if m.get('method') == 'turn/completed'
                        and m['params']['turn']['id'] == identity), None)
                await native.until(lambda: terminal(turn))
                self.assertEqual(terminal(turn)['status'], 'interrupted')
                second = await native.rpc('turn/start', {'threadId': native.thread, 'input': [
                    {'type': 'text', 'text': 'Different new continuation: call fixture_next once, then finish.'}]})
                self.assertIn('result', second, second)
                new_turn = second['result']['turn']['id']
                self.assertNotEqual(new_turn, turn)
                await native.until(lambda: terminal(new_turn))
                self.assertEqual(terminal(new_turn)['status'], 'completed')
                self.assertIn('SYNTHETIC_STOP_NEXT_VERIFIED', dumps(native.received))
                self.assertEqual(len(requests), 3)
                self.assertEqual(sum(e['kind'] == 'started' for e in native.events()), 1)
                calls = [e for e in native.events() if e.get('method') == 'tools/call']
                self.assertEqual([e['params']['name'] for e in calls], ['fixture_wait', 'fixture_next'])
        finally:
            await gateway.close(); await server.close()


if __name__ == "__main__":
    unittest.main()
