"""Explicit archival of one reviewed cache-prewrite failure; never replay it.

The original attempt remains failed. A complete archive only frees its fixed
allocation path; it does not activate routing, replace cache/config/entry bytes,
start services, or authorize replay. Unknown and partial attempts remain blocked.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import tomllib
from copy import deepcopy

import operator_unified_retire as records
from operator_core import windows_config_transaction as transaction

ROOT = 'operator-unified-failed-archive'
SCOPE = 'reviewed_cache_prewrite_failure_archive'
RUN = re.compile(r'generation-[a-f0-9]{32}\Z')
KNOWN_CONSUMER = 'af99c0e24316641e30ab2919e9bf3730cbf10fe4d16e140ad0784fcea5dba8bf'
FAILURE = {'schema_version': 1, 'stage': 'consume', 'status': 'stopped_for_review',
    'native_reopen_attempted': False, 'model_requests': 0, 'native_reopen_witnessed': False,
    'activation_status': 'attempt_requires_review', 'reason': 'unified_cache_changed'}
SOURCE_FILES = ('operator_unified_failed_archive.py', 'operator_unified_retire.py',
    'operator_unified_withdraw.py', 'operator_unified_supersede.py',
    'operator_unified_cold_start.py', 'operator_unified_prepare.py',
    'operator_unified_entry_preview.py', 'operator_legacy_runtime_upgrade.py',
    'operator_web_service.py', 'operator_core/windows_config_transaction.py',
    'operator_installation.psm1', 'operator_desktop_pair.psm1',
    'operator_desktop_pair_legacy.psm1', 'operator_desktop_pair_upgrade.psm1',
    'operator_entry_migration.ps1', 'operator_entry_upgrade.ps1',
    'operator_entry_shortcut_adoption.ps1', 'restore-codex-official-route.ps1')
REVIEW_KEYS = {'schema_version', 'scope', 'project', 'home', 'plan_sha256',
    'directory_identity', 'files', 'context', 'config_delta', 'source_sha256',
    'queue', 'recovery', 'config', 'marker', 'cache', 'entry'}


class FailedArchiveError(ValueError):
    """Fixed local failure codes; no paths, requests or credentials."""


def _directory_identity(path: Path) -> dict:
    from operator_unified_withdraw import _allocation_directory_handle
    with _allocation_directory_handle(path) as handle:
        identity, _ = transaction._identity(handle)
        return {'volume': identity.volume, 'file_id': identity.file_id}


def _snapshot(path: Path, *, optional=False):
    from operator_unified_withdraw import _snapshot as snapshot
    return snapshot(path, optional=optional)


def _context(paths: dict[str, Path]) -> dict:
    return {name: {'path': str(path), **_snapshot(path)} for name, path in sorted(paths.items())}


def _tree(path: Path) -> dict:
    value = records._tree(path)
    return {name: ({'directory': True, 'identity': _directory_identity(path / name)}
                   if 'directory' in item else item) for name, item in value.items()}


def _sources() -> dict:
    parent = Path(__file__).resolve().parent
    return {name: records._hash(records._read(parent / name)) for name in SOURCE_FILES}


def _failure(raw: bytes) -> bool:
    value = json.loads(raw)
    return (value == FAILURE and type(value['schema_version']) is int
            and type(value['model_requests']) is int
            and type(value['native_reopen_attempted']) is bool
            and type(value['native_reopen_witnessed']) is bool)


def _config_delta(saved: bytes, current: bytes) -> str:
    """Review current native effort as data; never restore or dispatch it.

    Only this failed-archive path admits the observed native effort preferences.
    Ordinary retirement and all cold-launch equality checks remain unchanged.
    """
    try:
        return records._config_delta(saved, current)
    except records.RetireError:
        pass
    try:
        before, after = tomllib.loads(saved.decode()), tomllib.loads(current.decode())
        efforts = {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}
        if (before.get('model_reasoning_effort') not in efforts
                or after.get('model_reasoning_effort') not in efforts
                or before['model_reasoning_effort'] == after['model_reasoning_effort']):
            raise ValueError()
        old_lines, new_lines = saved.splitlines(keepends=True), current.splitlines(keepends=True)
        if len(old_lines) != len(new_lines):
            raise ValueError()
        pattern = re.compile(rb'''model_reasoning_effort = (?P<quote>["'])(?:low|medium|high|xhigh|max|ultra)(?P=quote)(?P<ending>\r?\n?)\Z''')
        changed = [index for index, (old, new) in enumerate(zip(old_lines, new_lines))
                   if old != new and pattern.fullmatch(old) and pattern.fullmatch(new)]
        if len(changed) != 1:
            raise ValueError()
        index = changed[0]
        a, b = pattern.fullmatch(old_lines[index]), pattern.fullmatch(new_lines[index])
        if a['quote'] != b['quote'] or a['ending'] != b['ending']:
            raise ValueError()
        old_lines[index] = new_lines[index]
        adjusted = b''.join(old_lines)
        expected = deepcopy(before)
        expected['model_reasoning_effort'] = after['model_reasoning_effort']
        if tomllib.loads(adjusted.decode()) != expected:
            raise ValueError()
        records._config_delta(adjusted, current)
        return 'native_effort_and_desktop_preferences_only'
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise FailedArchiveError('unified_failed_archive_native_config_changed') from exc


def _validate_intent(value: dict) -> None:
    from operator_unified_withdraw import _valid_snapshot, ENTRY_REQUIRED, ENTRY_OPTIONAL
    expected = {'schema_version', 'scope', 'source', 'target', 'review', 'review_sha256'}
    review = value.get('review')
    if (set(value) != expected or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['scope'] != SCOPE
            or not isinstance(review, dict) or set(review) != REVIEW_KEYS
            or type(review.get('schema_version')) is not int or review['schema_version'] != 1
            or review.get('scope') != SCOPE
            or value['review_sha256'] != records._hash(records._json(review))):
        raise FailedArchiveError('unified_failed_archive_intent_invalid')
    home = Path(review['home'])
    source, target = Path(value['source']), Path(value['target'])
    if (not home.is_absolute() or source != home / 'operator-unified-activation'
            or target.name != 'evidence' or target.parent.parent != home / ROOT
            or RUN.fullmatch(target.parent.name) is None
            or not isinstance(review.get('files'), dict)
            or not isinstance(review.get('context'), dict)
            or not isinstance(review.get('directory_identity'), dict)
            or not isinstance(review.get('project'), str) or not Path(review['project']).is_absolute()
            or not isinstance(review.get('plan_sha256'), str)
            or records.HEX64.fullmatch(review['plan_sha256']) is None
            or review['config_delta'] not in {'unchanged', 'cua_pipe_only', 'desktop_preferences_only',
                                             'native_effort_and_desktop_preferences_only'}
            or set(review['source_sha256']) != set(SOURCE_FILES)
            or any(not isinstance(item, str) or records.HEX64.fullmatch(item) is None
                   for item in review['source_sha256'].values())
            or review['queue'] != {'actionable_inbox': 0, 'open_callbacks': 0}
            or any(type(item) is not int for item in review['queue'].values())
            or not _valid_snapshot(review['config']) or not _valid_snapshot(review['marker'])
            or not _valid_snapshot(review['cache'], optional=True)
            or not ENTRY_REQUIRED <= set(review['entry']) <= ENTRY_REQUIRED | ENTRY_OPTIONAL
            or any(not _valid_snapshot(item, optional=name in ENTRY_OPTIONAL)
                   for name, item in review['entry'].items())):
        raise FailedArchiveError('unified_failed_archive_intent_invalid')


def _verify_run(run: Path, *, pending=False) -> dict:
    names = {'intent.json', 'receipt.json', 'evidence', 'context'}
    if pending:
        names.add('completion-pending.json')
    if {path.name for path in run.iterdir()} != names:
        raise FailedArchiveError('unified_failed_archive_incomplete')
    intent, raw = records._load(run / 'intent.json', 262144)
    _validate_intent(intent)
    receipt, _ = records._load(run / 'receipt.json')
    if (Path(intent['target']) != run / 'evidence'
            or receipt != {'schema_version': 1, 'phase': 'failed_original_archived_witnessed',
                           'intent_sha256': records._hash(raw)}
            or _tree(run / 'evidence') != intent['review']['files']
            or _directory_identity(run / 'evidence') != intent['review']['directory_identity']):
        raise FailedArchiveError('unified_failed_archive_changed')
    context = intent['review']['context']
    if {path.name for path in (run / 'context').iterdir()} != set(context):
        raise FailedArchiveError('unified_failed_archive_context_changed')
    for name, item in context.items():
        if (Path(name).name != name or name in {'.', '..'}
                or records._hash(records._read(run / 'context' / name)) != item['sha256']):
            raise FailedArchiveError('unified_failed_archive_context_changed')
    if (records._hash(records._read(run / 'context/consumer.py.txt')) != KNOWN_CONSUMER
            or not _failure(records._read(run / 'context/handoff-result.json'))
            or records._hash(records._read(run / 'evidence/plan.json')) != intent['review']['plan_sha256']
            or records._present(run / 'evidence/completion.json')):
        raise FailedArchiveError('unified_failed_archive_original_changed')
    return intent


def archive_status(home: Path, *, pending: Path | None = None) -> dict:
    """Static read-only integrity gate. No current task or cache observation."""
    root = home / ROOT
    if not records._present(root):
        return {'status': 'absent', 'generations': 0}
    try:
        records._plain(root)
        runs = list(root.iterdir())
        if len(runs) > 32:
            raise FailedArchiveError('unified_failed_archive_capacity')
        for run in runs:
            records._plain(run)
            if not run.is_dir() or RUN.fullmatch(run.name) is None:
                raise FailedArchiveError('unified_failed_archive_invalid')
            if run == pending:
                # Internal caller holds the entry mutex, current-file guards,
                # source directory handle and port reservation. Public status
                # never supplies this exception and remains uncertain.
                continue
            intent = _verify_run(run)
            if intent['review']['home'] != str(home):
                raise FailedArchiveError('unified_failed_archive_scope')
        return {'status': 'failed_originals_retained', 'generations': len(runs)}
    except Exception:
        return {'status': 'uncertain'}


def _inspect(plan_path: Path, handoff_result: Path, consumer: Path,
             recovery: Path, *, reserved=False, pending: Path | None = None) -> dict:
    import operator_unified_cold_start as cold
    import operator_unified_supersede as supersede
    import operator_unified_entry_preview as entry
    import operator_unified_withdraw as withdraw
    import operator_legacy_runtime_upgrade as upgrade
    import operator_web_service as web

    paths = [plan_path, handoff_result, consumer, recovery]
    if any(not path.is_absolute() for path in paths):
        raise FailedArchiveError('unified_failed_archive_absolute_scope_required')
    plan, plan_raw, directory = cold._plan(plan_path)
    project, home = Path(plan['project']), Path(plan['home'])
    if (handoff_result.name != 'result.json'
            or handoff_result.parent.parent != project / '.codex/operator-unified-handoff'
            or re.fullmatch(r'run-[a-f0-9]{32}', handoff_result.parent.name) is None
            or consumer.is_relative_to(directory)
            or recovery.is_relative_to(directory)):
        raise FailedArchiveError('unified_failed_archive_evidence_scope')
    if pending is not None and (pending.parent != home / ROOT or RUN.fullmatch(pending.name) is None):
        raise FailedArchiveError('unified_failed_archive_scope')
    if archive_status(home, pending=pending)['status'] == 'uncertain':
        raise FailedArchiveError('unified_failed_archive_requires_review')
    if pending is None and archive_status(home).get('generations', 0) >= 32:
        raise FailedArchiveError('unified_failed_archive_capacity')
    if (records.archive_status(home)['status'] == 'uncertain'
            or supersede.archive_status(home)['status'] == 'uncertain'):
        raise FailedArchiveError('unified_failed_archive_other_history_uncertain')
    if (records._hash(records._read(consumer)) != KNOWN_CONSUMER
            or not _failure(records._read(handoff_result, 16384))):
        raise FailedArchiveError('unified_failed_archive_failure_contract_changed')
    result = json.loads(records._read(handoff_result, 16384))
    if (type(result['model_requests']) is not int or type(result['schema_version']) is not int
            or type(result['native_reopen_attempted']) is not bool
            or type(result['native_reopen_witnessed']) is not bool):
        raise FailedArchiveError('unified_failed_archive_failure_contract_changed')
    manifest, _ = records._load(handoff_result.parent / 'manifest.json', 16384)
    if (manifest.get('schema_version') != 1 or manifest.get('plan') != str(plan_path)
            or manifest.get('home') != str(home) or manifest.get('project') != str(project)
            or manifest.get('config_sha256') != plan['config_sha256']
            or manifest.get('router_state') != plan['router']['state']
            or manifest.get('web_profile') != plan['router']['web_profile']
            or manifest.get('port') != plan['router']['port']
            or manifest.get('source_sha256', {}).get('operator_unified_cold_start.py') != KNOWN_CONSUMER):
        raise FailedArchiveError('unified_failed_archive_handoff_changed')
    plan_sha = records._hash(plan_raw)
    journal, _ = records._load(directory / 'journal.json')
    arm, _ = records._load(directory / 'arm.json')
    attempt, _ = records._load(directory / 'attempt.json')
    backup = attempt.get('cache_backup')
    if (journal != {'schema_version': 1, 'phase': 'prepared_not_armed', 'plan_sha256': plan_sha}
            or set(arm) != {'schema_version', 'phase', 'plan_sha256', 'consumer_sha256',
                           'python_sha256', 'entry', 'launcher', 'marker_release_sha256'}
            or arm.get('schema_version') != 1 or arm.get('phase') != 'armed'
            or arm.get('plan_sha256') != plan_sha or arm.get('consumer_sha256') != KNOWN_CONSUMER
            or not isinstance(backup, str) or records.RETIRED_CACHE.fullmatch(backup) is None
            or attempt != {'schema_version': 1, 'phase': 'may_have_activated',
                           'plan_sha256': plan_sha, 'cache_backup': backup}):
        raise FailedArchiveError('unified_failed_archive_attempt_invalid')
    expected = {'before.toml', 'candidate.toml', 'plan.json', 'journal.json', 'arm.json',
                'attempt.json', 'marker-release'}
    if plan['cache']['existed']:
        expected.add('cache-before.bin')
    if {path.name for path in directory.iterdir()} != expected:
        raise FailedArchiveError('unified_failed_archive_partial_or_unknown_attempt')
    if (records._hash(records._read(directory / 'before.toml')) != plan['config_sha256']
            or records._hash(records._read(directory / 'candidate.toml')) != plan['candidate_sha256']
            or (plan['cache']['existed'] and records._hash(records._read(directory / 'cache-before.bin'))
                != plan['cache']['sha256'])):
        raise FailedArchiveError('unified_failed_archive_original_changed')
    release, saved_entry = records._historical_release(plan, directory, plan_sha, arm)
    if release is None or arm.get('marker_release_sha256') != release:
        raise FailedArchiveError('unified_failed_archive_release_changed')
    marker_intent, _ = records._load(directory / 'marker-release/intent.json')
    if {path.name for path in (directory / 'marker-release').iterdir()} != {
            'intent.json', 'receipt.json', 'before.bin', marker_intent['backup']}:
        raise FailedArchiveError('unified_failed_archive_partial_or_unknown_attempt')
    recovery_check = records._recovery(plan, directory, recovery, False, True)
    if saved_entry.get('configuration_sha256') != recovery_check['entry_before_sha256']:
        raise FailedArchiveError('unified_failed_archive_recovery_changed')
    recovered, _ = records._load(recovery, 65536)
    row = next(row for row in recovered['files'] if row['name'] == 'desktop-entry.json')
    if entry.verify_owned_entry(project, project / '.codex/operator-desktop-entry',
            recovered_config=row) != saved_entry['ownership_sha256']:
        raise FailedArchiveError('unified_failed_archive_entry_owner_changed')
    current = withdraw._current(plan)
    if current['marker']['sha256'] != records._hash(records.MARKER):
        raise FailedArchiveError('unified_failed_archive_native_marker_changed')
    delta = _config_delta(records._read(directory / 'before.toml'),
                                 transaction.observe_config(home / 'config.toml').data)
    python = Path(manifest['python'])
    if (python != Path(sys.executable).resolve(strict=True)
            or records._hash(records._read(python, 16777216)) != arm['python_sha256']):
        raise FailedArchiveError('unified_failed_archive_python_changed')
    workflow = project / '.codex/operator-unified-startup'
    script = records._read(workflow / cold.SCRIPT, 16384)
    sync = records._read(workflow / 'startup-sync-plan.json', 16384)
    desired_old = cold.render_workflow(python, plan_path).replace(
        records._hash(records._read(Path(cold.__file__).resolve())).encode(), KNOWN_CONSUMER.encode())
    if (script != desired_old or records._hash(script) != plan['startup_bundle']['startup_script_sha256']
            or records._hash(sync) != plan['startup_bundle']['sync_plan_sha256']):
        raise FailedArchiveError('unified_failed_archive_workflow_changed')
    # Exact absence and an exclusively reservable port are separate evidence
    # from a clean stop. The failed record is never relabelled as success.
    if not reserved:
        records._stopped(plan, require_desktop_closed=False)
    elif web.process_identity(plan['router']['process']['pid']) is not None:
        raise FailedArchiveError('unified_failed_archive_router_reappeared')
    if records._present(Path(plan['router']['state']) / 'codex-entry.json'):
        raise FailedArchiveError('unified_failed_archive_route_active')
    upgrade.process_gate(project, Path(__file__).resolve().parent.parent)
    queue = upgrade.queue_gate(project / '.codex/feishu-codex-operator-runtime')
    if web.status(Path(plan['router']['web_profile']))['status'] not in {'stopped', 'configured'}:
        raise FailedArchiveError('unified_failed_archive_saved_web_not_stopped')
    context = {'consumer.py.txt': consumer, 'recovery-intent.json': recovery,
               'recovery-completed.json': recovery.parent / 'completed.json',
               'recovery-entry-before.json': recovery.parent / 'desktop-entry.json.before',
               'workflow.ps1': workflow / cold.SCRIPT,
               'workflow-sync.json': workflow / 'startup-sync-plan.json'}
    handoff_tree = records._tree(handoff_result.parent)
    if len(handoff_tree) > 16 or any('directory' in item for item in handoff_tree.values()):
        raise FailedArchiveError('unified_failed_archive_handoff_bound')
    context.update({'handoff-' + name: handoff_result.parent / name for name in handoff_tree})
    original_tree = _tree(directory)
    context.update({'original--' + name.replace('/', '--'): directory / name
                    for name, item in original_tree.items() if 'directory' not in item})
    return {'schema_version': 1, 'scope': SCOPE, 'project': str(project), 'home': str(home),
        'plan_sha256': plan_sha, 'directory_identity': _directory_identity(directory),
        'files': original_tree, 'context': _context(context),
        'config_delta': delta, 'source_sha256': _sources(), 'queue': queue,
        'recovery': recovery_check, **current}


def preview(plan: Path, result: Path, consumer: Path, recovery: Path) -> dict:
    review = _inspect(plan, result, consumer, recovery)
    return {'status': 'failed_archive_reviewed_preview',
            'review_sha256': records._hash(records._json(review)),
            'original_attempt_status': 'failed_retained', 'configuration_changed': False,
            'cache_changed': False, 'entry_changed': False, 'model_requests': 0}


def _rename_handle(handle, parent_handle, target: Path, identity: dict) -> None:
    from operator_unified_withdraw import _RenameInfo
    current, _ = transaction._identity(handle)
    parent, _ = transaction._identity(parent_handle)
    if ({'volume': current.volume, 'file_id': current.file_id} != identity
            or parent.volume != current.volume or not target.is_absolute()
            or _directory_identity(target.parent) != {'volume': parent.volume, 'file_id': parent.file_id}):
        raise FailedArchiveError('unified_failed_archive_directory_changed')
    name = str(target).encode('utf-16-le')
    buffer = ctypes.create_string_buffer(_RenameInfo.name.offset + len(name) + 2)
    value = _RenameInfo.from_buffer(buffer)
    value.flags, value.root, value.name_length = 0, None, len(name)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, name, len(name))
    kernel = transaction._kernel
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    if not kernel.SetFileInformationByHandle(handle, 3, buffer, len(buffer)):
        raise FailedArchiveError('unified_failed_archive_move_failed_' + str(ctypes.get_last_error()))


def archive(plan: Path, result: Path, consumer: Path, recovery: Path, expected: str) -> dict:
    import operator_unified_withdraw as withdraw
    import operator_model_router as router
    from operator_core.web_browser_driver import private_directory
    review = _inspect(plan, result, consumer, recovery)
    if (not isinstance(expected, str) or records.HEX64.fullmatch(expected) is None
            or expected != records._hash(records._json(review))):
        raise FailedArchiveError('unified_failed_archive_review_changed')
    native = Path(review['home'])
    root = native / ROOT
    with withdraw._entry_mutex(Path(review['project'])), ExitStack() as stack:
        stack.enter_context(transaction._open(native, directory=True))
        withdraw._freeze_current(review, stack)
        originals = stack.enter_context(ExitStack())
        original_data = {}
        for relative, item in review['files'].items():
            if 'directory' in item:
                continue
            path = plan.parent / relative
            handle = originals.enter_context(transaction._open(path))
            data, identity = transaction._read_handle(handle)
            snapshot = transaction.ConfigSnapshot(path, data, identity)
            if {'sha256': records._hash(snapshot.data), 'identity': records._identity(snapshot)} != item:
                raise FailedArchiveError('unified_failed_archive_original_changed')
            original_data[path] = snapshot
        copied = {}
        for name, item in review['context'].items():
            path = Path(item['path'])
            snapshot = original_data.get(path)
            if snapshot is None:
                snapshot = transaction._snapshot_while_frozen(path, stack)
            if records._hash(snapshot.data) != item['sha256'] or records._identity(snapshot) != item['identity']:
                raise FailedArchiveError('unified_failed_archive_context_changed')
            copied[name] = snapshot.data
        source_handle = stack.enter_context(withdraw._allocation_directory_handle(plan.parent, moving=True))
        if _inspect(plan, result, consumer, recovery) != review:
            raise FailedArchiveError('unified_failed_archive_review_changed')
        binding = json.loads(records._read(plan))['router']
        stack.enter_context(router.reserve_inactive_port(binding['port']))
        if not records._present(root):
            private_directory(root)
        records._plain(root)
        stack.enter_context(transaction._open(root, directory=True))
        run = root / ('generation-' + secrets.token_hex(16))
        private_directory(run)
        parent_handle = stack.enter_context(withdraw._allocation_directory_handle(run, parent=True))
        intent = {'schema_version': 1, 'scope': SCOPE, 'source': str(plan.parent),
                  'target': str(run / 'evidence'), 'review': review, 'review_sha256': expected}
        records._record(run / 'intent.json', intent)
        private_directory(run / 'context')
        for name, data in copied.items():
            transaction._write_new(run / 'context' / name, data)
        fence_raw = records._json({'scope': SCOPE, 'intent_sha256': records._hash(records._json(intent))})
        transaction._write_new(run / 'completion-pending.json', fence_raw)
        fence = stack.enter_context(withdraw._completion_fence_handle(run / 'completion-pending.json', fence_raw))
        if _inspect(plan, result, consumer, recovery, reserved=True, pending=run) != review:
            # The pending archive has an exclusive intent and cannot be retried.
            raise FailedArchiveError('unified_failed_archive_review_changed')
        # Windows refuses a nonempty cross-parent directory rename while its
        # descendants have open handles, including fully delete-shared readers.
        # Keep the directory identity bound, close only those readers, then move
        # once and freeze/witness all original bytes and identities afterward.
        # A changed child is retained in an uncertain archive, never accepted.
        originals.close()
        _rename_handle(source_handle, parent_handle, run / 'evidence', review['directory_identity'])
        if records._present(plan.parent):
            raise FailedArchiveError('unified_failed_archive_source_reappeared')
        # Windows requires delete sharing on child handles for the directory
        # move. Once moved, freeze every retained file against writes/replacement
        # through the receipt and final completion boundary. Path swaps during
        # the move still fail the full original identity/bytes witness.
        for relative, item in review['files'].items():
            if 'directory' in item:
                continue
            snapshot = transaction._snapshot_while_frozen(run / 'evidence' / relative, stack)
            if {'sha256': records._hash(snapshot.data), 'identity': records._identity(snapshot)} != item:
                raise FailedArchiveError('unified_failed_archive_original_changed')
        for name, data in copied.items():
            snapshot = transaction._snapshot_while_frozen(run / 'context' / name, stack)
            if snapshot.data != data:
                raise FailedArchiveError('unified_failed_archive_context_changed')
        records._record(run / 'receipt.json', {'schema_version': 1,
            'phase': 'failed_original_archived_witnessed', 'intent_sha256': records._hash(records._json(intent))})
        _verify_run(run, pending=True)
        if withdraw._current({'home': review['home'], 'project': review['project']}) != {
                key: review[key] for key in ('config', 'marker', 'cache', 'entry')}:
            raise FailedArchiveError('unified_failed_archive_native_state_changed')
        if _sources() != review['source_sha256'] or records._present(plan.parent):
            raise FailedArchiveError('unified_failed_archive_final_witness_changed')
        _verify_run(run, pending=True)
        withdraw._commit_completion_fence(fence)
    if archive_status(native)['status'] != 'failed_originals_retained':
        raise FailedArchiveError('unified_failed_archive_receipt_uncertain')
    return {'status': 'failed_original_archived_witnessed', 'original_attempt_status': 'failed_retained',
            'configuration_changed': False, 'cache_changed': False, 'entry_changed': False,
            'model_requests': 0, 'replay_performed': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preview', 'archive', 'status'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--handoff-result', type=Path)
    parser.add_argument('--consumer-source', type=Path)
    parser.add_argument('--recovery-intent', type=Path)
    parser.add_argument('--expected-review-sha256')
    parser.add_argument('--python', type=Path)
    args = parser.parse_args()
    try:
        if (not args.plan.is_absolute() or args.plan.name != 'plan.json'
                or args.plan.parent.name != 'operator-unified-activation'
                or (args.python is not None and args.python.resolve(strict=True)
                    != Path(sys.executable).resolve(strict=True))):
            raise FailedArchiveError('unified_failed_archive_selected_scope_changed')
        extra = (args.handoff_result, args.consumer_source, args.recovery_intent)
        if args.action == 'status':
            if any(extra) or args.expected_review_sha256:
                parser.error('status takes only the selected plan scope')
            value = archive_status(args.plan.parent.parent)
        else:
            if not all(extra) or (args.action == 'preview' and args.expected_review_sha256):
                parser.error('exact failure, historical consumer and recovery evidence required')
            value = (preview(args.plan, *extra) if args.action == 'preview' else
                     archive(args.plan, *extra, args.expected_review_sha256))
        print(json.dumps(value, sort_keys=True))
        return 1 if value['status'] == 'uncertain' else 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, (FailedArchiveError, records.RetireError)) else 'unified_failed_archive_unavailable'
        print(json.dumps({'status': 'unavailable', 'reason': code,
                          'configuration_changed': False, 'cache_changed': False,
                          'entry_changed': False, 'model_requests': 0}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
