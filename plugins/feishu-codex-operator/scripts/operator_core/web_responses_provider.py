"""Opt-in loopback HTTP boundary for the Operator-owned Web bridge.

No global configuration, provider registration, native credential forwarding,
browser launch or local tool execution occurs here. The caller supplies the
browser driver, private lifecycle and the separately exposed MCP transport.
"""
import asyncio
import secrets

from aiohttp import web
from .web_model_protocol import PUBLIC_CITATION_ERRORS

from .model_router import MAX_BODY, RequestSizeError, decode_request
from .responses_capabilities import RouterError
from .responses_tool_adapter import dumps
from .web_mcp_transport import INDEX_REPLY_BYTES, INDEX_READ_LIMIT, WebRequestCapacityError, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout, require


_CONTINUATION_ERRORS = frozenset((
    'web_mcp_history_changed', 'web_mcp_request_binding_changed',
    'web_mcp_exact_call_result_required', 'web_mcp_call_identity_changed',
    'web_mcp_result_identity_changed', 'web_mcp_original_result_required',
    'web_mcp_result_without_call', 'web_mcp_text_result_required',
    'unmatched_tool_output', 'tool_output_identity_mismatch',
    'tool_output_missing_from_explicit_history', 'unfinished_tool_call',
    'duplicate_history_call_id', 'unsupported_structured_content',
    'unsupported_input_modality'))
_REQUEST_CONTRACT_ERRORS = frozenset((
    'unsupported_tool_type', 'invalid_tool_name', 'custom_tool_not_registered',
    'unsupported_custom_tool_format', 'unsupported_deferred_tool',
    'client_tool_search_not_supported', 'input_tool_definitions_not_supported',
    'unsupported_input_tool_definition_fields', 'named_function_output_not_registered',
    'named_function_output_requires_text_parts', 'unsupported_named_function_output_metadata',
    'unsupported_named_function_output_fields',
    'opaque_cross_provider_context_not_supported', 'unsupported_history_item',
    'web_mcp_function_representation_required', 'web_mcp_object_schema_required',
    'web_mcp_text_description_required', 'reasoning_effort_not_registered',
    'reasoning_summary_not_supported', 'text_verbosity_not_supported'))
_PUBLIC_ROUTER_ERRORS = _CONTINUATION_ERRORS | _REQUEST_CONTRACT_ERRORS | PUBLIC_CITATION_ERRORS | frozenset((
    'web_bridge_response_busy', 'web_bridge_browser_busy',
    'web_bridge_turn_consumed_no_retry', 'web_bridge_admission_limit',
    'web_browser_driver_failed_no_retry', 'web_mcp_turn_closed', 'web_bridge_closed',
    'web_mcp_context_not_read',
    'web_native_turn_identity_required', 'web_bridge_endpoint_already_owned',
    'web_explicit_route_required', 'web_provider_object_required',
    'web_mcp_payload_too_large', 'web_mcp_native_wait_already_owned',
    'web_mcp_call_already_released', 'web_turn_metadata_json_object_required',
    'web_workspace_telemetry_shape_unsupported',
    'web_desktop_locked_before_dispatch', 'web_desktop_unavailable_before_dispatch',
    'web_browser_assistance_pending_before_dispatch',
    'web_browser_login_required_before_dispatch', 'web_browser_challenge_required_before_dispatch'))


class WebResponsesProvider:
    def __init__(self, bridge):
        self.bridge = bridge
        self.token = secrets.token_urlsafe(32)
        self.host = None
        self.runner = None
        self.closed = False
        self.requests = 0
        self.admission_state = 'ready'
        self.admission_guard = None
        self.connection_status = None

    async def start(self, *, port=0):
        require(not self.closed and self.runner is None, 'web_provider_already_started_or_closed')
        require(type(port) is int and 0 <= port <= 65535, 'web_provider_port_invalid')
        application = web.Application(client_max_size=MAX_BODY)
        application.router.add_route('*', '/{tail:.*}', self.handle)
        self.runner = web.AppRunner(application, access_log=None,
            handler_cancellation=True, auto_decompress=False)
        try:
            await self.runner.setup()
            site = web.TCPSite(self.runner, '127.0.0.1', port)
            await site.start()
            self.host = '127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
            return 'http://' + self.host + '/v1'
        except BaseException:
            await self.stop()
            raise

    @staticmethod
    def error(code, status, **details):
        details.setdefault('message', '本次请求未能完成，系统不会自动重做。')
        details.setdefault('retryable', False)
        # Codex retries 408/409/5xx even when the JSON says retryable=false.
        # These Web-owned outcomes are terminal, including partial execution.
        # Keep the original cause explicit; native/upstream router errors are
        # outside this boundary. Authentication and capacity statuses stay exact.
        if status in (408, 409, 429) or 500 <= status <= 599:
            details['cause_http_status'] = status
            status = 400
        if 'transport' in details:
            # Only the request-local bridge observer supplies this projection.
            # Native clients may display just message, so keep the same bounded
            # transport facts readable without suggesting execution succeeded.
            turn = details['transport']['turn']
            released, results = turn['calls_released'], turn['results_received']
            details['message'] += ('本轮本机未转交工具调用。' if released == 0 else
                f'本轮已向原生接口转交 {released} 次工具调用，收到 {results} 份配对结果；'
                '配对结果不代表执行成功。')
        return web.json_response({'error': {'code': code, **details}}, status=status,
            headers={'Cache-Control': 'no-store'})

    async def handle(self, request):
        if self.closed:
            return self.error('web_provider_closed', 503)
        if (request.host != self.host or request.query_string
                or request.headers.get('Origin') not in (None, 'http://' + self.host)):
            return self.error('web_provider_endpoint_rejected', 403)
        authorization = request.headers.get('Authorization', '')
        if not secrets.compare_digest(authorization.encode('utf-8'),
                ('Bearer ' + self.token).encode('utf-8')):
            return self.error('web_provider_auth_required', 401)
        if request.path == '/health' and request.method == 'GET':
            state = self.current_admission()
            return web.json_response({'ready': True, 'active': self.bridge.turn is not None,
                'requests': self.requests, 'state': state,
                'accepting_requests': state == 'ready',
                'transport': self.bridge.diagnostics(),
                'mcp': self.bridge.endpoint.diagnostics(),
                **({'connection': self.connection_status()} if self.connection_status is not None else {})},
                headers={'Cache-Control': 'no-store'})
        if request.path != '/v1/responses':
            return self.error('web_provider_route_not_found', 404)
        if request.method != 'POST':
            return web.Response(status=405, headers={'Allow': 'POST'})
        if request.content_type != 'application/json':
            return self.error('web_provider_json_required', 415)
        self.requests += 1
        failure_transport = None

        def observe_failure(value):
            nonlocal failure_transport
            failure_transport = value

        def failure_details():
            return {'transport': failure_transport} if failure_transport is not None else {}

        try:
            raw = await asyncio.wait_for(request.read(), 10)
            payload = decode_request(raw, request.headers.get('Content-Encoding', 'identity'), strict=True)
            require(isinstance(payload, dict), 'web_provider_object_required')
            # Check after the awaited body read: a concurrent assist/stop action
            # must close admission even for an HTTP request already in flight.
            # Draining keeps exact tool-result continuation alive, but never
            # admits a new browser generation or consumes its native identity.
            state = self.current_admission()
            if state != 'ready':
                continuing = (state == 'draining' and self.bridge.turn is not None
                    and not self.bridge.turn.closed
                    and self.bridge.identity(payload) == self.bridge.owner)
                if not continuing:
                    code = ('web_browser_assistance_pending_before_dispatch' if state == 'assistance'
                        else 'web_connection_required_before_dispatch' if state == 'connection'
                        else 'web_connection_reconnecting_before_dispatch' if state == 'reconnecting'
                        else 'web_provider_draining' if state == 'draining' else 'web_provider_not_accepting')
                    message = ('网页连接需要人工协助。请主动打开 Operator 辅助窗口，完成登录或验证后关闭窗口，再发送新消息。本次没有向网页模型发送消息。'
                        if state == 'assistance' else '网页服务正在停止，本次新请求未接纳。'
                        if state == 'draining' else '工具连接正在恢复，地址和已授权插件仍保留。本次没有向网页模型发送消息，请连接恢复后再发新消息。'
                        if state == 'reconnecting' else '请先完成当前网页工具连接的绑定，再发送新消息。本次没有向网页模型发送消息。'
                        if state == 'connection' else '网页服务当前不可用，请检查连接状态。本次没有向网页模型发送消息。')
                    return self.error(code, 503, message=message)
            response, events = await self.bridge.exchange(payload, on_failure=observe_failure)
            # Bridge terminal validation has already preflighted all serialized
            # event JSON bounds. Framing changes neither text nor call identities.
            if payload.get('stream', False):
                body = ''.join('event: ' + event['type'] + '\ndata: ' + dumps(event) + '\n\n'
                    for event in events).encode('utf-8')
                return web.Response(body=body, content_type='text/event-stream',
                    headers={'Cache-Control': 'no-store'})
            return web.json_response(response, dumps=dumps, headers={'Cache-Control': 'no-store'})
        except asyncio.CancelledError:
            # AppRunner cancellation reaches bridge.exchange, which closes its
            # owned browser generation. An uncertain response is never replayed.
            raise
        except RequestSizeError as error:
            return self.error('web_provider_request_too_large', 413,
                limit_bytes=error.limit, scope=error.scope,
                observation='local_request_preflight',
                message=f'当前 Web 请求解码后超过连接的 {error.limit} 字节限制（decoded_request），'
                    '本次未提交网页模型。原任务和历史保留；可切回原生模型继续。无需重新登录，不会截断或自动重做。')
        except web.HTTPRequestEntityTooLarge:
            return self.error('web_provider_request_too_large', 413,
                limit_bytes=MAX_BODY, scope='http_request',
                observation='local_request_preflight',
                message=f'当前 Web 请求正文超过连接的 {MAX_BODY} 字节限制（http_request），'
                    '本次未提交网页模型。原任务和历史保留；可切回原生模型继续。无需重新登录，不会截断或自动重做。')
        except asyncio.TimeoutError:
            return self.error('web_provider_request_timeout_no_retry', 408,
                message='本次请求等待超时，已停止等待；已有操作不会自动重做。', **failure_details())
        except WebBrowserHttpError as error:
            return self.error(str(error), 502, upstream_status=error.upstream_status,
                message=f'网页模型拒绝了本次生成请求（HTTP {error.upstream_status}），已停止等待，未自动重试。'
                    '登录状态或 Pro 标识不能单独证明生成接口当前可用。', **failure_details())
        except WebRequestCapacityError as error:
            return self.error(str(error), 413, observation='local_request_preflight',
                scope='indexed_context', limit_pages=24, reply_limit_bytes=INDEX_REPLY_BYTES,
                single_use_read_limit=INDEX_READ_LIMIT,
                message='当前任务的历史或工具说明超出此网页连接的读取容量，本次未向网页模型提交，也未执行本机工具。'
                    '原任务与历史保留；可以切回原生模型继续，或另建较小的 Web 任务。'
                    '无需重新登录，系统不会截断历史或自动重做。', **failure_details())
        except WebBrowserNetworkError as error:
            return self.error(str(error), 502, network_error=error.network_error,
                observation='browser_network', retryable=False,
                message='网页模型的网络连接发生中断或传输错误，本次请求已停止，不会自动重发。'
                    '请先检查网络和后台连接状态；已有登录与固定连接配置保留，无需重新创建。'
                    '此前可能已有部分操作完成，请先核对结果。', **failure_details())
        except WebBrowserFinalTimeout as error:
            return self.error(str(error), 504, observation='browser_wait',
                message='网页回复等待超时，本次请求已停止，未自动重做。'
                    '这不表示登录已过期；已有认证和固定连接配置仍保留。'
                    '此前可能已有部分操作完成，请先核对结果与后台状态。', **failure_details())
        except WebBrowserUiError as error:
            code = str(error)
            message = {
                'web_tool_confirmation_required_no_retry':
                    '网页显示本次工具操作需要单独确认，因此本次请求已停止。长期授权和固定连接仍保留；需要人工确认的操作请在可见的 ChatGPT 会话中处理。',
                'web_session_expired_during_generation_no_retry':
                    '网页在本次请求中显示登录已过期。请打开 Operator 辅助窗口完成登录；不需要重新创建插件或密钥。',
                'web_subscription_unavailable_during_generation_no_retry':
                    '网页显示暂时无法加载账号订阅。请先在 Operator 辅助窗口检查账号页面；这不是本机工具执行失败的证据。',
                'web_response_error_no_retry':
                    '网页显示本次回复发生错误，已停止等待。这不是本机工具执行失败的证据。',
            }[code]
            return self.error(code, 409 if code == 'web_tool_confirmation_required_no_retry' else 502,
                message=message + '本次可能已有部分操作完成，系统不会自动重做。',
                observation='public_ui', retryable=False, **failure_details())
        except RouterError as error:
            code = str(error)
            # A syntactically plausible exception string can still contain a
            # private value. Only fixed, known protocol labels cross HTTP.
            if code not in _PUBLIC_ROUTER_ERRORS:
                code = 'web_provider_protocol_rejected'
            status = 409 if code in {'web_bridge_response_busy', 'web_bridge_browser_busy',
                'web_bridge_turn_consumed_no_retry', 'web_bridge_admission_limit'} else 400
            if code in {'web_browser_driver_failed_no_retry', 'web_mcp_turn_closed', 'web_bridge_closed',
                    'web_mcp_context_not_read'} or code in PUBLIC_CITATION_ERRORS:
                status = 502
            if code in {'web_desktop_locked_before_dispatch', 'web_desktop_unavailable_before_dispatch'}:
                return self.error(code, 503, message='请解锁并打开这台 Windows 的桌面，再发送新消息。此次没有向网页模型发送消息。', **failure_details())
            if code == 'web_browser_assistance_pending_before_dispatch':
                return self.error(code, 503, message='请先在已打开的 Operator 辅助窗口完成登录或验证，然后关闭该窗口，再发送新消息。本次未向模型发送消息。', **failure_details())
            if code in {'web_browser_login_required_before_dispatch', 'web_browser_challenge_required_before_dispatch'}:
                action = '登录' if code == 'web_browser_login_required_before_dispatch' else '真人验证'
                return self.error(code, 503, message='网页模型需要完成' + action
                    + '。请打开 Operator 登录辅助窗口，完成后关闭窗口，再发送新消息。本次未向模型发送消息。', **failure_details())
            if code in {'web_bridge_response_busy', 'web_bridge_browser_busy'}:
                message = '网页连接正在处理另一个请求，本次请求未接纳；请等待当前请求结束。'
            elif code in {'web_bridge_turn_consumed_no_retry', 'web_bridge_admission_limit'}:
                message = '本次请求不能再次接纳，系统不会重新执行已经消费的轮次。'
            elif code == 'web_mcp_context_not_read':
                message = '网页已结束回复，但尚未读完本次请求的上下文，因此该回复未作为任务结果返回。'
                message += '这不表示登录失效；已有连接配置保留，本次不会自动重做。'
            elif code in PUBLIC_CITATION_ERRORS:
                message = '网页已返回回复，但其中的来源引用未通过完整校验，因此没有将它作为结果返回。'
                message += '登录和连接配置保留，本次不会自动重做。'
            elif code in {'web_browser_driver_failed_no_retry', 'web_mcp_turn_closed', 'web_bridge_closed'}:
                message = '网页请求未能完成，已停止等待。本次可能已有部分操作完成，系统不会自动重做。'
            elif code == 'opaque_cross_provider_context_not_supported':
                message = '当前任务包含此 Web 连接无法读取的加密历史或压缩记录，已停止本次请求。'
                message += '请使用从第一轮就选择 Web 模型的新任务；原任务和历史保留。无需重新登录，系统不会自动重做。'
            elif code in _REQUEST_CONTRACT_ERRORS:
                message = '当前任务的工具或历史格式尚不受此 Web 连接支持，已停止本次请求；无需重新登录，系统不会自动重做。'
            else:
                message = '本次请求或工具结果未通过接续校验，已停止等待；已有操作不会自动重做。'
            return self.error(code, status, message=message, **failure_details())
        except Exception:
            return self.error('web_provider_failed_no_retry', 500, **failure_details())

    def current_admission(self):
        if self.admission_guard is not None and not self.admission_guard():
            return ('connection' if self.admission_state in ('ready', 'connection') else
                'stopped' if self.admission_state == 'draining' else self.admission_state)
        return self.admission_state

    async def stop(self):
        self.admission_state = 'stopped'
        self.closed = True
        await self.bridge.stop()
        if self.runner is not None:
            runner, self.runner = self.runner, None
            await runner.cleanup()
