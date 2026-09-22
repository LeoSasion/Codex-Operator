"""Read-only teardown checks and explicit one-shot routing detachment. No tasks."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import time
from urllib.request import Request, ProxyHandler, build_opener

import routing_cli
from operator_core import model_router_config as settings


def assert_port_free(port):
    with socket.socket() as listener:
        if os.name == 'nt': listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', port))


def service(state, port, *, stop=False, expected=None):
    # The public entry runs the canonical source router; older installations
    # run its installed copy. Both use the same private state and token, but
    # their exact script paths deliberately produce different identities.
    scripts = {state.parent / 'operator_model_router.py',
               Path(__file__).with_name('operator_model_router.py')}
    identities = {hashlib.sha256((str(script.resolve()) + '\n' + str(state.resolve())).encode()).hexdigest()
                  for script in scripts}
    if stop:
        if expected is None:
            raise ValueError('router_stop_identity_required')
        service(state, port, expected=expected)  # Verify before sending a stop.
    request = Request(settings.url(state, port) + '/lifecycle', method='POST' if stop else 'GET',
                      data=b'' if stop else None)
    with build_opener(ProxyHandler({}), settings._NoRedirect()).open(request, timeout=3) as response:
        raw = response.read(16385)
    if len(raw) > 16384: raise ValueError('invalid_router_status')
    value = settings.loads(raw)
    if (not isinstance(value, dict) or value.get('service') not in identities
            or type(value.get('pid')) is not int or value['pid'] <= 0
            or (expected is not None and (value['service'], value['pid']) != expected)):
        raise ValueError('router_identity_mismatch')
    return value


def inspect(project, config, port):
    # The separately owned Web entry must be detached before archiving its
    # interpreter/runtime. Never mistake the legacy 4317 listener for that route.
    inspect_web_startup(project, config)
    migration = project/'.codex/operator-entry-migration/journal.json'
    if migration.exists():
        from operator_web_service import checked_path, read_json
        checked_path(migration)
        record = read_json(migration)
        if (record.get('scope') != 'desktop_entry_only' or record.get('project') != str(project)
                or record.get('phase') != 'restored'):
            raise ValueError('restore_separate_desktop_entry_migration_before_uninstall')
    trial = project/'.codex/operator-web-service/desktop/current.json'
    if trial.exists():
        from operator_web_desktop import status as desktop_status
        if desktop_status(trial.parent.parent, config.parent)['status'] != 'disconnected':
            raise ValueError('disconnect_web_desktop_trial_before_uninstall')
    runtime = project/'.codex/feishu-codex-operator-runtime'
    state = runtime/'model-router'
    pending = 0
    if (runtime/'callbacks.sqlite3').exists():
        with closing(sqlite3.connect((runtime/'callbacks.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
            pending = db.execute("select count(*) from final_callback_requests where state in ('pending','captured')").fetchone()[0]
    entry = state/'codex-entry.json'
    owned_entry = entry.exists()
    if owned_entry:
        journal = settings.read_registration(entry)
        expected = {'config':str(config.resolve()), 'block':settings.BEGIN + 'openai_base_url = ' + json.dumps(settings.url(state,port)) + '\n' + settings.END}
        if journal != expected or not config.read_bytes().startswith(journal['block'].encode()):
            raise ValueError('router_entry_ownership_conflict')
    try:
        assert_port_free(port)
        router = {'status':'stopped'}
    except OSError:
        router = service(state,port)
    active = 0 if router['status']=='stopped' else router['diagnostics']['timing']['active']
    if not isinstance(active,int) or active < 0: raise ValueError('invalid_router_activity')
    callback = routing_cli._status(runtime)
    return {'pending_callbacks':pending,'active_router_requests':active,
            'router_status':router['status'],'owned_router_entry':owned_entry,
            'router_identity':None if router['status']=='stopped' else (router['service'], router['pid']),
            'owned_callback_registration':callback['matches_runtime'],
            'other_callback_registration_preserved':callback['configured'] and not callback['matches_runtime']}


def inspect_web_startup(project, config):
    profile = project/'.codex/operator-web-service'
    bundle = project/'.codex/operator-web-startup'
    # A Channels-only uninstall must not require optional Web dependencies.
    # Reject linked paths before absence checks, including dangling links.
    for path in (profile, bundle, *profile.parents):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('web_manager_linked_path_rejected')
    if not profile.exists() and not bundle.exists():
        return
    from operator_web_service import checked_path, read_json, status
    checked_path(profile, exists=False)
    # A saved service does not require a cold-launch plan. Inspect it first,
    # including malformed/uncertain records, before any teardown mutations.
    if profile.exists():
        checked_path(profile, directory=True)
        observed = status(profile)
        if (observed['status'] not in ('stopped', 'configured')
                or observed.get('start_available') is False):
            raise ValueError('stop_saved_web_service_before_uninstall')
    if not bundle.exists():
        return
    checked_path(bundle, directory=True)
    plan = read_json(bundle/'web-startup.json')
    if (plan.get('version') != 1 or plan.get('project') != str(project)
            or plan.get('home') != str(config.parent)
            or plan.get('profile') != str(project/'.codex/operator-web-service')
            or plan.get('router_state') != str(bundle/'router')
            or type(plan.get('port')) is not int or not 1024 <= plan['port'] <= 65535):
        raise ValueError('web_startup_uninstall_ownership_conflict')
    state = checked_path(bundle/'router', directory=True)
    if (state/'codex-entry.json').exists():
        raise ValueError('deactivate_web_startup_before_uninstall')
    # This is a read-only guard, not service control or a guessed recovery.
    assert_port_free(plan['port'])
    launch = bundle/'router-launch.json'
    if launch.exists() and read_json(launch).get('phase') != 'stopped':
        raise ValueError('stop_exact_web_startup_router_before_uninstall')
    activation = bundle/'activation.json'
    if activation.exists() and read_json(activation).get('phase') != 'cancelled':
        raise ValueError('cancel_web_startup_activation_before_uninstall')
    if not profile.exists():
        raise ValueError('web_startup_uninstall_profile_missing')


def detach(project, config, port):
    observed = inspect(project,config,port)
    if observed['pending_callbacks'] or observed['active_router_requests']:
        raise ValueError('finish_callbacks_and_router_requests_before_uninstall')
    runtime = project/'.codex/feishu-codex-operator-runtime'; state = runtime/'model-router'
    if observed['owned_router_entry']: settings.deactivate(state,config)
    if observed['router_status'] != 'stopped':
        service(state,port,stop=True,expected=observed['router_identity'])  # One stop only.
        deadline = time.monotonic()+5
        while True:
            try: assert_port_free(port); break
            except OSError:
                if time.monotonic() >= deadline: raise ValueError('router_stop_not_confirmed')
                time.sleep(.1)  # Listener release check, not model/request replay.
    if observed['owned_callback_registration']: routing_cli._unregister(runtime)
    return {'routing_detached':True,'model_requests_replayed':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inspect','detach'])
    parser.add_argument('--project-root',required=True,type=Path)
    parser.add_argument('--codex-config',required=True,type=Path)
    parser.add_argument('--port',type=int,default=4317)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535: raise ValueError('invalid_router_port')
        operation = inspect if args.action=='inspect' else detach
        print(json.dumps(operation(args.project_root.resolve(),args.codex_config.resolve(),args.port)))
    except Exception:
        # Never print config contents, tokens, callback material or credentialed URLs.
        print(json.dumps({'error':'uninstall_preflight_or_detach_failed','retried':False}))
        raise SystemExit(1)
