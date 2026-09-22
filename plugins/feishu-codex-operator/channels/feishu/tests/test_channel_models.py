from __future__ import annotations
from pathlib import Path
import sys
ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".codex-plugin/plugin.json").is_file())
sys.path.insert(0, str(ROOT / "development"))
from run_tests import prepare_test_imports
prepare_test_imports(ROOT)

import json
import subprocess
import tempfile
import time
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from operator_core.channel_models import ChannelModels, NativeModelCatalog, ModelSelectionError, pending_arguments
from operator_core.state import SessionStore
from operator_core.final_callback import FinalCallbackStore
from operator_core.runtime import parse_command
from operator_core.beeper_relay import BeeperRelayClient
from operator_core import runtime as runtime_module, lark
from operator_core.runtime import OperatorRuntime
from operator_core.config import load_config
from operator_core.rate_limits import parse_account_rate_limits
from test_rate_limits import result_for
import relay_mcp_server
from test_beeper_relay import config_for, BEEPER_ID, RESPONDER_ID, FakeLifecycleObserver

ROW = {"model": "gpt-5.6-luna", "hidden": False, "defaultReasoningEffort": "medium",
       "supportedReasoningEfforts": [{"reasoningEffort": e} for e in ("low", "medium", "high")]}
CHOICE = {"model": "gpt-5.6-luna", "thinking": "low"}


class ChannelModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = SessionStore(self.root / "sessions.json")
        self.session = self.sessions.bind_thread("p2p:test", RESPONDER_ID, {"host_id": "local"})
        self.config = SimpleNamespace(beeper_thread_id=BEEPER_ID, codex_executable="", app_server_timeout_seconds=10)
        self.reads = []
        self.native_config = {}
        self.native_task = {"id": RESPONDER_ID, "modelProvider": "openai", "ephemeral": False,
                            "model": "gpt-6-astra", "reasoningEffort": "high", "preview": "PRIVATE"}
        self.page = {"data": [ROW], "nextCursor": None}
        outer = self
        class API:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def request(self, method, params):
                outer.reads.append((method, params))
                return {"config/read": {"config": outer.native_config}, "thread/read": {"thread": outer.native_task},
                        "model/list": outer.page}[method]
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"OPENAI_BASE_URL": ""}).start()
        patch("operator_core.channel_models.AppServerSession", API).start()
        patch("operator_core.beeper_relay.discover_codex_executable", return_value=self.root / "codex.exe").start()
        self.models = ChannelModels(self.config, self.sessions)

    def command(self, argument):
        return self.models.command("p2p:test", self.sessions.get("p2p:test"), argument)

    def test_exact_command_parse_never_promotes_business_text(self):
        for text, expected in [("@机器人 /model Luna low", ("model", "Luna low")), (" /MODEL ", ("model", "")),
                               ("/models", ("unsupported", "")), ("请 /model luna", ("", ""))]:
            self.assertEqual(parse_command(text), expected)

    def test_list_and_current_are_readonly_without_transcript(self):
        before = self.sessions.path.read_bytes()
        self.assertIn("gpt-5.6-luna", self.command("list"))
        self.assertIn("gpt-6-astra / high", self.command(""))
        self.assertEqual(before, self.sessions.path.read_bytes())
        self.assertEqual({m for m, _ in self.reads}, {"config/read", "thread/read", "model/list"})
        self.assertTrue(all(p == {"threadId": RESPONDER_ID, "includeTurns": False} for m, p in self.reads if m == "thread/read"))
        self.assertNotIn("PRIVATE", json.dumps(self.sessions.get("p2p:test")))

    def test_pending_is_durable_once_and_no_longer_overrides_desktop(self):
        self.assertIn("下一条新消息", self.command("luna low"))
        stored = SessionStore(self.sessions.path).get("p2p:test")
        self.assertEqual(self.models.prepare(stored), CHOICE)
        self.sessions.update_model_selection("p2p:test", stored, None, consume=True)
        self.assertIsNone(self.models.prepare(self.sessions.get("p2p:test")))
        with self.assertRaises(ModelSelectionError):
            self.sessions.update_model_selection("p2p:test", stored, None, consume=True)
        self.assertIn("不代表", self.command(""))

    def test_selection_save_failure_rolls_back_and_remains_unsent(self):
        with patch.object(self.sessions, "_save_locked", side_effect=OSError("disk")):
            with self.assertRaises(OSError): self.command("luna low")
        self.assertNotIn("model_selection", self.sessions.get("p2p:test"))

    def test_consumption_failure_keeps_pending_but_emits_no_selection(self):
        self.command("luna low")
        saved = self.sessions.get("p2p:test")
        with patch.object(self.sessions, "_save_locked", side_effect=OSError("disk")):
            with self.assertRaises(OSError): self.sessions.update_model_selection("p2p:test", saved, None, consume=True)
        self.assertEqual(self.sessions.get("p2p:test"), saved)

    def test_choice_cannot_follow_rebind_or_overwrite_newer_choice(self):
        self.command("luna low")
        old = self.sessions.get("p2p:test")
        self.command("luna high")
        with self.assertRaises(ModelSelectionError): self.sessions.update_model_selection("p2p:test", old, None, consume=True)
        rebound = self.sessions.bind_thread("p2p:test", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        self.assertIsNone(pending_arguments(rebound))
        with self.assertRaises(ModelSelectionError): self.sessions.update_model_selection("p2p:test", old, None, consume=True)

    def test_cancel_sends_nothing_and_does_not_read_native(self):
        self.command("luna low")
        self.reads.clear()
        self.assertIn("已取消", self.command("cancel"))
        self.assertEqual(self.reads, [])
        self.assertNotIn("model_selection", self.sessions.get("p2p:test"))

    def test_unavailable_or_invalid_choices_do_not_replace_saved_choice(self):
        self.command("luna low")
        before = self.sessions.path.read_bytes()
        for argument in ("spark", "web/chatgpt", "luna ultra", "luna low injected"):
            self.command(argument)
            self.assertEqual(before, self.sessions.path.read_bytes())
        self.page = {"data": [], "nextCursor": None}
        with self.assertRaises(ModelSelectionError): self.models.prepare(self.sessions.get("p2p:test"))

    def test_non_native_or_custom_routes_never_claim_selectable(self):
        for config in ({"model_provider": "web"}, {"model_providers": {"openai": {"base_url": "http://localhost"}}},
                       {"model_catalog_json": "custom.json"}, {"openai_base_url": "http://localhost/v1"},
                       {"openai_base_url": ""}, {"openai_base_url": False}):
            self.native_config = config
            with self.assertRaises(ModelSelectionError): self.command("list")
        self.native_config = {}
        self.native_task["modelProvider"] = "web"
        with self.assertRaises(ModelSelectionError): self.command("luna low")

    def test_new_route_override_preserves_pending_choice_and_stops_before_catalog(self):
        self.command("luna low")
        before = self.sessions.path.read_bytes()
        for environment, config in [({}, {"openai_base_url": "http://localhost/private"}),
                ({"OPENAI_BASE_URL": "http://localhost/private"}, {})]:
            with self.subTest(environment=bool(environment)):
                self.native_config = config
                self.reads.clear()
                with patch.dict(os.environ, environment):
                    with self.assertRaisesRegex(ModelSelectionError, "model_native_route_unverified"):
                        self.models.prepare(self.sessions.get("p2p:test"))
                self.assertTrue(all(method == "config/read" for method, _ in self.reads))
                self.assertEqual(self.sessions.path.read_bytes(), before)

    def test_catalog_malformed_incomplete_or_duplicate_fails_closed(self):
        for page in ({"data": [ROW], "nextCursor": "more"}, {"data": [ROW, ROW]},
                     {"data": [dict(ROW, supportedReasoningEfforts=[{}])]}):
            self.page = page
            with self.assertRaises(ModelSelectionError): self.command("list")

    def test_hidden_and_retired_models_are_not_available(self):
        self.page = {"data": [dict(ROW, hidden=True), dict(ROW, model="gpt-5.3-codex-spark")]}
        rows, _ = NativeModelCatalog(self.config).read(self.session)
        self.assertEqual(rows, [])

    def test_beeper_or_remote_or_wrong_identity_refused(self):
        for change in ({"thread_id": BEEPER_ID}, {"host_id": "remote"}):
            with self.assertRaises(ModelSelectionError): NativeModelCatalog(self.config).read(dict(self.session, **change))
        self.native_task["id"] = BEEPER_ID
        with self.assertRaises(ModelSelectionError): self.command("list")

    def test_selection_exact_args_survive_store_and_generated_program(self):
        store = FinalCallbackStore(self.root / "callbacks.sqlite3")
        text = '保留 " 引号 \\ 路径\n🙂 ` ${tools}`'
        store.open("a"*32, "e1", RESPONDER_ID, relay_prompt=text, model_selection=CHOICE)
        dispatch = store.take_relay("a"*32)
        self.assertEqual(dispatch, dict(threadId=RESPONDER_ID, hostId="local", prompt=text, **CHOICE))
        self.assertIsNone(store.take_relay("a"*32))
        script = ("const started=Date.now(); const ALL_TOOLS=[{name:'mcp__codex_app__send_message_to_thread'}];"
                  "const text=()=>{}; let calls=0; const tools={mcp__codex_app__send_message_to_thread: async a=>{calls++; console.log(JSON.stringify(a)); return {}}};"
                  + "(" + relay_mcp_server.relay_program(dispatch) + ")().then(()=>{if(calls!==1)process.exit(2)});")
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout), dispatch)

    def test_ordinary_relay_omits_overrides_and_invalid_optional_keys_stop(self):
        base = dict(threadId=RESPONDER_ID, hostId="local", prompt="exact")
        for invalid in (dict(base, model="gpt-5.6-luna"), dict(base, **CHOICE, config={}), dict(base, model="web/test", thinking="low")):
            with self.assertRaises(relay_mcp_server.FinalCallbackError): relay_mcp_server.relay_program(invalid)
        self.assertNotIn('"model":', relay_mcp_server.relay_program(base))

    def test_beeper_queue_keeps_luna_low_and_business_dispatch_gets_explicit_choice(self):
        calls, payloads = [], []
        def runner(argv, **kwargs):
            calls.append(argv)
            request_id = client.request_id("new-event")
            payloads.append(client.callbacks.take_relay(request_id))
            client.callbacks.submit(request_id, "answer")
            return SimpleNamespace(returncode=0)
        client = BeeperRelayClient(config_for(self.root), runner=runner, codex_executable=self.root / "codex.exe",
                                  wake_signal_sender=lambda _: None, lifecycle_observer=FakeLifecycleObserver(["unknown"]))
        try:
            answer = client.send(self.session, "new request", event_id="new-event", responder_model_selection=CHOICE)
        finally:
            client.close()
        self.assertEqual(answer.final_answer, "answer")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("--thread")+1], BEEPER_ID)
        self.assertEqual(calls[0][calls[0].index("--model")+1], "gpt-5.6-luna")
        self.assertEqual(payloads[0]["threadId"], RESPONDER_ID)
        self.assertEqual({k: payloads[0][k] for k in CHOICE}, CHOICE)

    def test_runtime_control_business_callback_and_followup_without_sticky_override(self):
        with patch.dict(os.environ, {"CODEX_OPERATOR_PROJECT_ROOT": str(self.root)}, clear=True):
            config = load_config()
        config = replace(config, owner_open_id="offline-owner", beeper_thread_id=BEEPER_ID,
                         download_resources=False, codex_executable=str(self.root / "codex.exe"))
        runtime = OperatorRuntime(config, "fake-lark")
        runtime.bot_open_id = "offline-bot"
        runtime.relay._codex_executable = self.root / "codex.exe"
        runtime.relay._lifecycle_observer = None
        runtime.relay._wake_signal_sender = lambda _: None
        runtime.rate_limits._reader = lambda: parse_account_rate_limits(result_for(used=1))
        runtime.rate_limits.prime()
        runtime.sessions.bind_thread("p2p:offline-chat", RESPONDER_ID, {"name": "Offline"})
        payloads, delivered = [], []
        current_event = ""
        def queue(argv, **kwargs):
            request_id = runtime.relay.request_id(current_event)
            payloads.append(runtime.relay.callbacks.take_relay(request_id))
            runtime.relay.callbacks.submit(request_id, "精确回传")
            return SimpleNamespace(returncode=0)
        runtime.relay._runner = queue
        def reply(_cli, event, answer, *a, **kw):
            delivered.append((event["message_id"], answer))
            return lark.ReplyResult(True)
        try:
            with patch.object(runtime_module, "reply_to_message", side_effect=reply), \
                 patch.object(lark, "run_command", side_effect=AssertionError("no external CLI")):
                for i, message in enumerate(("/model luna low", "first new request", "second new request")):
                    current_event = f"model-event-{i}"
                    event = {"event_id": current_event, "message_id": f"model-message-{i}", "chat_id": "offline-chat",
                             "chat_type": "p2p", "sender_id": "offline-owner", "message_type": "text", "content": message}
                    runtime.intake(event)
                    deadline = time.monotonic() + 3
                    while runtime._scheduled and time.monotonic() < deadline: time.sleep(0.01)
                    self.assertFalse(runtime._scheduled)
                    runtime.intake(event)
            self.assertEqual(len(payloads), 2)
            self.assertEqual({k: payloads[0][k] for k in CHOICE}, CHOICE)
            self.assertNotIn("model", payloads[1])
            self.assertNotIn("thinking", payloads[1])
            self.assertEqual(len(delivered), 3)
            self.assertIn("下一条新消息", delivered[0][1])
            self.assertEqual([v for _, v in delivered[1:]], ["精确回传", "精确回传"])
            self.assertEqual(runtime.relay.pending_count(), 0)
        finally:
            with patch.object(runtime, "write_health"): runtime.shutdown()

    def test_empty_probe_reports_loaded_contract_without_native_send(self):
        code = relay_mcp_server.relay_program(None)
        result = subprocess.run(["node", "-e", "const started=Date.now(); const text=x=>console.log(JSON.stringify(x)); (" + code + ")();"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["model_selection_contract"], "native_next_turn_v1")


if __name__ == "__main__": unittest.main()
