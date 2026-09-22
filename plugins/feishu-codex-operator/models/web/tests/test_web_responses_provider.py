"""Actual loopback HTTP with synthetic browser messages, no model execution."""

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
import io
import json
import time
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from test_web_model_protocol import message, SLUG, FUNCTION
from test_web_mcp_transport import protocol
from operator_core.model_router import MAX_BODY
from operator_core.responses_capabilities import RouterError
from operator_core.web_mcp_transport import WebBrowserHttpError, WebMcpEndpoint, WebResponsesBridge
from operator_core.web_responses_provider import WebResponsesProvider


class WebResponsesProviderTests(unittest.IsolatedAsyncioTestCase):
    def payload(self, turn='fixture-turn', stream=True):
        return {'model':SLUG,'input':[{'role':'user','content':'fixture'}],
            'tools':[FUNCTION], 'reasoning':{'effort':'high'}, 'stream':stream,
            'client_metadata':{'thread_id':'fixture-thread','turn_id':turn}}

    async def create_provider(self, browser):
        bridge = WebResponsesBridge(protocol().route, WebMcpEndpoint(), browser)
        provider = WebResponsesProvider(bridge)
        url = await provider.start()
        self.addAsyncCleanup(provider.stop)
        return provider, url, {'Authorization':'Bearer ' + provider.token}

    async def test_http_call_result_and_final_preserve_sse_bytes(self):
        actual = []
        async def browser(turn):
            turn.begin(turn.key)
            actual.append(await turn.invoke(turn.key, 1, 'inspect', {'value':'中文\r\nx'}))
            return message(['  中文\r\n', '', 'a_b\n'])
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload()
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, 'text/event-stream')
                events = [json.loads(line[6:]) for line in (await response.text()).splitlines()
                    if line.startswith('data: ')]
            call = events[-1]['response']['output'][0]
            output = {'type':'function_call_output','call_id':call['call_id'],
                'output':[{'type':'input_text','text':'actual\r\nresult'}]}
            payload['input'] += [call, output]
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
                events = [json.loads(line[6:]) for line in (await response.text()).splitlines()
                    if line.startswith('data: ')]
                parts = events[-1]['response']['output'][0]['content']
            self.assertEqual([part['text'] for part in parts], ['  中文\r\n', '', 'a_b\n'])
            self.assertEqual(actual, [{'codex_function_result':output}])
            self.assertEqual(provider.requests, 2)
            async with client.get('http://' + provider.host + '/health') as response:
                observation = (await response.json())['transport']
                self.assertEqual(observation['scope'], 'transport_only')
                self.assertEqual(observation['last_turn']['calls_released'], 1)
                self.assertEqual(observation['last_turn']['results_received'], 1)
                self.assertTrue(observation['last_turn']['public_final_returned'])
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                self.assertEqual((await response.json())['error']['code'], 'web_bridge_turn_consumed_no_retry')

    async def test_json_and_compressed_input_have_one_dispatch_each(self):
        calls = []
        async def browser(turn):
            calls.append(turn.begin(turn.key)['request']['input'])
            return message(['exact\r\n中文'])
        _, url, headers = await self.create_provider(browser)
        async with ClientSession(headers=headers) as client:
            for index, compressed in enumerate((False, True)):
                payload = self.payload(turn=str(index), stream=False)
                options = {'json':payload} if not compressed else {
                    'data':gzip.compress(json.dumps(payload).encode()),
                    'headers':{'Content-Type':'application/json','Content-Encoding':'gzip'}}
                async with client.post(url + '/responses', **options) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.content_type, 'application/json')
                    self.assertEqual((await response.json())['output'][0]['content'][0]['text'], 'exact\r\n中文')
            self.assertEqual(len(calls), 2)

    async def test_auth_host_origin_path_and_method_reject_before_dispatch(self):
        calls = []
        async def browser(turn):
            calls.append(True)
            return message()
        provider, url, headers = await self.create_provider(browser)
        async with ClientSession() as client:
            for path, method, extra, expected in [
                ('/responses','POST',{},401),
                ('/responses','POST',{**headers,'Host':'untrusted.example'},403),
                ('/responses','POST',{**headers,'Origin':'https://untrusted.example'},403),
                ('/responses?x=1','POST',headers,403),
                ('/unknown','POST',headers,404),
                ('/responses','GET',headers,405),
                ('/responses','POST',{**headers,'Content-Type':'text/plain'},415),
            ]:
                async with client.request(method,url + path,headers=extra,data=b'{}') as response:
                    self.assertEqual(response.status, expected)
            async with client.get('http://' + provider.host + '/health',headers=headers) as response:
                self.assertEqual(await response.json(), {'ready':True,'active':False,'requests':0,
                    'state':'ready','accepting_requests':True,
                    'mcp':provider.bridge.endpoint.diagnostics(),
                    'transport': {'scope':'transport_only','active_turn':None,'last_turn':None}})
        self.assertEqual(calls, [])

    async def test_authenticated_health_exposes_local_mcp_rejection_without_call_data(self):
        async def browser(turn):
            return message()
        provider, _, headers = await self.create_provider(browser)
        endpoint=provider.bridge.endpoint
        address=await endpoint.start()
        self.addAsyncCleanup(endpoint.stop)
        async with ClientSession() as client:
            async with client.post(address,json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                    'params':{'name':'operator_call','arguments':{'turn_key':'private-probe-key'}}}) as response:
                self.assertEqual(response.status,400)
            async with client.get('http://'+provider.host+'/health') as response:
                self.assertEqual(response.status,401)
                self.assertNotIn('mcp',await response.json())
            async with client.get('http://'+provider.host+'/health',headers=headers) as response:
                result=await response.json()
                self.assertEqual(result['mcp']['events'][-1]['code'],'web_mcp_session_required')
                self.assertEqual(result['mcp']['events'][-1]['tool'],'operator_call')
                self.assertEqual(result['requests'],0)
                self.assertIsNone(result['transport']['active_turn'])
                self.assertNotIn('private-probe-key',json.dumps(result))
                self.assertNotIn(endpoint.path,json.dumps(result))

    async def test_wire_and_decompressed_bounds_reject_before_browser(self):
        calls = []
        async def browser(turn):
            calls.append(True)
            return message()
        _, url, headers = await self.create_provider(browser)
        async with ClientSession(headers=headers) as client:
            oversized = b' ' * (MAX_BODY + 1)
            for encoding, body in [('identity',oversized),('gzip',gzip.compress(oversized))]:
                async with client.post(url + '/responses', data=io.BytesIO(body), headers={
                        'Content-Type':'application/json','Content-Encoding':encoding}) as response:
                    self.assertEqual(response.status, 413)
                    error = (await response.json())['error']
                    self.assertEqual(error['limit_bytes'], MAX_BODY)
                    self.assertEqual(error['scope'], 'http_request' if encoding == 'identity' else 'decoded_request')
                    self.assertEqual(error['observation'], 'local_request_preflight')
                    self.assertFalse(error['retryable'])
                    self.assertIn(error['scope'],error['message'])
                    self.assertIn(str(MAX_BODY),error['message'])
            async with client.post(url + '/responses',data=b'{"model":"one","model":"two"}',
                    headers={'Content-Type':'application/json'}) as response:
                self.assertEqual(response.status, 400)
        self.assertEqual(calls, [])

    async def test_assistance_gate_is_observable_and_never_queues_a_request(self):
        calls = []
        async def browser(turn):
            calls.append(turn.begin(turn.key)['request']['input'])
            return message(['new explicit request'])
        provider, url, headers = await self.create_provider(browser)
        provider.admission_state = 'assistance'
        async with ClientSession(headers=headers) as client:
            async with client.get('http://' + provider.host + '/health') as response:
                health = await response.json()
                self.assertTrue(health['ready'])  # Listener only, not browser readiness.
                self.assertEqual(health['state'], 'assistance')
                self.assertFalse(health['accepting_requests'])
            async with client.post(url + '/responses', json=self.payload('during-assistance')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                error = (await response.json())['error']
                self.assertEqual(error['code'], 'web_browser_assistance_pending_before_dispatch')
                self.assertIn('主动打开 Operator 辅助窗口', error['message'])
            self.assertFalse(provider.bridge.admitted)
            provider.admission_state = 'ready'
            await asyncio.sleep(0)
            self.assertEqual(calls, [])
            async with client.post(url + '/responses', json=self.payload('new-after-assistance')) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(len(calls), 1)

    async def test_drain_allows_only_the_owned_tool_result_then_stays_closed(self):
        results = []
        async def browser(turn):
            turn.begin(turn.key)
            results.append(await turn.invoke(turn.key, 1, 'inspect', {'value':'original'}))
            return message(['completed original turn'])
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload('owned', stream=False)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
                call = (await response.json())['output'][0]
            provider.admission_state = 'draining'
            async with client.post(url + '/responses', json=self.payload('unrelated')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                self.assertEqual((await response.json())['error']['code'], 'web_provider_draining')
            self.assertEqual(provider.bridge.owner, ('fixture-thread','owned'))
            output = {'type':'function_call_output','call_id':call['call_id'],'output':'exact result'}
            payload['input'] += [call, output]
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(results, [{'codex_function_result':output}])
            async with client.post(url + '/responses', json=self.payload('after-drain')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 503)
            self.assertEqual(len(provider.bridge.admitted), 1)

    async def test_disconnect_cancels_browser_and_duplicate_does_not_start_again(self):
        started, stopped = asyncio.Event(), asyncio.Event()
        async def browser(turn):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        _, url, headers = await self.create_provider(browser)
        async with ClientSession(headers=headers) as client:
            pending = asyncio.create_task(client.post(url + '/responses', json=self.payload()))
            await asyncio.wait_for(started.wait(), 2)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            await asyncio.wait_for(stopped.wait(), 2)
            async with client.post(url + '/responses', json=self.payload()) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)

    async def test_browser_failure_returns_fixed_error_and_shutdown_closes_listener(self):
        async def browser(turn):
            raise RuntimeError('Private page or credential must not appear')
        provider, url, headers = await self.create_provider(browser)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=self.payload()) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                error = (await response.json())['error']
                self.assertEqual(error['code'], 'web_browser_driver_failed_no_retry')
                self.assertIs(error['retryable'], False)
                self.assertIn('不会自动重做', error['message'])
                self.assertIn('本轮本机未转交工具调用。', error['message'])
                self.assertEqual(error['transport']['turn']['calls_released'], 0)
                self.assertNotIn('Private', json.dumps(error))
        await provider.stop()
        self.assertTrue(provider.closed)
        self.assertIsNone(provider.runner)
        self.assertIsNone(provider.bridge.endpoint.turn)

    async def test_incomplete_indexed_context_is_terminal_and_distinct_from_browser_failure(self):
        calls=[]
        async def browser(turn):
            turn.prepare_indexed()
            calls.append(turn)
            page=turn.begin(turn.key)
            self.assertIsNotNone(page['next_read_key'])
            if len(calls)==2:
                while page['next_read_key']:
                    page=turn.begin(page['next_read_key'])
            return message(['private public text', '', '\r\n中文'])
        for stream in (False,True):
            calls.clear()
            provider,url,headers=await self.create_provider(browser)
            payload=self.payload(stream=stream)
            payload['input'][0]['content']='中文 context\r\n' * 7000
            async with ClientSession(headers=headers) as client:
                async with client.post(url+'/responses',json=payload) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                    self.assertEqual(response.content_type,'application/json')
                    error=(await response.json())['error']
                self.assertEqual(error['code'],'web_mcp_context_not_read')
                self.assertFalse(error['retryable'])
                self.assertIn('尚未读完本次请求的上下文',error['message'])
                self.assertIn('这不表示登录失效',error['message'])
                self.assertIn('本轮本机未转交工具调用',error['message'])
                self.assertNotIn('private public text',json.dumps(error))
                self.assertNotIn(calls[0].key,json.dumps(error))
                self.assertFalse(error['transport']['turn']['request_read'])
                self.assertEqual(error['transport']['turn']['calls_released'],0)
                self.assertFalse(error['transport']['turn']['public_final_returned'])
                self.assertIsNone(provider.bridge.turn)
                self.assertTrue(calls[0].closed)
                self.assertEqual(calls[0].indexed.pages,{})
                async with client.post(url+'/responses',json=payload) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                self.assertEqual(len(calls),1)
                payload['client_metadata']['turn_id']='new-complete-context'
                payload['stream']=False
                async with client.post(url+'/responses',json=payload) as response:
                    self.assertEqual(response.status,200)
                    output=(await response.json())['output'][0]
                self.assertEqual([part['text'] for part in output['content']],['private public text','','\r\n中文'])
                self.assertEqual(len(calls),2)
            await provider.stop()

    async def test_local_citation_error_reaches_http_without_source_content_or_replay(self):
        count = 0
        async def browser(turn):
            nonlocal count
            count += 1
            turn.begin(turn.key)
            return message(['private text \ue200url\ue202unmapped\ue202turn0search0\ue201'], public_references=[])
        provider,url,headers=await self.create_provider(browser)
        provider.bridge.citation_mode='markdown_links_v1'
        async with ClientSession(headers=headers) as client:
            async with client.post(url+'/responses',json=self.payload()) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                error=(await response.json())['error']
            self.assertEqual(error['code'],'web_public_citation_unmapped')
            self.assertFalse(error['retryable'])
            self.assertIn('来源引用',error['message'])
            self.assertNotIn('private text',json.dumps(error))
            self.assertEqual(error['transport']['turn']['calls_released'],0)
            async with client.post(url+'/responses',json=self.payload()) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            self.assertEqual(count,1)

    async def test_browser_exception_cannot_claim_local_context_terminal_gate(self):
        for claimed in ('web_mcp_context_not_read', 'web_mcp_request_capacity_exceeded_before_dispatch', 'web_public_citation_unmapped'):
            for indexed in (False,True):
                async def browser(turn):
                    if indexed: turn.prepare_indexed()
                    raise RouterError(claimed)
                provider,url,headers=await self.create_provider(browser)
                async with ClientSession(headers=headers) as client:
                    async with client.post(url+'/responses',json=self.payload()) as response:
                        self.assertEqual(response.status, 400)
                        self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                        error=(await response.json())['error']
                    self.assertEqual(error['code'],'web_browser_driver_failed_no_retry')
                    self.assertNotIn('尚未读完',error['message'])
                    self.assertNotIn('读取容量',error['message'])
                await provider.stop()

    async def test_rejected_native_result_reports_only_current_transport_without_replay(self):
        received = []
        async def browser(turn):
            turn.begin(turn.key)
            received.append(await turn.invoke(turn.key, 1, 'inspect', {'value': 'private argument'}))
            return message(['must not be returned'])
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload(stream=False)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
                call = (await response.json())['output'][0]
            payload['input'] += [call, {'type': 'function_call_output',
                'call_id': 'private_wrong_identity', 'output': 'private result'}]
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 400)
                error = (await response.json())['error']
            self.assertIs(error['retryable'], False)
            self.assertIn('接续校验', error['message'])
            self.assertIn('本轮已向原生接口转交 1 次工具调用，收到 0 份配对结果', error['message'])
            self.assertIn('配对结果不代表执行成功', error['message'])
            self.assertEqual(error['transport'], {'scope': 'transport_only', 'turn': {
                'sequence': 1, 'request_read': True, 'calls_accepted': 1, 'calls_released': 1,
                'results_received': 0, 'pending_call': 'released_without_result',
                'public_final_returned': False}})
            for private in ('private', call['call_id'], 'inspect'):
                self.assertNotIn(private, json.dumps(error))
            self.assertEqual(received, [])
            async with client.post(url + '/responses', json=self.payload()) as response:
                replay = (await response.json())['error']
                self.assertEqual(replay['code'], 'web_bridge_turn_consumed_no_retry')
                self.assertNotIn('transport', replay)
                self.assertNotIn('本轮', replay['message'])
            self.assertEqual(provider.bridge.turn_sequence, 1)

    async def test_native_final_wait_timeout_keeps_received_result_distinct_from_success(self):
        received = []
        async def browser(turn):
            turn.begin(turn.key)
            received.append(await turn.invoke(turn.key, 1, 'inspect', {'value': 'x'}))
            await asyncio.Future()
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload(stream=False)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                call = (await response.json())['output'][0]
            output = {'type': 'function_call_output', 'call_id': call['call_id'],
                'output': '{"isError":true,"message":"private permission denial"}'}
            payload['input'] += [call, output]
            provider.bridge.turn.deadline = time.monotonic() + 0.1
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 408)
                error = (await response.json())['error']
            self.assertEqual(error['code'], 'web_provider_request_timeout_no_retry')
            self.assertIs(error['retryable'], False)
            self.assertIn('超时', error['message'])
            self.assertIn('本轮已向原生接口转交 1 次工具调用，收到 1 份配对结果', error['message'])
            self.assertIn('配对结果不代表执行成功', error['message'])
            progress = error['transport']['turn']
            self.assertEqual((progress['calls_released'], progress['results_received']), (1, 1))
            self.assertIsNone(progress['pending_call'])
            self.assertFalse(progress['public_final_returned'])
            self.assertEqual(received, [{'codex_function_result': output}])
            self.assertNotIn('private', json.dumps(error))
            self.assertIsNone(provider.bridge.turn)

    async def test_busy_and_pre_admission_errors_never_inherit_other_turn_progress(self):
        async def browser(turn):
            turn.begin(turn.key)
            await turn.invoke(turn.key, 1, 'inspect', {'value': 'owned'})
            return message(['done'])
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload('owned', stream=False)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                call = (await response.json())['output'][0]
            async with client.post(url + '/responses', json=self.payload('other')) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                busy_error = (await response.json())['error']
                self.assertNotIn('transport', busy_error)
                self.assertNotIn('本轮', busy_error['message'])
            self.assertEqual(provider.bridge.owner, ('fixture-thread', 'owned'))
            payload['input'] += [call, {'type': 'function_call_output',
                'call_id': call['call_id'], 'output': 'done'}]
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 200)
            previous = provider.bridge.diagnostics()['last_turn']
            for kind in ('model', 'identity', 'exception'):
                invalid = self.payload('new-' + kind)
                if kind == 'model':
                    invalid['model'] = 'unknown'
                elif kind == 'identity':
                    invalid.pop('client_metadata')
                if kind == 'exception':
                    # Even lowercase underscore-only exception text is private,
                    # not automatically an approved public error code.
                    with patch('operator_core.web_mcp_transport.WebModelProtocol',
                            side_effect=RouterError('private_token_123')):
                        async with client.post(url + '/responses', json=invalid) as response:
                            error = (await response.json())['error']
                    self.assertEqual(error['code'], 'web_provider_protocol_rejected')
                else:
                    async with client.post(url + '/responses', json=invalid) as response:
                        error = (await response.json())['error']
                self.assertNotIn('transport', error)
                self.assertNotIn('本轮', error['message'])
                self.assertIs(error['retryable'], False)
                self.assertNotIn('private_token', json.dumps(error))
                self.assertEqual(provider.bridge.diagnostics()['last_turn'], previous)
            self.assertEqual(provider.bridge.turn_sequence, 1)

    async def test_native_contract_rejections_are_specific_without_payload_or_dispatch(self):
        calls = []
        async def browser(turn):
            calls.append(True)
            return message()
        provider, url, headers = await self.create_provider(browser)
        cases = [({'tools': [{'type': 'web_search'}]}, 'unsupported_tool_type'),
            ({'input': [{'type': 'function_call_output', 'namespace': 'codex_app',
                'name': 'create_thread', 'output': 'private_history'}]}, 'named_function_output_not_registered'),
            ({'tools': [{'type': 'custom', 'name': 'private_tool'}]}, 'custom_tool_not_registered')]
        async with ClientSession(headers=headers) as client:
            for index, (changes, code) in enumerate(cases):
                async with client.post(url + '/responses', json={**self.payload(str(index)), **changes}) as response:
                    self.assertEqual(response.status, 400)
                    error = (await response.json())['error']
                self.assertEqual(error['code'], code)
                self.assertIs(error['retryable'], False)
                self.assertIn('无需重新登录', error['message'])
                self.assertNotIn('private', json.dumps(error))
                self.assertNotIn('transport', error)
        self.assertEqual(calls, [])
        self.assertEqual(provider.bridge.turn_sequence, 0)

    async def test_opaque_history_guidance_does_not_dispatch_rewrite_or_expose_history(self):
        calls = []
        async def browser(turn):
            calls.append(True)
            return message()
        provider, url, headers = await self.create_provider(browser)
        cases = [{'type': 'reasoning', 'encrypted_content': 'private_encrypted_history'},
            {'type': 'compaction', 'id': 'private_compaction_history'}]
        async with ClientSession(headers=headers) as client:
            for index, item in enumerate(cases):
                payload = self.payload('opaque-' + str(index))
                payload['input'].append(item)
                original = json.dumps(payload, ensure_ascii=False)
                async with client.post(url + '/responses', json=payload) as response:
                    self.assertEqual(response.status, 400)
                    error = (await response.json())['error']
                self.assertEqual(error['code'], 'opaque_cross_provider_context_not_supported')
                self.assertIs(error['retryable'], False)
                self.assertIn('加密历史或压缩记录', error['message'])
                self.assertIn('从第一轮就选择 Web 模型的新任务', error['message'])
                self.assertIn('原任务和历史保留', error['message'])
                self.assertIn('无需重新登录', error['message'])
                self.assertNotIn('private_', json.dumps(error))
                self.assertNotIn('transport', error)
                self.assertEqual(json.dumps(payload, ensure_ascii=False), original)
        self.assertEqual(calls, [])
        self.assertEqual(provider.bridge.turn_sequence, 0)
        self.assertIsNone(provider.bridge.turn)

    async def test_closed_previous_browser_failure_cannot_override_new_request_rejection(self):
        fail = asyncio.Event()
        async def browser(turn):
            turn.begin(turn.key)
            call = asyncio.create_task(turn.invoke(turn.key, 1, 'inspect', {'value': 'old'}))
            try:
                await fail.wait()
                raise WebBrowserHttpError(429)
            finally:
                call.cancel()
                await asyncio.gather(call, return_exceptions=True)
        provider, url, headers = await self.create_provider(browser)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=self.payload('old', stream=False)) as response:
                self.assertEqual(response.status, 200)
            fail.set()
            await asyncio.wait_for(provider.bridge.driver, 2)
            self.assertTrue(provider.bridge.turn.closed)
            invalid = self.payload('new')
            invalid['model'] = 'unknown'
            async with client.post(url + '/responses', json=invalid) as response:
                self.assertEqual(response.status, 400)
                error = (await response.json())['error']
            self.assertEqual(error['code'], 'web_explicit_route_required')
            self.assertNotIn('upstream_status', error)
            self.assertNotIn('transport', error)
            self.assertNotIn('本轮', error['message'])
            self.assertEqual(provider.bridge.turn_sequence, 1)

    async def test_browser_cleanup_failure_does_not_escape_to_the_next_request(self):
        async def browser(turn):
            turn.begin(turn.key)
            try:
                await turn.invoke(turn.key, 1, 'inspect', {'value': 'old'})
            finally:
                raise WebBrowserHttpError(429)
        provider, url, headers = await self.create_provider(browser)
        payload = self.payload('old', stream=False)
        async with ClientSession(headers=headers) as client:
            async with client.post(url + '/responses', json=payload) as response:
                call = (await response.json())['output'][0]
            payload['input'] += [call, {'type': 'function_call_output',
                'call_id': 'wrong', 'output': 'rejected'}]
            async with client.post(url + '/responses', json=payload) as response:
                self.assertEqual(response.status, 400)
                rejected = (await response.json())['error']
            self.assertEqual(rejected['code'], 'unmatched_tool_output')
            self.assertNotIn('upstream_status', rejected)
            invalid = self.payload('new')
            invalid['model'] = 'unknown'
            async with client.post(url + '/responses', json=invalid) as response:
                self.assertEqual(response.status, 400)
                error = (await response.json())['error']
            self.assertEqual(error['code'], 'web_explicit_route_required')
            self.assertNotIn('upstream_status', error)
            self.assertNotIn('transport', error)
            self.assertNotIn('本轮', error['message'])
            self.assertIsNone(provider.bridge.failure)
