"""One native catalog can advertise native, API, Local and bound Web models."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = next(parent for parent in Path(__file__).resolve().parents
              if (parent / ".codex-plugin/plugin.json").is_file())
sys.path.insert(0, str(PLUGIN / "development"))
from run_tests import prepare_test_imports
prepare_test_imports(PLUGIN)
sys.path.insert(0, str(PLUGIN / "scripts"))

from operator_core.model_registry import ModelRegistry, RouterError, WebServiceBinding
from operator_core.app_server import AppServerSession
from operator_web_model import text_routes


BEEPER = json.loads((PLUGIN / "scripts/operator_core/beeper_model_catalog.json")
                    .read_text(encoding="utf-8"))
NATIVE = {"models": [{"slug": "official-fixture", "display_name": "Official",
                      "visibility": "list", "supported_in_api": True,
                      "opaque_native_feature": {"keep": [1, 2, 3]}}],
          "catalog_generation": "native-fixture"}


def external(slug):
    return {"slug": slug, "display_name": slug, "model": "upstream-" + slug,
            "api_base": "http://127.0.0.1:1/v1", "api_key_env": "",
            "context_window": 32000, "reasoning_efforts": ["low"], "responses": None}


class MixedModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.registry = ModelRegistry({"version": 2, "models": [
            external("api/fixture"), external("local/fixture")]}, BEEPER)
        self.binding = WebServiceBinding("a" * 64, "b" * 64, "private-fixture")
        self.web = tuple(replace(route, model=route.slug, web_binding=self.binding)
                         for route in text_routes(tools=True))

    def test_one_catalog_preserves_native_and_exposes_exact_web_selections(self):
        native_before = deepcopy(NATIVE)
        published = self.registry.with_web_routes(self.web)
        catalog = published.merge(NATIVE)
        rows = {row["slug"]: row for row in catalog["models"]}

        self.assertEqual(NATIVE, native_before)
        self.assertEqual(catalog["models"][0], native_before["models"][0])
        self.assertEqual(catalog["catalog_generation"], "native-fixture")
        self.assertEqual(list(rows), ["official-fixture", "beeper", "api/fixture",
                                      "local/fixture", *(route.slug for route in self.web)])
        for route in self.web:
            row = rows[route.slug]
            self.assertEqual(row["display_name"], route.display_name)
            self.assertEqual(row["default_reasoning_level"], route.reasoning_efforts[0])
            self.assertEqual([level["effort"] for level in row["supported_reasoning_levels"]],
                             list(route.reasoning_efforts))
            self.assertEqual(row["visibility"], "list")
            self.assertFalse(row["supports_search_tool"])
            self.assertNotIn("opaque_native_feature", row)
            self.assertEqual(route.context_window, 16000)
            self.assertFalse(route.web_context_window_verified)
            for field in ("context_window", "max_context_window",
                          "effective_context_window_percent"):
                self.assertNotIn(field, row)
        self.assertEqual(self.registry.routes.keys(), {"api/fixture", "local/fixture"})

    def test_entire_web_catalog_rebinds_together_and_old_snapshot_stays_frozen(self):
        first = self.registry.with_web_routes(self.web)
        replacement = WebServiceBinding("a" * 64, "c" * 64, "new-private-fixture")
        second = first.with_web_routes(tuple(replace(route, web_binding=replacement)
                                             for route in self.web))
        self.assertEqual({route.web_binding for route in first.routes.values()
                          if route.web_binding}, {self.binding})
        self.assertEqual({route.web_binding for route in second.routes.values()
                          if route.web_binding}, {replacement})
        self.assertEqual(second.routes["api/fixture"], first.routes["api/fixture"])

    def test_duplicate_mixed_generation_and_native_collision_fail_before_publication(self):
        before = dict(self.registry.routes)
        for routes, code in ((self.web + self.web[:1], "web_route_duplicate_or_invalid"),
                            ((self.web[0], replace(self.web[1], web_binding=
                              WebServiceBinding("a" * 64, "c" * 64, "private-fixture"))),
                             "web_route_binding_mismatch"),
                            ((self.web[0], "not-a-route"), "web_route_duplicate_or_invalid")):
            with self.subTest(code=code), self.assertRaisesRegex(RouterError, "^" + code + "$"):
                self.registry.with_web_routes(routes)
            self.assertEqual(self.registry.routes, before)

        published = self.registry.with_web_routes(self.web)
        with self.assertRaisesRegex(RouterError, "web_route_binding_mismatch"):
            published.with_web_route(replace(self.web[0], web_binding=
                WebServiceBinding("a" * 64, "c" * 64, "private-fixture")))
        self.assertIs(published.routes[self.web[0].slug], self.web[0])

        colliding = deepcopy(NATIVE)
        colliding["models"].append({"slug": self.web[0].slug})
        colliding_before = deepcopy(colliding)
        with self.assertRaisesRegex(RouterError, "model_catalog_collision"):
            published.merge(colliding)
        self.assertEqual(colliding, colliding_before)


@unittest.skipUnless(os.environ.get("CODEX_OPERATOR_TEST_CLI"),
                     "explicit current CLI path required for isolated catalog read")
class CurrentCliMixedCatalogTests(unittest.TestCase):
    def test_model_list_accepts_web_entries_without_unverified_context_capacity(self):
        executable = Path(os.environ["CODEX_OPERATOR_TEST_CLI"]).resolve(strict=True)
        binding = WebServiceBinding("a" * 64, "b" * 64, "private-fixture")
        web = tuple(replace(route, model=route.slug, web_binding=binding)
                    for route in text_routes(tools=True))
        registry = ModelRegistry({"version": 2, "models": [external("api/fixture")]}, BEEPER)
        native = deepcopy(BEEPER["models"][0])
        native.update(slug="official-fixture", display_name="Official fixture")
        catalog_value = registry.with_web_routes(web).merge({"models": [native]})
        with tempfile.TemporaryDirectory(prefix="operator-mixed-catalog-") as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(json.dumps(catalog_value), encoding="utf-8")
            environment = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith(("CODEX_", "OPENAI_", "CHATGPT_"))}
            environment["CODEX_HOME"] = directory
            popen = subprocess.Popen
            children = []

            def isolated_popen(args, **kwargs):
                child = popen([*args, "-c", "model_catalog_json=" + json.dumps(str(catalog)),
                              "-c", 'openai_base_url="http://127.0.0.1:1/v1"',
                              "-c", 'cli_auth_credentials_store="file"'],
                             **{**kwargs, "env": environment, "cwd": directory,
                                "stderr": subprocess.PIPE})
                children.append(child)
                return child

            try:
                with patch("operator_core.app_server.subprocess.Popen", side_effect=isolated_popen):
                    with AppServerSession(executable, 15) as session:
                        result = session.request("model/list", {"includeHidden": False, "limit": 100})
            except Exception as exc:
                detail = children[0].stderr.read() if children else "no child"
                raise AssertionError("isolated model/list failed: " + detail[:2000]) from exc
            finally:
                for child in children:
                    if child.stdout is not None:
                        child.stdout.close()
                    if child.stderr is not None:
                        child.stderr.close()
        listed = {row["model"]: row for row in result["data"]}
        self.assertIn("official-fixture", listed)
        self.assertIn("api/fixture", listed)
        for route in web:
            self.assertIn(route.slug, listed)
            self.assertFalse(listed[route.slug]["hidden"])


if __name__ == "__main__":
    unittest.main()
