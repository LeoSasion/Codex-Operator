"""Bounded read-only Web binding identity in the router lifecycle status."""

from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import importlib.util
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace
import unittest
from urllib.error import URLError

import operator_model_router as service
from operator_core import model_router_config as config
from operator_core.model_registry import WebServiceBinding


class BoundWebRouteDigestTests(unittest.TestCase):
    def test_unbound_bound_and_rebound_are_read_only_and_content_free(self):
        token = "do-not-disclose-private-token"
        routes = {"api/one": SimpleNamespace(web_binding=None)}
        registry = SimpleNamespace(routes=routes)
        unbound = service.bound_web_route_digests(registry)
        self.assertEqual(unbound, {"web_route_bound": False,
            "web_route_profile_sha256": None, "web_route_session_sha256": None})
        first = WebServiceBinding("a" * 64, "b" * 64, token)
        routes["web/one"] = SimpleNamespace(web_binding=first)
        routes["web/two"] = SimpleNamespace(web_binding=first)
        result = service.bound_web_route_digests(registry)
        self.assertEqual(result, {"web_route_bound": True,
            "web_route_profile_sha256": "a" * 64,
            "web_route_session_sha256": "b" * 64})
        self.assertNotIn(token, str(result))
        self.assertIs(routes["web/one"].web_binding, first)
        routes["web/one"] = SimpleNamespace(web_binding=WebServiceBinding("a" * 64,
                                                                            "c" * 64, token))
        ambiguous = service.bound_web_route_digests(registry)
        self.assertEqual(ambiguous, {"web_route_bound": True,
            "web_route_profile_sha256": None, "web_route_session_sha256": None})
        routes["web/two"] = routes["web/one"]
        changed = service.bound_web_route_digests(registry)
        self.assertEqual(changed["web_route_session_sha256"], "c" * 64)
        self.assertNotIn(token, str(changed))

    def test_lifecycle_diagnostics_keep_existing_fields_and_do_not_mutate_registry(self):
        binding = WebServiceBinding("a" * 64, "b" * 64, "private-token")
        route = SimpleNamespace(web_binding=binding, responses=None)
        registry = SimpleNamespace(routes={"web/one": route})
        router = SimpleNamespace(failure_count=2, last_failure=None, native_enabled=True, native_search_identity=None,
            metrics=SimpleNamespace(snapshot=lambda: {"active": 0}),
            registry_sha256="d" * 64, registry=registry)
        result = service.lifecycle_diagnostics(router, Path("selected-profile"))
        self.assertEqual(result["failure_count"], 2)
        self.assertTrue(result['native_enabled'])
        self.assertIsNone(result['native_search_identity'])
        self.assertEqual(result["timing"], {"active": 0})
        self.assertEqual(result["registry_sha256"], "d" * 64)
        self.assertEqual(result["adapted_models"], 0)
        self.assertEqual(result["web_route_profile_sha256"], "a" * 64)
        self.assertEqual(result["web_route_session_sha256"], "b" * 64)
        self.assertIs(registry.routes["web/one"], route)
        self.assertNotIn("private-token", str(result))

    @unittest.skipUnless(importlib.util.find_spec("aiohttp"), "optional router runtime required")
    def test_existing_lifecycle_status_reports_unbound_without_writes(self):
        with tempfile.TemporaryDirectory(prefix="operator-web-route-status-") as directory:
            state = Path(directory)
            config.initialize(state)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            original = {path.name: path.read_bytes() for path in state.iterdir() if path.is_file()}
            try:
                started = service.start(state, port)
                status = service.control(state, port)
                self.assertEqual(status["pid"], started["pid"])
                self.assertEqual(status["status"], "ready")
                self.assertEqual(status["diagnostics"]["web_route_bound"], False)
                self.assertIsNone(status["diagnostics"]["web_route_profile_sha256"])
                self.assertIsNone(status["diagnostics"]["web_route_session_sha256"])
                self.assertEqual(original, {path.name: path.read_bytes()
                                            for path in state.iterdir() if path.is_file()})
            finally:
                try:
                    service.control(state, port, stop=True)
                except URLError:
                    pass
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        service.control(state, port)
                    except URLError:
                        break
                    time.sleep(.1)
                else:
                    self.fail("disposable router did not release its port")


if __name__ == "__main__":
    unittest.main()
