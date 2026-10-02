"""Own transient MCP transport boundaries. No real browser, task or tool."""

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
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web
from test_web_model_protocol import make, message, FUNCTION
from operator_core.responses_capabilities import RouterError
from operator_core.responses_tool_adapter import dumps
from operator_core.web_model_protocol import _tool_declaration_change_kinds
from operator_core.web_mcp_transport import (WebMcpTurn, WebMcpEndpoint,
    QuickTunnelAnnouncement, WebResponsesBridge, IndexedWebRequest, INDEX_REPLY_BYTES, INDEX_READ_LIMIT)


class QuickTunnelAnnouncementTests(unittest.TestCase):
    def test_failure_urls_never_claim_a_connected_endpoint(self):
        parser = QuickTunnelAnnouncement()
        for line in ['failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": EOF',
                '2026-09-15T10:17:18Z INF Requesting new quick Tunnel on trycloudflare.com...',
                '2026-09-15T10:17:18Z INF |  https://unbound.trycloudflare.com  |',
                '2026-09-15T10:17:18Z INF Registered tunnel connection connIndex=0 fixture']:
            self.assertFalse(parser.feed(line))
        self.assertIsNone(parser.origin)

    def test_banner_and_connection_are_both_required_and_address_cannot_change(self):
        parser = QuickTunnelAnnouncement()
        self.assertFalse(parser.feed('2026-09-15T10:17:18Z INF |  Your quick Tunnel has been created! Visit it at (fixture):  |'))
        self.assertFalse(parser.feed('2026-09-15T10:17:18Z INF |  https://api.trycloudflare.com  |'))
        self.assertIsNone(parser.origin)
        self.assertFalse(parser.feed('2026-09-15T10:17:18Z INF |  https://owned-fixture.trycloudflare.com  |'))
        self.assertEqual(parser.origin, 'https://owned-fixture.trycloudflare.com')
        self.assertTrue(parser.feed('2026-09-15T10:17:18Z INF Registered tunnel connection connIndex=0 fixture'))
        with self.assertRaisesRegex(RouterError, 'web_tunnel_address_changed'):
            parser.feed('2026-09-15T10:17:18Z INF |  https://changed-fixture.trycloudflare.com  |')


def protocol(items=None, **controls):
    return make({'input': items if items is not None else [{'role': 'user', 'content': 'fixture'}],
        'tools': [FUNCTION], **controls}, structured_tool_outputs=True)


class WebMcpSessionRecyclingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.endpoint = WebMcpEndpoint()
        self.url = await self.endpoint.start()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.endpoint.stop()

    async def rpc(self, session, payload):
        headers = {'Mcp-Session-Id': session} if session is not None else {}
        async with self.client.post(self.url, headers=headers, json=payload) as response:
            body = await response.read()
            return response.status, json.loads(body) if body else None, dict(response.headers)

    async def initialize(self):
        status, body, headers = await self.rpc(None, {'jsonrpc': '2.0', 'id': 0,
            'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}})
        self.assertEqual(status, 200)
        self.assertIn('result', body)
        return headers['Mcp-Session-Id']

    async def test_non_object_parameters_fail_as_rpc_errors_without_cancelling_a_turn(self):
        for params in (None, [], 'invalid'):
            with self.subTest(method='initialize', params=params):
                status, body, _ = await self.rpc(None, {'jsonrpc': '2.0', 'id': 0,
                    'method': 'initialize', 'params': params})
                self.assertEqual(status, 200)
                self.assertEqual(body['error']['message'], 'web_mcp_invalid_request')
                self.assertEqual(self.endpoint.sessions, {})
        session = await self.initialize()
        turn = self.endpoint.turn = WebMcpTurn(protocol())
        try:
            for params in (None, [], 'invalid'):
                with self.subTest(method='notifications/cancelled', params=params):
                    status, body, _ = await self.rpc(session, {'jsonrpc': '2.0',
                        'method': 'notifications/cancelled', 'params': params})
                    self.assertEqual(status, 200)
                    self.assertEqual(body['error']['message'], 'web_mcp_invalid_request')
                    self.assertFalse(turn.closed)
        finally:
            turn.close()

    async def ping(self, session, number=1):
        status, body, _ = await self.rpc(session, {'jsonrpc': '2.0', 'id': number, 'method': 'ping'})
        self.assertEqual((status, body), (200, {'jsonrpc': '2.0', 'id': number, 'result': {}}))

    async def used_session(self):
        session = await self.initialize()
        await self.ping(session)
        return session

    async def test_many_sequential_turn_reads_stay_bounded_and_old_ids_never_replay(self):
        sessions = []
        for index in range(160):
            turn = self.endpoint.turn = WebMcpTurn(protocol([{'role': 'user', 'content': 'new-' + str(index)}]))
            session = await self.initialize()
            sessions.append(session)
            status, _, _ = await self.rpc(session, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            self.assertEqual(status, 202)
            payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'operator_begin', 'arguments': {'turn_key': turn.key}}}
            status, body, _ = await self.rpc(session, payload)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body['result']['content'][0]['text'])['request']['input'],
                turn.protocol.request()['input'])
            self.assertLessEqual(len(self.endpoint.sessions), 64)
            self.assertEqual(turn.calls, 0)
            turn.close()
        status, _, _ = await self.rpc(sessions[0], payload)
        self.assertEqual(status, 404)
        status, body, _ = await self.rpc(sessions[-1], payload)
        self.assertEqual(body['error']['message'], 'web_mcp_duplicate_no_retry')
        self.assertEqual(self.endpoint.diagnostics()['session_pool'],
            {'limit': 64, 'size': 64, 'busy': 0, 'reclaimed': 96, 'expired': 0})
        # A new transport session does not revive an old completed turn.
        session = await self.initialize()
        _, body, _ = await self.rpc(session, payload)
        self.assertEqual(body['error']['message'], 'web_mcp_turn_closed')
        self.assertEqual((turn.calls, turn.released_calls, turn.results), (0, 0, 0))
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_closed'):
            await turn.next_response()

    async def test_recent_idle_use_is_kept_and_handshake_only_sessions_are_not_evicted(self):
        sessions = [await self.used_session() for _ in range(64)]
        await self.ping(sessions[0], 2)
        fresh = await self.initialize()
        self.assertIn(sessions[0], self.endpoint.sessions)
        self.assertNotIn(sessions[1], self.endpoint.sessions)
        self.assertIn(fresh, self.endpoint.sessions)
        # Eventually every slot belongs to a handshake not yet used for an RPC.
        for _ in range(63):
            await self.initialize()
        _, body, _ = await self.rpc(None, {'jsonrpc': '2.0', 'id': 0,
            'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}})
        self.assertEqual(body['error']['message'], 'web_mcp_session_limit')
        self.assertEqual(len(self.endpoint.sessions), 64)

    async def test_session_is_kept_while_a_request_body_is_still_arriving(self):
        session = await self.used_session()
        release = asyncio.Event()
        async def body():
            yield b'{"jsonrpc":"2.0","id":2,'
            await release.wait()
            yield b'"method":"ping"}'
        async def slow_request():
            async with self.client.post(self.url, headers={'Mcp-Session-Id': session,
                    'Content-Type': 'application/json'}, data=body()) as response:
                return response.status, await response.json()
        task = asyncio.create_task(slow_request())
        try:
            async def body_is_waiting():
                while not self.endpoint.sessions[session].get('in_flight', 0):
                    await asyncio.sleep(.005)
            await asyncio.wait_for(body_is_waiting(), 1)
            for _ in range(70):
                await self.used_session()
            self.assertIn(session, self.endpoint.sessions)
            release.set()
            self.assertEqual(await asyncio.wait_for(task, 1),
                (200, {'jsonrpc': '2.0', 'id': 2, 'result': {}}))
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['busy'], 0)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_pending_http_result_survives_recycling_and_keeps_duplicate_guard(self):
        session = await self.used_session()
        turn = self.endpoint.turn = WebMcpTurn(protocol())
        source = turn.begin(turn.key)
        payload = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'operator_call', 'arguments': {'turn_key': turn.key,
                'name': 'inspect', 'arguments': {'value': 'waiting-native-result'}}}}
        task = asyncio.create_task(self.rpc(session, payload))
        try:
            response, _ = await asyncio.wait_for(turn.next_response(), 1)
            call = response['output'][0]
            for _ in range(96):
                await self.used_session()
            self.assertIn(session, self.endpoint.sessions)
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['busy'], 1)
            _, duplicate, _ = await self.rpc(session, payload)
            self.assertEqual(duplicate['error']['message'], 'web_mcp_duplicate_no_retry')
            self.assertFalse(turn.closed)
            output = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'unchanged\r\n真实'}
            turn.accept_result(protocol(source['request']['input'] + [call, output]))
            status, body, _ = await asyncio.wait_for(task, 1)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body['result']['content'][0]['text']), {'codex_function_result': output})
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['busy'], 0)
            await self.ping(session, 3)
            _, duplicate, _ = await self.rpc(session, payload)
            self.assertEqual(duplicate['error']['message'], 'web_mcp_duplicate_no_retry')
            self.assertEqual((turn.calls, turn.released_calls, turn.results), (1, 1, 1))
        finally:
            turn.close()
            await asyncio.gather(task, return_exceptions=True)

    async def test_expiry_never_removes_a_pending_call_then_releases_the_slot(self):
        session = await self.used_session()
        turn = self.endpoint.turn = WebMcpTurn(protocol())
        source = turn.begin(turn.key)
        # Direct transport users still pin by the pending call's exact session.
        task = asyncio.create_task(turn.invoke(turn.key, 2, 'inspect', {'value': 'direct'}, session_id=session))
        try:
            response, _ = await asyncio.wait_for(turn.next_response(), 1)
            self.endpoint.sessions[session]['deadline'] = 0
            for _ in range(70):
                await self.used_session()
            self.assertIn(session, self.endpoint.sessions)
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['busy'], 1)
            call = response['output'][0]
            output = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'direct-result'}
            turn.accept_result(protocol(source['request']['input'] + [call, output]))
            self.assertEqual(await task, {'codex_function_result': output})
            await self.initialize()
            self.assertNotIn(session, self.endpoint.sessions)
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['expired'], 1)
        finally:
            turn.close()
            await asyncio.gather(task, return_exceptions=True)

    async def test_matching_cancellation_releases_the_http_pin_without_replay(self):
        session = await self.used_session()
        turn = self.endpoint.turn = WebMcpTurn(protocol())
        turn.begin(turn.key)
        task = asyncio.create_task(self.rpc(session, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'operator_call', 'arguments': {'turn_key': turn.key,
                'name': 'inspect', 'arguments': {'value': 'cancelled'}}}}))
        try:
            await asyncio.wait_for(turn.next_response(), 1)
            for _ in range(70):
                await self.used_session()
            self.assertIn(session, self.endpoint.sessions)
            status, _, _ = await self.rpc(session, {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                'params': {'requestId': 2}})
            self.assertEqual(status, 202)
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
            self.assertTrue(turn.closed)
            self.assertEqual(self.endpoint.sessions[session]['in_flight'], 0)
            self.assertEqual(self.endpoint.diagnostics()['session_pool']['busy'], 0)
            self.assertEqual((turn.calls, turn.released_calls, turn.results), (1, 1, 0))
            _, body, _ = await self.rpc(session, {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'})
            self.assertEqual(body['error']['message'], 'web_mcp_duplicate_no_retry')
        finally:
            turn.close()
            await asyncio.gather(task, return_exceptions=True)


class IndexedWebRequestTests(unittest.IsolatedAsyncioTestCase):
    def decode_records(self, entries):
        records, pieces, active = [], [], None
        for entry in entries:
            if entry['encoding'] == 'json':
                self.assertIsNone(active)
                self.assertEqual(entry['record_index'], len(records))
                records.append(entry['value'])
            else:
                self.assertEqual(entry['record_index'], len(records))
                if active is None: active = entry['record_index']
                self.assertEqual(entry['record_index'], active)
                self.assertEqual(entry['fragment_index'], len(pieces))
                pieces.append(entry['json_fragment'])
                if len(pieces) == entry['fragment_total']:
                    records.append(json.loads(''.join(pieces)))
                    pieces, active = [], None
        self.assertIsNone(active)
        first = records[0]
        self.assertEqual(first['kind'], 'request_fields')
        request = deepcopy(first['value'])
        if first['input_format'] == 'array':
            self.assertEqual(first['input_count'], len(records) - 1)
            self.assertEqual([r['request_input_index'] for r in records[1:]], list(range(first['input_count'])))
            self.assertTrue(all(r['kind'] == 'input_item' for r in records[1:]))
            request['input'] = [r['value'] for r in records[1:]]
        elif first['input_format'] == 'value':
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]['kind'], 'input_value')
            request['input'] = records[1]['value']
        else:
            self.assertEqual(first['input_format'], 'absent')
            self.assertEqual(len(records), 1)
        return {'request': request, 'tools_present': first['tools_present'], 'tool_count': first['tool_count']}

    async def test_structured_context_records_preserve_full_order_and_block_incomplete_reads(self):
        from operator_core.web_mcp_transport import MCP_TOOLS
        from operator_core.web_browser_driver import current_user_preview
        original = [
            {'role': 'developer', 'content': '中😀 C:\\path "quote"\r\n\t' * 9000},
            {'role': 'user', 'content': 'OLD request; do not execute'},
            {'role': 'assistant', 'content': 'Old failure is retained'},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': 'NEW 当前请求\r\n'},
                {'type': 'input_text', 'text': ''}, {'type': 'input_text', 'text': '  trailing  '}]}]
        native = protocol(original)
        endpoint = WebMcpEndpoint(begin_result_mode='structured_begin_v1', indexed_protocol='mcp_context_records_v3')
        url = await endpoint.start(); self.addAsyncCleanup(endpoint.stop)
        turn = endpoint.turn = WebMcpTurn(native)
        preview = current_user_preview(original)
        turn.prepare_indexed(wire_protocol=endpoint.indexed_protocol, begin_result_mode=endpoint.begin_result_mode,
            source_user_preview=preview)
        key, entries, count = turn.key, [], 0
        shape = MCP_TOOLS[0]['outputSchema']['oneOf'][-1]
        async with ClientSession() as client:
            async with client.post(url, json={'jsonrpc':'2.0','id':0,'method':'initialize',
                    'params':{'protocolVersion':'2025-11-25'}}) as response:
                client.headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
            while key:
                rpc = int('9' * 4000) if count == 0 else '😀' * 124 + str(count)
                async with client.post(url, json={'jsonrpc':'2.0','id':rpc,'method':'tools/call',
                        'params':{'name':'operator_begin','arguments':{'turn_key':key}}}) as response:
                    raw = await response.read()
                    self.assertEqual(response.status, 200); self.assertLessEqual(len(raw), INDEX_REPLY_BYTES)
                    result = json.loads(raw)['result']
                self.assertEqual(result['content'], [])
                page = result['structuredContent']; self.assertEqual(page['index'], count)
                self.assertTrue(set(shape['required']) <= set(page) <= set(shape['properties']))
                self.assertNotIn('json_fragment', page)
                for entry in page['records']:
                    row = shape['properties']['records']['items']['oneOf'][entry['encoding'] != 'json']
                    self.assertEqual(set(entry), set(row['required']))
                entries.extend(page['records']); key = page['next_read_key']; count += 1
                if count == 1:
                    self.assertEqual(entries[0]['value']['current_user_preview'], preview)
                    self.assertEqual(entries[0]['value']['current_user_preview']['source_input_index'], 3)
                if key:
                    with self.assertRaisesRegex(RouterError, 'web_mcp_context_not_read'):
                        await turn.invoke(turn.key, 1, 'inspect', {'value':'not authorized by preview'})
            self.assertEqual(page['total'], count)
            self.assertGreater(count, 1)
            self.assertEqual(entries[-1]['encoding'], 'json')
            self.assertEqual(entries[-1]['value']['value'], original[-1])
            context = self.decode_records(entries)
            expected = native.request(); expected.pop('tools')
            self.assertEqual(context, {'request': expected, 'tools_present': True, 'tool_count': 1})
            self.assertEqual(native.source_input(), original)
            self.assertTrue(any(e['encoding'] == 'json_fragment' for e in entries))
            with self.assertRaisesRegex(RouterError, 'web_mcp_schema_not_read'):
                await turn.invoke(turn.key, 2, 'inspect', {'value':'not authorized by context alone'})
            catalog = turn.begin(page['catalog_read_key'])
            schema = turn.begin(catalog['entries'][0]['schema_read_key'])
            self.assertEqual(json.loads(schema['json_fragment'])['request_tool'], native.request()['tools'][0])
        self.assertEqual((turn.calls, turn.results), (0, 0))

    def test_context_header_preview_rejects_other_history_or_promoted_sources(self):
        original = [{'role':'user','content':'old'}, {'role':'user','content':'current 中文\r\n'}]
        good = {'source_input_index':1,'source_message':deepcopy(original[-1])}
        for preview in ({**good,'source_input_index':True}, {**good,'source_input_index':0},
                {**good,'source_message':original[0]}, {**good,'source_message':{'role':'user','content':'changed'}},
                {**good,'extra':'not allowed'}):
            with self.subTest(preview=preview), self.assertRaisesRegex(RouterError,'web_mcp_current_user_preview_unbound'):
                IndexedWebRequest(protocol(original),wire_protocol='mcp_context_records_v3',
                    begin_result_mode='structured_begin_v1',source_user_preview=preview)
        for tail in ({'role':'assistant','content':'not user'},
                {'role':'user','name':'tool-result','content':'not user'},
                {'role':'user','content':[{'type':'input_text','text':'text','other':'metadata'}]}):
            with self.subTest(tail=tail), self.assertRaisesRegex(RouterError,'web_mcp_current_user_preview_unbound'):
                IndexedWebRequest(protocol([tail]),wire_protocol='mcp_context_records_v3',
                    begin_result_mode='structured_begin_v1',source_user_preview={'source_input_index':0,'source_message':tail})
        with self.assertRaisesRegex(RouterError,'web_mcp_current_user_preview_unbound'):
            IndexedWebRequest(protocol(original),source_user_preview=good)

    def test_context_records_keep_absent_scalar_empty_and_many_items_distinct(self):
        cases = [{}, {'input': []}, {'input': ''}, {'input': None}, {'input': False},
            {'input': [{'role':'user','content':str(i)} for i in range(1600)]}]
        for request in cases:
            with self.subTest(shape=type(request.get('input')).__name__, present='input' in request):
                index = IndexedWebRequest.__new__(IndexedWebRequest)
                index.wire_protocol='mcp_context_records_v3';index.begin_result_mode='structured_begin_v1'
                index.pages, index.expected, index.catalog_key = {}, {}, None
                expected={'request':request,'tools_present':False,'tool_count':0}
                key=index.context_records(expected);entries=[];count=0
                while key:
                    page=index.pages[key][0];self.assertTrue(index.fits(page))
                    entries.extend(page['records']);key=page['next_read_key'];count+=1
                self.assertEqual(self.decode_records(entries), expected)
                self.assertLessEqual(count, 24)
                if isinstance(request.get('input'), list) and request['input']:
                    self.assertGreater(count, 1)
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_protocol_invalid'):
            IndexedWebRequest(protocol(),wire_protocol='mcp_context_records_v3')
        index.pages,index.expected={},{}
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_section_too_large'):
            index.context_records({'request':{'input':['\\"😀' * 1200000]},'tools_present':False,'tool_count':0})
        self.assertEqual(index.pages,{})

    def test_structured_large_ascii_record_uses_reply_budget_without_losing_any_source(self):
        source=[{'role':'developer','content':'A'*70000},
            {'role':'user','content':'current exact user\r\n'}]
        native=protocol(source)
        index=IndexedWebRequest(native,wire_protocol='mcp_context_records_v3',begin_result_mode='structured_begin_v1')
        key=index.first_key;entries=[];pages=[]
        while key:
            page=index.pages[key][0];self.assertTrue(index.fits(page))
            entries.extend(page['records']);pages.append(page);key=page['next_read_key']
        self.assertEqual(len(pages),2)
        fragments=[entry['json_fragment'] for entry in entries if entry['encoding']=='json_fragment']
        self.assertTrue(any(len(part)>32768 for part in fragments))
        expected=native.request();expected.pop('tools')
        self.assertEqual(self.decode_records(entries),{'request':expected,'tools_present':True,'tool_count':1})
        self.assertEqual(native.source_input(),source)

    async def test_paged_catalog_discovers_exact_entries_before_reading_the_remaining_inventory(self):
        from test_web_model_protocol import EXEC
        tools = [{**FUNCTION, 'description': '中文 schema 😀\\r\\n' * 3500},
            {'type': 'namespace', 'name': 'functions', 'tools': [EXEC]},
            *[{**FUNCTION, 'name': 'inspect_' + str(i)} for i in range(336)]]
        payload = {'input': [{'role': 'user', 'content': 'original 中文\r\n'}], 'tools': tools}
        caps = {'custom_tools': {'exec': 'wrap', 'functions.exec': 'wrap'}}
        native = make(payload, **caps)
        turn = WebMcpTurn(native)
        self.addCleanup(turn.close)
        turn.prepare_indexed(wire_protocol='mcp_catalog_pages_v2')
        context, last = self.read_section(turn, turn.key)
        hidden_key = next(k for k, (_, section, name, _) in turn.indexed.pages.items()
            if section == 'schema' and name == native.mcp_tools()[-1]['name'])
        with self.assertRaisesRegex(RouterError, 'web_mcp_catalog_entry_not_read'):
            turn.begin(hidden_key)
        first = turn.begin(last['catalog_read_key'])
        self.assertEqual(first['protocol'], 'mcp_catalog_pages_v2')
        self.assertGreater(first['total'], 1)
        self.assertNotIn('json_fragment', first)
        self.assertEqual(first['entries'][0]['name'], 'inspect')
        self.assertEqual(first['entries'][1]['source'], {'type': 'custom', 'namespace': 'functions', 'name': 'exec'})
        # A modified returned page cannot make an undiscovered schema readable.
        first['entries'].append({'name': native.mcp_tools()[-1]['name']})
        with self.assertRaisesRegex(RouterError, 'web_mcp_catalog_entry_not_read'):
            turn.begin(hidden_key)
        first['entries'].pop()
        self.assertFalse(turn.indexed.catalog_complete)
        before = turn.indexed.read_observation()
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_key_unavailable'):
            turn.begin(last['catalog_read_key'])
        self.assertEqual(turn.indexed.read_observation(), before)
        schema_first = turn.begin(first['entries'][0]['schema_read_key'])
        self.assertGreater(schema_first['total'], 1)
        with self.assertRaisesRegex(RouterError, 'web_mcp_schema_not_read'):
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'not released'})
        fragments = [schema_first['json_fragment']]
        key = schema_first['next_read_key']
        while key:
            page = turn.begin(key); fragments.append(page['json_fragment']); key = page['next_read_key']
        schema = json.loads(''.join(fragments))
        self.assertEqual(schema['request_tool'], native.request()['tools'][0])
        self.assertEqual(schema['mcp_tool'], native.mcp_tools()[0])
        self.assertFalse(turn.indexed.catalog_complete)
        task = asyncio.create_task(turn.invoke(turn.key, 2, 'inspect', {'value': 'exact 中文\r\n'}))
        response, _ = await turn.next_response()
        call = response['output'][0]
        self.assertEqual(json.loads(call['arguments']), {'value': 'exact 中文\r\n'})
        result = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'permission denied\r\n'}
        turn.accept_result(make({**payload, 'input': native.source_input() + [call, result]}, **caps))
        self.assertEqual(await task, {'codex_function_result': result})
        self.assertEqual(turn.indexed.page_reads['catalog'], 1)
        entries = first['entries']; key = first['next_read_key']; count = 1
        while key:
            page = turn.begin(key)
            self.assertEqual(page['index'], count)
            self.assertTrue(turn.indexed.fits(page))
            entries += page['entries']; key = page['next_read_key']; count += 1
        self.assertEqual(count, first['total'])
        self.assertEqual([entry['index'] for entry in entries], list(range(338)))
        self.assertEqual([entry['name'] for entry in entries], [tool['name'] for tool in native.mcp_tools()])
        self.assertEqual({entry['name']: entry['source'] for entry in entries}, native.mcp_tool_sources())
        expected = native.request(); expected.pop('tools')
        self.assertEqual(context['request'], expected)
        self.assertTrue(turn.indexed.catalog_complete)
        last_schema, _ = self.read_section(turn, entries[-1]['schema_read_key'])
        self.assertEqual(last_schema['request_tool'], native.request()['tools'][-1])
        turn.close()
        self.assertEqual(turn.indexed.discovered, set())
        self.assertEqual((turn.calls, turn.results), (1, 1))

    def test_paged_catalog_keeps_bounds_and_rejects_unknown_protocol(self):
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_protocol_invalid'):
            IndexedWebRequest(protocol(), wire_protocol='unknown')
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_protocol_invalid'):
            WebMcpEndpoint(indexed_protocol='mcp_catalog_pages_v2')
        index = IndexedWebRequest.__new__(IndexedWebRequest)
        index.wire_protocol = 'mcp_catalog_pages_v2'; index.pages, index.expected = {}, {}
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_page_too_large'):
            index.catalog_pages([{'name': 'x' * INDEX_REPLY_BYTES}])
        self.assertEqual(index.pages, {})
        # Small entries keep every Unicode, quote and slash byte without splitting a row.
        original = [{'index': i, 'name': '中文😀\\path\"' + str(i), 'source': {'name': 'source\r\n'},
            'schema_read_key': 'f' * 64} for i in range(400)]
        key = index.catalog_pages(original); reconstructed = []
        while key:
            page = index.pages[key][0]
            self.assertTrue(index.fits(page))
            self.assertTrue(page['entries'])
            reconstructed += page['entries']; key = page['next_read_key']
        self.assertEqual(reconstructed, original)

    def test_unicode_and_escaped_pages_use_the_available_wire_budget_losslessly(self):
        for label, source, maximum in [
                ('ascii', 'workspace file\n' * 18000, 9),
                ('unicode', '中文目录😀\r\n' * 18000, 12),
                ('quoted', 'C:\\project\\file "value"\r\n' * 10000, 16)]:
            with self.subTest(label=label):
                index = IndexedWebRequest.__new__(IndexedWebRequest)
                index.pages, index.expected = {}, {}
                value = {'request': {'input': [{'role': 'user', 'content': source}]}}
                key = index.fragments('context', value)
                fragments = []
                while key:
                    page = index.pages[key][0]
                    self.assertTrue(index.fits(page))
                    fragments.append(page['json_fragment'])
                    key = page['next_read_key']
                self.assertLessEqual(len(fragments), maximum)
                self.assertEqual(json.loads(''.join(fragments)), value)
                # Even an empty prefix cannot fit this oversized envelope.
                with self.assertRaisesRegex(RouterError, 'web_mcp_index_page_too_large'):
                    index.fragments('context', {}, final_fields={'extra': 'x' * INDEX_REPLY_BYTES})
                with self.assertRaisesRegex(RouterError, 'web_mcp_index_section_too_large'):
                    index.fragments('context', value, maximum_pages=1)

    def read_section(self, turn, key):
        fragments = []
        while key:
            page = turn.begin(key)
            self.assertEqual(page['index'], len(fragments))
            # Measure the actual outer HTTP JSON with a maximal string RPC id.
            result = ({'structuredContent': page, 'content': [], 'isError': False}
                if turn.indexed.begin_result_mode == 'structured_begin_v1' else {
                'content': [{'type': 'text', 'text': json.dumps(page, ensure_ascii=False,
                    separators=(',', ':'))}], 'isError': False})
            wire = json.dumps({'jsonrpc': '2.0', 'id': '😀' * 128, 'result': result}, ensure_ascii=False,
                separators=(',', ':')).encode('utf8')
            self.assertLessEqual(len(wire), INDEX_REPLY_BYTES)
            fragments.append(page['json_fragment'])
            key = page['next_read_key']
        self.assertEqual(page['total'], len(fragments))
        return json.loads(''.join(fragments)), page

    async def description_fixture(self, *, spare_description='Unread original', mode='unread',
            wire_protocol='mcp_indexed_request_v1'):
        payload = {'input': [{'role': 'user', 'content': 'new fixture'}],
            'tools': [FUNCTION, {'type': 'namespace', 'name': 'fixture_tools', 'tools': [
                {**FUNCTION, 'name': 'spare', 'description': spare_description}]}]}
        native = make(payload, structured_tool_outputs=True)
        turn = WebMcpTurn(native)
        self.addCleanup(turn.close)
        turn.prepare_indexed(wire_protocol=wire_protocol,
            begin_result_mode='text_v1' if wire_protocol == 'mcp_indexed_request_v1' else 'structured_begin_v1')
        if wire_protocol == 'mcp_indexed_request_v1':
            _, last = self.read_section(turn, turn.key)
            catalog, _ = self.read_section(turn, last['catalog_read_key'])
        else:
            key = turn.key
            while key:
                page = turn.begin(key)
                key = page['next_read_key']
            catalog, key = [], page['catalog_read_key']
            while key:
                page = turn.begin(key)
                catalog.extend(page['entries'])
                key = page['next_read_key']
        self.read_section(turn, catalog[0]['schema_read_key'])
        if mode == 'read':
            self.read_section(turn, catalog[1]['schema_read_key'])
        elif mode == 'partial':
            self.assertIsNotNone(turn.begin(catalog[1]['schema_read_key'])['next_read_key'])
        task = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'first'}))
        response, _ = await turn.next_response()
        call = response['output'][0]
        continued = deepcopy(payload)
        result = {'type': 'function_call_output', 'call_id': call['call_id'],
            'output': [{'type': 'input_text', 'text': 'permission denied\r\n'},
                       {'type': 'input_text', 'text': 'unchanged second part'}]}
        continued['input'] += [call, result]
        return turn, task, payload, continued, catalog, result

    async def test_unread_description_refresh_preserves_result_and_published_schema_key(self):
        for wire in ('mcp_indexed_request_v1', 'mcp_catalog_pages_v2', 'mcp_context_records_v3'):
            with self.subTest(wire=wire):
                await self.description_success_case(wire)

    async def description_success_case(self, wire):
        turn, task, original, continued, catalog, result = await self.description_fixture(wire_protocol=wire)
        continued['tools'][1]['tools'][0]['description'] = 'Exact new description 中文\r\n' * 1800
        new = make(continued, structured_tool_outputs=True)
        reads = turn.indexed.reads
        old_keys = {key for key, row in turn.indexed.pages.items() if row[2] == catalog[1]['name']}
        try:
            turn.accept_result(new)
            self.assertEqual(await task, {'codex_function_result': result})
            self.assertEqual(turn.indexed.reads, reads)
            self.assertNotIn(catalog[1]['name'], turn.indexed.described)
            self.assertEqual(turn.observation()['unread_description_refreshes'], 1)
            self.assertNotIn('binding_changes', turn.observation())
            schema, last = self.read_section(turn, catalog[1]['schema_read_key'])
            self.assertGreater(last['total'], 1)
            self.assertEqual(schema['request_tool'], new.request()['tools'][1])
            self.assertEqual(schema['mcp_tool'], new.mcp_tools()[1])
            self.assertFalse(old_keys & set(turn.indexed.pages))
            second = asyncio.create_task(turn.invoke(turn.key, 2, catalog[1]['name'], {'value': 'second'}))
            try:
                response, _ = await turn.next_response()
                call = response['output'][0]
                self.assertEqual((call['name'], call['namespace']), ('spare', 'fixture_tools'))
                continued['input'] += [call, {'type': 'function_call_output',
                    'call_id': call['call_id'], 'output': 'exact second result'}]
                turn.accept_result(make(continued, structured_tool_outputs=True))
                self.assertEqual((await second)['codex_function_result']['output'], 'exact second result')
                turn.finish(message(['finished']))
                final, _ = await turn.next_response()
                self.assertEqual(final['output'][0]['content'][0]['text'], 'finished')
            finally:
                turn.close()
                await asyncio.gather(second, return_exceptions=True)
        finally:
            turn.close()
            await asyncio.gather(task, return_exceptions=True)

    async def test_description_refresh_rejects_read_partial_schema_and_other_contract_changes(self):
        cases = ('read', 'partial', 'parameters', 'strict', 'reordered', 'namespace',
            'instructions', 'history', 'call_id')
        for case in cases:
            with self.subTest(case=case):
                turn, task, _, continued, catalog, _ = await self.description_fixture(
                    spare_description='large description ' * 4000 if case == 'partial' else 'original',
                    mode=case)
                prior = turn.protocol
                continued['tools'][1]['tools'][0]['description'] = 'changed'
                if case == 'parameters':
                    continued['tools'][1]['tools'][0]['parameters']['properties']['extra'] = {'type': 'number'}
                elif case == 'strict': continued['tools'][1]['tools'][0]['strict'] = True
                elif case == 'reordered': continued['tools'].reverse()
                elif case == 'namespace': continued['tools'][1]['description'] = 'namespace changed'
                elif case == 'instructions': continued['instructions'] = 'changed'
                elif case == 'history': continued['input'][0]['content'] = 'changed'
                elif case == 'call_id': continued['input'][-2]['arguments'] = '{"value":"altered"}'
                expected = ('web_mcp_history_changed' if case == 'history' else
                    'web_mcp_call_identity_changed' if case == 'call_id' else
                    'web_mcp_request_binding_changed')
                try:
                    with self.assertRaisesRegex(RouterError, '^' + expected + '$'):
                        turn.accept_result(make(continued, structured_tool_outputs=True))
                    self.assertIs(turn.protocol, prior)
                    self.assertEqual(turn.results, 0)
                    self.assertNotIn('unread_description_refreshes', turn.observation())
                finally:
                    turn.close()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_unread_description_refresh_preserves_read_budget_and_page_capacity(self):
        for over_capacity in (False, True):
            with self.subTest(over_capacity=over_capacity):
                turn, task, _, continued, catalog, result = await self.description_fixture()
                continued['tools'][1]['tools'][0]['description'] = (
                    'x' * (INDEX_REPLY_BYTES * 25) if over_capacity else 'new unread description')
                old_protocol = turn.protocol
                try:
                    if over_capacity:
                        with self.assertRaisesRegex(RouterError, '^web_mcp_index_section_too_large$'):
                            turn.accept_result(make(continued, structured_tool_outputs=True))
                        self.assertIs(turn.protocol, old_protocol)
                        self.assertEqual(turn.results, 0)
                    else:
                        turn.indexed.reads = INDEX_READ_LIMIT
                        turn.accept_result(make(continued, structured_tool_outputs=True))
                        self.assertEqual(await task, {'codex_function_result': result})
                        self.assertEqual(turn.indexed.reads, INDEX_READ_LIMIT)
                        with self.assertRaisesRegex(RouterError, '^web_mcp_read_limit$'):
                            turn.begin(catalog[1]['schema_read_key'])
                        with self.assertRaisesRegex(RouterError, '^web_mcp_schema_not_read$'):
                            await turn.invoke(turn.key, 2, catalog[1]['name'], {'value': 'blocked'})
                finally:
                    turn.close()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_exact_unicode_context_and_catalog_preserve_all_native_declarations(self):
        from test_web_model_protocol import EXEC
        source = '中文😀 C:\\a_b\\z "quoted"\r\n\t\u0000  '
        tools = [{'type': 'namespace', 'name': 'functions', 'tools': [EXEC]},
            *[{**FUNCTION, 'name': 'inspect_' + str(i), 'description': source * 12}
                for i in range(337)]]
        original = make({'input': [{'role': 'user', 'content': source * 3000}], 'tools': tools},
            custom_tools={'exec': 'wrap', 'functions.exec': 'wrap'})
        turn = WebMcpTurn(original)
        turn.prepare_indexed()
        self.assertFalse(turn.observation()['request_read'])
        context, last = self.read_section(turn, turn.key)
        self.assertGreater(last['total'], 1)
        self.assertTrue(turn.observation()['request_read'])
        self.assertEqual(context['tool_count'], 338)
        self.assertNotIn('tools', context['request'])
        catalog, _ = self.read_section(turn, last['catalog_read_key'])
        self.assertEqual(len(catalog), 338)
        self.assertEqual(catalog[0]['source'], {'type': 'custom', 'namespace': 'functions', 'name': 'exec'})
        self.assertEqual(catalog[1]['source'], {'type': 'function', 'namespace': None, 'name': 'inspect_0'})
        # Two selected declarations remain exact; 336 others stay unread and
        # available. Catalog presence by itself never enables tool execution.
        schema, _ = self.read_section(turn, catalog[0]['schema_read_key'])
        self.assertEqual(schema['request_tool'], original.request()['tools'][0])
        self.assertEqual(schema['mcp_tool'], original.mcp_tools()[0])
        schema2, _ = self.read_section(turn, catalog[-1]['schema_read_key'])
        self.assertEqual(schema2['request_tool'], original.request()['tools'][-1])
        expected = original.request()
        declared = expected.pop('tools')
        self.assertEqual(context['request'], expected)
        self.assertEqual([x['name'] for x in catalog], [x['name'] for x in declared])
        self.assertEqual(turn.indexed.described, {catalog[0]['name'], catalog[-1]['name']})
        self.assertEqual(turn.calls, 0)
        turn.finish(message(['exact\r\nfinal']))
        final, _ = await turn.next_response()
        self.assertEqual(final['output'][0]['content'][0]['text'], 'exact\r\nfinal')
        turn.close()
        self.assertEqual(turn.indexed.pages, {})

    async def test_order_and_complete_schema_gate_native_calls_and_results(self):
        native = protocol([{'role': 'user', 'content': 'history中文\r\n' * 9000}],
            tools=[{**FUNCTION, 'description': 'schema😀\r\n' * 3000}])
        turn = WebMcpTurn(native)
        self.addCleanup(turn.close)
        turn.prepare_indexed()
        first = turn.begin(turn.key)
        self.assertFalse(turn.observation()['request_read'])
        last_context = next(key for key, (_, section, _, final) in turn.indexed.pages.items()
            if section == 'context' and final)
        for action, code in [
                (lambda: turn.begin(last_context), 'web_mcp_read_out_of_order'),
                (lambda: turn.begin(turn.indexed.catalog_key), 'web_mcp_context_not_read'),
                (lambda: turn.finish(message()), 'web_mcp_context_not_read'),
                (lambda: turn.begin(turn.key), 'web_mcp_begin_already_consumed')]:
            with self.assertRaisesRegex(RouterError, code): action()
        with self.assertRaisesRegex(RouterError, 'web_mcp_context_not_read'):
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
        key = first['next_read_key']
        while key:
            page = turn.begin(key)
            key = page['next_read_key']
        schema_key = next(key for key, (_, section, _, _) in turn.indexed.pages.items() if section == 'schema')
        with self.assertRaisesRegex(RouterError, 'web_mcp_catalog_not_read'):
            turn.begin(schema_key)
        catalog, _ = self.read_section(turn, page['catalog_read_key'])
        schema_first = turn.begin(catalog[0]['schema_read_key'])
        self.assertGreater(schema_first['total'], 1)
        schema_last = next(key for key, (_, section, _, final) in turn.indexed.pages.items()
            if section == 'schema' and final)
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_out_of_order'):
            turn.begin(schema_last)
        with self.assertRaisesRegex(RouterError, 'web_mcp_schema_not_read'):
            await turn.invoke(turn.key, 2, 'inspect', {'value': 'x'})
        key = schema_first['next_read_key']
        while key:
            page = turn.begin(key)
            key = page['next_read_key']
        task = asyncio.create_task(turn.invoke(turn.key, 3, 'inspect', {'value': 'exact 中文\r\n'}))
        response, _ = await turn.next_response()
        call = response['output'][0]
        self.assertEqual(json.loads(call['arguments']), {'value': 'exact 中文\r\n'})
        with self.assertRaisesRegex(RouterError, 'web_mcp_call_out_of_order'):
            turn.begin(schema_last)
        result = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'permission denied\r\n'}
        follow = protocol(native.source_input() + [call, result],
            tools=[{**FUNCTION, 'description': 'schema😀\r\n' * 3000}])
        turn.accept_result(follow)
        self.assertEqual(await task, {'codex_function_result': result})
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_key_unavailable'):
            turn.begin(schema_last)
        self.assertEqual((turn.calls, turn.results), (1, 1))

    async def test_read_observation_distinguishes_stages_without_retaining_content(self):
        turn = WebMcpTurn(protocol([{'role': 'user', 'content': 'private context\r\n' * 5000}],
            tools=[{**FUNCTION, 'description': 'private schema\r\n' * 5000}]))
        self.addCleanup(turn.close)
        self.assertNotIn('indexed_reads', turn.observation())
        turn.prepare_indexed()
        initial = turn.observation()['indexed_reads']
        self.assertEqual(set(initial), {'context_pages_read', 'context_pages_total',
            'catalog_pages_read', 'catalog_pages_total', 'schema_pages_read', 'schemas_complete'})
        self.assertTrue(all(type(value) is int for value in initial.values()))
        self.assertGreater(initial['context_pages_total'], 1)
        self.assertEqual(initial['context_pages_read'], 0)
        self.assertEqual(initial['catalog_pages_total'], 1)
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_rejected'):
            turn.begin(turn.indexed.catalog_key)
        self.assertEqual(turn.observation()['indexed_reads'], initial)
        _, last = self.read_section(turn, turn.key)
        context = turn.observation()['indexed_reads']
        self.assertEqual(context['context_pages_read'], context['context_pages_total'])
        self.assertEqual(context['catalog_pages_read'], 0)
        self.assertEqual(context['schema_pages_read'], 0)
        catalog, _ = self.read_section(turn, last['catalog_read_key'])
        first = turn.begin(catalog[0]['schema_read_key'])
        partial = turn.observation()['indexed_reads']
        self.assertEqual(partial['catalog_pages_read'], partial['catalog_pages_total'])
        self.assertEqual(partial['schema_pages_read'], 1)
        self.assertEqual(partial['schemas_complete'], 0)
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_key_unavailable'):
            turn.begin(catalog[0]['schema_read_key'])
        self.assertEqual(turn.observation()['indexed_reads'], partial)
        key = first['next_read_key']
        while key:
            page = turn.begin(key)
            key = page['next_read_key']
        complete = turn.observation()['indexed_reads']
        self.assertEqual(complete['schema_pages_read'], first['total'])
        self.assertEqual(complete['schemas_complete'], 1)
        self.assertEqual(sum(complete[key] for key in ('context_pages_read',
            'catalog_pages_read', 'schema_pages_read')), turn.indexed.reads)
        self.assertEqual(turn.observation()['calls_accepted'], 0)
        turn.close()
        self.assertEqual(turn.indexed.pages, {})
        self.assertEqual(turn.observation()['indexed_reads'], complete)
        complete['schema_pages_read'] = -1
        self.assertEqual(turn.observation()['indexed_reads']['schema_pages_read'], first['total'])

    async def test_turn_keys_lifetime_limits_and_text_only_do_not_fetch_tools(self):
        turn = WebMcpTurn(protocol())
        turn.prepare_indexed()
        foreign = WebMcpTurn(protocol())
        foreign.prepare_indexed()
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_rejected'):
            turn.begin(foreign.key)
        with self.assertRaisesRegex(RouterError, 'web_mcp_index_already_prepared'):
            turn.prepare_indexed()
        _, last = self.read_section(turn, turn.key)
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_key_unavailable'):
            turn.begin(foreign.indexed.catalog_key)
        self.assertFalse(turn.indexed.catalog_complete)
        self.assertEqual(turn.indexed.described, set())
        turn.indexed.reads = INDEX_READ_LIMIT
        with self.assertRaisesRegex(RouterError, 'web_mcp_read_limit'):
            turn.begin(last['catalog_read_key'])
        turn.close()
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_closed'):
            turn.begin(last['catalog_read_key'])
        foreign.deadline = 0
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_closed'):
            foreign.begin(foreign.key)
        foreign.close()
        empty = WebMcpTurn(make({'tools': []}))
        empty.prepare_indexed()
        context, last = self.read_section(empty, empty.key)
        self.assertEqual(context['tool_count'], 0)
        self.assertIsNone(last['catalog_read_key'])
        empty.finish(message(['no tool needed']))
        response, _ = await empty.next_response()
        self.assertEqual(response['output'][0]['content'][0]['text'], 'no tool needed')
        self.assertEqual(empty.indexed.reads, 1)
        empty.close()

    async def test_unavailable_read_diagnostics_distinguish_consumed_unknown_and_type(self):
        for wire in ('mcp_indexed_request_v1', 'mcp_catalog_pages_v2', 'mcp_context_records_v3'):
            turn = WebMcpTurn(protocol())
            self.addCleanup(turn.close)
            turn.prepare_indexed(wire_protocol=wire, begin_result_mode='structured_begin_v1')
            context_key = turn.indexed.first_key
            key = turn.key
            while key:
                last = turn.begin(key)
                key = last['next_read_key']
            catalog_key = last['catalog_read_key']
            if wire == 'mcp_indexed_request_v1':
                catalog, _ = self.read_section(turn, catalog_key)
            else:
                catalog = turn.begin(catalog_key)['entries']
            schema_key = catalog[0]['schema_read_key']
            self.read_section(turn, schema_key)
            before = turn.indexed.read_observation()
            for key in (None, {'private': 'not a key'}, 'unknown-private-read-handle',
                    context_key, catalog_key, schema_key):
                with self.assertRaisesRegex(RouterError, '^web_mcp_read_key_unavailable$'):
                    turn.begin(key)
            observed = turn.observation()
            self.assertEqual(observed['indexed_reads'], before)
            self.assertEqual(observed['indexed_read_rejections'], {'counts': {
                'invalid_type': 2, 'unknown': 1, 'consumed_context': 1,
                'consumed_catalog': 1, 'consumed_schema': 1}, 'counts_capped': False})
            for private in (context_key, catalog_key, schema_key, 'unknown-private-read-handle',
                    'not a key'):
                self.assertNotIn(private, json.dumps(observed))
            self.assertEqual(len(turn.indexed.consumed_pages), turn.indexed.reads)
            self.assertLessEqual(len(turn.indexed.consumed_pages), INDEX_READ_LIMIT)
            turn.close()
            self.assertEqual(turn.indexed.consumed_pages, {})
            self.assertEqual(turn.observation(), observed)

    async def test_read_rejection_counts_are_bounded_and_do_not_consume_valid_catalog(self):
        turn = WebMcpTurn(protocol())
        self.addCleanup(turn.close)
        turn.prepare_indexed()
        _, last = self.read_section(turn, turn.key)
        before = turn.indexed.reads
        for _ in range(INDEX_READ_LIMIT + 2):
            with self.assertRaisesRegex(RouterError, '^web_mcp_read_key_unavailable$'):
                turn.begin('unknown')
        self.assertEqual(turn.indexed.reads, before)
        self.assertEqual(turn.observation()['indexed_read_rejections'], {
            'counts': {'unknown': INDEX_READ_LIMIT}, 'counts_capped': True})
        page = turn.begin(last['catalog_read_key'])
        self.assertEqual(page['section'], 'catalog')
        self.assertEqual(turn.indexed.reads, before + 1)
        self.assertEqual(turn.calls, 0)


class WebResponsesBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_citation_failure_retains_bounded_shape_without_sources_or_replay(self):
        visits = []
        async def browser(turn):
            visits.append(turn)
            turn.begin(turn.key)
            if len(visits) > 1:
                return message(['new answer'], public_references=[])
            return message(['private answer'],
                metadata={'operator_web_renderer': 'modern_content_references_v1'},
                public_references=[{'type': 'grouped_webpages',
                    'matched_text': '\ue200cite\ue202source1\ue201',
                    'start_idx': 0, 'end_idx': 16, 'items': []}])
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            citation_mode='markdown_links_v1')
        self.addAsyncCleanup(bridge.stop)
        payload = self.payload()
        with self.assertRaisesRegex(RouterError, '^web_public_citation_sources_invalid$'):
            await bridge.exchange(payload)
        result = bridge.diagnostics()['last_turn']
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['calls_released'], 0)
        self.assertFalse(result['public_final_returned'])
        self.assertEqual(result['citation_validation'], {
            'renderer': 'modern', 'reference_count': 1, 'references': {
                'grouped_webpages': {'count': 1, 'sources_max': 0, 'source_shapes': {'empty_array': 1}}}})
        self.assertNotIn('private', json.dumps(result))
        result['citation_validation']['references']['grouped_webpages']['sources_max'] = 42
        self.assertEqual(bridge.diagnostics()['last_turn']['citation_validation']
            ['references']['grouped_webpages']['sources_max'], 0)
        with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
            await bridge.exchange(payload)
        self.assertEqual(len(visits), 1)
        fresh = self.payload()
        fresh['client_metadata']['turn_id'] += '-new'
        await bridge.exchange(fresh)
        self.assertEqual(len(visits), 2)
        self.assertNotIn('citation_validation', bridge.diagnostics()['last_turn'])

    def payload(self, turn='turn-1', thread='thread-1'):
        from test_web_model_protocol import SLUG
        return {'model': SLUG, 'input': [{'role': 'user', 'content': 'fixture'}],
            'tools': [FUNCTION], 'reasoning': {'effort': 'high'}, 'stream': True,
            'client_metadata': {'thread_id': thread, 'turn_id': turn}}

    async def test_native_call_result_and_final_then_new_turn_without_replay(self):
        received = []
        async def browser(turn):
            turn.begin(turn.key)
            received.append(await turn.invoke(turn.key, 1, 'inspect', {'value': '中文'}))
            return message(['exact\r\nfinal'])
        endpoint = WebMcpEndpoint()
        bridge = WebResponsesBridge(protocol().route, endpoint, browser)
        try:
            for generation in ('turn-1', 'turn-2'):
                payload = self.payload(turn=generation)
                response, events = await bridge.exchange(payload)
                self.assertEqual(events[-1]['type'], 'response.completed')
                call = response['output'][0]
                result = {'type':'function_call_output', 'call_id':call['call_id'],
                    'output':'actual\r\nresult'}
                continued = deepcopy(payload)
                continued['input'] += [call, result]
                final, _ = await bridge.exchange(continued)
                self.assertEqual(received[-1], {'codex_function_result':result})
                self.assertEqual(final['output'][0]['content'][0]['text'], 'exact\r\nfinal')
                self.assertIsNone(endpoint.turn)
                snapshot = bridge.diagnostics()
                self.assertIsNone(snapshot['active_turn'])
                self.assertEqual(snapshot['last_turn']['sequence'], len(received))
                self.assertEqual(snapshot['last_turn']['results_received'], 1)
                with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
                    await bridge.exchange(payload)
            self.assertEqual(len(received), 2)
        finally:
            await bridge.stop()

    async def test_progress_keeps_denied_result_separate_from_transport_completion(self):
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'private argument'})
            return message(['private final says blocked_by_openai_safety_check'])
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        self.addAsyncCleanup(bridge.stop)
        payload = self.payload()
        response, _ = await bridge.exchange(payload)
        active = bridge.diagnostics()
        self.assertEqual(active, {'scope': 'transport_only', 'last_turn': None, 'active_turn': {
            'sequence': 1, 'request_read': True, 'calls_accepted': 1, 'calls_released': 1,
            'results_received': 0, 'pending_call': 'released_without_result', 'public_final_returned': False}})
        self.assertEqual(bridge.diagnostics(), active)  # Reads do not consume or progress anything.
        call = response['output'][0]
        payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'],
            'output': '{"isError":true,"message":"private native permission denial"}'}]
        await bridge.exchange(payload)
        terminal = bridge.diagnostics()
        self.assertEqual(terminal, {'scope': 'transport_only', 'active_turn': None, 'last_turn': {
            'sequence': 1, 'outcome': 'public_final_returned', 'request_read': True,
            'calls_accepted': 1, 'calls_released': 1, 'results_received': 1,
            'pending_call': None, 'public_final_returned': True}})
        for secret in ('private', 'blocked_by_openai_safety_check', 'inspect', call['call_id']):
            self.assertNotIn(secret, json.dumps(terminal))
        terminal['last_turn']['calls_released'] = 99
        self.assertEqual(bridge.diagnostics()['last_turn']['calls_released'], 1)

    async def test_failed_continuation_retains_outstanding_call_and_never_accepts_replay(self):
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            return message()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        self.addAsyncCleanup(bridge.stop)
        payload = self.payload()
        response, _ = await bridge.exchange(payload)
        payload['input'] += [response['output'][0], {'type': 'function_call_output',
            'call_id': 'wrong-private-id', 'output': 'cannot be accepted'}]
        with self.assertRaises(RouterError):
            await bridge.exchange(payload)
        observed = bridge.diagnostics()
        self.assertEqual(observed['last_turn']['outcome'], 'failed')
        self.assertEqual(observed['last_turn']['pending_call'], 'released_without_result')
        self.assertEqual(observed['last_turn']['results_received'], 0)
        self.assertFalse(observed['last_turn']['public_final_returned'])
        with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
            await bridge.exchange(self.payload())
        await bridge.stop()
        self.assertEqual(bridge.diagnostics(), observed)

    async def test_stop_preserves_released_call_with_unknown_result(self):
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            return message()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        await bridge.exchange(self.payload())
        await bridge.stop()
        observed = bridge.diagnostics()['last_turn']
        self.assertEqual(observed['outcome'], 'stopped')
        self.assertEqual(observed['calls_released'], 1)
        self.assertEqual(observed['results_received'], 0)
        self.assertEqual(observed['pending_call'], 'released_without_result')
        self.assertFalse(observed['public_final_returned'])

    async def test_new_task_or_turn_cannot_infer_cancellation_of_a_pending_call(self):
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            return message()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        try:
            payload = self.payload()
            response, _ = await bridge.exchange(payload)
            active = bridge.turn
            # A completed tool-call HTTP response does not report whether the
            # native user subsequently stopped while its result was pending.
            # A different new turn is not evidence of cancellation either.
            for other in [self.payload(thread='other-thread'), self.payload(turn='next-turn')]:
                with self.assertRaisesRegex(RouterError, 'web_bridge_browser_busy'):
                    await bridge.exchange(other)
                self.assertIs(bridge.turn, active)
                self.assertFalse(active.closed)
                self.assertFalse(active.client_cancelled)
            call = response['output'][0]
            payload['input'] += [call, {'type':'function_call_output',
                'call_id':call['call_id'],'output':'actual'}]
            await bridge.exchange(payload)
        finally:
            await bridge.stop()

    async def test_cancellation_stops_owned_browser_and_never_restarts_consumed_turn(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        async def browser(turn):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        request = asyncio.create_task(bridge.exchange(self.payload()))
        try:
            await asyncio.wait_for(started.wait(), 1)
            with self.assertRaisesRegex(RouterError, 'web_bridge_response_busy'):
                await bridge.exchange(self.payload())
            request.cancel()
            with self.assertRaises(asyncio.CancelledError): await request
            self.assertTrue(stopped.is_set())
            self.assertIsNone(bridge.endpoint.turn)
            self.assertEqual(bridge.diagnostics()['last_turn']['outcome'], 'cancelled')
            self.assertEqual(bridge.diagnostics()['last_turn']['calls_released'], 0)
            with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
                await bridge.exchange(self.payload())
        finally:
            await bridge.stop()

    async def test_native_interruption_closes_released_call_before_reusing_browser(self):
        observed, stopped = [], asyncio.Event()
        async def observer(identity):
            observed.append(identity)
            return True
        async def browser(turn):
            turn.begin(turn.key)
            if len(bridge.admitted) > 1:
                return message(['new independent answer'])
            try:
                await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            finally:
                self.assertTrue(turn.closed)
                self.assertTrue(turn.client_cancelled)
                stopped.set()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .01
        self.addAsyncCleanup(bridge.stop)
        await bridge.exchange(self.payload())
        await asyncio.wait_for(stopped.wait(), 1)
        await asyncio.sleep(.02)
        self.assertEqual(observed, [('thread-1', 'turn-1')])
        self.assertIsNone(bridge.turn)
        self.assertEqual(bridge.diagnostics()['last_turn']['outcome'], 'cancelled')
        self.assertEqual(bridge.diagnostics()['last_turn']['pending_call'], 'released_without_result')
        with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
            await bridge.exchange(self.payload())
        result, _ = await bridge.exchange(self.payload(turn='fresh'))
        self.assertEqual(result['output'][0]['content'][0]['text'], 'new independent answer')
        self.assertEqual(bridge.diagnostics()['native_interruption'],
            {'sequence': 2, 'checks': 0, 'state': 'idle'})

    async def test_native_metadata_unknown_does_not_retry_or_cancel_pending_call(self):
        for value in (None, 'true'):
            observations = []
            async def observer(identity):
                observations.append(identity)
                return value
            async def browser(turn):
                turn.begin(turn.key)
                await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
                native_interruption_observer=observer)
            bridge.native_poll_interval = .001
            try:
                await bridge.exchange(self.payload())
                await asyncio.wait_for(bridge.native_watch, 1)
                await asyncio.sleep(.01)
                self.assertEqual(len(observations), 1)
                self.assertFalse(bridge.turn.closed)
                self.assertFalse(bridge.turn.client_cancelled)
                self.assertEqual(bridge.native_observation['state'], 'unavailable')
            finally:
                await bridge.stop()

    async def test_native_observation_cannot_cancel_a_continuation_that_arrived_during_read(self):
        started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        observed, continued = asyncio.Event(), asyncio.Event()
        async def observer(_):
            started.set()
            await release.wait()
            observed.set()
            return True
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            continued.set()
            await finished.wait()
            return message()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .001
        self.addAsyncCleanup(bridge.stop)
        payload = self.payload()
        response, _ = await bridge.exchange(payload)
        await asyncio.wait_for(started.wait(), 1)
        call = response['output'][0]
        payload['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'actual'}]
        continuation = asyncio.create_task(bridge.exchange(payload))
        await asyncio.wait_for(continued.wait(), 1)
        release.set()
        await asyncio.wait_for(observed.wait(), 1)
        self.assertFalse(bridge.turn.closed)
        self.assertFalse(bridge.turn.client_cancelled)
        finished.set()
        await asyncio.wait_for(continuation, 1)

    async def test_native_observation_refreshes_after_same_turn_moves_to_next_call(self):
        observing, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        checks = []
        async def observer(identity):
            checks.append(identity)
            if len(checks) == 1:
                observing.set()
                await release.wait()
            return True
        async def browser(turn):
            turn.begin(turn.key)
            try:
                await turn.invoke(turn.key, 1, 'inspect', {'value': 'first'})
                await turn.invoke(turn.key, 2, 'inspect', {'value': 'second'})
                return message()
            finally:
                stopped.set()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .001
        self.addAsyncCleanup(bridge.stop)
        payload = self.payload()
        response, _ = await bridge.exchange(payload)
        await asyncio.wait_for(observing.wait(), 1)
        call = response['output'][0]
        payload['input'] += [call, {'type': 'function_call_output',
            'call_id': call['call_id'], 'output': 'actual'}]
        await bridge.exchange(payload)
        release.set()
        await asyncio.wait_for(stopped.wait(), 1)
        self.assertEqual(checks, [('thread-1', 'turn-1')] * 2)
        self.assertEqual(bridge.last_turn['outcome'], 'cancelled')
        self.assertEqual(bridge.last_turn['calls_released'], 2)
        self.assertEqual(bridge.last_turn['results_received'], 1)
        self.assertEqual(bridge.last_turn['pending_call'], 'released_without_result')

    async def test_service_stop_waits_for_confirmed_native_cancellation_cleanup(self):
        cleaning, release = asyncio.Event(), asyncio.Event()
        async def observer(_): return True
        async def browser(turn):
            turn.begin(turn.key)
            try:
                await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})
            finally:
                cleaning.set()
                await release.wait()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .001
        await bridge.exchange(self.payload())
        await asyncio.wait_for(cleaning.wait(), 1)
        stop = asyncio.create_task(bridge.stop())
        try:
            await asyncio.sleep(.01)
            self.assertFalse(stop.done())
            release.set()
            await asyncio.wait_for(stop, 1)
        finally:
            release.set()
            await asyncio.gather(stop, return_exceptions=True)

    async def test_disconnect_during_failed_continuation_waits_for_owned_cleanup(self):
        observing, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        browser_stopped, observer_stopped = asyncio.Event(), asyncio.Event()
        invocations = []
        async def observer(_):
            observing.set()
            try:
                await asyncio.Future()
            finally:
                cleaning.set()
                await release.wait()
                observer_stopped.set()
        async def browser(turn):
            turn.begin(turn.key)
            if len(bridge.admitted) > 1:
                return message(['fresh answer'])
            # Like the real browser process, its wait is independent of the
            # endpoint handler waiting for the native tool's paired result.
            invocations.append(asyncio.create_task(
                turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})))
            try:
                await asyncio.Future()
            finally:
                browser_stopped.set()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .001
        self.addAsyncCleanup(bridge.stop)
        await bridge.exchange(self.payload())
        await asyncio.wait_for(observing.wait(), 1)
        invalid = self.payload()
        invalid['model'] = 'unregistered-model'
        continuation = asyncio.create_task(bridge.exchange(invalid))
        try:
            await asyncio.wait_for(cleaning.wait(), 1)
            continuation.cancel()
            await asyncio.sleep(.01)
            continuation.cancel()  # A second disconnect must not abandon it.
            await asyncio.sleep(.01)
            self.assertFalse(continuation.done())
            self.assertTrue(bridge.exchanging)
            self.assertFalse(observer_stopped.is_set())
            with self.assertRaisesRegex(RouterError, 'web_bridge_response_busy'):
                await bridge.exchange(self.payload(turn='fresh'))
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(continuation, 1)
            self.assertTrue(observer_stopped.is_set())
            self.assertTrue(browser_stopped.is_set())
            self.assertFalse(bridge.exchanging)
            self.assertEqual(bridge.last_turn['outcome'], 'failed')
            with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
                await bridge.exchange(self.payload())
            result, _ = await bridge.exchange(self.payload(turn='fresh'))
            self.assertEqual(result['output'][0]['content'][0]['text'], 'fresh answer')
        finally:
            release.set()
            await asyncio.gather(continuation, *invocations, return_exceptions=True)

    async def test_service_stop_joins_existing_failed_continuation_cleanup(self):
        observing, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        browser_stopped = asyncio.Event()
        invocations = []
        async def observer(_):
            observing.set()
            try:
                await asyncio.Future()
            finally:
                cleaning.set()
                await release.wait()
        async def browser(turn):
            turn.begin(turn.key)
            invocations.append(asyncio.create_task(
                turn.invoke(turn.key, 1, 'inspect', {'value': 'x'})))
            try:
                await asyncio.Future()
            finally:
                browser_stopped.set()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser,
            native_interruption_observer=observer)
        bridge.native_poll_interval = .001
        await bridge.exchange(self.payload())
        await asyncio.wait_for(observing.wait(), 1)
        invalid = self.payload()
        invalid['model'] = 'unregistered-model'
        continuation = asyncio.create_task(bridge.exchange(invalid))
        await asyncio.wait_for(cleaning.wait(), 1)
        stop = asyncio.create_task(bridge.stop())
        try:
            await asyncio.sleep(.01)
            self.assertFalse(stop.done())
            release.set()
            await asyncio.wait_for(stop, 1)
            self.assertTrue(browser_stopped.is_set())
            with self.assertRaises(RouterError):
                await continuation
            self.assertEqual(bridge.last_turn['outcome'], 'failed')
        finally:
            release.set()
            await asyncio.gather(continuation, stop, *invocations, return_exceptions=True)

    async def test_browser_error_is_redacted_and_a_new_turn_can_start(self):
        count = 0
        async def browser(turn):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError('private page detail must never be returned')
            turn.begin(turn.key)
            return message()
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        try:
            with self.assertRaisesRegex(RouterError, '^web_browser_driver_failed_no_retry$'):
                await bridge.exchange(self.payload())
            await bridge.exchange(self.payload(turn='turn-2'))
            self.assertEqual(count, 2)
        finally:
            await bridge.stop()

    async def test_local_citation_failure_is_specific_terminal_and_never_replayed(self):
        calls = 0
        async def browser(turn):
            nonlocal calls
            calls += 1
            turn.begin(turn.key)
            return message(['\ue200url\ue202Missing\ue202turn0search1\ue201'], public_references=[])
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser, citation_mode='markdown_links_v1')
        try:
            with self.assertRaisesRegex(RouterError, '^web_public_citation_unmapped$'):
                await bridge.exchange(self.payload())
            self.assertEqual(bridge.diagnostics()['last_turn']['calls_released'], 0)
            with self.assertRaisesRegex(RouterError, 'web_bridge_turn_consumed_no_retry'):
                await bridge.exchange(self.payload())
            self.assertEqual(calls, 1)
        finally:
            await bridge.stop()

    async def test_browser_cannot_claim_local_citation_validation(self):
        async def browser(turn):
            raise RouterError('web_public_citation_unmapped')
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser, citation_mode='markdown_links_v1')
        try:
            with self.assertRaisesRegex(RouterError, '^web_browser_driver_failed_no_retry$'):
                await bridge.exchange(self.payload())
        finally:
            await bridge.stop()


class WebMcpTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_index_page_budget_matches_actual_representation_without_losing_history(self):
        source='中文😀 "quoted" \\folder\\file\r\n\t' * 6500
        payload=[{'role':'user','content':source}]
        counts={}
        for mode,wire in [('text_v1','mcp_indexed_request_v1'),
                ('structured_begin_v1','mcp_indexed_request_v1'),
                ('structured_begin_v1','mcp_catalog_pages_v2')]:
            with self.subTest(mode=mode,wire=wire):
                endpoint=WebMcpEndpoint(begin_result_mode=mode,indexed_protocol=wire)
                url=await endpoint.start()
                turn=endpoint.turn=WebMcpTurn(protocol(payload))
                turn.prepare_indexed(wire_protocol=wire,begin_result_mode=mode)
                expected=turn.preview_begin()['request'];expected.pop('tools')
                try:
                    async with ClientSession() as client:
                        async with client.post(url,json={'jsonrpc':'2.0','id':0,'method':'initialize',
                                'params':{'protocolVersion':'2025-11-25'}}) as response:
                            client.headers['Mcp-Session-Id']=response.headers['Mcp-Session-Id']
                        # A changed envelope cannot consume the larger packed page.
                        endpoint.begin_result_mode='text_v1' if mode=='structured_begin_v1' else 'structured_begin_v1'
                        async with client.post(url,json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                                'params':{'name':'operator_begin','arguments':{'turn_key':turn.key}}}) as response:
                            self.assertEqual((await response.json())['error']['message'],'web_mcp_page_representation_changed')
                        self.assertFalse(turn.begun);self.assertEqual(turn.indexed.reads,0)
                        endpoint.begin_result_mode=mode
                        key=turn.key;fragments=[]
                        while key:
                            rpc=('😀'*128 if len(fragments)==0 else int('9'*4000))
                            # Each large id is unique while retaining its worst-case size.
                            if len(fragments)>0:rpc-=len(fragments)
                            async with client.post(url,json={'jsonrpc':'2.0','id':rpc,'method':'tools/call',
                                    'params':{'name':'operator_begin','arguments':{'turn_key':key}}}) as response:
                                self.assertEqual(response.status,200)
                                raw=await response.read();self.assertLessEqual(len(raw),INDEX_REPLY_BYTES)
                                decoded=json.loads(raw)
                                self.assertNotIn('error',decoded)
                                result=decoded['result']
                            page=result['structuredContent'] if mode=='structured_begin_v1' else json.loads(result['content'][0]['text'])
                            self.assertEqual(page['index'],len(fragments))
                            fragments.append(page['json_fragment']);key=page['next_read_key']
                            if key:
                                with self.assertRaisesRegex(RouterError,'web_mcp_context_not_read'):
                                    await turn.invoke(turn.key,50,'inspect',{'value':'must not run'})
                                self.assertFalse(turn.indexed.context_complete)
                        self.assertTrue(turn.indexed.context_complete)
                        self.assertEqual(json.loads(''.join(fragments)),{'request':expected,'tools_present':True,'tool_count':1})
                        self.assertEqual(turn.protocol.request()['input'],payload)
                        self.assertEqual((turn.calls,turn.results),(0,0))
                        counts[(mode,wire)]=len(fragments)
                finally:
                    turn.close();await endpoint.stop()
        self.assertLess(counts[('structured_begin_v1','mcp_indexed_request_v1')],counts[('text_v1','mcp_indexed_request_v1')])
        self.assertEqual(counts[('structured_begin_v1','mcp_indexed_request_v1')],counts[('structured_begin_v1','mcp_catalog_pages_v2')])

    async def test_paged_catalog_http_shape_and_schema_gate_with_large_rpc_id(self):
        endpoint = WebMcpEndpoint(begin_result_mode='structured_begin_v1', indexed_protocol='mcp_catalog_pages_v2')
        url = await endpoint.start()
        self.addAsyncCleanup(endpoint.stop)
        from test_web_model_protocol import EXEC
        native = make({'tools': [FUNCTION,
            {'type': 'tool_search', 'execution': 'client', 'parameters': {'type': 'object'}},
            {'type': 'namespace', 'name': 'functions', 'tools': [EXEC]},
            *[{**FUNCTION, 'name': 'inspect_' + str(i)} for i in range(335)]]},
            custom_tools={'exec': 'wrap', 'functions.exec': 'wrap'})
        turn = endpoint.turn = WebMcpTurn(native)
        turn.prepare_indexed(wire_protocol=endpoint.indexed_protocol,
            begin_result_mode=endpoint.begin_result_mode)
        async with ClientSession() as client:
            async def rpc(number, method, params):
                async with client.post(url, json={'jsonrpc': '2.0', 'id': number,
                        'method': method, 'params': params}) as response:
                    if response.headers.get('Mcp-Session-Id'):
                        client.headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
                    raw = await response.read()
                    if method == 'tools/call': self.assertLessEqual(len(raw), INDEX_REPLY_BYTES)
                    self.assertEqual(response.status, 200)
                    return json.loads(raw)
            await rpc(0, 'initialize', {'protocolVersion': '2025-11-25'})
            definitions = (await rpc(1, 'tools/list', {}))['result']['tools']
            first = (await rpc(2, 'tools/call', {'name': 'operator_begin',
                'arguments': {'turn_key': turn.key}}))['result']['structuredContent']
            result = (await rpc(int('9' * 4000), 'tools/call', {'name': 'operator_begin',
                'arguments': {'turn_key': first['catalog_read_key']}}))['result']
            page = result['structuredContent']; shape = definitions[0]['outputSchema']['oneOf'][3]
            self.assertEqual(result['content'], [])
            self.assertTrue(set(shape['required']) <= set(page) <= set(shape['properties']))
            self.assertEqual(page['protocol'], shape['properties']['protocol']['const'])
            self.assertEqual(page['section'], 'catalog')
            self.assertGreater(page['total'], 1)
            source_shape = shape['properties']['entries']['items']['properties']['source']
            self.assertEqual([entry['source']['type'] for entry in page['entries'][:3]],
                ['function', 'tool_search', 'custom'])
            for entry in page['entries']:
                self.assertEqual(set(entry['source']), set(source_shape['required']))
                self.assertIn(entry['source']['type'], source_shape['properties']['type']['enum'])
            selected = page['entries'][0]
            unread = next(k for k, (_, section, name, _) in turn.indexed.pages.items()
                if section == 'schema' and name == native.mcp_tools()[-1]['name'])
            rejected = await rpc(4, 'tools/call', {'name': 'operator_begin', 'arguments': {'turn_key': unread}})
            self.assertEqual(rejected['error']['message'], 'web_mcp_catalog_entry_not_read')
            schema = (await rpc(5, 'tools/call', {'name': 'operator_begin',
                'arguments': {'turn_key': selected['schema_read_key']}}))['result']['structuredContent']
            self.assertEqual(json.loads(schema['json_fragment'])['request_tool'], native.request()['tools'][0])
            self.assertFalse(turn.indexed.catalog_complete)
            self.assertEqual(turn.calls, 0)

    async def test_structured_begin_preserves_complete_pages_and_legacy_endpoint_bytes(self):
        source='中文 😀 "quotes" C:\\fixture\\path\r\n'*3200
        for mode in ('text_v1','structured_begin_v1'):
            for indexed in (False,True):
                with self.subTest(mode=mode,indexed=indexed):
                    endpoint=WebMcpEndpoint(begin_result_mode=mode)
                    url=await endpoint.start()
                    turn=endpoint.turn=WebMcpTurn(protocol([{'role':'user','content':source}]))
                    original=turn.preview_begin()
                    if indexed: turn.prepare_indexed(begin_result_mode=mode)
                    try:
                        async with ClientSession() as client:
                            async with client.post(url,json={'jsonrpc':'2.0','id':0,'method':'initialize',
                                    'params':{'protocolVersion':'2025-11-25'}}) as r:
                                client.headers['Mcp-Session-Id']=r.headers['Mcp-Session-Id']
                            async with client.post(url,json={'jsonrpc':'2.0','id':1,'method':'tools/list'}) as r:
                                tools=(await r.json())['result']['tools']
                            self.assertEqual('outputSchema' in tools[0],mode=='structured_begin_v1')
                            self.assertNotIn('outputSchema',tools[1])
                            key=turn.key;fragments=[];count=0
                            while key:
                                rpc=int('9'*4000) if count==0 else count+1
                                async with client.post(url,json={'jsonrpc':'2.0','id':rpc,'method':'tools/call',
                                        'params':{'name':'operator_begin','arguments':{'turn_key':key}}}) as r:
                                    self.assertEqual(r.status,200)
                                    raw=await r.read();result=json.loads(raw)['result']
                                self.assertIs(result['isError'],False)
                                if mode=='structured_begin_v1':
                                    self.assertEqual(set(result),{'content','structuredContent','isError'})
                                    self.assertEqual(result['content'],[])
                                    page=result['structuredContent']
                                    shape=tools[0]['outputSchema']['oneOf'][0 if indexed else 1]
                                    self.assertTrue(set(shape['required'])<=set(page)<=set(shape['properties']))
                                else:
                                    self.assertEqual(set(result),{'content','isError'})
                                    page=json.loads(result['content'][0]['text'])
                                self.assertNotIn('_meta',result)
                                if indexed:
                                    self.assertLessEqual(len(raw),INDEX_REPLY_BYTES)
                                    self.assertEqual(page['index'],count)
                                    fragments.append(page['json_fragment']);key=page['next_read_key']
                                else:
                                    self.assertEqual(page,original);key=None
                                count+=1
                            if indexed:
                                expected={'request':{k:v for k,v in original['request'].items() if k!='tools'},
                                    'tools_present':True,'tool_count':len(original['request']['tools'])}
                                self.assertEqual(json.loads(''.join(fragments)),expected)
                                self.assertTrue(turn.indexed.context_complete)
                            async with client.post(url,json={'jsonrpc':'2.0','id':999,'method':'tools/call',
                                    'params':{'name':'operator_begin','arguments':{'turn_key':turn.key}}}) as r:
                                self.assertEqual((await r.json())['error']['message'],'web_mcp_begin_already_consumed')
                            self.assertEqual(turn.calls,0)
                            self.assertEqual(turn.protocol.request()['input'][0]['content'],source)
                    finally:
                        turn.close();await endpoint.stop()

    async def test_history_types_and_original_source_cannot_drift_between_calls(self):
        for change in ('user_boolean', 'result_boolean', 'source_null', 'array_order'):
            with self.subTest(change=change):
                initial = [{'role': 'user', 'content': '原文\r\n',
                    'metadata': {'allowed': True, 'order': ['first', 'second']}}]
                turn = WebMcpTurn(protocol(initial))
                turn.begin(turn.key)
                first = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'first'}))
                first_response, _ = await turn.next_response()
                first_call = first_response['output'][0]
                first_result = {'type': 'function_call_output', 'call_id': first_call['call_id'],
                    'output': [{'type': 'input_text', 'text': '拒绝\r\n',
                        'metadata': {'allowed': False}}]}
                history = initial + [first_call, first_result]
                turn.accept_result(protocol(history))
                self.assertEqual(await first, {'codex_function_result': first_result})
                second = asyncio.create_task(turn.invoke(turn.key, 2, 'inspect', {'value': 'second'}))
                try:
                    second_response, _ = await turn.next_response()
                    second_call = second_response['output'][0]
                    continued = deepcopy(history + [second_call, {
                        'type': 'function_call_output', 'call_id': second_call['call_id'], 'output': 'exact'}])
                    if change == 'user_boolean':
                        continued[0]['metadata']['allowed'] = 1
                    elif change == 'result_boolean':
                        continued[2]['output'][0]['metadata']['allowed'] = 0
                    elif change == 'source_null':
                        # The adapter removes namespace=None in prepared history;
                        # the complete original source still changed.
                        continued[1]['namespace'] = None
                    else:
                        continued[0]['metadata']['order'].reverse()
                    with self.assertRaisesRegex(RouterError, '^web_mcp_history_changed$'):
                        turn.accept_result(protocol(continued))
                    self.assertTrue(turn.closed)
                    self.assertEqual((turn.calls, turn.released_calls, turn.results), (2, 2, 1))
                    with self.assertRaises(asyncio.CancelledError):
                        await second
                    with self.assertRaisesRegex(RouterError, '^web_mcp_turn_closed$'):
                        await turn.invoke(turn.key, 3, 'inspect', {'value': 'must not be released'})
                    self.assertEqual(turn.calls, 2)
                finally:
                    turn.close()
                    await asyncio.gather(second, return_exceptions=True)

    async def test_history_object_order_changes_preserve_exact_result_parts(self):
        initial = [{'role': 'user', 'content': '原文\r\n',
            'metadata': {'first': True, 'second': 1, 'third': [False, 0]}}]
        turn = WebMcpTurn(protocol(initial))
        turn.begin(turn.key)
        invoke = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': '中文'}))
        try:
            response, _ = await turn.next_response()
            call = response['output'][0]
            result = {'type': 'function_call_output', 'call_id': call['call_id'],
                'output': [{'type': 'input_text', 'text': ' 真实\r\n😀 '},
                    {'type': 'input_text', 'text': ''}]}
            reordered = [{'metadata': {'third': [False, 0], 'second': 1, 'first': True},
                'content': '原文\r\n', 'role': 'user'}]
            turn.accept_result(protocol(reordered + [call, result]))
            self.assertEqual(await invoke, {'codex_function_result': result})
            self.assertEqual(turn.results, 1)
        finally:
            turn.close()
            await asyncio.gather(invoke, return_exceptions=True)

    async def test_accepted_but_unreleased_call_remains_distinct_after_closure(self):
        turn = WebMcpTurn(protocol())
        turn.begin(turn.key)
        invoke = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}))
        await asyncio.sleep(0)
        turn.close()
        with self.assertRaises(asyncio.CancelledError):
            await invoke
        self.assertEqual(turn.observation(), {'request_read': True, 'calls_accepted': 1,
            'calls_released': 0, 'results_received': 0, 'pending_call': 'not_released',
            'public_final_returned': False})

    async def test_endpoint_records_rejections_before_native_execution_without_secrets(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        turn = endpoint.turn = WebMcpTurn(protocol())
        try:
            async with ClientSession() as client:
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                        'params': {'protocolVersion': '2025-11-25'}}) as r:
                    session = r.headers['Mcp-Session-Id']
                async def invoke(rpc, name, args):
                    async with client.post(url, headers={'Mcp-Session-Id': session},
                            json={'jsonrpc': '2.0', 'id': rpc, 'method': 'tools/call',
                                  'params': {'name': name, 'arguments': args}}) as r:
                        return await r.json()
                result = await invoke(1, 'operator_begin', {'turn_key': turn.key})
                self.assertIn('result', result)
                result = await invoke(2, 'operator_begin', {'turn_key': turn.key})
                self.assertEqual(result['error']['message'], 'web_mcp_begin_already_consumed')
                result = await invoke(3, 'operator_call', {'turn_key': 'private_bad_key',
                    'name': 'inspect', 'arguments': {'value': 'private_arguments'}})
                self.assertEqual(result['error']['message'], 'web_mcp_turn_rejected')
                result = await invoke(3, 'operator_call', {'turn_key': turn.key,
                    'name': 'inspect', 'arguments': {'value': 'private_arguments'}})
                self.assertEqual(result['error']['message'], 'web_mcp_duplicate_no_retry')
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 4,
                        'method': 'tools/call', 'params': {'name': 'operator_call', 'arguments': {}}}) as r:
                    self.assertEqual(r.status, 400)
                task = asyncio.create_task(invoke(5, 'operator_call', {'turn_key': turn.key,
                    'name': 'inspect', 'arguments': {'value': 'private_arguments'}}))
                response, _ = await turn.next_response()
                call = response['output'][0]
                output = {'type': 'function_call_output', 'call_id': call['call_id'],
                    'output': 'private_native_error_result'}
                turn.accept_result(protocol(turn.protocol.request()['input'] + [call, output]))
                self.assertIn('private_native_error_result', (await task)['result']['content'][0]['text'])
            snapshot = endpoint.diagnostics()
            received = [e for e in snapshot['events'] if e['event'] == 'received' and e['method'] == 'tools/call']
            replies = [e for e in snapshot['events'] if e['event'] == 'reply_prepared' and e['method'] == 'tools/call']
            rejected = [e for e in snapshot['events'] if e['event'] == 'rejected']
            self.assertEqual((len(received), len(replies), len(rejected)), (6, 2, 4))
            self.assertEqual([e['stage'] for e in rejected], ['tool_dispatch', 'tool_dispatch', 'rpc', 'session'])
            self.assertEqual((turn.calls, turn.results), (1, 1))
            self.assertTrue(turn.frames.empty())
            encoded = json.dumps(snapshot)
            for secret in (turn.key, session, endpoint.path, 'private_bad_key', 'private_arguments', 'private_native_error_result'):
                self.assertNotIn(secret, encoded)
            snapshot['events'].clear()
            snapshot['methods'].clear()
            self.assertTrue(endpoint.diagnostics()['events'])
            self.assertEqual(endpoint.methods['tools/call'], 6)
        finally:
            await endpoint.stop()

    async def test_indexed_page_local_write_observation_is_bounded_and_preserves_reply(self):
        endpoint = WebMcpEndpoint(begin_result_mode='structured_begin_v1',
            indexed_protocol='mcp_context_records_v3')
        url = await endpoint.start()
        secret = 'private_source_content_' + 'x' * 70000
        turn = endpoint.turn = WebMcpTurn(protocol([{'role': 'user', 'content': secret}]))
        turn.prepare_indexed(wire_protocol='mcp_context_records_v3',
            begin_result_mode='structured_begin_v1')
        try:
            async with ClientSession() as client:
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0,
                        'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}}) as reply:
                    session = reply.headers['Mcp-Session-Id']
                    await reply.read()
                async with client.post(url, headers={'Mcp-Session-Id': session},
                        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'operator_begin',
                                'arguments': {'turn_key': turn.key}}}) as reply:
                    raw = await reply.read()
                    self.assertEqual(reply.status, 200)
                self.assertLessEqual(len(raw), INDEX_REPLY_BYTES)
                page = json.loads(raw)['result']['structuredContent']
                self.assertEqual((page['section'], page['index']), ('context', 0))
                self.assertGreater(page['total'], 1)
            events = [item for item in endpoint.diagnostics()['events']
                if item['tool'] == 'operator_begin']
            self.assertEqual([item['event'] for item in events],
                ['received', 'reply_prepared', 'local_response_write_completed'])
            self.assertEqual([(item['section'], item['index'], item['total']) for item in events[1:]],
                [('context', 0, page['total'])] * 2)
            self.assertNotIn(turn.key, json.dumps(events))
            self.assertNotIn(secret, json.dumps(events))
            self.assertNotIn(session, json.dumps(events))
        finally:
            turn.close()
            await endpoint.stop()

    async def test_indexed_page_write_failure_cancel_and_repeat_never_claim_completion(self):
        endpoint = WebMcpEndpoint()
        page = ('context', 0, 2)

        async def write_ok(self, data=b''):
            return None

        async def write_broken(self, data=b''):
            raise BrokenPipeError('private_socket_error')

        async def write_cancelled(self, data=b''):
            raise asyncio.CancelledError

        payload = {'jsonrpc': '2.0', 'id': 'private_rpc_id', 'result': {}}
        headers = {'X-Page-Fixture': 'same'}
        observed = endpoint._page_response(payload, headers, page)
        original = web.json_response(payload, dumps=dumps, headers=headers)
        self.assertEqual(observed.body, original.body)
        self.assertEqual(dict(observed.headers), dict(original.headers))
        self.assertEqual((observed.status, observed.content_type),
            (original.status, original.content_type))
        with patch.object(web.Response, 'write_eof', write_ok):
            await observed.write_eof()
            await observed.write_eof()
        with patch.object(web.Response, 'write_eof', write_broken):
            reply = endpoint._page_response(payload, {}, page)
            with self.assertRaises(BrokenPipeError):
                await reply.write_eof()
        with patch.object(web.Response, 'write_eof', write_cancelled):
            reply = endpoint._page_response(payload, {}, page)
            with self.assertRaises(asyncio.CancelledError):
                await reply.write_eof()
        events = endpoint.diagnostics()['events']
        self.assertEqual([item['event'] for item in events],
            ['local_response_write_completed', 'local_response_write_failed',
                'local_response_write_failed'])
        self.assertTrue(all((item['section'], item['index'], item['total']) == page
            for item in events))
        for secret in ('private_rpc_id', 'private_socket_error'):
            self.assertNotIn(secret, json.dumps(events))

    async def test_endpoint_diagnostics_are_bounded_and_unknown_labels_are_redacted(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        try:
            async with ClientSession() as client:
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                        'params': {'protocolVersion': '2025-11-25'}}) as r:
                    session = r.headers['Mcp-Session-Id']
                for index in range(70):
                    async with client.post(url, headers={'Mcp-Session-Id': session},
                            json={'jsonrpc': '2.0', 'id': index + 1,
                                  'method': 'private_untrusted_method_' + str(index)}) as r:
                        self.assertIn('error', await r.json())
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 100, 'method': []}) as r:
                    self.assertEqual((await r.json())['error']['message'], 'web_mcp_method_invalid')
            snapshot = endpoint.diagnostics()
            self.assertEqual(snapshot['methods'], {'initialize': 1, 'other': 70})
            self.assertEqual(len(snapshot['events']), 128)
            self.assertEqual(snapshot['eventsDropped'], snapshot['eventsTotal'] - 128)
            self.assertNotIn('private_untrusted_method', json.dumps(snapshot))
            self.assertEqual(snapshot['events'][-1]['code'], 'web_mcp_method_invalid')
        finally:
            await endpoint.stop()

    def test_rejected_tool_inventory_diagnostic_reports_counts_only(self):
        original = {'input': [{'role': 'user', 'content': 'fixture'}], 'tools': [FUNCTION]}
        extra = {**FUNCTION, 'name': 'second_fixture_tool'}
        previous = make(original, structured_tool_outputs=True)
        expanded = make({**original, 'tools': [FUNCTION, extra]}, structured_tool_outputs=True)
        reduced = make({**original, 'tools': []}, structured_tool_outputs=True)
        self.assertEqual(expanded.continuation_changes(previous)['tool_declarations'], {
            'bounded': True, 'before_count': 1, 'after_count': 2,
            'added_count': 1, 'removed_count': 0, 'change_kinds': {
                'classified': True, 'identity_added_count': 1, 'identity_removed_count': 0,
                'description_changed_count': 0, 'parameters_changed_count': 0,
                'strict_changed_count': 0, 'defer_loading_changed_count': 0,
                'defer_loading_true_to_false_count': 0,
                'defer_loading_false_to_true_count': 0, 'other_changed_count': 0,
                'defer_loading_presence_only_count': 0,
                'namespace_tools_changed_count': 0, 'custom_format_changed_count': 0,
                'tool_search_execution_changed_count': 0,
                'function_changed_count': 0, 'custom_changed_count': 0,
                'namespace_changed_count': 0, 'tool_search_changed_count': 0,
                'namespace_nested': {'bounded': True, 'identity_added_count': 0,
                    'identity_removed_count': 0, 'same_identity_changed_count': 0,
                    'order_only_count': 0, 'unclassifiable_count': 0},
                'order_changed': False}})
        self.assertEqual(reduced.continuation_changes(previous)['tool_declarations'], {
            'bounded': True, 'before_count': 1, 'after_count': 0,
            'added_count': 0, 'removed_count': 1, 'change_kinds': {
                'classified': True, 'identity_added_count': 0, 'identity_removed_count': 1,
                'description_changed_count': 0, 'parameters_changed_count': 0,
                'strict_changed_count': 0, 'defer_loading_changed_count': 0,
                'defer_loading_true_to_false_count': 0,
                'defer_loading_false_to_true_count': 0, 'other_changed_count': 0,
                'defer_loading_presence_only_count': 0,
                'namespace_tools_changed_count': 0, 'custom_format_changed_count': 0,
                'tool_search_execution_changed_count': 0,
                'function_changed_count': 0, 'custom_changed_count': 0,
                'namespace_changed_count': 0, 'tool_search_changed_count': 0,
                'namespace_nested': {'bounded': True, 'identity_added_count': 0,
                    'identity_removed_count': 0, 'same_identity_changed_count': 0,
                    'order_only_count': 0, 'unclassifiable_count': 0},
                'order_changed': False}})
        self.assertNotIn(extra['name'], json.dumps(expanded.continuation_changes(previous)))

    def test_rejected_tool_field_diagnostic_counts_only_fixed_categories(self):
        source = {'type': 'function', 'name': 'private_tool_alpha',
            'description': 'private description alpha',
            'parameters': {'type': 'object', 'properties': {}}, 'strict': False,
            'defer_loading': False}
        changed = {**source, 'description': 'private description beta',
            'parameters': {'type': 'object', 'properties': {'secret': {'type': 'string'}}},
            'strict': True, 'defer_loading': True}
        result = _tool_declaration_change_kinds([source], [changed])
        self.assertEqual(result, {'classified': True,
            'identity_added_count': 0, 'identity_removed_count': 0,
            'description_changed_count': 1, 'parameters_changed_count': 1,
            'strict_changed_count': 1, 'defer_loading_changed_count': 1,
            'defer_loading_true_to_false_count': 0,
            'defer_loading_false_to_true_count': 1, 'other_changed_count': 0,
            'defer_loading_presence_only_count': 0,
            'namespace_tools_changed_count': 0, 'custom_format_changed_count': 0,
            'tool_search_execution_changed_count': 0,
            'function_changed_count': 1, 'custom_changed_count': 0,
            'namespace_changed_count': 0, 'tool_search_changed_count': 0,
            'namespace_nested': {'bounded': True, 'identity_added_count': 0,
                'identity_removed_count': 0, 'same_identity_changed_count': 0,
                'order_only_count': 0, 'unclassifiable_count': 0},
            'order_changed': False})
        self.assertNotIn('private', json.dumps(result))
        renamed = {**source, 'name': 'private_tool_beta'}
        self.assertEqual(_tool_declaration_change_kinds([source], [renamed])['identity_added_count'], 1)
        self.assertEqual(_tool_declaration_change_kinds([source], [renamed])['identity_removed_count'], 1)
        second = {**source, 'name': 'private_tool_gamma'}
        self.assertTrue(_tool_declaration_change_kinds([source, second], [second, source])['order_changed'])

    def test_rejected_tool_diagnostic_recognizes_only_boolean_defer_loading_lift(self):
        previous = [{**FUNCTION, 'name': 'private_' + str(index), 'defer_loading': True}
            for index in range(6)]
        continued = [{key: value for key, value in item.items() if key != 'defer_loading'}
            for item in previous]
        result = _tool_declaration_change_kinds(previous, continued)
        self.assertEqual((result['defer_loading_changed_count'],
            result['defer_loading_true_to_false_count'], result['other_changed_count']),
            (6, 6, 0))
        self.assertEqual((result['identity_added_count'], result['identity_removed_count']), (0, 0))
        self.assertNotIn('private_', json.dumps(result))
        explicit_false = {**previous[0], 'defer_loading': False}
        self.assertEqual(_tool_declaration_change_kinds([previous[0]], [explicit_false])[
            'defer_loading_true_to_false_count'], 1)
        malformed = {**previous[0], 'defer_loading': 'false'}
        bad = _tool_declaration_change_kinds([previous[0]], [malformed])
        self.assertEqual((bad['defer_loading_changed_count'], bad['other_changed_count']), (0, 1))
        presence_only = _tool_declaration_change_kinds(
            [{**FUNCTION, 'defer_loading': False}], [FUNCTION])
        self.assertEqual((presence_only['defer_loading_changed_count'],
            presence_only['defer_loading_presence_only_count'],
            presence_only['other_changed_count']), (0, 1, 0))

    def test_rejected_tool_diagnostic_separates_known_remaining_fields_by_kind(self):
        source = [
            {'type': 'function', 'name': 'secret_function', 'parameters': {'type': 'object'}},
            {'type': 'custom', 'name': 'secret_custom', 'format': {'type': 'text'}},
            {'type': 'namespace', 'name': 'secret_namespace', 'tools': []},
            {'type': 'tool_search', 'execution': 'client', 'parameters': {'type': 'object'}},
        ]
        changed = deepcopy(source)
        changed[0]['unknown_private_field'] = 'private value'
        changed[1]['format'] = {'type': 'grammar', 'secret': 'private value'}
        changed[2]['tools'] = [FUNCTION]
        changed[3]['execution'] = 'server'
        result = _tool_declaration_change_kinds(source, changed)
        self.assertEqual({key: result[key] for key in (
            'function_changed_count', 'custom_changed_count', 'namespace_changed_count',
            'tool_search_changed_count', 'namespace_tools_changed_count',
            'custom_format_changed_count', 'tool_search_execution_changed_count',
            'other_changed_count')}, {
            'function_changed_count': 1, 'custom_changed_count': 1,
            'namespace_changed_count': 1, 'tool_search_changed_count': 1,
            'namespace_tools_changed_count': 1, 'custom_format_changed_count': 1,
            'tool_search_execution_changed_count': 1, 'other_changed_count': 1})
        for private in ('secret_', 'private value', 'unknown_private_field'):
            self.assertNotIn(private, json.dumps(result))

    def test_rejected_namespace_nested_diagnostic_aggregates_one_level_only(self):
        def function(name, description='private original'):
            return {**FUNCTION, 'name': name, 'description': description}
        first = [
            {'type': 'namespace', 'name': 'secret_changed', 'tools': [function('secret_a')]},
            {'type': 'namespace', 'name': 'secret_added', 'tools': []},
            {'type': 'namespace', 'name': 'secret_removed', 'tools': [function('secret_b')]},
            {'type': 'namespace', 'name': 'secret_reordered',
                'tools': [function('secret_c'), function('secret_d')]},
            {'type': 'namespace', 'name': 'secret_duplicate', 'tools': [function('secret_e')]},
            {'type': 'namespace', 'name': 'secret_malformed', 'tools': [function('secret_f')]},
        ]
        second = deepcopy(first)
        second[0]['tools'][0]['description'] = 'private changed'
        second[1]['tools'].append(function('secret_g'))
        second[2]['tools'] = []
        second[3]['tools'].reverse()
        second[4]['tools'].append(function('secret_e'))
        second[5]['tools'] = ['private invalid']
        result = _tool_declaration_change_kinds(first, second)
        self.assertEqual(result['namespace_tools_changed_count'], 6)
        self.assertEqual(result['namespace_nested'], {
            'bounded': True, 'identity_added_count': 1, 'identity_removed_count': 1,
            'same_identity_changed_count': 1, 'order_only_count': 1,
            'unclassifiable_count': 2, 'field_changes': {
                'description': 1, 'parameters': 0, 'strict': 0, 'format': 0,
                'defer_loading_true_to_false': 0, 'defer_loading_false_to_true': 0,
                'defer_loading_presence_only': 0}})
        for private in ('secret_', 'private changed', 'private invalid'):
            self.assertNotIn(private, json.dumps(result))

    def test_nested_declaration_fields_keep_schema_and_loading_changes_distinct(self):
        original = [
            {**FUNCTION, 'name': 'private_function', 'description': 'private text',
                'strict': False, 'defer_loading': True},
            {**FUNCTION, 'name': 'private_presence', 'defer_loading': False},
            {'type': 'custom', 'name': 'private_custom', 'format': {'type': 'text'}},
        ]
        updated = deepcopy(original)
        updated[0].update(description='other private text', strict=True, defer_loading=False,
            parameters={'type': 'object', 'properties': {'private_arg': {'type': 'string'}}})
        updated[1].pop('defer_loading')
        updated[2].update(format={'type': 'grammar', 'definition': 'private grammar'},
            defer_loading=True)
        before = [{'type': 'namespace', 'name': 'private_namespace', 'tools': original}]
        after = [{'type': 'namespace', 'name': 'private_namespace', 'tools': updated}]
        saved = deepcopy((before, after))
        result = _tool_declaration_change_kinds(before, after)
        self.assertEqual(result['namespace_nested']['field_changes'], {
            'description': 1, 'parameters': 1, 'strict': 1, 'format': 1,
            'defer_loading_true_to_false': 1, 'defer_loading_false_to_true': 1,
            'defer_loading_presence_only': 1})
        self.assertEqual((before, after), saved)
        self.assertNotIn('private', json.dumps(result))

    def test_rejected_namespace_nested_diagnostic_caps_aggregate_size(self):
        many = [{**FUNCTION, 'name': 'private_' + str(index)} for index in range(1025)]
        old = [{'type': 'namespace', 'name': 'secret_namespace', 'tools': many}]
        new = [{'type': 'namespace', 'name': 'secret_namespace', 'tools': []}]
        self.assertEqual(_tool_declaration_change_kinds(old, new)['namespace_nested'], {
            'bounded': False, 'identity_added_count': 0, 'identity_removed_count': 0,
            'same_identity_changed_count': 0, 'order_only_count': 0,
            'unclassifiable_count': 1})

    def test_rejected_tool_field_diagnostic_does_not_guess_ambiguous_identity(self):
        source = {'type': 'function', 'name': 'private_tool_alpha'}
        for before, after in (([source, source], [source]), ([source], [source, source]),
                ([source], ['private invalid']), ([source] * 1025, [])):
            with self.subTest(before=len(before), after=len(after)):
                self.assertEqual(_tool_declaration_change_kinds(before, after), {'classified': False})

    async def test_continuation_controls_cannot_change_after_browser_begin(self):
        changes = [
            {'tool_choice': 'none'}, {'tool_choice': 'required'},
            {'reasoning': None}, {'parallel_tool_calls': True},
            {'instructions': None}, {'text': {'format': {'type': 'json_object'}}},
            {'tools': [{**FUNCTION, 'strict': True}]},
            {'tools': [{**FUNCTION, 'description': 'changed after non-indexed begin'}]},
            {'metadata': {'fixture': 1}},
            {'client_metadata': {'x-codex-turn-metadata': '{"turn_id":"changed"}'}},
        ]
        for change in changes:
            with self.subTest(change=change):
                payload = {'input': [{'role': 'user', 'content': 'fixture'}],
                    'tools': [FUNCTION], 'parallel_tool_calls': False,
                    'metadata': {'fixture': True},
                    'client_metadata': {'x-codex-turn-metadata': '{"turn_id":"original"}'}}
                turn = WebMcpTurn(make(payload, structured_tool_outputs=True))
                turn.begin(turn.key)
                task = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}))
                try:
                    response, _ = await turn.next_response()
                    call = response['output'][0]
                    continued = deepcopy(payload)
                    continued['input'] += [call, {'type': 'function_call_output',
                        'call_id': call['call_id'], 'output': 'exact result'}]
                    continued.update(change)
                    with self.assertRaisesRegex(RouterError, 'web_mcp_request_binding_changed'):
                        turn.accept_result(make(continued, structured_tool_outputs=True))
                    self.assertTrue(turn.closed)
                    self.assertEqual(turn.results, 0)
                    observation = turn.observation()
                    self.assertIn('binding_changes', observation)
                    self.assertEqual(observation['binding_changes']['route'], False)
                    self.assertTrue(observation['binding_changes']['controls']['fields'])
                    if 'tools' in change:
                        self.assertEqual(observation['binding_changes']['controls']['tool_declarations'], {
                            'bounded': True, 'before_count': 1, 'after_count': 1,
                            'added_count': 1, 'removed_count': 1, 'change_kinds': {
                                'classified': True, 'identity_added_count': 0,
                                'identity_removed_count': 0,
                                'description_changed_count': int(change['tools'][0]['description'] != FUNCTION['description']),
                                'parameters_changed_count': 0,
                                'strict_changed_count': int('strict' in change['tools'][0]),
                                'defer_loading_changed_count': 0,
                                'defer_loading_true_to_false_count': 0,
                                'defer_loading_false_to_true_count': 0,
                                'defer_loading_presence_only_count': 0,
                                'namespace_tools_changed_count': 0,
                                'custom_format_changed_count': 0,
                                'tool_search_execution_changed_count': 0,
                                'function_changed_count': 1, 'custom_changed_count': 0,
                                'namespace_changed_count': 0, 'tool_search_changed_count': 0,
                                'namespace_nested': {'bounded': True, 'identity_added_count': 0,
                                    'identity_removed_count': 0, 'same_identity_changed_count': 0,
                                    'order_only_count': 0, 'unclassifiable_count': 0},
                                'other_changed_count': 0, 'order_changed': False}})
                    else:
                        self.assertNotIn('tool_declarations', observation['binding_changes']['controls'])
                    self.assertNotIn('exact result', json.dumps(observation))
                    self.assertNotIn('Synthetic read', json.dumps(observation))
                    observation['binding_changes']['controls']['fields'].append('mutated')
                    self.assertNotIn('mutated', turn.binding_changes['controls']['fields'])
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    turn.close()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_rejected_result_is_terminal_and_cannot_be_repaired(self):
        turn = WebMcpTurn(protocol())
        source = turn.begin(turn.key)
        task = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}))
        try:
            response, _ = await turn.next_response()
            call = response['output'][0]
            history = source['request']['input'] + [call,
                {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'exact'}]
            bad = deepcopy(history)
            bad[0]['content'] = 'changed history'
            with self.assertRaisesRegex(RouterError, 'web_mcp_history_changed'):
                turn.accept_result(protocol(bad))
            with self.assertRaisesRegex(RouterError, 'web_mcp_turn_closed'):
                turn.accept_result(protocol(history))
            self.assertEqual(turn.results, 0)
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            turn.close()
            await asyncio.gather(task, return_exceptions=True)

    async def test_real_protocol_call_waits_for_exact_native_result(self):
        initial = protocol(metadata={'first': True, 'second': '中文'}, client_metadata={
            'x-codex-turn-metadata': '{"turn_id":"fixture","sandbox":"read-only"}'})
        turn = WebMcpTurn(initial)
        source = turn.begin(turn.key)
        task = asyncio.create_task(turn.invoke(turn.key, 'rpc-1', source['tools'][0]['name'], {'value': '中文\r\na_b'}))
        response, events = await turn.next_response()
        self.assertFalse(task.done())
        self.assertEqual(events[-1]['type'], 'response.completed')
        call = response['output'][0]
        result = {'type': 'function_call_output', 'call_id': call['call_id'],
            'output': [{'type': 'input_text', 'text': 'actual result\r\n中文'}, {'type': 'input_text', 'text': ''}]}
        history = source['request']['input'] + [call, result]
        continued = protocol(history, metadata={'second': '中文', 'first': True}, client_metadata={
            'x-codex-turn-metadata': '{"sandbox":"read-only","turn_id":"fixture","workspaces":{"fixture":{"has_changes":true}}}'})
        turn.accept_result(continued)
        self.assertEqual(initial.request()['client_metadata']['x-codex-turn-metadata'],
            '{"turn_id":"fixture","sandbox":"read-only"}')
        self.assertEqual(continued.request()['client_metadata']['x-codex-turn-metadata'],
            '{"sandbox":"read-only","turn_id":"fixture","workspaces":{"fixture":{"has_changes":true}}}')
        self.assertEqual(await task, {'codex_function_result': result})
        turn.finish(message(['final 中文']))
        final, _ = await turn.next_response()
        self.assertEqual(final['output'][0]['content'][0]['text'], 'final 中文')
        self.assertEqual((turn.calls, turn.results), (1, 1))
        turn.close()

    async def test_unknown_duplicate_and_pending_final_release_nothing(self):
        turn = WebMcpTurn(protocol())
        with self.assertRaises(RouterError): turn.begin('wrong')
        turn.begin(turn.key)
        with self.assertRaises(RouterError): turn.begin(turn.key)
        with self.assertRaises(RouterError): await turn.invoke(turn.key, 1, 'unknown', {})
        self.assertTrue(turn.frames.empty())
        task = asyncio.create_task(turn.invoke(turn.key, 2, 'inspect', {'value': 'x'}))
        await turn.next_response()
        with self.assertRaises(RouterError): await turn.invoke(turn.key, 2, 'inspect', {'value': 'x'})
        with self.assertRaises(RouterError): turn.finish(message())
        turn.close()
        with self.assertRaises(asyncio.CancelledError): await task

    async def test_changed_history_result_and_tool_map_do_not_resolve_waiter(self):
        for change in ('history', 'arguments', 'identity'):
            turn = WebMcpTurn(protocol())
            source = turn.begin(turn.key)
            task = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}))
            response, _ = await turn.next_response()
            call = response['output'][0]
            result = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'exact'}
            history = deepcopy(source['request']['input'] + [call, result])
            if change == 'history': history[0]['content'] = 'changed'
            elif change == 'arguments': history[-2]['arguments'] = '{"value":"different"}'
            else: history[-1]['call_id'] = 'different'
            with self.assertRaises(RouterError): turn.accept_result(protocol(history))
            self.assertFalse(task.done())
            turn.close()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_endpoint_only_exposes_bounded_authenticated_rpc(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        try:
            async with ClientSession() as client:
                async with client.get(url) as r: self.assertEqual(r.status, 405)
                async with client.post(url, headers={'Origin': 'https://untrusted.example'}, json={}) as r:
                    self.assertEqual(r.status, 403)
                async with client.post(url + '/wrong', json={}) as r: self.assertEqual(r.status, 403)
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-11-25'}}) as r:
                    session = r.headers['Mcp-Session-Id']
                    self.assertIn('result', await r.json())
                client.headers['Mcp-Session-Id'] = session
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) as r:
                    tools = (await r.json())['result']['tools']
                    self.assertEqual([t['name'] for t in tools], ['operator_begin', 'operator_call'])
                    self.assertEqual(tools[1]['annotations'], {'readOnlyHint': False, 'destructiveHint': True,
                        'idempotentHint': False, 'openWorldHint': True})
                    self.assertIs(tools[0]['annotations']['openWorldHint'], False)
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'operator_begin', 'arguments': {'turn_key': 'unknown'}}}) as r:
                    self.assertIn('error', await r.json())
        finally:
            await endpoint.stop()

    async def test_structured_call_preserves_original_result_and_legacy_representation(self):
        outputs = ['  actual 中文😀\r\na_b\\n  ',
            '{"error":"permission_denied","detail":"未执行"}',
            [{'type': 'input_text', 'text': 'ParserError\r\n中文'},
                {'type': 'input_text', 'text': ''}, {'type': 'input_text', 'text': 'last  '}]]
        for mode in ('text_v1', 'structured_call_v1'):
            for output in outputs:
                with self.subTest(mode=mode, output=output):
                    endpoint = WebMcpEndpoint(call_result_mode=mode)
                    url = await endpoint.start()
                    turn = endpoint.turn = WebMcpTurn(protocol())
                    source = turn.begin(turn.key)
                    pending = None
                    try:
                        async with ClientSession() as client:
                            async with client.post(url, json={'jsonrpc': '2.0', 'id': 0,
                                    'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}}) as r:
                                client.headers['Mcp-Session-Id'] = r.headers['Mcp-Session-Id']
                            async with client.post(url, json={'jsonrpc': '2.0', 'id': 1,
                                    'method': 'tools/list'}) as r:
                                tool = (await r.json())['result']['tools'][1]
                            self.assertEqual(tool['annotations'], {'readOnlyHint': False, 'destructiveHint': True,
                                'idempotentHint': False, 'openWorldHint': True})
                            self.assertEqual('outputSchema' in tool, mode == 'structured_call_v1')
                            pending = asyncio.create_task(client.post(url, json={'jsonrpc': '2.0', 'id': 2,
                                'method': 'tools/call', 'params': {'name': 'operator_call', 'arguments': {
                                    'turn_key': turn.key, 'name': 'inspect', 'arguments': {'value': 'fixture'}}}}))
                            response, _ = await turn.next_response()
                            self.assertFalse(pending.done())
                            call = response['output'][0]
                            original = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': output}
                            turn.accept_result(protocol(source['request']['input'] + [call, original]))
                            async with await pending as r:
                                self.assertEqual(r.status, 200)
                                result = (await r.json())['result']
                            expected = {'codex_function_result': original}
                            if mode == 'structured_call_v1':
                                self.assertEqual(result, {'structuredContent': expected, 'content': [], 'isError': False})
                                schema = tool['outputSchema']
                                self.assertEqual(schema['required'], ['codex_function_result'])
                                self.assertEqual(set(expected), set(schema['properties']))
                                self.assertIs(schema['additionalProperties'], False)
                                native_schema = schema['properties']['codex_function_result']
                                self.assertEqual(native_schema['required'], ['call_id'])
                                self.assertEqual(native_schema['properties']['call_id']['type'], 'string')
                                self.assertIs(native_schema['additionalProperties'], True)
                            else:
                                self.assertEqual(result, {'content': [{'type': 'text', 'text': json.dumps(
                                    expected, ensure_ascii=False, separators=(',', ':'))}], 'isError': False})
                            self.assertEqual((turn.calls, turn.released_calls, turn.results), (1, 1, 1))
                            # The MCP envelope cannot classify native failure as
                            # success or discard empty/whitespace content parts.
                            self.assertNotIn('_meta', result)
                            async with client.post(url, json={'jsonrpc': '2.0', 'id': 2,
                                    'method': 'tools/call', 'params': {'name': 'operator_call', 'arguments': {
                                        'turn_key': turn.key, 'name': 'inspect', 'arguments': {'value': 'replay'}}}}) as r:
                                self.assertEqual((await r.json())['error']['message'], 'web_mcp_duplicate_no_retry')
                            self.assertTrue(turn.frames.empty())
                    finally:
                        turn.close()
                        if pending is not None:
                            await asyncio.gather(pending, return_exceptions=True)
                        await endpoint.stop()

    async def test_session_scoped_ids_admit_new_calls_but_never_replay_a_session(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        turn = endpoint.turn = WebMcpTurn(protocol())
        source = turn.begin(turn.key)
        history = source['request']['input']
        try:
            async with ClientSession() as client:
                sessions = []
                for _ in range(2):
                    async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                        'params': {'protocolVersion': '2025-11-25'}}) as r:
                        sessions.append(r.headers['Mcp-Session-Id'])
                self.assertNotEqual(*sessions)
                for index, session in enumerate(sessions):
                    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': 'operator_call', 'arguments': {'turn_key': turn.key,
                            'name': 'inspect', 'arguments': {'value': str(index)}}}}
                    task = asyncio.create_task(client.post(url, headers={'Mcp-Session-Id': session}, json=payload))
                    response, _ = await turn.next_response()
                    call = response['output'][0]
                    output = {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'actual-' + str(index)}
                    history = history + [call, output]
                    turn.accept_result(protocol(history))
                    async with await task as r:
                        result = await r.json()
                        self.assertEqual(result['id'], 1)
                        self.assertIn('actual-' + str(index), result['result']['content'][0]['text'])
                    payload['params']['arguments']['arguments'] = {'value': 'different'}
                    async with client.post(url, headers={'Mcp-Session-Id': session}, json=payload) as r:
                        self.assertEqual((await r.json())['error']['message'], 'web_mcp_duplicate_no_retry')
                    self.assertTrue(turn.frames.empty())
                self.assertEqual((turn.calls, turn.results), (2, 2))
        finally:
            await endpoint.stop()

    async def test_sessions_are_required_bounded_and_expire_without_calls(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        try:
            async with ClientSession() as client:
                payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
                async with client.post(url, json=payload) as r: self.assertEqual(r.status, 400)
                async with client.post(url, headers={'Mcp-Session-Id': 'unknown'}, json=payload) as r:
                    self.assertEqual(r.status, 404)
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-11-25'}}) as r:
                    session = r.headers['Mcp-Session-Id']
                endpoint.sessions[session]['deadline'] = 0
                async with client.post(url, headers={'Mcp-Session-Id': session}, json=payload) as r:
                    self.assertEqual(r.status, 404)
                endpoint.sessions = {str(i): {'deadline': float('inf'), 'seen': set()} for i in range(64)}
                async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-11-25'}}) as r:
                    self.assertEqual((await r.json())['error']['message'], 'web_mcp_session_limit')
        finally:
            await endpoint.stop()

    async def test_cancellation_only_closes_the_exact_pending_session_and_id(self):
        endpoint = WebMcpEndpoint()
        url = await endpoint.start()
        turn = endpoint.turn = WebMcpTurn(protocol())
        turn.begin(turn.key)
        task = None
        try:
            async with ClientSession() as client:
                sessions = []
                for _ in range(2):
                    async with client.post(url, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                        'params': {'protocolVersion': '2025-11-25'}}) as r:
                        sessions.append(r.headers['Mcp-Session-Id'])
                task = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}, session_id=sessions[0]))
                await turn.next_response()
                notice = {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 1}}
                async with client.post(url, headers={'Mcp-Session-Id': sessions[1]}, json=notice) as r:
                    self.assertEqual(r.status, 202)
                self.assertFalse(turn.closed)
                notice['params']['requestId'] = 2
                async with client.post(url, headers={'Mcp-Session-Id': sessions[0]}, json=notice) as r:
                    self.assertEqual(r.status, 202)
                self.assertFalse(turn.closed)
                notice['params']['requestId'] = 1
                async with client.post(url, headers={'Mcp-Session-Id': sessions[0]}, json=notice) as r:
                    self.assertEqual(r.status, 202)
                self.assertTrue(turn.closed)
                with self.assertRaises(asyncio.CancelledError): await task
        finally:
            await endpoint.stop()
            if task is not None: await asyncio.gather(task, return_exceptions=True)

    async def test_close_wakes_native_waiter_without_releasing_output(self):
        turn = WebMcpTurn(protocol())
        wait = asyncio.create_task(turn.next_response())
        await asyncio.sleep(0)
        turn.close()
        with self.assertRaisesRegex(RouterError, 'web_mcp_turn_closed'):
            await asyncio.wait_for(wait, 0.5)

    async def test_original_namespaced_result_is_retained(self):
        from test_web_model_protocol import make, FUNCTION
        payload = {'input': [{'role': 'user', 'content': 'fixture'}],
            'tools': [{'type': 'namespace', 'name': 'fixture', 'tools': [FUNCTION]}]}
        p = make(payload, structured_tool_outputs=True)
        turn = WebMcpTurn(p)
        source = turn.begin(turn.key)
        task = asyncio.create_task(turn.invoke(turn.key, 1, source['tools'][0]['name'], {'value':'x'}))
        response, _ = await turn.next_response()
        call = response['output'][0]
        result = {'type':'function_call_output','call_id':call['call_id'],'name':'inspect','namespace':'fixture',
            'output':[{'type':'input_text','text':'真实\r\n结果','metadata':{'kept':True}}]}
        continued = deepcopy(payload)
        continued['input'] += [call, result]
        turn.accept_result(make(continued, structured_tool_outputs=True))
        self.assertEqual(await task, {'codex_function_result': result})
        turn.close()
