"""Source-bound cold-entry configuration; no launch, service control or inference.

Each activation creates a terminal cycle before touching config.toml. A separate
native PowerShell helper owns explicit recovery. Failed cycles are never retried.
"""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys

import operator_direct_profile as projection
import operator_native_models as native
from operator_core import windows_config_transaction as transaction
from operator_core.web_browser_driver import private_directory

HEX = re.compile(r'[a-f0-9]{64}\Z')
CYCLE = re.compile(r'[a-f0-9]{32}\Z')
MARKER = b'operator-native-route-only-v1\n'
ROOT = Path(__file__).resolve().parent
PLAN_KEYS = {'schema_version', 'contract', 'project', 'home', 'state', 'profile',
    'model', 'kind', 'display_name', 'python', 'native_helper', 'entry_script',
    'source_sha256', 'profile_binding', 'router_port'}
FILES = {'config-before.bin', 'config-candidate.bin', 'projection.json', 'profile.json', 'plan.json'}


class DirectEntryError(ValueError):
    pass


def require(value, code):
    if not value:
        raise DirectEntryError('direct_entry_' + code)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read(path, limit=1024 * 1024):
    path = native.checked_path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'file_bound')
    return raw


def encoded(value):
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False) + '\n').encode()
    require(len(raw) <= 4 * 1024 * 1024, 'record_bound')
    return raw


def record(path, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def load_json(path, limit=1024 * 1024):
    raw = read(path, limit)
    value = native.decode(raw)
    require(isinstance(value, dict), 'record_invalid')
    return value, raw


def file_hash(path):
    path = native.checked_path(path)
    require(path.stat().st_size <= 256 * 1024 * 1024, 'dependency_bound')
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def default_home():
    return Path.home() / '.codex'


def checked_home(home):
    home = native.checked_path(home, directory=True)
    effective = Path(os.environ.get('CODEX_HOME') or default_home())
    require(home == native.checked_path(default_home(), directory=True)
        and effective == home, 'default_native_home_required')
    require(read(home / 'operator-native-route-only', 4096) == MARKER, 'native_protection_required')
    return home


def sources():
    paths = sorted(ROOT.rglob('*.py')) + [ROOT / 'operator_core/beeper_model_catalog.json']
    require(len(paths) <= 256, 'source_bound')
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in paths}


def profile_binding(state, home, *, baseline=True):
    state = native.checked_path(state, directory=True)
    plan, manifest, files, journal = native.load(state, home)
    require(journal['phase'] == 'installed', 'installed_profile_required')
    generated, _ = native.artifacts(manifest, home)
    require(all(generated[kind] == files[kind]['prepared'][0]
        and read(files[kind]['path']) == generated[kind] for kind in ('profile', 'catalog')),
        'profile_source_changed')
    if baseline:
        native.check_base_provider(home, plan['provider'])
    binding = {name: digest(read(state / (name + '.json'))) for name in ('manifest', 'plan', 'journal')}
    binding.update({kind: digest(read(files[kind]['path'])) for kind in ('profile', 'catalog')})
    return manifest, binding


def native_baseline(raw):
    parsed = projection.parse(raw)
    require(parsed.get('model_provider', 'openai') == 'openai'
        and not any(key in parsed for key in ('profile', 'model_catalog_json', 'openai_base_url')),
        'native_baseline_required')
    require(not any(marker in raw for marker in (b'# BEGIN OPERATOR DIRECT',
        b'# BEGIN OPERATOR UNIFIED', b'# BEGIN OPERATOR MODEL ROUTER')),
        'managed_route_conflict')


def helper_preview(plan):
    pwsh = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PowerShell/7/pwsh.exe'
    require(pwsh.is_file(), 'powershell_unavailable')
    try:
        result = subprocess.run([str(pwsh), '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', plan['native_helper']['path'], '-CodexHome', plan['home'],
            '-ProjectRoot', plan['project'], '-Json'], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        require(result.returncode == 0 and len(result.stdout) <= 65536, 'native_recovery_unavailable')
        checked = native.decode(result.stdout)
        require(checked.get('status') == 'preview' and checked.get('route_before') == 'native'
            and checked.get('warnings') == [] and checked.get('recovery_lock_present') is True,
            'native_recovery_unavailable')
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError):
        raise DirectEntryError('direct_entry_native_recovery_unavailable') from None


def load_plan(path):
    path = native.checked_path(path)
    value, raw = load_json(path)
    require(set(value) == PLAN_KEYS and value['schema_version'] == 1
        and value['contract'] == 'operator_direct_entry_plan_v1', 'plan_invalid')
    project = native.checked_path(Path(value['project']), directory=True)
    home = checked_home(Path(value['home']))
    require(path.name == 'plan.json' and CYCLE.fullmatch(path.parent.name)
        and path.parent.parent == project / '.codex/operator-direct-startup/plans', 'plan_scope_invalid')
    require(type(value['router_port']) is int and 1024 <= value['router_port'] <= 65535,
        'plan_invalid')
    require(value['source_sha256'] == sources(), 'source_changed')
    for key in ('python', 'native_helper', 'entry_script'):
        item = value[key]
        require(isinstance(item, dict) and set(item) == {'path', 'sha256'}
            and isinstance(item['sha256'], str) and HEX.fullmatch(item['sha256'])
            and file_hash(Path(item['path'])) == item['sha256'], 'dependency_changed')
    manifest, binding = profile_binding(Path(value['state']), home, baseline=False)
    require(binding == value['profile_binding'] and all(value[key] == manifest[key]
        for key in ('profile', 'kind')) and value['model'] == manifest['model']['id']
        and value['display_name'] == manifest['model']['display_name'], 'profile_changed')
    return value, raw, manifest


def prior_cycle(home):
    """A recovered pointer is retained; failed or uncertain cycles never retry."""
    root = home / 'operator-direct-entry'
    pointer = native.checked_path(root / 'active.json', exists=False)
    cycle_root = native.checked_path(root / 'cycles', directory=True, exists=False)
    retained = list(cycle_root.iterdir()) if cycle_root.exists() else []
    require(len(retained) <= 128 and all(path.is_dir() and CYCLE.fullmatch(path.name)
        for path in retained), 'cycle_inventory_invalid')
    if not pointer.exists():
        require(not retained, 'unreferenced_cycle_requires_review')
        return None
    active, pointer_raw = load_json(pointer, 16384)
    require(set(active) == {'schema_version', 'contract', 'cycle', 'intent_sha256'}
        and active['schema_version'] == 1 and active['contract'] == 'operator_direct_entry_active_v1'
        and isinstance(active['cycle'], str) and CYCLE.fullmatch(active['cycle'])
        and isinstance(active['intent_sha256'], str) and HEX.fullmatch(active['intent_sha256']),
        'active_cycle_invalid')
    folder = native.checked_path(root / 'cycles' / active['cycle'], directory=True)
    for sibling in retained:
        if sibling != folder:
            _recovered_cycle(sibling, home)
    _recovered_cycle(folder, home, active['intent_sha256'])
    return pointer_raw


def _recovered_cycle(folder, home, expected_intent_sha=None):
    folder = native.checked_path(folder, directory=True)
    intent, raw = load_json(folder / 'intent.json', 4 * 1024 * 1024)
    intent_keys = {'schema_version', 'contract', 'project', 'home', 'cycle', 'plan_sha256',
        'native_helper_sha256', 'source_sha256', 'config_before_present', 'before_identity', 'files'}
    require(set(intent) == intent_keys and intent['schema_version'] == 1
        and intent['contract'] == 'operator_direct_entry_cycle_v1' and intent['config_before_present'] is True
        and (expected_intent_sha is None or digest(raw) == expected_intent_sha)
        and intent.get('cycle') == folder.name
        and intent.get('home') == str(home) and set(intent.get('files', {})) == FILES,
        'active_cycle_changed')
    require(all(digest(read(folder / name, 4 * 1024 * 1024)) == sha
        for name, sha in intent['files'].items()), 'active_cycle_changed')
    retained_plan, plan_raw = load_json(folder / 'plan.json')
    require(set(retained_plan) == PLAN_KEYS and retained_plan['schema_version'] == 1
        and retained_plan['contract'] == 'operator_direct_entry_plan_v1'
        and retained_plan['home'] == str(home) and retained_plan['project'] == intent['project']
        and digest(plan_raw) == intent['plan_sha256']
        and retained_plan['source_sha256'] == intent['source_sha256']
        and retained_plan['native_helper']['sha256'] == intent['native_helper_sha256'], 'active_cycle_changed')
    before = read(folder / 'config-before.bin')
    candidate = read(folder / 'config-candidate.bin')
    saved_projection, _ = load_json(folder / 'projection.json', 4 * 1024 * 1024)
    manifest = native.validate_manifest(native.decode(read(folder / 'profile.json')))
    require(digest(read(folder / 'profile.json')) == retained_plan['profile_binding']['manifest']
        and manifest['profile'] == retained_plan['profile'] and manifest['model']['id'] == retained_plan['model']
        and projection.restore(candidate, saved_projection) == before, 'active_cycle_changed')
    require((folder / 'recovered.json').is_file(), 'native_restore_required')
    receipt, receipt_raw = load_json(folder / 'recovered.json', 65536)
    expected = {'schema_version', 'contract', 'cycle', 'intent_sha256',
        'config_before_recovery_sha256', 'config_after_recovery_sha256', 'recovery_backup'}
    require(set(receipt) == expected and receipt['schema_version'] == 1
        and receipt['contract'] == 'operator_direct_entry_recovered_v1'
        and receipt['cycle'] == folder.name and receipt['intent_sha256'] == digest(raw),
        'recovery_receipt_invalid')
    require(all(isinstance(receipt[key], str) and HEX.fullmatch(receipt[key]) for key in
        ('config_before_recovery_sha256', 'config_after_recovery_sha256')), 'recovery_receipt_invalid')
    backup = native.checked_path(Path(receipt['recovery_backup']), directory=True)
    require(backup.parent == home / 'operator-route-recovery', 'recovery_receipt_invalid')
    backup_intent, _ = load_json(backup / 'intent.json', 1024 * 1024)
    completed, _ = load_json(backup / 'completed.json', 65536)
    rows = backup_intent.get('files', [])
    receipt_rows = [row for row in rows if row.get('target') == str(folder / 'recovered.json')]
    require(len(receipt_rows) == 1 and receipt_rows[0].get('after_sha256') == digest(receipt_raw)
        and receipt_rows[0].get('name') in completed.get('completed', []), 'recovery_receipt_invalid')
    config_rows = [row for row in rows if row.get('target') == str(home / 'config.toml')]
    require((len(config_rows) == 1 and config_rows[0].get('before_sha256') == receipt['config_before_recovery_sha256']
        and config_rows[0].get('after_sha256') == receipt['config_after_recovery_sha256']
        and config_rows[0].get('name') in completed.get('completed', [])) or
        (not config_rows and receipt['config_before_recovery_sha256'] == receipt['config_after_recovery_sha256']
         == intent['files']['config-before.bin']), 'recovery_receipt_invalid')


def prepare(state, project, home, python, native_helper, plan_path, *, router_port=4317):
    project = native.checked_path(project, directory=True)
    home = checked_home(home)
    plan_path = native.checked_path(plan_path, exists=False)
    require(plan_path.name == 'plan.json' and CYCLE.fullmatch(plan_path.parent.name)
        and plan_path.parent.parent == project / '.codex/operator-direct-startup/plans'
        and not plan_path.parent.exists(), 'new_plan_required')
    require(type(router_port) is int and 1024 <= router_port <= 65535, 'router_port_invalid')
    native_baseline(read(home / 'config.toml'))
    prior_cycle(home)
    manifest, binding = profile_binding(state, home)
    value = {'schema_version': 1, 'contract': 'operator_direct_entry_plan_v1',
        'project': str(project), 'home': str(home), 'state': str(state),
        'profile': manifest['profile'], 'model': manifest['model']['id'], 'kind': manifest['kind'],
        'display_name': manifest['model']['display_name'],
        'python': {'path': str(python), 'sha256': file_hash(python)},
        'native_helper': {'path': str(native_helper), 'sha256': file_hash(native_helper)},
        'entry_script': {'path': str(ROOT / 'operator_desktop_entry.ps1'),
            'sha256': file_hash(ROOT / 'operator_desktop_entry.ps1')},
        'source_sha256': sources(), 'profile_binding': binding, 'router_port': router_port}
    helper_preview(value)
    parent = plan_path.parent.parent
    for directory in (parent.parent, parent, plan_path.parent):
        if not directory.exists():
            private_directory(directory)
    record(plan_path, value)
    return {**preview(plan_path), 'status': 'prepared'}


def preview(plan_path):
    value, raw, manifest = load_plan(plan_path)
    home = Path(value['home'])
    prior_cycle(home)
    before = read(home / 'config.toml')
    native_baseline(before)
    helper_preview(value)
    candidate = projection.render(before, manifest, home, selector_mutation=True)
    require(projection.restore(candidate.data, candidate.recovery) == before, 'projection_roundtrip_failed')
    return {'status': 'preview', 'profile': value['profile'], 'model': value['model'],
        'kind': value['kind'], 'display_name': value['display_name'], 'plan_sha256': digest(raw),
        'current_config_sha256': digest(before), 'configuration_changed': False,
        'model_requests': 0, 'desktop_launch': False, 'desktop_acceptance': 'unverified'}


def maintenance_status(home):
    """Read only: retained direct cycles may admit a separate entry upgrade."""
    home = checked_home(home)
    prior_cycle(home)
    return {'status': 'maintenance_ready', 'configuration_changed': False,
        'model_requests': 0, 'desktop_launch': False}


@contextmanager
def lifecycle_guard(value):
    """Observe exact old services and empty queues, reserve their inactive port."""
    _lifecycle_observe(value)
    with socket.socket() as listener:
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', value['router_port']))
        yield lambda: _lifecycle_observe(value)


def _lifecycle_observe(value):
    from operator_core.responses_labels import assert_registry_edit_stopped
    import operator_web_service as web
    project, home = Path(value['project']), Path(value['home'])
    require(not (home / 'operator-unified-activation').exists(), 'legacy_activation_requires_review')
    require(all(row['name'].lower() != 'chatgpt.exe' for row in web.windows_process_entries()),
        'normal_desktop_exit_required')
    runtime = project / '.codex/feishu-codex-operator-runtime'
    router = runtime / 'model-router'
    assert_registry_edit_stopped(router)
    database = native.checked_path(runtime / 'state.sqlite3')
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        count = connection.execute("SELECT COUNT(*) FROM inbox_events WHERE status IN "
            "('queued','running','control_sending','reply_pending') OR "
            "(status='retryable_failed' AND COALESCE(last_error,'')<>'producer_unavailable_no_retry')").fetchone()[0]
    finally:
        connection.close()
    require(count == 0, 'operator_requests_pending')
    profile = project / '.codex/operator-web-service'
    if profile.exists():
        checked = web.status(native.checked_path(profile, directory=True))
        require(checked.get('configuration_current') is True and
            (checked.get('status') == 'ready' and checked.get('active') is False
             and checked.get('session_bound') is True or
             checked.get('status') in ('configured', 'stopped') and checked.get('start_available') is not False),
            'web_service_busy_or_uncertain')


def saved_api_credential(manifest):
    """Check only presence in saved Windows scope; never return or copy a key."""
    name = manifest['provider']['env_key']
    if manifest['kind'] == 'local' and not name:
        return
    require(os.name == 'nt', 'saved_api_credential_unavailable')
    import winreg
    for scope, location in ((winreg.HKEY_CURRENT_USER, 'Environment'),
            (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
        try:
            with winreg.OpenKey(scope, location, 0, winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, name)
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) and value.strip():
                    return
                # A saved User value shadows Machine scope even when unusable.
                raise DirectEntryError('direct_entry_saved_api_credential_unavailable')
        except FileNotFoundError:
            continue
        except OSError:
            raise DirectEntryError('direct_entry_saved_api_credential_unavailable') from None
    raise DirectEntryError('direct_entry_saved_api_credential_unavailable')


def activate(plan_path, expected_plan_sha256, expected_current_config_sha256):
    value, plan_raw, manifest = load_plan(plan_path)
    require(digest(plan_raw) == expected_plan_sha256, 'plan_preview_changed')
    require(Path(sys.executable) == Path(value['python']['path']), 'selected_python_required')
    home = Path(value['home'])
    saved_api_credential(manifest)
    with lifecycle_guard(value) as recheck_lifecycle:
        prior = prior_cycle(home)
        before = transaction.observe_config(home / 'config.toml')
        require(digest(before.data) == expected_current_config_sha256, 'config_preview_changed')
        native_baseline(before.data)
        helper_preview(value)
        candidate = projection.render(before.data, manifest, home, selector_mutation=True)
        require(projection.restore(candidate.data, candidate.recovery) == before.data, 'projection_roundtrip_failed')
        root = home / 'operator-direct-entry'
        for directory in (root, root / 'cycles'):
            if not directory.exists():
                private_directory(directory)
        cycle = secrets.token_hex(16)
        folder = root / 'cycles' / cycle
        private_directory(folder)
        retained = {'config-before.bin': before.data, 'config-candidate.bin': candidate.data,
            'projection.json': encoded(candidate.recovery),
            'profile.json': read(Path(value['state']) / 'manifest.json'), 'plan.json': plan_raw}
        for name, raw in retained.items():
            record(folder / name, raw)
        intent = {'schema_version': 1, 'contract': 'operator_direct_entry_cycle_v1',
            'project': value['project'], 'home': value['home'], 'cycle': cycle,
            'plan_sha256': digest(plan_raw), 'native_helper_sha256': value['native_helper']['sha256'],
            'source_sha256': value['source_sha256'], 'config_before_present': True,
            'before_identity': {'volume': before.identity.volume, 'file_id': before.identity.file_id},
            'files': {name: digest(raw) for name, raw in retained.items()}}
        intent_raw = encoded(intent)
        record(folder / 'intent.json', intent_raw)
        pointer = encoded({'schema_version': 1, 'contract': 'operator_direct_entry_active_v1',
            'cycle': cycle, 'intent_sha256': digest(intent_raw)})
        native.replace_file(root / 'active.json', (prior or b'', prior is not None), pointer)
        # From this point the cycle is terminal even if no config write occurs.
        value_now, raw_now, manifest_now = load_plan(plan_path)
        require(raw_now == plan_raw and manifest_now == manifest and value_now == value, 'inputs_changed')
        require(read(root / 'active.json', 16384) == pointer, 'active_cycle_changed')
        require(transaction.observe_config(home / 'config.toml') == before, 'config_preview_changed')
        recheck_lifecycle()
        outcome = transaction.replace_config_once(home / 'config.toml', before, candidate.data, folder)
        receipt = {'schema_version': 1, 'contract': 'operator_direct_entry_applied_v1',
            'cycle': cycle, 'intent_sha256': digest(intent_raw), 'status': outcome.status,
            'reason': outcome.reason, 'transaction': str(outcome.directory) if outcome.directory else None}
        record(folder / 'applied.json', receipt)
        require(outcome.status == 'applied', 'config_transaction_uncertain')
        return {'status': 'config_applied', 'cycle': cycle, 'configuration_changed': True,
            'model_requests': 0, 'desktop_launch': False, 'desktop_acceptance': 'unverified'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'preview', 'activate', 'maintenance-status'))
    parser.add_argument('--plan', type=Path)
    for name in ('state', 'project', 'home', 'python', 'native-helper'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--router-port', type=int, default=4317)
    parser.add_argument('--expected-plan-sha256')
    parser.add_argument('--expected-current-config-sha256')
    args = parser.parse_args(argv)
    try:
        require(args.action == 'maintenance-status' or args.plan is not None, 'plan_argument_required')
        if args.action == 'maintenance-status':
            require(args.plan is None, 'maintenance_plan_argument_invalid')
            result = maintenance_status(args.home or default_home())
        elif args.action == 'prepare':
            require(all(getattr(args, name) is not None for name in
                ('state', 'project', 'home', 'python', 'native_helper')), 'prepare_arguments_required')
            result = prepare(args.state, args.project, args.home, args.python,
                args.native_helper, args.plan, router_port=args.router_port)
        elif args.action == 'preview':
            result = preview(args.plan)
        else:
            result = activate(args.plan, args.expected_plan_sha256, args.expected_current_config_sha256)
    except Exception as error:
        code = str(error)
        if not re.fullmatch(r'(?:direct_entry|direct_profile|native_models)_[a-z_]{1,80}', code):
            code = 'direct_entry_unavailable_no_retry'
        print(json.dumps({'status': 'needs_review', 'reason': code, 'model_requests': 0,
            'desktop_launch': False, 'configuration_changed': 'unknown' if args.action == 'activate' else False}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
