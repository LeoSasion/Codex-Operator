"""Synthetic file/test execution only; no Web service, native CLI or account."""

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
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0,str(_OPERATOR_PLUGIN_ROOT/'scripts'))
import operator_web_acceptance as check


class WebAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='operator-web-check-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.case=check.create_case(self.root)
        self.fixture=check.CodingFixture(self.case)

    def read_and_fix(self):
        answer=self.fixture.call('inspect_fixture',{})
        self.assertFalse(answer['isError'])
        self.assertEqual(answer['content'][0]['text'],check.SOURCE)
        self.assertFalse(self.fixture.call('replace_fixture',{'old':'* 10\r\n','new':'* 100\r\n'})['isError'])

    def test_real_read_write_test_and_final_receipt_require_all_steps(self):
        self.read_and_fix()
        answer=self.fixture.call('run_fixture_tests',{})
        self.assertFalse(answer['isError'])
        data=json.loads(answer['content'][0]['text'])
        self.assertEqual(data['exit_code'],0)
        self.assertEqual(data['tests'],5)
        marker=data['marker']
        (self.case/'final.txt').write_bytes(('\r\n'+marker+'\n').encode())
        result=check.assess(self.case,0)
        self.assertTrue(result['passed'])
        self.assertFalse(result['verification_exact'])
        self.assertEqual(result['tool_steps_accepted'],3)
        actual=json.loads((self.case/'test-execution.json').read_bytes())
        self.assertIn('Ran 5 tests',actual['stderr'])
        self.assertIn('OK',actual['stderr'])
        self.assertEqual((self.case/'work/amounts.py').read_bytes(),check.EXPECTED.encode())
        self.assertEqual((self.case/'work/test_amounts.py').read_bytes(),check.TESTS.encode())

    def test_claimed_marker_without_tools_or_execution_never_passes(self):
        (self.case/'final.txt').write_text(self.fixture.marker)
        report=check.assess(self.case,0)
        self.assertFalse(report['passed'])
        self.assertTrue(report['verification_accepted'])
        self.assertEqual(report['tool_calls'],0)
        self.assertIsNone(report['test_exit_code'])

    def test_claimed_safety_block_is_reported_as_missing_test_not_proven_denial(self):
        self.read_and_fix()
        (self.case/'final.txt').write_text('The test tool was blocked by a safety check.')
        report=check.assess(self.case,0)
        self.assertFalse(report['passed'])
        self.assertEqual(report['next_step_missing'],'run_fixture_tests')
        self.assertEqual(report['tool_steps_accepted'],2)
        self.assertIsNone(report['test_exit_code'])
        summary=check.check_summary({'status':'failed',**report})
        self.assertIn('测试工具未执行',summary)
        self.assertNotIn('安全',summary)

    def test_summary_keeps_actual_test_failure_and_final_mismatch_distinct(self):
        self.assertIn('返回失败',check.check_summary({'status':'failed','test_exit_code':7}))
        self.assertIn('最终结果或产物校验未通过',
            check.check_summary({'status':'failed','test_exit_code':0}))

    def test_verified_assistance_state_has_actionable_summary_without_claiming_permission_denial(self):
        summary=check.check_summary({'status':'failed','needs_assistance':True,'test_exit_code':None})
        self.assertIn('登录或真人验证',summary)
        self.assertIn('不会自动重做',summary)
        self.assertNotIn('审批拒绝',summary)

    def test_arbitrary_code_and_wrong_patch_cannot_execute_or_write(self):
        self.fixture.call('inspect_fixture',{})
        with patch.object(check.subprocess,'run',side_effect=AssertionError('must not execute')):
            answer=self.fixture.call('replace_fixture',{'old':'* 10','new':"* 100; __import__('os').system('bad')"})
            self.assertTrue(answer['isError'])
            self.assertTrue(self.fixture.call('run_fixture_tests',{})['isError'])
            self.assertTrue(self.fixture.call('replace_fixture',{'old':'* 10','new':'* 100'})['isError'])
        self.assertEqual((self.case/'work/amounts.py').read_bytes(),check.SOURCE.encode())

    def test_tampered_tests_or_source_never_reach_execution(self):
        self.read_and_fix()
        (self.case/'work/test_amounts.py').write_text('raise RuntimeError("must not execute")')
        with patch.object(check.subprocess,'run',side_effect=AssertionError('must not execute')):
            self.assertTrue(self.fixture.call('run_fixture_tests',{})['isError'])
        self.assertFalse((self.case/'test-execution.json').exists())

    def test_nonzero_native_test_exit_is_retained_as_failure(self):
        self.read_and_fix()
        class Result:
            returncode=7
            stdout=b''
            stderr=b'fixed synthetic failure'
        with patch.object(check.subprocess,'run',return_value=Result()):
            self.assertTrue(self.fixture.call('run_fixture_tests',{})['isError'])
        (self.case/'final.txt').write_text(self.fixture.marker)
        report=check.assess(self.case,0)
        self.assertFalse(report['passed'])
        self.assertEqual(report['test_exit_code'],7)

    def test_repeated_operation_and_second_fixture_process_cannot_replay(self):
        self.assertFalse(self.fixture.call('inspect_fixture',{})['isError'])
        self.assertTrue(self.fixture.call('inspect_fixture',{})['isError'])
        self.assertTrue(self.fixture.call('replace_fixture',{'old':'* 10','new':'* 100'})['isError'])
        with self.assertRaises(FileExistsError):
            check.CodingFixture(self.case)

    def test_paths_and_unknown_operations_are_rejected(self):
        self.assertTrue(self.fixture.call('inspect_fixture',{'path':'../outside'})['isError'])
        self.assertFalse((self.root/'outside').exists())
        self.assertTrue(self.fixture.call('shell',{'command':'irrelevant'})['isError'])
        rows=(self.case/'tool-execution.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(rows[-1])['operation'],'unknown')

    def test_cli_nonzero_and_changed_artifact_cannot_be_success(self):
        self.read_and_fix();self.fixture.call('run_fixture_tests',{})
        (self.case/'final.txt').write_text(self.fixture.marker)
        self.assertFalse(check.assess(self.case,1)['passed'])
        (self.case/'work/amounts.py').write_text('changed after execution')
        self.assertFalse(check.assess(self.case,0)['passed'])

    def test_isolated_configuration_excludes_project_docs_and_general_execution(self):
        values=check.cli_settings(self.case,'api/chatgpt-web/fixture','http://127.0.0.1:1/private')
        check.write_cli_config(self.case,values)
        config=tomllib.loads((self.case/'home/config.toml').read_text(encoding='utf-8'))
        self.assertEqual(config['project_doc_max_bytes'],0)
        self.assertEqual(config['approval_policy'],'never')
        self.assertFalse(any(config['features'].values()))
        server=config['mcp_servers']['operator_check']
        self.assertTrue(server['required'])
        self.assertEqual(set(config['mcp_servers']),{'operator_check'})
        self.assertEqual(set(server['tools']),{'replace_fixture','run_fixture_tests'})
        self.assertEqual(server['args'][-1],str(self.case))
        self.assertEqual(config['model_providers']['operator_check']['request_max_retries'],0)
        original=(self.case/'home/config.toml').read_bytes()
        with self.assertRaises(FileExistsError):
            check.write_cli_config(self.case,values)
        self.assertEqual((self.case/'home/config.toml').read_bytes(),original)


class McpEvidenceTests(unittest.TestCase):
    def health(self,events=(),*,requests=0,sequence=0,generation='a'*32,dropped=0):
        rows=[{'sequence':index,'event':kind,'stage':stage,'method':'tools/call','tool':tool,'code':code}
            for index,(kind,stage,tool,code) in enumerate(events,dropped+1)]
        return {'active':False,'requests':requests,'transport':{'active_turn':None,
            'last_turn':{'sequence':sequence} if sequence else None},
            'mcp':{'generation':generation,'eventsTotal':dropped+len(rows),
                'eventsDropped':dropped,'events':rows}}

    def test_two_received_calls_do_not_establish_a_third_call_or_upstream_denial(self):
        events=[('received','rpc','operator_begin',None),('reply_prepared','serialize','operator_begin',None)]
        events+=2*[('received','rpc','operator_call',None),('reply_prepared','serialize','operator_call',None)]
        result=check.mcp_evidence(self.health(),self.health(events,requests=3,sequence=1),3)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['operator_begin_received'],1)
        self.assertEqual(result['operator_call_received'],2)
        self.assertEqual(result['operator_call_replies_prepared'],2)
        self.assertEqual(result['operator_call_rejections'],[])
        self.assertNotIn('upstream_denial',result)

    def test_protocol_rejection_is_distinct_from_native_execution(self):
        events=[('received','rpc','operator_call',None),
            ('rejected','tool_dispatch','operator_call','web_mcp_turn_rejected')]
        result=check.mcp_evidence(self.health(),self.health(events,requests=1,sequence=1),1)
        self.assertEqual(result['operator_call_received'],1)
        self.assertEqual(result['operator_call_replies_prepared'],0)
        self.assertEqual(result['operator_call_rejections'],
            [{'stage':'tool_dispatch','code':'web_mcp_turn_rejected'}])

    def test_previous_rejection_is_not_attributed_to_the_current_check(self):
        events=[('rejected','session','operator_call','web_mcp_session_expired')]
        before=self.health(events,requests=2,sequence=1)
        after=self.health(events+[('received','rpc','operator_call',None)],requests=3,sequence=2)
        result=check.mcp_evidence(before,after,1)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['operator_call_rejections'],[])

    def test_restart_concurrency_and_missing_projection_remain_unavailable(self):
        before=self.health()
        for after in ({},self.health(requests=1,sequence=1,generation='b'*32),
                self.health(requests=2,sequence=1),self.health(requests=1,sequence=2)):
            with self.subTest(after=after):
                self.assertEqual(check.mcp_evidence(before,after,1)['status'],'unavailable')

    def test_dropped_events_cannot_prove_no_rejection(self):
        after=self.health([('received','rpc','operator_call',None)],requests=1,sequence=1,dropped=129)
        self.assertEqual(check.mcp_evidence(self.health(),after,1)['status'],'history_incomplete')

    def test_untrusted_labels_and_inconsistent_sequence_never_escape(self):
        for field,value in (('code','private arbitrary message'),('tool','private_tool'),
                ('stage','private_path'),('sequence',True),('sequence',9)):
            after=self.health([('rejected','rpc','operator_call',None)],requests=1,sequence=1)
            after['mcp']['events'][0][field]=value
            result=check.mcp_evidence(self.health(),after,1)
            self.assertEqual(result,{'status':'unavailable','scope':'local_mcp_receive_only'})


if __name__=='__main__':
    unittest.main()
