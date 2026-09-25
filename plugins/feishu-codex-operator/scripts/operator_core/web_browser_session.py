"""One owned hidden browser with explicit, request-free human assistance.

Lifecycle design reference (independent Python implementation): WebCodex
01dc7d31d567aa0300bc246ac7f4a2db590bdbe2, desktop_shell.rs and
process/supervisor.rs. Visibility is separate from owned process lifetime;
Verified pre-dispatch assistance and a locally cancelled, visibly idle turn may
retain that process. Neither retention can resume or replay its consumed input.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
import re
import secrets
import subprocess

from .web_browser_driver import (child_environment, desktop_session_state, safe_effort_diagnostic, safe_effort_range_diagnostic, safe_generation_progress, safe_model_network, safe_user_binding_diagnostic,
    rejected_http_status, rejected_network_error, safe_public_interruption, public_interruption_code, rejected_ui_code, public_final_timeout)
from .web_mcp_transport import WebRequestCapacityError, WebBrowserAssistanceRequired, WebDesktopUnavailable, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout, require
from .responses_tool_adapter import loads
from .web_model_catalog import matches_selection


ASSISTANCE_CLOSE_FIELDS = {
    'phase': {'before', 'after_restore'},
    'route': {'temporary', 'home', 'other'},
    'pageKind': {'chatgpt', 'challenge', 'other', 'unknown'},
    'composer': {'yes', 'no', 'unknown'},
    'modelControl': {'zero', 'one', 'multiple', 'unknown'},
    'loginVisible': {'yes', 'no', 'unknown'},
    'userRows': {'zero', 'nonzero', 'unknown'},
    'assistantRows': {'zero', 'nonzero', 'unknown'},
    'composerEmpty': {'yes', 'no', 'unchecked'},
}
STARTUP_PREPARE_FIELDS = {key: ASSISTANCE_CLOSE_FIELDS[key] for key in (
    'route', 'pageKind', 'composer', 'modelControl', 'loginVisible',
    'userRows', 'assistantRows')}
STARTUP_STRUCTURE_FIELDS = {
    'readyState': {'loading', 'interactive', 'complete', 'unknown'},
    'legacyEditorCount': {'zero', 'one', 'multiple'},
    'legacyEditorEditable': {'yes', 'no', 'unknown'},
    'legacyEditorRect': {'yes', 'no', 'unknown'},
    'testIdEditorVisible': {'zero', 'one', 'multiple'},
    'roleTextboxEditableVisible': {'zero', 'one', 'multiple'},
    'editableVisible': {'zero', 'one', 'multiple'},
    'textareaVisible': {'zero', 'one', 'multiple'},
    'globalModelTotal': {'zero', 'one', 'multiple'},
    'globalModelVisible': {'zero', 'one', 'multiple'},
    'editorFormExists': {'yes', 'no', 'unknown'},
    'accessibleModelCount': {'zero', 'one', 'multiple', 'unknown'},
    'accessibleModelSource': {'aria_label', 'title', 'exact_text', 'multiple', 'unknown'},
    'accessibleModelTag': {'button', 'other', 'unknown'},
    'accessibleModelInEditorForm': {'yes', 'no', 'unknown'},
    'accessibleModelHaspopup': {'menu', 'absent', 'other', 'unknown'},
    'accessibleModelDisabled': {'yes', 'no', 'unknown'},
}
ASSISTANCE_FAILURE_CODES = {
    'web_assistance_closed_before_ready', 'web_worker_assistance_identity_invalid',
    'web_worker_request_during_assistance', 'web_page_state_timeout',
    'web_expected_origin_required', 'web_browser_operation_failed',
    'web_assistance_timeout', 'web_cancelled_no_retry',
    'web_new_chat_previous_page_changed', 'web_inspection_page_changed',
    'web_assistance_navigation_not_allowed', 'web_empty_composer_required',
    'web_composer_missing',
}


async def wait_owned_future(future, timeout):
    # Cancellation leaves the worker-owned future for cleanup to consume.
    # Python 3.14's shield logs later inner exceptions after waiter cancellation,
    # even when the owning cleanup subsequently retrieves those exceptions.
    done, _ = await asyncio.wait((future,), timeout=timeout)
    if not done:
        raise asyncio.TimeoutError
    return future.result()


class WebBrowserSession:
    def __init__(self, driver, *, startup_assistance=False, startup_prepare=False):
        require(driver.window_mode == 'background', 'web_session_background_required')
        require(type(startup_assistance) is bool and type(startup_prepare) is bool
            and not (startup_assistance and startup_prepare), 'web_startup_assistance_invalid')
        self.base, self.config = driver, driver.config
        self.folder = driver.work / 'session'
        self.folder.mkdir(mode=0o700)
        self.child = None
        self.readers = []
        self.current = None
        self.ready = None
        self.prepared = None
        self.closed = False
        self.launches = 0
        self.startup_assistance = startup_assistance
        self.startup_prepare = startup_prepare
        self.startup_failure_recorded = False
        self.startup_prepare_state_recorded = False
        self.startup_structure_recorded = False
        self.assistance_state = 'pending' if startup_assistance else 'preparing' if startup_prepare else 'not_requested'
        self.assistance = None
        self.assistance_reason = None
        self.retained_completed_page = False
        self._close_task = None

    def status(self):
        running = self.child is not None and self.child.returncode is None
        assistance_pending = self.assistance_state in ('pending', 'opening', 'awaiting_user', 'required')
        if self.closed or self.child is not None and not running:
            readiness = 'unavailable'
        elif assistance_pending:
            readiness = 'assistance_required'
        elif self.startup_prepare and (self.prepared is None or not self.prepared.done()):
            readiness = 'preparing'
        elif self.base.active:
            readiness = 'busy'
        elif self.child is None:
            readiness = 'not_started'
        elif self.ready is None or not self.ready.done():
            readiness = 'starting'
        else:
            readiness = 'ready'
        return {**self.base.status(), 'browser_lifecycle': 'session_v1',
            'process_launches': self.launches,
            'process_running': running, 'readiness': readiness,
            'needs_assistance': assistance_pending and not self.closed,
            'session_closed': self.closed, 'assistance_state': self.assistance_state,
            'inspection_available': self.retained_completed_page and readiness == 'ready'}

    def packet(self, name, value):
        target = self.folder / name
        require(not target.exists() and not target.is_symlink(), 'web_session_packet_already_exists')
        pending = target.with_suffix('.pending')
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        require(len(raw) <= 1024 * 1024, 'web_session_packet_too_large')
        with pending.open('xb') as stream:
            stream.write(raw)
        os.replace(pending, target)

    def record_startup_failure(self, value=None, *, fallback_stage='unknown'):
        if (not self.startup_prepare or self.prepared is None or self.prepared.done()
                or self.current is not None or self.startup_failure_recorded):
            return
        stage, code = fallback_stage, 'web_session_worker_failed_no_retry'
        if (isinstance(value, dict)
                and set(value) == {'operator_web', 'kind', 'stage', 'sent', 'error'}
                and value.get('stage') in ('configuration', 'startup_prepare')
                and value.get('sent') is False):
            stage = value['stage']
            error = value.get('error')
            if isinstance(error, str) and error in self.base.codes:
                code = error
        self.base.events.append({'kind': 'startup_failed', 'stage': stage, 'code': code})
        self.startup_failure_recorded = True

    def fail(self, code='web_session_worker_failed_no_retry'):
        if not self.closed:
            self.record_startup_failure()
        self.closed = True
        if self.assistance is not None or self.assistance_state in ('opening', 'awaiting_user'):
            self.assistance_state = 'failed'
        for future in (self.ready, self.prepared, None if self.current is None else self.current['future'],
                None if self.assistance is None else self.assistance['future']):
            if future is not None and not future.done():
                future.set_exception(ValueError(code))
        # A malformed/failed idle worker must not remain orphaned until the
        # service lifetime expires. This closes only the already owned child;
        # it never starts a replacement or replays an input.
        self.begin_close()

    def check_environment(self):
        state = desktop_session_state()
        if state in ('locked', 'disconnected'): raise WebDesktopUnavailable(state)
        require(all(hashlib.sha256(p.read_bytes()).digest() == digest for p, digest in self.base.bound.items()),
            'web_browser_source_changed')

    async def prepare_assistance(self):
        require(self.startup_assistance and self.launches == 0, 'web_startup_assistance_invalid')
        require(not self.base.active and self.current is None and self.assistance is None,
            'web_assistance_requires_idle_session')
        self.check_environment()
        try:
            await self.start(assistance=True)
        except BaseException:
            await self.close()
            raise

    async def prepare_hidden(self):
        """Observe one empty public page without admitting or sending model input."""
        require(self.startup_prepare and self.launches == 0 and self.current is None,
            'web_startup_prepare_invalid')
        self.check_environment()
        try:
            await self.start()
            await wait_owned_future(self.prepared, 80)
        except BaseException as error:
            if isinstance(error, Exception) and not self.closed:
                self.record_startup_failure(fallback_stage='launch' if self.child is None
                    else 'startup_wait')
            await self.close()
            raise

    async def assist(self, assistance_id, *, inspect_completed=False):
        """Open only the existing idle worker, or its one explicit first launch.

        The caller owns the service-instance admission check. Reserving the
        assistance state before the first await also fences concurrent turns.
        A failed request is never retained as input for this operation.
        """
        require(isinstance(assistance_id, str) and re.fullmatch(r'[a-f0-9]{32}', assistance_id),
            'web_assistance_identity_invalid')
        require(not self.closed and not self.base.active and self.current is None
            and self.assistance is None and self.assistance_state not in ('pending', 'opening', 'awaiting_user'),
            'web_assistance_requires_idle_session')
        require(type(inspect_completed) is bool, 'web_inspection_mode_invalid')
        require(not inspect_completed or self.status()['inspection_available'],
            'web_inspection_completed_page_required')
        self.check_environment()
        future = asyncio.get_running_loop().create_future()
        self.assistance = {'id': assistance_id, 'future': future,
            'inspect_completed': inspect_completed, 'close_checks': 0}
        self.assistance_state = 'opening'
        try:
            await self.start()
            self.packet('assist.json', {'id': assistance_id,
                **({'inspect_completed': True} if inspect_completed else {})})
            await wait_owned_future(future, 610)
        except BaseException:
            self.assistance_state = 'failed'
            await self.close()
            raise
        finally:
            self.assistance = None

    async def start(self, *, assistance=False):
        require(not self.closed, 'web_session_closed_new_service_required')
        if self.child is not None:
            require(self.child.returncode is None, 'web_session_worker_exited_no_retry')
            await wait_owned_future(self.ready, 20)
            return
        require(self.launches == 0, 'web_session_worker_restart_forbidden')
        require(assistance == self.startup_assistance, 'web_startup_assistance_invalid')
        self.launches += 1
        config = {**self.config, 'mode': 'worker', 'workerDirectory': str(self.folder), 'parentPid': os.getpid()}
        if assistance:
            config['startupAssistance'] = True
            self.assistance_state = 'opening'
        if self.startup_prepare:
            config['startupPrepare'] = True
        self.packet('config.json', config)
        self.ready = asyncio.get_running_loop().create_future()
        if self.startup_prepare:
            self.prepared = asyncio.get_running_loop().create_future()
        self.child = await asyncio.create_subprocess_exec(str(self.base.electron), str(self.base.host),
            str(self.folder / 'config.json'), cwd=self.folder, env=child_environment(),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, limit=17 * 1024 * 1024)
        self.readers = [asyncio.create_task(self.stdout()), asyncio.create_task(self.stderr())]
        await wait_owned_future(self.ready, 610 if assistance else 20)

    def event(self, value, current):
        kind = value.get('kind')
        if kind not in ('model_verified', 'dispatch_started', 'public_user_binding', 'window_state', 'generation_state', 'public_interruption_state', 'fresh_chat_navigation', 'model_network_state',
                'completed', 'failed', 'cancel_requested', 'cancel_click_attempted', 'cancel_click_unavailable',
                'cancel_idle_unverified', 'effort_initial_state', 'effort_step_verified',
                'effort_step_unavailable', 'effort_pro_unavailable', 'effort_pro_verified', 'effort_target_verified',
                'effort_range_unavailable'):
            return
        event = {'attempt': self.base.attempts, 'kind': kind,
            'stage': value.get('stage') if value.get('stage') in self.base.stages else 'other',
            'code': value.get('error') if isinstance(value.get('error'), str) and value['error'] in self.base.codes else None}
        if kind == 'model_verified':
            require(matches_selection(value, current['selection']), 'web_browser_selection_identity_invalid')
            event.update(**current['selection'], effortIndex=value['effortIndex'])
        elif kind == 'effort_range_unavailable':
            event.update(safe_effort_range_diagnostic(value))
        elif kind.startswith('effort_'):
            event.update(safe_effort_diagnostic(value))
        elif kind == 'window_state':
            require(all(type(value.get(k)) is bool for k in ('visible', 'focused', 'backgroundInput'))
                and all(type(value.get(k)) is int and 0 <= value[k] <= 10000 for k in ('shown', 'focusedEvents'))
                and value.get('inputMode') == 'dom_v1', 'web_window_state_invalid')
            window = {k: value[k] for k in ('visible', 'focused', 'backgroundInput', 'shown', 'focusedEvents', 'inputMode')}
            current['windows'].append(window)
            event.update(window)
        elif kind == 'public_interruption_state':
            require(current['dispatches'] == 1 and value.get('sent') is True
                and value.get('stage') == 'wait_public_final' and current['terminal'] is None,
                'web_browser_ui_failure_unbound')
            current['interruption'] = safe_public_interruption(value.get('state'))
            event['state'] = current['interruption']
        elif kind == 'generation_state':
            event['progress'] = safe_generation_progress(value.get('progress'))
        elif kind == 'fresh_chat_navigation':
            require(value.get('mode') == 'ui_new_chat_v1' and value.get('temporary') is True
                and all(type(value.get(k)) is int and value[k] == 0 for k in ('userRows', 'assistantRows')),
                'web_fresh_chat_state_invalid')
            event.update(mode='ui_new_chat_v1', temporary=True, userRows=0, assistantRows=0)
        elif kind == 'model_network_state':
            network = safe_model_network(value)
            event.update(network)
            if network['phase'] == 'response_started' and type(network['status']) is int and network['status'] >= 400:
                require(current['dispatches'] == 1, 'web_model_http_failure_unbound')
                current['http_statuses'].append(network['status'])
            if network['phase'] == 'error' and network['networkError'] in WebBrowserNetworkError.codes:
                require(current['dispatches'] == 1 and current['terminal'] is None, 'web_model_network_failure_unbound')
                current['network_errors'].append(network['networkError'])
        elif kind == 'public_user_binding' and isinstance(value.get('shape'), dict):
            event['shape'] = safe_user_binding_diagnostic(value['shape'])
        elif kind == 'completed' and isinstance(value.get('publicMessage'), dict):
            refs = value['publicMessage'].get('public_references')
            if isinstance(refs, list) and len(refs) <= 128:
                event['public_reference_count'] = len(refs)
        self.base.events.append(event)

    async def stdout(self):
        total = 0
        try:
            while line := await self.child.stdout.readline():
                total += len(line)
                require(total <= 64 * 1024 * 1024 and len(line) <= 16 * 1024 * 1024, 'web_browser_output_bound')
                if line in (b'\n', b'\r\n'): continue
                value = loads(line)
                require(isinstance(value, dict) and value.get('operator_web') == 1, 'web_browser_record_invalid')
                kind, request_id = value.get('kind'), value.get('requestId')
                if request_id is None:
                    if kind in ('assistance_opened', 'assistance_hidden', 'assistance_failed'):
                        self.assistance_event(value)
                    elif kind == 'assistance_close_state':
                        self.assistance_close_event(value)
                    elif kind == 'worker_ready':
                        require(not self.ready.done() and (not self.startup_assistance
                            or self.assistance_state == 'background'), 'web_session_duplicate_ready')
                        if self.startup_prepare:
                            self.base.events.append({'kind': 'startup_worker_ready'})
                        self.ready.set_result(True)
                    elif kind == 'startup_prepare_state':
                        self.startup_prepare_state_event(value)
                    elif kind == 'startup_control_structure':
                        self.startup_control_structure_event(value)
                    elif kind in ('worker_prepared', 'worker_attention_required'):
                        require(self.startup_prepare and self.ready is not None and self.ready.done()
                            and self.prepared is not None and not self.prepared.done()
                            and self.current is None and self.assistance is None,
                            'web_startup_prepare_sequence_invalid')
                        if kind == 'worker_prepared':
                            require(value.get('hidden') is True and value.get('empty') is True,
                                'web_startup_prepare_unverified')
                            self.assistance_state = 'background'
                            self.prepared.set_result(True)
                        else:
                            reason = value.get('reason')
                            require(reason in ('web_browser_login_required_before_dispatch',
                                'web_browser_challenge_required_before_dispatch'),
                                'web_startup_prepare_reason_invalid')
                            self.assistance_state = 'required'
                            self.assistance_reason = reason
                            self.prepared.set_result(False)
                    elif kind == 'failed':
                        self.record_startup_failure(value)
                        self.fail()
                    continue
                current = self.current
                require(current is not None and current['id'] == request_id, 'web_session_response_identity_changed')
                current['records'] += 1
                require(current['records'] <= 256, 'web_browser_output_bound')
                self.event(value, current)
                if kind == 'dispatch_started':
                    current['dispatches'] += 1
                    self.base.dispatches += 1
                    require(current['dispatches'] == 1, 'web_browser_duplicate_dispatch')
                if kind in ('completed', 'failed'):
                    require(current['terminal'] is None and not current['future'].done(), 'web_session_duplicate_terminal')
                    if kind == 'completed':
                        require(current['dispatches'] == 1 and matches_selection(value, current['selection'])
                            and isinstance(value.get('publicMessage'), dict)
                            and not current['http_statuses'] and not current['network_errors'] and public_interruption_code(current.get('interruption')) is None,
                            'web_browser_final_identity_invalid')
                        require(current['windows'] == [{'visible': False, 'focused': False, 'backgroundInput': True,
                            'shown': 0, 'focusedEvents': 0, 'inputMode': 'dom_v1'}], 'web_background_window_not_verified')
                    elif value.get('error') == 'web_model_http_rejected_no_retry':
                        require(current['dispatches'] == 1, 'web_model_http_failure_unbound')
                        rejected_http_status(value, current['http_statuses'])
                    elif value.get('error') == 'web_model_network_interrupted_no_retry':
                        require(current['dispatches'] == 1, 'web_model_network_failure_unbound')
                        rejected_network_error(value, current['network_errors'])
                    elif value.get('error') in WebBrowserUiError.codes:
                        require(current['dispatches'] == 1, 'web_browser_ui_failure_unbound')
                        rejected_ui_code(value, current.get('interruption'))
                    current['terminal'] = value
                if kind == 'worker_idle':
                    require(current['terminal'] is not None and not current['future'].done()
                        and type(value.get('resultCode')) is int
                        and value['resultCode'] == (0 if current['terminal']['kind'] == 'completed' else 1),
                        'web_session_terminal_not_sealed')
                    assistance_required = value.get('assistanceRequired', False)
                    require(type(assistance_required) is bool and (not assistance_required
                        or self.recoverable_assistance(current)), 'web_assistance_failure_unbound')
                    current['assistance_required'] = assistance_required
                    cancelled_idle = value.get('cancelledIdleVerified', False)
                    require(type(cancelled_idle) is bool and (not cancelled_idle
                        or current.get('client_cancel_requested') is True and not assistance_required
                        and current['terminal'].get('error') == 'web_cancelled_no_retry'
                        and current['terminal'].get('sent') is True and current['dispatches'] == 1
                        and not current['http_statuses'] and not current['network_errors']
                        and public_interruption_code(current.get('interruption')) is None
                        and current['windows'] == [{'visible': False, 'focused': False, 'backgroundInput': True,
                            'shown': 0, 'focusedEvents': 0, 'inputMode': 'dom_v1'}]),
                        'web_session_cancel_idle_unbound')
                    current['cancelled_idle'] = cancelled_idle
                    if cancelled_idle:
                        self.base.events.append({'attempt': self.base.attempts, 'kind': 'cancel_idle_verified'})
                    self.retained_completed_page = current['terminal']['kind'] == 'completed'
                    current['future'].set_result(current['terminal'])
            self.fail()
        except Exception:
            self.fail()

    async def stderr(self):
        total = 0
        try:
            while chunk := await self.child.stderr.read(65536):
                total += len(chunk)
                require(total <= 1024 * 1024, 'web_browser_stderr_bound')
        except Exception:
            self.fail()

    def assistance_event(self, value):
        kind = value['kind']
        pending = self.assistance
        if pending is None:
            require(self.startup_assistance and self.ready is not None and not self.ready.done()
                and value.get('assistanceId') is None, 'web_startup_assistance_invalid')
        else:
            require(value.get('assistanceId') == pending['id'] and not pending['future'].done(),
                'web_assistance_identity_changed')
        require(self.current is None, 'web_assistance_requires_idle_session')
        inspecting = pending is not None and pending.get('inspect_completed') is True
        require(value.get('inspectCompleted', False) is inspecting, 'web_inspection_mode_changed')
        if kind == 'assistance_opened':
            require(self.assistance_state == 'opening', 'web_assistance_sequence_invalid')
            self.assistance_state = 'awaiting_user'
        elif kind == 'assistance_hidden':
            require(self.assistance_state == 'awaiting_user' and value.get('visible') is False
                and value.get('focused') is False and value.get('userClosed') is True,
                'web_assistance_hidden_not_verified')
            require(not inspecting or value.get('pagePreserved') is True, 'web_inspection_page_not_preserved')
            if not inspecting:
                self.retained_completed_page = False
            self.assistance_state = 'background'
            self.assistance_reason = None
            if pending is not None:
                pending['future'].set_result(True)
        else:
            require(self.assistance_state in ('opening', 'awaiting_user'), 'web_assistance_sequence_invalid')
            self.fail('web_assistance_failed_no_retry')
        event = {'kind': kind, 'assistance_state': self.assistance_state}
        if kind == 'assistance_failed':
            code = value.get('error')
            event['code'] = code if isinstance(code, str) and code in ASSISTANCE_FAILURE_CODES else 'other'
        self.base.events.append(event)

    def startup_prepare_state_event(self, value):
        require(self.startup_prepare and self.ready is not None and self.ready.done()
            and self.prepared is not None and not self.prepared.done()
            and self.current is None and not self.closed and not self.startup_prepare_state_recorded
            and value.get('stage') == 'startup_prepare' and value.get('sent') is False,
            'web_startup_prepare_diagnostic_unbound')
        expected = {'operator_web', 'kind', 'stage', 'sent', *STARTUP_PREPARE_FIELDS}
        require(set(value) == expected and all(value.get(key) in allowed
            for key, allowed in STARTUP_PREPARE_FIELDS.items()),
            'web_startup_prepare_diagnostic_invalid')
        self.startup_prepare_state_recorded = True
        self.base.events.append({'kind': 'startup_prepare_state',
            **{key: value[key] for key in STARTUP_PREPARE_FIELDS}})

    def startup_control_structure_event(self, value):
        require(self.startup_prepare_state_recorded and not self.startup_structure_recorded
            and self.prepared is not None and not self.prepared.done()
            and self.current is None and not self.closed
            and value.get('stage') == 'startup_prepare' and value.get('sent') is False,
            'web_startup_structure_diagnostic_unbound')
        expected = {'operator_web', 'kind', 'stage', 'sent', *STARTUP_STRUCTURE_FIELDS}
        require(set(value) == expected and all(value.get(key) in allowed
            for key, allowed in STARTUP_STRUCTURE_FIELDS.items()),
            'web_startup_structure_diagnostic_invalid')
        self.startup_structure_recorded = True
        self.base.events.append({'kind': 'startup_control_structure',
            **{key: value[key] for key in STARTUP_STRUCTURE_FIELDS}})

    def assistance_close_event(self, value):
        pending = self.assistance
        require(pending is not None and self.assistance_state == 'awaiting_user'
            and self.current is None and value.get('assistanceId') == pending['id']
            and pending.get('inspect_completed') is False
            and value.get('stage') == 'worker_assistance' and value.get('sent') is False,
            'web_assistance_diagnostic_unbound')
        expected = {'operator_web', 'kind', 'stage', 'sent', 'assistanceId',
            *ASSISTANCE_CLOSE_FIELDS}
        require(set(value) == expected and all(value.get(key) in allowed
            for key, allowed in ASSISTANCE_CLOSE_FIELDS.items()),
            'web_assistance_diagnostic_invalid')
        phase = value['phase']
        require((phase == 'before' and pending['close_checks'] == 0)
            or (phase == 'after_restore' and pending['close_checks'] == 1),
            'web_assistance_diagnostic_sequence_invalid')
        pending['close_checks'] += 1
        self.base.events.append({'kind': 'assistance_close_state',
            **{key: value[key] for key in ASSISTANCE_CLOSE_FIELDS}})

    @staticmethod
    def recoverable_assistance(current):
        result = current['terminal']
        return (result is not None and result.get('kind') == 'failed' and current['dispatches'] == 0
            and result.get('sent') is False and result.get('stage') == 'load_fresh_page'
            and result.get('error') in ('web_browser_login_required_before_dispatch',
                'web_browser_challenge_required_before_dispatch'))

    async def __call__(self, turn):
        if self.startup_prepare and (self.prepared is None or not self.prepared.done()):
            raise WebBrowserAssistanceRequired('web_browser_preparing_before_dispatch')
        if self.assistance_state in ('pending', 'opening', 'awaiting_user'):
            raise WebBrowserAssistanceRequired('web_browser_assistance_pending_before_dispatch')
        if self.assistance_state == 'required':
            raise WebBrowserAssistanceRequired(self.assistance_reason)
        require(not self.base.active and not self.closed, 'web_session_not_available')
        self.base.active = True
        previous_completed_page = self.retained_completed_page
        self.retained_completed_page = False
        self.base.attempts += 1
        succeeded = False
        retained_for_assistance = False
        retained_after_cancel = False
        retained_after_preflight = False
        try:
            self.check_environment()
            request = self.base.request_config(turn)
            await self.start()
            future = asyncio.get_running_loop().create_future()
            current = self.current = {'id': secrets.token_hex(16), 'future': future,
                'selection': {key: request[key] for key in ('model', 'effort')},
                'dispatches': 0, 'windows': [], 'records': 0, 'terminal': None, 'http_statuses': [], 'network_errors': []}
            self.packet('next.json', {'id': current['id'], **request})
            result = await wait_owned_future(future, self.config['timeoutMs'] / 1000 + 12)
            if result['kind'] == 'failed':
                if result.get('error') == 'web_model_http_rejected_no_retry':
                    raise WebBrowserHttpError(rejected_http_status(result, current['http_statuses']))
                if result.get('error') == 'web_model_network_interrupted_no_retry':
                    raise WebBrowserNetworkError(rejected_network_error(result, current['network_errors']))
                if result.get('error') in WebBrowserUiError.codes:
                    raise WebBrowserUiError(rejected_ui_code(result, current.get('interruption')))
                if public_final_timeout(result):
                    require(current['dispatches'] == 1 and not current['http_statuses'] and not current['network_errors']
                        and public_interruption_code(current.get('interruption')) is None,
                        'web_browser_final_timeout_unbound')
                    raise WebBrowserFinalTimeout()
                if self.recoverable_assistance(current):
                    retained_for_assistance = (current.get('assistance_required') is True
                        and not self.closed and self.child.returncode is None)
                    if retained_for_assistance:
                        self.assistance_state = 'required'
                        self.assistance_reason = result['error']
                    raise WebBrowserAssistanceRequired(result['error'])
                raise ValueError('web_session_generation_failed_no_retry')
            self.base.completed += 1
            succeeded = True
            return deepcopy(result['publicMessage'])
        except asyncio.CancelledError:
            self.base.cancelled += 1
            # Only the caller's cancellation may retain the existing worker.
            # Driver deadlines, service shutdown and failed protocol continuations
            # also cancel this coroutine, but never select this reuse contract.
            if turn.client_cancelled and not self.closed and self.current is not None:
                cleanup = asyncio.create_task(self.cancel_to_idle())
                try:
                    retained_after_cancel = await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    retained_after_cancel = await cleanup
            raise
        except WebRequestCapacityError:
            # Capacity is checked synchronously before start()/next.json. Keep
            # the existing idle process and completed-page inspection state;
            # the rejected native turn stays consumed and is never replayed.
            require(self.current is None, 'web_capacity_failure_after_dispatch')
            retained_after_preflight = True
            self.retained_completed_page = previous_completed_page
            self.base.failed += 1
            self.base.events.append({'attempt': self.base.attempts, 'kind': 'request_preflight_rejected',
                'code': 'web_mcp_request_capacity_exceeded_before_dispatch'})
            raise
        except Exception as error:
            self.base.failed += 1
            self.base.events.append({'attempt': self.base.attempts, 'kind': 'driver_failed',
                'code': str(error) if isinstance(error, (WebDesktopUnavailable, WebBrowserAssistanceRequired, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout)) else 'rejected'})
            raise
        finally:
            if not succeeded and not retained_for_assistance and not retained_after_cancel and not retained_after_preflight:
                cleanup = asyncio.create_task(self.close())
                try: await asyncio.shield(cleanup)
                except asyncio.CancelledError: await cleanup
            self.current = None
            self.base.active = False

    async def cancel_to_idle(self):
        current = self.current
        if current is None or current['future'].done() or self.closed:
            return False
        try:
            current['client_cancel_requested'] = True
            self.packet('cancel.json', {'id': current['id'], 'reuse_when_idle': True})
            await wait_owned_future(current['future'], 7)
            return (current.get('cancelled_idle') is True and not self.closed
                and self.child is not None and self.child.returncode is None)
        except Exception:
            return False

    async def close(self):
        # stop, client cancellation and assistance failure can race. One task
        # owns child termination, reader joins and private packet cleanup.
        await asyncio.shield(self.begin_close())

    def begin_close(self):
        self.closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return self._close_task

    async def _close(self):
        current = self.current
        assistance_future = None if self.assistance is None else self.assistance['future']
        if assistance_future is not None and not assistance_future.done():
            assistance_future.set_exception(ValueError('web_assistance_stopped_no_retry'))
        if self.child is not None and self.child.returncode is None:
            if current is not None and not current['future'].done():
                if not (self.folder / 'cancel.json').exists():
                    self.packet('cancel.json', {'id': current['id']})
                try: await wait_owned_future(current['future'], 7)
                except (Exception, asyncio.CancelledError): pass
            if not (self.folder / 'shutdown.json').exists(): self.packet('shutdown.json', {'stop': True})
            try: await asyncio.wait_for(self.child.wait(), 8)
            except asyncio.TimeoutError:
                self.child.terminate()
                await asyncio.wait_for(self.child.wait(), 5)
        for reader in self.readers:
            if not reader.done(): reader.cancel()
        await asyncio.gather(*self.readers, return_exceptions=True)
        for future in (self.ready, self.prepared, None if current is None else current['future'], assistance_future):
            if future is not None and future.done() and not future.cancelled(): future.exception()
        if self.folder.exists():
            for name in ('config.json', 'next.json', 'active.json', 'cancel.json', 'shutdown.json',
                    'assist.json', 'assisting.json', 'assist.pending',
                    'config.pending', 'next.pending', 'cancel.pending', 'shutdown.pending'):
                file = self.folder / name
                if file.exists():
                    require(file.is_file() and not file.is_symlink(), 'web_session_cleanup_changed')
                    file.unlink()
            self.folder.rmdir()
