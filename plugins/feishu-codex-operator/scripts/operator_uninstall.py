"""Read-only teardown checks and explicit one-shot routing detachment. No tasks."""
import argparse
from contextlib import closing
import hashlib
import json
import tomllib
import os
from pathlib import Path
import socket
import sqlite3
import time
from urllib.request import Request, ProxyHandler, build_opener

import routing_cli
from operator_core import model_router_config as settings


class UnifiedCandidateConflict(ValueError):
    """Fixed, content-free uninstall blocker for the disposable route trial."""


def _unified_artifact_present(path):
    try:
        path.lstat()  # Also detects dangling links and Windows junctions.
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall') from exc
    return True


def inspect_unified_candidate(config):
    # A Channels-only exit does not need optional unified modules. Any saved
    # archive, including a linked or incomplete one, needs an exact receipt.
    home = config.parent
    if _unified_artifact_present(home/'operator-unified-workflow-renewal'):
        from operator_unified_workflow_renew import status as workflow_renewal_status
        if workflow_renewal_status(home)['status'] != 'workflows_retained':
            raise UnifiedCandidateConflict('unified_workflow_renewal_requires_review_before_uninstall')
    if _unified_artifact_present(home/'operator-unified-failed-archive'):
        from operator_unified_failed_archive import archive_status as failed_archive_status
        if failed_archive_status(home)['status'] != 'failed_originals_retained':
            raise UnifiedCandidateConflict('unified_failed_archive_requires_review_before_uninstall')
    if _unified_artifact_present(home/'operator-unified-retired-archive'):
        from operator_unified_retire import archive_status as retired_archive_status
        if retired_archive_status(home)['status'] != 'retained':
            raise UnifiedCandidateConflict('unified_retired_archive_requires_review_before_uninstall')
    archive = home/'operator-unified-prepared-archive'
    if _unified_artifact_present(archive):
        try:
            from operator_unified_supersede import archive_status
            if archive_status(home)['status'] != 'superseded_witnessed':
                raise ValueError('archive not witnessed')
        except Exception as exc:
            raise UnifiedCandidateConflict('unified_prepared_archive_requires_review_before_uninstall') from exc
    # The retained one-shot plan is separate ownership. Only its exact terminal
    # retirement receipt, checked against recovered native state, clears this
    # gate; neither a restored config nor an entry journal alone does so.
    activation = home/'operator-unified-activation'
    if _unified_artifact_present(activation):
        try:
            from operator_unified_retire import verify_retired
            if verify_retired(activation/'plan.json')['status'] != 'retired_witnessed':
                raise ValueError('retirement not witnessed')
        except Exception as exc:
            raise UnifiedCandidateConflict('unified_activation_requires_review_before_uninstall') from exc
    for path in (home/'operator-unified-disposable.json',
                 home/'operator-unified-candidate'):
        if _unified_artifact_present(path):
            raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')
    if config.is_symlink() or getattr(config, 'is_junction', lambda: False)():
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')
    if not config.exists():
        return
    if not config.is_file():
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')
    try:
        with config.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
    except OSError as exc:
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall') from exc
    if (len(raw) > 1024 * 1024 or b'OPERATOR UNIFIED' in raw
            or b'operator_unified_candidate' in raw):
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')
    try:
        parsed = tomllib.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall') from exc
    providers = parsed.get('model_providers')
    if (parsed.get('model_provider') == 'operator_unified_candidate'
            or isinstance(providers, dict) and 'operator_unified_candidate' in providers):
        raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')


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
    migration = project/'.codex/operator-entry-migration/journal.json'
    if migration.exists():
        from operator_web_service import checked_path, read_json
        checked_path(migration)
        record = read_json(migration)
        if (record.get('scope') != 'desktop_entry_only' or record.get('project') != str(project)
                or record.get('phase') != 'restored'):
            raise ValueError('restore_separate_desktop_entry_migration_before_uninstall')
    return inspect_entry(project, config, port)


def inspect_entry(project, config, port):
    """Entry restoration preflight, with no assertion of runtime ownership."""
    inspect_unified_candidate(config)
    inspect_mode_entries(project)
    # The separately owned Web entry must be detached before archiving its
    # interpreter/runtime. Never mistake the legacy 4317 listener for that route.
    inspect_web_startup(project, config)
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
        expected = ({'config':str(config.resolve()), 'block':block.decode()}
                    for block in settings.managed_entry_blocks(state,port))
        if journal not in expected or not config.read_bytes().startswith(journal['block'].encode()):
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


def inspect_mode_entries(project):
    """Every isolated Desktop/router must be known stopped before runtime removal."""
    parent = project / '.codex/operator-mode-entry'
    if not _unified_artifact_present(parent):
        return
    # Import only when saved mode state exists; Channels-only teardown needs no aiohttp.
    import operator_mode_entry as mode
    try:
        mode.checked_path(parent, directory=True)
        for root in parent.iterdir():
            mode.checked_path(root, directory=True)
            descriptor = mode.load(root, check_source=False)
            mode.require(descriptor['project'] == str(project), 'uninstall_project_changed')
            mode.require(mode.active_desktop(root) is None, 'close_extension_before_uninstall')
            attempt = mode.router_attempt(root)
            if attempt is not None:
                running = mode.decode(mode.read(attempt / 'running.json'))
                stopped = mode.decode(mode.read(attempt / 'stopped.json'))
                mode.require(stopped.get('server_confirmed_request_free') is True
                    and stopped.get('process') == running.get('process')
                    and not mode.process_matches(running.get('process')), 'stop_extension_router_before_uninstall')
            assert_port_free(descriptor['port'])
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('isolated_mode_requires_stopped_review_before_uninstall') from None


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
    retirement_artifacts = (bundle/'legacy-activation-retirement.json',
        bundle/'legacy-activation-original.json', bundle/'legacy-activation-retired.json')
    if any(path.exists() or path.is_symlink() for path in retirement_artifacts):
        from operator_web_activation_retire import retirement_status
        if retirement_status(bundle/'web-startup.json') != 'retired':
            raise ValueError('review_web_activation_retirement_before_uninstall')
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
    parser.add_argument('action',choices=['inspect','inspect-entry','detach'])
    parser.add_argument('--project-root',required=True,type=Path)
    parser.add_argument('--codex-config',required=True,type=Path)
    parser.add_argument('--port',type=int,default=4317)
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535: raise ValueError('invalid_router_port')
        if args.codex_config.is_symlink() or getattr(args.codex_config, 'is_junction', lambda: False)():
            raise UnifiedCandidateConflict('unified_candidate_requires_review_before_uninstall')
        operation = {'inspect': inspect, 'inspect-entry': inspect_entry, 'detach': detach}[args.action]
        print(json.dumps(operation(args.project_root.resolve(),args.codex_config.resolve(),args.port)))
    except UnifiedCandidateConflict as exc:
        print(json.dumps({'error':'uninstall_preflight_or_detach_failed',
                          'reason':str(exc),'retried':False}))
        raise SystemExit(1)
    except Exception:
        # Never print config contents, tokens, callback material or credentialed URLs.
        print(json.dumps({'error':'uninstall_preflight_or_detach_failed','retried':False}))
        raise SystemExit(1)
