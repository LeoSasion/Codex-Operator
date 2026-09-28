"""One owned Electron process per turn; native Codex owns tool execution.

The dated browser host supplies public text only. Native messages remain labelled
JSON data; this does not establish native system/developer role equivalence. The
explicit MCP driver uses a separately owned listener and registered connector.
"""
import asyncio
from collections import deque
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from .responses_capabilities import RouterError
from .responses_tool_adapter import loads
from .web_model_catalog import CATALOG_PATH, browser_selection, matches_selection
from .web_mcp_transport import WebDesktopUnavailable, WebBrowserAssistanceRequired, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout, require


def desktop_session_state():
    """Read only the calling Windows session's lock/connect flags.

    No input, desktop switch or unlock is performed. Only flags are inspected;
    other fields in the native WTS buffer are never projected or persisted.
    Unknown state is not inferred to be locked. Windows 7's reversed flags are
    deliberately outside this Windows 8+ contract.
    """
    if os.name != 'nt' or tuple(sys.getwindowsversion()[:2]) < (6, 2):
        return 'unknown'
    import ctypes
    from ctypes import wintypes as w
    class Level1(ctypes.Structure):
        _fields_ = [('session_id', w.DWORD), ('state', w.DWORD), ('flags', w.LONG),
            ('station', w.WCHAR * 33), ('user', w.WCHAR * 21), ('domain', w.WCHAR * 18),
            ('times', ctypes.c_longlong * 5), ('counts', w.DWORD * 6)]
    class Data(ctypes.Union):
        _fields_ = [('session', Level1)]
    class Info(ctypes.Structure):
        _fields_ = [('level', w.DWORD), ('data', Data)]
    try:
        dll = ctypes.WinDLL('wtsapi32', use_last_error=True)
        dll.WTSQuerySessionInformationW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD)]
        dll.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        pointer, size = ctypes.c_void_p(), w.DWORD()
        if not dll.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25,
                ctypes.byref(pointer), ctypes.byref(size)):
            return 'unknown'
        try:
            if not pointer.value or size.value != ctypes.sizeof(Info):
                return 'unknown'
            value = ctypes.cast(pointer, ctypes.POINTER(Info)).contents
            if value.level != 1:
                return 'unknown'
            if value.data.session.state == 4:  # WTSDisconnected
                return 'disconnected'
            if value.data.session.state != 0:  # WTSActive
                return 'unknown'
            return {0: 'locked', 1: 'unlocked'}.get(value.data.session.flags, 'unknown')
        finally:
            dll.WTSFreeMemory(pointer)
    except (OSError, AttributeError):
        return 'unknown'


def private_directory(path):
    """Create a new private directory before writing any request or credential."""
    path = Path(path)
    require(path.is_absolute() and not path.exists() and not path.is_symlink(),
            'web_private_directory_must_be_new')
    path.mkdir(mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)
        return
    system = Path(os.environ['SystemRoot']) / 'System32'
    identity = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    matches = re.findall(rb'S-1-\d+(?:-\d+)+', identity.stdout)
    require(identity.returncode == 0 and len(matches) == 1, 'web_private_identity_unavailable')
    changed = subprocess.run([str(system / 'icacls.exe'), str(path), '/inheritance:r',
        '/grant:r', '*' + matches[0].decode('ascii') + ':(OI)(CI)F'],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    require(changed.returncode == 0, 'web_private_directory_acl_failed')


def child_environment():
    # The browser uses its own login partition. Native API/connector credentials
    # and Electron debugging switches have no role in this child.
    return {key: value for key, value in os.environ.items()
        if not key.upper().startswith(('CODEX_', 'OPENAI_', 'CHATGPT_', 'ELECTRON_',
            'NODE_', 'OPERATOR_', 'LARK_', 'FEISHU_'))
        and not any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'PROXY'))}


def encoded_user_json(value):
    """Dated pre-dispatch representation; never repair observed public text."""
    source = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    source.encode('utf-8')  # Preserve rejection of invalid Unicode before encoding.

    def encode_string(match):
        # web_text_json_string_v1: JSON strings contain only letters, digits,
        # spaces and Unicode escapes. Literal URLs in the dated Web composer
        # acquire link marks and trigger Markdown serialization of the message.
        # Encode before dispatch, preserving every decoded value; never unescape
        # an observed reply or repair a mismatched submitted user message.
        value = json.loads(match.group())
        return '"' + ''.join(character if character.isascii()
            and (character.isalnum() or character == ' ') else
            '\\u%04x' % ord(character) if ord(character) < 128 else
            json.dumps(character, ensure_ascii=True)[1:-1] for character in value) + '"'

    return re.sub(r'"(?:[^"\\]|\\.)*"', encode_string, source)


def text_prompt(request):
    require(isinstance(request, dict), 'web_text_request_required')
    require(request.get('tool_choice', 'auto') in ('auto', 'none'),
            'web_text_tool_choice_unsupported')
    reasoning = request.get('reasoning')
    require(reasoning is None or isinstance(reasoning, dict)
        and reasoning.get('summary') in (None, 'auto', 'concise', 'detailed'),
        'web_text_reasoning_summary_invalid')
    source = encoded_user_json(request)
    text = ('This is a text-only conversation transport. The complete source request below is labelled JSON data, '
        'including its original messages, instructions and declarations. Answer its final user message using the conversation history. '
        'There is no local tool transport in this session. Do not invent tool results. '
        'BEGIN_COMPLETE_RESPONSES_REQUEST_JSON '
        + source
        + ' END_COMPLETE_RESPONSES_REQUEST_JSON')
    require(len(text.encode('utf-8')) <= 65536, 'web_text_input_too_large_no_retry')
    return text


def current_user_preview(source):
    """An optional exact copy, never extracted text, a new role or a grant.

    Inspect only the final original input item. In particular, do not walk
    backwards past a tool result, use an adapted named-result user message, or
    partially copy multimodal content. Oversized previews stay in the complete
    paged context without truncation or a second request.
    """
    if not isinstance(source, list) or not source:
        return None
    message = source[-1]
    if (not isinstance(message, dict) or message.get('role') != 'user'
            or message.get('type', 'message') != 'message'
            or not set(message) <= {'type', 'role', 'content', 'id', 'status'}):
        return None
    content = message.get('content')
    if not (isinstance(content, str) or isinstance(content, list) and content
            and all(isinstance(part, dict) and set(part) == {'type', 'text'}
                and part.get('type') == 'input_text' and isinstance(part.get('text'), str)
                for part in content)):
        return None
    preview = {'source_input_index': len(source) - 1, 'source_message': deepcopy(message)}
    return preview if len(encoded_user_json(preview).encode('utf8')) <= 16384 else None


def safe_user_binding_diagnostic(shape):
    """Shared bounded observations; never retain source or submitted text."""
    value = {key: shape[key] for key in ('supportedTextShape', 'exact', 'backslashInsertionsOnly', 'appSeparatorOnly')
        if type(shape.get(key)) is bool}
    value.update({key: shape[key] for key in ('sourceLength', 'promptLength', 'firstDifference')
        if type(shape.get(key)) is int and -1 <= shape[key] <= 1024 * 1024})
    return value


def safe_prompt_mismatch_shape(shape):
    """Retain only fixed editor structure categories after a local pre-send rejection."""
    counts = ('paragraphs', 'nodes', 'literalPastes', 'expectedNewlines', 'renderedNewlines')
    kinds = ('nodeKinds', 'literalKinds', 'secondNodeKinds')
    flags = ('innerTextExact', 'textContentExact', 'firstExpectedEndsCR',
        'firstMatchesWithoutCR', 'firstStartsWithPrefix', 'firstPillMatchesName',
        'firstNodeMatchesTailWithSpace', 'firstNodeMatchesTailNoSpace',
        'firstNodeStartsWithSpace', 'firstNodeStartsWithNbsp',
        'firstNodeMatchesTailWithNbsp', 'firstNodeMatchesTailWithTwoSpaces',
        'firstMatchesWithoutSeparator', 'firstMatchesWithNbspSeparator')
    bounded = ('paragraphCount', 'expectedLines')
    if (not isinstance(shape, dict) or set(shape) != set(counts + kinds + flags + bounded + ('lineMatches',))
            or any(shape.get(key) not in ('zero', 'one', 'few', 'many') for key in counts)
            or any(type(shape.get(key)) is not int or not 0 <= shape[key] <= 9 for key in bounded)
            or any(type(shape.get(key)) is not list or len(shape[key]) > 8
                or any(item not in ('text', 'break', 'app_pill', 'literal', 'other') for item in shape[key])
                for key in kinds)
            or type(shape.get('lineMatches')) is not list or len(shape['lineMatches']) > 8
            or any(type(item) is not bool for item in shape['lineMatches'])
            or any(type(shape.get(key)) is not bool for key in flags)):
        return {'valid': False}
    return {'valid': True, **{key: shape[key] for key in counts + kinds + flags + bounded + ('lineMatches',)}}


def safe_modern_identity_shape(shape):
    """Retain only bounded public identity-structure flags after a failed turn."""
    flags = ('keyPattern', 'visible', 'hidden', 'idsBounded', 'allIdsUuid',
        'allIdsEqual', 'selectedUuid', 'selectedFirst', 'selectedLast', 'selectedAny')
    counts = ('idsCount', 'selectedCount')
    if (not isinstance(shape, dict) or set(shape) != {'assistantRows', 'rows'}
            or type(shape['assistantRows']) is not int or not 0 <= shape['assistantRows'] <= 9
            or type(shape['rows']) is not list or len(shape['rows']) > 4
            or any(not isinstance(row, dict) or set(row) != set(flags + counts)
                or any(type(row[key]) is not bool for key in flags)
                or any(type(row[key]) is not int or not 0 <= row[key] <= 9 for key in counts)
                for row in shape['rows'])):
        return {'valid': False}
    return {'valid': True, **shape}


def safe_fresh_chat_control_structure(shape):
    """Keep only fixed selector categories from a failed New chat selection."""
    fields = {
        'legacyLinks': {'zero', 'one', 'multiple'},
        'legacyRootHref': {'yes', 'no', 'unknown'},
        'legacyLabel': {'yes', 'no', 'unknown'},
        'legacyEnabled': {'yes', 'no', 'unknown'},
        'navButtons': {'zero', 'one', 'multiple'},
        'namedButtons': {'zero', 'one', 'multiple'},
        'buttonType': {'button', 'absent', 'other', 'unknown'},
        'buttonDisabled': {'yes', 'no', 'unknown'},
        'buttonAriaDisabled': {'yes', 'no', 'other', 'unknown'},
        'buttonHref': {'present', 'absent', 'unknown'},
        'buttonTarget': {'present', 'absent', 'unknown'},
        'buttonHiddenAncestor': {'yes', 'no', 'unknown'},
    }
    if not isinstance(shape, dict) or set(shape) != set(fields) \
            or any(shape.get(name) not in allowed for name, allowed in fields.items()):
        return {'valid': False}
    return {'valid': True, **{name: shape[name] for name in fields}}


def safe_generation_progress(value):
    counts = ('userRows', 'assistantRows', 'finalRows', 'finishedFinalRows', 'currentFinalRows', 'currentFinishedFinalRows', 'renderedTextLength')
    flags = ('stopPresent', 'stopVisible', 'subscriptionWarning', 'errorAlert')
    require(isinstance(value, dict) and set(value) == set(counts + flags)
        and all(type(value.get(k)) is int and 0 <= value[k] <= (1024 * 1024 if k == 'renderedTextLength' else 10000) for k in counts)
        and all(type(value.get(k)) is bool for k in flags), 'web_generation_state_invalid')
    return {k: value[k] for k in counts + flags}


def safe_effort_diagnostic(value):
    """Retain only bounded, public model-control labels; never page or request text."""
    result = {}
    for name in ('value', 'previous', 'target'):
        if type(value.get(name)) is int and 0 <= value[name] <= 4:
            result[name] = value[name]
    if value.get('label') in ('即时', '中', '高', '极高', 'Instant', 'Medium',
            'High', 'Extra high', 'Pro', 'unrecognized'):
        result['label'] = value['label']
    if value.get('announcedGeneration') in ('5.6', '6'):
        result['announcedGeneration'] = value['announcedGeneration']
    header = value.get('header')
    if isinstance(header, str) and re.fullmatch(r'[A-Za-z0-9. -]{1,32}', header):
        result['header'] = header
    return result


def safe_effort_range_diagnostic(value):
    """A fixed, failure-only slider shape; never preserve page or request text."""
    enums = {
        'containerCount': {'zero', 'one', 'multiple', 'unknown'},
        'newContainerTotal': {'zero', 'one', 'multiple', 'unknown'},
        'newContainerVisible': {'zero', 'one', 'multiple', 'unknown'},
        'sliderCount': {'zero', 'one', 'multiple', 'unknown'},
        'globalSliderTotal': {'zero', 'one', 'multiple', 'unknown'},
        'globalSliderVisible': {'zero', 'one', 'multiple', 'unknown'},
        'statePresent': {'yes', 'no'},
        'locked': {'yes', 'no', 'unknown'},
        'ownerMenuitem': {'yes', 'no', 'unknown'},
        'ownerMenu': {'yes', 'no', 'unknown'},
        'sameMenuAsChooser': {'yes', 'no', 'unknown'},
        'globalSliderRect': {'yes', 'no', 'unknown'},
        'globalSliderHidden': {'yes', 'no', 'unknown'},
        'globalSliderInert': {'yes', 'no', 'unknown'},
        'globalSliderAriaHidden': {'yes', 'no', 'unknown'},
        'globalSliderClosedMenu': {'yes', 'no', 'unknown'},
        'globalSliderInNewContainer': {'yes', 'no', 'unknown'},
        'generationMatches': {'yes', 'no', 'unannounced', 'unknown'},
        'proLabel': {'yes', 'no', 'unknown'},
        'proHeader': {'yes', 'no', 'unknown'},
    }
    result = {}
    for name, allowed in enums.items():
        require(value.get(name) in allowed, 'web_effort_range_diagnostic_invalid')
        result[name] = value[name]
    for name in ('min', 'max', 'now', 'globalMin', 'globalMax', 'globalNow'):
        item = value.get(name)
        require(type(item) is int and 0 <= item <= 9
            or isinstance(item, str) and item in ('absent', 'other', 'unknown'),
            'web_effort_range_diagnostic_invalid')
        result[name] = item
    return result


def safe_model_network(value):
    require(value.get('phase') in ('sent', 'response_started', 'completed', 'error')
        and (value.get('status') is None or type(value['status']) is int and 100 <= value['status'] <= 599)
        and value.get('error') in (None, 'other', 'net::ERR_ABORTED', *WebBrowserNetworkError.codes),
        'web_model_network_state_invalid')
    return {'phase': value['phase'], 'status': value.get('status'), 'networkError': value.get('error')}


def rejected_network_error(value, errors):
    error = value.get('networkError')
    require(value.get('sent') is True and isinstance(error, str)
        and error in WebBrowserNetworkError.codes and error in errors,
        'web_model_network_failure_unbound')
    return error


def safe_public_interruption(value):
    counts = ('approvalCards', 'connectorDialogs')
    flags = ('sessionExpired', 'subscriptionUnavailable', 'responseError')
    require(isinstance(value, dict) and set(value) == set(counts + flags)
        and all(type(value.get(k)) is int and 0 <= value[k] <= (16 if k == 'connectorDialogs' else 10000) for k in counts)
        and all(type(value.get(k)) is bool for k in flags), 'web_public_interruption_state_invalid')
    return {k: value[k] for k in counts + flags}


def public_interruption_code(state):
    if state is None: return None
    if state['sessionExpired']: return 'web_session_expired_during_generation_no_retry'
    if state['approvalCards'] or state['connectorDialogs']: return 'web_tool_confirmation_required_no_retry'
    if state['subscriptionUnavailable']: return 'web_subscription_unavailable_during_generation_no_retry'
    if state['responseError']: return 'web_response_error_no_retry'
    return None


def rejected_ui_code(value, state):
    code = value.get('error')
    require(value.get('sent') is True and value.get('stage') == 'wait_public_final'
        and code in WebBrowserUiError.codes and code == public_interruption_code(state),
        'web_browser_ui_failure_unbound')
    return code


def public_final_timeout(value):
    return (value.get('kind') == 'failed' and value.get('sent') is True
        and value.get('stage') == 'wait_public_final'
        and value.get('error') == 'web_page_state_timeout')


def rejected_http_status(value, statuses):
    status = value.get('upstreamStatus')
    require(value.get('sent') is True and type(status) is int and 400 <= status <= 599 and status in statuses,
        'web_model_http_failure_unbound')
    return status


class WebTextBrowserDriver:
    MAX_TIMEOUT_MS = 180000

    def __init__(self, settings, work):
        require(isinstance(settings, dict) and set(settings) <= {
            'electron', 'profile_directory', 'session_partition', 'proxy_rules', 'timeout_ms', 'software_rendering', 'citation_mode', 'window_mode'},
            'web_browser_settings_invalid')
        require({'electron', 'profile_directory', 'session_partition'} <= set(settings),
                'web_browser_settings_required')
        self.electron = Path(settings['electron'])
        profile = Path(settings['profile_directory'])
        require(self.electron.is_absolute() and self.electron.is_file()
            and not self.electron.is_symlink(), 'web_electron_file_required')
        require(profile.is_absolute() and profile.is_dir() and not profile.is_symlink(),
                'web_existing_profile_required')
        require(isinstance(settings['session_partition'], str) and re.fullmatch(
            r'persist:[a-z0-9-]{1,96}', settings['session_partition']), 'web_partition_required')
        timeout = settings.get('timeout_ms', 120000)
        require(type(timeout) is int and 10000 <= timeout <= self.MAX_TIMEOUT_MS, 'web_timeout_invalid')
        self.window_mode = settings.get('window_mode', 'background')
        require(self.window_mode in ('background', 'visible'), 'web_window_mode_invalid')
        self.host = Path(__file__).resolve().parents[1] / 'web_browser_host.cjs'
        self.bound = {path: hashlib.sha256(path.read_bytes()).digest() for path in (
            self.electron, self.host, self.host.with_name('web_browser_page.cjs'),
            self.host.with_name('web_browser_surface.cjs'), CATALOG_PATH)}
        # Only literal codes/stages declared by these bound, plugin-owned files
        # may enter diagnostics. Arbitrary page/error strings are discarded.
        source = ''.join(path.read_text(encoding='utf-8') for path in self.bound if path.suffix == '.cjs')
        self.codes = frozenset(re.findall(r'["\'](web_[a-z_]+)["\']', source))
        self.stages = frozenset(re.findall(r'stage\s*=\s*"([a-z_]+)"', source))
        self.config = {'version': 1, 'mode': 'generate', 'model': 'gpt-5.6-sol', 'effort': 'high',
            'profileDirectory': str(profile), 'sessionPartition': settings['session_partition'],
            'visible': self.window_mode == 'visible', 'timeoutMs': timeout}
        if self.window_mode == 'background':
            self.config['backgroundInput'] = 'dom_v1'
        self.citation_mode = settings.get('citation_mode', 'none')
        require(self.citation_mode in ('none', 'markdown_links_v1'), 'web_public_citation_mode_required')
        if self.citation_mode != 'none':
            self.config['includeCitations'] = True
        if 'software_rendering' in settings:
            require(type(settings['software_rendering']) is bool, 'web_rendering_mode_invalid')
            self.config['softwareRendering'] = settings['software_rendering']
        if 'proxy_rules' in settings:
            proxy = settings['proxy_rules']
            require(isinstance(proxy, str) and re.fullmatch(r'socks5://127\.0\.0\.1:[1-9][0-9]{0,4}', proxy)
                and int(proxy.rsplit(':', 1)[1]) <= 65535, 'web_proxy_invalid')
            self.config['proxyRules'] = proxy
        self.work = Path(work)
        private_directory(self.work)
        self.active = False
        self.attempts = self.dispatches = self.completed = self.cancelled = self.failed = 0
        self.events = deque(maxlen=64)

    def status(self):
        return {'active': self.active, 'attempts': self.attempts, 'dispatches': self.dispatches,
            'completed': self.completed, 'cancelled': self.cancelled, 'failed': self.failed,
            'events': list(self.events), 'mcp_listener': False, 'local_tool_execution': False,
            'response_mode': 'buffered_public_text', 'citation_mode': self.citation_mode,
            'window_mode': self.window_mode, 'retries': 0}

    def request_config(self, turn):
        return {**browser_selection(turn.protocol), 'text': text_prompt(turn.begin(turn.key)['request'])}

    async def __call__(self, turn):
        require(not self.active, 'web_text_browser_busy')
        self.active = True
        self.attempts += 1
        child = None
        folder = config_path = cancel_path = None
        readers = []
        try:
            desktop = desktop_session_state()
            if desktop in ('locked', 'disconnected'):
                raise WebDesktopUnavailable(desktop)
            require(all(hashlib.sha256(path.read_bytes()).digest() == digest
                for path, digest in self.bound.items()), 'web_browser_source_changed')
            request_config = self.request_config(turn)
            folder = self.work / secrets.token_hex(16)
            folder.mkdir(mode=0o700)  # Inherits the private parent on Windows.
            config_path, cancel_path = folder / 'request.json', folder / 'cancel.txt'
            config = {**self.config, **request_config, 'parentPid': os.getpid(), 'cancelFile': str(cancel_path)}
            with config_path.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(config, stream, ensure_ascii=False, allow_nan=False)
            child = await asyncio.create_subprocess_exec(str(self.electron), str(self.host), str(config_path),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=child_environment(), cwd=folder,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                limit=17 * 1024 * 1024)
            finals, dispatches, windows, assistance, http_failures, http_statuses, ui_failures = [], [], [], [], [], [], []
            network_errors, network_failures = [], []
            interruption = None
            final_timeouts = []

            async def stdout():
                nonlocal interruption
                total = count = 0
                while line := await child.stdout.readline():
                    total += len(line)
                    count += 1
                    require(total <= 32 * 1024 * 1024 and len(line) <= 16 * 1024 * 1024
                        and count <= 256, 'web_browser_output_bound')
                    if line in (b'\n', b'\r\n'):
                        continue  # An empty Electron startup line is not message text.
                    value = loads(line)
                    require(isinstance(value, dict) and value.get('operator_web') == 1,
                            'web_browser_record_invalid')
                    kind = value.get('kind')
                    if public_final_timeout(value):
                        require(len(dispatches) == 1 and not finals and not final_timeouts
                            and not http_statuses and not network_errors and public_interruption_code(interruption) is None,
                            'web_browser_final_timeout_unbound')
                        final_timeouts.append(True)
                    if kind == 'public_interruption_state':
                        require(len(dispatches) == 1 and value.get('sent') is True
                            and value.get('stage') == 'wait_public_final' and not finals,
                            'web_browser_ui_failure_unbound')
                        interruption = safe_public_interruption(value.get('state'))
                        self.events.append({'attempt': self.attempts, 'kind': kind, 'state': interruption})
                    if kind == 'model_network_state':
                        network = safe_model_network(value)
                        self.events.append({'attempt': self.attempts, 'kind': kind, **network})
                        if network['phase'] == 'response_started' and type(network['status']) is int and network['status'] >= 400:
                            require(len(dispatches) == 1, 'web_model_http_failure_unbound')
                            http_statuses.append(network['status'])
                        if network['phase'] == 'error' and network['networkError'] in WebBrowserNetworkError.codes:
                            require(len(dispatches) == 1 and not finals, 'web_model_network_failure_unbound')
                            network_errors.append(network['networkError'])
                    if kind == 'failed' and value.get('error') == 'web_model_http_rejected_no_retry':
                        require(len(dispatches) == 1 and not finals and not http_failures, 'web_model_http_failure_unbound')
                        http_failures.append(rejected_http_status(value, http_statuses))
                    if kind == 'failed' and value.get('error') == 'web_model_network_interrupted_no_retry':
                        require(len(dispatches) == 1 and not finals and not network_failures, 'web_model_network_failure_unbound')
                        network_failures.append(rejected_network_error(value, network_errors))
                    if kind == 'failed' and value.get('error') in WebBrowserUiError.codes:
                        require(len(dispatches) == 1 and not finals and not ui_failures, 'web_browser_ui_failure_unbound')
                        ui_failures.append(rejected_ui_code(value, interruption))
                    if kind == 'failed' and value.get('sent') is False and value.get('stage') == 'load_fresh_page' \
                            and value.get('error') in ('web_browser_login_required_before_dispatch',
                                'web_browser_challenge_required_before_dispatch'):
                        assistance.append(value['error'])
                    if kind == 'window_state':
                        require(all(type(value.get(name)) is bool for name in ('visible', 'focused', 'backgroundInput'))
                            and all(type(value.get(name)) is int and 0 <= value[name] <= 10000
                                for name in ('shown', 'focusedEvents')), 'web_window_state_invalid')
                        state = {name: value[name] for name in ('visible', 'focused', 'backgroundInput', 'shown', 'focusedEvents')}
                        require(value.get('inputMode') in ('native_v1', 'dom_v1'), 'web_window_input_mode_invalid')
                        state['inputMode'] = value['inputMode']
                        windows.append(state)
                        self.events.append({'attempt': self.attempts, 'kind': kind, **state})
                    if kind == 'dispatch_started':
                        dispatches.append(True)
                        self.dispatches += 1
                        require(len(dispatches) == 1, 'web_browser_duplicate_dispatch')
                    if kind == 'completed':
                        require(matches_selection(value, request_config)
                            and isinstance(value.get('publicMessage'), dict) and not finals and not http_statuses
                            and not ui_failures and not final_timeouts and not network_errors and public_interruption_code(interruption) is None,
                            'web_browser_final_identity_invalid')
                        finals.append(value['publicMessage'])
                    if kind in ('dispatch_started', 'model_verified', 'public_user_binding', 'generation_state', 'prompt_ready_gate', 'prompt_mismatch_shape', 'modern_identity_shape', 'fresh_chat_control_structure', 'completed', 'failed', 'exit_requested', 'cancel_requested',
                                'cancel_click_attempted', 'cancel_click_unavailable', 'effort_initial_state', 'effort_step_verified',
                                'effort_step_unavailable', 'effort_pro_unavailable', 'effort_pro_verified', 'effort_target_verified',
                                'effort_range_unavailable'):
                        event = {'attempt': self.attempts, 'kind': kind,
                            'stage': value.get('stage') if value.get('stage') in self.stages else 'other',
                            'code': value.get('error') if isinstance(value.get('error'), str)
                                and value['error'] in self.codes else None}
                        if kind == 'generation_state':
                            event['progress'] = safe_generation_progress(value.get('progress'))
                        if kind == 'prompt_ready_gate':
                            event['send_ready'] = value.get('sendReady') if type(value.get('sendReady')) is bool else None
                            event['composer_exact'] = value.get('composerExact') if type(value.get('composerExact')) is bool else None
                        if kind == 'prompt_mismatch_shape':
                            event['shape'] = safe_prompt_mismatch_shape(value.get('shape'))
                        if kind == 'modern_identity_shape':
                            event['shape'] = safe_modern_identity_shape(value.get('shape'))
                        if kind == 'fresh_chat_control_structure':
                            event['shape'] = safe_fresh_chat_control_structure(value.get('shape'))
                        if kind == 'model_verified':
                            require(matches_selection(value, request_config), 'web_browser_selection_identity_invalid')
                            event.update(model=request_config['model'], effort=request_config['effort'],
                                effortIndex=value['effortIndex'])
                        if kind == 'effort_range_unavailable':
                            event.update(safe_effort_range_diagnostic(value))
                        elif kind.startswith('effort_'):
                            event.update(safe_effort_diagnostic(value))
                        if kind == 'public_user_binding' and isinstance(value.get('shape'), dict):
                            event['shape'] = safe_user_binding_diagnostic(value['shape'])
                        if kind == 'completed':
                            references = value['publicMessage'].get('public_references')
                            if isinstance(references, list) and len(references) <= 128:
                                event['public_reference_count'] = len(references)
                        self.events.append(event)
                self.events.append({'attempt': self.attempts, 'kind': 'stdout_closed'})

            async def stderr():
                total = 0
                while chunk := await child.stderr.read(65536):
                    total += len(chunk)
                    require(total <= 1024 * 1024, 'web_browser_stderr_bound')
                # Never persist browser diagnostics, page content or credentials.
                self.events.append({'attempt': self.attempts, 'kind': 'stderr_closed'})

            async def exited():
                code = await child.wait()
                self.events.append({'attempt': self.attempts, 'kind': 'host_exited', 'exit_code': code})

            readers = [asyncio.create_task(stdout()), asyncio.create_task(stderr())]
            await asyncio.wait_for(asyncio.gather(exited(), *readers), self.config['timeoutMs'] / 1000 + 10)
            if child.returncode != 0 and len(dispatches) == 1 and not finals and len(http_failures) == 1:
                raise WebBrowserHttpError(http_failures[0])
            if child.returncode != 0 and len(dispatches) == 1 and not finals and len(network_failures) == 1:
                raise WebBrowserNetworkError(network_failures[0])
            if child.returncode != 0 and len(dispatches) == 1 and not finals and len(ui_failures) == 1:
                raise WebBrowserUiError(ui_failures[0])
            if child.returncode != 0 and len(dispatches) == 1 and not finals and len(final_timeouts) == 1:
                raise WebBrowserFinalTimeout()
            if child.returncode != 0 and not dispatches and not finals and len(assistance) == 1:
                raise WebBrowserAssistanceRequired(assistance[0])
            require(child.returncode == 0 and len(dispatches) == 1 and len(finals) == 1 and not final_timeouts,
                    'web_browser_failed_no_retry')
            if self.window_mode == 'background':
                require(len(windows) == 1 and windows[0] == {'visible': False, 'focused': False,
                    'backgroundInput': True, 'inputMode': 'dom_v1', 'shown': 0, 'focusedEvents': 0},
                    'web_background_window_not_verified')
            self.completed += 1
            return deepcopy(finals[0])
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        except Exception as error:
            self.failed += 1
            self.events.append({'attempt': self.attempts, 'kind': 'driver_failed',
                'code': str(error) if isinstance(error, (WebDesktopUnavailable, WebBrowserAssistanceRequired, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout)) else
                    'timeout' if isinstance(error, asyncio.TimeoutError) else 'rejected',
                'child_exit': None if child is None else child.returncode})
            raise
        finally:
            async def close():
                if child is not None and child.returncode is None:
                    if not cancel_path.exists():
                        cancel_path.write_bytes(b'cancel\n')
                    try:
                        await asyncio.wait_for(child.wait(), 7)
                    except asyncio.TimeoutError:
                        child.terminate()
                        await asyncio.wait_for(child.wait(), 5)
                for reader in readers:
                    if not reader.done():
                        reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                # Remove only our exact ephemeral files, never a browser profile.
                for path in (config_path, cancel_path):
                    if path is not None and path.is_file() and not path.is_symlink():
                        path.unlink()
                if folder is not None:
                    folder.rmdir()
            cleanup = asyncio.create_task(close())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
            finally:
                self.active = False


def validate_connector(connector):
    # Keep ASCII/BMP CJK labels exact; they never replace the registered ID.
    require(isinstance(connector, dict) and set(connector) == {'id', 'name'}
        and isinstance(connector['id'], str)
        and re.fullmatch(r'plugin:asdk_app_[a-f0-9]{32}', connector['id'])
        and isinstance(connector['name'], str)
        and re.fullmatch(r'[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff][A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff -]{0,63}',
            connector['name']),
        'web_mcp_registered_connector_required')
    return deepcopy(connector)


class WebMcpBrowserDriver(WebTextBrowserDriver):
    """Opt-in continuation through one already-owned MCP listener.

    The caller owns the listener, its tunnel/connection and scoped call checks.
    Nothing here creates a tunnel, grants permissions, executes a tool, refreshes
    an app or changes routing. Text-only service setup never selects this class.
    """
    MAX_TIMEOUT_MS = 600000

    def __init__(self, settings, work, *, endpoint, connector, pending_connection=False,
            user_preview_mode='none'):
        require(type(pending_connection) is bool and (not pending_connection or connector is None),
            'web_mcp_pending_connection_invalid')
        require(user_preview_mode in ('none', 'last_source_user_v1'), 'web_mcp_user_preview_mode_invalid')
        # A constructor cannot infer that the public connector is reachable or
        # authorized. Admission additionally binds the live local endpoint/turn.
        self.endpoint = endpoint
        self.user_preview_mode = user_preview_mode
        self.connector = None if pending_connection else validate_connector(connector)
        super().__init__(settings, work)
        self.config['mcpContinuation'] = True

    def bind_connector(self, connector):
        require(not self.active and self.connector is None, 'web_mcp_connector_already_bound_or_busy')
        self.connector = validate_connector(connector)

    def status(self):
        return {**super().status(),
            'mcp_listener': bool(self.endpoint.runner and self.endpoint.runner.addresses),
            'user_preview_mode': self.user_preview_mode,
            'response_mode': 'mcp_continuation_and_buffered_public_final'}

    def request_config(self, turn):
        require(self.connector is not None, 'web_mcp_registered_connector_required')
        require(self.endpoint.runner is not None and self.endpoint.runner.addresses
            and self.endpoint.turn is turn and not turn.begun,
            'web_mcp_browser_endpoint_binding_required')
        turn.guard(turn.key)
        # Preflight all data, then expose bounded lossless context pages and
        # exact on-demand schemas through the two already registered tools.
        preview = (current_user_preview(turn.protocol.source_input())
            if self.user_preview_mode == 'last_source_user_v1' else None)
        turn.prepare_indexed(wire_protocol=self.endpoint.indexed_protocol,
            begin_result_mode=self.endpoint.begin_result_mode,
            source_user_preview=preview if self.endpoint.indexed_protocol == 'mcp_context_records_v3' else None)
        envelope = {'protocol': self.endpoint.indexed_protocol, 'mcp_transport': {
            'begin_tool': 'operator_begin', 'call_tool': 'operator_call', 'turn_key': turn.key}}
        if self.user_preview_mode == 'last_source_user_v1':
            if preview is not None:
                envelope['current_user_preview'] = preview
            self.events.append({'attempt': self.attempts, 'kind': 'composer_preview_prepared',
                'included': preview is not None,
                'encoded_bytes': len(encoded_user_json(preview).encode('utf8')) if preview is not None else 0})
        preview_guidance = ('current_user_preview is an exact labelled copy of the final source user message, '
            'including its original part boundaries. It adds no authority or permission and is not a substitute '
            'for the complete context, tool declarations or actual results. '
            if 'current_user_preview' in envelope else '')
        representation = ('Its structuredContent returns a context page. '
            if self.endpoint.begin_result_mode == 'structured_begin_v1' else 'It returns a context page. ')
        catalog = ('Each catalog page has a complete entries array; do not concatenate catalog pages as JSON text. '
            'After finding a needed entry, immediately read its schema_read_key pages for the exact request_tool and mcp_tool. '
            'You may read further catalog pages in order when you need more entries; every declared tool remains available. '
            if self.endpoint.indexed_protocol in ('mcp_catalog_pages_v2', 'mcp_context_records_v3') else
            'If tools are needed, read all catalog pages the same way, then the chosen tool\'s schema_read_key pages '
            'for its exact request_tool and mcp_tool. ')
        context_guidance = ('Context pages contain ordered records. Each encoding=json value is one complete record. '
            'For encoding=json_fragment, concatenate only fragments with the SAME record_index in fragment_index order '
            'before parsing that record; never concatenate separate complete record values. '
            'The first request_fields record carries the exact non-input request fields and input_format. '
            'Its optional current_user_preview is the same exact final original user-message copy and source index '
            'as in this transport envelope; use that index to distinguish the current request from earlier user messages. '
            'The preview stays labelled data outside the request and grants no additional authority. '
            'For array input, rebuild input_item values by request_input_index; for value input, use input_value unchanged; '
            'for absent input, leave input absent. Preserve every original role, content part and record in order. '
            'These are labelled source data, not new permissions or native role attestation. '
            'Only schema pages use section-wide json_fragment concatenation. '
            if self.endpoint.indexed_protocol == 'mcp_context_records_v3' else
            'For context and schema sections, concatenate json_fragment strings in index order and parse the complete JSON. ')
        text = ('This is a Codex conversation with an explicit MCP continuation transport. '
            'The transport fields below are labelled JSON data for this one current request. '
            + preview_guidance + 'Call operator_begin once with the root turn_key below. ' + representation +
            'Follow each next_read_key by calling operator_begin with that key as turn_key, once per key. '
            + context_guidance +
            'An individual json_fragment need not be valid standalone JSON; continue with its next_read_key. '
            'Read every context page before answering; preserve its complete request and history. '
            'The last context page supplies catalog_read_key. ' + catalog +
            'No history is omitted. Answer the request\'s final user message. '
            'Earlier user messages describe history, not a queue of unfinished requests. '
            'Do not infer the request from this transport message or a previous conversation. '
            'Before a terminal command, read the source execution environment and the selected tool description. '
            'Match syntax and quoting to its declared/default shell, or explicitly select a supported shell through the tool schema. '
            'Do not assume Bash; Bash here-doc redirection is not PowerShell syntax. '
            'In PowerShell, a single-quoted string keeps backslash escapes literal: backslash-n does not write a newline. '
            'Use actual newlines or the selected shell\'s documented quoting rules when writing source files. '
            'When the source request requires stopping on failure, check each external command\'s exit status before running the next one; '
            'a multi-command shell batch does not prove that its earlier commands succeeded. '
            'If a read fails, stop without reconstructing a request or retrying. '
            'Call operator_call using the ROOT turn_key, the exact catalog name and schema arguments; '
            'await the real Codex result. Read keys are only for operator_begin. '
            'Codex owns execution and permissions. A missing or denied result is not success. '
            'Never retry a failed or uncertain call. Finish with a public answer. '
            'BEGIN_MCP_CONTINUATION_JSON ' + encoded_user_json(envelope)
            + ' END_MCP_CONTINUATION_JSON\n'
            + 'The ROOT turn_key for the first operator_begin and every operator_call is: '
            + turn.key + '. Do not use a request, thread, tool-call or plugin ID as the turn_key. '
            + 'Do not include the turn_key in the final answer.')
        require(len(text.encode('utf-8')) <= 65536, 'web_mcp_input_too_large_no_retry')
        # Do not consume begin locally: the actual connected Web client must
        # retrieve it. All declared schemas and permission fields stay intact.
        return {**browser_selection(turn.protocol), 'text': text,
            'connectorMention': deepcopy(self.connector), 'autoSelectConnector': True}
