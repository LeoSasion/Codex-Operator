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
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "scripts"))
from operator_core import model_router_config as config
from operator_core.model_registry import RouterError
import operator_model_router as router


class ContractUpdateTests(unittest.TestCase):
    def setUp(self):
        from copy import deepcopy
        from test_responses_tools import ROUTE
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.old = deepcopy(ROUTE)
        self.other = {**deepcopy(ROUTE), "slug": "api/untouched"}
        config.initialize(self.state)
        config.register_routes(self.state, [self.old, self.other])
        self.target = self.state / "registry.json"
        self.before = self.target.read_bytes()
        self.row = deepcopy(self.old)
        self.row["responses"]["reasoning_summary"] = True
        self.preview = config.update_contracts(self.state, [self.row])

    def apply(self, rows=None, **kwargs):
        return config.update_contracts(self.state, rows or [self.row], apply=True,
            expected_sha256=self.preview["registry_sha256"],
            expected_candidate_sha256=self.preview["candidate_sha256"],
            guard=kwargs.pop("guard", Mock()), **kwargs)

    def test_preview_is_read_only_and_apply_keeps_original_and_other_row(self):
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["registry.json", "token"])
        guard = Mock()
        result = self.apply(guard=guard)
        self.assertEqual(guard.call_count, 2)
        self.assertTrue(result["applied"])
        self.assertEqual((self.state / result["backup_name"]).read_bytes(), self.before)
        self.assertEqual(json.loads(self.target.read_bytes())["models"], [self.row, self.other])
        self.assertEqual(result["changed_slugs"], [self.row["slug"]])
        self.assertFalse((self.state / "registry-edit.lock").exists())

    def test_summary_regression_is_fixed_only_in_updated_contract(self):
        from operator_core.responses_tool_adapter import prepare_request
        from operator_core.responses_capabilities import ResponsesCapabilities
        payload = {"input": "fixture", "reasoning": {"summary": "detailed"}}
        with self.assertRaisesRegex(RouterError, "reasoning_summary_not_supported"):
            prepare_request(payload, ResponsesCapabilities.parse(self.old["responses"]), ("low", "max"))
        self.apply()
        row = json.loads(self.target.read_bytes())["models"][0]
        prepared, _ = prepare_request(payload, ResponsesCapabilities.parse(row["responses"]), ("low", "max"))
        self.assertEqual(prepared["reasoning"], payload["reasoning"])

    def test_explicit_contract_restore_keeps_later_unrelated_registration(self):
        result = self.apply()
        later = {**self.other, "slug": "api/later"}
        config.register_route(self.state, later)
        saved = json.loads((self.state / result["backup_name"]).read_bytes())
        original_row = saved["models"][0]
        preview = config.update_contracts(self.state, [original_row])
        config.update_contracts(self.state, [original_row], apply=True,
            expected_sha256=preview["registry_sha256"],
            expected_candidate_sha256=preview["candidate_sha256"], guard=Mock())
        self.assertEqual(json.loads(self.target.read_bytes())["models"], [self.old, self.other, later])
        self.assertEqual((self.state / result["backup_name"]).read_bytes(), self.before)

    def test_identity_edits_missing_rows_and_duplicate_batch_are_refused(self):
        changes = {"model": "different", "api_base": "http://127.0.0.1:2/v1",
                   "api_key_env": "OTHER_KEY", "context_window": 8192,
                   "reasoning_efforts": ["low"], "display_name": "changed"}
        for key, value in changes.items():
            with self.subTest(field=key), self.assertRaisesRegex(RouterError, "contract_update_identity_changed"):
                config.update_contracts(self.state, [{**self.row, key: value}])
        for rows in ([{**self.row, "slug": "api/missing"}], [self.row, self.row], []):
            with self.subTest(rows=len(rows)), self.assertRaises(RouterError):
                config.update_contracts(self.state, rows)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_preview_binds_both_current_and_candidate_bytes(self):
        self.target.write_bytes(self.before + b"\n")
        with self.assertRaisesRegex(RouterError, "registry_changed_since_contract_preview"):
            self.apply()
        self.assertEqual(self.target.read_bytes(), self.before + b"\n")
        self.target.write_bytes(self.before)
        with self.assertRaisesRegex(RouterError, "candidate_changed_since_contract_preview"):
            self.apply([self.old])
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_verified_label_cannot_survive_a_changed_contract(self):
        current = {**self.old, "display_name": "Fixture [verified]"}
        self.target.write_text(json.dumps({"version": 2, "models": [current]}))
        before = self.target.read_bytes()
        updated = {**self.row, "display_name": current["display_name"]}
        with self.assertRaisesRegex(RouterError, "contract_update_verified_label_requires_review"):
            config.update_contracts(self.state, [updated])
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(config.update_contracts(self.state, [current])["changed_slugs"], [])

    def test_batch_is_atomic_and_cannot_enable_passthrough_adaptation(self):
        from copy import deepcopy
        second = deepcopy(self.other)
        second["responses"]["reasoning_summary"] = True
        second["context_window"] = 8192
        with self.assertRaisesRegex(RouterError, "contract_update_identity_changed"):
            config.update_contracts(self.state, [self.row, second])
        self.assertEqual(self.target.read_bytes(), self.before)
        second["context_window"] = self.other["context_window"]
        rows = [self.row, second]
        preview = config.update_contracts(self.state, rows)
        result = config.update_contracts(self.state, rows, apply=True,
            expected_sha256=preview["registry_sha256"],
            expected_candidate_sha256=preview["candidate_sha256"], guard=Mock())
        self.assertEqual(result["changed_slugs"], [self.row["slug"], second["slug"]])
        self.assertEqual(json.loads(self.target.read_bytes())["models"], rows)
        self.target.write_text(json.dumps({"version": 2, "models": [{**self.old, "responses": None}]}))
        before = self.target.read_bytes()
        with self.assertRaisesRegex(RouterError, "contract_update_requires_existing_adapted_registration"):
            config.update_contracts(self.state, [self.row])
        self.assertEqual(self.target.read_bytes(), before)

    def test_missing_guard_active_entry_and_busy_lifecycle_cannot_write(self):
        with self.assertRaisesRegex(RouterError, "contract_update_stopped_guard_required"):
            self.apply(guard=None)
        with self.assertRaisesRegex(RouterError, "fixture_busy"):
            self.apply(guard=Mock(side_effect=RouterError("fixture_busy")))
        (self.state / "codex-entry.json").write_text("{}")
        with self.assertRaisesRegex(RouterError, "deactivate_before_contract_update"):
            self.apply()
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_concurrent_changes_and_backup_conflict_are_retained(self):
        def race(_):
            if guard.call_count == 2:
                self.target.write_bytes(self.before + b"\n")
        guard = Mock(side_effect=race)
        with self.assertRaisesRegex(RouterError, "registry_changed_during_contract_update"):
            self.apply(guard=guard)
        self.assertEqual(self.target.read_bytes(), self.before + b"\n")
        self.target.write_bytes(self.before)
        backup = next(self.state.glob("contract-update-before-*.json"))
        backup.write_bytes(b"changed backup")
        with self.assertRaisesRegex(RouterError, "contract_update_backup_conflict"):
            self.apply()
        self.assertEqual(backup.read_bytes(), b"changed backup")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_locked_update_and_failed_atomic_write_preserve_original(self):
        lock = self.state / "registry-edit.lock"
        lock.write_bytes(b"other writer")
        with self.assertRaises(FileExistsError):
            self.apply()
        self.assertEqual(lock.read_bytes(), b"other writer")
        lock.unlink()
        with patch.object(config, "atomic_write", side_effect=OSError("fixture write failure")):
            with self.assertRaises(OSError): self.apply()
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(next(self.state.glob("contract-update-before-*.json")).read_bytes(), self.before)
        self.assertFalse(lock.exists())

    def test_unchanged_contract_does_not_reformat_or_write_backup(self):
        preview = config.update_contracts(self.state, [self.old])
        result = config.update_contracts(self.state, [self.old], apply=True,
            expected_sha256=preview["registry_sha256"],
            expected_candidate_sha256=preview["candidate_sha256"], guard=Mock())
        self.assertFalse(result["applied"])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(list(self.state.glob("contract-update-before-*")), [])

    def test_cli_preview_is_offline_and_apply_reserves_port(self):
        import io
        from contextlib import redirect_stdout
        import operator_core.responses_labels as labels
        request = self.state / "updates.json"
        request.write_text(json.dumps([self.row]))
        argv = ["router", "update-contracts", "--state-dir", str(self.state),
                "--registration", str(request)]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as output, \
                patch.object(router, "reserve_inactive_port") as reserve:
            router.main()
        reserve.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), self.preview)
        argv += ["--apply", "--expected-registry-sha256", self.preview["registry_sha256"],
                 "--expected-candidate-sha256", self.preview["candidate_sha256"]]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()), \
                patch.object(labels, "assert_registry_edit_stopped") as guard, \
                patch.object(router, "reserve_inactive_port") as reserve:
            router.main()
        reserve.assert_called_once_with(4317)
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(json.loads(self.target.read_bytes())["models"][0], self.row)


class RouterConfigTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows detached service launch")
    def test_router_start_detaches_from_desktop_console(self):
        from operator_core.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            child = Mock()
            child.poll.return_value = None
            with patch.object(router.settings, "url"), \
                    patch.object(ModelRegistry, "load"), \
                    patch.object(router, "selected_web_profile", return_value=None), \
                    patch.object(router, "control", side_effect=[OSError(), {"status": "ready", "diagnostics": {
                        "native_enabled": True, "native_search_identity": None}}]), \
                    patch.object(router.subprocess, "Popen", return_value=child) as spawn:
                self.assertEqual(router.start(state, 4317)["status"], "ready")
            flags = spawn.call_args.kwargs["creationflags"]
            self.assertEqual(flags, router.subprocess.CREATE_NO_WINDOW
                             | router.subprocess.CREATE_NEW_PROCESS_GROUP
                             | router.subprocess.CREATE_BREAKAWAY_FROM_JOB)
            self.assertTrue(spawn.call_args.kwargs["close_fds"])

    def test_fresh_router_start_refuses_existing_or_wrong_process(self):
        from operator_core.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch.object(router.settings, "url"), \
                    patch.object(ModelRegistry, "load"), \
                    patch.object(router, "selected_web_profile", return_value=None), \
                    patch.object(router, "control", return_value={"status": "ready"}), \
                    patch.object(router.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(RouterError, "router_existing_service_requires_review"):
                    router.start(state, 4317, require_fresh=True)
            spawn.assert_not_called()
            child = Mock(pid=1234)
            child.poll.return_value = None
            with patch.object(router.settings, "url"), \
                    patch.object(ModelRegistry, "load"), \
                    patch.object(router, "selected_web_profile", return_value=None), \
                    patch.object(router, "web_profile_identity", return_value=None), \
                    patch.object(router, "control", side_effect=[OSError(),
                        {"status": "ready", "pid": 5678, "diagnostics": {"web_profile_identity": None}}]), \
                    patch.object(router.subprocess, "Popen", return_value=child):
                with self.assertRaisesRegex(RouterError, "router_fresh_service_identity_mismatch"):
                    router.start(state, 4317, require_fresh=True)
            child.terminate.assert_called_once()
            child.wait.assert_called_once_with(timeout=5)

    def test_v2_append_preserves_legacy_routes_and_refuses_replacement(self):
        from test_responses_tools import ROUTE
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config.initialize(state)
            old = {k: v for k, v in ROUTE.items() if k != "responses"}
            config.register_route(state, old)
            adapted = {**ROUTE, "slug": "api/adapted"}
            config.register_route(state, adapted)
            value = json.loads((state / "registry.json").read_text())
            self.assertEqual(value["version"], 2)
            self.assertEqual(value["models"], [{**old, "responses": None}, adapted])
            before = (state / "registry.json").read_bytes()
            config.register_route(state, old)
            config.register_route(state, adapted)
            self.assertEqual(before, (state / "registry.json").read_bytes())
            with self.assertRaises(RouterError):
                config.register_route(state, {**adapted, "model": "different"})
            self.assertEqual(before, (state / "registry.json").read_bytes())

    def test_lmstudio_can_explicitly_append_v2_capabilities(self):
        from test_responses_tools import CAPABILITIES
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config.initialize(state)
            with patch.object(config, "lmstudio_models", return_value=["fixture"]):
                config.register_lmstudio(state, model="fixture", slug="local/fixture",
                    api_base="http://127.0.0.1:1234/v1", key_env="", context_window=8192,
                    efforts=["low"], responses=CAPABILITIES)
            value = json.loads((state / "registry.json").read_text())
            self.assertEqual(value["version"], 2)
            self.assertEqual(value["models"][0]["responses"], CAPABILITIES)

    def test_registration_file_is_bounded_and_duplicate_keys_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registration.json"
            for data in (b'{"model":"one","model":"two"}', b"x" * 1048577):
                path.write_bytes(data)
                with self.assertRaises(RouterError):
                    config.read_registration(path)

    def test_lmstudio_refuses_non_loopback_and_credential_urls(self):
        for base in ("https://example.com/v1", "http://localhost/v1", "http://user@127.0.0.1/v1",
                     "http://127.0.0.1/v1?key=secret", "http://127.0.0.1/chat/completions"):
            with self.subTest(base=base), self.assertRaises(RouterError):
                config.lmstudio_models(base)

    def test_lmstudio_registration_preserves_and_converges(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            config.initialize(state)
            kwargs = dict(model="local-model", slug="local/lmstudio", api_base="http://127.0.0.1:1234/v1",
                          key_env="", context_window=8192, efforts=["none"])
            with patch.object(config, "lmstudio_models", return_value=["local-model"]):
                config.register_lmstudio(state, **kwargs)
                before = (state / "registry.json").read_bytes()
                config.register_lmstudio(state, **kwargs)
                self.assertEqual(before, (state / "registry.json").read_bytes())
                with self.assertRaises(RouterError):
                    config.register_lmstudio(state, **{**kwargs, "context_window": 16384})
                self.assertEqual(before, (state / "registry.json").read_bytes())
                self.assertFalse((state / "registry-edit.lock").exists())
                (state / "codex-entry.json").write_text("{}")
                with self.assertRaises(RouterError):
                    config.register_lmstudio(state, **kwargs)

    def test_lmstudio_discovery_is_bounded_and_metadata_only(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"data":[{"id":"a"}]}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(config, "build_opener", return_value=opener):
            self.assertEqual(config.lmstudio_models("http://127.0.0.1:1234/v1"), ["a"])
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertFalse(request.has_header("Authorization"))
            self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/models")
            response.read.assert_called_once_with(1048577)
            response.read.return_value = b'x' * 1048577
            with self.assertRaises(RouterError):
                config.lmstudio_models("http://127.0.0.1:1234/v1")

    def test_switches_invalidate_cache_with_recoverable_backups(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            cache = Path(root) / "models_cache.json"
            config.initialize(state)
            target.write_bytes(b'model="native"\n')
            cache.write_bytes(b"original catalog")
            with patch.object(config, "health", return_value={}):
                config.activate(state, 4317, target)
                self.assertFalse(cache.exists())
                cache.write_bytes(b"augmented catalog")
                config.activate(state, 4317, target)
                self.assertEqual(cache.read_bytes(), b"augmented catalog")
            config.deactivate(state, target)
            self.assertFalse(cache.exists())
            self.assertEqual({p.read_bytes() for p in Path(root).glob("models_cache.router-backup-*.json")},
                             {b"original catalog", b"augmented catalog"})

    def test_config_failure_restores_cache(self):
        with tempfile.TemporaryDirectory() as root:
            target, cache = Path(root) / "config.toml", Path(root) / "models_cache.json"
            target.write_bytes(b"original")
            cache.write_bytes(b"catalog")
            with patch.object(config, "atomic_write", side_effect=OSError("test")), self.assertRaises(OSError):
                config.write_entry(target, b"changed")
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(cache.read_bytes(), b"catalog")

    def test_concurrent_cache_is_not_overwritten_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            target, cache = Path(root) / "config.toml", Path(root) / "models_cache.json"
            cache.write_bytes(b"original")
            def fail(*_args):
                cache.write_bytes(b"concurrent")
                raise OSError("test")
            with patch.object(config, "atomic_write", side_effect=fail), self.assertRaises(OSError):
                config.write_entry(target, b"changed")
            self.assertEqual(cache.read_bytes(), b"concurrent")
            self.assertEqual([p.read_bytes() for p in Path(root).glob("models_cache.router-backup-*.json")], [b"original"])

    def test_non_file_cache_blocks_config_change(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "config.toml"
            (Path(root) / "models_cache.json").mkdir()
            with self.assertRaises(RouterError):
                config.write_entry(target, b"changed")
            self.assertFalse(target.exists())

    def test_activation_and_rollback_preserve_later_unrelated_edits(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            target = Path(root) / "config.toml"
            target.write_bytes(b'model = "native"\r\n[features]\r\nfoo = true\r\n')
            before = target.read_bytes()
            config.initialize(state)
            token = (state / "token").read_bytes()
            config.initialize(state)
            self.assertEqual(token, (state / "token").read_bytes())
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
                config.activate(state, 4317, target)
            active = target.read_bytes()
            self.assertEqual(active.count(b"experimental_realtime_webrtc_call_base_url"), 1)
            self.assertEqual(active.count(b"experimental_realtime_ws_base_url"), 1)
            parsed = tomllib.loads(active.decode())
            self.assertEqual(parsed[config.VOICE_ROUTE_KEY], config.OFFICIAL_VOICE_BASE_URL)
            self.assertEqual(parsed[config.VOICE_WS_ROUTE_KEY], config.OFFICIAL_VOICE_BASE_URL)
            self.assertEqual(json.loads((state / "codex-entry.json").read_text())["block"].encode()
                             + before, active)
            target.write_bytes(target.read_bytes() + b'bar = false\r\n')
            config.deactivate(state, target)
            self.assertEqual(before + b'bar = false\r\n', target.read_bytes())

    def test_existing_official_voice_route_is_preserved_as_user_owned(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            original = (b'# Keep this setting\r\n'
                        + b'experimental_realtime_webrtc_call_base_url = '
                        + json.dumps(config.OFFICIAL_VOICE_BASE_URL).encode() + b' # user comment\r\n'
                        + b'[features]\r\nfoo = true\r\n')
            target.write_bytes(original)
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
                config.activate(state, 4317, target)
            active = target.read_bytes()
            self.assertEqual(active.count(b"experimental_realtime_webrtc_call_base_url"), 1)
            self.assertEqual(active.count(b"experimental_realtime_ws_base_url"), 1)
            self.assertTrue(active.endswith(original))
            owned = json.loads((state / "codex-entry.json").read_text())["block"]
            self.assertNotIn(config.VOICE_ROUTE_KEY, owned)
            self.assertIn(config.VOICE_WS_ROUTE_KEY, owned)
            config.deactivate(state, target)
            self.assertEqual(target.read_bytes(), original)

    def test_existing_official_ws_route_is_preserved_as_user_owned(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            original = (config.VOICE_WS_ROUTE_KEY + " = "
                        + json.dumps(config.OFFICIAL_VOICE_BASE_URL) + " # user comment\n").encode()
            target.write_bytes(original)
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
                config.activate(state, 4317, target)
            active = target.read_bytes()
            self.assertEqual(active.count(config.VOICE_WS_ROUTE_KEY.encode()), 1)
            self.assertEqual(active.count(config.VOICE_ROUTE_KEY.encode()), 1)
            self.assertTrue(active.endswith(original))
            owned = json.loads((state / "codex-entry.json").read_text())["block"]
            self.assertIn(config.VOICE_ROUTE_KEY, owned)
            self.assertNotIn(config.VOICE_WS_ROUTE_KEY, owned)
            config.deactivate(state, target)
            self.assertEqual(target.read_bytes(), original)

    def test_existing_both_official_voice_routes_remain_user_owned(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            original = (config.VOICE_ROUTE_KEY + " = " + json.dumps(config.OFFICIAL_VOICE_BASE_URL)
                        + " # call\n" + config.VOICE_WS_ROUTE_KEY + " = "
                        + json.dumps(config.OFFICIAL_VOICE_BASE_URL) + " # ws\n").encode()
            target.write_bytes(original)
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
                config.activate(state, 4317, target)
            owned = json.loads((state / "codex-entry.json").read_text())["block"]
            self.assertNotIn(config.VOICE_ROUTE_KEY, owned)
            self.assertNotIn(config.VOICE_WS_ROUTE_KEY, owned)
            config.deactivate(state, target)
            self.assertEqual(target.read_bytes(), original)

    def test_conflicting_voice_route_stops_before_activation_side_effects(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            for key, error in ((config.VOICE_ROUTE_KEY, "existing_voice_route_requires_explicit_migration"),
                               (config.VOICE_WS_ROUTE_KEY, "existing_voice_ws_route_requires_explicit_migration")):
                with self.subTest(key=key):
                    original = (key + ' = "https://voice.example/v1"\n').encode()
                    target.write_bytes(original)
                    with patch.object(config, "health") as health, patch.object(config, "ensure_recovery_shortcut") as recovery:
                        with self.assertRaisesRegex(RouterError, error):
                            config.activate(state, 4317, target)
                        health.assert_not_called()
                        recovery.assert_not_called()
                    self.assertEqual(target.read_bytes(), original)
                    self.assertFalse((state / "codex-entry.json").exists())

    def test_legacy_active_entry_stays_removable_without_claiming_voice_protection(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            legacy_blocks = config.managed_entry_blocks(state, 4317)[:2]
            original = b'model = "native"\n'
            for legacy in legacy_blocks:
                with self.subTest(block=legacy):
                    target.write_bytes(legacy + original)
                    (state / "codex-entry.json").write_text(json.dumps({
                        "config": str(target.resolve()), "block": legacy.decode()}))
                    with patch.object(config, "health") as health, patch.object(config, "ensure_recovery_shortcut") as recovery:
                        with self.assertRaisesRegex(RouterError, "legacy_router_voice_route_unprotected"):
                            config.activate(state, 4317, target)
                        health.assert_not_called()
                        recovery.assert_not_called()
                    self.assertEqual(target.read_bytes(), legacy + original)
                    config.deactivate(state, target)
                    self.assertEqual(target.read_bytes(), original)

    def test_changed_managed_voice_line_blocks_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            target.write_bytes(b'model="native"\n')
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
            changed = target.read_bytes().replace(
                (config.VOICE_WS_ROUTE_KEY + ' = ' + json.dumps(config.OFFICIAL_VOICE_BASE_URL)).encode(),
                (config.VOICE_WS_ROUTE_KEY + ' = "https://voice.example/v1"').encode())
            target.write_bytes(changed)
            with self.assertRaisesRegex(RouterError, "managed_config_changed"):
                config.deactivate(state, target)
            self.assertEqual(target.read_bytes(), changed)
            self.assertTrue((state / "codex-entry.json").exists())

    def test_malformed_or_extended_entry_journal_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / "state", Path(root) / "config.toml"
            config.initialize(state)
            target.write_bytes(b'model="native"\n')
            protected = config.managed_entry_blocks(state, 4317)[3].decode()
            for journal in ({"config": str(target.resolve()), "block": []},
                            {"config": str(target.resolve()), "block": protected, "extra": True}):
                with self.subTest(journal=journal):
                    (state / "codex-entry.json").write_text(json.dumps(journal))
                    with self.assertRaisesRegex(RouterError, "existing_router_journal_conflict"):
                        config.activation_preflight(state, 4317, target)
                    self.assertEqual(target.read_bytes(), b'model="native"\n')

    def test_existing_route_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            target = Path(root) / "config.toml"
            config.initialize(state)
            for text in ('openai_base_url="https://example.org"\n',
                         'model_provider="other"\n', 'model_catalog_json="custom.json"\n'):
                target.write_text(text)
                with patch.object(config, "health", return_value={"status": "ready"}), self.assertRaises(RouterError):
                    config.activate(state, 4317, target)
                self.assertEqual(text, target.read_text())

    def test_commented_legacy_route_roundtrip_preserves_every_original_byte(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / 'state', Path(root) / 'config.toml'
            config.initialize(state)
            for newline in (b'\n', b'\r\n'):
                original = newline.join([
                    b'# BEGIN FEISHU OPERATOR MODEL ROUTER',
                    b'# openai_base_url = "http://127.0.0.1:4317/' + b'a' * 64 + b'/v1"',
                    b'# END FEISHU OPERATOR MODEL ROUTER',
                    '# 原有备注保持'.encode(), b'model="native"', b''])
                target.write_bytes(original)
                cache = Path(root) / 'models_cache.json'
                cache.write_bytes(b'original catalog')
                before = {p.name: p.read_bytes() for p in state.iterdir()}
                with patch.object(config, 'health') as health, patch.object(config, 'ensure_recovery_shortcut') as recovery:
                    config.activation_preflight(state, 4318, target)
                    health.assert_not_called(); recovery.assert_not_called()
                    self.assertEqual(cache.read_bytes(), b'original catalog')
                    self.assertEqual(before, {p.name:p.read_bytes() for p in state.iterdir()})
                    config.activate(state, 4318, target)
                block = json.loads((state/'codex-entry.json').read_text())['block'].encode()
                self.assertEqual(target.read_bytes(), block + original)
                self.assertFalse(cache.exists())
                config.deactivate(state, target)
                self.assertEqual(target.read_bytes(), original)

    def test_comment_compatibility_does_not_adopt_unknown_or_active_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / 'state', Path(root) / 'config.toml'
            config.initialize(state)
            inactive = config.BEGIN + '# openai_base_url = "http://127.0.0.1:4317/' + 'a'*64 + '/v1"\n' + config.END
            cases = [inactive.replace('# openai_base_url', 'openai_base_url'),
                inactive.replace('/v1', '/other'), inactive.replace(':4317', ':0'),
                inactive.replace('# END FEISHU OPERATOR MODEL ROUTER\n', ''),
                inactive + inactive, '# unrelated\n' + inactive,
                inactive + 'openai_base_url="https://example.org"\n',
                inactive + 'model_provider="other"\n', inactive + 'model_catalog_json="custom.json"\n',
                inactive.replace('# openai_base_url', '# unknown')]
            for content in cases:
                with self.subTest(content=content):
                    target.write_text(content, encoding='utf8')
                    original = target.read_bytes()
                    with patch.object(config, 'health') as health, patch.object(config, 'ensure_recovery_shortcut') as recovery:
                        with self.assertRaises(RouterError): config.activate(state, 4318, target)
                        health.assert_not_called(); recovery.assert_not_called()
                    self.assertEqual(target.read_bytes(), original)
                    self.assertFalse((state/'codex-entry.json').exists())

    def test_configuration_change_during_preparation_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            state, target = Path(root) / 'state', Path(root) / 'config.toml'
            config.initialize(state); target.write_bytes(b'model="native"\n')
            changed = b'model="native"\n# later edit\n'
            with patch.object(config, 'health', side_effect=lambda *_: target.write_bytes(changed)):
                with self.assertRaisesRegex(RouterError, 'activation_config_changed'):
                    config.activate(state, 4318, target)
            self.assertEqual(target.read_bytes(), changed)
            self.assertFalse((state/'codex-entry.json').exists())

    def test_changed_owned_prefix_blocks_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            target = Path(root) / "config.toml"
            config.initialize(state)
            with patch.object(config, "health", return_value={"status": "ready"}):
                config.activate(state, 4317, target)
            target.write_text("# user edited\n" + target.read_text())
            before = target.read_bytes()
            with self.assertRaises(RouterError):
                config.deactivate(state, target)
            self.assertEqual(before, target.read_bytes())
