"""Cold-launch ownership and single-attempt boundaries; no live account or service."""

# Resolve the canonical plugin independently of this test's module directory.
from pathlib import Path as _OperatorTestPath
import sys as _operator_test_sys
_OPERATOR_PLUGIN_ROOT = next(parent for parent in _OperatorTestPath(__file__).resolve().parents
    if (parent / ".codex-plugin/plugin.json").is_file()
    and (parent / "scripts/source_route_contract.py").is_file())
_operator_test_sys.path.insert(0, str(_OPERATOR_PLUGIN_ROOT / "development"))
from run_tests import prepare_test_imports as _prepare_test_imports
_prepare_test_imports(_OPERATOR_PLUGIN_ROOT)

from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

ROOT = _OPERATOR_PLUGIN_ROOT
sys.path.insert(0, str(ROOT/'scripts'))
import operator_web_startup as startup


class WebStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='operator-web-startup-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root/'.codex').mkdir()
        self.home = self.root/'home'; self.home.mkdir()
        (self.home/'config.toml').write_bytes(b'model = "native"\n')
        self.profile = self.root/'.codex/operator-web-service'; self.profile.mkdir()
        (self.profile/'profile.json').write_text('{}')
        mocked = patch.object(startup.manager, 'load_profile', return_value=(self.profile, {}))
        mocked.start(); self.addCleanup(mocked.stop)
        self.bundle = self.root/'.codex/operator-web-startup'
        self.path = self.bundle/startup.PLAN

    def prepare(self):
        return startup.prepare(self.root, self.profile, self.home, 4318)

    def write(self, path, value):
        startup.manager.service.write_json(path, value)

    def test_prepare_repeat_preserves_config_and_has_no_service_side_effects(self):
        with patch.object(startup.manager, 'spawn_child') as spawn:
            self.assertFalse(self.prepare()['reused'])
            snapshot = {p.name:p.read_bytes() for p in self.bundle.iterdir() if p.is_file()}
            self.assertTrue(self.prepare()['reused'])
            self.assertEqual(snapshot, {p.name:p.read_bytes() for p in self.bundle.iterdir() if p.is_file()})
            spawn.assert_not_called()
        self.assertEqual((self.home/'config.toml').read_bytes(), b'model = "native"\n')
        self.assertFalse((self.home/'auth.json').exists())

    def test_tampering_is_rejected_before_any_start(self):
        self.prepare()
        original = self.path.read_bytes()
        plan = json.loads(original)
        for changes in ({'router_state':str(self.root)}, {'profile':str(self.home)},
                        {'runtime':{}}, {'port':True}, {'startup_script':'../bad.ps1'}):
            with self.subTest(changes=changes):
                self.write(self.path, {**plan, **changes})
                with patch.object(startup.manager, 'start') as start:
                    with self.assertRaises((RuntimeError, ValueError)):
                        startup.start(self.path, services_only=True)
                    start.assert_not_called()
        self.path.write_bytes(original)
        (self.bundle/startup.SCRIPT).write_text('exit 0')
        with self.assertRaisesRegex(ValueError, 'workflow_changed'):
            startup.load(self.path)

    def test_changed_profile_and_nonempty_registry_rejected(self):
        self.prepare()
        (self.profile/'profile.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'profile_changed'):
            startup.load(self.path)
        (self.profile/'profile.json').write_text('{}')
        self.write(self.bundle/'router/registry.json', {'version':2,'models':[{}]})
        with self.assertRaisesRegex(ValueError, 'dedicated_router_required'):
            startup.load(self.path)

    def test_normal_start_requires_exact_active_entry(self):
        self.prepare()
        with patch.object(startup.manager, 'start') as start:
            with self.assertRaisesRegex(ValueError, 'entry_not_active'):
                startup.start(self.path)
            start.assert_not_called()

    def test_old_call_only_entry_cannot_start_without_voice_websocket_route(self):
        self.prepare()
        plan = startup.load(self.path)
        state = Path(plan['router_state'])
        old = startup.config.managed_entry_blocks(state, plan['port'])[1]
        target = self.home/'config.toml'
        target.write_bytes(old + b'model="native"\n')
        self.write(state/'codex-entry.json', {'config': str(target.resolve()), 'block': old.decode()})
        with patch.object(startup.manager, 'start') as start:
            with self.assertRaisesRegex(startup.config.RouterError, 'legacy_router_voice_route_unprotected'):
                startup.start(self.path)
            start.assert_not_called()
        self.assertTrue(startup.entry_active(plan))

    def test_service_start_once_then_observe_and_bind(self):
        self.prepare()
        with patch.object(startup.manager, 'start', return_value={'status':'starting'}) as start, \
                patch.object(startup.manager, 'status', return_value={'status':'ready','active':False}) as status, \
                patch.object(startup, 'start_router') as launch, \
                patch.object(startup.router, 'bind_web') as bind, patch.object(startup.time, 'sleep'):
            result = startup.start(self.path, services_only=True)
            self.assertFalse(result['entry_active'])
            self.assertEqual(result['model_requests'], 0)
            start.assert_called_once_with(self.profile); status.assert_called_once_with(self.profile)
            launch.assert_called_once(); bind.assert_called_once()

    def test_unready_web_does_not_start_router_or_retry(self):
        self.prepare()
        with patch.object(startup.manager, 'start', return_value={'status':'unavailable'}) as start, \
                patch.object(startup, 'start_router') as launch:
            with self.assertRaisesRegex(ValueError, 'saved_service_not_ready'):
                startup.start(self.path, services_only=True)
            start.assert_called_once(); launch.assert_not_called()

    def test_router_refuses_uncertain_receipt_without_spawn(self):
        self.prepare(); plan = startup.load(self.path)
        self.write(self.bundle/'router-launch.json', {'phase':'uncertain'})
        with patch.object(startup, 'checked_router', side_effect=URLError('absent')), \
                patch.object(startup.router, 'reserve_inactive_port', return_value=nullcontext()), \
                patch.object(startup.manager, 'spawn_child') as spawn:
            with self.assertRaisesRegex(ValueError, 'uncertain_no_retry'):
                startup.start_router(plan, self.bundle)
            spawn.assert_not_called()

    def test_router_spawn_failure_records_uncertainty_once(self):
        self.prepare(); plan = startup.load(self.path)
        with patch.object(startup, 'checked_router', side_effect=URLError('absent')), \
                patch.object(startup.router, 'reserve_inactive_port', return_value=nullcontext()), \
                patch.object(startup.manager, 'spawn_child', side_effect=OSError('fixture')) as spawn:
            with self.assertRaises(OSError): startup.start_router(plan, self.bundle)
            spawn.assert_called_once()
        self.assertEqual(startup.manager.read_json(self.bundle/'router-launch.json')['phase'], 'uncertain')

    def test_running_router_must_have_same_source_and_process_birth(self):
        self.prepare(); plan = startup.load(self.path)
        result = {'status':'ready','pid':321,'diagnostics':{
            'web_profile_identity':startup.router.web_profile_identity(self.profile)}}
        receipt = {'phase':'ready','runtime':plan['runtime'],
            'worker':{'pid':321,'birth':'old','executable':plan['runtime']['worker_python']}}
        self.write(self.bundle/'router-launch.json', receipt)
        with patch.object(startup.router, 'control', return_value=result), \
                patch.object(startup.manager, 'process_identity', return_value={**receipt['worker'],'birth':'new'}):
            with self.assertRaisesRegex(ValueError, 'worker_identity_changed'):
                startup.checked_router(plan)
        receipt['runtime'] = {}; self.write(self.bundle/'router-launch.json', receipt)
        with patch.object(startup.router, 'control', return_value=result):
            with self.assertRaisesRegex(ValueError, 'ownership_changed'): startup.checked_router(plan)

    def test_stop_marks_stopped_only_after_exit_and_port_reservation(self):
        self.prepare()
        self.write(self.bundle/'router-launch.json', {'phase':'ready','worker':{'pid':321}})
        with patch.object(startup, 'checked_router'), \
                patch.object(startup.router, 'control', return_value={'status':'stopping'}) as control, \
                patch.object(startup.manager, 'process_identity', return_value=None), \
                patch.object(startup.router, 'reserve_inactive_port', return_value=nullcontext()) as reserve:
            self.assertEqual(startup.stop(self.path)['status'], 'stopped')
            control.assert_called_once_with(self.bundle/'router', 4318, stop=True)
            reserve.assert_called_once_with(4318)
        self.assertEqual(startup.manager.read_json(self.bundle/'router-launch.json')['phase'], 'stopped')

    def test_active_route_cannot_be_stopped(self):
        self.prepare()
        with patch.object(startup, 'entry_active', return_value=True), patch.object(startup.router, 'control') as control:
            with self.assertRaisesRegex(ValueError, 'deactivate_before_stop'): startup.stop(self.path)
            control.assert_not_called()

    def test_read_only_status_does_not_launch_or_create_journals(self):
        self.prepare()
        with patch.object(startup, 'checked_router', side_effect=URLError('absent')), \
                patch.object(startup.manager, 'status', return_value={'status':'configured'}), \
                patch.object(startup.manager, 'spawn_child') as spawn:
            self.assertFalse(startup.status(self.path)['router_ready'])
            spawn.assert_not_called()
        self.assertFalse((self.bundle/'router-launch.json').exists())

    def arm(self):
        with patch.object(startup, 'checked_router', return_value={'diagnostics':{'web_route_bound':True}}), \
                patch.object(startup.config, 'ensure_recovery_shortcut') as recovery:
            result = startup.arm_entry(self.path)
            recovery.assert_called_once_with(self.home/'config.toml')
        self.assertFalse(result['configuration_changed'])

    def test_armed_activation_preserves_original_and_rejects_changed_config(self):
        self.prepare(); self.arm()
        self.assertEqual((self.bundle/'config-before-activation.toml').read_bytes(), (self.home/'config.toml').read_bytes())
        (self.home/'config.toml').write_bytes(b'model="changed"\n')
        with patch.object(startup.manager, 'start') as start:
            with self.assertRaisesRegex(ValueError, 'snapshot_changed'): startup.start(self.path)
            start.assert_not_called()

    def test_armed_activation_waits_for_closed_desktop_before_services(self):
        self.prepare(); self.arm()
        with patch.object(startup.manager, 'windows_process_entries', return_value=[{'name':'ChatGPT.exe'}]), \
                patch.object(startup.manager, 'start') as start:
            with self.assertRaisesRegex(ValueError, 'close_desktop'): startup.start(self.path)
            start.assert_not_called()

    def test_failed_activation_cannot_retry_on_next_launch(self):
        self.prepare(); self.arm()
        with patch.object(startup, 'assert_desktop_closed'), \
                patch.object(startup.manager, 'start', return_value={'status':'ready'}), \
                patch.object(startup, 'start_router'), patch.object(startup.router, 'bind_web'), \
                patch.object(startup.config, 'activate', side_effect=OSError('fixture failure')) as activate:
            with self.assertRaises(OSError): startup.start(self.path)
            with self.assertRaisesRegex(ValueError, 'entry_not_active'): startup.start(self.path)
            activate.assert_called_once()
        self.assertEqual(startup.manager.read_json(self.bundle/'activation.json')['phase'], 'may_have_activated')

    def test_cold_activation_after_readiness_is_verified(self):
        self.prepare(); self.arm()
        with patch.object(startup, 'assert_desktop_closed') as closed, \
                patch.object(startup.manager, 'start', return_value={'status':'ready'}), \
                patch.object(startup, 'start_router'), patch.object(startup.router, 'bind_web'), \
                patch.object(startup.config, 'activate') as activate, \
                patch.object(startup, 'entry_active', side_effect=[False,True]):
            result = startup.start(self.path)
            self.assertTrue(result['configuration_changed']); self.assertTrue(result['entry_active'])
            self.assertEqual(closed.call_count, 2); activate.assert_called_once()
        self.assertEqual(startup.manager.read_json(self.bundle/'activation.json')['phase'], 'activated')

    def test_real_activation_keeps_commented_legacy_config_and_new_route_owned(self):
        self.prepare()
        original = (startup.config.BEGIN + '# openai_base_url = "http://127.0.0.1:4317/'
            + 'a'*64 + '/v1"\n' + startup.config.END + 'model="native"\n').encode()
        (self.home/'config.toml').write_bytes(original)
        self.arm()
        with patch.object(startup, 'assert_desktop_closed'), \
                patch.object(startup.manager, 'start', return_value={'status':'ready'}), \
                patch.object(startup, 'start_router'), patch.object(startup.router, 'bind_web'), \
                patch.object(startup.config, 'health'):
            result = startup.start(self.path)
        self.assertTrue(result['entry_active'])
        self.assertEqual(startup.manager.read_json(self.bundle/'activation.json')['phase'], 'activated')
        active = (self.home/'config.toml').read_bytes()
        self.assertTrue(active.endswith(original))
        self.assertEqual(active.count(b'experimental_realtime_webrtc_call_base_url'), 1)
        self.assertEqual(active.count(b'experimental_realtime_ws_base_url'), 1)
        startup.config.deactivate(self.bundle/'router', self.home/'config.toml')
        self.assertEqual((self.home/'config.toml').read_bytes(), original)

    def test_arm_rejects_config_conflict_before_recovery_or_saved_intent(self):
        self.prepare()
        original = b'model_provider="custom"\n'
        (self.home/'config.toml').write_bytes(original)
        with patch.object(startup, 'checked_router') as observe, \
                patch.object(startup.config, 'ensure_recovery_shortcut') as recovery:
            with self.assertRaisesRegex(startup.config.RouterError, 'existing_provider'):
                startup.arm_entry(self.path)
            observe.assert_not_called(); recovery.assert_not_called()
        self.assertEqual((self.home/'config.toml').read_bytes(), original)
        self.assertFalse((self.bundle/'activation.json').exists())
        self.assertFalse((self.bundle/'config-before-activation.toml').exists())

    def test_public_activation_error_codes_do_not_expose_unknown_exception_text(self):
        for code in startup.ACTIVATION_ERRORS:
            self.assertEqual(startup.public_error(startup.config.RouterError(code)), 'web_startup_'+code)
            self.assertEqual(startup.public_error(RuntimeError(code)), 'web_startup_unavailable')
        self.assertEqual(startup.public_error(startup.config.RouterError('private://secret')), 'web_startup_unavailable')
        self.assertEqual(startup.public_error(ValueError('web_startup_plan_changed')), 'web_startup_plan_changed')

    def test_disarm_preserves_intent_without_config_or_service_changes(self):
        self.prepare(); self.arm()
        original=(self.bundle/'activation.json').read_bytes()
        with patch.object(startup.manager, 'start') as start, patch.object(startup.config,'deactivate') as deactivate:
            self.assertEqual(startup.disarm_entry(self.path)['status'],'disarmed')
            start.assert_not_called(); deactivate.assert_not_called()
        retained=list(self.bundle.glob('activation-retained-*.json'))
        self.assertEqual(len(retained),1); self.assertEqual(retained[0].read_bytes(),original)
        self.assertEqual(startup.manager.read_json(self.bundle/'activation.json')['phase'],'cancelled')
        with patch.object(startup.manager,'start') as start:
            with self.assertRaisesRegex(ValueError,'entry_not_active'): startup.start(self.path)
            start.assert_not_called()

    def test_native_recovery_lock_allows_status_disarm_and_exact_router_stop(self):
        self.prepare(); self.arm()
        original=(self.home/'config.toml').read_bytes()
        (self.home/'operator-native-route-only').write_bytes(b'fixture recovery lock\n')
        intent=(self.bundle/'activation.json').read_bytes()
        with patch.object(startup, 'checked_router', side_effect=URLError('absent')), \
                patch.object(startup.manager, 'status', return_value={'status':'stopped'}), \
                patch.object(startup.manager, 'start') as start:
            self.assertFalse(startup.status(self.path)['entry_active'])
            self.assertEqual(startup.disarm_entry(self.path)['status'],'disarmed')
            start.assert_not_called()
        self.assertEqual(next(self.bundle.glob('activation-retained-*.json')).read_bytes(),intent)
        self.write(self.bundle/'router-launch.json', {'phase':'ready','worker':{'pid':321}})
        with patch.object(startup, 'checked_router'), \
                patch.object(startup.router, 'control', return_value={'status':'stopping'}) as control, \
                patch.object(startup.manager, 'process_identity', return_value=None), \
                patch.object(startup.router, 'reserve_inactive_port', return_value=nullcontext()):
            self.assertEqual(startup.stop(self.path)['status'],'stopped')
            control.assert_called_once_with(self.bundle/'router',4318,stop=True)
        self.assertEqual((self.home/'config.toml').read_bytes(),original)
        self.assertEqual(startup.manager.read_json(self.bundle/'router-launch.json')['phase'],'stopped')

    def test_native_recovery_lock_still_blocks_arm_and_cold_activation(self):
        self.prepare(); self.arm()
        (self.home/'operator-native-route-only').write_bytes(b'fixture recovery lock\n')
        before=(self.bundle/'activation.json').read_bytes()
        with patch.object(startup.manager, 'start') as start, \
                patch.object(startup.config, 'ensure_recovery_shortcut') as recovery:
            for operation in (startup.arm_entry, startup.start):
                with self.subTest(operation=operation.__name__), \
                        self.assertRaisesRegex(startup.config.RouterError,'official_route_recovery_lock_active'):
                    operation(self.path)
            start.assert_not_called(); recovery.assert_not_called()
        self.assertEqual((self.bundle/'activation.json').read_bytes(),before)


if __name__ == '__main__': unittest.main()
