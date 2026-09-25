"""Isolated loopback tests. No Codex process, credential store or real provider."""

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
import gzip
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "scripts"))
from operator_core.model_registry import ModelRegistry, RouterError
from operator_core.beeper_provider import BEEPER_IDENTITY_TEXT

try:
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from yarl import URL
    from operator_core.model_router import ModelRouter
except ImportError:
    aiohttp = None


CATALOG = {"models": [{"slug": "native-test", "display_name": "Native", "visibility": "list",
    "context_window": 123456, "comp_hash": "preserve", "model_messages": {"opaque": ["keep"]},
    "supported_reasoning_levels": [{"effort": "low", "description": "Low"}]}], "opaque": "retain"}
BEEPER = json.loads((_OPERATOR_PLUGIN_ROOT /
    "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
TOKEN = "a" * 64
ROUTE = {"slug": "api/example", "display_name": "Example",
         "model": "upstream-test", "api_base": "http://127.0.0.1:1/v1", "api_key_env": "ROUTER_TEST_KEY",
         "context_window": 32000, "reasoning_efforts": ["low"]}


def registry(*routes):
    return ModelRegistry({"version": 1, "models": list(routes)}, BEEPER)


class RegistryTests(unittest.TestCase):
    def test_merge_preserves_native_and_does_not_mutate_inputs(self):
        original = deepcopy(CATALOG)
        result = registry(ROUTE).merge(CATALOG)
        self.assertEqual(CATALOG, original)
        self.assertEqual(result["models"][:1], original["models"])
        self.assertEqual([r["slug"] for r in result["models"]], ["native-test", "beeper", "api/example"])
        result["models"][0]["model_messages"]["opaque"].append("change")
        self.assertEqual(CATALOG, original)

    def test_collision_is_terminal(self):
        catalog = deepcopy(CATALOG)
        catalog["models"].append({"slug": "beeper"})
        with self.assertRaises(RouterError):
            registry().merge(catalog)

    def test_rejects_unsafe_or_duplicate_routes(self):
        for changes in ({"slug": "native-test"}, {"adapter": "web"},
                        {"api_base": "http://remote.example/v1"},
                        {"api_base": "https://secret@remote.example/v1"},
                        {"api_key_env": "bad-name"}, {"context_window": -1}):
            with self.subTest(changes=changes), self.assertRaises(RouterError):
                registry({**ROUTE, **changes})
        with self.assertRaises(RouterError):
            registry(ROUTE, ROUTE)


@unittest.skipIf(aiohttp is None, "optional router environment is required")
class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.endpoints = []
        self.handshakes = []
        self.redirect_ws = False
        self.response_headers = {}
        self.ws_headers = {}
        self.status = 200
        self.json_response = False
        self.negotiate_compression = False
        self.account_catalogs = {}
        self.http_release = None
        self.http_entered = asyncio.Queue()
        self.stream_body = b'data: {"type":"response.completed"}\n\ndata: [DONE]\n\n'

        async def upstream(request):
            if request.path.endswith("/models"):
                return web.json_response(self.account_catalogs.get(
                    request.headers.get("ChatGPT-Account-Id"), CATALOG))
            if request.method == "GET":
                self.handshakes.append(request.path)
                if self.redirect_ws:
                    return web.Response(status=302, headers={"Location": self.base + "/leak"})
                ws = web.WebSocketResponse()
                ws.headers.update(self.ws_headers)
                if request.headers.get("X-Test-State"):
                    ws.headers["X-Codex-Turn-State"] = request.headers["X-Test-State"]
                await ws.prepare(request)
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        self.received.append((message.data.encode(), dict(request.headers)))
                        await ws.send_str(message.data)
                return ws
            body = await request.read()
            self.endpoints.append(request.raw_path)
            self.received.append((body, dict(request.headers)))
            if self.http_release is not None:
                self.http_entered.put_nowait(request.path)
                await self.http_release.wait()
            if self.negotiate_compression:
                response_body = b'{"synthetic_search_result":true}\n'
                response_headers = {"Content-Type": "application/x-ndjson"}
                if "gzip" in request.headers.get("Accept-Encoding", ""):
                    response_body = gzip.compress(response_body)
                    response_headers["Content-Encoding"] = "gzip"
                return web.Response(body=response_body, headers=response_headers)
            if self.json_response:
                return web.json_response({"id": "resp_test", "object": "response", "created_at": 1,
                    "model": "gpt-5", "status": "completed", "output": [], "usage": {
                    "input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
            if self.status == 302:
                return web.Response(status=302, headers={"Location": self.base + "/leak"})
            return web.Response(status=self.status, body=self.stream_body,
                                headers={"Content-Type": "text/event-stream", "X-Proof": "preserved",
                                         **self.response_headers})

        app = web.Application(handler_args={"auto_decompress": False})
        app.router.add_route("*", "/{path:.*}", upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.base = str(self.upstream.make_url("" )).rstrip("/")

        self.router = ModelRouter(registry({**ROUTE, "api_base": self.base + "/v1"},
            {**ROUTE, "slug": "local/example", "api_key_env": "", "api_base": self.base + "/v1"}),
            TOKEN, native_base=self.base)
        self.client = TestClient(TestServer(self.router.app()))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer native-test-secret", "ChatGPT-Account-Id": "native-account",
                        "Content-Type": "application/json", "X-Test": "preserve-native"}
        self.prefix = self.router.prefix
        self.env = patch.dict(os.environ, {"ROUTER_TEST_KEY": "external-test-secret"})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.client.close()
        await self.upstream.close()

    async def test_local_failures_have_safe_standard_errors_and_no_retry(self):
        cases = [(RuntimeError("private prompt secret"), "internal"),
                 (asyncio.TimeoutError("private endpoint secret"), "timeout"),
                 (aiohttp.ClientConnectionError("private credential secret"), "transport")]
        for exc, category in cases:
            with self.subTest(category=category):
                before = self.router.failure_count
                with patch.object(self.router, "local_response", new=AsyncMock(side_effect=exc)) as invoke:
                    response = await self.client.post(self.prefix + "/responses", json={"model": "beeper", "input": "hello"})
                    self.assertEqual(response.status, 502)
                    result = await response.json()
                    self.assertEqual(result["error"]["code"], "router_" + category + "_no_retry")
                    self.assertEqual(invoke.await_count, 1)
                self.assertEqual(self.router.failure_count, before + 1)
                self.assertEqual(self.router.last_failure, {"phase": "local_response", "category": category,
                                                          "upstream_status": None})
                self.assertNotIn("secret", json.dumps([result, self.router.last_failure]))

    async def test_large_upstream_header_is_preserved(self):
        value = "x" * 16384
        self.response_headers = {"X-Codex-Turn-State": value}
        response = await self.client.post(self.prefix + "/responses", headers=self.headers,
            json={"model": "native-test", "input": "synthetic"}, max_field_size=65536)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["X-Codex-Turn-State"], value)
        self.assertEqual(await response.read(), self.stream_body)
        self.assertEqual(len(self.received), 1)

    async def test_oversized_upstream_header_fails_without_retry(self):
        self.response_headers = {"X-Synthetic-Large": "x" * 65537}
        response = await self.client.post(self.prefix + "/responses", headers=self.headers,
            json={"model": "native-test", "input": "synthetic"})
        self.assertEqual(response.status, 502)
        self.assertEqual((await response.json())["error"]["code"], "router_transport_no_retry")
        self.assertEqual(len(self.received), 1)

    async def test_upstream_502_is_preserved_and_distinguished(self):
        self.status = 502
        self.stream_body = b"upstream original error"
        response = await self.client.post(self.prefix + "/responses", headers=self.headers,
                                          json={"model": "native-test", "input": "test"})
        self.assertEqual(response.status, 502)
        self.assertEqual(await response.read(), self.stream_body)
        self.assertEqual(self.router.last_failure, {"phase": "http_connect", "category": "upstream_http",
                                                  "upstream_status": 502})
        self.assertEqual(len(self.received), 1)

    async def test_catalog_validator_tracks_augmented_body(self):
        import hashlib
        first = await self.client.get(self.prefix + "/models", headers=self.headers)
        body = await first.read()
        etag = first.headers["ETag"]
        self.assertEqual(etag, '"' + hashlib.sha256(body).hexdigest() + '"')
        self.assertEqual(first.headers["Cache-Control"], "no-cache")
        self.assertIn("Authorization", first.headers["Vary"])
        again = await self.client.get(self.prefix + "/models", headers={**self.headers, "If-None-Match": etag})
        self.assertEqual(again.status, 200)
        self.assertEqual(again.headers["ETag"], etag)
        await again.read()
        with patch.dict(CATALOG, {"opaque": "changed"}):
            changed = await self.client.get(self.prefix + "/models", headers=self.headers)
            self.assertNotEqual(changed.headers["ETag"], etag)
            await changed.read()

    async def test_native_catalog_cache_is_scoped_to_chatgpt_account(self):
        second = deepcopy(CATALOG)
        second["models"][0]["slug"] = "native-second-account"
        self.account_catalogs = {"native-account": CATALOG, "second-account": second}
        first = await self.client.post(self.prefix + "/responses", headers=self.headers,
            json={"model": "native-test", "input": "first"})
        self.assertEqual(first.status, 200)
        await first.read()
        second_headers = {**self.headers, "ChatGPT-Account-Id": "second-account"}
        later = await self.client.post(self.prefix + "/responses", headers=second_headers,
            json={"model": "native-second-account", "input": "second"})
        self.assertEqual(later.status, 200)
        await later.read()
        self.assertEqual([json.loads(body)["model"] for body, _ in self.received],
                         ["native-test", "native-second-account"])

    async def test_catalog_and_native_http_are_lossless(self):
        response = await self.client.get(self.prefix + "/models?client_version=0.1.0", headers=self.headers)
        catalog = await response.json()
        self.assertEqual(CATALOG["models"], catalog["models"][:1])
        raw = b'{ "model" : "native-test", "input": [], "future_field": {"opaque":"yes"} }'
        response = await self.client.post(self.prefix + "/responses", data=raw, headers=self.headers)
        self.assertEqual(200, response.status)
        self.assertEqual(b'data: {"type":"response.completed"}\n\ndata: [DONE]\n\n', await response.read())
        self.assertEqual(raw, self.received[0][0])
        self.assertEqual("Bearer native-test-secret", self.received[0][1]["Authorization"])
        self.assertEqual("preserved", response.headers["X-Proof"])

    async def test_external_route_never_receives_native_credentials(self):
        response = await self.client.post(self.prefix + "/responses", json={"model": "api/example", "input": "hello"}, headers=self.headers)
        await response.read()
        body, headers = self.received[0]
        self.assertEqual("upstream-test", json.loads(body)["model"])
        self.assertEqual("Bearer external-test-secret", headers["Authorization"])
        self.assertNotIn("ChatGPT-Account-Id", headers)
        self.assertNotIn("X-Test", headers)

    async def test_unknown_model_never_dispatches(self):
        response = await self.client.post(self.prefix + "/responses", json={"model": "api/unknown", "input": "hello"}, headers=self.headers)
        self.assertEqual(400, response.status)
        self.assertEqual([], self.received)

    async def test_native_auxiliary_endpoints_preserve_opaque_payloads(self):
        for endpoint, body, content_type in (
            ("alpha/search", b'{ "query":"example", "future":true }', "application/json"),
            ("images/generations", b'{"model":"image-model","prompt":"example"}', "application/json"),
            ("images/edits", b'--boundary\r\nContent-Disposition: form-data; name="image"\r\n\r\n\x00\xff\r\n--boundary--\r\n',
             "multipart/form-data; boundary=boundary")):
            response = await self.client.post(URL(self.prefix + "/" + endpoint + "?opaque=a%2Fb", encoded=True), data=body,
                headers={**self.headers, "Content-Type": content_type})
            self.assertEqual(200, response.status)
            await response.read()
            self.assertEqual(body, self.received[-1][0])
            self.assertEqual(content_type, self.received[-1][1]["Content-Type"])
            self.assertEqual("Bearer native-test-secret", self.received[-1][1]["Authorization"])
            self.assertEqual("/" + endpoint + "?opaque=a%2Fb", self.endpoints[-1])

    async def test_auxiliary_routes_reject_missing_auth_wrong_method_and_unknown_path(self):
        response = await self.client.post(self.prefix + "/alpha/search", json={"query": "example"})
        self.assertEqual(400, response.status)
        response = await self.client.get(self.prefix + "/images/edits", headers=self.headers)
        self.assertEqual(405, response.status)
        response = await self.client.post(self.prefix + "/images/unknown", json={}, headers=self.headers)
        self.assertEqual(404, response.status)
        self.assertEqual([], self.received)

    async def test_native_compression_negotiation_preserves_client_absence(self):
        self.negotiate_compression = True
        raw = b'{"synthetic_search_result":true}\n'
        for endpoint in ("alpha/search", "responses"):
            for accepted in (None, "identity", "gzip"):
                with self.subTest(endpoint=endpoint, accepted=accepted):
                    headers = dict(self.headers)
                    if accepted is not None:
                        headers["Accept-Encoding"] = accepted
                    response = await self.client.post(self.prefix + "/" + endpoint,
                        json={"model": "native-test", "input": "synthetic"}, headers=headers,
                        skip_auto_headers={"Accept-Encoding"}, auto_decompress=False)
                    self.assertEqual(200, response.status)
                    body = await response.read()
                    self.assertEqual(accepted, self.received[-1][1].get("Accept-Encoding"))
                    if accepted == "gzip":
                        self.assertEqual("gzip", response.headers.get("Content-Encoding"))
                        self.assertEqual(raw, gzip.decompress(body))
                    else:
                        self.assertNotIn("Content-Encoding", response.headers)
                        self.assertEqual(raw, body)

    async def test_native_compressed_request_and_response_bytes_are_preserved(self):
        try:
            from compression import zstd
        except ImportError:
            from backports import zstd
        raw = b'{ "model":"native-test", "input":[], "future_field":"retain" }'
        self.stream_body = gzip.compress(self.stream_body)
        self.response_headers = {"Content-Encoding": "gzip"}
        for encoding, body in (("gzip", gzip.compress(raw)), ("zstd", zstd.compress(raw))):
            response = await self.client.post(self.prefix + "/responses", data=body,
                headers={**self.headers, "Content-Encoding": encoding}, auto_decompress=False)
            self.assertEqual(200, response.status, await response.text() if response.status != 200 else "")
            self.assertEqual(self.stream_body, await response.read())
            self.assertEqual(body, self.received[-1][0])
            self.assertEqual(encoding, self.received[-1][1]["Content-Encoding"])

    async def test_compressed_external_requests_still_isolate_credentials(self):
        raw = json.dumps({"model": "api/example", "input": "unchanged"}).encode()
        response = await self.client.post(self.prefix + "/responses", data=gzip.compress(raw),
            headers={**self.headers, "Content-Encoding": "gzip"})
        self.assertEqual(200, response.status)
        await response.read()
        body, headers = self.received[0]
        self.assertEqual("unchanged", json.loads(body)["input"])
        self.assertEqual("Bearer external-test-secret", headers["Authorization"])
        self.assertNotIn("Content-Encoding", headers)
        self.assertNotIn("ChatGPT-Account-Id", headers)

    async def test_native_http_above_old_16_mib_limit_preserves_wire_bytes(self):
        self.upstream.app._client_max_size = 65 * 1024 * 1024
        raw = b'{"model":"native-test","input":"' + b'x' * (17 * 1024 * 1024) + b'"}'
        for encoding, body in (("identity", raw), ("gzip", gzip.compress(raw))):
            with self.subTest(encoding=encoding):
                response = await self.client.post(self.prefix + "/responses", data=body,
                    headers={**self.headers, "Content-Encoding": encoding})
                self.assertEqual(200, response.status, await response.text())
                self.assertEqual(body, self.received[-1][0])
                self.assertEqual(encoding, self.received[-1][1]["Content-Encoding"])

    async def test_incomplete_and_oversized_compressed_requests_never_dispatch(self):
        from operator_core import model_router
        for raw, status in ((b"not-gzip", 400), (gzip.compress(b'{"model":"native-test"}')[:-2], 400),
                            (gzip.compress(b"x" * 2048), 413)):
            with patch.object(model_router, "MAX_NATIVE_HTTP_BODY", 1024):
                response = await self.client.post(self.prefix + "/responses", data=raw,
                    headers={**self.headers, "Content-Encoding": "gzip"})
            self.assertEqual(status, response.status)
        self.assertEqual([], self.received)

    async def test_external_large_http_body_keeps_original_limit(self):
        raw = b'{"model":"local/example","input":"' + b'x' * (17 * 1024 * 1024) + b'"}'
        for encoding, body in (("identity", raw), ("gzip", gzip.compress(raw))):
            response = await self.client.post(self.prefix + "/responses", data=body,
                headers={**self.headers, "Content-Encoding": encoding})
            self.assertEqual(413, response.status)
            error = (await response.json())["error"]
            self.assertEqual(error["code"], "router_request_too_large")
            self.assertEqual(error["limit_bytes"], 16 * 1024 * 1024)
            self.assertEqual(error["scope"], "external_request")
        self.assertEqual([], self.received)

    async def test_native_wire_and_decoded_limits_report_413_without_dispatch(self):
        from operator_core import model_router
        raw = b'{"model":"native-test","input":"' + b'x' * 1100 + b'"}'
        with patch.object(model_router, "MAX_NATIVE_HTTP_BODY", 1024), \
                patch.object(self.client.server.app, "_client_max_size", 1025):
            for encoding, body, scope in (("identity", raw, "http_request"),
                                          ("gzip", gzip.compress(raw), "decoded_request")):
                response = await self.client.post(self.prefix + "/responses", data=body,
                    headers={**self.headers, "Content-Encoding": encoding})
                self.assertEqual(413, response.status)
                error = (await response.json())["error"]
                self.assertEqual(error["code"], "router_request_too_large")
                self.assertEqual(error["scope"], scope)
                self.assertEqual(error["limit_bytes"], 1024)
                self.assertEqual(self.router.last_failure['scope'], scope)
                self.assertEqual(self.router.last_failure['limit_bytes'], 1024)
                self.assertEqual(self.router.last_failure['code'], 'router_request_too_large')
                self.assertIn(scope,error['message'])
                self.assertIn('1024',error['message'])
        self.assertEqual([], self.received)

    async def test_native_exact_http_limit_is_accepted(self):
        from operator_core import model_router
        raw = b'{"model":"native-test","input":[]}'
        raw += b' ' * (1024 - len(raw))
        with patch.object(model_router, "MAX_NATIVE_HTTP_BODY", 1024), \
                patch.object(self.client.server.app, "_client_max_size", 1025):
            response = await self.client.post(self.prefix + "/responses", data=raw, headers=self.headers)
            self.assertEqual(200, response.status)
            await response.read()
        self.assertEqual(self.received[0][0], raw)

    async def test_upstream_413_remains_distinct_and_unchanged(self):
        self.status = 413
        self.stream_body = b'{"error":"synthetic upstream size limit"}'
        response = await self.client.post(self.prefix + "/responses",
            json={"model": "native-test", "input": []}, headers=self.headers)
        self.assertEqual(413, response.status)
        self.assertEqual(self.stream_body, await response.read())
        self.assertEqual(len(self.received), 1)

    async def test_identity_works_without_native_credentials(self):
        response = await self.client.post(self.prefix + "/responses", json={"model": "beeper", "input": "hello"})
        self.assertEqual(BEEPER_IDENTITY_TEXT, (await response.json())["output"][0]["content"][0]["text"])
        self.assertEqual([], self.received)

    async def test_request_fields_cannot_override_destination_or_key(self):
        response = await self.client.post(self.prefix + "/responses", json={
            "model": "api/example", "input": "hello", "api_key": "injected",
            "api_base": "https://untrusted.invalid", "num_retries": 99})
        await response.read()
        self.assertEqual(1, len(self.received))
        self.assertEqual("Bearer external-test-secret", self.received[0][1]["Authorization"])

    async def test_local_endpoint_has_no_native_authorization(self):
        response = await self.client.post(self.prefix + "/responses", json={
            "model": "local/example", "input": "hello"}, headers=self.headers)
        await response.read()
        self.assertEqual(200, response.status)
        self.assertNotIn("Authorization", self.received[0][1])

    async def test_standard_nonstreaming_response_and_request_fields(self):
        self.json_response = True
        payload = {"model": "api/example", "input": [{"type": "function_call_output",
            "call_id": "call_example", "output": "原样结果"}], "instructions": "unchanged",
            "tools": [{"type": "function", "name": "example", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "low"}, "text": {"format": {"type": "json_object"}},
            "previous_response_id": "resp_previous", "store": False, "stream": False,
            "future_field": {"keep": True}}
        response = await self.client.post(self.prefix + "/responses", json=payload)
        result = await response.json()
        self.assertEqual(200, response.status, result)
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, len(self.received))
        self.assertEqual("Bearer external-test-secret", self.received[0][1]["Authorization"])
        self.assertEqual({**payload, "model": "upstream-test"}, json.loads(self.received[0][0]))

    async def test_redirect_and_rate_limit_never_retry(self):
        for status in (302, 429):
            self.status = status
            before = len(self.received)
            response = await self.client.post(self.prefix + "/responses", json={"model": "api/example", "input": "hello"})
            await response.read()
            self.assertEqual(400 if status == 302 else 429, response.status)
            self.assertEqual(before + 1, len(self.received))

    async def test_native_compaction_is_opaque(self):
        payload = {"model": "native-test", "input": [{"type": "compaction", "encrypted_content": "opaque"}]}
        response = await self.client.post(self.prefix + "/responses/compact", json=payload, headers=self.headers)
        await response.read()
        self.assertEqual(payload, json.loads(self.received[0][0]))
        response = await self.client.post(self.prefix + "/responses", json={**payload, "model": "local/example"})
        self.assertEqual(400, response.status)
        self.assertEqual(1, len(self.received))

    async def test_token_and_browser_origin_protection(self):
        response = await self.client.get("/v1/models")
        self.assertEqual(404, response.status)
        response = await self.client.get(self.prefix + "/models", headers={"Origin": "http://untrusted.example"})
        self.assertEqual(400, response.status)

    async def wait_for_active(self, count):
        async def settled():
            while self.router.metrics.active != count:
                await asyncio.sleep(0)
        await asyncio.wait_for(settled(), 3)

    async def open_idle_native_websocket(self):
        ws = await self.client.ws_connect(self.prefix + "/responses", headers=self.headers)
        try:
            raw = '{ "type":"response.create", "model":"native-test", "input":[] }'
            await ws.send_str(raw)
            self.assertEqual((await ws.receive(timeout=3)).data, raw)
            return ws
        except BaseException:
            await ws.close()
            raise

    async def test_idle_websocket_capacity_does_not_block_http_search_or_catalog(self):
        sockets = []
        try:
            for _ in range(16):
                sockets.append(await self.open_idle_native_websocket())
            self.assertEqual(self.router.metrics.active, 16)
            self.assertTrue(self.router.websocket_slots.locked())
            self.assertFalse(self.router.http_slots.locked())
            with self.assertRaises(aiohttp.WSServerHandshakeError) as caught:
                await self.client.ws_connect(self.prefix + "/responses", headers=self.headers)
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(len(self.handshakes), 16)

            for endpoint, body in (("responses", b'{ "model":"native-test", "input":[] }'),
                                   ("alpha/search", b'{ "opaque_search":"retain bytes" }')):
                reply = await self.client.post(self.prefix + "/" + endpoint, headers=self.headers, data=body)
                self.assertEqual(reply.status, 200)
                self.assertEqual(await reply.read(), self.stream_body)
                self.assertEqual(self.received[-1][0], body)
                self.assertEqual(self.received[-1][1]["Authorization"], self.headers["Authorization"])
            catalog = await self.client.get(self.prefix + "/models", headers=self.headers)
            self.assertEqual(catalog.status, 200)
            self.assertEqual((await catalog.json())["models"][0], CATALOG["models"][0])

            # Ordinary GET and malformed upgrade requests are short HTTP work,
            # even when the WebSocket pool is full.
            for headers in ({}, {"Upgrade": "websocket", "Connection": "upgrade",
                                 "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "invalid"}):
                reply = await self.client.get(self.prefix + "/responses", headers=headers)
                self.assertEqual(reply.status, 400)
                await reply.read()
            self.assertEqual(self.router.metrics.active, 16)

            # More turns on an existing connection consume no additional slot.
            for turn in range(2):
                raw = json.dumps({"type": "response.create", "model": "native-test", "input": str(turn)})
                await sockets[0].send_str(raw)
                self.assertEqual((await sockets[0].receive(timeout=3)).data, raw)
                self.assertEqual(self.router.metrics.active, 16)
            await sockets.pop(0).close()
            await self.wait_for_active(15)
            sockets.append(await self.open_idle_native_websocket())
            self.assertEqual(self.router.metrics.active, 16)
        finally:
            await asyncio.gather(*(ws.close() for ws in sockets))
        await self.wait_for_active(0)
        self.assertFalse(self.router.websocket_slots.locked())
        self.assertFalse(self.router.http_slots.locked())
        # 17 admitted WS connections and five short HTTP requests; the rejected
        # seventeenth concurrent upgrade never entered active/outcome accounting.
        self.assertEqual(sum(self.router.metrics.outcomes.values()), 22)

    async def test_full_http_capacity_keeps_websocket_budget_and_releases_both(self):
        self.http_release = asyncio.Event()
        pending, sockets = [], []
        try:
            for _ in range(16):
                pending.append(asyncio.create_task(self.client.post(self.prefix + "/responses",
                    headers=self.headers, json={"model": "native-test", "input": "held synthetic request"})))
            await asyncio.wait_for(asyncio.gather(*(self.http_entered.get() for _ in range(16))), 3)
            self.assertEqual(self.router.metrics.active, 16)
            self.assertTrue(self.router.http_slots.locked())
            for method, headers in (("POST", self.headers), ("GET", {}),
                    ("GET", {"Upgrade": "websocket", "Connection": "upgrade",
                             "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "invalid"})):
                reply = await self.client.request(method, self.prefix + "/responses", headers=headers)
                self.assertEqual(reply.status, 503)
                self.assertEqual(await reply.json(), {"error": "router_busy_no_retry"})
            self.assertEqual(len(self.received), 16)

            for _ in range(16):
                sockets.append(await self.open_idle_native_websocket())
            self.assertEqual(self.router.metrics.active, 32)
            self.assertTrue(self.router.http_slots.locked())
            self.assertTrue(self.router.websocket_slots.locked())
            with self.assertRaises(aiohttp.WSServerHandshakeError) as caught:
                await self.client.ws_connect(self.prefix + "/responses", headers=self.headers)
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(len(self.handshakes), 16)
            self.http_release.set()
            replies = await asyncio.wait_for(asyncio.gather(*pending), 3)
            for reply in replies:
                self.assertEqual(reply.status, 200)
                self.assertEqual(await reply.read(), self.stream_body)
            await self.wait_for_active(16)
            # A fresh HTTP operation is admitted after all held requests finish,
            # while every idle WebSocket remains connected.
            reply = await self.client.post(self.prefix + "/alpha/search", headers=self.headers,
                                           data=b'{"synthetic":"search after drain"}')
            self.assertEqual(reply.status, 200)
            await reply.read()
            self.assertEqual(self.router.metrics.active, 16)
        finally:
            self.http_release.set()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*(ws.close() for ws in sockets))
        await self.wait_for_active(0)
        self.assertFalse(self.router.websocket_slots.locked())
        self.assertFalse(self.router.http_slots.locked())
        self.assertEqual(sum(self.router.metrics.outcomes.values()), 33)

    async def test_native_websocket_forwards_only_native_handshake_metadata(self):
        self.ws_headers = {"X-Codex-Turn-State": "synthetic-state", "X-Models-Etag": "synthetic-etag",
                           "Set-Cookie": "private-cookie", "X-Unrelated": "private-value"}
        raw = '{"type":"response.create","model":"native-test","input":[]}'
        async with self.client.ws_connect(self.prefix + "/responses", headers=self.headers) as ws:
            await ws.send_str(raw)
            metadata = await asyncio.wait_for(ws.receive_json(), 3)
            self.assertEqual(metadata, {"type": "response.metadata", "headers": {
                "x-codex-turn-state": "synthetic-state"}})
            catalog_metadata = await asyncio.wait_for(ws.receive_json(), 3)
            self.assertEqual(catalog_metadata, {"type": "codex.response.metadata", "headers": {
                "x-models-etag": "synthetic-etag"}})
            self.assertEqual(raw, (await asyncio.wait_for(ws.receive(), 3)).data)
        self.assertEqual(1, len(self.received))
        self.assertIsNone(self.router.last_failure)

    async def test_concurrent_websocket_metadata_is_connection_local(self):
        async def exchange(state):
            async with self.client.ws_connect(self.prefix + "/responses",
                    headers={**self.headers, "X-Test-State": state}) as ws:
                await ws.send_json({"type": "response.create", "model": "native-test", "input": []})
                metadata = await asyncio.wait_for(ws.receive_json(), 3)
                self.assertEqual(metadata["headers"], {"x-codex-turn-state": state})
                self.assertEqual("response.create", (await asyncio.wait_for(ws.receive_json(), 3))["type"])
        await asyncio.gather(exchange("state-a"), exchange("state-b"))
        self.assertEqual(2, len(self.received))

    async def test_native_websocket_preserves_first_message(self):
        raw = '{ "type":"response.create", "model":"native-test", "input":[] }'
        async with self.client.ws_connect(self.prefix + "/responses", headers=self.headers) as ws:
            await ws.send_str(raw)
            message = await asyncio.wait_for(ws.receive(), 3)
            self.assertEqual(raw, message.data)
        self.assertEqual(raw.encode(), self.received[0][0])

    async def test_native_websocket_redirect_is_not_followed(self):
        self.redirect_ws = True
        async with self.client.ws_connect(self.prefix + "/responses", headers=self.headers) as ws:
            await ws.send_json({"type": "response.create", "model": "native-test", "input": []})
            message = await asyncio.wait_for(ws.receive(), 3)
            self.assertEqual(aiohttp.WSMsgType.CLOSE, message.type)
            self.assertEqual(1011, message.data)
        self.assertEqual(["/responses"], self.handshakes)
        self.assertEqual([], self.received)

    async def test_native_websocket_never_sends_a_later_external_model_to_native(self):
        async with self.client.ws_connect(self.prefix + "/responses", headers=self.headers) as ws:
            await ws.send_json({"type": "response.create", "model": "native-test", "input": []})
            await asyncio.wait_for(ws.receive(), 3)
            await ws.send_json({"type": "response.create", "model": "api/example", "input": []})
            message = await asyncio.wait_for(ws.receive(), 3)
            self.assertEqual(aiohttp.WSMsgType.CLOSE, message.type)
        self.assertEqual(1, len(self.received))

    async def test_external_tool_events_are_preserved_over_http_and_websocket(self):
        events = [
            {"type": "response.created", "response": {"id": "resp_test", "status": "in_progress"}},
            {"type": "response.output_item.added", "output_index": 0, "item": {
                "type": "function_call", "id": "fc_test", "call_id": "call_test", "name": "example"}},
            {"type": "response.function_call_arguments.delta", "item_id": "fc_test",
                "output_index": 0, "delta": '{"text":"你好"}'},
            {"type": "response.completed", "response": {"id": "resp_test", "status": "completed"}}]
        self.stream_body = b"".join(b"event: " + e["type"].encode() + b"\ndata: " +
            json.dumps(e, ensure_ascii=False).encode() + b"\n\n" for e in events)
        response = await self.client.post(self.prefix + "/responses", json={
            "model": "api/example", "input": "hello", "stream": True})
        self.assertEqual(self.stream_body, await response.read())
        async with self.client.ws_connect(self.prefix + "/responses", headers=self.headers) as ws:
            await ws.send_json({"type": "response.create", "model": "api/example", "input": "hello"})
            for event in events:
                self.assertEqual(event, await asyncio.wait_for(ws.receive_json(), 3))
        self.assertEqual(2, len(self.received))

    async def test_truncated_external_websocket_stream_closes_without_retry(self):
        self.stream_body = b'data: {"type":"response.created"}\n\ndata: [DONE]\n\n'
        async with self.client.ws_connect(self.prefix + "/responses") as ws:
            await ws.send_json({"type": "response.create", "model": "api/example", "input": "hello"})
            self.assertEqual("response.created", (await ws.receive_json())["type"])
            message = await asyncio.wait_for(ws.receive(), 3)
            self.assertEqual(aiohttp.WSMsgType.CLOSE, message.type)
            self.assertEqual(1011, message.data)
        self.assertEqual(1, len(self.received))

    async def test_beeper_websocket_emits_identity(self):
        async with self.client.ws_connect(self.prefix + "/responses") as ws:
            await ws.send_json({"type": "response.create", "model": "beeper", "input": "hello"})
            text = ""
            for _ in range(8):
                event = await asyncio.wait_for(ws.receive_json(), 3)
                if event["type"] == "response.output_text.delta":
                    text += event["delta"]
            self.assertEqual(BEEPER_IDENTITY_TEXT, text)


@unittest.skipIf(aiohttp is None, 'optional router environment is required')
class ManagedWebRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from operator_web_model import text_route
        self.base_route = text_route(tools=True)
        self.router = ModelRouter(registry(), TOKEN, web_profile=Path('selected-fixture'))
        self.client = TestClient(TestServer(self.router.app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.prefix = self.router.prefix

    def payload(self, turn='turn', stream=False):
        from test_web_model_protocol import FUNCTION
        return {'model':self.base_route.slug,'input':[{'role':'user','content':'中文\r\n原文'}],
            'tools':[FUNCTION],'reasoning':{'effort':'high'},'stream':stream,
            'client_metadata':{'thread_id':'fixture-thread','turn_id':turn}}

    async def provider(self, browser, generation='b'):
        from dataclasses import replace
        from operator_core.model_registry import WebServiceBinding
        from operator_core.web_mcp_transport import WebResponsesBridge, WebMcpEndpoint
        from operator_core.web_responses_provider import WebResponsesProvider
        bridge = WebResponsesBridge(self.base_route, WebMcpEndpoint(), browser)
        provider = WebResponsesProvider(bridge)
        base = await provider.start()
        self.addAsyncCleanup(provider.stop)
        route = replace(self.base_route, api_base=base, model=self.base_route.slug,
            web_binding=WebServiceBinding('a'*64,generation*64,provider.token))
        return provider, bridge, route

    async def publish(self, route):
        self.router._web_bind_not_before = 0 # Explicit fixture clock boundary only.
        with patch('operator_web_service.resolve_routes', return_value=(route,)) as resolve:
            value = await self.router.bind_web_service({'profile_sha256':route.web_binding.profile_sha256,
                'session_sha256':route.web_binding.session_sha256})
        return value, resolve

    async def ws_response(self, ws, payload):
        await ws.send_json({'type':'response.create',**payload})
        for _ in range(32):
            event = await asyncio.wait_for(ws.receive_json(), 5)
            if event['type'] == 'response.completed':
                return event['response']
        self.fail('missing terminal')

    async def test_real_bridge_http_tools_results_native_auth_isolation_no_double_adaptation(self):
        from test_web_model_protocol import message
        actual = []
        async def browser(turn):
            turn.begin(turn.key)
            actual.append(await turn.invoke(turn.key,1,'inspect',{'value':'  中文\r\n\\"$()'}))
            return message(['  原样\r\n','', '结果'])
        provider, bridge, route = await self.provider(browser)
        await self.publish(route)
        payload = self.payload()
        with patch('operator_core.model_router.prepare_request', side_effect=AssertionError('double conversion')), \
                patch.object(bridge,'exchange', wraps=bridge.exchange) as exchange:
            first = await self.client.post(self.prefix+'/responses', json=payload,
                headers={'Authorization':'Bearer NATIVE_SECRET','ChatGPT-Account-Id':'NATIVE_ACCOUNT'})
            self.assertEqual(first.status,200, await first.text())
            call = (await first.json())['output'][0]
            self.assertEqual(json.loads(call['arguments']), {'value':'  中文\r\n\\"$()'})
            result = {'type':'function_call_output','call_id':call['call_id'],
                'output':[{'type':'input_text','text':'denied\r\n原生结果'}]}
            self.assertEqual(exchange.call_args.args[0], payload)
            payload['input'] += [call,result]
            final = await self.client.post(self.prefix+'/responses', json=payload)
            self.assertEqual(final.status,200, await final.text())
            self.assertEqual([p['text'] for p in (await final.json())['output'][0]['content']],
                ['  原样\r\n','','结果'])
            self.assertEqual(actual,[{'codex_function_result':result}])
            self.assertEqual(exchange.call_args.args[0],payload)
        replay = await self.client.post(self.prefix+'/responses',json=payload)
        self.assertEqual(replay.status,400)
        self.assertEqual((await replay.json())['error']['cause_http_status'],409)
        self.assertEqual((await replay.json())['error']['code'],'web_bridge_turn_consumed_no_retry')
        self.assertEqual(provider.requests,3)

    async def test_websocket_tools_continuation_and_sse(self):
        from test_web_model_protocol import message
        actual = []
        async def browser(turn):
            turn.begin(turn.key)
            actual.append(await turn.invoke(turn.key,1,'inspect',{'value':'same'}))
            return message(['exact\r\nfinal'])
        _, _, route = await self.provider(browser)
        await self.publish(route)
        async with self.client.ws_connect(self.prefix+'/responses') as ws:
            payload = self.payload(stream=True)
            call = (await self.ws_response(ws,payload))['output'][0]
            result = {'type':'function_call_output','call_id':call['call_id'],'output':'refused'}
            payload['input'] += [call,result]
            response = await self.ws_response(ws,payload)
            self.assertEqual(response['output'][0]['content'][0]['text'],'exact\r\nfinal')
            self.assertEqual(actual,[{'codex_function_result':result}])

    async def test_web_terminal_failure_http_and_socket_preserve_partial_results(self):
        from operator_core.web_mcp_transport import WebBrowserNetworkError
        actual = []
        async def browser(turn):
            turn.begin(turn.key)
            actual.append(await turn.invoke(turn.key,1,'inspect',{'value':'before disconnect'}))
            raise WebBrowserNetworkError('net::ERR_CONNECTION_RESET')
        provider, bridge, route = await self.provider(browser)
        await self.publish(route)
        for socket in (False, True):
            payload = self.payload('socket' if socket else 'http')
            if socket:
                ws = await self.client.ws_connect(self.prefix+'/responses')
                call = (await self.ws_response(ws,payload))['output'][0]
            else:
                first = await self.client.post(self.prefix+'/responses',json=payload)
                call = (await first.json())['output'][0]
            result = {'type':'function_call_output','call_id':call['call_id'],'output':'native denial\r\n'}
            payload['input'] += [call,result]
            if socket:
                await ws.send_json({'type':'response.create',**payload})
                failure = await asyncio.wait_for(ws.receive_json(),5)
                self.assertEqual((failure['type'],failure['status']),('error',400))
                error = failure['error']
                await ws.close()
            else:
                response = await self.client.post(self.prefix+'/responses',json=payload)
                self.assertEqual(response.status,400)
                error = (await response.json())['error']
            self.assertEqual(error['cause_http_status'],502)
            self.assertEqual(error['network_error'],'net::ERR_CONNECTION_RESET')
            self.assertFalse(error['retryable'])
            self.assertEqual(error['transport']['turn']['calls_released'],1)
            self.assertEqual(error['transport']['turn']['results_received'],1)
            self.assertFalse(error['transport']['turn']['public_final_returned'])
            self.assertEqual(actual[-1],{'codex_function_result':result})
            self.assertIsNone(bridge.turn)
        self.assertEqual(provider.requests,4)
        self.assertEqual(len(actual),2)

    async def test_invalid_managed_terminal_body_never_becomes_assistant_output(self):
        from test_web_model_protocol import message
        from aiohttp import web
        async def browser(turn):
            return message()
        provider, _, route = await self.provider(browser)
        await self.publish(route)
        for body in ({'error':{'code':'private bad value','message':'bad','retryable':False}},
                     {'error':{'code':'valid_code','message':'x'*65536,'retryable':False}},
                     {'error':{'code':'valid_code','message':'bad','retryable':True}}):
            with patch.object(provider.bridge,'exchange',side_effect=RuntimeError('fixture')), \
                    patch.object(provider,'error',return_value=web.json_response(body,status=400)):
                async with self.client.ws_connect(self.prefix+'/responses') as ws:
                    await ws.send_json({'type':'response.create',**self.payload()})
                    terminal = await asyncio.wait_for(ws.receive(),5)
                    self.assertEqual(terminal.type,aiohttp.WSMsgType.CLOSE)
                    self.assertEqual(terminal.data,1011)

    async def test_snapshot_publication_new_http_old_socket_and_no_cross_instance_turn(self):
        from test_web_model_protocol import message
        async def old(turn):
            turn.begin(turn.key); return message(['old'])
        async def new(turn):
            turn.begin(turn.key); return message(['new'])
        first, _, route1 = await self.provider(old)
        second, _, route2 = await self.provider(new,'c')
        await self.publish(route1)
        snapshot = self.router._registry
        self.assertEqual(snapshot.merge(CATALOG)['models'][0],CATALOG['models'][0])
        async with self.client.ws_connect(self.prefix+'/responses') as ws:
            self.assertEqual((await self.ws_response(ws,self.payload('one')))['output'][0]['content'][0]['text'],'old')
            await self.publish(route2)
            self.assertIs(snapshot.routes[route1.slug],route1)
            self.assertEqual((await self.ws_response(ws,self.payload('two')))['output'][0]['content'][0]['text'],'old')
            result = await self.client.post(self.prefix+'/responses',json=self.payload('new'))
            self.assertEqual((await result.json())['output'][0]['content'][0]['text'],'new')
            result = await self.client.post(self.prefix+'/responses',json=self.payload('one'))
            self.assertEqual(result.status,400)
            self.assertIn('instance_changed_no_retry', await result.text())
        self.assertEqual((first.requests,second.requests),(2,1))

    async def test_same_binding_no_io_failures_keep_previous_and_throttle(self):
        from test_web_model_protocol import message
        async def browser(turn):
            turn.begin(turn.key); return message()
        _, _, route = await self.provider(browser)
        await self.publish(route)
        expected = {'profile_sha256':'a'*64,'session_sha256':'b'*64}
        with patch('operator_web_service.resolve_routes',side_effect=AssertionError('no read')):
            self.assertFalse((await self.router.bind_web_service(expected))['changed'])
        before = self.router._registry
        with self.assertRaisesRegex(RouterError,'throttled'):
            await self.router.bind_web_service({**expected,'session_sha256':'c'*64})
        self.router._web_bind_not_before = 0
        with patch('operator_web_service.resolve_routes',side_effect=OSError('PRIVATE')):
            with self.assertRaisesRegex(RouterError,'^web_route_service_unavailable_no_retry$'):
                await self.router.bind_web_service({**expected,'session_sha256':'c'*64})
        self.assertIs(before,self.router._registry)
        self.assertGreater(self.router._web_bind_not_before,0)

    async def test_binding_selection_collision_and_private_field_cannot_be_registered(self):
        from test_web_model_protocol import message
        async def browser(turn):
            return message()
        _,_,route = await self.provider(browser)
        expected = {'profile_sha256':'a'*64,'session_sha256':'b'*64}
        self.router.web_profile=None
        with self.assertRaisesRegex(RouterError,'not_selected'):
            await self.router.bind_web_service(expected)
        self.router.web_profile=Path('selected-fixture')
        with self.assertRaisesRegex(RouterError,'digest_required'):
            await self.router.bind_web_service({**expected,'token':'must-not-accept'})
        with self.assertRaisesRegex(RouterError,'invalid_route_fields'):
            registry({**ROUTE,'web_binding':{}})
        self.router._registry=registry({**ROUTE,'slug':route.slug})
        with self.assertRaisesRegex(RouterError,'catalog_collision'):
            await self.publish(route)

    async def test_registry_reload_preserves_binding_and_rejects_collision_atomically(self):
        from test_web_model_protocol import message
        async def browser(turn):
            return message()
        _,_,route = await self.provider(browser)
        await self.publish(route)
        candidate=registry(ROUTE)
        with patch.object(ModelRegistry,'load_snapshot',return_value=(candidate,'d'*64)):
            await self.router.reload_registry(Path('fixture'),'d'*64)
        self.assertIs(self.router._registry.routes[route.slug],route)
        before=self.router._registry
        collision=registry({**ROUTE,'slug':route.slug})
        self.router._reload_not_before=0
        with patch.object(ModelRegistry,'load_snapshot',return_value=(collision,'e'*64)):
            with self.assertRaisesRegex(RouterError,'catalog_collision'):
                await self.router.reload_registry(Path('fixture'),'e'*64)
        self.assertIs(before,self.router._registry)
        self.assertEqual(self.router.registry_sha256,'d'*64)

    async def test_websocket_disconnect_cancels_browser_no_retry(self):
        entered,cancelled=asyncio.Event(),asyncio.Event()
        async def browser(turn):
            turn.begin(turn.key); entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        provider,_,route=await self.provider(browser)
        await self.publish(route)
        ws=await self.client.ws_connect(self.prefix+'/responses')
        await ws.send_json({'type':'response.create',**self.payload(stream=True)})
        await asyncio.wait_for(entered.wait(),5)
        await ws.close()
        await asyncio.wait_for(cancelled.wait(),5)
        self.assertEqual(provider.requests,1)

    async def test_native_catalog_and_wire_unchanged_after_web_attachment(self):
        from test_web_model_protocol import message
        seen=[]
        async def native(request):
            if request.path=='/models':
                return web.json_response(CATALOG)
            seen.append((await request.read(),request.headers['Authorization']))
            return web.Response(body=b'native-exact')
        app=web.Application();app.router.add_route('*','/{path:.*}',native)
        upstream=TestServer(app);await upstream.start_server()
        self.addAsyncCleanup(upstream.close)
        self.router.native_base=str(upstream.make_url('')).rstrip('/')
        async def browser(turn):
            self.fail('native reached web')
        provider,_,route=await self.provider(browser)
        await self.publish(route)
        headers={'Authorization':'Bearer ORIGINAL-NATIVE'}
        catalog=await self.client.get(self.prefix+'/models',headers=headers)
        rows=(await catalog.json())['models']
        self.assertEqual(rows[0],CATALOG['models'][0])
        self.assertEqual(rows[-1]['slug'],route.slug)
        raw=b'{ "model" : "native-test", "input" : "original whitespace" }'
        response=await self.client.post(self.prefix+'/responses',data=raw,headers=headers)
        self.assertEqual(await response.read(),b'native-exact')
        self.assertEqual(seen,[(raw,'Bearer ORIGINAL-NATIVE')])
        self.assertEqual(provider.requests,0)

    async def test_binding_cancellation_and_concurrent_reload_cannot_publish_late(self):
        import threading
        entered,release=threading.Event(),threading.Event()
        from test_web_model_protocol import message
        async def browser(turn):
            return message()
        _,_,route=await self.provider(browser)
        expected={'profile_sha256':'a'*64,'session_sha256':'b'*64}
        def delayed(*args):
            entered.set();release.wait(5);return (route,)
        with patch('operator_web_service.resolve_routes',side_effect=delayed):
            pending=asyncio.create_task(self.router.bind_web_service(expected))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,3))
                with self.assertRaisesRegex(RouterError,'busy_no_retry'):
                    await self.router.reload_registry(Path('fixture'),'c'*64)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            finally:
                release.set()
        self.assertEqual(self.router._registry.routes,{})

    async def test_turn_admission_memory_is_bounded_and_identifies_original_turn(self):
        from test_web_model_protocol import message
        async def browser(turn):
            self.fail('capacity rejection must precede forwarding')
        provider,_,route=await self.provider(browser)
        await self.publish(route)
        self.router._web_turn_bindings={str(n):'b'*64 for n in range(4096)}
        response=await self.client.post(self.prefix+'/responses',json=self.payload())
        self.assertEqual(response.status,400)
        self.assertIn('turn_capacity_no_retry',await response.text())
        self.assertEqual(provider.requests,0)

    async def test_lifecycle_control_has_no_path_or_secret_input_and_sanitizes_failures(self):
        from operator_model_router import web_binding_response
        app=web.Application()
        async def handle(request):
            return await web_binding_response(self.router,Path('fixture'),request)
        app.router.add_route('*','/binding',handle)
        client=TestClient(TestServer(app));await client.start_server()
        self.addAsyncCleanup(client.close)
        expected={'profile_sha256':'a'*64,'session_sha256':'b'*64}
        for options,status in [({'json':expected,'headers':{'Origin':'https://example.test'}},403),
                ({'json':{**expected,'path':'arbitrary'}},409),
                ({'data':b'x'*1025,'headers':{'Content-Type':'application/json'}},400)]:
            response=await client.post('/binding',**options)
            self.assertEqual(response.status,status)
        with patch('operator_web_service.resolve_routes',side_effect=OSError('SECRET')):
            response=await client.post('/binding',json=expected)
            self.assertNotIn('SECRET',await response.text())
            self.assertEqual(response.status,409)


if __name__ == "__main__":
    unittest.main()
