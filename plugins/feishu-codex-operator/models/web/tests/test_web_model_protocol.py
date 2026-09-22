"""Synthetic Web contracts only; no browser, tunnel, model or tool execution."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)


from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "scripts"))
from operator_core.model_registry import ModelRegistry
from operator_core.responses_capabilities import RouterError, UpstreamProtocolError
from operator_core.responses_tool_adapter import EXEC_GRAMMAR, NAMED_OUTPUT_PREFIX, dumps
from operator_core.web_model_protocol import WebModelProtocol, public_web_message


CAPS = {"protocol": "responses-tools-v1", "function_tools": True,
    "custom_tools": {"exec": "wrap"}, "tool_choice": ["auto", "none", "required"],
    "named_tool_choice": "native", "parallel_tool_calls": False, "tool_search": True,
    "input_modalities": ["text"], "structured_tool_outputs": False,
    "developer_role": "native", "reasoning_input": True, "reasoning_summary": False,
    "previous_response_id": False, "text_verbosity": False, "codex_tool_mode": "code_mode_only",
    "completed_output_policy": "require_message_or_tool"}
SLUG = "api/chatgpt-web/gpt-5.6-sol"
ROW = {"slug": SLUG, "display_name": "Web GPT-5.6 Sol contract fixture", "model": "gpt-5.6-sol",
    "api_base": "http://127.0.0.1:1/v1", "api_key_env": "", "context_window": 32000,
    "reasoning_efforts": ["high"], "responses": CAPS}
BEEPER = json.loads((_OPERATOR_PLUGIN_ROOT /
    "scripts/operator_core/beeper_model_catalog.json").read_text(encoding="utf-8"))
EXEC = {"type": "custom", "name": "exec", "description": "Native Codex exec",
    "format": {"type": "grammar", "syntax": "lark", "definition": EXEC_GRAMMAR}}
FUNCTION = {"type": "function", "name": "inspect", "description": "Synthetic read",
    "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                   "required": ["value"], "additionalProperties": False}}
SOURCE = '// @exec: {"max_output_tokens": 23}\r\ntext("中文😀 C:\\\\tmp\\\\a_b");\n'


def make(payload=None, **caps):
    row = deepcopy(ROW)
    row["responses"].update(caps)
    route = ModelRegistry({"version": 2, "models": [row]}, BEEPER).routes[SLUG]
    body = {"model": SLUG, "input": "Synthetic request", "tools": [],
            "reasoning": {"effort": "high"}, "stream": True}
    if payload:
        body.update(payload)
    return WebModelProtocol(route, body)


def message(parts=None, **changes):
    return {"id": "web_message_1", "author": {"role": "assistant"}, "recipient": "all",
            "status": "finished_successfully", "channel": "final", "end_turn": True,
            "content": {"content_type": "text", "parts": parts or ["Synthetic answer"]}, **changes}


def response(protocol, *items, **changes):
    return {"id": "response_web_1", "object": "response", "model": protocol.route.model,
            "status": "completed", "output": list(items), "usage": None, **changes}


class WebModelProtocolTests(unittest.TestCase):
    def test_managed_mcp_route_preserves_native_named_results_and_exec(self):
        from operator_web_model import text_route
        named = [{'type': 'function_call_output', 'namespace': 'codex_app', 'name': name,
            'output': [{'type': 'input_text', 'text': '<codex_delegation>中文\\n</codex_delegation>'}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'synthetic', 'create_time': 123.5}}
            for name in ('create_thread', 'send_message_to_thread')]
        named[1]['call_id'] = None
        envelope = {'type': 'additional_tools', 'role': 'developer', 'tools': [FUNCTION]}
        payload = {'model': SLUG, 'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [EXEC]}],
            'input': named + [envelope], 'reasoning': {'effort': 'high'}, 'parallel_tool_calls': False}
        original = deepcopy(payload)
        protocol = WebModelProtocol(text_route(tools=True), payload)
        self.assertEqual(payload, original)
        self.assertEqual(protocol.source_input(), original['input'])
        mapped = protocol.request()
        for source, item in zip(named, mapped['input']):
            self.assertEqual(item['role'], 'user')
            text = item['content'][0]['text']
            self.assertTrue(text.startswith(NAMED_OUTPUT_PREFIX))
            self.assertEqual(json.loads(text[len(NAMED_OUTPUT_PREFIX):]), source)
        self.assertEqual(len(mapped['input']), 2)
        self.assertEqual(len(mapped['tools']), 2)
        call = {'type': 'function_call', 'id': 'item_native', 'call_id': 'native_call',
            'name': protocol.mcp_tools()[0]['name'], 'arguments': dumps({'input': SOURCE}), 'status': 'completed'}
        restored, _ = protocol.complete(response(protocol, call))
        native = restored['output'][0]
        self.assertEqual((native['type'], native['namespace'], native['name'], native['input']),
            ('custom_tool_call', 'functions', 'exec', SOURCE))
        result = {'type': 'custom_tool_call_output', 'call_id': native['call_id'],
            'output': [{'type': 'input_text', 'text': ' exact result\r\n'}]}
        follow = WebModelProtocol(text_route(tools=True), {**payload, 'input': payload['input'] + [native, result]})
        self.assertEqual(follow.source_input()[-1], result)
        self.assertEqual(json.loads(follow.request()['input'][-2]['arguments']), {'input': SOURCE})

    def test_managed_codecs_reject_unknown_sources_and_leave_text_mode_unregistered(self):
        from operator_web_model import text_route
        named = {'type': 'function_call_output', 'namespace': 'codex_app', 'name': 'create_thread', 'output': 'text'}
        for payload, code in [
                ({'input': [{**named, 'name': 'unknown'}]}, 'named_function_output_not_registered'),
                ({'tools': [{**EXEC, 'name': 'unknown'}]}, 'custom_tool_not_registered'),
                ({'tools': [{**EXEC, 'format': {'type': 'grammar', 'syntax': 'lark', 'definition': 'unknown'}}]},
                    'unsupported_custom_tool_format'),
                ({'input': [{**named, 'output': [{'type': 'input_image', 'image_url': 'private'}]}]},
                    'named_function_output_requires_text_parts')]:
            with self.subTest(code=code), self.assertRaisesRegex(RouterError, code):
                WebModelProtocol(text_route(tools=True), {'model': SLUG, **payload})
        for payload in ({'input': [named]}, {'tools': [EXEC]},
                {'input': [{'type': 'additional_tools', 'role': 'developer', 'tools': [FUNCTION]}]}):
            with self.subTest(payload=payload), self.assertRaises(RouterError):
                WebModelProtocol(text_route(), {'model': SLUG, **payload})

    def citation_fixture(self):
        marker = '\ue200cite\ue202turn42search0\ue201'
        prefix = '🪐**中文 answer**。'
        raw = message([prefix + marker, '\r\n```text\na_b  \\n\n```'])
        total = sum(len(part) for part in raw['content']['parts'])
        source = {'title': 'A [public] source', 'url': 'https://example.com/a?q=x_y'}
        raw['public_references'] = [
            {'type': 'grouped_webpages', 'matched_text': marker, 'start_idx': len(prefix),
                'end_idx': len(prefix + marker), 'items': [source]},
            {'type': 'sources_footnote', 'matched_text': ' ', 'start_idx': total,
                'end_idx': total + 1, 'sources': [deepcopy(source)]}]
        return raw

    def test_explicit_citations_render_scalar_positions_and_keep_other_text(self):
        raw = self.citation_fixture()
        before = deepcopy(raw)
        protocol = WebModelProtocol(make().route, {'model': SLUG, 'input': 'citation fixture'},
            citation_mode='markdown_links_v1')
        result, events = protocol.complete_public_message('response_citations', raw)
        parts = result['output'][0]['content']
        self.assertEqual(parts[0]['text'], '🪐**中文 answer**。[A \\[public\\] source](<https://example.com/a?q=x_y>)')
        self.assertEqual(parts[1]['text'], raw['content']['parts'][1])
        self.assertEqual(raw, before)
        self.assertEqual(events[-1]['response'], result)
        self.assertEqual([item['type'] for item in result['output']], ['message'])
        self.assertNotIn('web_search_call', json.dumps(events))

    def test_citations_reject_wrong_positions_sources_and_unsafe_links(self):
        mutations = [
            lambda v: v['public_references'][0].update(start_idx=v['public_references'][0]['start_idx'] + 1),
            lambda v: v['public_references'][0].update(matched_text='different'),
            lambda v: v['public_references'].append(deepcopy(v['public_references'][0])),
            lambda v: v['public_references'][1]['sources'][0].update(title='unbound title'),
            lambda v: v['public_references'][0]['items'][0].update(url='javascript:alert(1)'),
            lambda v: v['public_references'][0]['items'][0].update(url='https://user:password@example.com'),
            lambda v: v['public_references'][0]['items'][0].update(url='https://example.com/\npath'),
            lambda v: v['public_references'][0]['items'][0].update(title='line\nbreak'),
            lambda v: v['public_references'][0].update(type='unknown'),
            lambda v: v.update(public_references=[]),
        ]
        for index, mutate in enumerate(mutations):
            raw = self.citation_fixture()
            mutate(raw)
            with self.subTest(index=index), self.assertRaises(RouterError):
                public_web_message(raw, citation_mode='markdown_links_v1')
        with self.assertRaisesRegex(RouterError, 'web_public_citation_mode_required'):
            public_web_message(self.citation_fixture())
        with self.assertRaisesRegex(RouterError, 'web_public_citations_invalid'):
            public_web_message(message(), citation_mode='markdown_links_v1')

    def test_citations_reject_cross_part_spans_and_preserve_empty_parts(self):
        raw = self.citation_fixture()
        raw['public_references'] = raw['public_references'][:1]
        text, suffix = raw['content']['parts']
        raw['content']['parts'] = ['', text, '', suffix]
        result = public_web_message(raw, citation_mode='markdown_links_v1')
        self.assertEqual([part['text'] for part in result['content']][::2], ['', ''])
        raw['content']['parts'] = [text[:-1], text[-1:] + suffix]
        with self.assertRaisesRegex(RouterError, 'web_public_citation_text_mismatch'):
            public_web_message(raw, citation_mode='markdown_links_v1')

    def url_fixture(self):
        raw = self.citation_fixture()
        label = '中文😀 [Link]'
        marker = '\ue200url\ue202' + label + '\ue202turn0search2\ue201'
        offset = sum(map(len, raw['content']['parts']))
        raw['content']['parts'].extend(['', marker, '\r\n'])
        total = sum(map(len, raw['content']['parts']))
        raw['public_references'][1].update(start_idx=total, end_idx=total)
        raw['public_references'].insert(1, {'type': 'url', 'title': label,
            'matched_text': marker, 'start_idx': offset, 'end_idx': offset + len(marker),
            'item': {'title': 'Distinct source title', 'url': 'https://example.net/new?q=a_b'}})
        return raw

    def test_url_labels_and_zero_width_footnote_preserve_parts_and_sources(self):
        raw = self.url_fixture(); original = deepcopy(raw)
        result = public_web_message(raw, citation_mode='markdown_links_v1')
        self.assertEqual(result['content'][3]['text'], '[中文😀 \\[Link\\]](<https://example.net/new?q=a_b>)')
        self.assertEqual([part['text'] for part in result['content']][1:3], raw['content']['parts'][1:3])
        self.assertEqual(result['content'][-1]['text'], '\r\n')
        self.assertEqual(raw, original)
        raw['public_references'][-1]['end_idx'] += 1
        self.assertEqual(public_web_message(raw, citation_mode='markdown_links_v1'), result)

    def test_url_validation_rejects_unbound_labels_spans_and_sources(self):
        mutations = [
            lambda v: v['public_references'][1].update(title='changed'),
            lambda v: v['public_references'][1].update(start_idx=0),
            lambda v: v['public_references'][1]['item'].update(url='javascript:evil()'),
            lambda v: v['public_references'][1]['item'].update(title='unsafe\nlabel'),
            lambda v: v['public_references'][1].pop('item'),
            lambda v: v['public_references'].pop(1),
            lambda v: v['public_references'].append(deepcopy(v['public_references'][1])),
            lambda v: v['public_references'][-1].update(start_idx=0),
            lambda v: v['public_references'][1].update(type=[]),
        ]
        for index, mutate in enumerate(mutations):
            raw = self.url_fixture(); mutate(raw)
            with self.subTest(index=index), self.assertRaises(RouterError):
                public_web_message(raw, citation_mode='markdown_links_v1')

    def test_url_only_with_empty_citation_footer_and_plain_mode_are_distinct(self):
        raw = self.url_fixture()
        raw['public_references'] = [raw['public_references'][1]]
        raw['content']['parts'][0] = 'x' * len(raw['content']['parts'][0])
        public_web_message(raw, citation_mode='markdown_links_v1')
        with self.assertRaisesRegex(RouterError, 'web_public_citation_mode_required'):
            public_web_message(raw)
        raw['public_references'][0]['end_idx'] = raw['public_references'][0]['start_idx']
        with self.assertRaisesRegex(RouterError, 'web_public_citation_position_invalid'):
            public_web_message(raw, citation_mode='markdown_links_v1')

    def test_footer_subset_never_drops_earlier_inline_sources(self):
        raw = self.url_fixture()
        ref = raw['public_references'][1]
        ref['type'] = 'grouped_webpages'
        ref['items'] = [ref.pop('item')]
        ref.pop('title')
        marker = '\ue200cite\ue202turn0search2\ue201'
        raw['content']['parts'][3] = marker
        ref.update(matched_text=marker, end_idx=ref['start_idx'] + len(marker))
        total = sum(map(len,raw['content']['parts']))
        raw['public_references'][-1].update(start_idx=total,end_idx=total)
        result = public_web_message(raw,citation_mode='markdown_links_v1')
        rendered = ''.join(part['text'] for part in result['content'])
        self.assertIn('https://example.net/new?q=a_b',rendered)
        self.assertIn('https://example.com/a?q=x_y',rendered)

    def test_workspace_telemetry_is_not_a_permission_or_sandbox_override(self):
        for state in ({'has_changes': 1}, {'has_changes': True, 'sandbox': 'disabled'}, None,
                {'has_changes': True, 'associated_remote_urls': []},
                {'has_changes': True, 'associated_remote_urls': {'origin': {'url': 'x'}}},
                {'has_changes': True, 'latest_git_commit_hash': 'unknown'},
                {'has_changes': True, 'latest_git_commit_hash': None},
                {'has_changes': True, 'permission': 'all'},
                {'associated_remote_urls': {'origin': 'https://example.test/repo.git'}}):
            with self.subTest(state=state), self.assertRaisesRegex(RouterError,
                    'web_workspace_telemetry_shape_unsupported'):
                make({'client_metadata': {'x-codex-turn-metadata': json.dumps({
                    'workspaces': {'fixture': state}})}})

    def test_dated_git_telemetry_can_arrive_late_without_changing_original_request(self):
        base={'turn_id':'fixture','sandbox_mode':'read-only','auto_review_enabled':False}
        initial=make({'client_metadata':{'x-codex-turn-metadata':json.dumps(base)}})
        for dirty in (False,True):
            metadata={**base,'workspaces':{'fixture':{'has_changes':dirty,
                'associated_remote_urls':{'origin':'https://example.test/repo.git'},
                'latest_git_commit_hash':'a'*40}}}
            raw=json.dumps(metadata)
            continued=make({'client_metadata':{'x-codex-turn-metadata':raw}})
            self.assertEqual(initial.continuation_contract(),continued.continuation_contract())
            self.assertEqual(continued.request()['client_metadata']['x-codex-turn-metadata'],raw)
            metadata['sandbox_mode']='workspace-write'
            changed=make({'client_metadata':{'x-codex-turn-metadata':json.dumps(metadata)}})
            self.assertNotEqual(initial.continuation_contract(),changed.continuation_contract())

    def test_git_telemetry_bounds_reject_before_tool_release(self):
        for workspaces in ([], {'':{'has_changes':True}},
                {'x':{'has_changes':True,'associated_remote_urls':{'origin':'x'*8193}}},
                {str(i):{'has_changes':True} for i in range(33)}):
            with self.subTest(value=workspaces), self.assertRaisesRegex(RouterError,
                    'web_workspace_telemetry_shape_unsupported'):
                make({'client_metadata':{'x-codex-turn-metadata':json.dumps({'workspaces':workspaces})}})

    def test_continuation_diagnostics_keep_only_fixed_labels_and_preserve_contract(self):
        before = make({'metadata': {'private_key': True}, 'client_metadata': {
            'x-codex-turn-metadata': json.dumps({'sandbox_mode': 'read-only', 'private_key': 'secret-old'})}})
        after = make({'metadata': {'private_key': 1}, 'client_metadata': {
            'private_key': 'secret-new',
            'x-codex-turn-metadata': json.dumps({'sandbox_mode': 'workspace-write', 'private_key': 'secret-new'})}})
        contracts = (before.continuation_contract(), after.continuation_contract())
        diagnostic = after.continuation_changes(before)
        self.assertEqual(diagnostic, {'fields': ['client_metadata', 'metadata'],
            'client_metadata': ['other', 'x-codex-turn-metadata'],
            'turn_metadata': ['other', 'sandbox_mode']})
        for private in ('private_key', 'secret', 'read-only', 'workspace-write'):
            self.assertNotIn(private, json.dumps(diagnostic))
        self.assertNotEqual(*contracts)
        self.assertEqual(contracts, (before.continuation_contract(), after.continuation_contract()))
        self.assertEqual(before.continuation_changes(before), {'fields': []})

    def test_continuation_diagnostics_distinguish_absent_null_and_typed_changes(self):
        for left, right in (({}, {'metadata': None}), ({'metadata': None}, {'metadata': {}}),
                ({'metadata': {'a': True}}, {'metadata': {'a': 1}}),
                ({'client_metadata': None}, {'client_metadata': {}})):
            with self.subTest(left=left, right=right):
                initial, changed = make(left), make(right)
                self.assertNotEqual(initial.continuation_contract(), changed.continuation_contract())
                self.assertTrue(changed.continuation_changes(initial)['fields'])

    def test_public_markdown_parts_and_native_events_are_exact(self):
        parts = ["  a_b 中文✓\r\n", "", '```python\nx = "C:\\\\tmp\\\\a_b"\n```\n']
        raw = message(parts)
        before = deepcopy(raw)
        final, events = make().complete_public_message("response_1", raw)
        self.assertEqual(raw, before)
        self.assertEqual([part["text"] for part in final["output"][0]["content"]], parts)
        deltas = [e for e in events if e["type"] == "response.output_text.delta"]
        self.assertEqual([(e["content_index"], e["delta"]) for e in deltas], list(enumerate(parts)))
        self.assertEqual(events[-1]["response"], final)
        self.assertEqual(final["model"], SLUG)
        self.assertIsNone(final["usage"])

    def test_private_nontext_unfinished_and_ambiguous_parts_are_rejected(self):
        bad = [message(channel="analysis"), message(status="in_progress"), message(end_turn=False),
               message(recipient="some_tool"), message(author={"role": "tool"}),
               message(metadata={"is_visually_hidden_from_conversation": True}),
               message(metadata={"is_visually_hidden": "true"}),
               message(metadata={"is_visually_hidden": 1}),
               message(content={"content_type": "thoughts", "parts": ["private"]}),
               message(content={"content_type": "text", "parts": ["good", {"image": "x"}]}),
               message(content={"content_type": "text", "text": "fallback"}),
               message(channel=[]), message(end_turn=1), message(parts=["\ud800"])]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(RouterError):
                public_web_message(value)
        with self.assertRaisesRegex(RouterError, "web_commentary_is_not_final_answer"):
            make().complete_public_message("response_1", message(channel="commentary", end_turn=False))

    def test_public_message_namespace_is_stable_without_rewriting_history(self):
        raw = message(['  中文\r\n', '', 'unchanged'], id='3ae86d94-6b8f-4eba-974c-b5fd7c061f82')
        original = deepcopy(raw)
        result, events = make().complete_public_message('response_ids', raw)
        item = result['output'][0]
        self.assertRegex(item['id'], r'^msg_[A-Za-z0-9_]{1,60}$')
        self.assertEqual(public_web_message(raw)['id'], item['id'])
        self.assertEqual(raw, original)
        for event in events:
            if 'item_id' in event:
                self.assertEqual(event['item_id'], item['id'])
            if 'item' in event:
                self.assertEqual(event['item']['id'], item['id'])
        self.assertEqual(events[-1]['response'], result)
        # Old Web UUIDs and the new projected message both stay exactly as
        # supplied when a later caller provides history. No migration/repair.
        historical = {**deepcopy(item), 'id': raw['id']}
        payload = {'input': [historical, item]}
        before = deepcopy(payload)
        following = make(payload)
        self.assertEqual(payload, before)
        self.assertEqual(following.source_input(), before['input'])
        self.assertEqual(following.request()['input'], before['input'])

    def test_public_message_ids_are_bounded_distinct_and_require_original_identity(self):
        source_ids = ['plain', 'msg_plain', '界' * 170, 'x' * 512]
        projected = [public_web_message(message(id=value))['id'] for value in source_ids]
        self.assertEqual(len(set(projected)), len(source_ids))
        for item_id in projected:
            self.assertRegex(item_id, r'^msg_[A-Za-z0-9_]{1,60}$')
        for source_id in (None, '', 'x' * 513, '\ud800'):
            with self.subTest(source_id=repr(source_id)), self.assertRaises(RouterError):
                public_web_message(message(id=source_id))

    def test_utf8_bound_and_empty_answer_have_no_repair(self):
        with patch("operator_core.web_model_protocol.MAX_EVENT_BYTES", 5):
            with self.assertRaises(RouterError):
                public_web_message(message(["中文"]))
        with self.assertRaises(UpstreamProtocolError):
            make().complete_public_message("response_1", message(["", ""]))

    def test_request_schema_uses_existing_aliases_without_input_mutation(self):
        tools = [EXEC, {"type": "namespace", "name": "mcp__fixture", "tools": [FUNCTION]}]
        original = deepcopy(tools)
        protocol = make({"tools": tools})
        request = protocol.request()
        declared = protocol.mcp_tools()
        self.assertEqual(tools, original)
        self.assertEqual([t["name"] for t in declared], [t["name"] for t in request["tools"]])
        self.assertEqual(declared[1]["inputSchema"], FUNCTION["parameters"])
        request["tools"][1]["parameters"]["properties"].clear()
        declared[1]["inputSchema"].clear()
        self.assertEqual(protocol.mcp_tools()[1]["inputSchema"], FUNCTION["parameters"])
        with self.assertRaisesRegex(RouterError, "web_mcp_object_schema_required"):
            make({"tools": [{**FUNCTION, "parameters": {"type": "string"}}]})
        with self.assertRaisesRegex(RouterError, "web_mcp_text_description_required"):
            make({"tools": [{**FUNCTION, "description": None}]})

    def test_custom_exec_and_paired_result_roundtrip_preserve_source(self):
        protocol = make({"tools": [EXEC]})
        wire_name = protocol.mcp_tools()[0]["name"]
        raw = {"type": "function_call", "id": "item_1", "call_id": "real_call_1",
               "name": wire_name, "arguments": dumps({"input": SOURCE}), "status": "completed"}
        final, events = protocol.complete(response(protocol, raw))
        call = final["output"][0]
        self.assertEqual(call["type"], "custom_tool_call")
        self.assertEqual(call["input"], SOURCE)
        self.assertEqual(call["call_id"], "real_call_1")
        self.assertEqual(events[-1]["response"]["output"], [call])
        result = {"type": "custom_tool_call_output", "call_id": call["call_id"],
                  "output": " 真实结果\r\n"}
        following = make({"tools": [EXEC], "input": [call, result]}).request()
        self.assertEqual(json.loads(following["input"][0]["arguments"]), {"input": SOURCE})
        self.assertEqual(following["input"][1]["call_id"], "real_call_1")
        self.assertEqual(following["input"][1]["output"], result["output"])

    def test_failure_unknown_tool_and_trailing_bad_content_release_nothing(self):
        protocol = make({"tools": [FUNCTION]})
        call = {"type": "function_call", "id": "item_1", "call_id": "real_call_1",
                "name": protocol.mcp_tools()[0]["name"], "arguments": '{"value":"中文"}', "status": "completed"}
        bad_message = {"type": "message", "id": "item_2", "role": "assistant",
                       "content": [{"type": "input_text", "text": "invalid"}], "status": "completed"}
        for raw in [response(protocol, call, status="failed"),
                    response(protocol, {**call, "name": "not_declared"}),
                    response(protocol, call, bad_message), response(protocol, call, call)]:
            with self.subTest(raw=raw), self.assertRaises(UpstreamProtocolError):
                protocol.complete(raw)

    def test_tool_choice_and_model_identity_cannot_be_widened(self):
        protocol = make({"tools": [FUNCTION], "tool_choice": "none"})
        call = {"type": "function_call", "id": "item_1", "call_id": "real_call_1",
                "name": protocol.mcp_tools()[0]["name"], "arguments": '{}', "status": "completed"}
        with self.assertRaises(UpstreamProtocolError):
            protocol.complete(response(protocol, call))
        with self.assertRaisesRegex(RouterError, "web_response_model_mismatch"):
            protocol.complete(response(protocol, model="latest"))
        with self.assertRaisesRegex(RouterError, "web_explicit_route_required"):
            make({"model": "gpt-6"})
        with self.assertRaisesRegex(RouterError, "web_mcp_function_representation_required"):
            make({"tools": [EXEC]}, custom_tools={"exec": "native"})

    def test_tool_like_prose_never_becomes_a_call(self):
        prose = '{"type":"function_call","name":"exec","arguments":"do something"}'
        final, _ = make().complete_public_message("response_1", message([prose]))
        self.assertEqual([item["type"] for item in final["output"]], ["message"])
        self.assertEqual(final["output"][0]["content"][0]["text"], prose)


if __name__ == "__main__":
    unittest.main()
