"""One-shot detach against synthetic loopback lifecycle only, never inference."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

import hashlib
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=_OPERATOR_PLUGIN_ROOT
sys.path.insert(0,str(ROOT/'scripts'))
import operator_uninstall as uninstall
from operator_core import model_router_config as settings


class UninstallRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='operator-uninstall-'); self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name).resolve(); self.runtime=self.project/'.codex/feishu-codex-operator-runtime'
        self.state=self.runtime/'model-router'; self.state.mkdir(parents=True)
        (self.state/'token').write_text('a'*64,encoding='ascii')
        self.config=self.project/'config.toml'; self.original=b'model="native-fixture"\n# later user settings\n'
        self.active=0; self.stops=0; self.paths=[]
        self.router_script=self.runtime/'operator_model_router.py'
        self.service_pid=os.getpid()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.reply(False)
            def do_POST(self): self.reply(True)
            def reply(self,stop):
                owner.paths.append(self.path)
                assert self.path=='/'+'a'*64+'/v1/lifecycle'
                if stop: owner.stops+=1
                identity=hashlib.sha256((str(owner.router_script.resolve())+'\n'+str(owner.state.resolve())).encode()).hexdigest()
                raw=json.dumps({'service':identity,'pid':owner.service_pid,'status':'stopping' if stop else 'ready',
                                'diagnostics':{'timing':{'active':owner.active}}}).encode()
                self.send_response(200); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
                if stop: threading.Thread(target=owner.close_server,daemon=True).start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.close_server)
        self.port=self.server.server_port
        block=settings.BEGIN+'openai_base_url = '+json.dumps(settings.url(self.state,self.port))+'\n'+settings.END
        self.config.write_bytes(block.encode()+self.original)
        (self.state/'codex-entry.json').write_text(json.dumps({'config':str(self.config),'block':block}),encoding='utf-8')
        local=self.project/'local-appdata'
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(local)}); self.env.start(); self.addCleanup(self.env.stop)
        self.callback=local/'OpenAI/Codex/feishu-codex-final-callback/registration.json'; self.callback.parent.mkdir(parents=True)

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def test_separate_entry_migration_must_be_restored_before_global_teardown(self):
        journal=self.project/'.codex/operator-entry-migration/journal.json'
        journal.parent.mkdir()
        journal.write_text(json.dumps({'scope':'desktop_entry_only','project':str(self.project),'phase':'installed'}),encoding='utf8')
        before=self.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'restore_separate_desktop_entry_migration'):
            uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.stops,0)

    def test_detach_restores_native_bytes_and_preserves_other_runtime_registration(self):
        original=json.dumps({'schema_version':2,'runtime_dir':str(self.project/'other-runtime')}).encode()
        self.callback.write_bytes(original)
        result=uninstall.detach(self.project,self.config,self.port)
        self.assertTrue(result['routing_detached']); self.assertEqual(self.stops,1)
        self.assertEqual(self.config.read_bytes(),self.original)
        self.assertFalse((self.state/'codex-entry.json').exists()); self.assertEqual(self.callback.read_bytes(),original)

    def test_active_request_and_pending_callback_block_before_config_mutation(self):
        before=self.config.read_bytes(); self.active=1
        with self.assertRaises(ValueError): uninstall.detach(self.project,self.config,self.port)
        self.active=0
        with closing(sqlite3.connect(self.runtime/'callbacks.sqlite3')) as db, db:
            db.execute('create table final_callback_requests (state text)'); db.execute("insert into final_callback_requests values ('pending')")
        with self.assertRaises(ValueError): uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.config.read_bytes(),before); self.assertEqual(self.stops,0)

    def test_canonical_public_router_can_be_detached_using_the_same_identity(self):
        self.router_script=Path(uninstall.__file__).with_name('operator_model_router.py')
        self.assertTrue(uninstall.detach(self.project,self.config,self.port)['routing_detached'])
        self.assertEqual(self.stops,1)
        self.assertEqual(self.config.read_bytes(),self.original)

    def test_unknown_router_script_is_rejected_before_stop_or_config_changes(self):
        self.router_script=self.project/'other/operator_model_router.py'
        before=self.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'router_identity_mismatch'):
            uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.stops,0)
        self.assertEqual(self.config.read_bytes(),before)

    def test_router_process_changed_after_inspection_is_not_sent_a_stop(self):
        result=uninstall.inspect(self.project,self.config,self.port)
        self.service_pid+=1
        with self.assertRaisesRegex(ValueError,'router_identity_mismatch'):
            uninstall.service(self.state,self.port,stop=True,expected=result['router_identity'])
        self.assertEqual(self.stops,0)

    def test_changed_router_prefix_stops_without_touching_user_config(self):
        changed=b'# user changed managed area\n'+self.config.read_bytes(); self.config.write_bytes(changed)
        with self.assertRaises(ValueError): uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.config.read_bytes(),changed); self.assertEqual(self.stops,0); self.assertEqual(self.paths,[])

    def web_startup_fixture(self):
        bundle=self.project/'.codex/operator-web-startup'
        (bundle/'router').mkdir(parents=True)
        plan={'version':1,'project':str(self.project),'home':str(self.config.parent),
            'profile':str(self.project/'.codex/operator-web-service'),
            'router_state':str(bundle/'router'),'port':4318}
        (bundle/'web-startup.json').write_text(json.dumps(plan),encoding='utf-8')
        Path(plan['profile']).mkdir()
        saved=patch('operator_web_service.status',return_value={'status':'configured'})
        saved.start(); self.addCleanup(saved.stop)
        return bundle

    def test_independent_saved_web_service_blocks_before_any_legacy_teardown(self):
        profile=self.project/'.codex/operator-web-service'; profile.mkdir()
        before=self.config.read_bytes()
        self.assertFalse((self.project/'.codex/operator-web-startup').exists())
        for status in ('ready','starting','draining','unavailable','assistance'):
            with self.subTest(status=status), patch('operator_web_service.status',return_value={'status':status}) as observe:
                with self.assertRaisesRegex(ValueError,'stop_saved_web_service'):
                    uninstall.detach(self.project,self.config,self.port)
                observe.assert_called_once_with(profile)
        self.assertEqual(self.stops,0); self.assertEqual(self.paths,[])
        self.assertEqual(self.config.read_bytes(),before)

    def test_no_web_state_needs_no_optional_web_dependencies(self):
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',
            'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
            'import operator_uninstall; operator_uninstall.inspect_web_startup(Path(sys.argv[2]),Path(sys.argv[3]))',
            str(ROOT/'scripts'),str(self.project),str(self.config)],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_independent_uncertain_or_partial_profile_fails_closed(self):
        profile=self.project/'.codex/operator-web-service'; profile.mkdir()
        before=self.config.read_bytes()
        with self.assertRaises(ValueError):  # Missing profile must not mean stopped.
            uninstall.detach(self.project,self.config,self.port)
        with patch('operator_web_service.status',return_value={'status':'configured','start_available':False}):
            with self.assertRaisesRegex(ValueError,'stop_saved_web_service'):
                uninstall.detach(self.project,self.config,self.port)
        with patch('operator_web_service.status',side_effect=ValueError('uncertain_launch')):
            with self.assertRaisesRegex(ValueError,'uncertain_launch'):
                uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.config.read_bytes(),before); self.assertEqual(self.stops,0)

    def test_independent_stopped_or_never_started_service_allows_preflight(self):
        profile=self.project/'.codex/operator-web-service'; profile.mkdir()
        for status in ('stopped','configured'):
            with self.subTest(status=status), patch('operator_web_service.status',return_value={'status':status}):
                self.assertEqual(uninstall.inspect(self.project,self.config,self.port)['router_status'],'ready')
        self.assertEqual(self.stops,0)

    def test_active_web_entry_blocks_legacy_detach_before_any_mutation(self):
        bundle=self.web_startup_fixture()
        (bundle/'router/codex-entry.json').write_text('{}')
        before=self.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'deactivate_web_startup'):
            uninstall.detach(self.project,self.config,self.port)
        self.assertEqual(self.config.read_bytes(),before); self.assertEqual(self.stops,0)

    def test_pending_cold_activation_blocks_uninstall(self):
        bundle=self.web_startup_fixture()
        (bundle/'activation.json').write_text('{"phase":"armed"}')
        with patch.object(uninstall,'assert_port_free'):
            with self.assertRaisesRegex(ValueError,'cancel_web_startup'):
                uninstall.inspect_web_startup(self.project,self.config)

    def test_web_background_must_be_stopped_before_runtime_archive(self):
        self.web_startup_fixture()
        with patch.object(uninstall,'assert_port_free'), \
                patch('operator_web_service.status',return_value={'status':'ready'}):
            with self.assertRaisesRegex(ValueError,'stop_saved_web_service'):
                uninstall.inspect_web_startup(self.project,self.config)
        with patch.object(uninstall,'assert_port_free'), \
                patch('operator_web_service.status',return_value={'status':'stopped'}):
            uninstall.inspect_web_startup(self.project,self.config)


if __name__=='__main__': unittest.main()
