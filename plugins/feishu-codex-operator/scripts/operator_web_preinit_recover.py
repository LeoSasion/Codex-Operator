"""Explicit retirement of one proven pre-initialization saved Web launch.

This is deliberately separate from the stopped-snapshot recovery path. It does
not start a service, retry a request, repair a Python installation, or claim a
clean stop. The failed launch record and all browser/login files remain intact.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

import operator_web_service as manager
from operator_core.responses_capabilities import RouterError


ERROR_CODES = frozenset({
    'web_preinit_record_invalid', 'web_preinit_runtime_changed',
    'web_preinit_source_changed', 'web_preinit_process_live',
    'web_preinit_state_present', 'web_preinit_marker_present',
    'web_preinit_import_unverified', 'web_preinit_transaction_exists',
    'web_preinit_preview_changed', 'web_preinit_recovery_required',
})
MISSING_AIOHTTP_EXIT = 37
SOURCE_NAMES = ('operator_web_model.py', str(Path('operator_core') / 'web_openai_tunnel.py'))
RECORD_KEYS = frozenset({'version', 'attempt', 'phase', 'pid', 'process', 'runtime'})
IMPORT_PROBE = '''
import importlib.util
import sys
sys.path[0] = sys.argv[1]
if importlib.util.find_spec('aiohttp') is not None:
    raise SystemExit(38)
try:
    import aiohttp
except ModuleNotFoundError as error:
    raise SystemExit(37 if error.name == 'aiohttp' else 39)
except BaseException:
    raise SystemExit(39)
raise SystemExit(38)
'''


def _saved_source_identity(runtime):
    source_root = runtime.get('source_root')
    manager.require(isinstance(source_root, str) and Path(source_root).is_absolute(),
        'web_preinit_runtime_changed')
    root = manager.checked_path(source_root, directory=True)
    manager.require(Path(runtime['backend']) == root / 'operator_web_model.py',
        'web_preinit_runtime_changed')
    sources = runtime.get('sources')
    manager.require(isinstance(sources, dict), 'web_preinit_runtime_changed')
    for name in SOURCE_NAMES:
        expected = sources.get(name)
        manager.require(isinstance(expected, str) and manager.DIGEST.fullmatch(expected),
            'web_preinit_runtime_changed')
        actual = manager.digest(manager.read_bytes(manager.checked_path(root / name), 4 * 1024 * 1024))
        manager.require(actual == expected, 'web_preinit_source_changed')
    for name, hash_name in (('python', 'python_sha256'),
                            ('worker_python', 'worker_python_sha256')):
        path = manager.checked_path(runtime[name])
        manager.require(manager.file_digest(path) == runtime[hash_name],
            'web_preinit_runtime_changed')


def _missing_aiohttp(profile, runtime):
    """Probe only the saved interpreter's import boundary, without a service."""
    try:
        result = subprocess.run(
            [runtime['python'], '-E', '-s', '-B', '-u', '-c', IMPORT_PROBE,
                runtime['source_root']],
            cwd=str(profile), env=manager.child_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, shell=False, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            check=False)
    except (OSError, subprocess.TimeoutExpired):
        manager.require(False, 'web_preinit_import_unverified')
    manager.require(result.returncode == MISSING_AIOHTTP_EXIT,
        'web_preinit_import_unverified')


def _snapshot(profile, config, record, *, prepared_transaction=None):
    manager.require(record is not None and set(record) == RECORD_KEYS
        and record['version'] == 1 and record['phase'] == 'uncertain'
        and isinstance(record['attempt'], str) and manager.ID.fullmatch(record['attempt'])
        and type(record['pid']) is int and record['pid'] > 0
        and record['runtime'] == config['runtime'], 'web_preinit_record_invalid')
    owner = record['process']
    runtime = record['runtime']
    manager.require(isinstance(owner, dict) and set(owner) == {'pid', 'birth', 'executable'}
        and owner['pid'] == record['pid'] and isinstance(owner['birth'], str)
        and owner['birth'].isdigit() and owner['executable'] == runtime['python'],
        'web_preinit_record_invalid')
    manager.require(manager.settings_identity(config['settings']['path']) == config['settings'],
        'web_manager_settings_changed')
    _saved_source_identity(runtime)
    state = manager.state_path(profile, record)
    manager.require(not state.exists() and not state.is_symlink()
        and not getattr(state, 'is_junction', lambda: False)(), 'web_preinit_state_present')
    observed = manager.process_identity(owner['pid'])
    manager.require(observed is None or (isinstance(observed, dict)
        and observed.get('birth') != owner['birth']), 'web_preinit_process_live')
    manager.recovery_dependencies_absent(config)
    settings = manager.service.loads(manager.read_bytes(config['settings']['path']))
    manager.require(settings.get('transport') == 'mcp_v1', 'web_preinit_recovery_required')
    mcp = settings['mcp']
    marker = manager.checked_path(Path(mcp['binding_file']).parent /
        ('active-' + mcp['tunnel_id'] + '.json'), exists=False)
    manager.require(not marker.exists() and not marker.is_symlink()
        and not getattr(marker, 'is_junction', lambda: False)(), 'web_preinit_marker_present')
    history = manager.checked_path(profile / 'history', directory=True)
    transactions = tuple(history.glob('preinit-recovery-' + record['attempt'] + '-*'))
    manager.require((not transactions if prepared_transaction is None else
        len(transactions) == 1 and transactions[0] == prepared_transaction),
        'web_preinit_transaction_exists')
    _missing_aiohttp(profile, runtime)
    paths = (profile / 'profile.json', profile / 'current.json',
        profile / 'instances' / (record['attempt'] + '.json'),
        Path(config['settings']['path']))
    files = {str(path): manager.digest(manager.read_bytes(path)) for path in paths}
    value = {'version': 1, 'attempt': record['attempt'], 'outcome':
        'uncertain_launch_preinit_import_failure_retired', 'files': files,
        'sources': {name: runtime['sources'][name] for name in SOURCE_NAMES},
        'python_sha256': runtime['python_sha256']}
    value['preview_sha256'] = manager.digest(json.dumps(value, sort_keys=True).encode('utf-8'))
    return value


def recover_preinit(profile, *, expected_preview=None):
    profile, _ = manager.load_profile(profile, validate_current=False)
    with manager.operation_lock(profile):
        profile, config = manager.load_profile(profile, validate_current=False)
        value = _snapshot(profile, config, manager.current_record(profile))
        if expected_preview is None:
            return {'status': 'recovery_preview', 'preview_sha256': value['preview_sha256'],
                'summary': '已核对这次后台在初始化前失败；可显式归档旧占用，原记录与登录保持。'}
        manager.require(isinstance(expected_preview, str)
            and manager.DIGEST.fullmatch(expected_preview)
            and expected_preview == value['preview_sha256'],
            'web_preinit_preview_changed')
        history = manager.checked_path(profile / 'history', directory=True)
        transaction = history / ('preinit-recovery-' + value['attempt'] + '-'
            + secrets.token_hex(16))
        manager.private_directory(transaction)
        for index, (name, expected) in enumerate(value['files'].items()):
            raw = manager.read_bytes(Path(name))
            manager.require(manager.digest(raw) == expected, 'web_preinit_preview_changed')
            (transaction / (str(index) + '.original')).write_bytes(raw)
        receipt = {**value, 'phase': 'prepared', 'launched': False,
            'replayed': False, 'clean_stop_claimed': False}
        manager.service.write_json(transaction / 'receipt.json', receipt)
        # A failed recheck leaves a prepared journal for manual review. Never
        # remove it or silently repeat this one-shot retirement.
        manager.require(_snapshot(profile, config, manager.current_record(profile),
            prepared_transaction=transaction) == value,
            'web_preinit_preview_changed')
        pointer = profile / 'current.json'
        manager.require(manager.digest(manager.read_bytes(pointer)) == value['files'][str(pointer)],
            'web_preinit_preview_changed')
        os.rename(pointer, transaction / 'current.json')
        receipt['phase'] = 'retired'
        manager.service.write_json(transaction / 'receipt.json', receipt)
        return {'status': 'recovered_preinit',
            'summary': '旧占用已单次归档；原异常、登录和请求记录保留，未启动或重做请求。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preview', 'apply'))
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--expected-preview')
    args = parser.parse_args()
    try:
        manager.require((args.action == 'apply') == (args.expected_preview is not None),
            'web_preinit_preview_changed')
        result = recover_preinit(args.profile, expected_preview=args.expected_preview)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, RouterError) and str(error) in (
            ERROR_CODES | manager.ERROR_CODES) else 'web_preinit_unavailable_no_retry'
        print(json.dumps({'status': 'unavailable', 'code': code,
            'summary': '本次占用未归档；需核对原始记录，不会自动启动或重做请求。'},
            ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
