"""Explicit synthetic coding check through the managed Web route and native CLI.

No Desktop task, global configuration, credentials, service start or permission
change. The native CLI owns tool calls; a narrow MCP fixture owns only two new
synthetic files. Results are dated evidence, never a business-answer transport.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tomllib

from operator_core.responses_capabilities import RouterError
from operator_core.responses_tool_adapter import dumps, loads
from operator_core.web_browser_driver import private_directory
from operator_web_service import (checked_path, file_digest, load_profile, current_record,
    observe, route_preview, read_json, read_bytes)

SOURCE = '# 合成检查：保留注释与换行。\r\ndef to_cents(whole_units):\r\n    return whole_units * 10\r\n'
EXPECTED = SOURCE.replace('* 10\r\n', '* 100\r\n')
TESTS = '''import unittest
from amounts import to_cents
class ConversionTests(unittest.TestCase):
    def test_zero(self): self.assertEqual(to_cents(0), 0)
    def test_one(self): self.assertEqual(to_cents(1), 100)
    def test_many(self): self.assertEqual(to_cents(37), 3700)
    def test_negative(self): self.assertEqual(to_cents(-12), -1200)
    def test_range(self):
        for value in range(-100, 101): self.assertEqual(to_cents(value), value * 100)
'''
EMPTY = {'type':'object','properties':{},'additionalProperties':False}
TOOLS = [
    {'name':'inspect_fixture','description':'Read the one disposable amounts.py source file. No path input.',
     'inputSchema':EMPTY,'annotations':{'readOnlyHint':True,'openWorldHint':False}},
    {'name':'replace_fixture','description':'Replace one unique literal substring in amounts.py; only the exact reviewed multiplier fix is admitted. No arbitrary code or paths.',
     'inputSchema':{'type':'object','properties':{'old':{'type':'string'},'new':{'type':'string'}},
         'required':['old','new'],'additionalProperties':False},
     'annotations':{'readOnlyHint':False,'destructiveHint':False,'idempotentHint':False,'openWorldHint':False}},
    {'name':'run_fixture_tests','description':'Run the fixed local Python unit tests on the validated synthetic source. No command, path or network input.',
     'inputSchema':EMPTY,'annotations':{'readOnlyHint':False,'destructiveHint':False,
         'idempotentHint':False,'openWorldHint':False}}]


def require(ok, code):
    if not ok:
        raise RouterError(code)


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        handle.write(dumps(value))


def create_case(parent):
    checked_path(parent, directory=True)
    case = parent / ('check-' + secrets.token_hex(16))
    private_directory(case)
    for name in ('home','work'):
        private_directory(case/name)
    (case/'work/amounts.py').write_bytes(SOURCE.encode('utf-8'))
    (case/'work/test_amounts.py').write_bytes(TESTS.encode('utf-8'))
    save(case/'case.json',{'version':1,'marker':'OPERATOR_WEB_CHECK_'+secrets.token_hex(16)})
    return case


class CodingFixture:
    def __init__(self, case):
        self.case = checked_path(case,directory=True)
        self.work = checked_path(case/'work',directory=True)
        self.marker = read_json(case/'case.json')['marker']
        require(isinstance(self.marker,str) and len(self.marker)==51 and self.marker.startswith('OPERATOR_WEB_CHECK_'),
            'web_check_fixture_invalid')
        # A second MCP process must never restart the fixture sequence.
        with (case/'fixture-started').open('xb') as handle:
            handle.write(b'started once')
        self.stage, self.failed = 0, False

    def call(self, name, args):
        accepted, result, exit_code = False, 'fixture_operation_rejected_no_retry', None
        try:
            require(not self.failed and type(args) is dict,'web_check_fixture_failed')
            source = checked_path(self.work/'amounts.py')
            tests = checked_path(self.work/'test_amounts.py')
            require(tests.read_bytes()==TESTS.encode('utf-8'),'web_check_tests_changed')
            raw = source.read_bytes()
            if self.stage==0 and name=='inspect_fixture' and args=={}:
                require(raw==SOURCE.encode('utf-8'),'web_check_source_changed')
                result,accepted = raw.decode('utf-8'),True
            elif self.stage==1 and name=='replace_fixture' and set(args)=={'old','new'}:
                old,new = args['old'],args['new']
                require(isinstance(old,str) and isinstance(new,str) and 0<len(old)<=256 and len(new)<=256,
                    'web_check_patch_invalid')
                require(raw==SOURCE.encode('utf-8') and SOURCE.count(old)==1
                    and SOURCE.replace(old,new,1)==EXPECTED,'web_check_patch_invalid')
                source.write_bytes(EXPECTED.encode('utf-8'))
                result,accepted = 'Exact patch written. Call run_fixture_tests.',True
            elif self.stage==2 and name=='run_fixture_tests' and args=={}:
                require(raw==EXPECTED.encode('utf-8'),'web_check_source_changed')
                # Only the exact reviewed source above can reach execution.
                process = subprocess.run([sys.executable,'-I','-S','-B','-m','unittest','discover',
                    '-s',str(self.work),'-p','test_amounts.py','-v'],stdin=subprocess.DEVNULL,
                    capture_output=True,timeout=15,cwd=self.work,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                exit_code = process.returncode
                require(len(process.stdout)+len(process.stderr)<=65536,'web_check_test_output_bound')
                save(self.case/'test-execution.json',{'exit_code':exit_code,
                    'python_sha256':file_digest(Path(sys.executable).resolve()),
                    'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'tests_sha256':hashlib.sha256(tests.read_bytes()).hexdigest(),
                    'stdout':process.stdout.decode('utf-8','replace'),
                    'stderr':process.stderr.decode('utf-8','replace')})
                require(exit_code==0 and source.read_bytes()==raw,'web_check_tests_failed')
                result,accepted = dumps({'exit_code':0,'tests':5,'marker':self.marker}),True
        except Exception:
            accepted = False
        self.failed = self.failed or not accepted
        if accepted:
            self.stage += 1
        with (self.case/'tool-execution.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(dumps({'step':self.stage,'operation':name if name in {t['name'] for t in TOOLS} else 'unknown',
                'accepted':accepted,'test_exit_code':exit_code})+'\n')
        return {'isError':not accepted,'content':[{'type':'text','text':result}]}


def fixture_main(case):
    fixture = CodingFixture(case)
    for line in sys.stdin.buffer:
        require(len(line)<=65536,'web_check_fixture_input_bound')
        value = loads(line)
        if 'id' not in value:
            continue
        method,params = value.get('method'),value.get('params',{})
        if method=='initialize':
            result={'protocolVersion':params['protocolVersion'],'capabilities':{'tools':{}},
                'serverInfo':{'name':'operator-coding-check','version':'1'}}
        elif method=='tools/list':
            result={'tools':TOOLS}
        elif method=='tools/call':
            result=fixture.call(params.get('name'),params.get('arguments'))
        elif method=='ping':
            result={}
        else:
            result={'isError':True,'content':[{'type':'text','text':'unsupported_fixture_method'}]}
        sys.stdout.buffer.write((dumps({'jsonrpc':'2.0','id':value['id'],'result':result})+'\n').encode('utf-8'))
        sys.stdout.buffer.flush()


def assess(case, cli_exit):
    from operator_responses_eval import verify_final_message
    records=[]
    path=case/'tool-execution.jsonl'
    if path.exists():
        records=[loads(line) for line in read_bytes(path).splitlines()]
    marker=read_json(case/'case.json')['marker']
    final=verify_final_message(case/'final.txt',marker,'marker_line_v1')
    tests=read_json(case/'test-execution.json') if (case/'test-execution.json').exists() else {}
    operations=[r.get('operation') for r in records]
    expected=[t['name'] for t in TOOLS]
    passed=(cli_exit==0 and operations==expected
        and all(r.get('accepted') is True for r in records) and tests.get('exit_code')==0
        and (case/'work/amounts.py').read_bytes()==EXPECTED.encode('utf-8')
        and (case/'work/test_amounts.py').read_bytes()==TESTS.encode('utf-8')
        and final['verification_accepted'])
    missing=None
    if operations==expected[:len(records)] and all(r.get('accepted') is True for r in records):
        if len(records)<len(expected): missing=expected[len(records)]
    # A model saying a tool was blocked is not a tool call or a proven rejection.
    # Report only the locally observed execution boundary.
    return {'passed':passed,'next_step_missing':missing,
        'tool_calls':len(records),'tool_steps_accepted':sum(r.get('accepted') is True for r in records),
        'test_exit_code':tests.get('exit_code'),'cli_exit_code':cli_exit,**final}


def check_summary(receipt):
    if receipt['status']=='passed':
        return '原生客户端已完成读取、准确修改和实际测试，合成项目的五项测试通过；Desktop 日常界面仍需单独验收。'
    if receipt.get('needs_assistance') is True:
        return '网页需要完成登录或真人验证，本次检查已结束；请在现有辅助窗口处理，已有连接继续沿用，失败请求不会自动重做。'
    if receipt.get('cli_exit_code')==0 and receipt.get('next_step_missing')=='run_fixture_tests':
        return '文件读取和精确修改已完成，但测试工具未执行；本次检查未通过，实际记录已保留，未重做请求。'
    if receipt.get('test_exit_code') is not None and receipt['test_exit_code']!=0:
        return '测试工具已实际执行并返回失败；本次检查未通过，已保留退出码和记录，未重做请求。'
    if receipt.get('test_exit_code')==0:
        return '实际测试已通过，但最终结果或产物校验未通过；已保留差异记录，未把本次检查判为成功。'
    return '本次完整编码检查未通过，已保留实际执行记录，未重做请求；请由助手核对未完成的步骤。'


def mcp_evidence(before, after, client_requests):
    """Attribute a bounded endpoint interval to one otherwise idle check.

    These counts locate the local receive boundary. They never prove a
    platform denial, model intent, remote receipt, or execution success.
    """
    from operator_core.web_mcp_transport import _MCP_DIAGNOSTIC_CODES, _MCP_DIAGNOSTIC_METHODS
    unknown={'status':'unavailable','scope':'local_mcp_receive_only'}
    def count(value): return type(value) is int and 0<=value<=2**53
    def sequence(health):
        require(health.get('active') is False,'web_check_diagnostics_busy')
        transport=health['transport']
        require(transport['active_turn'] is None,'web_check_diagnostics_busy')
        last=transport['last_turn']
        seq=0 if last is None else last['sequence']
        require(count(seq),'web_check_diagnostics_invalid')
        return seq
    try:
        first,last=before['mcp'],after['mcp']
        require(isinstance(first['generation'],str) and re.fullmatch('[0-9a-f]{32}',first['generation'])
            and first['generation']==last['generation'],'web_check_diagnostics_generation_changed')
        require(all(count(v) for v in (before['requests'],after['requests'],client_requests,
            first['eventsTotal'],last['eventsTotal'],last['eventsDropped'])),'web_check_diagnostics_invalid')
        require(after['requests']-before['requests']==client_requests and client_requests>0
            and sequence(after)==sequence(before)+1,'web_check_diagnostics_ambiguous')
        require(last['eventsTotal']>=first['eventsTotal'],'web_check_diagnostics_invalid')
        events=last['events']
        require(isinstance(events,list) and len(events)<=128
            and last['eventsTotal']-last['eventsDropped']==len(events),'web_check_diagnostics_invalid')
        if last['eventsDropped']>first['eventsTotal']:
            return {**unknown,'status':'history_incomplete'}
        allowed_events={'received','rejected','reply_prepared','cancelled'}
        allowed_stages={'http','body','rpc','session','tool_arguments','tool_dispatch','serialize'}
        for index,event in enumerate(events,last['eventsDropped']+1):
            require(isinstance(event,dict) and set(event)=={'sequence','event','stage','method','tool','code'}
                and type(event['sequence']) is int and event['sequence']==index
                and event['event'] in allowed_events and event['stage'] in allowed_stages
                and event['method'] in _MCP_DIAGNOSTIC_METHODS|{'other'}
                and event['tool'] in (None,'operator_begin','operator_call')
                and event['code'] in _MCP_DIAGNOSTIC_CODES|{None,'web_mcp_other_rejection'},
                'web_check_diagnostics_invalid')
        selected=[e for e in events if e['sequence']>first['eventsTotal']]
        calls=[e for e in selected if e['tool']=='operator_call']
        return {'status':'complete','scope':'local_mcp_receive_only',
            'operator_begin_received':sum(e['event']=='received' and e['tool']=='operator_begin' for e in selected),
            'operator_call_received':sum(e['event']=='received' for e in calls),
            'operator_call_replies_prepared':sum(e['event']=='reply_prepared' for e in calls),
            'operator_call_cancelled':sum(e['event']=='cancelled' for e in calls),
            'operator_call_rejections':[{'stage':e['stage'],'code':e['code']} for e in calls if e['event']=='rejected'],
            'other_rejections':sum(e['event']=='rejected' and e['tool']!='operator_call' for e in selected)}
    except (RouterError,KeyError,TypeError,ValueError):
        return unknown


def cli_settings(case, slug, base_url):
    settings={'model':slug,'model_provider':'operator_check','model_reasoning_effort':'high',
        'model_catalog_json':str(case/'catalog.json'),'approval_policy':'never',
        'web_search':'disabled','project_doc_max_bytes':0,'analytics.enabled':False,
        'skills.include_instructions':False,
        'model_providers.operator_check.name':'Operator coding check',
        'model_providers.operator_check.base_url':base_url,
        'model_providers.operator_check.wire_api':'responses',
        'model_providers.operator_check.request_max_retries':0,
        'model_providers.operator_check.stream_max_retries':0,
        'model_providers.operator_check.supports_websockets':False,
        'mcp_servers.operator_check.command':sys.executable,
        'mcp_servers.operator_check.args':['-B',str(Path(__file__).resolve()),'fixture','--case',str(case)],
        'mcp_servers.operator_check.required':True,
        # These two fixed operations are explicitly admitted for this disposable
        # check only. They cannot edit/run arbitrary code or host files. This
        # never establishes Desktop approval/denial behavior or changes it.
        'mcp_servers.operator_check.tools.replace_fixture.approval_mode':'approve',
        'mcp_servers.operator_check.tools.run_fixture_tests.approval_mode':'approve'}
    for feature in ('plugins','remote_plugin','shell_tool','view_image','image_generation',
            'goals','multi_agent','multi_agent_v2','standalone_web_search','enable_mcp_apps',
            'skill_search','skill_mcp_dependency_install'):
        settings['features.'+feature]=False
    return settings


def write_cli_config(case, settings):
    # The isolated home is private and new. No ancestor AGENTS or user/plugin
    # configuration belongs in a synthetic coding request.
    raw='\n'.join(key+'='+json.dumps(value,ensure_ascii=True) for key,value in settings.items())+'\n'
    tomllib.loads(raw)
    with (case/'home/config.toml').open('x',encoding='utf-8') as handle:
        handle.write(raw)


async def verify(profile):
    from aiohttp import web
    from operator_core.beeper_relay import discover_codex_executable
    from operator_core.model_registry import ModelRegistry
    from operator_core.model_router import ModelRouter
    from operator_responses_eval import collect_child, isolated_environment, parse_cli_version
    profile,config=load_profile(profile)
    # Never start a Web service just to inspect/check it.
    result,live=await asyncio.to_thread(observe,profile,config,current_record(profile))
    require(live is not None and result['status']=='ready' and not result['active'],'web_check_ready_service_required')
    executable=discover_codex_executable()
    version_process=await asyncio.create_subprocess_exec(str(executable),'--version',
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        version_stdout,_=await asyncio.wait_for(version_process.communicate(),10)
    finally:
        if version_process.returncode is None:
            version_process.terminate();await version_process.wait()
    version=parse_cli_version(version_stdout,version_process.returncode)
    directory=profile/'checks'
    if not directory.exists():
        private_directory(directory)
    checked_path(directory,directory=True)
    # One check at a time. Native inference holds neither manager's lifecycle
    # lock nor any request-controlling task. A running service stays controllable.
    gate=directory/'active-check'
    with gate.open('xb') as handle:
        handle.write(b'no automatic replay')
    case=create_case(directory)
    child=communication=runner=None
    receipt={'version':1,'started_at':datetime.now(timezone.utc).isoformat(),'status':'failed',
        'scope':'synthetic_native_cli_coding','desktop_acceptance':False,'retry_count':0,
        'cli_version':version,'cli_sha256':file_digest(executable),'source':config['runtime']['sources'],
        'check_source_sha256':file_digest(Path(__file__).resolve()),'client_requests':0}
    before_health=live[2]
    router=None
    begin=time.monotonic()
    try:
        catalog=read_json(Path(__file__).with_name('operator_core')/'beeper_model_catalog.json')
        registry=ModelRegistry({'version':2,'models':[]},catalog)
        router=ModelRouter(registry,secrets.token_hex(32),web_profile=profile)
        expected=await asyncio.to_thread(route_preview,profile)
        await router.bind_web_service(expected)
        receipt.update(expected)
        slug=next(iter(router.registry.routes))
        @web.middleware
        async def admission(request,handler):
            if request.method!='POST' or request.path!=router.prefix+'/responses':
                return web.json_response({'error':'check_responses_only'},status=404)
            receipt['client_requests']+=1
            if receipt['client_requests']>6:
                return web.json_response({'error':'check_request_budget_no_retry'},status=429)
            return await handler(request)
        app=router.app();app.middlewares.insert(0,admission)
        runner=web.AppRunner(app,access_log=None,shutdown_timeout=3)
        await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        native={'models':[{**catalog['models'][0],'slug':'synthetic-native'}]}
        save(case/'catalog.json',router.registry.merge(native))
        settings=cli_settings(case,slug,f'http://127.0.0.1:{port}'+router.prefix)
        write_cli_config(case,settings)
        command=[str(executable),'exec','--ephemeral','--strict-config','--ignore-rules',
            '--skip-git-repo-check','--sandbox','read-only','--color','never','-C',str(case/'work'),
            '--output-last-message',str(case/'final.txt')]
        command+=['This is an authorized, disposable coding check. Use only the three registered operator_check MCP tools, '
            'directly and one at a time. Inspect the existing amounts.py using inspect_fixture. '
            'Fix its whole-units-to-cents multiplier using one unique literal replacement with replace_fixture, '
            'preserving all other bytes. Then actually call run_fixture_tests and read its result. '
            'Do not claim tests ran without their result. If any operation fails, stop without retrying. '
            'If all tests pass, reply only with the exact OPERATOR_WEB_CHECK_ marker returned by the test tool. '
            'At most eight empty LF/CRLF lines may surround that final marker; no other text.']
        save(case/'started.json',{'cli_sha256':receipt['cli_sha256'],'may_have_started':True})
        child=await asyncio.create_subprocess_exec(*command,cwd=case/'work',
            env=isolated_environment(case/'home'),stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        communication=asyncio.create_task(collect_child(child))
        stdout,stderr=await asyncio.wait_for(asyncio.shield(communication),240)
        (case/'native.stdout.log').write_bytes(stdout);(case/'native.stderr.log').write_bytes(stderr)
        receipt.update(assess(case,child.returncode))
        receipt['status']='passed' if receipt['passed'] else 'failed'
    except asyncio.TimeoutError:
        receipt['failure_code']='web_check_timeout_no_retry'
    except Exception:
        receipt['failure_code']='web_check_stopped_no_retry'
    finally:
        if child is not None and child.returncode is None:
            child.terminate()
            await child.wait()
        if communication is not None:
            outcome=await asyncio.gather(communication,return_exceptions=True)
            if isinstance(outcome[0],tuple):
                for name,data in zip(('native.stdout.log','native.stderr.log'),outcome[0]):
                    if not (case/name).exists(): (case/name).write_bytes(data)
        if runner is not None: await runner.cleanup()
        try:
            final_state,final_live=await asyncio.to_thread(observe,profile,config,current_record(profile))
            receipt['service_state']=final_state['status']
            receipt['needs_assistance']=final_state.get('needs_assistance') is True
            receipt['mcp_evidence']=mcp_evidence(before_health,final_live[2],receipt['client_requests'])
        except Exception:
            receipt['mcp_evidence']={'status':'unavailable','scope':'local_mcp_receive_only'}
        receipt['elapsed_seconds']=round(time.monotonic()-begin,3)
        if router is not None: receipt['router_failures']=router.failure_count
        save(case/'receipt.json',receipt)
        # Durable receipt precedes clearing the check lock. A crash leaves it for
        # explicit review; it never triggers an automatic rerun.
        gate.unlink()
    passed=receipt['status']=='passed'
    return {'status':'passed' if passed else 'failed','summary':check_summary(receipt),
        'scope':'synthetic_native_cli_coding','tool_steps_accepted':receipt.get('tool_steps_accepted',0),
        'next_step_missing':receipt.get('next_step_missing'),
        'mcp_evidence':receipt['mcp_evidence'],
        'needs_assistance':receipt.get('needs_assistance',False),
        'test_exit_code':receipt.get('test_exit_code'),'desktop_acceptance':False,'receipt':str(case/'receipt.json')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('verify','fixture'))
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--case',type=Path)
    args=parser.parse_args()
    if args.action=='fixture':
        require(args.case is not None and args.profile is None,'web_check_arguments_invalid')
        fixture_main(args.case)
        return 0
    require(args.profile is not None and args.case is None,'web_check_arguments_invalid')
    try:
        result=asyncio.run(verify(args.profile))
    except Exception:
        result={'status':'unavailable','summary':'完整编码检查尚未开始或准备未完成；请先核对现有后台状态和上次检查记录，无需重新创建连接。'}
    print(dumps(result))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
