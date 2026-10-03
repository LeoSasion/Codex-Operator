"""Private, explicit lifecycle entry for an already configured Web service.

Configuration references existing settings; it never copies keys, edits Codex,
registers a model, opens a browser, or installs a service. Each explicit start
records the may-have-started boundary before creating one hidden child. A live
owned instance is reused. A clean stop or an explicit, checked dead-instance
retirement permits a later start. Unknown outcomes never trigger another launch.
"""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError

import operator_web_model as service
from operator_core.web_browser_driver import child_environment, private_directory
from operator_core.web_mcp_transport import require, WebBrowserNetworkError


LOCK_BYTES = b'operator-web-service-lock-v1\n'
ID = re.compile(r'[a-f0-9]{32}')
DIGEST = re.compile(r'[a-f0-9]{64}')
START_OBSERVATION_SECONDS = 5
START_READY_OBSERVATION_SECONDS = 20
DEPENDENCY_CHECK_TIMEOUT_SECONDS = 10
DEPENDENCY_IMPORT_PROBE = (
    "import importlib,sys;sys.path.insert(0,sys.argv[1]);"
    "importlib.import_module('aiohttp');"
    "importlib.import_module('operator_web_model');"
    "importlib.import_module('operator_core.web_openai_tunnel');"
    "importlib.import_module('operator_core.web_responses_provider')"
)
ERROR_CODES = frozenset('''web_manager_absolute_path_required web_manager_linked_path_rejected
web_manager_path_unavailable web_manager_file_bound web_manager_record_invalid
web_manager_executable_bound web_manager_source_bound web_manager_hidden_settings_required
web_manager_browser_settings_required web_manager_transport_invalid web_manager_fixed_connection_required
web_manager_tunnel_client_changed web_manager_profile_already_exists web_manager_profile_invalid
web_manager_runtime_changed web_manager_settings_invalid web_manager_settings_changed web_manager_lock_changed
web_manager_operation_in_progress web_manager_pid_invalid web_manager_process_observation_unavailable
web_manager_pointer_invalid web_manager_launch_record_invalid web_manager_launch_ownership_unknown
web_manager_process_identity_changed web_manager_session_invalid web_manager_session_changed
web_manager_uncertain_launch_no_retry web_manager_uncertain_stop_no_retry web_manager_health_bound
web_manager_health_invalid web_manager_status_identity_changed web_manager_live_identity_changed
web_manager_child_exited_no_retry web_manager_start_not_live web_manager_action_invalid
web_manager_replacement_invalid web_manager_service_not_started web_manager_live_service_required
web_manager_settings_argument_invalid web_manager_stopped_update_required web_manager_worker_identity_changed
web_manager_worker_parent_unverified web_service_drain_invalid web_assistance_requires_idle_session
web_service_stop_already_requested web_service_command_pending web_manager_launch_record_changed
web_service_stop_identity_changed web_manager_status_invalid web_manager_fixed_connection_in_use'''.split())
ERROR_CODES |= frozenset('''web_manager_detached_launch_failed web_manager_detached_launch_invalid
web_manager_recovery_not_dead web_manager_recovery_dependencies_live web_manager_recovery_changed
web_manager_recovery_marker_invalid web_manager_recovery_required web_manager_recovery_unsupported
web_manager_preinit_recovery_pending'''.split())
ERROR_CODES |= frozenset({'web_manager_python_dependencies_unavailable', 'web_service_status_invalid',
    'web_manager_start_identity_changed', 'web_manager_start_observation_invalid'})


def checked_path(value, *, exists=True, directory=False):
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'web_manager_absolute_path_required')
    for part in (path, *path.parents):
        require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(),
            'web_manager_linked_path_rejected')
    if exists:
        require(path.is_dir() if directory else path.is_file(), 'web_manager_path_unavailable')
    return path


def read_bytes(path, limit=65536):
    path = checked_path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'web_manager_file_bound')
    return raw


def read_json(path):
    value = service.loads(read_bytes(path))
    require(isinstance(value, dict), 'web_manager_record_invalid')
    return value


def read_status_bytes(path):
    raw = read_bytes(path, service.LEGACY_STATUS_SNAPSHOT_BYTES)
    service.status_snapshot_value(raw, bound_error='web_manager_file_bound')
    return raw


def read_status_json(path):
    return service.status_snapshot_value(read_status_bytes(path), bound_error='web_manager_file_bound')


def recovery_file_bytes(path, state):
    return read_status_bytes(path) if path == state / 'status.json' else read_bytes(path)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    path = checked_path(path)
    result = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(block)
            require(size <= 512 * 1024 * 1024, 'web_manager_executable_bound')
            result.update(block)
    return result.hexdigest()


def runtime_identity():
    root = Path(__file__).resolve().parent
    sources = [Path(__file__).resolve(), root / 'operator_web_model.py',
        *sorted((root / 'operator_core').glob('*.py')), *sorted(root.glob('web_browser_*.cjs')),
        root / 'operator_core' / 'web_model_catalog.json']
    require(len(sources) <= 128, 'web_manager_source_bound')
    return {'python': str(Path(sys.executable).resolve()),
        'python_sha256': file_digest(Path(sys.executable).resolve()),
        'worker_python': str(Path(getattr(sys, '_base_executable', sys.executable)).resolve()),
        'worker_python_sha256': file_digest(Path(getattr(sys, '_base_executable', sys.executable)).resolve()),
        'python_version': sys.version, 'backend': str(root / 'operator_web_model.py'),
        'source_root': str(root),
        'sources': {str(path.relative_to(root)): digest(read_bytes(path, 4 * 1024 * 1024))
            for path in sources}}


def settings_identity(path):
    raw = read_bytes(path)
    value = service.loads(raw)
    require(isinstance(value, dict) and set(value) <= {
        'electron', 'profile_directory', 'session_partition', 'proxy_rules', 'timeout_ms',
        'software_rendering', 'citation_mode', 'window_mode', 'browser_lifecycle',
        'startup_assistance', 'transport', 'mcp', 'native_cancellation_mode', 'native_cancellation_home'}
        and value.get('window_mode', 'background') == 'background'
        and value.get('browser_lifecycle', 'session_v1') == 'session_v1'
        and value.get('startup_assistance', False) is False,
        'web_manager_hidden_settings_required')
    require({'electron', 'profile_directory', 'session_partition'} <= set(value),
        'web_manager_browser_settings_required')
    mode = value.get('transport', 'text_only')
    require(mode in ('text_only', 'mcp_v1') and (mode == 'mcp_v1') == ('mcp' in value),
        'web_manager_transport_invalid')
    service.selected_native_cancellation_home(value)
    dependencies = {'electron': {'path': str(checked_path(value['electron'])),
        'sha256': file_digest(value['electron'])}}
    checked_path(value['profile_directory'], directory=True)
    if mode == 'mcp_v1':
        mcp = value['mcp']
        require(isinstance(mcp, dict) and mcp.get('mode') == 'openai_tunnel_v1',
            'web_manager_fixed_connection_required')
        require({'tunnel_client', 'tunnel_client_sha256', 'tunnel_id', 'api_key_file', 'binding_file'} <= set(mcp)
            and isinstance(mcp['tunnel_id'], str)
            and re.fullmatch(r'tunnel_[a-f0-9]{32}', mcp['tunnel_id']),
            'web_manager_fixed_connection_required')
        actual = file_digest(mcp['tunnel_client'])
        require(actual == mcp['tunnel_client_sha256'], 'web_manager_tunnel_client_changed')
        dependencies['tunnel_client'] = {'path': str(checked_path(mcp['tunnel_client'])), 'sha256': actual}
        # Validate references without reading or copying the runtime key.
        checked_path(mcp['api_key_file'])
        binding = checked_path(mcp['binding_file'], exists=False)
        checked_path(binding.parent, directory=True)
    return {'path': str(checked_path(path)), 'sha256': digest(raw), 'dependencies': dependencies}


def fixed_connection_available(config):
    """Read-only preflight; never adopt or remove another instance's lock."""
    raw = read_bytes(config['settings']['path'])
    require(digest(raw) == config['settings']['sha256'], 'web_manager_settings_changed')
    settings = service.loads(raw)
    if settings.get('transport', 'text_only') != 'mcp_v1':
        return True
    mcp = settings['mcp']
    marker = checked_path(Path(mcp['binding_file']).parent /
        ('active-' + mcp['tunnel_id'] + '.json'), exists=False)
    return not marker.exists()


def configure(profile, settings):
    profile = checked_path(profile, exists=False)
    checked_path(profile.parent, directory=True)
    config = {'version': 1, 'settings': settings_identity(settings), 'runtime': runtime_identity()}
    if profile.exists():
        profile, _ = load_profile(profile, validate_current=False)
        with operation_lock(profile):
            profile, previous = load_profile(profile, validate_current=False)
            require(config == {'version': 1, 'settings': settings_identity(settings), 'runtime': runtime_identity()},
                'web_manager_settings_changed')
            if previous == config:
                return {'status': 'configured', 'reused': True,
                    'summary': '现有入口的配置一致，继续沿用；无需重复填写连接或密钥。'}
            current = current_record(profile)
            result, _ = observe(profile, previous, current)
            require(result['status'] in ('stopped', 'configured'), 'web_manager_stopped_update_required')
            require(config == {'version': 1, 'settings': settings_identity(settings), 'runtime': runtime_identity()},
                'web_manager_settings_changed')
            # Preserve every prior configuration before explicit stopped update.
            history = profile / 'history'
            checked_path(history, directory=True)
            service.write_json(history / ('profile-' + secrets.token_hex(16) + '.json'), previous)
            service.write_json(profile / 'profile.json', config)
            return {'status': 'configured', 'updated': True,
                'summary': '已在无活动实例后更新入口登记；原登记已保留，固定连接和密钥未改动。'}
    private_directory(profile)
    private_directory(profile / 'instances')
    private_directory(profile / 'history')
    (profile / 'manager.lock').write_bytes(LOCK_BYTES)
    service.write_json(profile / 'profile.json', config)
    return {'status': 'configured', 'summary': '已保存现有配置引用；以后沿用该入口，无需重复填写固定连接或密钥。'}


def load_profile(profile, *, validate_current=True):
    profile = checked_path(profile, directory=True)
    checked_path(profile / 'instances', directory=True)
    config = read_json(profile / 'profile.json')
    require(set(config) == {'version', 'settings', 'runtime'} and config['version'] == 1,
        'web_manager_profile_invalid')
    runtime = config['runtime']
    require(isinstance(runtime, dict) and all(isinstance(runtime.get(key), str)
        and Path(runtime[key]).is_absolute() for key in ('python', 'worker_python', 'backend'))
        and all(isinstance(runtime.get(key), str) and DIGEST.fullmatch(runtime[key])
            for key in ('python_sha256', 'worker_python_sha256')), 'web_manager_profile_invalid')
    require(isinstance(config['settings'], dict) and isinstance(config['settings'].get('path'), str),
        'web_manager_settings_invalid')
    if validate_current:
        require(config['runtime'] == runtime_identity(), 'web_manager_runtime_changed')
        require(config['settings'] == settings_identity(config['settings']['path']), 'web_manager_settings_changed')
    return profile, config


@contextmanager
def operation_lock(profile):
    path = checked_path(profile / 'manager.lock')
    with path.open('r+b', buffering=0) as stream:
        try:
            require(stream.read(len(LOCK_BYTES) + 1) == LOCK_BYTES, 'web_manager_lock_changed')
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            require(False, 'web_manager_operation_in_progress')
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def process_identity(pid):
    """Read executable and process birth, never infer ownership from PID alone."""
    require(type(pid) is int and pid > 0, 'web_manager_pid_invalid')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return None
            require(False, 'web_manager_process_observation_unavailable')
        try:
            creation, exit_time, kernel_time, user_time = [wintypes.FILETIME() for _ in range(4)]
            require(kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time)), 'web_manager_process_observation_unavailable')
            if exit_time.dwHighDateTime or exit_time.dwLowDateTime:
                return None
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            require(kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)),
                'web_manager_process_observation_unavailable')
            birth = str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            return {'pid': pid, 'birth': birth, 'executable': str(Path(buffer.value).resolve())}
        finally:
            kernel.CloseHandle(handle)
    proc = Path('/proc') / str(pid)
    try:
        raw = (proc / 'stat').read_text()
        fields = raw[raw.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'birth': fields[19], 'executable': str((proc / 'exe').resolve(strict=True))}
    except FileNotFoundError:
        return None
    except OSError:
        require(False, 'web_manager_process_observation_unavailable')


def windows_process_entries():
    import ctypes
    from ctypes import wintypes
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    require(snapshot != ctypes.c_void_p(-1).value, 'web_manager_process_observation_unavailable')
    try:
        entry = ProcessEntry(); entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        result = []
        while found:
            require(len(result) < 32768, 'web_manager_process_observation_unavailable')
            result.append({'pid': entry.th32ProcessID, 'parent': entry.th32ParentProcessID,
                'name': entry.szExeFile})
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        require(ctypes.get_last_error() == 18, 'web_manager_process_observation_unavailable')
        return result
    finally:
        kernel.CloseHandle(snapshot)


def parent_pid(pid):
    if os.name != 'nt':
        raw = (Path('/proc') / str(pid) / 'stat').read_text()
        return int(raw[raw.rfind(')') + 2:].split()[1])
    for entry in windows_process_entries():
        if entry['pid'] == pid:
            return entry['parent']
    require(False, 'web_manager_worker_parent_unverified')


def current_record(profile):
    pointer = profile / 'current.json'
    if not pointer.exists() and not pointer.is_symlink():
        return None
    value = read_json(pointer)
    require(set(value) == {'version', 'attempt'} and value['version'] == 1
        and isinstance(value['attempt'], str) and ID.fullmatch(value['attempt']), 'web_manager_pointer_invalid')
    record = read_json(profile / 'instances' / (value['attempt'] + '.json'))
    require(record.get('version') == 1 and record.get('attempt') == value['attempt']
        and record.get('phase') in ('may_have_started', 'starting', 'running', 'uncertain'),
        'web_manager_launch_record_invalid')
    return record


def state_path(profile, record):
    require(isinstance(record.get('attempt'), str) and ID.fullmatch(record['attempt']),
        'web_manager_launch_record_invalid')
    return checked_path(profile / 'instances' / record['attempt'], exists=False)


def save_record(profile, record):
    service.write_json(profile / 'instances' / (record['attempt'] + '.json'), record)


def owned_process(record, config, *, stopped_snapshot=False):
    runtime = record.get('runtime')
    require(isinstance(runtime, dict) and all(isinstance(runtime.get(key), str)
        for key in ('python', 'worker_python')), 'web_manager_launch_record_invalid')
    owner = record.get('process')
    require(isinstance(owner, dict) and set(owner) == {'pid', 'birth', 'executable'}
        and type(owner['pid']) is int and owner['pid'] > 0
        and isinstance(owner['birth'], str) and owner['birth'].isdigit()
        and Path(owner['executable']) == Path(runtime['python']),
        'web_manager_launch_ownership_unknown')
    observed = process_identity(owner['pid'])
    if observed is not None and observed != owner:
        require(stopped_snapshot, 'web_manager_process_identity_changed')
        observed = None  # A different birth cannot be the recorded old process.
    worker = record.get('worker')
    worker_observed = None
    if worker is not None:
        require(isinstance(worker, dict) and set(worker) == {'pid', 'birth', 'executable'}
            and type(worker['pid']) is int and worker['pid'] > 0
            and isinstance(worker['birth'], str) and worker['birth'].isdigit()
            and Path(worker['executable']) in (Path(runtime['worker_python']), Path(runtime['python'])),
            'web_manager_launch_ownership_unknown')
        worker_observed = process_identity(worker['pid'])
        if worker_observed is not None and worker_observed != worker:
            require(stopped_snapshot, 'web_manager_worker_identity_changed')
            worker_observed = None
    return observed is not None or worker_observed is not None


def session_snapshot(state, record):
    raw = read_bytes(state / 'session.json')
    session = service.loads(raw)
    require(isinstance(session, dict) and session.get('version') == 1
        and type(session.get('pid')) is int and session['pid'] > 0
        and ('worker' not in record or session['pid'] == record['worker']['pid'])
        and isinstance(session.get('instance'), str) and ID.fullmatch(session['instance'])
        and isinstance(session.get('base_url'), str)
        and re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}/v1', session['base_url'])
        and 1 <= int(session['base_url'].split(':')[2][:-3]) <= 65535
        and isinstance(session.get('token'), str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', session['token']),
        'web_manager_session_invalid')
    if 'instance' in record or 'session_sha256' in record:
        require(record.get('instance') == session['instance'] and record.get('session_sha256') == digest(raw),
            'web_manager_session_changed')
    return session, digest(raw)


def session_worker(session, record, config):
    worker = process_identity(session['pid'])
    require(worker is not None, 'web_manager_worker_identity_changed')
    if 'worker' in record:
        require(worker == record['worker'], 'web_manager_worker_identity_changed')
    elif session['pid'] == record['process']['pid']:
        require(worker == record['process'], 'web_manager_worker_identity_changed')
    else:
        # Windows venv python.exe is a launcher; the actual interpreter is its
        # direct child. Bind both observed process births and the pinned base
        # interpreter, never accept an arbitrary Python PID from session.json.
        require(Path(worker['executable']) == Path(record['runtime']['worker_python'])
            and int(worker['birth']) >= int(record['process']['birth'])
            and parent_pid(worker['pid']) == record['process']['pid']
            and process_identity(record['process']['pid']) == record['process'],
            'web_manager_worker_parent_unverified')
    return worker


def safe_guidance(details, health):
    require(details.get('state') in ('ready', 'preparing', 'connection', 'reconnecting', 'assistance',
        'unavailable', 'draining', 'stopped') and type(details.get('needs_assistance')) is bool,
        'web_manager_status_invalid')
    if details['state'] == 'assistance' and (details.get('assistance') or {}).get('inspect_completed') is True:
        return '正在查看已结束对话的只读文字快照；关闭预览后恢复接收请求，原页面保留。'
    summaries = {'ready': '后台已就绪，沿用现有固定连接和登录配置。',
        'preparing': '后台正在无请求地检查已保存的网页会话；请稍后查看状态。',
        'connection': '请完成当前固定连接的绑定；已有插件时先核对绑定，无需重复创建。',
        'reconnecting': '连接正在恢复，已保存的配置保留；未自动重做请求。',
        'assistance': '当前网页会话尚未就绪；请先查看准确页面，再判断是否需要人工操作。',
        'unavailable': '当前后台不可用，请检查已有实例；连接和配置仍保留。',
        'draining': '后台正在停止，等待当前请求结束；不会接纳新的请求。',
        'stopped': '后台已停止，等待所属进程结束；固定连接和配置仍保留。'}
    if details['needs_assistance']:
        return summaries['assistance']
    return '当前请求仍在处理中。' if health['active'] else summaries[details['state']]


def safe_diagnostics(details, health):
    """Separate bounded local observations; never infer a cloud rejection cause.

    Browser events are from the saved status snapshot, transport counts from
    authenticated health. They are not an atomic snapshot of the same request.
    No extra probe, transcript, assistant prose or arbitrary error text is read.
    """
    def count(value):
        return type(value) is int and 0 <= value <= 9007199254740991

    network = {'scope': 'saved_browser_attempt', 'state': 'unknown'}
    browser = details.get('browser')
    if isinstance(browser, dict) and count(browser.get('attempts')) and browser['attempts'] > 0:
        events = browser.get('events')
        if isinstance(events, list) and len(events) <= 128:
            current = [event for event in events if isinstance(event, dict)
                and type(event.get('attempt')) is int and event['attempt'] == browser['attempts']
                and event.get('kind') == 'model_network_state']
            if current:
                last = current[-1]
                phase, code, status = last.get('phase'), last.get('networkError'), last.get('status')
                if phase == 'sent' and code is None and status is None:
                    network.update(state='sent')
                elif phase == 'response_started' and code is None and type(status) is int and 100 <= status <= 599:
                    network.update(state='http_response', http_status=status)
                elif phase == 'error' and isinstance(code, str):
                    if code in WebBrowserNetworkError.codes:
                        network.update(state='network_error', code=code)
                    elif code == 'net::ERR_ABORTED':
                        network.update(state='aborted')
                    else:
                        network.update(state='other_error')
    transport = {'scope': 'local_transport_only', 'state': 'unknown'}
    observed = health.get('transport')
    if isinstance(observed, dict) and observed.get('scope') == 'transport_only':
        active, last = observed.get('active_turn'), observed.get('last_turn')
        turn = active if active is not None else last
        if active is None and last is None:
            transport.update(state='no_turn')
        elif isinstance(turn, dict) and all(count(turn.get(key)) for key in
                ('sequence', 'calls_accepted', 'calls_released', 'results_received')) \
                and turn['sequence'] > 0 \
                and turn['results_received'] <= turn['calls_released'] <= turn['calls_accepted']:
            transport.update(state='active' if active is not None else 'last_turn',
                **{key: turn[key] for key in ('calls_accepted', 'calls_released', 'results_received')})
            if type(turn.get('public_final_returned')) is bool:
                transport['public_final_returned'] = turn['public_final_returned']
    return {'network': network, 'tools': transport,
        'summary': '网页传输与本机工具接收分别记录；HTTP 200 不代表工具已投递，配对结果不代表执行成功。'}


def observe(profile, config, record):
    if record is None:
        return {'status': 'configured', 'summary': '配置已保存，后台尚未启动。请使用此入口启动。'}, None
    state = state_path(profile, record)
    stopped_snapshot = False
    if 'instance' in record and 'session_sha256' in record and (state / 'status.json').is_file():
        session, _ = session_snapshot(state, record)
        terminal = read_status_json(state / 'status.json')
        stopped_snapshot = terminal.get('instance') == session['instance'] and terminal.get('state') == 'stopped'
    # A reused PID proves the old process has gone only together with the exact
    # bound stopped snapshot. Never control that new process or use PID reuse
    # to recover an active/unknown launch.
    alive = owned_process(record, config, stopped_snapshot=stopped_snapshot)
    if not alive:
        require('instance' in record and 'session_sha256' in record, 'web_manager_uncertain_launch_no_retry')
        session, _ = session_snapshot(state, record)
        details = read_status_json(state / 'status.json')
        require(details.get('instance') == session['instance'] and details.get('state') == 'stopped',
            'web_manager_uncertain_stop_no_retry')
        return {'status': 'stopped', 'summary': '后台已正常停止，固定连接和登录配置仍保留；可从此入口再次启动。'}, None
    if not (state / 'session.json').exists():
        return {'status': 'starting', 'summary': '后台正在准备现有连接；可查看状态，未重复启动或打开辅助窗口。'}, None
    session, session_hash = session_snapshot(state, record)
    worker = session_worker(session, record, config)
    request = Request(session['base_url'][:-3] + '/health',
        headers={'Authorization': 'Bearer ' + session['token']})
    try:
        with build_opener(ProxyHandler({}), service.NoConnectionProbeRedirect()).open(request, timeout=3) as response:
            raw = response.read(65537)
    except HTTPError as error:
        error.close()
        raise
    require(len(raw) <= 65536, 'web_manager_health_bound')
    health = service.loads(raw)
    require(isinstance(health, dict) and health.get('ready') is True
        and type(health.get('active')) is bool and health.get('state') in
        ('ready', 'preparing', 'connection', 'reconnecting', 'assistance', 'draining', 'stopped'),
        'web_manager_health_invalid')
    details = read_status_json(state / 'status.json')
    require(details.get('instance') == session['instance'], 'web_manager_status_identity_changed')
    require(session_snapshot(state, record)[1] == session_hash and owned_process(record, config)
        and session_worker(session, record, config) == worker,
        'web_manager_live_identity_changed')
    return {'status': details['state'], 'active': health['active'],
        'needs_assistance': details.get('needs_assistance') is True,
        'summary': safe_guidance(details, health),
        'diagnostics': safe_diagnostics(details, health)}, (session, session_hash, health, worker)


def bind_session(profile, record, live):
    session, session_hash, _, worker = live
    updated = {**record, 'instance': session['instance'], 'session_sha256': session_hash,
        'worker': worker, 'phase': 'running'}
    if updated != record:
        save_record(profile, updated)
    return updated


def route_preview(profile):
    """Digest-only read; never publishes a route, writes state or prints a key."""
    profile, config = load_profile(profile)
    with operation_lock(profile):
        profile, config = load_profile(profile)
        record = current_record(profile)
        require(record is not None, 'web_manager_live_service_required')
        result, live = observe(profile, config, record)
        require(live is not None and result['status'] == 'ready' and not result['active'],
            'web_manager_idle_ready_required')
        session, session_hash, health, _ = live
        require(session.get('model') == service.SLUG and session.get('mode') == 'mcp_v1'
            and health.get('accepting_requests') is True, 'web_manager_tools_route_required')
        return {'profile_sha256': digest(read_bytes(profile / 'profile.json')),
            'session_sha256': session_hash}


def resolve_route(profile, expected):
    return resolve_routes(profile, expected)[0]


def resolve_routes(profile, expected, *, require_bound_session=False):
    """Capture one checked service generation. Only the caller retains its key."""
    from dataclasses import replace
    from operator_core.model_registry import WebServiceBinding
    require(isinstance(expected, dict) and set(expected) == {'profile_sha256', 'session_sha256'}
        and all(isinstance(v, str) and DIGEST.fullmatch(v) for v in expected.values()),
        'web_manager_route_digest_required')
    profile, config = load_profile(profile)
    with operation_lock(profile):
        profile, config = load_profile(profile)
        profile_raw = read_bytes(profile / 'profile.json')
        require(digest(profile_raw) == expected['profile_sha256'], 'web_manager_route_digest_changed')
        record = current_record(profile)
        require(record is not None and record.get('session_sha256', expected['session_sha256']) == expected['session_sha256'],
            'web_manager_route_digest_changed')
        # Publishing a persistent Desktop endpoint requires the live worker's
        # ownership receipt first. A read-only observation must not fabricate it.
        if require_bound_session:
            require(record.get('phase') == 'running' and 'worker' in record
                and 'instance' in record and record.get('session_sha256') == expected['session_sha256'],
                'web_manager_session_binding_required')
        result, live = observe(profile, config, record)
        require(live is not None and result['status'] == 'ready' and not result['active'],
            'web_manager_idle_ready_required')
        session, session_hash, health, _ = live
        require(session_hash == expected['session_sha256'] and session.get('model') == service.SLUG
            and session.get('mode') == 'mcp_v1' and health.get('accepting_requests') is True,
            'web_manager_tools_route_required')
        require(read_bytes(profile / 'profile.json') == profile_raw and current_record(profile) == record,
            'web_manager_route_digest_changed')
        # Compare again after the network observation. No process/config mutation.
        load_profile(profile)
        routes = service.text_routes(tools=True) if 'models' in session else (service.text_route(tools=True),)
        require('models' not in session or session['models'] == [route.slug for route in routes],
            'web_manager_model_catalog_changed')
        return tuple(replace(route, model=route.slug, api_base=session['base_url'],
            web_binding=WebServiceBinding(**expected, token=session['token'])) for route in routes)


def windows_powershell():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetSystemDirectoryW(buffer, len(buffer))
    require(0 < size < len(buffer), 'web_manager_detached_launch_invalid')
    return checked_path(Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe')


class DetachedWindowsChild:
    """Hold the exact CIM-created process handle; never reopen a reused PID."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.pid = pid
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
        require(bool(self.handle), 'web_manager_detached_launch_invalid')

    def poll(self):
        import ctypes
        from ctypes import wintypes
        value = wintypes.DWORD()
        require(self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(value)),
            'web_manager_process_observation_unavailable')
        return None if value.value == 259 else value.value

    def wait(self, timeout=None):
        milliseconds = 0xffffffff if timeout is None else max(0, int(timeout * 1000))
        result = self.kernel.WaitForSingleObject(self.handle, milliseconds)
        if result == 258:
            raise subprocess.TimeoutExpired('owned detached Web child', timeout)
        require(result == 0, 'web_manager_process_observation_unavailable')
        return self.poll()

    def kill(self):
        # Used by disposable fixture cleanup only. Production sends owned stop IPC.
        require(self.kernel.TerminateProcess(self.handle, 1), 'web_manager_process_observation_unavailable')

    def __del__(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def spawn_windows_child(argv, profile):
    # Match the existing Operator detached launcher. CREATE_BREAKAWAY on a
    # direct child alone can still inherit an outer Desktop job. CIM creates
    # the one child independently, with an explicit allowlisted environment.
    payload = {'command': subprocess.list2cmdline(argv), 'directory': str(profile),
        'environment': [key + '=' + value for key, value in sorted(child_environment().items())]}
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    require(len(raw) <= 32768, 'web_manager_detached_launch_invalid')
    encoded = base64.b64encode(raw).decode('ascii')
    script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$launch=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')) | ConvertFrom-Json
$startup=New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
    CreateFlags=[uint32]0x09000400; ShowWindow=[uint16]0
    EnvironmentVariables=[string[]]$launch.environment
}
$result=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine=[string]$launch.command; CurrentDirectory=[string]$launch.directory
    ProcessStartupInformation=$startup
}
if($result.ReturnValue -ne 0 -or $result.ProcessId -le 0){exit 1}
@{pid=[int]$result.ProcessId} | ConvertTo-Json -Compress
""".replace('PAYLOAD', encoded)
    command = [str(windows_powershell()), '-NoLogo', '-NoProfile', '-NonInteractive',
        '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode('ascii')]
    require(len(subprocess.list2cmdline(command)) < 32767, 'web_manager_detached_launch_invalid')
    result = subprocess.run(command, cwd=str(profile), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        env=child_environment(), creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    require(result.returncode == 0 and len(result.stdout) <= 4096 and len(result.stderr) <= 4096,
        'web_manager_detached_launch_failed')
    value = service.loads(result.stdout)
    require(isinstance(value, dict) and set(value) == {'pid'} and type(value['pid']) is int
        and value['pid'] > 0, 'web_manager_detached_launch_invalid')
    return DetachedWindowsChild(value['pid'])


def spawn_child(argv, profile):
    if os.name == 'nt':
        return spawn_windows_child(argv, profile)
    return subprocess.Popen(argv, cwd=str(profile), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
        env=child_environment(), creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        start_new_session=os.name != 'nt')


def check_python_dependencies(runtime, profile):
    """Import serving dependencies in the saved interpreter before any launch journal.

    The probe imports modules only. Its output is discarded, and any failure is
    one fixed public code. It cannot establish that a later launch will succeed.
    """
    python = checked_path(runtime['python'])
    source_root = checked_path(runtime['source_root'], directory=True)
    require(file_digest(python) == runtime['python_sha256'], 'web_manager_runtime_changed')
    try:
        result = subprocess.run(
            [str(python), '-I', '-B', '-c', DEPENDENCY_IMPORT_PROBE, str(source_root)],
            cwd=str(profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, shell=False, env=child_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=DEPENDENCY_CHECK_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        require(False, 'web_manager_python_dependencies_unavailable')
    require(result.returncode == 0, 'web_manager_python_dependencies_unavailable')


def recovery_dependencies_absent(config):
    """Conservatively reject even an unrelated live use of these exact binaries.

    Older instances did not journal child births. A dead parent alone is not
    sufficient evidence that its tunnel/browser has gone. Never stop candidates.
    """
    require(os.name == 'nt', 'web_manager_recovery_unsupported')
    paths = {Path(value['path']) for value in config['settings']['dependencies'].values()}
    names = {path.name.casefold() for path in paths}
    for entry in windows_process_entries():
        if entry['name'].casefold() in names:
            identity = process_identity(entry['pid'])
            require(identity is None or Path(identity['executable']) not in paths,
                'web_manager_recovery_dependencies_live')


def unbound_stopped_snapshot(profile, config, record):
    """Retire an unbound, request-free stopped launch without inventing ownership.

    This explicit maintenance path never binds a dead worker or changes status.
    A live process, request, marker or listener leaves the uncertainty intact.
    """
    import socket
    require(record.get('phase') == 'starting'
        and not {'worker', 'instance', 'session_sha256'} & set(record),
        'web_manager_recovery_required')
    require(not owned_process(record, config), 'web_manager_recovery_not_dead')
    require(settings_identity(config['settings']['path']) == config['settings'], 'web_manager_settings_changed')
    state = state_path(profile, record)
    session, session_hash = session_snapshot(state, record)
    details = read_status_json(state / 'status.json')
    require(details.get('instance') == session['instance'] and details.get('state') == 'stopped'
        and type(details.get('requests')) is int and details['requests'] == 0
        and details.get('browser', {}).get('active') is False
        and details.get('transport', {}).get('active_turn') is None,
        'web_manager_recovery_required')
    require(process_identity(session['pid']) is None, 'web_manager_recovery_not_dead')
    recovery_dependencies_absent(config)
    settings = service.loads(read_bytes(config['settings']['path']))
    if settings.get('transport', 'text_only') == 'mcp_v1':
        marker = Path(settings['mcp']['binding_file']).parent / ('active-' + settings['mcp']['tunnel_id'] + '.json')
        require(not marker.exists() and not marker.is_symlink(), 'web_manager_recovery_marker_invalid')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        if os.name == 'nt': reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reservation.bind(('127.0.0.1', int(session['base_url'].split(':')[2][:-3])))
    files = {str(path): digest(recovery_file_bytes(path, state)) for path in (profile / 'profile.json', profile / 'current.json',
        profile / 'instances' / (record['attempt'] + '.json'), state / 'session.json', state / 'status.json')}
    value = {'version': 1, 'attempt': record['attempt'], 'instance': session['instance'],
        'session_sha256': session_hash, 'files': files, 'marker': None,
        'outcome': 'unbound_request_free_stopped_snapshot_retired'}
    value['preview_sha256'] = digest(json.dumps(value, sort_keys=True).encode('utf-8'))
    return value


def recovery_snapshot(profile, config, record):
    if record is not None and 'worker' not in record:
        return unbound_stopped_snapshot(profile, config, record)
    require(record is not None and 'worker' in record and 'instance' in record,
        'web_manager_recovery_required')
    # PID reuse, missing ownership or observation failure remains a rejection.
    require(not owned_process(record, config), 'web_manager_recovery_not_dead')
    require(settings_identity(config['settings']['path']) == config['settings'],
        'web_manager_settings_changed')
    state = state_path(profile, record)
    session, session_hash = session_snapshot(state, record)
    details = read_status_json(state / 'status.json')
    require(details.get('instance') == session['instance'] and details.get('state') != 'stopped',
        'web_manager_recovery_required')
    recovery_dependencies_absent(config)
    snapshots = {str(path): digest(recovery_file_bytes(path, state)) for path in
        (profile / 'profile.json', profile / 'current.json',
         profile / 'instances' / (record['attempt'] + '.json'), state / 'session.json', state / 'status.json')}
    settings = service.loads(read_bytes(config['settings']['path']))
    marker = None
    if settings.get('transport', 'text_only') == 'mcp_v1':
        mcp = settings['mcp']
        connection_path = state / 'connection.json'
        connection = read_json(connection_path)
        require(connection.get('instance') == session['instance']
            and connection.get('tunnel_id') == mcp['tunnel_id']
            and connection.get('kind') == 'fixed_openai_tunnel'
            and isinstance(connection.get('connection_id'), str) and ID.fullmatch(connection['connection_id']),
            'web_manager_recovery_marker_invalid')
        marker = checked_path(Path(mcp['binding_file']).parent / ('active-' + mcp['tunnel_id'] + '.json'))
        require(marker.stat().st_nlink == 1, 'web_manager_recovery_marker_invalid')
        require(read_json(marker) == {'version': 1, 'instance': connection['connection_id'],
            'pid': record['worker']['pid'], 'state': str(state)}, 'web_manager_recovery_marker_invalid')
        snapshots[str(connection_path)] = digest(read_bytes(connection_path))
        snapshots[str(marker)] = digest(read_bytes(marker))
    value = {'version': 1, 'attempt': record['attempt'], 'instance': session['instance'],
        'session_sha256': session_hash, 'files': snapshots, 'marker': str(marker) if marker else None}
    value['preview_sha256'] = digest(json.dumps(value, sort_keys=True).encode('utf-8'))
    return value


def recover(profile, *, expected_preview=None):
    """Explicit archive of a proven dead instance; no launch, replay or clean-stop claim."""
    profile, _ = load_profile(profile, validate_current=False)
    with operation_lock(profile):
        profile, config = load_profile(profile, validate_current=False)
        record = current_record(profile)
        value = recovery_snapshot(profile, config, record)
        if expected_preview is None:
            return {'status': 'recovery_preview', 'preview_sha256': value['preview_sha256'],
                'summary': '已确认原后台及相关浏览器、隧道进程退出；可显式归档旧占用，保留原状态且不重做请求。'}
        require(isinstance(expected_preview, str) and DIGEST.fullmatch(expected_preview)
            and expected_preview == value['preview_sha256'], 'web_manager_recovery_changed')
        history = checked_path(profile / 'history', directory=True)
        transaction = history / ('recovery-' + secrets.token_hex(16))
        private_directory(transaction)
        state = state_path(profile, record)
        for index, (name, expected) in enumerate(value['files'].items()):
            raw = recovery_file_bytes(Path(name), state)
            require(digest(raw) == expected, 'web_manager_recovery_changed')
            (transaction / (str(index) + '.original')).write_bytes(raw)
        journal = {**value, 'phase': 'prepared', 'outcome': value.get('outcome', 'uncontrolled_exit_retired'),
            'replayed': False, 'launched': False}
        service.write_json(transaction / 'receipt.json', journal)
        # Reobserve processes and every source immediately before changing the
        # exact marker/pointer. Do not overwrite status.json with a fabricated stop.
        require(recovery_snapshot(profile, config, current_record(profile)) == value,
            'web_manager_recovery_changed')
        if value['marker']:
            marker = Path(value['marker'])
            archived = marker.with_name('retired-' + transaction.name + '-' + marker.name)
            require(not archived.exists(), 'web_manager_recovery_changed')
            os.rename(marker, archived)
            journal.update(phase='marker_archived', archived_marker=str(archived))
            service.write_json(transaction / 'receipt.json', journal)
        pointer = profile / 'current.json'
        require(digest(read_bytes(pointer)) == value['files'][str(pointer)], 'web_manager_recovery_changed')
        os.rename(pointer, transaction / 'current.json')
        journal['phase'] = 'retired'
        service.write_json(transaction / 'receipt.json', journal)
        return {'status': 'recovered', 'summary': '旧实例占用已归档，异常退出记录和全部请求保持；可显式更新配置并启动新后台，尚未启动或重放。'}


def require_complete_preinit_recoveries(profile):
    """Never launch past an interrupted, malformed or linked preinit journal."""
    history = checked_path(profile / 'history', directory=True)
    for index, transaction in enumerate(history.glob('preinit-recovery-*')):
        require(index < 4096, 'web_manager_preinit_recovery_pending')
        transaction = checked_path(transaction, directory=True)
        match = re.fullmatch(r'preinit-recovery-([a-f0-9]{32})-[a-f0-9]{32}', transaction.name)
        require(match is not None, 'web_manager_preinit_recovery_pending')
        receipt = read_json(transaction / 'receipt.json')
        pointer = checked_path(transaction / 'current.json')
        files = receipt.get('files')
        original = read_json(pointer)
        receipt_keys = {'version', 'attempt', 'outcome', 'files', 'sources',
            'python_sha256', 'preview_sha256', 'phase', 'launched', 'replayed',
            'clean_stop_claimed'}
        require(set(receipt) == receipt_keys and receipt.get('version') == 1
            and receipt.get('attempt') == match.group(1)
            and receipt.get('phase') == 'retired'
            and receipt.get('outcome') == 'uncertain_launch_preinit_import_failure_retired'
            and receipt.get('launched') is False and receipt.get('replayed') is False
            and receipt.get('clean_stop_claimed') is False
            and isinstance(files, dict) and len(files) == 4
            and all(isinstance(name, str) and isinstance(value, str)
                and DIGEST.fullmatch(value) for name, value in files.items())
            and isinstance(receipt.get('sources'), dict)
            and len(receipt['sources']) == 2
            and all(isinstance(value, str) and DIGEST.fullmatch(value)
                for value in receipt['sources'].values())
            and isinstance(receipt.get('python_sha256'), str)
            and DIGEST.fullmatch(receipt['python_sha256'])
            and isinstance(receipt.get('preview_sha256'), str)
            and DIGEST.fullmatch(receipt['preview_sha256'])
            and files.get(str(profile / 'current.json')) == digest(read_bytes(pointer))
            and original == {'version': 1, 'attempt': match.group(1)},
            'web_manager_preinit_recovery_pending')
        preview_value = {key: receipt[key] for key in (
            'version', 'attempt', 'outcome', 'files', 'sources', 'python_sha256')}
        require(receipt['preview_sha256'] == digest(json.dumps(
            preview_value, sort_keys=True).encode('utf-8')),
            'web_manager_preinit_recovery_pending')
        for number, expected in enumerate(files.values()):
            require(digest(read_bytes(transaction / (str(number) + '.original'))) == expected,
                'web_manager_preinit_recovery_pending')
        current = profile / 'current.json'
        if current.exists() or current.is_symlink():
            require(read_json(current).get('attempt') != match.group(1),
                'web_manager_preinit_recovery_pending')


def start(profile, *, observation_seconds=START_OBSERVATION_SECONDS):
    profile, _ = load_profile(profile, validate_current=False)
    with operation_lock(profile):
        profile, config = load_profile(profile)
        return _start_locked(profile, config, observation_seconds)[0]


def _start_locked(profile, config, observation_seconds):
    """One explicit launch/reuse, retaining its exact private record for its caller."""
    require_complete_preinit_recoveries(profile)
    record = current_record(profile)
    if record is not None:
        result, live = observe(profile, config, record)
        if live is not None:
            require(load_profile(profile)[1] == config and current_record(profile) == record,
                'web_manager_start_identity_changed')
            record = bind_session(profile, record, live)
            return {**result, 'reused': True}, record
        if result['status'] != 'stopped':
            return {**result, 'reused': True}, record
    # All validation is complete before publishing the conservative boundary.
    require(load_profile(profile)[1] == config, 'web_manager_settings_changed')
    require(fixed_connection_available(config), 'web_manager_fixed_connection_in_use')
    check_python_dependencies(config['runtime'], profile)
    # Dependency probing may take ten seconds. Its earlier snapshots cannot
    # authorize a launch after a source/settings/ownership or tunnel change.
    require(load_profile(profile)[1] == config and current_record(profile) == record,
        'web_manager_start_identity_changed')
    require(fixed_connection_available(config), 'web_manager_fixed_connection_in_use')
    require(load_profile(profile)[1] == config and current_record(profile) == record,
        'web_manager_start_identity_changed')
    record = {'version': 1, 'attempt': secrets.token_hex(16), 'phase': 'may_have_started',
        'runtime': config['runtime']}
    save_record(profile, record)
    service.write_json(profile / 'current.json', {'version': 1, 'attempt': record['attempt']})
    state = state_path(profile, record)
    argv = [config['runtime']['python'], '-E', '-s', '-u', config['runtime']['backend'],
        'serve', '--settings', config['settings']['path'], '--state', str(state), '--prepare-hidden']
    try:
        child = spawn_child(argv, profile)
        record['pid'] = child.pid
        save_record(profile, record)
        identity = process_identity(child.pid)
        require(identity is not None and Path(identity['executable']) == Path(config['runtime']['python']),
            'web_manager_launch_ownership_unknown')
        record.update(process=identity, phase='starting')
        save_record(profile, record)
        deadline = time.monotonic() + observation_seconds
        while True:
            if child.poll() is not None:
                require(False, 'web_manager_child_exited_no_retry')
            if (state / 'session.json').is_file() and (state / 'status.json').is_file():
                require(load_profile(profile)[1] == config, 'web_manager_settings_changed')
                result, live = observe(profile, config, record)
                require(live is not None, 'web_manager_start_not_live')
                require(load_profile(profile)[1] == config and current_record(profile) == record,
                    'web_manager_start_identity_changed')
                record = bind_session(profile, record, live)
                return {**result, 'reused': False}, record
            if time.monotonic() >= deadline:
                return {'status': 'starting', 'reused': False,
                    'summary': '后台已启动，现有连接仍在准备；可查看状态，系统不会再次启动或重做请求。'}, record
            time.sleep(.05)
    except Exception:
        # A change observed during health I/O belongs to its later writer.
        # Retain that record instead of replacing it with our stale snapshot.
        try:
            unchanged = current_record(profile) == record
        except Exception:
            unchanged = False
        if unchanged:
            save_record(profile, {**record, 'phase': 'uncertain'})
        raise


def start_ready(profile, *, observation_seconds=START_READY_OBSERVATION_SECONDS):
    """Finish this explicit start's late-ready binding without a second launch.

    The manager lock and private record span launch and bounded observations.
    Status remains read-only; this path never adopts a replacement generation.
    """
    require(type(observation_seconds) in (int, float)
        and 0 <= observation_seconds <= START_READY_OBSERVATION_SECONDS,
        'web_manager_start_observation_invalid')
    profile, _ = load_profile(profile, validate_current=False)
    with operation_lock(profile):
        profile, config = load_profile(profile)
        result, record = _start_locked(profile, config, START_OBSERVATION_SECONDS)
        deadline = time.monotonic() + observation_seconds
        while result['status'] in ('starting', 'preparing') and time.monotonic() < deadline:
            time.sleep(.1)
            require(load_profile(profile)[1] == config and current_record(profile) == record,
                'web_manager_start_identity_changed')
            observed, live = observe(profile, config, record)
            require(load_profile(profile)[1] == config and current_record(profile) == record,
                'web_manager_start_identity_changed')
            result = {**observed, 'reused': result['reused']}
            if live is not None and result['status'] == 'ready' and not result.get('active', False):
                bind_session(profile, record, live)
                return {**result, 'session_bound': True}
        return result


def status(profile):
    profile, config = load_profile(profile, validate_current=False)
    record = current_record(profile)
    result, live = observe(profile, config, record)
    if live is not None:
        session, session_hash, _, worker = live
        # A late-ready child can be observed before explicit start reuse saves
        # its receipt. Report that distinction without mutating ownership.
        result = {**result, 'session_bound': record.get('phase') == 'running'
            and record.get('instance') == session['instance']
            and record.get('session_sha256') == session_hash and record.get('worker') == worker}
    try:
        load_profile(profile)
    except Exception:
        result = {**result, 'configuration_current': False,
            'summary': result['summary'] + '程序或配置已变化；可停止当前后台，正常停止后用 configure 更新登记。'}
    else:
        result = {**result, 'configuration_current': True}
        if result['status'] in ('configured', 'stopped') and not fixed_connection_available(config):
            result = {**result, 'start_available': False, 'reason': 'web_manager_fixed_connection_in_use',
                'summary': '配置已保存，但固定连接仍有占用记录。请先核对原实例；无需重新创建插件、连接或密钥。'}
    return result


def control(profile, action, *, replace_closed_browser=False, drain_seconds=0):
    require(action in ('assist', 'inspect', 'stop'), 'web_manager_action_invalid')
    require(type(replace_closed_browser) is bool and (not replace_closed_browser or action == 'assist'),
        'web_manager_replacement_invalid')
    require(type(drain_seconds) is int and 0 <= drain_seconds <= 30
        and (action == 'stop' or drain_seconds == 0), 'web_service_drain_invalid')
    profile, _ = load_profile(profile, validate_current=False)
    with operation_lock(profile):
        profile, config = load_profile(profile, validate_current=action != 'stop')
        record = current_record(profile)
        require(record is not None, 'web_manager_service_not_started')
        result, live = observe(profile, config, record)
        if action == 'stop' and result['status'] == 'stopped':
            return result
        require(live is not None, 'web_manager_live_service_required')
        record = bind_session(profile, record, live)
        session, _, health, _ = live
        state = state_path(profile, record)
        if action in ('assist', 'inspect'):
            require(health['active'] is False, 'web_assistance_requires_idle_session')
            command = {'instance': session['instance'], 'id': secrets.token_hex(16),
                **({'inspect_completed': True} if action == 'inspect' else {}),
                **({'replace_closed_browser': True} if replace_closed_browser else {})}
            service.write_command(state / 'assist.json', command)
            if action == 'inspect':
                return {'status': 'inspection_requested',
                    'summary': '已请求只读现场预览；展示当前回复与已显示的页面提示，关闭后原页面保留。'}
            return {'status': 'assistance_requested',
                'summary': '已请求打开当前后台的辅助窗口；完成登录或验证后关闭窗口，已有配置继续沿用。'}
        path = state / 'stop.json'
        if path.exists():
            require(service.stop_request(path, session['instance']) == drain_seconds,
                'web_service_stop_already_requested')
        else:
            service.write_command(path, {'instance': session['instance'], 'drain_seconds': drain_seconds})
        return {'status': 'stop_requested', 'summary': '已请求停止当前后台；请查看状态确认结束，固定配置继续保留。'}


def error_result(error):
    from operator_core.responses_capabilities import RouterError
    code = str(error) if isinstance(error, RouterError) and str(error) in ERROR_CODES \
        else 'web_manager_unavailable_no_retry'
    if code == 'web_manager_operation_in_progress':
        summary = '此入口正在处理另一项操作；可查看状态，系统不会重复启动。'
    elif code in ('web_manager_runtime_changed', 'web_manager_settings_changed'):
        summary = '已保存的程序或配置发生变化，请先核对变更；原连接和凭据未修改。'
    elif code == 'web_manager_profile_already_exists':
        summary = '已有保存的入口，请直接查看状态或启动；未覆盖原配置。'
    elif code == 'web_manager_fixed_connection_in_use':
        summary = '固定连接仍有占用记录，本次未启动后台。请先核对原实例；无需重新创建插件、连接或密钥。'
    elif code == 'web_manager_python_dependencies_unavailable':
        summary = '保存的 Python 未通过服务依赖导入检查；本次未启动后台，也未写入启动记录。'
    else:
        summary = '当前后台状态尚未核实，请检查现有实例；系统未自动重启、清除连接记录或重做请求。'
    return {'status': 'unavailable', 'code': code, 'summary': summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('configure', 'start', 'status', 'assist', 'inspect', 'stop', 'recover'))
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--replace-closed-browser', action='store_true')
    parser.add_argument('--drain-seconds', type=int, default=0)
    parser.add_argument('--expected-preview')
    args = parser.parse_args()
    try:
        require((args.action == 'configure') == (args.settings is not None), 'web_manager_settings_argument_invalid')
        require(not args.replace_closed_browser or args.action == 'assist', 'web_manager_replacement_invalid')
        require(args.drain_seconds == 0 or args.action == 'stop', 'web_service_drain_invalid')
        require(args.expected_preview is None or args.action == 'recover', 'web_manager_recovery_changed')
        if args.action == 'configure':
            result = configure(args.profile, args.settings)
        elif args.action == 'start':
            result = start_ready(args.profile)
        elif args.action == 'status':
            result = status(args.profile)
        elif args.action == 'recover':
            result = recover(args.profile, expected_preview=args.expected_preview)
        else:
            result = control(args.profile, args.action,
                replace_closed_browser=args.replace_closed_browser, drain_seconds=args.drain_seconds)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps(error_result(error), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
