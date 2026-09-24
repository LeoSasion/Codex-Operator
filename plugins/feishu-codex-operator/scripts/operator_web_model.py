"""Explicit, owner-stopped Web service. Never edits Codex configuration.

Start with a NEW private state directory. status is read-only; assist and stop
address the authenticated live instance. Background sessions are the default;
only an explicit assist request or startup_assistance can display a window.
Stop cancels immediately unless a bounded drain is explicitly requested.
The service has no expiry by default; a finite lifetime is opt-in.
Text-only is the default. Explicit mcp_v1 owns one selected development tunnel
and accepts a separately authorized connector binding. No model registration,
automatic authorization, service installation, restart or replay is performed.
An explicit assist --replace-closed-browser can replace one stopped idle browser
without replacing the connection or the native no-replay ledger.

Independent Python lifecycle design informed by WebCodex (Apache-2.0), commit
01dc7d31d567aa0300bc246ac7f4a2db590bdbe2: desktop_shell.rs and
process/supervisor.rs; no Runner or third-party execution engine is embedded.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from operator_core.model_registry import ModelRegistry
from operator_core.web_model_catalog import MODELS, PREFIX
from operator_core.responses_tool_adapter import loads
from operator_core.web_browser_driver import WebTextBrowserDriver, WebMcpBrowserDriver, private_directory
from operator_core.web_browser_session import WebBrowserSession
from operator_core.web_connection import WebMcpConnection
from operator_core.web_openai_tunnel import WebOpenAITunnel
from operator_core.web_mcp_transport import MCP_TOOLS, WebMcpEndpoint, WebResponsesBridge, require
from operator_core.web_responses_provider import WebResponsesProvider


SLUG = 'api/chatgpt-web/gpt-5.6-sol'
DEFAULT_SERVICE_LIFETIME = 0
MAX_SERVICE_LIFETIME = 72 * 60 * 60


def text_route(*, tools=False, model='gpt-5.6-sol'):
    # Only explicit mcp_v1 enables call release through the connected endpoint.
    # The default text transport still rejects every local call.
    require(model in MODELS, 'web_explicit_model_required')
    definition = MODELS[model]
    row = {'slug': PREFIX + model, 'display_name': definition['display_name'],
        'model': model, 'api_base': 'http://127.0.0.1:1/v1', 'api_key_env': '',
        'context_window': 16000, 'reasoning_efforts': definition['reasoning_efforts'], 'responses': {
            'protocol': 'responses-tools-v1', 'function_tools': True,
            # Explicit native Desktop codecs; they only represent declarations
            # and history. Codex still owns every execution and permission.
            'custom_tools': {'exec': 'wrap', 'functions.exec': 'wrap'} if tools else {},
            'named_function_outputs': {name: 'user_message_json_v1' for name in (
                'codex_app.create_thread', 'codex_app.send_message_to_thread')} if tools else {},
            'input_tool_definitions': 'additional_tools_v1' if tools else 'reject',
            'tool_choice': ['auto', 'none', 'required'] if tools else ['auto', 'none'],
            'named_tool_choice': 'native' if tools else 'reject',
            'parallel_tool_calls': False, 'tool_search': tools, 'input_modalities': ['text'],
            'structured_tool_outputs': tools, 'developer_role': 'native',
            # Desktop 26.908.9136.0's concurrent-summary feature overrides its
            # saved "none" preference with "detailed". Accept that optional
            # request field unchanged in the complete labelled JSON. This is
            # input compatibility, not a promise to produce a reasoning item:
            # the browser driver returns only the bound public final message.
            'reasoning_input': True, 'reasoning_summary': True, 'previous_response_id': False,
            'text_verbosity': False, 'codex_tool_mode': 'standard',
            'completed_output_policy': 'require_message_or_tool'}}
    return ModelRegistry({'version': 2, 'models': [row]}, {'models': [{}]}).routes[row['slug']]


def text_routes(*, tools=False):
    return tuple(text_route(tools=tools, model=model) for model in MODELS)


def read_json(path, limit=65536):
    require(path.is_file() and not path.is_symlink(), 'web_service_regular_file_required')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'web_service_file_too_large')
    return loads(raw)


def write_json(path, value, *, defer_busy_replace=False):
    # Readers on Windows can temporarily deny replacement. A unique owned
    # staging file must be removed even then, so a failed publication cannot
    # poison later writes or hide the original failure during shutdown.
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.pending', dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        try:
            os.replace(pending, path)
        except PermissionError as error:
            if defer_busy_replace and os.name == 'nt' and error.winerror in (5, 32, 33):
                return False
            raise
        return True
    finally:
        pending.unlink(missing_ok=True)


class ServiceSnapshots:
    """Coalesce observations while a Windows reader holds their previous file.

    Commands, session credentials and initial setup still require publication.
    Only observations of already-applied service state may be deferred. Flushing
    publishes data; it never repeats a command, browser request or tool call.
    """
    def __init__(self, state):
        self.state = state
        self.pending = {}

    def queue(self, name, value):
        self.pending[name] = value

    def flush(self):
        for name, value in list(self.pending.items()):
            if write_json(self.state / name, value, defer_busy_replace=True):
                del self.pending[name]


def write_command(path, value):
    """Publish a complete private command without replacing another request."""
    pending = path.with_name(path.name + '.pending')
    require(not path.exists() and not path.is_symlink(), 'web_service_command_pending')
    with pending.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
    try:
        # Linking is atomic and fails if another caller already published the
        # command. The pending and destination paths share the private directory.
        os.link(pending, path)
    finally:
        pending.unlink()


def live_status(state):
    session = read_json(state / 'session.json')
    require(isinstance(session, dict) and session.get('version') == 1
        and isinstance(session.get('instance'), str)
        and re.fullmatch(r'[a-f0-9]{32}', session['instance']), 'web_service_session_invalid')
    base, token = session.get('base_url'), session.get('token')
    require(isinstance(base, str) and re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}/v1', base)
        and isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token),
        'web_service_endpoint_invalid')
    request = Request(base[:-3] + '/health', headers={'Authorization': 'Bearer ' + token})
    with build_opener(ProxyHandler({}), NoConnectionProbeRedirect()).open(request, timeout=3) as response:
        raw = response.read(65537)
    require(len(raw) <= 65536, 'web_service_health_too_large')
    health = loads(raw)
    require(isinstance(health, dict) and health.get('ready') is True, 'web_service_not_ready')
    require(read_json(state / 'session.json') == session, 'web_service_session_changed')
    return session, health


class NoConnectionProbeRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def check_connection(state, session, health):
    """One explicit public initialize/list check, with no browser or tool calls.

    Reachability is dated observation only. It neither binds a connector nor
    proves account authorization; status remains a purely local read.
    """
    require(session.get('mode') == 'mcp_v1' and health.get('active') is False,
        'web_connection_probe_requires_idle')
    setup = read_json(state / 'connection.json')
    require(setup.get('instance') == session['instance'], 'web_connection_instance_changed')
    if setup.get('kind') == 'fixed_openai_tunnel':
        connection = health.get('connection', {})
        good = (connection.get('mode') == 'openai_tunnel_v1' and connection.get('connected') is True
            and connection.get('poll_observed') is True and health.get('state') != 'stopped')
        result = {'instance': session['instance'], 'state': 'transport_ready' if good else 'failed',
            'checked_at': int(time.time()), 'rpc_requests': 0, 'model_requests': 0, 'tool_calls': 0,
            'scope': 'owned_client_readiness_and_recent_control_plane_poll',
            'chatgpt_authorization_verified': False}
        write_json(state / 'connection-check.json', result)
        return result
    url = setup.get('endpoint_url')
    require(isinstance(url, str) and re.fullmatch(
        r'https://[a-z0-9-]+\.trycloudflare\.com/mcp/[A-Za-z0-9_-]{43}', url),
        'web_connection_probe_endpoint_invalid')
    opener = build_opener(NoConnectionProbeRedirect())
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    methods = [('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'operator-connection-check', 'version': '1'}}), ('tools/list', {})]
    result = {'instance': session['instance'], 'state': 'failed', 'checked_at': int(time.time()),
        'rpc_requests': 0, 'model_requests': 0, 'tool_calls': 0}
    try:
        for index, (method, params) in enumerate(methods):
            identity = 'connection-check-' + str(index)
            payload = json.dumps({'jsonrpc': '2.0', 'id': identity, 'method': method,
                'params': params}).encode('utf-8')
            result['rpc_requests'] += 1
            with opener.open(Request(url, payload, headers), timeout=15) as response:
                require(response.status == 200, 'web_connection_probe_http_failed')
                raw = response.read(65537)
                require(len(raw) <= 65536, 'web_connection_probe_response_bound')
                value = loads(raw)
                require(isinstance(value, dict) and value.get('jsonrpc') == '2.0'
                    and value.get('id') == identity and 'error' not in value,
                    'web_connection_probe_response_invalid')
                if index == 0:
                    require(value.get('result') == {'protocolVersion': '2025-03-26',
                        'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'operator-web-tools', 'version': '0.2.0'}},
                        'web_connection_probe_server_changed')
                    sid = response.headers.get('Mcp-Session-Id')
                    require(isinstance(sid, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', sid),
                        'web_connection_probe_session_invalid')
                    headers['Mcp-Session-Id'] = sid
                else:
                    require(value.get('result') == {'tools': MCP_TOOLS},
                        'web_connection_probe_tools_changed')
        current, current_health = live_status(state)
        require(current == session and current_health.get('active') is False
            and read_json(state / 'connection.json') == setup, 'web_connection_probe_instance_changed')
        result['state'] = 'reachable'
    except HTTPError as error:
        result.update(code='web_connection_probe_http_failed', http_status=error.code)
    except (URLError, TimeoutError):
        result['code'] = 'web_connection_probe_transport_failed'
    except Exception as error:
        result['code'] = assistance_error(error)
    write_json(state / 'connection-check.json', result)
    return result


def selected_lifecycle(config):
    # Preserve explicitly visible, per-turn diagnostics. Ordinary omitted
    # settings select one hidden worker; no UI is shown automatically.
    default = 'per_turn' if config.get('window_mode') == 'visible' else 'session_v1'
    lifecycle = config.get('browser_lifecycle', default)
    require(lifecycle in ('per_turn', 'session_v1'), 'web_browser_lifecycle_invalid')
    return lifecycle


def stop_request(path, instance):
    value = read_json(path)
    require(isinstance(value, dict) and set(value) <= {'instance', 'drain_seconds'}
        and value.get('instance') == instance, 'web_service_stop_identity_changed')
    seconds = value.get('drain_seconds', 0)
    require(type(seconds) is int and 0 <= seconds <= 30, 'web_service_drain_invalid')
    return seconds


def take_stop_request(state, instance):
    source, active = state / 'stop.json', state / 'stop.active.json'
    require(not active.exists() and not active.is_symlink(), 'web_service_stop_claim_changed')
    require(source.is_file() and not source.is_symlink(), 'web_service_regular_file_required')
    source.rename(active)
    try:
        return stop_request(active, instance)
    finally:
        require(active.is_file() and not active.is_symlink(), 'web_service_stop_claim_changed')
        active.unlink()


def take_assistance_request(state, instance):
    source, active = state / 'assist.json', state / 'assist.active.json'
    require(not active.exists() and not active.is_symlink(), 'web_service_assistance_claim_changed')
    require(source.is_file() and not source.is_symlink(), 'web_service_regular_file_required')
    source.rename(active)
    try:
        value = read_json(active, 1024)
        require(isinstance(value, dict) and {'instance', 'id'} <= set(value)
            and set(value) <= {'instance', 'id', 'replace_closed_browser', 'inspect_completed'}
            and value['instance'] == instance, 'web_service_assistance_identity_changed')
        require(isinstance(value['id'], str) and re.fullmatch(r'[a-f0-9]{32}', value['id']),
            'web_assistance_identity_invalid')
        replace = value.get('replace_closed_browser', False)
        require(type(replace) is bool, 'web_assistance_replacement_invalid')
        inspect = value.get('inspect_completed', False)
        require(type(inspect) is bool and not (inspect and replace), 'web_inspection_mode_invalid')
        return value['id'], replace, inspect
    finally:
        require(active.is_file() and not active.is_symlink(), 'web_service_assistance_claim_changed')
        active.unlink()


def take_connection_binding(state, instance):
    source, active = state / 'connect.json', state / 'connect.active.json'
    require(not active.exists() and not active.is_symlink(), 'web_connection_claim_changed')
    require(source.is_file() and not source.is_symlink(), 'web_service_regular_file_required')
    source.rename(active)
    try:
        value = read_json(active, 4096)
        require(isinstance(value, dict) and set(value) == {'instance', 'binding'}
            and value['instance'] == instance, 'web_connection_instance_changed')
        return value['binding']
    finally:
        require(active.is_file() and not active.is_symlink(), 'web_connection_claim_changed')
        active.unlink()


def service_status(instance, browser, provider, *, assistance=None, phase=None, connection=None,
        browser_replacements=0):
    observation = browser.status()
    readiness = observation.get('readiness', 'busy' if observation.get('active') else 'ready')
    needs_assistance = observation.get('needs_assistance', False)
    state = phase or ('unavailable' if readiness == 'unavailable' else
        'assistance' if needs_assistance else 'preparing' if readiness == 'preparing' else 'ready')
    if connection is not None and not connection.ready and phase is None and readiness != 'unavailable':
        state = 'unavailable' if connection.failed.is_set() else 'reconnecting' if connection.reconnecting else 'connection'
        readiness = {'connection': 'connection_required', 'reconnecting': 'connection_reconnecting',
            'unavailable': 'unavailable'}[state]
    return {'instance': instance, 'state': state, 'readiness': readiness,
        'needs_assistance': needs_assistance, 'browser': observation,
        'requests': provider.requests, 'assistance': assistance,
        'transport': provider.bridge.diagnostics(),
        'mcp': provider.bridge.endpoint.diagnostics(),
        'explicit_browser_replacements': browser_replacements,
        **({'connection': connection.status()} if connection is not None else {})}


def service_guidance(details):
    """User-facing progress from fixed local observations, never answer prose."""
    state = details['state']
    if state == 'stopped':
        return '后台服务已停止，已保存的固定连接和插件绑定仍保留。'
    if details.get('needs_assistance'):
        if (details.get('assistance') or {}).get('inspect_completed') is True:
            return '正在查看已结束对话的只读文字快照；关闭预览后恢复接收请求，原页面保留。'
        return '网页会话尚未就绪；先查看当前准确页面，再判断是否需要登录或验证。已有固定连接继续沿用。'
    if state == 'connection':
        return '请完成当前固定连接的绑定；已有插件时先核对绑定，不要重复创建。'
    if state == 'reconnecting':
        return '连接正在恢复，固定配置保留；未自动重做先前请求。'
    if state == 'preparing':
        return '后台正在检查已保存的网页会话；尚未发送模型请求，也不会自动重做先前请求。'
    if state == 'unavailable':
        return '后台连接当前不可用，请先检查连接状态；不要重复创建插件或重发先前操作。'
    transport = details.get('transport') or {}
    active = transport.get('active_turn')
    last = transport.get('last_turn')
    observed = active or last
    if observed is None:
        return '后台服务已就绪，尚无本次服务的请求记录。'
    counts = (f"已向 Codex 转交 {observed['calls_released']} 次工具调用，"
        f"收到 {observed['results_received']} 份配对结果。")
    if active is not None:
        prefix = '当前请求仍在处理中。'
    elif last['outcome'] == 'public_final_returned':
        prefix = '最近一次网页回复已返回。'
    else:
        prefix = '最近一次请求已停止，未自动重做。'
    return prefix + counts + '结果可能包含失败或拒绝，任务是否完成需核对实际结果。'


def request_active(bridge, browser):
    return bridge.turn is not None or bridge.exchanging or browser.status().get('active', False)


def assistance_error(error):
    # Never include child/page exception text in persisted status.
    from operator_core.responses_capabilities import RouterError
    return str(error) if isinstance(error, RouterError) and re.fullmatch(r'[a-z0-9_]{1,128}', str(error)) \
        else 'web_assistance_failed_no_retry'


async def serve(settings, state, lifetime=DEFAULT_SERVICE_LIFETIME, *, prepare_hidden=False):
    require(type(lifetime) is int and (lifetime == 0 or 60 <= lifetime <= MAX_SERVICE_LIFETIME),
        'web_service_lifetime_invalid')
    config = read_json(settings)
    require(isinstance(config, dict), 'web_browser_settings_invalid')
    mode = config.get('transport', 'text_only')
    require(mode in ('text_only', 'mcp_v1') and (mode == 'mcp_v1') == ('mcp' in config),
        'web_service_transport_invalid')
    lifecycle = selected_lifecycle(config)
    assistance = config.get('startup_assistance', False)
    require(type(assistance) is bool and (not assistance or lifecycle == 'session_v1'),
        'web_startup_assistance_invalid')
    require(type(prepare_hidden) is bool and (not prepare_hidden
        or lifecycle == 'session_v1' and not assistance), 'web_startup_prepare_invalid')
    startup_prepare = prepare_hidden
    private_directory(state)
    endpoint = WebMcpEndpoint(begin_result_mode='structured_begin_v1' if mode == 'mcp_v1' else 'text_v1',
        call_result_mode='structured_call_v1' if mode == 'mcp_v1' else 'text_v1',
        indexed_protocol='mcp_context_records_v3' if mode == 'mcp_v1' else 'mcp_indexed_request_v1')
    connection = None
    if mode == 'mcp_v1':
        require(isinstance(config['mcp'], dict), 'web_connection_settings_invalid')
        connection_type = WebOpenAITunnel if config['mcp'].get('mode') == 'openai_tunnel_v1' else WebMcpConnection
        connection = connection_type(config['mcp'], endpoint, state)
    driver_config = {k: v for k, v in config.items()
        if k not in ('browser_lifecycle', 'startup_assistance', 'transport', 'mcp')}
    base_browser = (WebMcpBrowserDriver(driver_config, state / 'requests', endpoint=endpoint,
        user_preview_mode='last_source_user_v1',
        connector=None, pending_connection=True) if connection is not None else
        WebTextBrowserDriver(driver_config, state / 'requests'))
    browser = base_browser
    if lifecycle == 'session_v1': browser = WebBrowserSession(browser,
        startup_assistance=assistance, startup_prepare=startup_prepare)
    bridge = WebResponsesBridge(text_route(tools=connection is not None), endpoint, browser,
        routes=text_routes(tools=connection is not None),
        timeout=browser.config['timeoutMs'] / 1000 + 15,
        citation_mode=config.get('citation_mode', 'none'),
        check_call=(lambda *_: require(connection.ready, 'web_connection_unavailable'))
            if connection is not None else lambda *_: require(False, 'web_text_calls_unavailable'))
    provider = WebResponsesProvider(bridge)
    if connection is not None:
        provider.admission_guard = lambda: connection.ready
        provider.connection_status = lambda: {key: value for key, value in connection.status().items()
            if key in ('mode', 'state', 'connected', 'poll_observed')}
        connection.request_active = lambda: request_active(bridge, browser)
    ended = asyncio.Event()
    handlers = {}
    for name in ('SIGINT', 'SIGTERM'):
        value = getattr(signal, name)
        handlers[value] = signal.signal(value, lambda *_: ended.set())
    instance = secrets.token_hex(16)
    preparation = None
    page_preparation = None
    assistance_result = None
    assistance_ids = set()
    browser_replacements = 0
    drain_seconds = 0
    snapshots = ServiceSnapshots(state)
    try:
        if connection is not None:
            await connection.start()
            if connection.connector is not None:
                base_browser.bind_connector(connection.connector)
            write_json(state / 'connection.json', {'instance': instance, **connection.setup()})
        needs_connection = connection is not None and not connection.ready
        provider.admission_state = ('connection' if needs_connection else 'assistance' if assistance
            else 'preparing' if startup_prepare else 'ready')
        base = await provider.start()
        write_json(state / 'session.json', {'version': 1, 'instance': instance,
            'pid': os.getpid(), 'base_url': base, 'token': provider.token, 'model': SLUG,
            'models': [route.slug for route in text_routes(tools=connection is not None)],
            'expires_at': int(time.time()) + lifetime if lifetime else None, 'mode': mode})
        print(json.dumps({'status': 'connection_required' if needs_connection else 'ready',
            'mode': mode, 'mcp_listener': connection is not None,
            'browser_lifecycle': lifecycle, 'browser_readiness': browser.status().get('readiness', 'ready')}), flush=True)
        if assistance:
            assistance_result = {'id': None, 'state': 'opening', 'source': 'startup'}
            preparation = asyncio.create_task(browser.prepare_assistance())
        elif startup_prepare:
            page_preparation = asyncio.create_task(browser.prepare_hidden())
        deadline = time.monotonic() + lifetime if lifetime else None
        previous = None
        while not ended.is_set() and (deadline is None or time.monotonic() < deadline):
            if connection is not None and connection.failed.is_set():
                break
            if preparation is not None and preparation.done():
                try:
                    preparation.result()
                    assistance_result = {**assistance_result, 'state': 'completed'}
                except Exception as error:
                    assistance_result = {**assistance_result, 'state': 'failed', 'code': assistance_error(error)}
                preparation = None
            if page_preparation is not None and page_preparation.done():
                try: page_preparation.result()
                except Exception: pass  # The owned browser is closed and status becomes unavailable.
                page_preparation = None
            stop = state / 'stop.json'
            if stop.exists() or stop.is_symlink():
                try:
                    drain_seconds = take_stop_request(state, instance)
                except Exception as error:
                    # A stale instance's stop command has no authority to end
                    # this service. Reject it without cancelling current work.
                    snapshots.queue('stop-result.json', {'instance': instance,
                        'state': 'rejected', 'code': assistance_error(error)})
                else:
                    snapshots.queue('stop-result.json', {'instance': instance,
                        'state': 'accepted', 'drain_seconds': drain_seconds})
                    snapshots.flush()
                    break
            connect = state / 'connect.json'
            if connect.exists() or connect.is_symlink():
                try:
                    binding = take_connection_binding(state, instance)
                    require(connection is not None, 'web_connection_mode_required')
                    require(not request_active(bridge, browser), 'web_connection_requires_idle')
                    connector = connection.bind(binding)
                    base_browser.bind_connector(connector)
                    snapshots.queue('connection.json', {'instance': instance, **connection.setup()})
                    snapshots.queue('connect-result.json', {'instance': instance, 'state': 'bound'})
                except Exception as error:
                    snapshots.queue('connect-result.json', {'instance': instance,
                        'state': 'rejected', 'code': assistance_error(error)})
            assist = state / 'assist.json'
            if assist.exists() or assist.is_symlink():
                assistance_id = None
                try:
                    assistance_id, replace_closed, inspect_completed = take_assistance_request(state, instance)
                    require(assistance_id not in assistance_ids, 'web_assistance_consumed_no_retry')
                    require(len(assistance_ids) < 128, 'web_assistance_request_limit')
                    assistance_ids.add(assistance_id)
                    require(isinstance(browser, WebBrowserSession), 'web_assistance_requires_session')
                    require(preparation is None and page_preparation is None and not request_active(bridge, browser),
                        'web_assistance_requires_idle_session')
                    require(not inspect_completed or browser.status()['inspection_available'],
                        'web_inspection_completed_page_required')
                    # No await between observing idle and fencing HTTP admission.
                    provider.admission_state = 'assistance'
                    if replace_closed:
                        require(browser.closed and browser_replacements < 8,
                            'web_assistance_closed_browser_required')
                        # Explicit owner recovery replaces only a stopped idle
                        # browser. Retain the endpoint, its sessions, connector,
                        # native admission ledger and original source binding.
                        # No failed turn or pending input is carried forward.
                        browser.check_environment()
                        await browser.close()
                        browser = WebBrowserSession(base_browser)
                        bridge.run_browser = browser
                        browser_replacements += 1
                    else:
                        require(not browser.closed, 'web_session_closed_explicit_replacement_required')
                    assistance_result = {'id': assistance_id, 'state': 'opening', 'source': 'explicit',
                        **({'inspect_completed': True} if inspect_completed else {})}
                    preparation = asyncio.create_task(browser.assist(assistance_id, inspect_completed=inspect_completed))
                except Exception as error:
                    rejected = {'id': assistance_id, 'state': 'rejected', 'code': assistance_error(error)}
                    snapshots.queue('assist-result.json', {'instance': instance, **rejected})
                    if preparation is None:
                        assistance_result = rejected
            status = service_status(instance, browser, provider, assistance=assistance_result,
                phase='assistance' if preparation is not None else 'preparing' if page_preparation is not None else None,
                connection=connection,
                browser_replacements=browser_replacements)
            if preparation is not None:
                provider.admission_state = 'assistance'
            elif page_preparation is not None:
                provider.admission_state = 'preparing'
            elif status['state'] == 'unavailable':
                provider.admission_state = 'stopped'
            elif connection is not None and not connection.ready:
                provider.admission_state = 'reconnecting' if connection.reconnecting else 'connection'
            else:
                provider.admission_state = 'assistance' if status['needs_assistance'] else 'ready'
            if status != previous:
                snapshots.queue('status.json', status)
                if assistance_result is not None:
                    snapshots.queue('assist-result.json', {'instance': instance, **assistance_result,
                        'window_state': status['browser'].get('assistance_state', 'not_available')})
                previous = status
            snapshots.flush()
            try:
                await asyncio.wait_for(ended.wait(), 0.2)
            except asyncio.TimeoutError:
                pass
        provider.admission_state = 'draining'
        drain_deadline = time.monotonic() + drain_seconds
        while (drain_seconds and request_active(bridge, browser) and not ended.is_set()
                and time.monotonic() < drain_deadline):
            snapshots.queue('status.json', service_status(instance, browser, provider,
                assistance=assistance_result, phase='draining', connection=connection,
                browser_replacements=browser_replacements))
            snapshots.flush()
            try:
                await asyncio.wait_for(ended.wait(), min(0.1, max(0.001, drain_deadline - time.monotonic())))
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            provider.admission_state = 'stopped'
            if preparation is not None:
                preparation.cancel()
                await asyncio.gather(preparation, return_exceptions=True)
            if page_preparation is not None:
                page_preparation.cancel()
                await asyncio.gather(page_preparation, return_exceptions=True)
            try:
                await provider.stop()
            finally:
                try:
                    if isinstance(browser, WebBrowserSession): await browser.close()
                finally:
                    if connection is not None: await connection.close()
            snapshots.queue('status.json', {**service_status(instance, browser, provider,
                assistance=assistance_result, phase='stopped', connection=connection,
                browser_replacements=browser_replacements), 'readiness': 'unavailable',
                'needs_assistance': False, 'restart': 'explicit_new_session_only'})
            snapshots.flush()
            if snapshots.pending:
                print(json.dumps({'status': 'stopped', 'code': 'web_service_snapshot_publication_deferred',
                    'pending_snapshots': len(snapshots.pending)}), file=sys.stderr)
        finally:
            for value, handler in handlers.items():
                signal.signal(value, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'status', 'assist', 'inspect', 'connect', 'check-connection', 'stop'))
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--prepare-hidden', action='store_true',
        help='serve only: check one empty saved Web page before accepting a model request')
    parser.add_argument('--binding', type=Path, help='connect only: private binding for this exact connection')
    parser.add_argument('--replace-closed-browser', action='store_true',
        help='assist only: explicitly replace a closed idle browser, retaining the live connection and no-replay ledger')
    parser.add_argument('--lifetime', type=int, default=DEFAULT_SERVICE_LIFETIME,
        help='0 (default): no service expiry; opt-in limit: 60..259200 seconds; platform tunnel availability is separate')
    parser.add_argument('--drain-seconds', type=int, default=0,
        help='stop only: wait 0..30 seconds for the owned request before cancelling; default 0')
    args = parser.parse_args()
    require(args.state.is_absolute(), 'web_service_absolute_state_required')
    try:
        require(type(args.drain_seconds) is int and 0 <= args.drain_seconds <= 30
            and (args.action == 'stop' or args.drain_seconds == 0), 'web_service_drain_invalid')
        require((args.action == 'connect') == (args.binding is not None), 'web_connection_binding_required')
        require(not args.replace_closed_browser or args.action == 'assist', 'web_assistance_replacement_invalid')
        require(not args.prepare_hidden or args.action == 'serve', 'web_startup_prepare_invalid')
        if args.action == 'serve':
            require(args.settings is not None and args.settings.is_absolute(), 'web_service_settings_required')
            asyncio.run(serve(args.settings, args.state, args.lifetime,
                prepare_hidden=args.prepare_hidden))
        else:
            session, health = live_status(args.state)
            if args.action == 'check-connection':
                result = check_connection(args.state, session, health)
                print(json.dumps(result))
                return 0 if result['state'] in ('reachable', 'transport_ready') else 1
            elif args.action == 'stop':
                stop = args.state / 'stop.json'
                command = {'instance': session['instance'], 'drain_seconds': args.drain_seconds}
                if stop.exists():
                    require(stop_request(stop, session['instance']) == args.drain_seconds,
                        'web_service_stop_already_requested')
                else:
                    write_command(stop, command)
                print(json.dumps({'status': 'stop_requested', 'mode': 'drain' if args.drain_seconds else 'cancel',
                    'drain_seconds': args.drain_seconds}))
            elif args.action == 'connect':
                require(args.binding.is_absolute() and session.get('mode') == 'mcp_v1'
                    and health.get('active') is False, 'web_connection_requires_idle')
                write_command(args.state / 'connect.json', {'instance': session['instance'],
                    'binding': read_json(args.binding, 4096)})
                print(json.dumps({'status': 'connection_binding_requested'}))
            elif args.action in ('assist', 'inspect'):
                require(health.get('active') is False, 'web_assistance_requires_idle_session')
                assistance_id = secrets.token_hex(16)
                write_command(args.state / 'assist.json', {'instance': session['instance'], 'id': assistance_id,
                    **({'inspect_completed': True} if args.action == 'inspect' else {}),
                    **({'replace_closed_browser': True} if args.replace_closed_browser else {})})
                print(json.dumps({'status': 'inspection_requested' if args.action == 'inspect' else 'assistance_requested',
                    'assistance_id': assistance_id, 'next': 'close_read_only_preview' if args.action == 'inspect'
                    else 'complete_login_or_verification_then_close_window'}))
            else:
                details = read_json(args.state / 'status.json')
                require(details.get('instance') == session['instance'], 'web_service_status_identity_changed')
                print(json.dumps({'status': details['state'], **health,
                    'readiness': details['readiness'], 'needs_assistance': details['needs_assistance'],
                    'summary': service_guidance(details), 'details': details}, ensure_ascii=False))
    except Exception as error:
        from operator_core.responses_capabilities import RouterError
        print(json.dumps({'status': 'failed', 'code': str(error) if isinstance(error, RouterError)
            else 'web_service_unavailable_no_retry',
            **({'errno': error.errno, 'winerror': getattr(error, 'winerror', None)}
                if isinstance(error, OSError) else {})}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
