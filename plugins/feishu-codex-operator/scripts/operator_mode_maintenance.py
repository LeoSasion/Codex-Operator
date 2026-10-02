"""Explicit maintenance for retained, identity-bound isolated entry records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import operator_mode_entry as mode


FOCUS_REVIEW = 'operator_mode_stopped_focus_review_v1'
STARTUP_REVIEW = 'operator_mode_early_startup_failure_review_v1'
ROUTER_ABSENCE = 'operator_mode_router_absence_review_v1'


def isolated_processes_absent(root):
    # Inspect all package generations: an official update may change its path.
    program = r'''$ErrorActionPreference='Stop'
$ReviewRoot=$env:CODEX_OPERATOR_REVIEW_ROOT
if(-not $ReviewRoot){exit 2}
$UserData=Join-Path $ReviewRoot 'user-data'
$items=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe' OR Name='operator-mode-host.exe' OR Name='operator-mode-picker.exe'")
foreach($item in $items){
  if(-not $item.ExecutablePath -or -not $item.CommandLine){exit 2}
  if($item.ExecutablePath -ieq (Join-Path $ReviewRoot 'operator-mode-host.exe') -or
     $item.ExecutablePath -ieq (Join-Path $ReviewRoot 'operator-mode-picker.exe') -or
     $item.CommandLine.IndexOf($UserData,[StringComparison]::OrdinalIgnoreCase) -ge 0){exit 1}
}
'''
    shell = mode.shutil.which('pwsh.exe')
    mode.require(shell is not None, 'powershell_unavailable')
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', program],
                            capture_output=True, timeout=20,
                            env={**mode.os.environ, 'CODEX_OPERATOR_REVIEW_ROOT': str(root)},
                            creationflags=subprocess.CREATE_NO_WINDOW if mode.os.name == 'nt' else 0)
    mode.require(result.returncode == 0, 'isolated_process_still_running_or_unknown')


def router_absence_snapshot(root, attempt, descriptor):
    """Retain an unclean generation; never manufacture a stopped record."""
    mode.checked_path(attempt, directory=True)
    mode.require(attempt.parent == root / 'router-launches' and re.fullmatch('[a-f0-9]{32}', attempt.name),
                 'router_absence_scope_invalid')
    allowed = {'intent.json', 'running.json', 'absence-original-entry.json', 'absence-reviewed.json'}
    mode.require({p.name for p in attempt.iterdir()} <= allowed
                 and all((attempt / name).is_file() for name in ('intent.json', 'running.json')),
                 'router_absence_not_reviewable')
    intent = mode.decode(mode.read(attempt / 'intent.json'))
    running = mode.decode(mode.read(attempt / 'running.json'))
    process = running.get('process')
    mode.require(intent.get('native_enabled') is False
                 and descriptor.get('root') == str(root) and descriptor.get('native_enabled') is False
                 and type(descriptor.get('port')) is int and 1 <= descriptor['port'] <= 65535
                 and isinstance(process, dict) and set(process) == {'pid', 'birth', 'executable'}
                 and type(process['pid']) is int and process['pid'] > 0
                 and isinstance(process['birth'], str) and re.fullmatch('[0-9]+', process['birth'])
                 and isinstance(process['executable'], str)
                 and re.fullmatch('[a-f0-9]{64}', running.get('service', ''))
                 and not mode.process_matches(process), 'router_absence_process_running_or_unknown')
    return {'contract': ROUTER_ABSENCE, 'root': str(root), 'attempt': attempt.name,
            'files': {name: mode.file_hash(attempt / name) for name in ('intent.json', 'running.json')},
            'entry_sha256': mode.digest(mode.json_bytes(descriptor)), 'port': descriptor['port'],
            'process': process, 'normal_stop_claimed': False, 'server_request_free_claimed': False,
            'requests_replayed': 0}


def reviewed_router_absence(root, attempt):
    record = mode.decode(mode.read(attempt / 'absence-reviewed.json'))
    original = mode.decode(mode.read(attempt / 'absence-original-entry.json'))
    snapshot = router_absence_snapshot(root, attempt, original)
    mode.require(record.get('snapshot') == snapshot
                 and record.get('preview_sha256') == mode.digest(mode.json_bytes(snapshot))
                 and record.get('port_exclusively_reserved') is True
                 and record.get('stopped_desktops_observed') is True, 'router_absence_review_changed')
    return True


def review_router_absence(root, expected=None):
    import operator_model_router as router
    with mode.lock(root):
        descriptor = mode.load(root, check_source=False)
        current, old = mode.source_bindings(), descriptor['source_bindings']
        allowed = {'operator_mode_entry.py', 'operator_mode_entry.ps1', 'operator_mode_host.cs',
                   'operator_mode_picker.cs', 'operator_mode_maintenance.py', 'operator_mode_pair_refresh.ps1'}
        mode.require(all(old.get(key) == current.get(key) for key in old.keys() | current.keys()
                         if key not in allowed), 'maintenance_router_source_changed')
        stopped_desktops(root)
        activation_hosts_absent(root)
        isolated_processes_absent(root)
        attempt = mode.router_attempt(root)
        mode.require(attempt is not None and not any((attempt / name).exists() for name in
                     ('absence-reviewed.json', 'absence-original-entry.json')), 'router_absence_review_not_fresh')
        snapshot = router_absence_snapshot(root, attempt, descriptor)
        with router.reserve_inactive_port(descriptor['port']):
            sha = mode.digest(mode.json_bytes(snapshot))
            if expected is None:
                return {'phase': 'router_absence_review_ready', 'preview_sha256': sha,
                        'normal_stop_claimed': False, 'model_requests': 0, 'desktop_launch': False}
            mode.require(re.fullmatch('[a-f0-9]{64}', expected or '') and expected == sha,
                         'router_absence_preview_changed')
            # Recheck while the port remains exclusively held, before any receipt write.
            stopped_desktops(root)
            activation_hosts_absent(root)
            isolated_processes_absent(root)
            mode.require(mode.load(root, check_source=False) == descriptor and mode.source_bindings() == current
                         and router_absence_snapshot(root, attempt, descriptor) == snapshot,
                         'router_absence_preview_changed')
            mode.write_new(attempt / 'absence-original-entry.json', descriptor)
            mode.write_new(attempt / 'absence-reviewed.json', {'snapshot': snapshot, 'preview_sha256': sha,
                'port_exclusively_reserved': True, 'stopped_desktops_observed': True, 'reviewed_utc': mode.utc()})
        return {'phase': 'router_absence_reviewed', 'normal_stop_claimed': False,
                'old_generation_retained': True, 'model_requests': 0, 'desktop_launch': False}


def startup_processes_absent(root, descriptor):
    """Read process metadata only; a failed launch is never restarted or killed."""
    program = r'''$ErrorActionPreference='Stop'
$ReviewRoot=$env:CODEX_OPERATOR_REVIEW_ROOT
$Official=$env:CODEX_OPERATOR_REVIEW_OFFICIAL
if(-not $ReviewRoot -or -not $Official){exit 2}
$HostPath=Join-Path $ReviewRoot 'operator-mode-host.exe'
$PickerPath=Join-Path $ReviewRoot 'operator-mode-picker.exe'
$UserData=Join-Path $ReviewRoot 'user-data'
$items=@(Get-CimInstance Win32_Process -Filter "Name='operator-mode-host.exe' OR Name='operator-mode-picker.exe' OR Name='ChatGPT.exe'")
foreach($item in $items){
  if(-not $item.ExecutablePath){exit 2}
  if($item.ExecutablePath -ieq $HostPath -or $item.ExecutablePath -ieq $PickerPath){exit 1}
  if($item.ExecutablePath -ieq $Official){
    if(-not $item.CommandLine){exit 2}
    if($item.CommandLine.IndexOf($UserData,[StringComparison]::OrdinalIgnoreCase) -ge 0){exit 1}
  }
  if(-not $item.ExecutablePath -and $item.CommandLine -and
      $item.CommandLine.IndexOf($ReviewRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0){exit 2}
}
'''
    shell = mode.shutil.which('pwsh.exe')
    mode.require(shell is not None, 'powershell_unavailable')
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', program],
                            capture_output=True, timeout=20,
                            env={**mode.os.environ, 'CODEX_OPERATOR_REVIEW_ROOT': str(root),
                                 'CODEX_OPERATOR_REVIEW_OFFICIAL': descriptor['package']['executable']},
                            creationflags=subprocess.CREATE_NO_WINDOW if mode.os.name == 'nt' else 0)
    mode.require(result.returncode == 0, 'startup_process_still_running_or_unknown')


def startup_failure_snapshot(root, attempt_id):
    mode.require(re.fullmatch('[a-f0-9]{32}', attempt_id or ''), 'launch_record_invalid')
    directory = mode.checked_path(root / 'launches' / attempt_id, directory=True)
    names = {'intent.json', 'dispatched.json', 'host-plan.json', 'host-starting.json',
             'host-failed.json', 'controller-failed.json'}
    mode.require({p.name for p in directory.iterdir()} - {'startup-reviewed.json'} == names,
                 'startup_failure_not_reviewable')
    files = {name: mode.file_hash(directory / name, 65536) for name in sorted(names)}
    values = {name: mode.decode(mode.read(directory / name)) for name in sorted(names)}
    failed = values['host-failed.json']
    plan = values['host-plan.json']
    starting = values['host-starting.json']
    controller = values['controller-failed.json']
    mode.require(failed.get('reason') == 'mode_host_failed'
                 and type(failed.get('hresult')) is int and failed['hresult'] == -2147467261
                 and failed.get('desktop_launched') is True
                 and failed.get('automatically_retried') is False
                 and failed.get('desktop_terminated') is False
                 and failed.get('failure_stage') in {None, 'child_identity', 'desktop_record'}
                 and controller.get('reason') == 'mode_host_failed'
                 and controller.get('automatically_retried') is False,
                 'startup_failure_not_reviewable')
    mode.require(values['intent.json'].get('contract') == mode.CONTRACT
                 and values['dispatched.json'].get('accepted') is True
                 and plan.get('contract') == mode.HOST_CONTRACT and plan.get('schema_version') == 1
                 and plan.get('root') == str(root) and plan.get('home') == str(root / 'home')
                 and plan.get('user_data') == str(root / 'user-data')
                 and starting.get('contract') == mode.HOST_CONTRACT
                 and starting.get('plan_sha256') == files['host-plan.json']
                 and starting.get('package_identity') == plan.get('package_full_name')
                 and re.fullmatch('[a-f0-9]{64}', starting.get('native_config_sha256', '')),
                 'startup_failure_identity_invalid')
    return {'contract': STARTUP_REVIEW, 'root': str(root), 'attempt': attempt_id, 'files': files,
            'failed_result_preserved': True, 'normal_exit_claimed': False,
            'replayed': False, 'new_desktop_instances': 0}


def reviewed_startup_failure(root, directory):
    receipt = directory / 'startup-reviewed.json'
    if not receipt.is_file():
        return False
    mode.file_hash(receipt, 65536)
    value = mode.decode(mode.read(receipt))
    snapshot = startup_failure_snapshot(root, directory.name)
    baseline = value.get('review_baseline')
    mode.require(isinstance(baseline, dict)
                 and set(baseline) == {'extension_config_sha256', 'native_config_sha256'}
                 and all(isinstance(sha, str) and re.fullmatch('[a-f0-9]{64}', sha)
                         for sha in baseline.values()), 'startup_review_changed')
    mode.require(value.get('snapshot') == snapshot
                 and value.get('preview_sha256') == mode.digest(mode.json_bytes(
                     {'snapshot': snapshot, 'review_baseline': baseline}))
                 and value.get('startup_processes_absent') is True, 'startup_review_changed')
    return True


def review_startup(root, attempt_id, expected=None):
    with mode.lock(root):
        descriptor = mode.load(root, check_source=False)
        snapshot = startup_failure_snapshot(root, attempt_id)
        directory = root / 'launches' / attempt_id
        plan = mode.decode(mode.read(directory / 'host-plan.json'))
        starting = mode.decode(mode.read(directory / 'host-starting.json'))
        current_plan = mode.host_plan(root, descriptor)
        # Desktop may persist its model/effort choice. load() still validates the
        # owned provider and route; review binds those current bytes and restores
        # neither the launch configuration nor any native settings.
        mode.require({key: item for key, item in plan.items() if key != 'config_sha256'}
                     == {key: item for key, item in current_plan.items() if key != 'config_sha256'}
                     and mode.file_hash(root / 'host-plan.json') == snapshot['files']['host-plan.json']
                     and mode.file_hash(root / 'operator-mode-host.exe') == plan['host_sha256']
                     and mode.file_hash(mode.Path(descriptor['native_home']) / 'config.toml')
                     == starting['native_config_sha256'], 'startup_review_baseline_changed')
        startup_processes_absent(root, descriptor)
        mode.require(startup_failure_snapshot(root, attempt_id) == snapshot
                     and mode.load(root, check_source=False) == descriptor
                     and mode.file_hash(root / 'home' / 'config.toml') == current_plan['config_sha256']
                     and mode.file_hash(mode.Path(descriptor['native_home']) / 'config.toml')
                     == starting['native_config_sha256']
                     and mode.file_hash(root / 'operator-mode-host.exe') == plan['host_sha256']
                     and mode.file_hash(root / 'host-plan.json') == snapshot['files']['host-plan.json'],
                     'startup_review_baseline_changed')
        baseline = {'extension_config_sha256': current_plan['config_sha256'],
                    'native_config_sha256': starting['native_config_sha256']}
        sha = mode.digest(mode.json_bytes({'snapshot': snapshot, 'review_baseline': baseline}))
        if expected is None:
            return {'phase': 'startup_review_ready', 'preview_sha256': sha,
                    'failed_result_preserved': True, 'normal_exit_claimed': False, 'model_requests': 0}
        mode.require(expected == sha, 'startup_review_preview_changed')
        receipt = directory / 'startup-reviewed.json'
        mode.require(not receipt.exists(), 'startup_review_already_retained')
        mode.write_new(receipt, {'snapshot': snapshot, 'preview_sha256': sha,
                                'review_baseline': baseline,
                                'startup_processes_absent': True, 'reviewed_utc': mode.utc()})
        return {'phase': 'startup_failure_reviewed', 'failed_result_preserved': True,
                'normal_exit_claimed': False, 'model_requests': 0, 'desktop_launch': False}


def activation_hosts_absent(root):
    # Process command lines are checked in memory and never returned or logged.
    program = r'''$ErrorActionPreference='Stop'
$Root=$env:CODEX_OPERATOR_REVIEW_ROOT
if(-not $Root){exit 2}
$items=@(Get-CimInstance Win32_Process -Filter "Name='operator-mode-host.exe'")
$found=@($items|Where-Object {$_.CommandLine -and $_.CommandLine.Contains($Root) -and $_.CommandLine.Contains('--activate')})
if($found.Count){exit 1}
'''
    shell = mode.shutil.which('pwsh.exe')
    mode.require(shell is not None, 'powershell_unavailable')
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', program],
                            capture_output=True, timeout=20,
                            env={**mode.os.environ, 'CODEX_OPERATOR_REVIEW_ROOT': str(root)},
                            creationflags=subprocess.CREATE_NO_WINDOW if mode.os.name == 'nt' else 0)
    mode.require(result.returncode == 0, 'activation_host_still_running_or_unknown')


def focus_failure_snapshot(root, activation_id):
    mode.require(re.fullmatch('[a-f0-9]{32}', activation_id or ''), 'activation_invalid')
    directory = mode.checked_path(root / 'activations' / activation_id, directory=True)
    names = {'intent.json', 'host-starting.json', 'failed.json', 'controller-failed.json'}
    mode.require({p.name for p in directory.iterdir()} - {'focus-reviewed.json'} == names,
                 'focus_failure_not_reviewable')
    files = {name: mode.file_hash(directory / name, 65536) for name in sorted(names)}
    values = {name: mode.decode(mode.read(directory / name)) for name in sorted(names)}
    intent = values['intent.json']
    mode.require(values['failed.json'].get('reason') == 'mode_foreground_not_granted'
                 and values['failed.json'].get('automatically_retried') is False
                 and values['controller-failed.json'].get('reason') == 'mode_foreground_not_granted',
                 'focus_failure_not_reviewable')
    mode.require(re.fullmatch('[a-f0-9]{32}', intent.get('attempt', ''))
                 and re.fullmatch('[a-f0-9]{64}', intent.get('plan_sha256', '')),
                 'focus_failure_identity_invalid')
    launch = mode.checked_path(root / 'launches' / intent['attempt'], directory=True)
    started = mode.decode(mode.read(launch / 'desktop-started.json'))
    exited = mode.decode(mode.read(launch / 'desktop-exited.json'))
    bound = mode.decode(mode.read(launch / 'windows-bound.json'))
    process = started.get('process')
    mode.require(isinstance(process, dict) and type(process.get('pid')) is int
                 and started.get('pid') == process['pid'] == intent.get('original_pid')
                 == values['host-starting.json'].get('original_pid') == exited.get('pid') == bound.get('pid')
                 and exited.get('window_was_bound') is True and exited.get('exit_code') == 0
                 and exited.get('native_config_unchanged') is True
                 and bound.get('native_config_unchanged') is True
                 and not mode.process_matches(process)
                 and not any((launch / name).exists() for name in ('host-failed.json', 'controller-failed.json'))
                 and (launch / 'dispatched.json').is_file()
                 and mode.file_hash(launch / 'host-plan.json') == intent['plan_sha256'],
                 'focus_failure_requires_normal_exit')
    for name in ('desktop-started.json', 'desktop-exited.json', 'windows-bound.json',
                 'dispatched.json', 'host-plan.json'):
        files['../../launches/' + launch.name + '/' + name] = mode.file_hash(launch / name)
    return {'contract': FOCUS_REVIEW, 'root': str(root), 'activation': activation_id,
            'attempt': launch.name, 'original_process': process, 'files': files,
            'failed_result_preserved': True, 'replayed': False, 'new_desktop_instances': 0}


def reviewed_focus_failure(root, directory):
    receipt = directory / 'focus-reviewed.json'
    if not receipt.is_file():
        return False
    mode.file_hash(receipt, 65536)
    value = mode.decode(mode.read(receipt))
    snapshot = focus_failure_snapshot(root, directory.name)
    mode.require(value.get('snapshot') == snapshot
                 and value.get('preview_sha256') == mode.digest(mode.json_bytes(snapshot))
                 and value.get('activation_hosts_absent') is True, 'focus_review_changed')
    return True


def stopped_desktops(root):
    for activation in (root / 'activations').iterdir():
        mode.checked_path(activation, directory=True)
        mode.require(re.fullmatch('[a-f0-9]{32}', activation.name), 'activation_invalid')
        if any((activation / name).exists() for name in ('failed.json', 'controller-failed.json')):
            mode.require(reviewed_focus_failure(root, activation), 'previous_window_activation_uncertain')
        else:
            mode.require((activation / 'completed.json').is_file(), 'previous_window_activation_uncertain')
    for launch in (root / 'launches').iterdir():
        mode.checked_path(launch, directory=True)
        if (launch / 'startup-reviewed.json').exists():
            mode.require(reviewed_startup_failure(root, launch), 'previous_launch_running_or_uncertain')
            continue
        mode.require(re.fullmatch('[a-f0-9]{32}', launch.name)
                     and not any((launch / name).exists() for name in ('host-failed.json', 'controller-failed.json')),
                     'previous_launch_running_or_uncertain')
        started = mode.decode(mode.read(launch / 'desktop-started.json'))
        exited = mode.decode(mode.read(launch / 'desktop-exited.json'))
        mode.require(exited.get('pid') == started.get('pid') and exited.get('window_was_bound') is True
                     and not mode.process_matches(started.get('process')), 'close_extension_before_maintenance')


def review_focus(root, activation_id, expected=None):
    with mode.lock(root):
        mode.load(root, check_source=False)
        snapshot = focus_failure_snapshot(root, activation_id)
        activation_hosts_absent(root)
        sha = mode.digest(mode.json_bytes(snapshot))
        if expected is None:
            return {'phase': 'focus_review_ready', 'preview_sha256': sha,
                    'failed_result_preserved': True, 'model_requests': 0}
        mode.require(expected == sha, 'focus_review_preview_changed')
        receipt = root / 'activations' / activation_id / 'focus-reviewed.json'
        mode.require(not receipt.exists(), 'focus_review_already_retained')
        mode.write_new(receipt, {'snapshot': snapshot, 'preview_sha256': sha,
                                'activation_hosts_absent': True, 'reviewed_utc': mode.utc()})
        return {'phase': 'focus_failure_reviewed', 'failed_result_preserved': True,
                'model_requests': 0, 'desktop_launch': False}


def maintenance_stop(root):
    """Stop the checked idle service after a separately reviewed focus failure."""
    import operator_model_router as router
    with mode.lock(root):
        descriptor = mode.load(root, check_source=False)
        current = mode.source_bindings()
        allowed = {'operator_mode_entry.py', 'operator_mode_entry.ps1', 'operator_mode_host.cs',
                   'operator_mode_picker.cs', 'operator_mode_maintenance.py', 'operator_mode_pair_refresh.ps1'}
        old = descriptor['source_bindings']
        mode.require(all(old.get(key) == current.get(key) for key in old.keys() | current.keys()
                         if key not in allowed), 'maintenance_router_source_changed')
        stopped_desktops(root)
        activation_hosts_absent(root)
        attempt = mode.router_attempt(root)
        mode.require(attempt is not None and not (attempt / 'stop-intent.json').exists()
                     and not (attempt / 'stopped.json').exists(), 'maintenance_stop_not_fresh')
        running = mode.decode(mode.read(attempt / 'running.json'))
        mode.require(mode.process_matches(running.get('process')), 'router_process_uncertain')
        before = mode.start_router(root, descriptor, check_web_service=False)  # No Web probe or launch during stop.
        diagnostics = before.get('diagnostics', {})
        mode.require(diagnostics.get('timing', {}).get('active') == 0, 'router_not_request_free')
        mode.write_new(attempt / 'stop-intent.json', {'created_utc': mode.utc(),
            'process': running['process'], 'maintenance': 'reviewed_stopped_focus_failure'})
        stopped = router.control(root / 'router', descriptor['port'], stop=True)
        mode.require(stopped.get('service') == before['service'] and stopped.get('pid') == before['pid']
                     and stopped.get('status') == 'stopping', 'router_stop_unconfirmed')
        deadline = time.monotonic() + 10
        while mode.process_matches(running['process']) and time.monotonic() < deadline:
            time.sleep(.1)
        mode.require(not mode.process_matches(running['process']), 'router_process_not_exited')
        with router.reserve_inactive_port(descriptor['port']):
            mode.write_new(attempt / 'stopped.json', {'process': running['process'],
                'stopped_utc': mode.utc(), 'server_confirmed_request_free': True})
        return mode.report(root, descriptor, phase='service_stopped', desktop_launch=False)


PAIR_REFRESH = 'operator_mode_bound_pair_refresh_v1'
PAIR_FILES = ('entry.json', 'entry.ps1', 'operator-mode-host.exe', 'operator-mode-native.exe', 'operator-mode-picker.exe')
PAIR_RETIREMENT = 'operator_mode_unwritten_pair_retirement_v1'
PAIR_ROLLBACK_REVIEW = 'operator_mode_pair_rollback_review_v1'


def pair_retained_tree(directory, excluded=()):
    mode.checked_path(directory, directory=True)
    paths = sorted(directory.rglob('*'))
    mode.require(len(paths) <= 128, 'pair_review_file_bound')
    for path in paths:
        mode.checked_path(path, directory=path.is_dir())
    return {path.relative_to(directory).as_posix(): mode.file_hash(path)
            for path in paths if path.is_file() and path.name not in excluded}


def pair_rollback_snapshot(root, stage, *, current=True):
    """Review a completed rollback without calling it an unwritten publication."""
    from operator_mode_backends import BACKEND_FILES
    mode.require(stage.parent == root / 'pair-refreshes' and re.fullmatch('[a-f0-9]{32}', stage.name),
                 'pair_rollback_scope_invalid')
    descriptor = mode.decode(mode.read(stage / 'originals/entry.json'))
    project = Path(descriptor['project'])
    mode.validate_scope(project, root, Path(descriptor['native_home']))
    pair = project / '.codex/operator-desktop-pair'
    transaction, generation = pair / 'upgrades' / stage.name, pair / 'generations' / stage.name
    plan = mode.decode(mode.read(stage / 'intent.json'))
    manifest = mode.decode(mode.read(stage / 'prepared.json'))
    failure = mode.decode(mode.read(stage / 'failed.json'))
    apply = mode.decode(mode.read(stage / 'apply-intent.json'))
    mode.require(plan.get('contract') == PAIR_REFRESH and plan.get('root') == str(root)
                 and manifest.get('contract') == PAIR_REFRESH and manifest.get('root') == str(root)
                 and manifest.get('generation') == stage.name
                 and manifest.get('protected_files') == plan.get('protected_files')
                 and failure.get('automatically_retried') is False
                 and re.fullmatch('[a-z][a-z0-9_]{1,127}', failure.get('reason', ''))
                 and re.fullmatch('[a-f0-9]{64}', apply.get('preview_sha256', '')),
                 'pair_rollback_record_invalid')
    files = (*PAIR_FILES, *(BACKEND_FILES if 'backend_update' in plan else ()))
    mode.require(set(manifest['files']) == set(files)
                 and set(plan['managed_files']) == set(files), 'pair_rollback_record_invalid')
    retained = pair_retained_tree(stage, ('retired.json',))
    names = {'intent.json', 'prepared.json', 'failed.json', 'apply-intent.json'}
    names |= {directory + '/' + name for directory in ('originals', 'staged') for name in files}
    mode.require(set(retained) == names, 'pair_rollback_record_invalid')
    for name in files:
        row = manifest['files'][name]
        mode.require(set(row) == {'before', 'after'}
                     and row['before'] == plan['managed_files'][name] == retained['originals/' + name]
                     and row['after'] == retained['staged/' + name], 'pair_rollback_backup_changed')
    pending = mode.decode(mode.read(transaction / 'pending.json'))
    rows = pending.get('changes')
    mode.require(set(pending) == {'schema_version', 'phase', 'changes', 'moves'}
                 and pending['schema_version'] == 1 and pending['phase'] == 'may_have_written'
                 and pending['moves'] == [] and isinstance(rows, list) and 1 <= len(rows) <= 16
                 and all(isinstance(row, dict) and set(row) == {'path', 'before', 'after'} for row in rows),
                 'pair_rollback_transaction_invalid')
    by_path = {row['path']: row for row in rows}
    mode.require(len(by_path) == len(rows), 'pair_rollback_transaction_invalid')
    receipt_path = pair / 'ownership.json'
    mode.require(str(receipt_path) in by_path, 'pair_rollback_transaction_invalid')
    receipt_index = next(i for i, row in enumerate(rows) if row['path'] == str(receipt_path))
    old = mode.decode(mode.read(transaction / f'{receipt_index}.before'))
    mode.require(old.get('phase') == 'installed' and old.get('scope') == 'legacy_entry_only'
                 and old.get('project') == str(project) and old.get('home') == descriptor['native_home']
                 and old.get('runtime_ownership') == 'unresolved'
                 and re.fullmatch('[a-f0-9]{32}', old.get('generation', ''))
                 and isinstance(old.get('steps'), list) and bool(old['steps'])
                 and old['steps'][-1]['workflow'].get('path') == str(root)
                 and old['steps'][-1]['workflow'].get('entry_plan_sha256') == retained['originals/entry.json'],
                 'pair_rollback_owner_invalid')
    build = old.get('build')
    bundle = project / '.codex/operator-desktop-entry'
    build_names = {'Codex拓展入口.exe', 'operator_desktop_entry.ps1', 'desktop-entry.json',
                   'launcher-manifest.json', 'Codex拓展入口.ico'}
    mode.require(isinstance(build, dict) and set(build) == build_names,
                 'pair_rollback_owner_invalid')
    expected_paths = {str(root / name) for name in files}
    expected_paths |= {str(bundle / name) for name in build_names - {'Codex拓展入口.ico'}}
    expected_paths.add(str(receipt_path))
    mode.require(set(by_path) == expected_paths, 'pair_rollback_transaction_scope_invalid')
    saved_transaction = pair_retained_tree(transaction, ('rollback-reviewed.json',))
    expected_saved = {'pending.json'} | {f'{i}.{side}' for i in range(len(rows)) for side in ('before', 'after')}
    mode.require(set(saved_transaction) == expected_saved, 'pair_rollback_transaction_invalid')
    baseline = {}
    for i, row in enumerate(rows):
        path = Path(row['path'])
        for side in ('before', 'after'):
            mode.require(re.fullmatch('[a-f0-9]{64}', row[side] or '')
                         and saved_transaction[f'{i}.{side}'] == row[side], 'pair_rollback_backup_changed')
        if path.parent == root or path in {root / name for name in files}:
            name = path.relative_to(root).as_posix()
            mode.require(row['before'] == manifest['files'][name]['before']
                         and row['after'] == manifest['files'][name]['after'], 'pair_rollback_backup_changed')
        elif path.parent == bundle:
            mode.require(row['before'] == build[path.name]
                         and (path.name == 'desktop-entry.json' or row['before'] == row['after']),
                         'pair_rollback_backup_changed')
        baseline[str(path)] = row['before']
    config_index = next(i for i, row in enumerate(rows) if row['path'] == str(bundle / 'desktop-entry.json'))
    before_config = mode.decode(mode.read(transaction / f'{config_index}.before'))
    after_config = mode.decode(mode.read(transaction / f'{config_index}.after'))
    expected_config = {**before_config, 'mode_entry_sha256': retained['staged/entry.json']}
    mode.require(before_config.get('mode_entry_sha256') == retained['originals/entry.json']
                 and after_config == expected_config, 'pair_rollback_backup_changed')
    new = mode.decode(mode.read(transaction / f'{receipt_index}.after'))
    new_build = {**build, 'desktop-entry.json': by_path[str(bundle / 'desktop-entry.json')]['after']}
    workflow = {'contract': mode.CONTRACT, 'path': str(root),
                'entry_plan_sha256': retained['staged/entry.json'],
                'entry_script_sha256': before_config['entry_script_sha256']}
    expected_new = {**old, 'generation': stage.name, 'transaction': stage.name, 'build': new_build,
                    'steps': [*old['steps'], {'generation': stage.name, 'before': build,
                                           'after': new_build, 'workflow': workflow}]}
    mode.require(new == expected_new, 'pair_rollback_backup_changed')
    saved_generation = pair_retained_tree(generation)
    mode.require(isinstance(old.get('files'), dict)
                 and set(saved_generation) == set(old['files']) | {'entry-config.after.json', 'isolated-entry.after.json'}
                 and all(saved_generation[name] == sha for name, sha in old['files'].items())
                 and saved_generation['entry-config.after.json'] == by_path[str(bundle / 'desktop-entry.json')]['after']
                 and saved_generation['isolated-entry.after.json'] == retained['staged/entry.json'],
                 'pair_rollback_backup_changed')
    baseline.update(plan['protected_files'])
    baseline[str(bundle / 'Codex拓展入口.ico')] = build['Codex拓展入口.ico']
    mode.require(isinstance(old.get('links'), dict) and 1 <= len(old['links']) <= 4,
                 'pair_rollback_owner_invalid')
    for path, row in old['links'].items():
        mode.require(isinstance(row, dict) and re.fullmatch('[a-f0-9]{64}', row.get('after', '')),
                     'pair_rollback_owner_invalid')
        baseline[path] = row['after']
    if current:
        for path, sha in baseline.items():
            mode.require(mode.file_hash(Path(path)) == sha, 'pair_rollback_baseline_changed')
        mode.require(mode.inspect_package() == descriptor['package'], 'official_package_changed')
    return {'contract': PAIR_ROLLBACK_REVIEW, 'root': str(root), 'stage': str(stage),
            'retained_stage': retained, 'retained_transaction': saved_transaction,
            'retained_generation': saved_generation, 'restored_baseline': baseline,
            'publication_may_have_started': True, 'current_baseline_verified': True,
            'failed_result_preserved': True, 'replayed': False}


def reviewed_pair_rollback(root, stage):
    receipt = mode.decode(mode.read(stage / 'retired.json'))
    snapshot = pair_rollback_snapshot(root, stage, current=False)
    saved = receipt.get('snapshot', {})
    attempt = Path(saved.get('stopped_router_attempt', ''))
    mode.require(attempt.parent == root / 'router-launches' and re.fullmatch('[a-f0-9]{32}', attempt.name),
                 'pair_rollback_review_changed')
    snapshot['stopped_router_files'] = {name: mode.file_hash(attempt / name)
                                       for name in ('running.json', 'stopped.json')}
    snapshot['stopped_router_attempt'] = str(attempt)
    sha = mode.digest(mode.json_bytes(snapshot))
    descriptor = mode.decode(mode.read(stage / 'originals/entry.json'))
    transaction = Path(descriptor['project']) / '.codex/operator-desktop-pair/upgrades' / stage.name
    peer = mode.decode(mode.read(transaction / 'rollback-reviewed.json'))
    mode.require(receipt.get('snapshot') == snapshot and receipt.get('preview_sha256') == sha
                 and peer == {'contract': PAIR_ROLLBACK_REVIEW, 'root': str(root), 'stage': str(stage),
                              'retirement_sha256': mode.file_hash(stage / 'retired.json')},
                 'pair_rollback_review_changed')
    return True


def review_pair_rollback(root, stage, expected=None):
    import operator_model_router as router
    with mode.lock(root):
        mode.require(not (stage / 'retired.json').exists(), 'pair_rollback_review_not_fresh')
        snapshot = pair_rollback_snapshot(root, stage)
        descriptor = mode.decode(mode.read(stage / 'originals/entry.json'))
        transaction = Path(descriptor['project']) / '.codex/operator-desktop-pair/upgrades' / stage.name
        mode.require(not (transaction / 'rollback-reviewed.json').exists(), 'pair_rollback_review_not_fresh')
        stopped_desktops(root)
        activation_hosts_absent(root)
        isolated_processes_absent(root)
        attempt = mode.router_attempt(root)
        mode.require(attempt is not None, 'pair_rollback_stop_required')
        running = mode.decode(mode.read(attempt / 'running.json'))
        stopped = mode.decode(mode.read(attempt / 'stopped.json'))
        mode.require(stopped.get('process') == running.get('process')
                     and stopped.get('server_confirmed_request_free') is True
                     and not mode.process_matches(running.get('process')), 'router_stop_uncertain')
        snapshot['stopped_router_files'] = {name: mode.file_hash(attempt / name)
                                           for name in ('running.json', 'stopped.json')}
        # The proof is retained at the original attempt; it adds no clean-stop claim.
        snapshot['stopped_router_attempt'] = str(attempt)
        sha = mode.digest(mode.json_bytes(snapshot))
        with router.reserve_inactive_port(descriptor['port']):
            if expected is None:
                return {'phase': 'pair_rollback_review_ready', 'preview_sha256': sha, 'live_files_changed': False}
            mode.require(expected == sha, 'pair_rollback_preview_changed')
            isolated_processes_absent(root)
            mode.require(pair_rollback_snapshot(root, stage) == {key: value for key, value in snapshot.items()
                if key not in {'stopped_router_files', 'stopped_router_attempt'}}, 'pair_rollback_preview_changed')
            mode.write_new(stage / 'retired.json', {'snapshot': snapshot, 'preview_sha256': sha, 'reviewed_utc': mode.utc()})
            mode.write_new(transaction / 'rollback-reviewed.json', {'contract': PAIR_ROLLBACK_REVIEW,
                'root': str(root), 'stage': str(stage), 'retirement_sha256': mode.file_hash(stage / 'retired.json')})
        return {'phase': 'pair_rollback_reviewed', 'failed_result_preserved': True,
                'live_files_changed': False, 'replayed': False}


def unwritten_pair_files(stage):
    mode.checked_path(stage, directory=True)
    names = {'intent.json', 'prepared.json', 'apply-intent.json', 'failed.json'}
    names |= {directory + '/' + name for directory in ('originals', 'staged') for name in PAIR_FILES}
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()} - {'retired.json'}
    mode.require(actual == names, 'pair_failure_not_unwritten_review')
    values = {name: mode.file_hash(stage / name) for name in sorted(names)}
    failure = mode.decode(mode.read(stage / 'failed.json'))
    mode.require(failure.get('reason') == 'mode_pair_entry_busy'
                 and failure.get('automatically_retried') is False, 'pair_failure_not_unwritten_review')
    return values


def retired_pair_valid(stage):
    value = mode.decode(mode.read(stage / 'retired.json'))
    snapshot = value.get('snapshot')
    if isinstance(snapshot, dict) and snapshot.get('contract') == PAIR_ROLLBACK_REVIEW:
        return reviewed_pair_rollback(Path(snapshot.get('root', '')), stage)
    mode.require(isinstance(snapshot, dict) and snapshot.get('contract') == PAIR_RETIREMENT
                 and snapshot.get('stage') == str(stage)
                 and snapshot.get('retained_files') == unwritten_pair_files(stage)
                 and snapshot.get('installed_files_unchanged') is True
                 and snapshot.get('pair_transaction_absent') is True
                 and value.get('preview_sha256') == mode.digest(mode.json_bytes(snapshot)), 'pair_retirement_changed')
    return True


def retire_unwritten_pair(root, stage, expected=None):
    """Retain a lock-denied attempt only after proving publication never began."""
    import operator_model_router as router
    with mode.lock(root):
        mode.require(stage.parent == root / 'pair-refreshes' and re.fullmatch('[a-f0-9]{32}', stage.name)
                     and not (stage / 'retired.json').exists(), 'pair_retirement_not_fresh')
        retained = unwritten_pair_files(stage)
        descriptor = mode.decode(mode.read(root / 'entry.json'))
        project = Path(descriptor['project'])
        mode.validate_scope(project, root, Path(descriptor['native_home']))
        plan = mode.decode(mode.read(stage / 'intent.json'))
        manifest = mode.decode(mode.read(stage / 'prepared.json'))
        mode.require(plan.get('contract') == PAIR_REFRESH and plan.get('root') == str(root)
                     and manifest.get('contract') == PAIR_REFRESH and manifest.get('root') == str(root)
                     and manifest.get('generation') == stage.name and set(manifest['files']) == set(PAIR_FILES)
                     and manifest.get('protected_files') == plan.get('protected_files')
                     and mode.read(root / 'entry.json') == mode.read(stage / 'originals/entry.json'),
                     'pair_retirement_baseline_changed')
        for name, row in manifest['files'].items():
            mode.require(row['before'] == plan['managed_files'][name] == mode.file_hash(root / name)
                         == mode.file_hash(stage / 'originals' / name)
                         and row['after'] == mode.file_hash(stage / 'staged' / name), 'pair_retirement_baseline_changed')
        for path, sha in plan['protected_files'].items():
            mode.require(mode.file_hash(Path(path)) == sha, 'pair_retirement_baseline_changed')
        for directory in ('generations', 'upgrades'):
            target = project / '.codex/operator-desktop-pair' / directory / stage.name
            mode.checked_path(target, directory=True, exists=False)
            mode.require(not target.exists(), 'pair_publication_may_have_started')
        mode.require(mode.inspect_package() == descriptor['package'], 'official_package_changed')
        stopped_desktops(root)
        activation_hosts_absent(root)
        attempt = mode.router_attempt(root)
        mode.require(attempt is not None, 'pair_retirement_stop_required')
        running = mode.decode(mode.read(attempt / 'running.json'))
        stopped = mode.decode(mode.read(attempt / 'stopped.json'))
        mode.require(stopped.get('process') == running.get('process')
                     and stopped.get('server_confirmed_request_free') is True
                     and not mode.process_matches(running.get('process')), 'router_stop_uncertain')
        snapshot = {'contract': PAIR_RETIREMENT, 'stage': str(stage), 'retained_files': retained,
                    'installed_files_unchanged': True, 'pair_transaction_absent': True,
                    'router_stopped': True, 'desktop_exited': True, 'replayed': False}
        sha = mode.digest(mode.json_bytes(snapshot))
        with router.reserve_inactive_port(descriptor['port']):
            if expected is None:
                return {'phase': 'pair_retirement_ready', 'preview_sha256': sha, 'live_files_changed': False}
            mode.require(expected == sha, 'pair_retirement_preview_changed')
            mode.write_new(stage / 'retired.json', {'snapshot': snapshot, 'preview_sha256': sha,
                                                  'retired_utc': mode.utc()})
        return {'phase': 'unwritten_pair_attempt_retired', 'failed_result_preserved': True,
                'live_files_changed': False, 'replayed': False}


def pair_prepare(root, *, compiler=mode.compile_host, registry_path=None, web_profile=None, package_update=False):
    import operator_model_router as router
    from operator_mode_backends import snapshot, candidate_descriptor, BACKEND_FILES
    with mode.lock(root):
        plan = mode.refresh_snapshot(root, bound_pair=True, registry_path=registry_path, web_profile=web_profile,
                                     package_update=package_update)
        with router.reserve_inactive_port(plan['port']):
            parent = root / 'pair-refreshes'
            if not parent.exists():
                mode.private_directory(parent)
            stage = parent / mode.secrets.token_hex(16)
            mode.private_directory(stage)
            mode.write_new(stage / 'intent.json', plan)
            try:
                for name in ('originals', 'staged'):
                    mode.private_directory(stage / name)
                files = (*PAIR_FILES, *(BACKEND_FILES if 'backend_update' in plan else ()))
                for name in files:
                    raw = mode.read(root / name)
                    mode.require(mode.digest(raw) == plan['managed_files'][name], 'pair_original_changed')
                    (stage / 'originals' / name).parent.mkdir(parents=True, exist_ok=True)
                    mode.write_new(stage / 'originals' / name, raw)
                descriptor = mode.decode(mode.read(stage / 'originals/entry.json'))
                descriptor = mode.package_update_descriptor(descriptor, plan.get('package_update'))
                if 'backend_update' in plan:
                    update, registry_raw, catalog_raw = snapshot(root, registry_path, web_profile)
                    mode.require(update == plan['backend_update'], 'pair_backend_snapshot_changed')
                    for name, raw in zip(BACKEND_FILES, (registry_raw, catalog_raw)):
                        (stage / 'staged' / name).parent.mkdir(parents=True, exist_ok=True)
                        mode.write_new(stage / 'staged' / name, raw)
                    descriptor = candidate_descriptor(descriptor, update)
                outputs = compiler(stage / 'staged')
                mode.require(set(outputs) == set(PAIR_FILES) - {'entry.json', 'entry.ps1'}, 'pair_compile_incomplete')
                descriptor.update(source_bindings=plan['sources'], compiled=outputs,
                                  entry_sha256=mode.file_hash(mode.SCRIPTS / 'operator_mode_entry.ps1'))
                mode.write_new(stage / 'staged/entry.ps1', mode.read(mode.SCRIPTS / 'operator_mode_entry.ps1'))
                mode.write_new(stage / 'staged/entry.json', descriptor)
                mode.require(mode.refresh_snapshot(root, bound_pair=True, registry_path=registry_path,
                    web_profile=web_profile, package_update=package_update) == plan, 'pair_prepare_baseline_changed')
                manifest = {'contract': PAIR_REFRESH, 'root': str(root), 'generation': stage.name,
                            'files': {name: {'before': plan['managed_files'][name],
                                             'after': mode.file_hash(stage / 'staged' / name)} for name in files},
                            'protected_files': plan['protected_files']}
                if 'backend_update' in plan:
                    manifest['backend_update'] = plan['backend_update']
                if 'package_update' in plan:
                    manifest['package_update'] = plan['package_update']
                mode.write_new(stage / 'prepared.json', manifest)
            except Exception as error:
                mode.write_new(stage / 'failed.json', {'reason': mode.failure_reason(error),
                    'retained_utc': mode.utc(), 'automatically_retried': False})
                raise
        return {'phase': 'pair_refresh_prepared', 'stage': str(stage), 'live_files_changed': False,
                'model_requests': 0, 'desktop_launch': False}


def pair_stage(root, stage):
    from operator_mode_backends import candidate_descriptor, BACKEND_FILES
    mode.checked_path(stage, directory=True)
    mode.require(stage.parent == root / 'pair-refreshes' and re.fullmatch('[a-f0-9]{32}', stage.name)
                 and not any((stage / name).exists() for name in ('apply-intent.json', 'completed.json', 'failed.json')),
                 'pair_stage_not_fresh')
    intent = mode.decode(mode.read(stage / 'intent.json'))
    update = intent.get('backend_update')
    plan = mode.refresh_snapshot(root, bound_pair=True,
        registry_path=mode.Path(update['registry_file']) if update is not None else None,
        web_profile=mode.Path(update['web']['profile']) if update is not None and update['web'] is not None else None,
        package_update='package_update' in intent)
    mode.require(intent == plan, 'pair_stage_baseline_changed')
    manifest = mode.decode(mode.read(stage / 'prepared.json'))
    files = (*PAIR_FILES, *(BACKEND_FILES if update is not None else ()))
    mode.require(manifest.get('contract') == PAIR_REFRESH and manifest.get('root') == str(root)
                 and manifest.get('generation') == stage.name and set(manifest.get('files', {})) == set(files)
                 and manifest.get('backend_update') == update
                 and manifest.get('package_update') == plan.get('package_update')
                 and manifest.get('protected_files') == plan['protected_files'], 'pair_stage_invalid')
    for name in files:
        row = manifest['files'][name]
        mode.require(row.get('before') == plan['managed_files'][name]
                     == mode.file_hash(stage / 'originals' / name)
                     and row.get('after') == mode.file_hash(stage / 'staged' / name), 'pair_stage_changed')
    original = mode.decode(mode.read(stage / 'originals/entry.json'))
    candidate = mode.decode(mode.read(stage / 'staged/entry.json'))
    expected = candidate_descriptor(original, update)
    expected = mode.package_update_descriptor(expected, plan.get('package_update'))
    expected.update(source_bindings=plan['sources'], entry_sha256=manifest['files']['entry.ps1']['after'],
                    compiled={name: manifest['files'][name]['after'] for name in PAIR_FILES if name.endswith('.exe')})
    mode.require(candidate == expected
                 and mode.read(stage / 'staged/entry.ps1') == mode.read(mode.SCRIPTS / 'operator_mode_entry.ps1'),
                 'pair_descriptor_changed')
    return plan, manifest


def pair_powershell(root, stage, action, expected=None):
    shell = mode.shutil.which('pwsh.exe')
    mode.require(shell is not None, 'powershell_unavailable')
    arguments = [shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                 str(mode.SCRIPTS / 'operator_mode_pair_refresh.ps1'), '-Action', action,
                 '-Root', str(root), '-StageDirectory', str(stage)]
    if expected is not None:
        arguments += ['-ExpectedPlanSha256', expected]
    result = subprocess.run(arguments, capture_output=True, timeout=90,
                            creationflags=subprocess.CREATE_NO_WINDOW if mode.os.name == 'nt' else 0)
    mode.require(len(result.stdout) <= 65536, 'pair_response_bound')
    value = mode.decode(result.stdout)
    if result.returncode != 0:
        code = value.get('reason') if isinstance(value, dict) else None
        raise mode.ModeEntryError(code if isinstance(code, str) and re.fullmatch('[a-z][a-z0-9_]{1,127}', code)
                                  else 'mode_pair_refresh_failed')
    mode.require(value.get('native_config_writes') == 0 and value.get('desktop_launch') is False,
                 'pair_response_invalid')
    return value


def pair_preview(root, stage):
    import operator_model_router as router
    with mode.lock(root):
        plan, _ = pair_stage(root, stage)
        with router.reserve_inactive_port(plan['port']):
            return pair_powershell(root, stage, 'preview')


def pair_apply(root, stage, expected):
    import operator_model_router as router
    with mode.lock(root):
        plan, manifest = pair_stage(root, stage)
        with router.reserve_inactive_port(plan['port']):
            preview = pair_powershell(root, stage, 'preview')
            mode.require(re.fullmatch('[a-f0-9]{64}', expected or '')
                         and preview.get('preview_sha256') == expected, 'pair_preview_changed')
            mode.write_new(stage / 'apply-intent.json', {'preview_sha256': expected, 'started_utc': mode.utc()})
            try:
                value = pair_powershell(root, stage, 'apply', expected)
                mode.require(value.get('phase') == 'pair_refreshed' and value.get('generation') == stage.name,
                             'pair_apply_unconfirmed')
                for name, row in manifest['files'].items():
                    mode.require(mode.file_hash(root / name) == row['after'], 'pair_write_unconfirmed')
                for path, sha in plan['protected_files'].items():
                    mode.require(mode.file_hash(Path(path)) == sha, 'pair_protected_file_changed')
                mode.write_new(stage / 'completed.json', {'completed_utc': mode.utc(), 'preview_sha256': expected,
                    'entry_sha256': mode.file_hash(root / 'entry.json'), 'home_preserved': True})
            except Exception as error:
                mode.write_new(stage / 'failed.json', {'reason': mode.failure_reason(error),
                    'retained_utc': mode.utc(), 'automatically_retried': False})
                raise
        mode.load(root)
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['focus-preview', 'focus-review', 'service-stop',
                                         'router-absence-preview', 'router-absence-review',
                                         'startup-preview', 'startup-review',
                                         'pair-prepare', 'pair-preview', 'pair-apply',
                                         'retire-pair-preview', 'retire-pair',
                                         'rollback-pair-preview', 'rollback-pair-review', 'rollback-pair-status'])
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--registry-file', type=Path)
    parser.add_argument('--web-profile', type=Path)
    parser.add_argument('--package-update', action='store_true')
    parser.add_argument('--activation')
    parser.add_argument('--attempt')
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--expected-preview-sha256')
    args = parser.parse_args()
    try:
        mode.require(args.root.is_absolute(), 'absolute_root_required')
        mode.require(args.action == 'pair-prepare' or (args.registry_file is None and args.web_profile is None),
                     'backend_options_require_pair_prepare')
        mode.require(args.action == 'pair-prepare' or not args.package_update, 'package_update_requires_pair_prepare')
        if args.action == 'service-stop':
            result = maintenance_stop(args.root)
        elif args.action in {'router-absence-preview', 'router-absence-review'}:
            if args.action == 'router-absence-review':
                mode.require(re.fullmatch('[a-f0-9]{64}', args.expected_preview_sha256 or ''),
                             'router_absence_preview_required')
            result = review_router_absence(args.root,
                args.expected_preview_sha256 if args.action == 'router-absence-review' else None)
        elif args.action in {'startup-preview', 'startup-review'}:
            if args.action == 'startup-review':
                mode.require(re.fullmatch('[a-f0-9]{64}', args.expected_preview_sha256 or ''),
                             'startup_review_preview_required')
            result = review_startup(args.root, args.attempt,
                                    args.expected_preview_sha256 if args.action == 'startup-review' else None)
        elif args.action == 'pair-prepare':
            result = pair_prepare(args.root, registry_path=args.registry_file, web_profile=args.web_profile,
                                  package_update=args.package_update)
        elif args.action in {'pair-preview', 'pair-apply'}:
            mode.require(args.stage is not None and args.stage.is_absolute(), 'pair_stage_required')
            result = pair_preview(args.root, args.stage) if args.action == 'pair-preview' else pair_apply(
                args.root, args.stage, args.expected_preview_sha256)
        elif args.action in {'retire-pair-preview', 'retire-pair'}:
            mode.require(args.stage is not None and args.stage.is_absolute(), 'pair_stage_required')
            if args.action == 'retire-pair':
                mode.require(re.fullmatch('[a-f0-9]{64}', args.expected_preview_sha256 or ''),
                             'pair_retirement_preview_required')
            result = retire_unwritten_pair(args.root, args.stage,
                args.expected_preview_sha256 if args.action == 'retire-pair' else None)
        elif args.action in {'rollback-pair-preview', 'rollback-pair-review', 'rollback-pair-status'}:
            mode.require(args.stage is not None and args.stage.is_absolute(), 'pair_stage_required')
            if args.action == 'rollback-pair-status':
                mode.require(reviewed_pair_rollback(args.root, args.stage), 'pair_rollback_review_changed')
                result = {'phase': 'pair_rollback_reviewed', 'live_files_changed': False, 'replayed': False}
            else:
                if args.action == 'rollback-pair-review':
                    mode.require(re.fullmatch('[a-f0-9]{64}', args.expected_preview_sha256 or ''),
                                 'pair_rollback_preview_required')
                result = review_pair_rollback(args.root, args.stage,
                    args.expected_preview_sha256 if args.action == 'rollback-pair-review' else None)
        else:
            if args.action == 'focus-review':
                mode.require(re.fullmatch('[a-f0-9]{64}', args.expected_preview_sha256 or ''),
                             'focus_review_preview_required')
            result = review_focus(args.root, args.activation,
                                  args.expected_preview_sha256 if args.action == 'focus-review' else None)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({'phase': 'failed', 'reason': mode.failure_reason(error),
                          'automatically_retried': False}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
