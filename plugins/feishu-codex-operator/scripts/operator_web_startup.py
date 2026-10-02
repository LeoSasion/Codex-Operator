"""Owned cold-launch workflow for a saved Web profile and native Responses router.

Preparation never changes Codex settings or launches a service. An explicit
service-start supports acceptance before activation; ordinary start requires
the exact previously activated route. Neither operation sends a model request,
replays a turn, repairs an uncertain service, or changes permissions.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import time
from urllib.error import URLError

import operator_model_router as router
import operator_web_service as manager
from operator_core import model_router_config as config
from operator_core.web_mcp_transport import require


SCRIPT = 'start-codex-with-web.ps1'
PLAN = 'web-startup.json'
ACTIVATION_ERRORS = frozenset({
    'managed_config_changed', 'existing_provider_requires_explicit_migration',
    'existing_route_catalog_or_profile_requires_explicit_migration',
    'existing_voice_route_requires_explicit_migration',
    'existing_voice_ws_route_requires_explicit_migration', 'legacy_router_voice_route_unprotected',
    'existing_router_journal_conflict', 'bom_config_requires_explicit_normalization',
    'official_route_recovery_lock_active', 'recovery_shortcut_required_before_activation',
    'activation_config_changed', 'model_cache_requires_regular_file', 'router_not_ready',
})


def public_error(error):
    code = str(error)
    if isinstance(error, config.RouterError) and code in ACTIVATION_ERRORS:
        return 'web_startup_' + code
    if code.startswith('web_startup_') and code.replace('_', '').isalnum():
        return code
    return 'web_startup_unavailable'


def paths(project):
    project = manager.checked_path(project, directory=True)
    private = manager.checked_path(project / '.codex', directory=True)
    return project, private / 'operator-web-startup'


def source_identity():
    root = Path(__file__).resolve().parent
    return {**manager.runtime_identity(), 'startup_sources': {
        name: manager.file_digest(root / name) for name in
        ('operator_web_startup.py', 'operator_model_router.py', 'operator_desktop_entry.ps1')}}


def powershell_quote(value):
    require(isinstance(value, str) and '\x00' not in value and '\r' not in value and '\n' not in value,
        'web_startup_path_invalid')
    return "'" + value.replace("'", "''") + "'"


def workflow(plan_path, plan):
    runtime = plan['runtime']
    return ("#requires -Version 7.0\n$ErrorActionPreference = 'Stop'\n"
        "$python = " + powershell_quote(runtime['python']) + "\n"
        "if ((Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant() -cne "
        + powershell_quote(runtime['python_sha256']) + ") { throw 'Saved Python changed.' }\n"
        "& $python -X utf8 -E -s -B " + powershell_quote(str(Path(__file__).resolve()))
        + " start --plan " + powershell_quote(str(plan_path)) + "\n"
        "if ($LASTEXITCODE -ne 0) { exit 1 }\nexit 0\n").encode('utf-8')


def prepare(project, profile, home, port):
    project, bundle = paths(project)
    profile, _ = manager.load_profile(profile)
    require(profile == project / '.codex/operator-web-service', 'web_startup_profile_scope')
    home = manager.checked_path(home, directory=True)
    require(type(port) is int and 1024 <= port <= 65535, 'web_startup_port_invalid')
    plan = {'version': 1, 'project': str(project), 'profile': str(profile),
        'home': str(home), 'port': port, 'runtime': source_identity(),
        'profile_sha256': manager.file_digest(profile / 'profile.json'),
        'router_state': str(bundle / 'router'), 'startup_script': SCRIPT}
    if bundle.exists():
        existing = load(bundle / PLAN)
        require(existing == plan, 'web_startup_plan_changed')
        return {'status': 'prepared', 'reused': True, 'configuration_changed': False}
    manager.private_directory(bundle)
    with (bundle / 'manager.lock').open('xb') as stream:
        stream.write(manager.LOCK_BYTES)
    state = bundle / 'router'
    manager.private_directory(state)
    config.initialize(state)
    manager.service.write_json(bundle / PLAN, plan)
    content = workflow(bundle / PLAN, plan)
    with (bundle / SCRIPT).open('xb') as stream:
        stream.write(content)
    manager.service.write_json(bundle / 'startup-sync-plan.json', {
        'schema_version': 2, 'startup_script': SCRIPT,
        'entry_files': {SCRIPT: manager.digest(content)}})
    return {'status': 'prepared', 'reused': False, 'configuration_changed': False}


def load(plan_path):
    plan_path = manager.checked_path(plan_path)
    plan = manager.read_json(plan_path)
    require(set(plan) == {'version', 'project', 'profile', 'home', 'port', 'runtime',
        'profile_sha256', 'router_state', 'startup_script'} and plan['version'] == 1,
        'web_startup_plan_invalid')
    project, bundle = paths(Path(plan['project']))
    require(plan_path == bundle / PLAN and plan['startup_script'] == SCRIPT
        and plan['profile'] == str(project / '.codex/operator-web-service')
        and plan['router_state'] == str(bundle / 'router'), 'web_startup_plan_scope')
    manager.checked_path(plan['home'], directory=True)
    require(type(plan['port']) is int and 1024 <= plan['port'] <= 65535, 'web_startup_port_invalid')
    require(plan['runtime'] == source_identity(), 'web_startup_runtime_changed')
    profile = Path(plan['profile'])
    manager.load_profile(profile)
    require(manager.file_digest(profile / 'profile.json') == plan['profile_sha256'],
        'web_startup_profile_changed')
    state = manager.checked_path(plan['router_state'], directory=True)
    registration = config.read_registration(manager.checked_path(state / 'registry.json'))
    require(registration.get('version') in (1, 2) and registration.get('models') == [],
        'web_startup_dedicated_router_required')
    require(manager.read_bytes(bundle / SCRIPT) == workflow(plan_path, plan),
        'web_startup_workflow_changed')
    metadata = manager.read_json(bundle / 'startup-sync-plan.json')
    require(metadata == {'schema_version': 2, 'startup_script': SCRIPT,
        'entry_files': {SCRIPT: manager.file_digest(bundle / SCRIPT)}}, 'web_startup_workflow_changed')
    return plan


def entry_active(plan):
    state, home = Path(plan['router_state']), Path(plan['home'])
    # Recovery blocks activation, not observation or cleanup of an owned entry.
    # arm_entry/start still enforce the lock through activation_preflight/activate.
    journal = state / 'codex-entry.json'
    if not journal.exists():
        return False
    value = manager.read_json(journal)
    expected = ({'config': str((home / 'config.toml').resolve()), 'block': block.decode()}
                for block in config.managed_entry_blocks(state, plan['port']))
    require(value in expected,
        'web_startup_entry_ownership_changed')
    require(manager.read_bytes(home / 'config.toml', 1024 * 1024).startswith(value['block'].encode()),
        'web_startup_entry_changed')
    return True


def checked_router(plan, launching=None):
    result = router.control(Path(plan['router_state']), plan['port'])
    require(result.get('status') == 'ready' and result.get('diagnostics', {}).get('web_profile_identity')
        == router.web_profile_identity(Path(plan['profile'])), 'web_startup_router_identity_changed')
    receipt = launching if launching is not None else manager.read_json(
        Path(plan['router_state']).parent / 'router-launch.json')
    require(receipt.get('runtime') == plan['runtime']
        and receipt.get('phase') in (('starting',) if launching is not None else ('ready',)),
        'web_startup_router_ownership_changed')
    worker = manager.session_worker({'pid': result['pid']}, receipt, {})
    if launching is not None:
        receipt['worker'] = worker
    return result


def start_router(plan, bundle):
    """CIM detached child on Windows; retain any uncertain launch for review."""
    try:
        return checked_router(plan)
    except URLError:
        # Absence is established by exclusive port reservation, not a timeout.
        with router.reserve_inactive_port(plan['port']):
            pass
    receipt_path = bundle / 'router-launch.json'
    if receipt_path.exists():
        old = manager.read_json(receipt_path)
        require(old.get('phase') == 'stopped', 'web_startup_router_uncertain_no_retry')
        history = bundle / ('router-launch-' + secrets.token_hex(16) + '.json')
        with history.open('xb') as stream:
            stream.write(manager.read_bytes(receipt_path))
    receipt = {'version': 1, 'phase': 'may_have_started', 'attempt': secrets.token_hex(16),
        'runtime': plan['runtime']}
    manager.service.write_json(receipt_path, receipt)
    argv = [plan['runtime']['python'], '-E', '-s', '-u', str(Path(router.__file__).resolve()),
        'serve', '--state-dir', plan['router_state'], '--port', str(plan['port']),
        '--web-profile', plan['profile']]
    try:
        child = manager.spawn_child(argv, bundle)
        receipt.update(pid=child.pid, process=manager.process_identity(child.pid), phase='starting')
        require(receipt['process'] is not None
            and Path(receipt['process']['executable']) == Path(plan['runtime']['python']),
            'web_startup_router_process_unknown')
        manager.service.write_json(receipt_path, receipt)
        deadline = time.monotonic() + 15
        while child.poll() is None and time.monotonic() < deadline:
            try:
                result = checked_router(plan, launching=receipt)
                receipt.update(phase='ready', service_pid=result['pid'])
                manager.service.write_json(receipt_path, receipt)
                return result
            except URLError:
                time.sleep(.1)  # Read-only local startup observation, never a model retry.
        raise RuntimeError('web_startup_router_not_ready')
    except BaseException:
        receipt['phase'] = 'uncertain'
        manager.service.write_json(receipt_path, receipt)
        raise


def stop(plan_path):
    """Explicit request-free stop; an uncertain stop is never auto-repeated."""
    plan = load(plan_path)
    bundle = Path(plan_path).parent
    with manager.operation_lock(bundle):
        require(not entry_active(plan), 'web_startup_deactivate_before_stop')
        checked_router(plan)
        receipt_path = bundle / 'router-launch.json'
        receipt = manager.read_json(receipt_path)
        # The server also rejects an active entry or an in-flight request.
        result = router.control(Path(plan['router_state']), plan['port'], stop=True)
        require(result.get('status') == 'stopping', 'web_startup_stop_uncertain_no_retry')
        receipt['phase'] = 'stopping'
        manager.service.write_json(receipt_path, receipt)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if manager.process_identity(receipt['worker']['pid']) is None:
                with router.reserve_inactive_port(plan['port']):
                    receipt['phase'] = 'stopped'
                    manager.service.write_json(receipt_path, receipt)
                return {'status': 'stopped', 'web_service_unchanged': True, 'replayed': False}
            time.sleep(.1)
        raise RuntimeError('web_startup_stop_uncertain_no_retry')


def start(plan_path, *, services_only=False):
    plan = load(plan_path)
    bundle = Path(plan_path).parent
    with manager.operation_lock(bundle):
        require(load(plan_path) == plan, 'web_startup_plan_changed')
        active = entry_active(plan)
        activation_path = bundle / 'activation.json'
        activation = manager.read_json(activation_path) if activation_path.exists() else None
        armed = not active and activation is not None and activation.get('phase') == 'armed'
        require(services_only or active or armed, 'web_startup_entry_not_active')
        if active:
            # An old owned prefix can still be stopped or removed, but starting
            # Desktop through it requires both Voice routes to be verified.
            config.activation_preflight(Path(plan['router_state']), plan['port'],
                Path(plan['home']) / 'config.toml')
        if armed:
            require(activation.get('plan_sha256') == manager.file_digest(plan_path)
                and activation.get('config_sha256') == manager.file_digest(Path(plan['home']) / 'config.toml'),
                'web_startup_activation_snapshot_changed')
            config.activation_preflight(Path(plan['router_state']), plan['port'], Path(plan['home']) / 'config.toml')
            if not services_only:
                assert_desktop_closed()
        profile = Path(plan['profile'])
        outcome = manager.start(profile)
        # A single start may still be preparing; observe it, never start again.
        deadline = time.monotonic() + 20
        while outcome['status'] == 'starting' and time.monotonic() < deadline:
            time.sleep(.1)
            outcome = manager.status(profile)
        require(outcome['status'] == 'ready' and not outcome.get('active', False),
            'web_startup_saved_service_not_ready')
        start_router(plan, bundle)
        router.bind_web(Path(plan['router_state']), plan['port'], profile)
        require(load(plan_path) == plan, 'web_startup_plan_changed')
        if armed and not services_only:
            assert_desktop_closed()
            require(activation == manager.read_json(activation_path)
                and activation['config_sha256'] == manager.file_digest(Path(plan['home']) / 'config.toml'),
                'web_startup_activation_snapshot_changed')
            activation['phase'] = 'may_have_activated'
            manager.service.write_json(activation_path, activation)
            config.activate(Path(plan['router_state']), plan['port'], Path(plan['home']) / 'config.toml')
            require(entry_active(plan), 'web_startup_activation_not_verified')
            activation['phase'] = 'activated'
            manager.service.write_json(activation_path, activation)
            active = True
        return {'status': 'ready', 'configuration_changed': bool(armed and not services_only), 'entry_active': active,
            'model_requests': 0, 'replayed': False,
            'summary': '后台与模型入口已就绪，沿用已保存的登录和连接。'}


def assert_desktop_closed():
    require(os.name == 'nt' and all(row['name'].lower() != 'chatgpt.exe'
        for row in manager.windows_process_entries()), 'web_startup_close_desktop_before_activation')


def arm_entry(plan_path):
    """Owner-requested activation at the next reviewed cold launch, never now."""
    plan = load(plan_path)
    bundle = Path(plan_path).parent
    with manager.operation_lock(bundle):
        require(not entry_active(plan), 'web_startup_entry_already_active')
        config.activation_preflight(Path(plan['router_state']), plan['port'], Path(plan['home']) / 'config.toml')
        observed = checked_router(plan)
        require(observed['diagnostics'].get('web_route_bound') is True, 'web_startup_binding_required')
        path = bundle / 'activation.json'
        require(not path.exists(), 'web_startup_activation_already_recorded')
        original = manager.read_bytes(Path(plan['home']) / 'config.toml', 1024 * 1024)
        # This real-home recovery integration is part of explicit global setup.
        config.ensure_recovery_shortcut(Path(plan['home']) / 'config.toml')
        require(manager.read_bytes(Path(plan['home']) / 'config.toml', 1024 * 1024) == original,
            'web_startup_activation_snapshot_changed')
        with (bundle / 'config-before-activation.toml').open('xb') as stream:
            stream.write(original)
        manager.service.write_json(path, {'version':1, 'phase':'armed',
            'plan_sha256':manager.file_digest(plan_path), 'config_sha256':manager.digest(original)})
        return {'status':'armed_for_cold_launch', 'configuration_changed':False, 'model_requests':0}


def disarm_entry(plan_path):
    """Cancel a not-active cold-launch intent; never change routing or services."""
    plan = load(plan_path)
    bundle = Path(plan_path).parent
    with manager.operation_lock(bundle):
        require(not entry_active(plan), 'web_startup_deactivate_before_disarm')
        path = bundle / 'activation.json'
        if not path.exists():
            return {'status':'disarmed', 'configuration_changed':False}
        value = manager.read_json(path)
        require(value.get('plan_sha256') == manager.file_digest(plan_path)
            and value.get('phase') in ('armed', 'activated', 'cancelled'),
            'web_startup_activation_uncertain_no_retry')
        if value['phase'] != 'cancelled':
            with (bundle / ('activation-retained-' + secrets.token_hex(16) + '.json')).open('xb') as stream:
                stream.write(manager.read_bytes(path))
            manager.service.write_json(path, {**value, 'phase':'cancelled'})
        return {'status':'disarmed', 'configuration_changed':False}


def status(plan_path):
    plan = load(plan_path)
    active = entry_active(plan)
    try:
        observed = checked_router(plan)
        router_ready = observed['diagnostics'].get('web_route_bound') is True
    except (OSError, RuntimeError, ValueError):
        router_ready = False
    return {'status': 'configured', 'entry_active': active, 'router_ready': router_ready,
        'web': manager.status(Path(plan['profile'])), 'configuration_changed': False,
        'summary': '启动配置已保存；检查不会启动服务或重做请求。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'status', 'start', 'service-start', 'router-stop', 'arm-entry', 'disarm-entry'))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--port', type=int, default=4318)
    args = parser.parse_args()
    if args.action == 'prepare':
        if not all((args.project, args.profile, args.home)) or args.plan:
            parser.error('prepare requires exact project, profile and home')
        result = prepare(args.project, args.profile, args.home, args.port)
    else:
        if not args.plan or any((args.project, args.profile, args.home)):
            parser.error('an exact plan is required')
        if args.action == 'status':
            result = status(args.plan)
        elif args.action == 'router-stop':
            result = stop(args.plan)
        elif args.action == 'arm-entry':
            result = arm_entry(args.plan)
        elif args.action == 'disarm-entry':
            result = disarm_entry(args.plan)
        else:
            result = start(args.plan, services_only=args.action == 'service-start')
    # Startup may inherit a legacy Windows console code page. ASCII JSON keeps
    # the exact Unicode summary readable after PowerShell redirects the stream.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = public_error(error)
        print(json.dumps({'status': 'unavailable', 'code': code, 'replayed': False,
            'summary': '启动检查未完成，已有配置和任务保留；请由助手核对当前状态。'}, ensure_ascii=True))
        raise SystemExit(1)
