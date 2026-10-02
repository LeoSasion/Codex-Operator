"""Explicit source-pinned workflow renewal after retained failed-plan archival.

Retains the old workflow and reselects only the recovery-bound entry bytes.
Never prepares/arms an activation, starts a service, opens Desktop or replays.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import re
import secrets
import sys

import operator_unified_failed_archive as failed
import operator_unified_retire as records
import operator_unified_withdraw as withdraw
from operator_core import windows_config_transaction as transaction

ROOT = 'operator-unified-workflow-renewal'
RUN = re.compile(r'generation-[a-f0-9]{32}\Z')
SOURCES = (*failed.SOURCE_FILES, 'operator_unified_workflow_renew.py',
           'operator_unified_upgrade.py')
REVIEW_KEYS = {'schema_version', 'project', 'home', 'archive', 'python', 'port',
    'saved_entry', 'directory_identity', 'files', 'context', 'queue',
    'source_sha256', 'config', 'cache', 'marker', 'entry'}


class RenewalError(ValueError):
    """Fixed local maintenance reason."""


def _sources():
    return {name: records._hash(records._read(Path(__file__).parent / name)) for name in SOURCES}


def _verify(run, *, pending=False):
    names = {'intent.json', 'receipt.json', 'evidence', 'context', 'entry-reselection'}
    if pending:
        names.add('completion-pending.json')
    if {path.name for path in run.iterdir()} != names:
        raise RenewalError('unified_workflow_renewal_incomplete')
    intent, raw = records._load(run / 'intent.json', 262144)
    review = intent['review']
    receipt, _ = records._load(run / 'receipt.json')
    if (set(intent) != {'schema_version', 'scope', 'source', 'target', 'review', 'review_sha256'}
            or type(intent['schema_version']) is not int or intent['schema_version'] != 1
            or intent['scope'] != 'failed_archive_workflow_renewal'
            or set(review) != REVIEW_KEYS or type(review['schema_version']) is not int
            or review['schema_version'] != 1 or not Path(review['project']).is_absolute()
            or not Path(review['python']).is_absolute()
            or Path(review['archive']).parent != Path(review['home']) / failed.ROOT
            or type(review['port']) is not int or not 1024 <= review['port'] <= 65535
            or intent['review_sha256'] != records._hash(records._json(review))
            or Path(review['home']) != run.parent.parent or run.parent.name != ROOT
            or RUN.fullmatch(run.name) is None
            or Path(intent['source']) != Path(review['project']) / '.codex/operator-unified-startup'
            or Path(intent['target']) != run / 'evidence'
            or set(review['source_sha256']) != set(SOURCES)
            or any(not isinstance(value, str) or records.HEX64.fullmatch(value) is None
                   for value in review['source_sha256'].values())
            or review['queue'] != {'actionable_inbox': 0, 'open_callbacks': 0}
            or any(type(value) is not int for value in review['queue'].values())
            or set(receipt['new_files']) != {'start-codex-with-web.ps1', 'startup-sync-plan.json'}
            or any(not withdraw._valid_snapshot(item) for item in receipt['new_files'].values())
            or not withdraw._valid_snapshot({'sha256': '0' * 64, 'identity': receipt['new_directory']})
            or receipt['phase'] != 'workflow_renewed_witnessed'
            or type(receipt['schema_version']) is not int or receipt['schema_version'] != 1
            or set(receipt) != {'schema_version', 'phase', 'intent_sha256', 'new_files', 'new_directory'}
            or receipt['intent_sha256'] != records._hash(raw)
            or failed._tree(run / 'evidence') != review['files']
            or failed._directory_identity(run / 'evidence') != review['directory_identity']):
        raise RenewalError('unified_workflow_renewal_changed')
    context = review['context']
    after = {'after--' + name: item['sha256'] for name, item in receipt['new_files'].items()}
    if {path.name for path in (run / 'context').iterdir()} != set(context) | set(after):
        raise RenewalError('unified_workflow_renewal_context_changed')
    for name, digest in {**{name: item['sha256'] for name, item in context.items()}, **after}.items():
        if Path(name).name != name or records._hash(records._read(run / 'context' / name)) != digest:
            raise RenewalError('unified_workflow_renewal_context_changed')
    entry = run / 'entry-reselection'
    if {path.name for path in entry.iterdir()} != {
            'before.json', 'after.json', 'boundary.bak', 'intent.json', 'completed.json'}:
        raise RenewalError('unified_workflow_renewal_entry_uncertain')
    entry_intent, _ = records._load(entry / 'intent.json')
    completed, _ = records._load(entry / 'completed.json')
    before = records._read(entry / 'before.json')
    original = records._read(entry / 'after.json')
    if (completed != {'status': 'entry_reselected', 'routing_changed': False}
            or entry_intent != {'target': str(Path(review['project']) / '.codex/operator-desktop-entry/desktop-entry.json'),
                'before_sha256': records._hash(before), 'after_sha256': records._hash(original),
                'saved_entry': review['saved_entry']}
            or records._hash(original) != review['saved_entry']['configuration_sha256']
            or records._hash(before) != review['entry']['desktop-entry.json']['sha256']
            or records._read(entry / 'boundary.bak') != before
            or withdraw._snapshot(entry / 'boundary.bak') != review['entry']['desktop-entry.json']):
        raise RenewalError('unified_workflow_renewal_entry_uncertain')
    return intent


def status(home, *, pending=None):
    root = home / ROOT
    if not records._present(root):
        return {'status': 'absent', 'generations': 0}
    try:
        records._plain(root)
        runs = list(root.iterdir())
        if not runs or len(runs) > 32:
            raise RenewalError('unified_workflow_renewal_history_bound')
        for run in runs:
            records._plain(run)
            if not run.is_dir() or RUN.fullmatch(run.name) is None:
                raise RenewalError('unified_workflow_renewal_invalid')
            if run != pending:
                _verify(run)
        return {'status': 'workflows_retained', 'generations': len(runs)}
    except Exception:
        return {'status': 'uncertain'}


def retained_workflow(project, home):
    """Locate the exact historical workflow behind one witnessed replacement.

    This read-only compatibility check grants no activation or service authority.
    Current and retained directory/file identities must still match the receipt.
    """
    current = status(home)
    if current['status'] == 'absent':
        return None
    if current['status'] != 'workflows_retained':
        raise RenewalError('unified_workflow_renewal_requires_review')
    bundle = project / '.codex/operator-unified-startup'
    matches = []
    for run in (home / ROOT).iterdir():
        intent = _verify(run)
        if Path(intent['source']) == bundle and Path(intent['review']['project']) == project:
            matches.append((run, intent))
    if len(matches) != 1:
        raise RenewalError('unified_workflow_renewal_scope_changed')
    run, intent = matches[0]
    receipt, _ = records._load(run / 'receipt.json')
    if (failed._tree(bundle) != receipt['new_files']
            or failed._directory_identity(bundle) != receipt['new_directory']
            or failed.archive_status(home)['status'] != 'failed_originals_retained'):
        raise RenewalError('unified_workflow_renewal_current_changed')
    failed._verify_run(Path(intent['review']['archive']))
    # Recheck the complete retained proof after observing the current files.
    if _verify(run) != intent or status(home) != current:
        raise RenewalError('unified_workflow_renewal_current_changed')
    return run / 'evidence'


def _inspect(archive, python, *, reserved=False, pending=None):
    import operator_unified_cold_start as cold
    import operator_unified_entry_preview as entry
    import operator_legacy_runtime_upgrade as cutover
    import operator_web_service as web
    if not archive.is_absolute() or not python.is_absolute():
        raise RenewalError('unified_workflow_renewal_absolute_scope_required')
    original = failed._verify_run(archive)
    saved = original['review']
    home, project = Path(saved['home']), Path(saved['project'])
    if (archive.parent != home / failed.ROOT or failed.RUN.fullmatch(archive.name) is None
            or failed.archive_status(home)['status'] != 'failed_originals_retained'
            or status(home, pending=pending)['status'] == 'uncertain'
            or records._present(home / 'operator-unified-activation')
            or python.resolve(strict=True) != Path(sys.executable).resolve(strict=True)):
        raise RenewalError('unified_workflow_renewal_requires_review')
    if pending is None and status(home).get('generations', 0) >= 32:
        raise RenewalError('unified_workflow_renewal_history_bound')
    if pending is not None and (pending.parent != home / ROOT or RUN.fullmatch(pending.name) is None):
        raise RenewalError('unified_workflow_renewal_scope_changed')
    plan, _ = records._load(archive / 'evidence/plan.json')
    arm, _ = records._load(archive / 'evidence/arm.json')
    bundle = project / '.codex/operator-unified-startup'
    files = failed._tree(bundle)
    if set(files) != {cold.SCRIPT, 'startup-sync-plan.json'}:
        raise RenewalError('unified_workflow_renewal_old_workflow_changed')
    for name, historical in ((cold.SCRIPT, 'workflow.ps1'), ('startup-sync-plan.json', 'workflow-sync.json')):
        if files[name] != {key: saved['context'][historical][key] for key in ('sha256', 'identity')}:
            raise RenewalError('unified_workflow_renewal_old_workflow_changed')
    if records._hash(records._read(python, 16777216)) != arm['python_sha256']:
        raise RenewalError('unified_workflow_renewal_python_changed')
    current = withdraw._current(plan)
    recovery = Path(saved['context']['recovery-intent.json']['path'])
    recovery_value, _ = records._load(recovery)
    row = next(item for item in recovery_value['files'] if item['name'] == 'desktop-entry.json')
    if (records._hash(records._read(recovery)) != saved['context']['recovery-intent.json']['sha256']
            or entry.verify_owned_entry(project, project / '.codex/operator-desktop-entry', recovered_config=row)
                != arm['entry']['ownership_sha256']):
        raise RenewalError('unified_workflow_renewal_entry_changed')
    records._recovery(plan, archive / 'evidence', recovery, False, True)
    if not reserved:
        records._stopped(plan, require_desktop_closed=False)
    elif web.process_identity(plan['router']['process']['pid']) is not None:
        raise RenewalError('unified_workflow_renewal_router_reappeared')
    if records._present(Path(plan['router']['state']) / 'codex-entry.json'):
        raise RenewalError('unified_workflow_renewal_route_active')
    cutover.process_gate(project, Path(__file__).parent.parent)
    queue = cutover.queue_gate(project / cutover.RUNTIME_RELATIVE)
    if web.status(Path(plan['router']['web_profile']))['status'] not in {'stopped', 'configured'}:
        raise RenewalError('unified_workflow_renewal_web_not_stopped')
    context_paths = {'recovery-intent.json': recovery,
        'recovery-completed.json': recovery.parent / 'completed.json',
        'recovery-entry-before.json': recovery.parent / 'desktop-entry.json.before'}
    if any(withdraw._snapshot(path) != {key: saved['context'][name][key] for key in ('sha256', 'identity')}
           for name, path in context_paths.items()):
        raise RenewalError('unified_workflow_renewal_recovery_changed')
    context_paths['failed-intent.json'] = archive / 'intent.json'
    context_paths['failed-receipt.json'] = archive / 'receipt.json'
    context_paths.update({'original--' + name: bundle / name for name in files})
    return {'schema_version': 1, 'project': str(project), 'home': str(home), 'archive': str(archive),
        'python': str(python), 'port': plan['router']['port'], 'saved_entry': arm['entry'],
        'directory_identity': failed._directory_identity(bundle), 'files': files,
        'context': failed._context(context_paths), 'queue': queue, 'source_sha256': _sources(), **current}


def preview(archive, python):
    review = _inspect(archive, python)
    return {'status': 'workflow_renewal_reviewed_preview',
        'review_sha256': records._hash(records._json(review)), 'model_requests': 0}


def renew(archive, python, expected):
    import operator_unified_cold_start as cold
    import operator_unified_upgrade as upgrade
    import operator_model_router as router
    from operator_core.web_browser_driver import private_directory
    review = _inspect(archive, python)
    if expected != records._hash(records._json(review)):
        raise RenewalError('unified_workflow_renewal_review_changed')
    project, home = Path(review['project']), Path(review['home'])
    bundle = project / '.codex/operator-unified-startup'
    root = home / ROOT
    with withdraw._entry_mutex(project), ExitStack() as stack:
        stack.enter_context(transaction._open(home, directory=True))
        # Entry configuration is the sole replacement target. All other native
        # and entry bytes stay frozen; reselect_entry checks its own before/backup.
        for path, item in [(home / 'config.toml', review['config']),
                (home / 'models_cache.json', review['cache']),
                (home / 'operator-native-route-only', review['marker']),
                *((project / '.codex/operator-desktop-entry' / name, item)
                  for name, item in review['entry'].items() if name != 'desktop-entry.json')]:
            if item is None:
                if records._present(path):
                    raise RenewalError('unified_workflow_renewal_native_changed')
            else:
                snapshot = transaction._snapshot_while_frozen(path, stack)
                if withdraw._snapshot(path) != item:
                    raise RenewalError('unified_workflow_renewal_native_changed')
        originals = stack.enter_context(ExitStack())
        captures = {}
        for name, item in review['context'].items():
            path = Path(item['path'])
            snapshot = transaction._snapshot_while_frozen(path,
                originals if path.parent == bundle else stack)
            if withdraw._snapshot(path) != {key: item[key] for key in ('sha256', 'identity')}:
                raise RenewalError('unified_workflow_renewal_context_changed')
            captures[name] = snapshot.data
        moving = stack.enter_context(withdraw._allocation_directory_handle(bundle, moving=True))
        stack.enter_context(router.reserve_inactive_port(review['port']))
        if not records._present(root):
            private_directory(root)
        records._plain(root)
        stack.enter_context(transaction._open(root, directory=True))
        run = root / ('generation-' + secrets.token_hex(16))
        private_directory(run)
        private_directory(run / 'context')
        parent = stack.enter_context(withdraw._allocation_directory_handle(run, parent=True))
        intent = {'schema_version': 1, 'scope': 'failed_archive_workflow_renewal',
            'source': str(bundle), 'target': str(run / 'evidence'), 'review': review,
            'review_sha256': expected}
        records._record(run / 'intent.json', intent)
        for name, data in captures.items():
            transaction._write_new(run / 'context' / name, data)
        fence_raw = records._json({'scope': intent['scope'],
            'intent_sha256': records._hash(records._json(intent))})
        transaction._write_new(run / 'completion-pending.json', fence_raw)
        fence = stack.enter_context(withdraw._completion_fence_handle(run / 'completion-pending.json', fence_raw))
        if _inspect(archive, python, reserved=True, pending=run) != review:
            raise RenewalError('unified_workflow_renewal_review_changed')
        originals.close()  # Required Windows nonempty-directory move boundary.
        failed._rename_handle(moving, parent, run / 'evidence', review['directory_identity'])
        for name in review['files']:
            transaction._snapshot_while_frozen(run / 'evidence' / name, stack)
        if failed._tree(run / 'evidence') != review['files']:
            raise RenewalError('unified_workflow_renewal_original_changed')
        created = cold.create_workflow(project, home, python)
        if created['reused'] is not False:
            raise RenewalError('unified_workflow_renewal_new_workflow_uncertain')
        new_files = failed._tree(bundle)
        for name in new_files:
            snapshot = transaction._snapshot_while_frozen(bundle / name, stack)
            transaction._write_new(run / 'context' / ('after--' + name), snapshot.data)
        # This is a new workflow scope, never a modified historical activation.
        scope = {'project': str(project), 'home': str(home),
                 'startup_bundle': cold.preparation._startup_bundle(project)}
        cold._verify_workflow(scope, python)
        recovery = Path(review['context']['recovery-intent.json']['path'])
        upgrade.reselect_entry(scope, review['saved_entry'], recovery, run)
        transaction._snapshot_while_frozen(project / '.codex/operator-desktop-entry/desktop-entry.json', stack)
        records._record(run / 'receipt.json', {'schema_version': 1, 'phase': 'workflow_renewed_witnessed',
            'intent_sha256': records._hash(records._json(intent)), 'new_files': new_files,
            'new_directory': failed._directory_identity(bundle)})
        for path in [run / 'intent.json', run / 'receipt.json',
                *(run / 'context').iterdir(), *(run / 'entry-reselection').iterdir()]:
            transaction._snapshot_while_frozen(path, stack)
        _verify(run, pending=True)
        current = withdraw._current(scope)
        if (any(current[key] != review[key] for key in ('config', 'cache', 'marker'))
                or any(current['entry'][name] != item for name, item in review['entry'].items()
                       if name != 'desktop-entry.json')
                or cold._selected_entry(scope) != review['saved_entry']
                or _sources() != review['source_sha256']
                or failed._tree(bundle) != new_files
                or records._present(home / 'operator-unified-activation')
                or failed.archive_status(home)['status'] != 'failed_originals_retained'):
            raise RenewalError('unified_workflow_renewal_final_witness_changed')
        _verify(run, pending=True)
        withdraw._commit_completion_fence(fence)
    if status(home)['status'] != 'workflows_retained':
        raise RenewalError('unified_workflow_renewal_receipt_uncertain')
    return {'status': 'workflow_renewed_witnessed', 'configuration_changed': False,
        'cache_changed': False, 'entry_reselected': True, 'routing_activated': False,
        'model_requests': 0}
