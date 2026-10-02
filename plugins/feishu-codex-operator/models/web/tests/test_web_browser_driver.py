"""Real private child processes and loopback service; no live browser or model."""

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
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from test_web_model_protocol import message, make, FUNCTION
from operator_core.web_browser_driver import (WebTextBrowserDriver, WebMcpBrowserDriver, text_prompt,
    child_environment, safe_generation_progress, safe_public_turn_state, safe_public_identity_structure, safe_public_interruption, safe_prompt_mismatch_shape,
    safe_modern_identity_shape, safe_fresh_chat_control_structure,
    current_user_preview, encoded_user_json)
from operator_core.web_browser_session import WebBrowserSession
from operator_core.web_mcp_transport import WebRequestCapacityError, WebMcpEndpoint, WebMcpTurn, WebResponsesBridge
from operator_core.web_model_protocol import WebModelProtocol
from operator_core.web_responses_provider import WebResponsesProvider
import operator_web_model as service


class PromptDiagnosticTests(unittest.TestCase):
    def test_public_identity_structure_rejects_raw_values_and_unknown_fields(self):
        shape = {'role':'assistant', 'userBubbles':0, 'visibleUserBubbles':0, 'bubbleBound':None, 'renderAncestors':[],
            'groups':{name:{'present':False,'unknownFields':0,'fields':[]} for name in
                ('item','turn','entry','entryUserMessage','entryUserItem','turnUserMessage','itemParentMessage',
                 'itemNode','turnParent','entryParent','entryUserMessageNode','entryMessageNode')}}
        shape['groups']['turn'] = {'present':True,'unknownFields':1,
            'fields':[['parentMessageId','string',True,False]]}
        self.assertEqual(safe_public_identity_structure(shape), {'valid':True,**shape})
        for changed in ({**shape,'raw_id':'private'}, {**shape,'userBubbles':True},
            {**shape,'renderAncestors':[{'depth':0,'fields':[['allMessages','array',1,0,0,1,1,True]]}]},
            {**shape,'renderAncestors':[{'depth':0,'fields':[['entries','array','private',0,0,1,1,True]]}]},
            {**shape,'groups':{**shape['groups'],'account':{}}},
            {**shape,'groups':{**shape['groups'],'turn':{'present':True,'unknownFields':0,
                'fields':[['parentMessageId','private',True,False]]}}},
            {**shape,'groups':{**shape['groups'],'turn':{'present':True,'unknownFields':0,
                'fields':[['parentMessageId','string',True,False,'private']]}}}):
            self.assertEqual(safe_public_identity_structure(changed), {'valid':False})

    def test_public_turn_state_keeps_unknown_separate_and_rejects_private_fields(self):
        state = dict.fromkeys(('sourceExact', 'userIdentityExact', 'sameTurnObject', 'sameUnitTurn',
            'assistantCompleted', 'assistantFinalPhase', 'latestIdentityExact', 'sourceIdentityExact',
            'turnCompleted', 'workCompleted', 'turnIdentityListValid', 'turnBoundUserPresent',
            'turnBoundUserFirst', 'turnAssistantLast', 'turnInitialPrefixExact',
            'requestRecordPresent', 'requestDocumentExact', 'requestRootExact', 'requestArmed',
            'requestBound', 'requestInvalid', 'requestUserIdentityExact', 'requestSourceExact',
            'conversationIdentityUuid', 'conversationIdentityBounded', 'conversationIdentityExact',
            'requestTemporaryDocument', 'conversationIdentityEmpty',
            'pendingAssistantIdentityAvailable', 'pendingAssistantConversationExact', 'pendingAssistantTurnIdentityExact'))
        state.update(legacyUserRows=0, legacyAssistantRows=0, modernUserRows=1, modernAssistantRows=1,
            userSource='available', assistantSource='unavailable', sourceExact=True, userIdentityExact=True)
        self.assertEqual(safe_public_turn_state(state), {'valid': True, **state})
        for changes in ({'modernUserRows': True}, {'modernUserRows': 10001}, {'modernAssistantRows': -1},
                {'sourceExact': 'private'}, {'userSource': 'private'}, {'message_id': 'private'},
                {'content': 'private'}, {'turnCompleted': 1}):
            with self.subTest(changes=changes):
                self.assertEqual(safe_public_turn_state({**state, **changes}), {'valid': False})
        self.assertEqual(safe_public_turn_state(None), {'valid': False})

    def test_shape_accepts_only_fixed_categories_and_never_copies_text(self):
        shape = {'paragraphs': 'one', 'nodes': 'few', 'literalPastes': 'one',
            'expectedNewlines': 'many', 'renderedNewlines': 'many',
            'nodeKinds': ['app_pill', 'text', 'literal'], 'literalKinds': ['text', 'break'],
            'secondNodeKinds': [], 'paragraphCount': 1, 'expectedLines': 2,
            'lineMatches': [False],
            'innerTextExact': False, 'textContentExact': False,
            'firstExpectedEndsCR': True, 'firstMatchesWithoutCR': True,
            'firstStartsWithPrefix': True, 'firstPillMatchesName': True,
            'firstNodeMatchesTailWithSpace': False, 'firstNodeMatchesTailNoSpace': False,
            'firstNodeStartsWithSpace': True, 'firstNodeStartsWithNbsp': False,
            'firstNodeMatchesTailWithNbsp': False,
            'firstNodeMatchesTailWithTwoSpaces': False,
            'firstMatchesWithoutSeparator': False,
            'firstMatchesWithNbspSeparator': False}
        self.assertEqual(safe_prompt_mismatch_shape(shape), {'valid': True, **shape})
        self.assertEqual(safe_prompt_mismatch_shape({**shape, 'body': 'private'}), {'valid': False})
        self.assertEqual(safe_prompt_mismatch_shape({**shape, 'nodeKinds': ['private']}), {'valid': False})
        self.assertEqual(safe_prompt_mismatch_shape({**shape, 'innerTextExact': 'true'}), {'valid': False})

    def test_modern_identity_shape_exports_only_fixed_flags(self):
        row = {'keyPattern': True, 'visible': True, 'hidden': False,
            'idsBounded': True, 'idsCount': 2, 'allIdsUuid': True,
            'allIdsEqual': False, 'selectedCount': 1, 'selectedUuid': True,
            'selectedFirst': False, 'selectedLast': True, 'selectedAny': True}
        shape = {'assistantRows': 1, 'rows': [row]}
        self.assertEqual(safe_modern_identity_shape(shape), {'valid': True, **shape})
        self.assertEqual(safe_modern_identity_shape({'assistantRows': 1,
            'rows': [{**row, 'id': 'private'}]}), {'valid': False})
        self.assertEqual(safe_modern_identity_shape({'assistantRows': 1,
            'rows': [{**row, 'idsCount': 10}]}), {'valid': False})

    def test_fresh_chat_control_structure_rejects_page_content(self):
        shape = {'legacyLinks': 'one', 'legacyRootHref': 'yes',
            'legacyLabel': 'yes', 'legacyEnabled': 'yes',
            'navButtons': 'multiple', 'namedButtons': 'one',
            'buttonType': 'absent', 'buttonDisabled': 'no',
            'buttonAriaDisabled': 'no', 'buttonHref': 'absent',
            'buttonTarget': 'absent', 'buttonHiddenAncestor': 'no'}
        self.assertEqual(safe_fresh_chat_control_structure(shape), {'valid': True, **shape})
        self.assertEqual(safe_fresh_chat_control_structure({**shape, 'text': 'PRIVATE'}), {'valid': False})
        self.assertEqual(safe_fresh_chat_control_structure({**shape, 'buttonType': 'PRIVATE'}), {'valid': False})



class BrowserDriverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'profile').mkdir()
        self.settings = {'electron': sys.executable, 'profile_directory': str(self.root / 'profile'),
            'session_partition': 'persist:operator-test', 'timeout_ms': 10000, 'window_mode': 'visible'}
        desktop = patch('operator_core.web_browser_driver.desktop_session_state', return_value='unlocked')
        self.desktop = desktop.start()
        self.addCleanup(desktop.stop)
        session_desktop = patch('operator_core.web_browser_session.desktop_session_state', return_value='unlocked')
        session_desktop.start()
        self.addCleanup(session_desktop.stop)

    def payload(self, turn='first'):
        return {'model': service.SLUG, 'input': [{'role': 'user', 'content': 'exact 中文\r\n'}],
            'reasoning': {'effort': 'high'}, 'stream': False,
            'client_metadata': {'thread_id': 'private-fixture', 'turn_id': turn}}

    def turn(self):
        return WebMcpTurn(WebModelProtocol(service.text_route(), self.payload()))

    def spawn_fixture(self, program, seen):
        original = asyncio.create_subprocess_exec
        async def spawn(*args, **kwargs):
            path = Path(args[-1])
            config = json.loads(path.read_text(encoding='utf-8'))
            seen.append(config)
            # This substitution belongs only to the test; production accepts no
            # caller script, executable arguments or page operation.
            return await original(sys.executable, '-u', '-c', program, str(path), **kwargs)
        return patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec', spawn)

    async def test_one_process_exact_parts_and_ephemeral_request_cleanup(self):
        driver = WebTextBrowserDriver(self.settings, self.root / 'requests')
        public = message(['  中文😀\r\n', '', 'a_b\n'])
        events = [{'operator_web': 1, 'kind': 'dispatch_started'}, {'operator_web': 1,
            'kind': 'completed', 'model': 'gpt-5.6-sol', 'effortIndex': 2, 'publicMessage': public}]
        program = 'import json\nprint()\n' + '\n'.join('print(' + repr(json.dumps(e)) + ')' for e in events)
        seen = []
        with self.spawn_fixture(program, seen):
            self.assertEqual(await driver(self.turn()), public)
        self.assertEqual(len(seen), 1)
        encoded = seen[0]['text'].split('BEGIN_COMPLETE_RESPONSES_REQUEST_JSON ', 1)[1]
        self.assertEqual(json.loads(encoded.rsplit(' END_COMPLETE_RESPONSES_REQUEST_JSON', 1)[0])
            ['input'][0]['content'], 'exact 中文\r\n')
        self.assertEqual(seen[0]['parentPid'], os.getpid())
        self.assertEqual(list((self.root / 'requests').iterdir()), [])
        self.assertEqual(driver.status()['completed'], 1)
        self.assertEqual(driver.status()['dispatches'], 1)
        self.assertNotIn('中文', json.dumps(driver.status(), ensure_ascii=False))

    async def test_native_disconnect_closes_owned_child_and_consumes_turn(self):
        driver = WebTextBrowserDriver(self.settings, self.root / 'requests')
        program = '''import json,sys,time
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
print(json.dumps({'operator_web':1,'kind':'dispatch_started'}),flush=True)
while not Path(c['cancelFile']).exists(): time.sleep(.02)
assert Path(c['cancelFile']).read_bytes()==b'cancel\\n'
Path(sys.argv[1]).with_name('stopped.fixture').write_bytes(b'stopped')
raise SystemExit(1)
'''
        # Preserve the fake child's separate observation outside the driver's
        # ephemeral directory before its normal cleanup runs.
        program = program.replace("Path(sys.argv[1]).with_name('stopped.fixture')",
            'Path(' + repr(str(self.root / 'child-stopped')) + ')')
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver, timeout=20)
        provider = WebResponsesProvider(bridge)
        base = await provider.start()
        self.addAsyncCleanup(provider.stop)
        seen = []
        with self.spawn_fixture(program, seen):
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                task = asyncio.create_task(client.post(base + '/responses', json=self.payload()))
                async def started():
                    while driver.dispatches != 1: await asyncio.sleep(.02)
                await asyncio.wait_for(started(), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                async def stopped():
                    while driver.active: await asyncio.sleep(.02)
                await asyncio.wait_for(stopped(), 4)
                self.assertEqual((self.root / 'child-stopped').read_bytes(), b'stopped')
                async with client.post(base + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
        self.assertEqual(len(seen), 1)
        self.assertEqual(driver.cancelled, 1)
        self.assertEqual(list((self.root / 'requests').iterdir()), [])

    async def test_optional_summary_request_kept_with_public_final_only(self):
        public = message(['公开答案  \r\n'])
        program = '\n'.join('print(' + repr(json.dumps(event)) + ')' for event in (
            {'operator_web': 1, 'kind': 'dispatch_started'}, {'operator_web': 1,
                'kind': 'completed', 'model': 'gpt-5.6-sol', 'effortIndex': 2,
                'publicMessage': public}))
        for index, summary in enumerate((None, 'auto', 'concise', 'detailed')):
            with self.subTest(summary=summary):
                payload = self.payload(str(index))
                payload['reasoning']['summary'] = summary
                original = deepcopy(payload)
                protocol = WebModelProtocol(service.text_route(), payload)
                driver = WebTextBrowserDriver(self.settings, self.root / str(index))
                seen = []
                with self.spawn_fixture(program, seen):
                    final = await driver(WebMcpTurn(protocol))
                encoded = seen[0]['text'].split('BEGIN_COMPLETE_RESPONSES_REQUEST_JSON ', 1)[1]
                encoded = encoded.rsplit(' END_COMPLETE_RESPONSES_REQUEST_JSON', 1)[0]
                self.assertEqual(json.loads(encoded), protocol.request())
                self.assertEqual(json.loads(encoded)['reasoning'], payload['reasoning'])
                response, _ = protocol.complete_public_message('resp_summary_fixture', final)
                self.assertEqual([item['type'] for item in response['output']], ['message'])
                self.assertEqual(response['output'][0]['content'][0]['text'], public['content']['parts'][0])
                self.assertEqual(payload, original)
        driver = WebTextBrowserDriver(self.settings, self.root / 'invalid-summary')
        for summary in ('unknown', 1, {}, []):
            payload = self.payload()
            payload['reasoning']['summary'] = summary
            with patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
                with self.assertRaisesRegex(ValueError, 'web_text_reasoning_summary_invalid'):
                    await driver(WebMcpTurn(WebModelProtocol(service.text_route(), payload)))
                spawn.assert_not_called()

    async def test_explicit_public_sources_reach_native_as_links_without_search_calls(self):
        driver = WebTextBrowserDriver({**self.settings, 'citation_mode': 'markdown_links_v1'},
            self.root / 'citation-requests')
        marker = '\ue200cite\ue202turn12search0\ue201'
        public = message(['🪐说明' + marker])
        public['public_references'] = [{'type': 'grouped_webpages', 'matched_text': marker,
            'start_idx': 3, 'end_idx': 3 + len(marker),
            'items': [{'title': 'Public source', 'url': 'https://example.com/a_b'}]}]
        program = '\n'.join('print(' + repr(json.dumps(event)) + ')' for event in (
            {'operator_web': 1, 'kind': 'dispatch_started'}, {'operator_web': 1,
                'kind': 'completed', 'model': 'gpt-5.6-sol', 'effortIndex': 2, 'publicMessage': public}))
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver,
            citation_mode='markdown_links_v1')
        provider = WebResponsesProvider(bridge)
        base = await provider.start()
        self.addAsyncCleanup(provider.stop)
        seen = []
        with self.spawn_fixture(program, seen):
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                async with client.post(base + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 200)
                    value = await response.json()
        self.assertEqual(value['output'][0]['content'][0]['text'],
            '🪐说明[Public source](<https://example.com/a_b>)')
        self.assertEqual([item['type'] for item in value['output']], ['message'])
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0]['includeCitations'])
        self.assertNotIn('https://example.com', json.dumps(driver.status()))

    async def test_locked_desktop_fails_before_browser_with_actionable_native_error(self):
        driver = WebTextBrowserDriver(self.settings, self.root / 'requests')
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
        provider = WebResponsesProvider(bridge)
        base = await provider.start()
        self.addAsyncCleanup(provider.stop)
        self.desktop.return_value = 'locked'
        with patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                async with client.post(base + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                    error = (await response.json())['error']
                    self.assertEqual(error['code'], 'web_desktop_locked_before_dispatch')
                    self.assertIn('解锁', error['message'])
                self.desktop.return_value = 'unlocked'
                async with client.post(base + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)  # No automatic replay after unlock.
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            spawn.assert_not_called()
        self.assertEqual(driver.dispatches, 0)
        self.assertEqual(list((self.root / 'requests').iterdir()), [])

    async def test_failed_or_ambiguous_child_never_supplies_answer_or_retries(self):
        for index, program in enumerate((
                "print('not-json')", "print('{}')", "raise SystemExit(1)",
                "print('{\"operator_web\":1,\"kind\":\"dispatch_started\"}')\n" * 2)):
            with self.subTest(index=index):
                driver = WebTextBrowserDriver(self.settings, self.root / str(index))
                seen = []
                with self.spawn_fixture(program, seen), self.assertRaises(ValueError):
                    await driver(self.turn())
                self.assertEqual(len(seen), 1)
                self.assertEqual(driver.completed, 0)
                self.assertFalse(driver.active)

    async def test_http_error_identity_cannot_be_fabricated_or_followed_by_success(self):
        for variant in ('no_dispatch', 'no_network', 'different_status', 'completed_after_rejection'):
            with self.subTest(variant=variant):
                driver = WebTextBrowserDriver(self.settings, self.root / ('http-unbound-' + variant))
                events = [] if variant == 'no_dispatch' else [{'operator_web':1, 'kind':'dispatch_started'}]
                if variant != 'no_network':
                    events.append({'operator_web':1, 'kind':'model_network_state', 'phase':'response_started',
                        'status':403, 'error':None})
                if variant == 'completed_after_rejection':
                    events.append({'operator_web':1, 'kind':'completed', 'model':'gpt-5.6-sol',
                        'effortIndex':2, 'publicMessage':message()})
                else:
                    events.append({'operator_web':1, 'kind':'failed', 'sent':True,
                        'error':'web_model_http_rejected_no_retry', 'upstreamStatus':401 if variant == 'different_status' else 403})
                program = '\n'.join('print(' + repr(json.dumps(e)) + ')' for e in events)
                if variant != 'completed_after_rejection': program += '\nraise SystemExit(1)'
                bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                provider = WebResponsesProvider(bridge)
                url = await provider.start()
                self.addAsyncCleanup(provider.stop)
                seen = []
                with self.spawn_fixture(program, seen):
                    async with ClientSession(headers={'Authorization':'Bearer ' + provider.token}) as client:
                        async with client.post(url + '/responses', json=self.payload()) as response:
                            self.assertEqual(response.status, 400)
                            self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                            error = (await response.json())['error']
                self.assertEqual(error['code'], 'web_browser_driver_failed_no_retry')
                self.assertNotIn('upstream_status', error)
                self.assertEqual(driver.completed, 0)
                self.assertEqual(len(seen), 1)

    async def test_failure_diagnostics_keep_only_bound_plugin_codes(self):
        for index, code in enumerate(('web_profile_already_owned', 'web_private_secret_value')):
            driver = WebTextBrowserDriver(self.settings, self.root / ('diagnostic-' + str(index)))
            event = {'operator_web': 1, 'kind': 'failed', 'stage': 'configuration',
                'error': code, 'private': 'DO_NOT_RETAIN'}
            program = 'print(' + repr(json.dumps(event)) + ')'
            with self.spawn_fixture(program, []), self.assertRaises(ValueError):
                await driver(self.turn())
            failures = [event for event in driver.events if event['kind'] == 'failed']
            self.assertEqual([event['code'] for event in failures], [code if index == 0 else None])
            self.assertNotIn('DO_NOT_RETAIN', json.dumps(driver.status()))

    async def test_fresh_chat_control_event_is_sanitized_on_both_browser_paths(self):
        shape = {'legacyLinks': 'zero', 'legacyRootHref': 'unknown',
            'legacyLabel': 'unknown', 'legacyEnabled': 'unknown',
            'navButtons': 'multiple', 'namedButtons': 'zero',
            'buttonType': 'unknown', 'buttonDisabled': 'unknown',
            'buttonAriaDisabled': 'unknown', 'buttonHref': 'unknown',
            'buttonTarget': 'unknown', 'buttonHiddenAncestor': 'unknown',
            'pageText': 'DO_NOT_RETAIN'}
        value = {'operator_web': 1, 'kind': 'fresh_chat_control_structure',
            'stage': 'load_fresh_page', 'shape': shape}
        driver = WebTextBrowserDriver(self.settings, self.root / 'fresh-chat-control-diagnostic')
        program = 'print(' + repr(json.dumps(value)) + ')\nraise SystemExit(1)'
        with self.spawn_fixture(program, []), self.assertRaises(ValueError):
            await driver(self.turn())
        self.assertEqual([event['shape'] for event in driver.events
            if event['kind'] == 'fresh_chat_control_structure'], [{'valid': False}])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(driver.status()))
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
            self.root / 'fresh-chat-session-diagnostic')
        session = WebBrowserSession(base)
        self.addAsyncCleanup(session.close)
        session.event(value, {})
        self.assertEqual(base.events[-1]['shape'], {'valid': False})
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(base.status()))

    async def test_public_turn_diagnostics_are_sanitized_by_both_driver_lifecycles(self):
        state = dict.fromkeys(('sourceExact', 'userIdentityExact', 'sameTurnObject', 'sameUnitTurn',
            'assistantCompleted', 'assistantFinalPhase', 'latestIdentityExact', 'sourceIdentityExact',
            'turnCompleted', 'workCompleted', 'turnIdentityListValid', 'turnBoundUserPresent',
            'turnBoundUserFirst', 'turnAssistantLast', 'turnInitialPrefixExact',
            'requestRecordPresent', 'requestDocumentExact', 'requestRootExact', 'requestArmed',
            'requestBound', 'requestInvalid', 'requestUserIdentityExact', 'requestSourceExact',
            'conversationIdentityUuid', 'conversationIdentityBounded', 'conversationIdentityExact',
            'requestTemporaryDocument', 'conversationIdentityEmpty',
            'pendingAssistantIdentityAvailable', 'pendingAssistantConversationExact', 'pendingAssistantTurnIdentityExact'))
        state.update(legacyUserRows=0, legacyAssistantRows=0, modernUserRows=1, modernAssistantRows=1,
            userSource='available', assistantSource='unavailable', sourceExact=True, userIdentityExact=True)
        for invalid in (False, True):
            value = {'kind': 'public_turn_state', 'operator_web': 1, 'stage': 'wait_public_final',
                'state': {**state, **({'id': 'DO_NOT_RETAIN'} if invalid else {})}}
            driver = WebTextBrowserDriver(self.settings, self.root / ('turn-diagnostic-' + str(invalid)))
            with self.spawn_fixture('print(' + repr(json.dumps(value)) + ')', []), self.assertRaises(ValueError):
                await driver(self.turn())
            expected = {'valid': False} if invalid else {'valid': True, **state}
            self.assertEqual([e['state'] for e in driver.events if e['kind'] == 'public_turn_state'], [expected])
            base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                self.root / ('turn-session-diagnostic-' + str(invalid)))
            session = WebBrowserSession(base)
            self.addAsyncCleanup(session.close)
            session.event(value, {})
            self.assertEqual(base.events[-1]['state'], expected)
            self.assertNotIn('DO_NOT_RETAIN', json.dumps(driver.status()))
            self.assertNotIn('DO_NOT_RETAIN', json.dumps(base.status()))

    async def test_identity_structure_is_sanitized_in_both_browser_lifecycles(self):
        shape = {'role':'assistant','userBubbles':0,'visibleUserBubbles':0,'bubbleBound':None, 'renderAncestors':[],
            'groups':{name:{'present':False,'unknownFields':0,'fields':[]} for name in
                ('item','turn','entry','entryUserMessage','entryUserItem','turnUserMessage','itemParentMessage',
                 'itemNode','turnParent','entryParent','entryUserMessageNode','entryMessageNode')}}
        for invalid in (False,True):
            value = {'kind':'public_identity_structure','operator_web':1,'stage':'wait_public_final',
                'shape':{**shape,**({'id':'DO_NOT_RETAIN'} if invalid else {})}}
            driver = WebTextBrowserDriver(self.settings,self.root/('structure-diagnostic-'+str(invalid)))
            with self.spawn_fixture('print('+repr(json.dumps(value))+')',[]),self.assertRaises(ValueError):
                await driver(self.turn())
            expected = {'valid':False} if invalid else {'valid':True,**shape}
            self.assertEqual([e['shape'] for e in driver.events if e['kind']=='public_identity_structure'],[expected])
            base = WebTextBrowserDriver({**self.settings,'window_mode':'background'},
                self.root/('structure-session-'+str(invalid)))
            session = WebBrowserSession(base)
            self.addAsyncCleanup(session.close)
            session.event(value,{})
            self.assertEqual(base.events[-1]['shape'],expected)
            self.assertNotIn('DO_NOT_RETAIN',json.dumps(driver.status()))
            self.assertNotIn('DO_NOT_RETAIN',json.dumps(base.status()))

    async def test_user_binding_diagnostics_keep_only_bounded_counts(self):
        driver = WebTextBrowserDriver(self.settings, self.root / 'binding-diagnostic')
        event = {'operator_web': 1, 'kind': 'public_user_binding', 'shape': {
            'exact': False, 'supportedTextShape': True, 'appSeparatorOnly': True, 'sourceLength': 12,
            'promptLength': 10, 'firstDifference': 7, 'sharedSuffix': 3,
            'prefix': 'DO_NOT_RETAIN', 'sourceNbsp': True, 'promptNbsp': -2,
            'sourceSpaces': 1024 * 1024 + 1, 'promptSpaces': 'DO_NOT_RETAIN'}}
        program = 'print(' + repr(json.dumps(event)) + ')'
        with self.spawn_fixture(program, []), self.assertRaises(ValueError):
            await driver(self.turn())
        shapes = [event['shape'] for event in driver.events if event['kind'] == 'public_user_binding']
        self.assertEqual(shapes, [{'exact': False, 'supportedTextShape': True, 'appSeparatorOnly': True,
            'sourceLength': 12, 'promptLength': 10, 'firstDifference': 7}])
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
            self.root / 'binding-session-diagnostic')
        session = WebBrowserSession(base)
        self.addAsyncCleanup(session.close)
        session.event(event, {})
        self.assertEqual(base.events[-1]['shape'], shapes[0])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(base.status()))
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(driver.status()))

    async def test_failed_effort_range_diagnostic_retains_only_fixed_shape(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
            self.root / 'effort-range-diagnostic')
        session = WebBrowserSession(base)
        self.addAsyncCleanup(session.close)
        value = {'kind': 'effort_range_unavailable', 'stage': 'select_effort',
            'containerCount': 'one', 'sliderCount': 'one', 'statePresent': 'yes',
            'newContainerTotal': 'one', 'newContainerVisible': 'one',
            'min': 0, 'max': 5, 'now': 4, 'locked': 'yes',
            'globalSliderTotal': 'one', 'globalSliderVisible': 'one',
            'globalMin': 0, 'globalMax': 5, 'globalNow': 4,
            'globalSliderRect': 'yes', 'globalSliderHidden': 'no',
            'globalSliderInert': 'no', 'globalSliderAriaHidden': 'no',
            'globalSliderClosedMenu': 'no', 'globalSliderInNewContainer': 'yes',
            'ownerMenuitem': 'yes', 'ownerMenu': 'yes', 'sameMenuAsChooser': 'yes',
            'generationMatches': 'yes', 'proLabel': 'yes', 'proHeader': 'yes',
            'private': 'DO_NOT_RETAIN'}
        session.event(value, {})
        event = base.events[-1]
        self.assertEqual(event['kind'], 'effort_range_unavailable')
        self.assertEqual(event['max'], 5)
        self.assertEqual(event['locked'], 'yes')
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(base.status()))
        with self.assertRaisesRegex(ValueError, 'web_effort_range_diagnostic_invalid'):
            session.event({**value, 'max': 'PRIVATE PAGE TEXT'}, {})
        self.assertEqual(len(base.events), 1)

    async def test_bound_and_forced_call_reject_before_process_and_retain_json(self):
        request = self.payload()
        request['instructions'] = 'spaces  \n中文'
        snapshot = deepcopy(request)
        value = text_prompt(request)
        encoded = value.split('BEGIN_COMPLETE_RESPONSES_REQUEST_JSON ', 1)[1].rsplit(' END_COMPLETE_RESPONSES_REQUEST_JSON', 1)[0]
        self.assertEqual(json.loads(encoded), request)
        self.assertEqual(request, snapshot)
        for choice in ('required', {'type': 'function', 'name': 'exec'}):
            with self.assertRaisesRegex(ValueError, 'web_text_tool_choice_unsupported'):
                text_prompt({**request, 'tool_choice': choice})
        with self.assertRaisesRegex(ValueError, 'web_text_input_too_large_no_retry'):
            text_prompt({**request, 'instructions': 'a' * 65536})
        driver = WebTextBrowserDriver(self.settings, self.root / 'requests')
        payload = self.payload()
        payload['input'][0]['content'] = 'x' * 65536
        with patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
            with self.assertRaisesRegex(ValueError, 'web_text_input_too_large_no_retry'):
                await driver(WebMcpTurn(WebModelProtocol(service.text_route(), payload)))
            spawn.assert_not_called()
        original_read = Path.read_bytes
        surface = driver.host.with_name('web_browser_surface.cjs')
        def changed_surface(path):
            return original_read(path) + (b'\n// changed after binding' if path == surface else b'')
        with patch.object(Path, 'read_bytes', changed_surface), \
                patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
            with self.assertRaisesRegex(ValueError, 'web_browser_source_changed'):
                await driver(self.turn())
            spawn.assert_not_called()

    async def test_text_json_encoding_prevents_literal_links_and_preserves_values(self):
        request = self.payload()
        request['instructions'] = 'https://example.com/a_b?q=中文😀 www.example.com a@example.com `x` [x] <tag> " \\ \r\n'
        request['metadata'] = {'@_/`*[]': [None, True, False, 3.14, -4, 2e-7, '\u2028\u00a0\x00']}
        original = deepcopy(request)
        value = text_prompt(request)
        encoded = value.split('BEGIN_COMPLETE_RESPONSES_REQUEST_JSON ', 1)[1].rsplit(' END_COMPLETE_RESPONSES_REQUEST_JSON', 1)[0]
        self.assertEqual(json.loads(encoded), original)
        self.assertEqual(request, original)
        for literal in ('https://', 'www.', '@example', '<tag>', '`x`', 'a_b'):
            self.assertNotIn(literal, value)
        self.assertTrue(value.isascii())
        with self.assertRaisesRegex(ValueError, 'web_text_input_too_large_no_retry'):
            text_prompt({**request, 'instructions': '/' * 12000})
        with self.assertRaises(UnicodeEncodeError):
            text_prompt({**request, 'instructions': '\ud800'})

    async def test_bounded_service_status_stop_and_no_state_reuse(self):
        settings = self.root / 'settings.json'
        settings.write_text('{"browser_lifecycle":"per_turn"}')
        state = self.root / 'service'
        class FakeDriver:
            config = {'timeoutMs': 10000}
            def status(self): return {'active': False, 'mcp_listener': False}
            async def __call__(self, turn):
                turn.begin(turn.key)
                return message(['public fixture'])
        with patch.object(service, 'WebTextBrowserDriver', return_value=FakeDriver()):
            task = asyncio.create_task(service.serve(settings, state, 60))
            async def ready():
                while not (state / 'status.json').exists(): await asyncio.sleep(.02)
            await asyncio.wait_for(ready(), 3)
            session, health = await asyncio.to_thread(service.live_status, state)
            mcp=health.pop('mcp')
            self.assertRegex(mcp.pop('generation'),r'^[0-9a-f]{32}$')
            self.assertEqual(mcp,{'events':[],'eventsDropped':0,'eventsTotal':0,'methods':{},'requests':0,
                'session_pool':{'limit':64,'size':0,'busy':0,'reclaimed':0,'expired':0}})
            self.assertEqual(health, {'ready': True, 'active': False, 'requests': 0,
                'state': 'ready', 'accepting_requests': True,
                'transport': {'scope': 'transport_only', 'active_turn': None, 'last_turn': None}})
            async with ClientSession(headers={'Authorization': 'Bearer ' + session['token']}) as client:
                async with client.post(session['base_url'] + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['output'][0]['content'][0]['text'], 'public fixture')
            service.write_json(state / 'stop.json', {'instance': session['instance']})
            await asyncio.wait_for(task, 3)
            self.assertEqual(service.read_json(state / 'status.json')['state'], 'stopped')
            with self.assertRaises(Exception): await asyncio.to_thread(service.live_status, state)
            with self.assertRaisesRegex(ValueError, 'web_private_directory_must_be_new'):
                await service.serve(settings, state, 60)

    async def test_health_retains_diagnostics_above_four_kib_and_rejects_over_bound_once(self):
        from aiohttp import web
        body = b''
        calls = []
        async def health(request):
            calls.append(request.path)
            self.assertEqual(request.headers.get('Authorization'), 'Bearer ' + 't' * 43)
            return web.Response(body=body, content_type='application/json')
        app = web.Application()
        app.router.add_get('/health', health)
        runner = web.AppRunner(app)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        state = self.root / 'health-bound'
        state.mkdir()
        service.write_json(state / 'session.json', {'version': 1, 'instance': 'a' * 32,
            'base_url': f'http://127.0.0.1:{port}/v1', 'token': 't' * 43})
        for size in (5000, 65536, 65537):
            with self.subTest(size=size):
                prefix = b'{"ready":true,"diagnostics":"'
                body = prefix + b'x' * (size - len(prefix) - 2) + b'"}'
                before = len(calls)
                if size <= 65536:
                    _, value = await asyncio.to_thread(service.live_status, state)
                    self.assertEqual(value, json.loads(body))
                else:
                    with self.assertRaisesRegex(ValueError, 'web_service_health_too_large'):
                        await asyncio.to_thread(service.live_status, state)
                self.assertEqual(len(calls), before + 1)

    def test_long_wait_is_explicit_mcp_only_and_defaults_stay_unchanged(self):
        endpoint = WebMcpEndpoint()
        connector = {'id': 'plugin:asdk_app_' + 'a' * 32, 'name': 'Operator fixture'}
        defaults = {k:v for k,v in self.settings.items() if k != 'timeout_ms'}
        text_driver = WebTextBrowserDriver(defaults, self.root / 'text-default')
        mcp_driver = WebMcpBrowserDriver(defaults, self.root / 'mcp-default', endpoint=endpoint, connector=connector)
        self.assertEqual(text_driver.config['timeoutMs'], 120000)
        self.assertEqual(mcp_driver.config['timeoutMs'], 120000)
        self.assertNotIn('mcpContinuation', text_driver.config)
        self.assertIs(mcp_driver.config['mcpContinuation'], True)
        for timeout in (10000, 180000, 600000, 600001, True):
            with self.subTest(timeout=timeout):
                settings = {**self.settings, 'timeout_ms': timeout}
                work = self.root / ('timeout-' + str(timeout))
                if type(timeout) is int and timeout <= 600000:
                    driver = WebMcpBrowserDriver(settings, work, endpoint=endpoint, connector=connector)
                    self.assertEqual(driver.config['timeoutMs'], timeout)
                else:
                    with self.assertRaisesRegex(ValueError, 'web_timeout_invalid'):
                        WebMcpBrowserDriver(settings, work, endpoint=endpoint, connector=connector)
        with self.assertRaisesRegex(ValueError, 'web_timeout_invalid'):
            WebTextBrowserDriver({**self.settings, 'timeout_ms': 600000}, self.root / 'text-long')

    def test_child_environment_excludes_credentials_and_injection_switches(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'native', 'ELECTRON_RUN_AS_NODE': '1',
                'NODE_OPTIONS': '--inspect', 'SOME_SECRET': 'secret', 'OPERATOR_WEB_KEY': 'local'}):
            env = child_environment()
            self.assertFalse({'OPENAI_API_KEY', 'ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS',
                'SOME_SECRET', 'OPERATOR_WEB_KEY'} & env.keys())

    async def test_mcp_browser_child_waits_for_exact_native_result_without_local_begin(self):
        # A real private child speaks MCP over loopback. The native caller below
        # is synthetic: no model, browser, tunnel or file tool is executed.
        for index, (wire_protocol, native_output) in enumerate((version, result)
                for version in ('mcp_indexed_request_v1', 'mcp_catalog_pages_v2', 'mcp_context_records_v3')
                for result in ('exact 中文😀\r\na_b  \n', '{"error":"permission_denied","detail":"未执行"}',
                    '{"exit_code":1,"output":"ParserError: python - <<\'PY\'\\r\\n重定向运算符后缺少文件规范。"}')):
            with self.subTest(native_output=native_output, wire_protocol=wire_protocol):
                call_mode = 'structured_call_v1' if wire_protocol != 'mcp_indexed_request_v1' else 'text_v1'
                endpoint = WebMcpEndpoint(begin_result_mode='structured_begin_v1', indexed_protocol=wire_protocol,
                    call_result_mode=call_mode)
                url = await endpoint.start()
                self.addAsyncCleanup(endpoint.stop)
                connector = {'id': 'plugin:asdk_app_' + 'a' * 32, 'name': 'Operator fixture'}
                driver = WebMcpBrowserDriver(self.settings, self.root / ('mcp-' + str(index)),
                    endpoint=endpoint, connector=connector, user_preview_mode='last_source_user_v1')
                payload = {**self.payload(str(index)), 'tools': [FUNCTION],
                    'reasoning': {'effort': 'high', 'summary': 'detailed'}}
                shell = 'powershell' if index % 2 == 0 else 'bash'
                payload['input'].insert(0, {'role': 'user', 'content':
                    '<environment_context>\r\n<cwd>C:/fixture/中文 原样</cwd>\r\n'
                    '<shell>' + shell + '</shell>\r\n</environment_context>'})
                if index % 2 == 0:
                    payload['input'][-1]['content'] = [{'type': 'input_text', 'text': '  中文😀\r\n'},
                        {'type': 'input_text', 'text': ''}, {'type': 'input_text', 'text': 'a_b \\n'}]
                route = make(payload, reasoning_summary=True).route
                bridge = WebResponsesBridge(route, endpoint, driver, timeout=20)
                provider = WebResponsesProvider(bridge)
                base = await provider.start()
                self.addAsyncCleanup(provider.stop)
                program = '''import json,sys
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
envelope=json.loads(c['text'].split('BEGIN_MCP_CONTINUATION_JSON ',1)[1].rsplit(' END_MCP_CONTINUATION_JSON',1)[0])
transport=envelope['mcp_transport']
assert envelope['current_user_preview']=={'source_input_index':len(EXPECTED_SOURCE_INPUT)-1,
 'source_message':EXPECTED_SOURCE_INPUT[-1]}
opener=build_opener(ProxyHandler({}))
session=None
def rpc(number,method,params):
 global session
 headers={'Content-Type':'application/json'}
 if session: headers['Mcp-Session-Id']=session
 data=json.dumps({'jsonrpc':'2.0','id':number,'method':method,'params':params}).encode('utf8')
 with opener.open(Request(URL,data=data,headers=headers),timeout=10) as response:
  session=response.headers.get('Mcp-Session-Id',session)
  result=json.load(response)
 assert 'error' not in result
 return result['result']
rpc(1,'initialize',{'protocolVersion':'2025-03-26'})
print(json.dumps({'operator_web':1,'kind':'dispatch_started'}),flush=True)
number=1
def section(key):
 global number
 fragments=[];entries=[];records=[];pages=0
 while key:
  number+=1
  result=rpc(number,'tools/call',{'name':transport['begin_tool'],'arguments':{'turn_key':key}})
  page=result['structuredContent'] if 'structuredContent' in result else json.loads(result['content'][0]['text'])
  assert page['index']==pages;pages+=1
  if 'records' in page:records.extend(page['records'])
  elif 'entries' in page:entries.extend(page['entries'])
  else:fragments.append(page['json_fragment'])
  key=page['next_read_key']
 if records:
  assert all(r['encoding']=='json' for r in records)
  assert [r['record_index'] for r in records]==list(range(len(records)))
  values=[r['value'] for r in records];first=values[0]
  assert first['input_format']=='array' and first['input_count']==len(values)-1
  assert [r['request_input_index'] for r in values[1:]]==list(range(len(values)-1))
  request=first['value'];request['input']=[r['value'] for r in values[1:]]
  return {'request':request,'tools_present':first['tools_present'],'tool_count':first['tool_count']},page
 return (entries if entries else json.loads(''.join(fragments))),page
context,last=section(transport['turn_key'])
catalog,_=section(last['catalog_read_key'])
schema,_=section(catalog[0]['schema_read_key'])
request=context['request'];request['tools']=[schema['request_tool']]
assert envelope['protocol']==EXPECTED_PROTOCOL and 'request' not in envelope
assert request==EXPECTED_REQUEST
assert request['input']==EXPECTED_SOURCE_INPUT
assert c['autoSelectConnector'] is True
result=rpc(number+1,'tools/call',{'name':transport['call_tool'],'arguments':{'turn_key':transport['turn_key'],'name':catalog[0]['name'],'arguments':{'value':'source_a_b\\r\\n中文'}}})
assert ('structuredContent' in result)==(EXPECTED_CALL_MODE=='structured_call_v1')
if EXPECTED_CALL_MODE=='structured_call_v1':
 assert result['content']==[] and result['isError'] is False
 original=result['structuredContent']['codex_function_result']
else:
 original=json.loads(result['content'][0]['text'])['codex_function_result']
assert original['output']==EXPECTED
assert set(original)=={'type','call_id','output'}
public=PUBLIC
public['content']['parts']=[original['output']]
print(json.dumps({'operator_web':1,'kind':'completed','model':'gpt-5.6-sol','effortIndex':2,'publicMessage':public}),flush=True)
'''
                expected_request = WebModelProtocol(route, payload).request()
                program = ('URL=' + repr(url) + '\nEXPECTED=' + repr(native_output) + '\nEXPECTED_PROTOCOL=' + repr(wire_protocol)
                    + '\nEXPECTED_CALL_MODE=' + repr(call_mode)
                    + '\nEXPECTED_REQUEST=' + repr(expected_request) + '\nEXPECTED_SOURCE_INPUT=' + repr(payload['input'])
                    + '\nPUBLIC=' + repr(message()) + '\n' + program)
                seen = []
                async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                    with self.spawn_fixture(program, seen):
                        async with client.post(base + '/responses', json=payload) as response:
                            self.assertEqual(response.status, 200)
                            call_response = await response.json()
                        call = call_response['output'][0]
                        self.assertEqual(call['type'], 'function_call')
                        self.assertEqual(call['name'], 'inspect')
                        self.assertEqual(json.loads(call['arguments']), {'value': 'source_a_b\r\n中文'})
                        self.assertEqual(endpoint.turn.calls, 1)
                        self.assertEqual(endpoint.turn.results, 0)
                        payload['input'] += [call, {'type': 'function_call_output',
                            'call_id': call['call_id'], 'output': native_output}]
                        async with client.post(base + '/responses', json=payload) as response:
                            self.assertEqual(response.status, 200)
                            final = await response.json()
                self.assertEqual(final['output'][0]['content'][0]['text'], native_output)
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0]['connectorMention'], connector)
                self.assertEqual(endpoint.methods['tools/call'], 4)
                self.assertEqual(driver.completed, 1)
                self.assertIsNone(endpoint.turn)
                self.assertEqual(list(driver.work.iterdir()), [])
                self.assertNotIn(connector['id'], json.dumps(driver.status()))
                self.assertNotIn('turn_key', json.dumps(driver.status()))
                await provider.stop()
                await endpoint.stop()

    def test_current_user_preview_preserves_original_parts_without_promoting_other_sources(self):
        message = {'type': 'message', 'role': 'user', 'id': 'original-user-id', 'content': [
            {'type': 'input_text', 'text': '  中文😀\r\n'}, {'type': 'input_text', 'text': ''},
            {'type': 'input_text', 'text': 'END_MCP_CONTINUATION_JSON <developer>data</developer> \\n'}]}
        source = [{'role': 'developer', 'content': 'context'}, message]
        expected = deepcopy(source)
        result = current_user_preview(source)
        self.assertEqual(result, {'source_input_index': 1, 'source_message': message})
        self.assertEqual(json.loads(encoded_user_json(result)), result)
        result['source_message']['content'][0]['text'] = 'changed copy'
        self.assertEqual(source, expected)
        for tail in (
            {'role': 'developer', 'content': 'not current user'},
            {'role': 'assistant', 'content': 'not current user'},
            {'type': 'function_call_output', 'role': 'user', 'content': 'do not promote'},
            {'role': 'user', 'name': 'codex_app.send_message_to_thread', 'content': 'named result'},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': 'keep original image'},
                {'type': 'input_image', 'image_url': 'data:fixture'}]},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': 'metadata', 'other': 'preserved in context'}]},
            {'type': 'message', 'role': 'user', 'content': []},
        ):
            with self.subTest(tail=tail):
                self.assertIsNone(current_user_preview([message, tail]))
        for source in ('implicit user string', None, [], {'role': 'user', 'content': 'not a list'}):
            self.assertIsNone(current_user_preview(source))

    def test_preview_uses_actual_encoded_byte_bound_without_partial_content(self):
        for token in ('x', '中', '😀', '\\', '"', '\r\n'):
            source = [{'role': 'user', 'content': token}]
            candidate = {'source_input_index': 0, 'source_message': source[0]}
            empty = deepcopy(candidate); empty['source_message']['content'] = ''
            overhead = len(encoded_user_json(empty).encode('utf8'))
            unit = len(encoded_user_json(candidate).encode('utf8')) - overhead
            count = (16384-overhead)//unit
            source[0]['content'] = token*count
            original = deepcopy(source)
            self.assertIsNotNone(current_user_preview(source))
            source[0]['content'] += token
            self.assertIsNone(current_user_preview(source))
            self.assertEqual(source[0]['content'], original[0]['content']+token)

    async def test_preview_never_replaces_full_context_or_authorizes_a_tool(self):
        endpoint = WebMcpEndpoint(indexed_protocol='mcp_catalog_pages_v2', begin_result_mode='structured_begin_v1')
        await endpoint.start(); self.addAsyncCleanup(endpoint.stop)
        connector = {'id': 'plugin:asdk_app_' + 'b'*32, 'name': 'Operator fixture'}
        driver = WebMcpBrowserDriver(self.settings, self.root/'preview', endpoint=endpoint,
            connector=connector, user_preview_mode='last_source_user_v1')
        for content in ('read the exact fixture', '完整中文' * 20000):
            payload = {**self.payload(), 'tools': [FUNCTION], 'tool_choice': 'none'}
            payload['input'].insert(0, {'role': 'developer', 'content': 'all permissions and context remain exact'})
            payload['input'][-1]['content'] = content
            protocol = make(payload)
            turn = WebMcpTurn(protocol); endpoint.turn = turn
            config = driver.request_config(turn)
            envelope = json.loads(config['text'].split('BEGIN_MCP_CONTINUATION_JSON ',1)[1]
                .split(' END_MCP_CONTINUATION_JSON',1)[0])
            self.assertEqual('current_user_preview' in envelope, content == 'read the exact fixture')
            self.assertLessEqual(len(config['text'].encode('utf8')), 65536)
            self.assertFalse(turn.begun)
            with self.assertRaisesRegex(ValueError, 'web_mcp_call_out_of_order'):
                await turn.invoke(turn.key, 'never-before-context', 'inspect', {'value':'no grant'})
            fragments, key = [], turn.key
            while key:
                page = turn.begin(key); fragments.append(page['json_fragment']); key = page['next_read_key']
            request = json.loads(''.join(fragments))['request']
            self.assertEqual(request['input'], protocol.request()['input'])
            self.assertEqual(request['tool_choice'], 'none')
            with self.assertRaisesRegex(ValueError, 'web_mcp_schema_not_read'):
                await turn.invoke(turn.key, 'never-before-schema', 'inspect', {'value':'no grant'})
            catalog = turn.begin(page['catalog_read_key'])
            schema = catalog['entries'][0]['schema_read_key']
            while schema:
                selected = turn.begin(schema); schema = selected['next_read_key']
            with self.assertRaisesRegex(ValueError, 'invalid_upstream_tool_response_no_retry'):
                await turn.invoke(turn.key, 'never-widen-none', 'inspect', {'value':'still no grant'})
            self.assertEqual((turn.calls, turn.released_calls), (0, 0))

    async def test_no_task_tools_still_requires_read_only_transport_context(self):
        endpoint = WebMcpEndpoint(indexed_protocol='mcp_context_records_v3',
            begin_result_mode='structured_begin_v1')
        await endpoint.start(); self.addAsyncCleanup(endpoint.stop)
        connector = {'id': 'plugin:asdk_app_' + 'b'*32, 'name': 'Operator fixture'}
        driver = WebMcpBrowserDriver(self.settings, self.root/'no-task-tools', endpoint=endpoint,
            connector=connector, user_preview_mode='last_source_user_v1')
        payload = {**self.payload(), 'tools': [FUNCTION], 'tool_choice': 'none'}
        payload['input'][-1]['content'] = 'Do not use task tools or search. Reply exactly BASIC_OK.'
        protocol = make(payload)
        turn = WebMcpTurn(protocol); endpoint.turn = turn
        self.addCleanup(turn.close)
        prompt = driver.request_config(turn)['text']
        self.assertIn('operator_begin is a required read-only transport step', prompt)
        self.assertIn('including when the user asks for no task tools or search', prompt)
        self.assertIn('Honor the source request and user instructions when deciding whether to call operator_call', prompt)
        self.assertFalse(turn.begun)
        with self.assertRaisesRegex(ValueError, 'web_mcp_context_not_read'):
            turn.finish(message(['BASIC_OK']))
        key = turn.key
        while key:
            page = turn.begin(key)
            self.assertEqual(page['section'], 'context')
            key = page['next_read_key']
        self.assertTrue(turn.observation()['request_read'])
        turn.finish(message(['BASIC_OK']))
        response, _ = await turn.next_response()
        self.assertEqual(response['output'][0]['content'][0]['text'], 'BASIC_OK')
        self.assertEqual((turn.calls, turn.released_calls, turn.results), (0, 0, 0))

    async def test_current_user_header_requires_explicit_preview_and_structured_context_modes(self):
        for wire in ('mcp_catalog_pages_v2','mcp_context_records_v3'):
            for mode in ('none','last_source_user_v1'):
                with self.subTest(wire=wire,mode=mode):
                    endpoint=WebMcpEndpoint(indexed_protocol=wire,begin_result_mode='structured_begin_v1')
                    await endpoint.start();self.addAsyncCleanup(endpoint.stop)
                    driver=WebMcpBrowserDriver(self.settings,self.root/(wire+mode),endpoint=endpoint,
                        connector={'id':'plugin:asdk_app_'+'b'*32,'name':'Operator fixture'},user_preview_mode=mode)
                    payload={**self.payload(),'tools':[FUNCTION],'tool_choice':'none'}
                    payload['input'].insert(0,{'role':'user','content':'older request stays history'})
                    native=make(payload);turn=WebMcpTurn(native);endpoint.turn=turn
                    config=driver.request_config(turn)
                    page=turn.begin(turn.key)
                    if wire=='mcp_context_records_v3':
                        header=page['records'][0]['value']
                        self.assertEqual('current_user_preview' in header,mode=='last_source_user_v1')
                        if mode=='last_source_user_v1':
                            self.assertEqual(header['current_user_preview'],current_user_preview(native.source_input()))
                        self.assertNotIn('current_user_preview',header['value'])
                        self.assertEqual([v['value']['value'] for v in page['records'][1:]],native.request()['input'])
                    else:
                        self.assertNotIn('current_user_preview',page['json_fragment'])
                    self.assertEqual(native.source_input(),payload['input'])
                    self.assertEqual(native.request()['tool_choice'],'none')
                    self.assertEqual((turn.calls,turn.released_calls),(0,0))
                    turn.close()

    async def test_mcp_browser_requires_live_exact_endpoint_and_bounds_prompt_before_spawn(self):
        endpoint = WebMcpEndpoint()
        connector = {'id': 'plugin:asdk_app_' + 'b' * 32, 'name': 'Operator fixture'}
        driver = WebMcpBrowserDriver(self.settings, self.root / 'mcp-rejected',
            endpoint=endpoint, connector=connector)
        turn = self.turn()
        with patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
            for name in ('连' * 65, '固定\n', '固定\u2028', '固定\u200b连接', ' 固定', '固定<script>'):
                with self.assertRaisesRegex(ValueError, 'web_mcp_registered_connector_required'):
                    WebMcpBrowserDriver(self.settings, self.root / 'bad-name',
                        endpoint=endpoint, connector={**connector, 'name': name})
            with self.assertRaisesRegex(ValueError, 'web_mcp_browser_endpoint_binding_required'):
                await driver(turn)
            self.assertFalse(turn.begun)
            await endpoint.start()
            self.addAsyncCleanup(endpoint.stop)
            endpoint.turn = self.turn()
            with self.assertRaisesRegex(ValueError, 'web_mcp_browser_endpoint_binding_required'):
                await driver(turn)
            endpoint.turn = turn
            valid = driver.request_config(turn)
            # The source request stays lossless, while the independent current
            # transport key needs no JSON escaping or substitution from history.
            self.assertRegex(turn.key, r'\A[a-f0-9]{64}\Z')
            envelope = json.loads(valid['text'].split('BEGIN_MCP_CONTINUATION_JSON ', 1)[1]
                .split(' END_MCP_CONTINUATION_JSON', 1)[0])
            self.assertEqual(envelope['protocol'], 'mcp_indexed_request_v1')
            self.assertNotIn('request', envelope)
            self.assertEqual(turn.preview_begin()['request'], turn.protocol.request())
            self.assertEqual(envelope['mcp_transport']['turn_key'], turn.key)
            self.assertIn('first operator_begin and every operator_call is: ' + turn.key + '.', valid['text'])
            with self.assertRaisesRegex(ValueError, 'web_mcp_turn_rejected'):
                turn.begin(turn.key.upper())
            self.assertFalse(turn.begun)
            connector['id'] = 'changed after construction'
            self.assertNotEqual(valid['connectorMention']['id'], connector['id'])
            self.assertFalse(turn.begun)
            turn.begin(turn.key)
            with self.assertRaisesRegex(ValueError, 'web_mcp_browser_endpoint_binding_required'):
                await driver(turn)
            payload = self.payload()
            payload['input'][0]['content'] = '完整中文 / \\n\r\n' * 6000
            large = WebMcpTurn(WebModelProtocol(service.text_route(), payload))
            endpoint.turn = large
            bootstrap = driver.request_config(large)
            self.assertLess(len(bootstrap['text'].encode('utf8')), 3072)
            self.assertNotIn('完整中文', bootstrap['text'])
            self.assertFalse(large.begun)
            pieces, key = [], large.key
            while key:
                page = large.begin(key)
                pieces.append(page['json_fragment'])
                key = page['next_read_key']
            self.assertGreater(len(pieces), 1)
            self.assertEqual(json.loads(''.join(pieces))['request']['input'], payload['input'])
            payload['input'][0]['content'] *= 20
            too_many = WebMcpTurn(WebModelProtocol(service.text_route(), payload))
            endpoint.turn = too_many
            with self.assertRaisesRegex(WebRequestCapacityError, 'web_mcp_request_capacity_exceeded_before_dispatch'):
                driver.request_config(too_many)
            self.assertFalse(too_many.begun)
            self.assertIsNone(too_many.indexed)
            # Two individually valid history parts can exceed the complete MCP
            # bound. Reject before starting a browser, without consuming begin.
            payload['input'] = [{'role': 'user', 'content': 'x' * (9 * 1024 * 1024)}] * 2
            oversized = WebMcpTurn(WebModelProtocol(service.text_route(), payload))
            endpoint.turn = oversized
            with self.assertRaisesRegex(ValueError, 'web_mcp_payload_too_large'):
                driver.request_config(oversized)
            self.assertFalse(oversized.begun)
            spawn.assert_not_called()
        self.assertEqual(list(driver.work.iterdir()), [])

    async def test_background_is_default_and_requires_a_complete_invisible_window_report(self):
        settings = {key: value for key, value in self.settings.items() if key != 'window_mode'}
        state = {'operator_web': 1, 'kind': 'window_state', 'visible': False, 'focused': False,
            'backgroundInput': True, 'inputMode': 'dom_v1', 'shown': 0, 'focusedEvents': 0}
        for index, report in enumerate((state, None, {**state, 'shown': 1}, {**state, 'focused': True},
                {**state, 'shown': False})):
            with self.subTest(report=report):
                driver = WebTextBrowserDriver(settings, self.root / ('hidden-' + str(index)))
                events = [{'operator_web': 1, 'kind': 'dispatch_started'}]
                if report is not None: events.append(report)
                events.append({'operator_web': 1, 'kind': 'completed', 'model': 'gpt-5.6-sol',
                    'effortIndex': 2, 'publicMessage': message(['hidden public answer'])})
                program = '\n'.join('print(' + repr(json.dumps(event)) + ')' for event in events)
                seen = []
                with self.spawn_fixture(program, seen):
                    if index == 0:
                        self.assertEqual(await driver(self.turn()), message(['hidden public answer']))
                    else:
                        with self.assertRaisesRegex(ValueError, 'web_(background_window_not_verified|window_state_invalid)'):
                            await driver(self.turn())
                self.assertEqual(len(seen), 1)
                self.assertIs(seen[0]['visible'], False)
                self.assertEqual(seen[0]['backgroundInput'], 'dom_v1')
                self.assertEqual(list(driver.work.iterdir()), [])

    async def test_background_login_and_challenge_are_actionable_without_retry_or_false_no_send_claim(self):
        for index, (code, dispatched) in enumerate((('web_browser_login_required_before_dispatch', False),
                ('web_browser_challenge_required_before_dispatch', False),
                ('web_browser_challenge_required_before_dispatch', True))):
            with self.subTest(code=code, dispatched=dispatched):
                driver = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                    self.root / ('attention-' + str(index)))
                events = ([{'operator_web': 1, 'kind': 'dispatch_started'}] if dispatched else [])
                events.append({'operator_web': 1, 'kind': 'failed', 'stage': 'load_fresh_page',
                    'sent': False, 'error': code})
                program = '\n'.join('print(' + repr(json.dumps(event)) + ')' for event in events) + '\nraise SystemExit(1)'
                bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                provider = WebResponsesProvider(bridge)
                base = await provider.start()
                self.addAsyncCleanup(provider.stop)
                seen = []
                with self.spawn_fixture(program, seen):
                    async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                        async with client.post(base + '/responses', json=self.payload()) as response:
                            self.assertEqual(response.status, 400)
                            self.assertEqual((await response.json())['error']['cause_http_status'], 502 if dispatched else 503)
                            error = (await response.json())['error']
                            self.assertEqual(error['code'], 'web_browser_driver_failed_no_retry' if dispatched else code)
                            self.assertIs(error['retryable'], False)
                            if dispatched:
                                self.assertIn('可能已有部分操作完成', error['message'])
                                self.assertNotIn('本次未向模型发送消息', error['message'])
                                self.assertNotIn('本次没有向网页模型发送消息', error['message'])
                            else:
                                self.assertIn('本次未向模型发送消息', error['message'])
                        async with client.post(base + '/responses', json=self.payload()) as response:
                            self.assertEqual(response.status, 400)
                            self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                self.assertEqual(len(seen), 1)
                self.assertEqual(list(driver.work.iterdir()), [])

    def test_generation_diagnostics_admit_only_fixed_bounded_counts_and_flags(self):
        state = {'userRows': 1, 'assistantRows': 1, 'finalRows': 0, 'finishedFinalRows': 0,
            'currentFinalRows': 0, 'currentFinishedFinalRows': 0, 'renderedTextLength': 0,
            'stopPresent': True, 'stopVisible': True, 'subscriptionWarning': False, 'errorAlert': False}
        self.assertEqual(safe_generation_progress(state), state)
        for changes in ({'userRows': True}, {'assistantRows': 10001}, {'finalRows': -1},
                {'errorAlert': 'private text'}, {'body': 'private text'}):
            with self.assertRaisesRegex(ValueError, 'web_generation_state_invalid'):
                safe_generation_progress({**state, **changes})

    def test_public_interruption_diagnostics_reject_text_unknown_fields_and_invalid_counts(self):
        state = {'approvalCards': 0, 'connectorDialogs': 0, 'sessionExpired': False,
            'subscriptionUnavailable': False, 'responseError': False}
        self.assertEqual(safe_public_interruption(state), state)
        for changes in ({'approvalCards': True}, {'approvalCards': 10001}, {'connectorDialogs': 17},
                {'connectorDialogs': -1}, {'responseError': 'private'}, {'text': 'private'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'web_public_interruption_state_invalid'):
                safe_public_interruption({**state, **changes})

    def ui_fixture_program(self, events, session, exit_code=1):
        return 'EVENTS=' + repr(events) + '\nSESSION=' + repr(session) + '\nEXIT=' + repr(exit_code) + '\n' + '''import json,sys,time
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
root=Path(c['workerDirectory']) if SESSION else None
ident=None
if SESSION:
 print(json.dumps({'operator_web':1,'kind':'worker_ready'}),flush=True)
 while not (root/'next.json').exists():time.sleep(.01)
 r=json.loads((root/'next.json').read_text(encoding='utf8'));ident=r['id']
 (root/'next.json').rename(root/'active.json')
for event in EVENTS:
 if SESSION:event={**event,'requestId':ident}
 print(json.dumps(event),flush=True)
if SESSION:
 (root/'active.json').unlink()
 print(json.dumps({'operator_web':1,'kind':'worker_idle','requestId':ident,'resultCode':EXIT}),flush=True)
raise SystemExit(EXIT)
'''

    async def test_network_failure_is_bound_private_and_never_replayed(self):
        from operator_core.web_mcp_transport import WebBrowserNetworkError
        variants = [('valid', code) for code in sorted(WebBrowserNetworkError.codes)] + [
            (name, 'net::ERR_CONNECTION_RESET') for name in ('no_dispatch', 'no_event',
                'mismatch', 'not_sent', 'aborted', 'unknown', 'duplicate', 'late_success')]
        for lifecycle in ('per_turn', 'session'):
            for variant, code in variants:
                with self.subTest(lifecycle=lifecycle, variant=variant, code=code):
                    base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                        self.root / f'network-{lifecycle}-{variant}-{code.split("::")[-1]}')
                    driver = WebBrowserSession(base) if lifecycle == 'session' else base
                    provider = WebResponsesProvider(WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver))
                    url = await provider.start()
                    self.addAsyncCleanup(provider.stop)
                    observed = 'net::ERR_ABORTED' if variant == 'aborted' else 'other' if variant == 'unknown' else code
                    events = [] if variant == 'no_dispatch' else [{'operator_web': 1, 'kind': 'dispatch_started'}]
                    if variant != 'no_event':
                        events.append({'operator_web': 1, 'kind': 'model_network_state',
                            'phase': 'error', 'status': None, 'error': observed, 'url': 'PRIVATE'})
                    failure = {'operator_web': 1, 'kind': 'failed', 'sent': variant != 'not_sent',
                        'error': 'web_model_network_interrupted_no_retry', 'body': 'PRIVATE',
                        'networkError': 'net::ERR_TIMED_OUT' if variant == 'mismatch' else observed}
                    events.append(failure)
                    if variant == 'duplicate': events.append(failure)
                    if variant == 'late_success':
                        events.append({'operator_web': 1, 'kind': 'completed', 'model': 'gpt-5.6-sol',
                            'effortIndex': 2, 'publicMessage': message(['false success'])})
                    seen = []
                    with self.spawn_fixture(self.ui_fixture_program(events, lifecycle == 'session'), seen):
                        async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                            async with asyncio.timeout(4):
                                async with client.post(url + '/responses', json=self.payload()) as response:
                                    error = (await response.json())['error']
                                    self.assertEqual(response.status, 400)
                                    self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                            if variant == 'valid':
                                self.assertEqual(error['code'], 'web_model_network_interrupted_no_retry')
                                self.assertEqual(error['network_error'], code)
                                self.assertEqual(error['observation'], 'browser_network')
                                self.assertFalse(error['retryable'])
                                self.assertIn('网络', error['message'])
                                self.assertNotIn('本次没有向网页模型发送消息', error['message'])
                            else:
                                self.assertNotEqual(error['code'], 'web_model_network_interrupted_no_retry')
                            self.assertNotIn('PRIVATE', json.dumps(error))
                            async with client.post(url + '/responses', json=self.payload()) as response:
                                self.assertEqual(response.status, 400)
                                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                    self.assertEqual(len(seen), 1)
                    self.assertEqual(base.completed, 0)
                    self.assertNotIn('PRIVATE', json.dumps(base.status()))
                    self.assertEqual(list(base.work.iterdir()), [])

    async def test_final_wait_timeout_is_distinct_from_login_and_never_replayed(self):
        for lifecycle in ('per_turn', 'session'):
            for variant in ('valid', 'no_dispatch', 'wrong_stage', 'not_sent', 'different_error',
                    'duplicate', 'completed_after_timeout', 'http_rejected', 'login_expired'):
                with self.subTest(lifecycle=lifecycle, variant=variant):
                    base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                        self.root / f'final-timeout-{lifecycle}-{variant}')
                    driver = WebBrowserSession(base) if lifecycle == 'session' else base
                    provider = WebResponsesProvider(WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver))
                    url = await provider.start()
                    self.addAsyncCleanup(provider.stop)
                    failure = {'operator_web': 1, 'kind': 'failed', 'sent': variant != 'not_sent',
                        'stage': 'load_fresh_page' if variant == 'wrong_stage' else 'wait_public_final',
                        'error': 'PRIVATE' if variant == 'different_error' else 'web_page_state_timeout',
                        'body': 'PRIVATE'}
                    events = [] if variant == 'no_dispatch' else [{'operator_web': 1, 'kind': 'dispatch_started'}]
                    if variant == 'http_rejected':
                        events.append({'operator_web': 1, 'kind': 'model_network_state',
                            'phase': 'response_started', 'status': 403, 'error': None})
                    if variant == 'login_expired':
                        events.append({'operator_web': 1, 'kind': 'public_interruption_state',
                            'stage': 'wait_public_final', 'sent': True, 'state': {
                                'approvalCards': 0, 'connectorDialogs': 0, 'sessionExpired': True,
                                'subscriptionUnavailable': False, 'responseError': False}})
                    events.append(failure)
                    if variant == 'duplicate': events.append(failure)
                    if variant == 'completed_after_timeout':
                        events.append({'operator_web': 1, 'kind': 'completed',
                            'model': 'gpt-5.6-sol', 'effortIndex': 2, 'publicMessage': message()})
                    seen = []
                    with self.spawn_fixture(self.ui_fixture_program(events, lifecycle == 'session',
                            0 if variant == 'completed_after_timeout' else 1), seen):
                        async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                            async with asyncio.timeout(4):
                                async with client.post(url + '/responses', json=self.payload()) as response:
                                    self.assertEqual(response.status, 400)
                                    self.assertEqual((await response.json())['error']['cause_http_status'], 504 if variant == 'valid' else 502)
                                    error = (await response.json())['error']
                            self.assertEqual(error['code'], 'web_browser_final_timeout_no_retry'
                                if variant == 'valid' else 'web_browser_driver_failed_no_retry')
                            self.assertIs(error['retryable'], False)
                            self.assertNotIn('PRIVATE', json.dumps(error))
                            if variant == 'valid':
                                self.assertEqual(error['observation'], 'browser_wait')
                                self.assertIn('不表示登录已过期', error['message'])
                                self.assertIn('本轮本机未转交工具调用', error['message'])
                            async with client.post(url + '/responses', json=self.payload()) as response:
                                self.assertEqual(response.status, 400)
                                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                    self.assertEqual((len(seen), base.completed), (1, 0))
                    self.assertNotIn('PRIVATE', json.dumps(list(base.events)))
                    self.assertEqual(list(base.work.iterdir()), [])

    async def test_observed_public_ui_failure_returns_actionable_error_and_never_replays(self):
        clear = {'approvalCards': 0, 'connectorDialogs': 0, 'sessionExpired': False,
            'subscriptionUnavailable': False, 'responseError': False}
        for lifecycle in ('per_turn', 'session'):
            for flag, code in (
                    ('approvalCards', 'web_tool_confirmation_required_no_retry'),
                    ('sessionExpired', 'web_session_expired_during_generation_no_retry'),
                    ('subscriptionUnavailable', 'web_subscription_unavailable_during_generation_no_retry'),
                    ('responseError', 'web_response_error_no_retry')):
                with self.subTest(lifecycle=lifecycle, flag=flag):
                    base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                        self.root / f'ui-{lifecycle}-{flag}')
                    driver = WebBrowserSession(base) if lifecycle == 'session' else base
                    bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                    provider = WebResponsesProvider(bridge)
                    url = await provider.start()
                    self.addAsyncCleanup(provider.stop)
                    state = {**clear, flag: 1 if flag == 'approvalCards' else True}
                    events = [
                        {'operator_web': 1, 'kind': 'dispatch_started'},
                        {'operator_web': 1, 'kind': 'public_interruption_state', 'sent': True,
                            'stage': 'wait_public_final', 'state': state, 'private': 'PRIVATE'},
                        {'operator_web': 1, 'kind': 'failed', 'sent': True,
                            'stage': 'wait_public_final', 'error': code, 'text': 'PRIVATE'}]
                    seen = []
                    with self.spawn_fixture(self.ui_fixture_program(events, lifecycle == 'session'), seen):
                        async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                            async with asyncio.timeout(4):
                                async with client.post(url + '/responses', json=self.payload()) as response:
                                    self.assertEqual(response.status, 400)
                                    self.assertEqual((await response.json())['error']['cause_http_status'], 409 if flag == 'approvalCards' else 502)
                                    error = (await response.json())['error']
                            self.assertEqual(error['code'], code)
                            self.assertEqual(error['observation'], 'public_ui')
                            self.assertIs(error['retryable'], False)
                            self.assertIn('不会自动重做', error['message'])
                            self.assertNotIn('PRIVATE', json.dumps(error))
                            async with client.post(url + '/responses', json=self.payload()) as response:
                                self.assertEqual(response.status, 400)
                                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                                self.assertEqual((await response.json())['error']['code'], 'web_bridge_turn_consumed_no_retry')
                    self.assertEqual((len(seen), base.dispatches, base.completed), (1, 1, 0))
                    self.assertNotIn('PRIVATE', json.dumps(list(base.events)))
                    self.assertEqual(list(base.work.iterdir()), [])

    async def test_public_ui_failure_requires_current_evidence_and_cannot_supply_a_success(self):
        clear = {'approvalCards': 0, 'connectorDialogs': 0, 'sessionExpired': False,
            'subscriptionUnavailable': False, 'responseError': False}
        for lifecycle in ('per_turn', 'session'):
            for variant in ('no_evidence', 'before_dispatch', 'wrong_stage', 'different_state',
                    'completed_after_interruption', 'cleared_before_error'):
                with self.subTest(lifecycle=lifecycle, variant=variant):
                    base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                        self.root / f'ui-unbound-{lifecycle}-{variant}')
                    driver = WebBrowserSession(base) if lifecycle == 'session' else base
                    bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                    provider = WebResponsesProvider(bridge)
                    url = await provider.start()
                    self.addAsyncCleanup(provider.stop)
                    observed = {'operator_web': 1, 'kind': 'public_interruption_state', 'sent': True,
                        'stage': 'wait_public_final', 'state': {**clear, 'approvalCards': 1}}
                    events = [] if variant == 'before_dispatch' else [{'operator_web': 1, 'kind': 'dispatch_started'}]
                    if variant != 'no_evidence': events.append(observed)
                    if variant == 'cleared_before_error': events.append({**observed, 'state': clear})
                    if variant == 'completed_after_interruption':
                        events.append({'operator_web': 1, 'kind': 'completed', 'model': 'gpt-5.6-sol',
                            'effortIndex': 2, 'publicMessage': message()})
                    else:
                        events.append({'operator_web': 1, 'kind': 'failed', 'sent': True,
                            'stage': 'load_fresh_page' if variant == 'wrong_stage' else 'wait_public_final',
                            'error': 'web_response_error_no_retry' if variant == 'different_state'
                                else 'web_tool_confirmation_required_no_retry'})
                    program = self.ui_fixture_program(events, lifecycle == 'session',
                        exit_code=0 if variant == 'completed_after_interruption' else 1)
                    seen = []
                    with self.spawn_fixture(program, seen):
                        async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                            async with client.post(url + '/responses', json=self.payload()) as response:
                                self.assertEqual(response.status, 400)
                                self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                                error = (await response.json())['error']
                    self.assertEqual(error['code'], 'web_browser_driver_failed_no_retry')
                    self.assertNotIn('observation', error)
                    self.assertEqual((len(seen), base.completed), (1, 0))

    def session_program(self, variant='normal'):
        return 'VARIANT=' + repr(variant) + '\nPUBLIC=' + repr(message()) + '\n' + '''import json,sys,time
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'));root=Path(c['workerDirectory'])
assert c['mode']=='worker' and c['visible'] is False and c['backgroundInput']=='dom_v1'
def emit(kind,**values):print(json.dumps({'operator_web':1,'kind':kind,**values}),flush=True)
if VARIANT.startswith('assist'):
 assert c['startupAssistance'] is True and 'text' not in c
 emit('assistance_opened')
 if VARIANT=='assist':
  while not (root/'fixture-assist-done.txt').exists():time.sleep(.02)
  (root/'fixture-assist-done.txt').unlink()
  emit('assistance_hidden',visible=False,focused=False,userClosed=True)
emit('worker_ready')
if VARIANT.startswith('prepare_'):
 assert c['startupPrepare'] is True and 'text' not in c and 'startupAssistance' not in c
 if VARIANT=='prepare_delayed':
  while not (root/'fixture-prepare-done.txt').exists():time.sleep(.02)
  (root/'fixture-prepare-done.txt').unlink()
 if VARIANT=='prepare_bad':emit('worker_prepared',hidden=False,empty=True)
 elif VARIANT=='prepare_challenge':
  emit('worker_attention_required',reason='web_browser_challenge_required_before_dispatch')
  while not (root/'assist.json').exists():time.sleep(.02)
  a=json.loads((root/'assist.json').read_text());(root/'assist.json').unlink()
  emit('assistance_opened',assistanceId=a['id'])
  while not (root/'fixture-assist-done.txt').exists():time.sleep(.02)
  (root/'fixture-assist-done.txt').unlink()
  emit('assistance_hidden',assistanceId=a['id'],visible=False,focused=False,userClosed=True)
 else:emit('worker_prepared',hidden=True,empty=True)
count=0
while not (root/'shutdown.json').exists():
 p=root/'next.json'
 if not p.exists():time.sleep(.02);continue
 r=json.loads(p.read_text(encoding='utf8'));p.rename(root/'active.json');ident=r['id']
 count+=1
 if count>1 or VARIANT=='invalid_navigation':
  emit('fresh_chat_navigation',requestId=ident,mode='ui_new_chat_v1',temporary=True,
   userRows=False if VARIANT=='invalid_navigation' else 0,assistantRows=0,private='discard this')
 emit('dispatch_started',requestId=ident)
 status=int(VARIANT.removeprefix('http_')) if VARIANT.startswith('http_') else 200
 emit('model_network_state',requestId=ident,phase='response_started',status=status,error=None,headers='discard this')
 emit('window_state',requestId=ident,visible=False,focused=False,backgroundInput=True,inputMode='dom_v1',shown=0,focusedEvents=0)
 if VARIANT.startswith('http_'):
  emit('failed',requestId=ident,sent=True,error='web_model_http_rejected_no_retry',upstreamStatus=status)
  (root/'active.json').unlink();emit('worker_idle',requestId=ident,resultCode=1);break
 if VARIANT=='cancel':
  while not (root/'cancel.json').exists():time.sleep(.02)
  assert json.loads((root/'cancel.json').read_text())=={'id':ident}
  emit('failed',requestId=ident,error='web_cancelled_no_retry')
  (root/'cancel.json').unlink();(root/'active.json').unlink()
  emit('worker_idle',requestId=ident,resultCode=1);break
 payload=json.loads(r['text'].split('BEGIN_COMPLETE_RESPONSES_REQUEST_JSON ',1)[1].rsplit(' END_COMPLETE_RESPONSES_REQUEST_JSON',1)[0])
 public={**PUBLIC,'content':{'content_type':'text','parts':[payload['input'][-1]['content']]}}
 if VARIANT=='wrong_id':ident='f'*32
 emit('completed',requestId=ident,model='gpt-5.6-sol',effortIndex=2,publicMessage=public)
 if VARIANT=='duplicate':emit('completed',requestId=ident,model='gpt-5.6-sol',effortIndex=2,publicMessage=public)
 (root/'active.json').unlink()
 emit('worker_idle',requestId=ident,resultCode=0)
'''

    async def test_http_rejection_returns_native_error_without_timeout_answer_or_replay(self):
        for lifecycle in ('per_turn', 'session'):
            for status in (401, 403, 429, 500):
                with self.subTest(lifecycle=lifecycle, status=status):
                    base_driver = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                        self.root / f'http-{lifecycle}-{status}')
                    driver = WebBrowserSession(base_driver) if lifecycle == 'session' else base_driver
                    bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                    provider = WebResponsesProvider(bridge)
                    url = await provider.start()
                    self.addAsyncCleanup(provider.stop)
                    events = [
                        {'operator_web':1, 'kind':'dispatch_started'},
                        {'operator_web':1, 'kind':'model_network_state', 'phase':'response_started', 'status':status, 'error':None},
                        {'operator_web':1, 'kind':'failed', 'sent':True,
                            'error':'web_model_http_rejected_no_retry', 'upstreamStatus':status, 'body':'PRIVATE'}]
                    program = self.session_program(f'http_{status}') if lifecycle == 'session' else (
                        '\n'.join('print(' + repr(json.dumps(e)) + ')' for e in events) + '\nraise SystemExit(1)')
                    seen = []
                    with self.spawn_fixture(program, seen):
                        async with ClientSession(headers={'Authorization':'Bearer ' + provider.token}) as client:
                            async with asyncio.timeout(4):
                                async with client.post(url + '/responses', json=self.payload()) as response:
                                    self.assertEqual(response.status, 400)
                                    self.assertEqual((await response.json())['error']['cause_http_status'], 502)
                                    error = (await response.json())['error']
                            self.assertEqual(error['code'], 'web_model_http_rejected_no_retry')
                            self.assertEqual(error['upstream_status'], status)
                            self.assertIn(f'HTTP {status}', error['message'])
                            self.assertNotIn('PRIVATE', json.dumps(error))
                            async with client.post(url + '/responses', json=self.payload()) as response:
                                self.assertEqual(response.status, 400)
                                self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                    self.assertEqual(len(seen), 1)
                    self.assertEqual(base_driver.dispatches, 1)
                    self.assertEqual(base_driver.completed, 0)
                    self.assertEqual(list(base_driver.work.iterdir()), [])

    async def test_index_capacity_rejection_is_local_413_without_browser_or_replay(self):
        endpoint = WebMcpEndpoint(indexed_protocol='mcp_context_records_v3',
            begin_result_mode='structured_begin_v1')
        await endpoint.start()
        self.addAsyncCleanup(endpoint.stop)
        base = WebMcpBrowserDriver({**self.settings, 'window_mode': 'background'},
            self.root / 'capacity', endpoint=endpoint,
            connector={'id': 'plugin:asdk_app_' + 'c' * 32, 'name': 'Fixture'})
        driver = WebBrowserSession(base)
        provider = WebResponsesProvider(WebResponsesBridge(service.text_route(), endpoint, driver))
        url = await provider.start()
        self.addAsyncCleanup(provider.stop)
        payload = self.payload('over-capacity')
        payload['input'][0]['content'] = 'private capacity fixture ' * 60000
        original = deepcopy(payload)
        with patch('operator_core.web_browser_driver.asyncio.create_subprocess_exec') as spawn:
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                async with client.post(url + '/responses', json=payload) as response:
                    self.assertEqual(response.status, 413)
                    error = (await response.json())['error']
                self.assertEqual(error['code'], 'web_mcp_request_capacity_exceeded_before_dispatch')
                self.assertEqual(error['observation'], 'local_request_preflight')
                self.assertEqual(error['scope'], 'indexed_context')
                self.assertEqual(error['limit_pages'], 24)
                self.assertEqual(error['reply_limit_bytes'], 48 * 1024)
                self.assertEqual(error['single_use_read_limit'], 40)
                self.assertFalse(error['retryable'])
                self.assertIn('无需重新登录', error['message'])
                self.assertIn('原任务与历史保留', error['message'])
                self.assertNotIn('private capacity fixture', json.dumps(error))
                self.assertEqual(error['transport']['turn']['calls_released'], 0)
                async with client.post(url + '/responses', json=payload) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
            spawn.assert_not_called()
        self.assertEqual(payload, original)
        self.assertEqual(base.attempts, 1)
        self.assertEqual(base.failed, 1)
        self.assertEqual(base.dispatches, 0)
        self.assertFalse(driver.closed)
        self.assertFalse(base.active)
        self.assertEqual(driver.launches, 0)
        self.assertIsNone(provider.bridge.turn)

    async def test_capacity_preflight_keeps_existing_idle_worker_and_completed_page(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / 'idle-capacity')
        driver = WebBrowserSession(base)
        self.addAsyncCleanup(driver.close)
        seen = []
        with self.spawn_fixture(self.session_program(), seen):
            await driver(self.turn())
            child = driver.child
            self.assertTrue(driver.retained_completed_page)
            payload = self.payload('different-oversized-request')
            payload['input'][0]['content'] = 'private oversized record ' * 60000
            turn = WebMcpTurn(WebModelProtocol(service.text_route(), payload))
            # Exercise the real local indexed preflight before the fixture's
            # text worker, without sending it an MCP request it cannot read.
            with patch.object(base, 'request_config', side_effect=lambda value: value.prepare_indexed()):
                with self.assertRaises(WebRequestCapacityError):
                    await driver(turn)
            self.assertIsNone(driver.current)
            self.assertIs(driver.child, child)
            self.assertIsNone(child.returncode)
            self.assertFalse(driver.closed)
            self.assertTrue(driver.retained_completed_page)
            self.assertTrue(driver.status()['inspection_available'])
            self.assertFalse((driver.folder / 'next.json').exists())
            self.assertFalse(turn.begun)
            self.assertIsNone(turn.indexed)
            await driver(self.turn())
            self.assertIs(driver.child, child)
            self.assertEqual(base.dispatches, 2)
            self.assertEqual(base.completed, 2)
            self.assertEqual(base.failed, 1)
            self.assertEqual(driver.launches, 1)
            self.assertEqual(len(seen), 1)

    async def test_session_reuses_one_private_process_and_seals_each_public_reply_before_release(self):
        for variant in ('normal', 'duplicate', 'wrong_id', 'invalid_navigation'):
            with self.subTest(variant=variant):
                base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / ('worker-' + variant))
                driver = WebBrowserSession(base)
                self.addAsyncCleanup(driver.close)
                bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
                self.addAsyncCleanup(bridge.stop)
                seen = []
                with self.spawn_fixture(self.session_program(variant), seen):
                    if variant == 'normal':
                        for index in range(2):
                            payload = self.payload(str(index))
                            payload['input'][0]['content'] = 'exact 中文😀\r\n_a_' + str(index)
                            response, _ = await bridge.exchange(payload)
                            self.assertEqual(response['output'][0]['content'][0]['text'], payload['input'][0]['content'])
                        self.assertEqual(driver.status()['completed'], 2)
                        self.assertTrue(driver.status()['process_running'])
                        navigation = [e for e in driver.status()['events'] if e['kind'] == 'fresh_chat_navigation']
                        self.assertEqual(len(navigation), 1)
                        self.assertEqual({k: navigation[0][k] for k in ('mode', 'temporary', 'userRows', 'assistantRows')},
                            {'mode': 'ui_new_chat_v1', 'temporary': True, 'userRows': 0, 'assistantRows': 0})
                        self.assertNotIn('private', navigation[0])
                        network = [e for e in driver.status()['events'] if e['kind'] == 'model_network_state']
                        self.assertEqual(len(network), 2)
                        self.assertTrue(all(e['status'] == 200 and 'headers' not in e for e in network))
                    else:
                        with self.assertRaisesRegex(ValueError, 'web_browser_driver_failed_no_retry'):
                            await bridge.exchange(self.payload())
                        self.assertEqual(driver.status()['completed'], 0)
                    await driver.close()
                    self.assertEqual(driver.status()['process_launches'], 1)
                    self.assertEqual(len(seen), 1)
                    self.assertFalse(driver.status()['process_running'])
                    self.assertEqual(list(base.work.iterdir()), [])

    async def test_session_cancellation_addresses_only_current_request_and_closes_worker_without_replay(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / 'worker-cancel')
        driver = WebBrowserSession(base)
        self.addAsyncCleanup(driver.close)
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
        self.addAsyncCleanup(bridge.stop)
        seen = []
        with self.spawn_fixture(self.session_program('cancel'), seen):
            task = asyncio.create_task(bridge.exchange(self.payload()))
            async def dispatched():
                while base.dispatches != 1: await asyncio.sleep(.02)
            await asyncio.wait_for(dispatched(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertEqual(base.cancelled, 1)
            self.assertFalse(driver.status()['process_running'])
            self.assertEqual(list(base.work.iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'web_bridge_turn_consumed_no_retry'):
                await bridge.exchange(self.payload())
            self.assertEqual(len(seen), 1)

    async def test_assistance_rejects_early_turns_without_queueing_then_reuses_the_verified_process(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / 'worker-assist')
        driver = WebBrowserSession(base, startup_assistance=True)
        self.addAsyncCleanup(driver.close)
        bridge = WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver)
        provider = WebResponsesProvider(bridge)
        address = await provider.start()
        self.addAsyncCleanup(provider.stop)
        seen = []
        with self.spawn_fixture(self.session_program('assist'), seen):
            preparation = asyncio.create_task(driver.prepare_assistance())
            async def opened():
                while driver.assistance_state != 'awaiting_user': await asyncio.sleep(.02)
            await asyncio.wait_for(opened(), 3)
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                async with client.post(address + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())['error']['cause_http_status'], 503)
                    self.assertIn('先查看当前准确页面', (await response.json())['error']['message'])
                    self.assertNotIn('完成登录或验证', (await response.json())['error']['message'])
                self.assertEqual(base.dispatches, 0)
                self.assertEqual(base.attempts, 0)
                (driver.folder / 'fixture-assist-done.txt').write_bytes(b'done')
                await asyncio.wait_for(preparation, 3)
                self.assertEqual(driver.assistance_state, 'background')
                async with client.post(address + '/responses', json=self.payload()) as response:
                    self.assertEqual(response.status, 400)  # The earlier request was never queued.
                    self.assertEqual((await response.json())['error']['cause_http_status'], 409)
                async with client.post(address + '/responses', json=self.payload('after-assistance')) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['output'][0]['content'][0]['text'], 'exact 中文\r\n')
            self.assertEqual(len(seen), 1)
            (driver.folder / 'next.pending').write_bytes(b'partial private request')
            hanging_reader = asyncio.create_task(asyncio.Event().wait())
            driver.readers.append(hanging_reader)
            await asyncio.wait_for(driver.close(), 3)
            self.assertTrue(hanging_reader.cancelled())
            self.assertEqual(list(base.work.iterdir()), [])

    async def test_assistance_requires_confirmed_hidden_state_before_worker_readiness(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / 'worker-assist-invalid')
        driver = WebBrowserSession(base, startup_assistance=True)
        self.addAsyncCleanup(driver.close)
        seen = []
        with self.spawn_fixture(self.session_program('assist_unhidden'), seen):
            with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                await asyncio.wait_for(driver.prepare_assistance(), 3)
            self.assertEqual(base.dispatches, 0)
            await driver.close()
            self.assertEqual(len(seen), 1)

    async def test_hidden_startup_preparation_fences_admission_without_a_model_request(self):
        base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'}, self.root / 'startup-prepare')
        driver = WebBrowserSession(base, startup_prepare=True)
        self.addAsyncCleanup(driver.close)
        provider = WebResponsesProvider(WebResponsesBridge(service.text_route(), WebMcpEndpoint(), driver))
        provider.admission_state = 'preparing'
        address = await provider.start()
        self.addAsyncCleanup(provider.stop)
        seen = []
        with self.spawn_fixture(self.session_program('prepare_delayed'), seen):
            preparation = asyncio.create_task(driver.prepare_hidden())
            while driver.ready is None or not driver.ready.done(): await asyncio.sleep(.02)
            self.assertEqual(driver.status()['readiness'], 'preparing')
            async with ClientSession(headers={'Authorization': 'Bearer ' + provider.token}) as client:
                async with client.post(address + '/responses', json=self.payload('during-preparation')) as response:
                    self.assertEqual(response.status, 400)
                    error = (await response.json())['error']
                    self.assertEqual(error['cause_http_status'], 503)
                    self.assertEqual(error['code'], 'web_browser_preparing_before_dispatch')
                # Readiness may change after the HTTP admission check. The
                # browser's own gate must retain the same fixed classification.
                provider.admission_state = 'ready'
                async with client.post(address + '/responses', json=self.payload('preparation-race')) as response:
                    self.assertEqual(response.status, 400)
                    error = (await response.json())['error']
                    self.assertEqual(error['cause_http_status'], 503)
                    self.assertEqual(error['code'], 'web_browser_preparing_before_dispatch')
                    self.assertIn('准备完成后可发送新消息', error['message'])
                    self.assertNotIn('登录', error['message'])
                self.assertEqual((base.attempts, base.dispatches), (0, 0))
                self.assertFalse((driver.folder / 'next.json').exists())
                (driver.folder / 'fixture-prepare-done.txt').write_bytes(b'done')
                await asyncio.wait_for(preparation, 3)
                self.assertEqual(driver.status()['readiness'], 'ready')
                provider.admission_state = 'ready'
                async with client.post(address + '/responses', json=self.payload('new-after-preparation')) as response:
                    self.assertEqual(response.status, 200)
            self.assertEqual((base.attempts, base.dispatches, base.completed), (1, 1, 1))
            self.assertEqual(len(seen), 1)
            self.assertTrue(seen[0]['startupPrepare'])

    async def test_startup_preparation_requires_verified_page_or_explicit_assistance(self):
        for variant in ('prepare_bad', 'prepare_challenge'):
            with self.subTest(variant=variant):
                base = WebTextBrowserDriver({**self.settings, 'window_mode': 'background'},
                    self.root / variant)
                driver = WebBrowserSession(base, startup_prepare=True)
                self.addAsyncCleanup(driver.close)
                seen = []
                with self.spawn_fixture(self.session_program(variant), seen):
                    if variant == 'prepare_bad':
                        with self.assertRaisesRegex(ValueError, 'web_session_worker_failed_no_retry'):
                            await asyncio.wait_for(driver.prepare_hidden(), 3)
                        self.assertTrue(driver.closed)
                    else:
                        await asyncio.wait_for(driver.prepare_hidden(), 3)
                        self.assertEqual(driver.status()['readiness'], 'assistance_required')
                        self.assertEqual(driver.status()['assistance_state'], 'required')
                        self.assertEqual((base.attempts, base.dispatches), (0, 0))
                        assistance = asyncio.create_task(driver.assist('a' * 32))
                        while driver.assistance_state != 'awaiting_user': await asyncio.sleep(.02)
                        (driver.folder / 'fixture-assist-done.txt').write_bytes(b'done')
                        await asyncio.wait_for(assistance, 3)
                        self.assertEqual(driver.status()['readiness'], 'ready')
                        self.assertEqual((base.attempts, base.dispatches), (0, 0))
                        self.assertEqual((await driver(self.turn()))['content']['parts'][0], 'exact 中文\r\n')
                    self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
