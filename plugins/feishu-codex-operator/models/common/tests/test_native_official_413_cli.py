"""Opt-in isolated probe of the current CLI's built-in OpenAI provider and router 413s.

No real Codex home, credentials, Desktop process or remote endpoint is used.
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

try:
    from aiohttp import web
    from operator_core.model_registry import ModelRegistry
    from operator_core.model_router import ModelRouter
    from operator_core import model_router
except ImportError:
    web = ModelRegistry = ModelRouter = model_router = None


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI") and ModelRouter is not None,
                     "explicit installed CLI and optional router dependencies required")
class CurrentCliOfficial413Tests(unittest.TestCase):
    def test_official_provider_upstream_and_local_413_are_measured_separately(self):
        self._check_413(provider_id="openai")

    def test_custom_provider_openai_auth_has_explicit_zero_retry_budget(self):
        self._check_413(provider_id="operator_auth_probe")

    def _check_413(self, *, provider_id):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        template = json.loads((_OPERATOR_PLUGIN_ROOT /
            "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))["models"][0]
        row = deepcopy(template)
        row.update(slug="synthetic-official-413", display_name="Synthetic Official 413",
                   description="Local fixture only", comp_hash="synthetic-official-413",
                   context_window=32000, max_context_window=32000)
        catalog = {"models": [row]}
        received = []
        ws_handshakes = []
        unexpected = []

        class FixtureHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_CONNECT(self):
                unexpected.append("unexpected_connect")
                self.send_error(403)

            def do_GET(self):
                if self.path.split("?", 1)[0] == "/native/v1/responses":
                    ws_handshakes.append(1)
                    self.send_error(426)
                    return
                if self.path.split("?", 1)[0] != "/native/v1/models":
                    unexpected.append("unexpected_get")
                    self.send_error(404)
                    return
                data = json.dumps(catalog).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if self.path.split("?", 1)[0] != "/native/v1/responses":
                    unexpected.append("unexpected_post")
                    self.send_error(404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(size)
                payload = json.loads(body)
                received.append({"body_size": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                    "model": payload.get("model"),
                    "authorized": self.headers.get("Authorization") ==
                        "Bearer fixture-key"})
                data = json.dumps({"error": {"type": "invalid_request_error",
                    "code": "synthetic_upstream_413", "message": "Synthetic upstream size limit"}}).encode()
                self.send_response(413)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        router_loop = asyncio.new_event_loop()
        router_thread = None
        try:
            beeper = json.loads((_OPERATOR_PLUGIN_ROOT /
                "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
            registry = ModelRegistry({"version": 1, "models": []}, beeper)
            router = ModelRouter(registry, "a" * 64,
                native_base=f"http://127.0.0.1:{server.server_port}/native/v1")
            router_hits = []
            app = router.app()

            @web.middleware
            async def record_requests(request, handler):
                if request.path.endswith("/responses"):
                    router_hits.append(request.method)
                return await handler(request)

            app.middlewares.insert(0, record_requests)
            ready = queue.Queue(maxsize=1)

            def run_router():
                asyncio.set_event_loop(router_loop)

                async def start():
                    runner = web.AppRunner(app)
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
            with tempfile.TemporaryDirectory(prefix="operator-official-413-") as directory:
                root = Path(directory)
                home, work = root / "home", root / "work"
                home.mkdir()
                work.mkdir()
                catalog_file = home / "catalog.json"
                catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
                provider_url = f'http://127.0.0.1:{router_port}/{"a" * 64}/v1'
                builtin_url = f'openai_base_url = "{provider_url}"\n' if provider_id == "openai" else ''
                custom_provider = ('' if provider_id == "openai" else
                    '[model_providers.operator_auth_probe]\n'
                    'name = "Operator synthetic auth route"\n'
                    f'base_url = "{provider_url}"\n'
                    'wire_api = "responses"\nrequires_openai_auth = true\n'
                    'request_max_retries = 0\nstream_max_retries = 0\n'
                    'supports_websockets = false\n')
                (home / "config.toml").write_text(
                    f'model = "synthetic-official-413"\nmodel_provider = "{provider_id}"\n'
                    'model_reasoning_effort = "low"\napproval_policy = "never"\n'
                    'sandbox_mode = "read-only"\nweb_search = "disabled"\n'
                    'model_catalog_json = ' + json.dumps(str(catalog_file)) + '\n'
                    'cli_auth_credentials_store = "file"\n'
                    + builtin_url +
                    '[features]\nplugins = false\nremote_plugin = false\n'
                    '[analytics]\nenabled = false\n' + custom_provider, encoding="utf-8")
                environment = {key: value for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
                                       "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                       "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}}
                environment.update(CODEX_HOME=str(home),
                    HTTP_PROXY=f"http://127.0.0.1:{server.server_port}",
                    HTTPS_PROXY=f"http://127.0.0.1:{server.server_port}",
                    ALL_PROXY=f"http://127.0.0.1:{server.server_port}",
                    NO_PROXY="127.0.0.1,localhost,::1")
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                login = subprocess.run([str(executable), "login", "--with-api-key"],
                    input="fixture-key\n", text=True,
                    cwd=work, env=environment, capture_output=True, timeout=10,
                    creationflags=flags)
                self.assertEqual(login.returncode, 0, "fake key setup failed in disposable home")
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
                    try:
                        message = messages.get(timeout=max(0, deadline - time.monotonic()))
                    except queue.Empty:
                        self.fail("isolated official provider turn timed out")
                    self.assertIsNotNone(message, "isolated App Server exited early")
                    return message

                def send(message):
                    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                    process.stdin.flush()

                def request(method, params):
                    nonlocal next_id
                    next_id += 1
                    send({"jsonrpc": "2.0", "id": next_id, "method": method, "params": params})
                    deadline = time.monotonic() + 30
                    while True:
                        message = receive(deadline)
                        if message.get("id") == next_id:
                            self.assertNotIn("error", message, (method, message))
                            return message["result"]
                        notifications.append(message)

                def wait_turn(thread_id, turn_id):
                    deadline = time.monotonic() + 50
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
                    request("initialize", {"clientInfo": {"name": "operator_413_probe",
                        "title": "Operator 413 probe", "version": "1"}})
                    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
                    listed = request("model/list", {"includeHidden": False, "limit": 100})
                    self.assertIn("synthetic-official-413", {row["model"] for row in listed["data"]})
                    thread = request("thread/start", {"model": "synthetic-official-413",
                        "cwd": str(work), "approvalPolicy": "never", "sandbox": "read-only"})["thread"]
                    self.assertEqual(thread["modelProvider"], provider_id)
                    turn = request("turn/start", {"threadId": thread["id"],
                        "model": "synthetic-official-413", "effort": "low",
                        "input": [{"type": "text", "text": "Synthetic upstream 413 fixture"}]})["turn"]
                    failure = wait_turn(thread["id"], turn["id"])
                    self.assertEqual(failure["status"], "failed", failure)
                    upstream_router_posts = router_hits.count("POST")
                    self.assertGreaterEqual(upstream_router_posts, 1,
                                            "official provider must send an HTTP request to local router")
                    if provider_id != "openai":
                        self.assertEqual(upstream_router_posts, 1,
                                         "the custom provider's explicit zero retries must hold")
                    self.assertEqual(len(received), upstream_router_posts,
                                     "upstream 413 should be passed through on each attempt")
                    self.assertTrue(all(row["authorized"] for row in received))
                    self.assertEqual({row["model"] for row in received}, {"synthetic-official-413"})
                    retained = request("thread/read", {"threadId": thread["id"],
                        "includeTurns": True})["thread"]
                    self.assertTrue(any(row["id"] == turn["id"] and row["status"] == "failed"
                                        for row in retained["turns"]))
                    self.assertEqual(router.last_failure["upstream_status"], 413)

                    # Only the router's HTTP acceptance bound changes. Native
                    # client settings and the upstream fixture remain unchanged.
                    before_router_posts = router_hits.count("POST")
                    before_upstream_posts = len(received)
                    before_ws_handshakes = len(ws_handshakes)
                    with patch.object(model_router, "MAX_NATIVE_HTTP_BODY", 1):
                        local_turn = request("turn/start", {"threadId": thread["id"],
                            "model": "synthetic-official-413", "effort": "low",
                            "input": [{"type": "text", "text": "Synthetic local 413 fixture"}]})["turn"]
                        local_failure = wait_turn(thread["id"], local_turn["id"])
                    self.assertEqual(local_failure["status"], "failed", local_failure)
                    local_router_posts = router_hits.count("POST") - before_router_posts
                    self.assertGreaterEqual(local_router_posts, 1)
                    if provider_id != "openai":
                        self.assertEqual(local_router_posts, 1,
                                         "the custom provider must not replay local 413")
                    self.assertEqual(len(received), before_upstream_posts,
                                     "local 413 must never dispatch its request to upstream")
                    self.assertEqual(router.last_failure["code"], "router_request_too_large")
                    self.assertEqual(router.last_failure["limit_bytes"], 1)
                    retained_after_local = request("thread/read", {"threadId": thread["id"],
                        "includeTurns": True})["thread"]
                    self.assertTrue(any(row["id"] == local_turn["id"] and row["status"] == "failed"
                                        for row in retained_after_local["turns"]))
                    self.assertFalse(unexpected)
                    print(json.dumps({"provider": provider_id,
                        "upstream_413_http_attempts": upstream_router_posts,
                        "upstream_413_ws_handshakes": before_ws_handshakes,
                        "upstream_413_distinct_request_bodies":
                            len({row["body_sha256"] for row in received}),
                        "local_413_http_attempts": local_router_posts,
                        "local_413_ws_handshakes": len(ws_handshakes) - before_ws_handshakes,
                        "local_413_backend_attempts": len(received) - before_upstream_posts,
                        "both_failed_turns_retained": True}, sort_keys=True))
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=3)
                    process.stdout.close()
        finally:
            router_loop.call_soon_threadsafe(router_loop.stop)
            if router_thread is not None:
                router_thread.join(timeout=5)
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
