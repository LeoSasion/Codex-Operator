"""Opt-in Web MCP continuation. No file, shell, browser or tool execution.

One native Responses conversation owns one browser turn. MCP carries structured
calls into the native client and waits for its exact paired results. This module
does not register models, expose native credentials, or parse calls from prose.
"""
import asyncio
from collections import deque
from copy import deepcopy
import json
import re
import secrets
import time

from aiohttp import web

from .responses_capabilities import RouterError
from .responses_tool_adapter import MAX_ARGUMENT_BYTES, dumps, loads
from .web_model_protocol import WebModelProtocol, PUBLIC_CITATION_ERRORS


def require(value, code):
    if not value:
        raise RouterError(code)


def encoded(value, maximum=2 * 1024 * 1024):
    raw = dumps(value)
    require(len(raw.encode("utf-8")) <= maximum, "web_mcp_payload_too_large")
    return raw


def same_json(left, right):
    """Compare JSON data without equating booleans/numbers or reordering arrays.

    Object key order is irrelevant, but text and every JSON value/type remain
    exact. This is an in-memory comparison, never a rewritten request or log.
    """
    options = {'ensure_ascii': False, 'sort_keys': True, 'separators': (',', ':'),
        'allow_nan': False}
    return json.dumps(left, **options) == json.dumps(right, **options)


def web_page_search_projection(payload):
    """Bind one live hosted-search advertisement to Web's own search.

    This Web-only representation cannot emit a Codex web_search_call. The
    original request remains in the caller; unsupported search constraints
    fail before browser dispatch rather than being silently discarded.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('tools'), list):
        return payload, None
    source = payload['tools']
    search = [(index, tool) for index, tool in enumerate(source) if isinstance(tool, dict)
        and tool.get('type') == 'web_search']
    if not search:
        return payload, None
    require(len(search) == 1 and payload.get('tool_choice', 'auto') == 'auto',
        'unsupported_tool_type')
    source_index, source_tool = search[0]
    require(source_tool.get('external_web_access') is True
        and set(source_tool) in ({'type', 'external_web_access'},
            {'type', 'external_web_access', 'search_content_types'})
        and source_tool.get('search_content_types', ['text']) in (['text'], ['text', 'image']),
        'unsupported_tool_type')
    # Copy only tool declarations here. WebModelProtocol takes its own bounded
    # input/history snapshot; duplicating an entire native body at this gate
    # would compound the existing large-request memory cost.
    projected = dict(payload)
    projected['tools'] = [deepcopy(tool) for index, tool in enumerate(source)
        if index != source_index]
    # The projected protocol cannot bind this removed declaration. Preserve
    # its complete source and position privately across native tool returns.
    return projected, {'source_index': source_index, 'source_tool': deepcopy(source_tool)}


class QuickTunnelAnnouncement:
    """Parse the explicit cloudflared banner and subsequent connection report.

    This is a process announcement, not a public reachability probe or account
    authorization. Error URLs and API request URLs never supply an endpoint.
    The caller must also retain and observe the exact live child process.
    """
    def __init__(self):
        self.origin = None
        self.connected = False
        self._banner = False

    def feed(self, line):
        require(isinstance(line, str) and len(line.encode('utf-8')) <= 16384,
            'web_tunnel_log_line_invalid')
        if ' INF |  Your quick Tunnel has been created! Visit it at ' in line:
            self._banner = True
        match = re.fullmatch(r'\S+ INF \|\s+(https://([a-z0-9-]+)\.trycloudflare\.com)\s+\|\s*', line)
        if self._banner and match and match[2] not in ('api', 'www'):
            require(self.origin is None or self.origin == match[1], 'web_tunnel_address_changed')
            self.origin = match[1]
        if self.origin and re.search(r' INF Registered tunnel connection connIndex=\d+ ', line):
            self.connected = True
        return self.connected


INDEX_REPLY_BYTES = 48 * 1024
INDEX_READ_LIMIT = 40
INDEX_PROTOCOLS = ('mcp_indexed_request_v1', 'mcp_catalog_pages_v2', 'mcp_context_records_v3')


class IndexedWebRequest:
    """Lossless context pages plus on-demand, exact native tool declarations.

    Independent implementation inspired by WebCodex's targeted discovery. Read
    handles are current-turn transport data, not caller identity or permission.
    The two existing MCP tool schemas remain sufficient: operator_begin reads
    each server-issued key once; operator_call always uses the root turn key.
    """
    wire_protocol = INDEX_PROTOCOLS[0]
    begin_result_mode = 'text_v1'

    def __init__(self, protocol, *, wire_protocol=INDEX_PROTOCOLS[0], begin_result_mode='text_v1', source_user_preview=None):
        require(wire_protocol in INDEX_PROTOCOLS, 'web_mcp_index_protocol_invalid')
        require(begin_result_mode in ('text_v1', 'structured_begin_v1'), 'web_mcp_begin_result_mode_invalid')
        require(wire_protocol != INDEX_PROTOCOLS[2] or begin_result_mode == 'structured_begin_v1',
            'web_mcp_index_protocol_invalid')
        if source_user_preview is not None:
            source = protocol.source_input()
            require(wire_protocol == INDEX_PROTOCOLS[2]
                and isinstance(source, list) and bool(source)
                and isinstance(source_user_preview, dict)
                and set(source_user_preview) == {'source_input_index', 'source_message'}
                and type(source_user_preview.get('source_input_index')) is int
                and source_user_preview['source_input_index'] == len(source) - 1
                and same_json(source_user_preview.get('source_message'), source[-1]),
                'web_mcp_current_user_preview_unbound')
            message = source[-1]
            require(isinstance(message, dict) and message.get('role') == 'user'
                and message.get('type', 'message') == 'message'
                and set(message) <= {'type', 'role', 'content', 'id', 'status'},
                'web_mcp_current_user_preview_unbound')
            content = message.get('content')
            require(isinstance(content, str) or isinstance(content, list) and bool(content)
                and all(isinstance(part, dict) and set(part) == {'type', 'text'}
                    and part.get('type') == 'input_text' and isinstance(part.get('text'), str)
                    for part in content), 'web_mcp_current_user_preview_unbound')
            encoded(source_user_preview, 16384)
        self.wire_protocol = wire_protocol
        self.begin_result_mode = begin_result_mode
        self.pages = {}
        self.expected = {}
        self.context_complete = False
        self.catalog_complete = False
        self.described = set()
        self.discovered = set()
        self.reads = 0
        request = protocol.request()
        present = 'tools' in request
        tools = request.pop('tools', [])
        descriptors = {tool['name']: tool for tool in protocol.mcp_tools()}
        sources = protocol.mcp_tool_sources()
        catalog = []
        for index, tool in enumerate(tools):
            name = tool['name']
            handle = self.fragments('schema', {'request_tool': tool,
                'mcp_tool': descriptors[name]}, name=name)
            catalog.append({'index': index, 'name': name, 'source': sources[name],
                'schema_read_key': handle})
        self.catalog_key = (self.catalog_pages(catalog) if wire_protocol in INDEX_PROTOCOLS[1:]
            else self.fragments('catalog', catalog)) if catalog else None
        context = {'request': request, 'tools_present': present, 'tool_count': len(tools)}
        self.first_key = (self.context_records(context, source_user_preview=source_user_preview) if wire_protocol == INDEX_PROTOCOLS[2]
            else self.fragments('context', context, maximum_pages=24,
                final_fields={'catalog_read_key': self.catalog_key}))
        self.page_reads = {'context': 0, 'catalog': 0, 'schema': 0}
        self.page_totals = {section: sum(row[1] == section for row in self.pages.values())
            for section in ('context', 'catalog')}

    def fits(self, value):
        # Reserve more than the bounded string RPC id or Python JSON integer
        # representation can require. Budget the explicitly selected envelope;
        # structuredContent does not have the legacy text block's extra escaping.
        # Both representations retain the same complete 48 KiB response bound.
        result = ({'structuredContent': value, 'content': [], 'isError': False}
            if self.begin_result_mode == 'structured_begin_v1' else
            {'content': [{'type': 'text', 'text': dumps(value)}], 'isError': False})
        return len(dumps({'jsonrpc': '2.0', 'id': 'x' * 8192,
            'result': result}).encode('utf8')) <= INDEX_REPLY_BYTES

    def fragments(self, section, value, *, name=None, maximum_pages=24, final_fields=None):
        raw = encoded(value, 16 * 1024 * 1024)
        pieces, offset = [], 0
        while offset < len(raw):
            count = min(32768, len(raw) - offset)
            def fits_count(size):
                candidate = {'protocol': self.wire_protocol, 'section': section,
                    'index': 999, 'total': 999, 'json_fragment': raw[offset:offset+size],
                    'next_read_key': 'f'*64, **(final_fields or {})}
                return self.fits(candidate)
            if not fits_count(count):
                # Each additional Unicode scalar adds serialized bytes. Find
                # the largest fitting prefix instead of leaving a half-full
                # page after rounding its character count down by powers of 2.
                lower, upper = 0, count - 1
                while lower < upper:
                    middle = (lower + upper + 1) // 2
                    if fits_count(middle): lower = middle
                    else: upper = middle - 1
                count = lower
            require(count > 0, 'web_mcp_index_page_too_large')
            pieces.append(raw[offset:offset+count])
            offset += count
            require(len(pieces) <= maximum_pages, 'web_mcp_index_section_too_large')
        return self.store_pages(section, [{'json_fragment': piece} for piece in pieces],
            name=name, final_fields=final_fields)

    def catalog_pages(self, catalog):
        """Whole entries per page, preserving every original index and identity.

        Discovering one page permits only its entries' schemas. Other pages stay
        available in order; neither discovery nor a name alone releases a call.
        """
        encoded(catalog, 16 * 1024 * 1024)
        pieces, offset = [], 0
        while offset < len(catalog):
            lower, upper = 0, len(catalog) - offset
            while lower < upper:
                count = (lower + upper + 1) // 2
                candidate = {'protocol': self.wire_protocol, 'section': 'catalog',
                    'index': 999, 'total': 999, 'entries': catalog[offset:offset+count],
                    'next_read_key': 'f' * 64}
                if self.fits(candidate): lower = count
                else: upper = count - 1
            require(lower > 0, 'web_mcp_index_page_too_large')
            pieces.append({'entries': catalog[offset:offset+lower]})
            offset += lower
            require(len(pieces) <= 24, 'web_mcp_index_section_too_large')
        return self.store_pages('catalog', pieces)

    def context_records(self, context, *, source_user_preview=None):
        """Preserve complete request fields and ordered input records as data.

        Whole records avoid JSON-inside-JSON for normal messages. An oversized
        record alone uses indexed fragments; never split, merge or re-role its
        content parts. This representation does not attest model comprehension.
        """
        encoded(context, 16 * 1024 * 1024)
        request = deepcopy(context['request'])
        present = 'input' in request
        source = request.pop('input', None)
        shape = 'array' if isinstance(source, list) else 'value' if present else 'absent'
        records = [{'kind': 'request_fields', 'value': request,
            'tools_present': context['tools_present'], 'tool_count': context['tool_count'],
            'input_format': shape,
            **({'input_count': len(source)} if shape == 'array' else {})}]
        if source_user_preview is not None:
            # Same bounded original-message copy as the explicit composer mode,
            # now available as structured data at the context header. It is not
            # inserted into request.input or assigned new authority. Full input
            # records, their order and every read/schema gate remain unchanged.
            records[0]['current_user_preview'] = deepcopy(source_user_preview)
        if shape == 'array':
            records.extend({'kind': 'input_item', 'request_input_index': index, 'value': item}
                for index, item in enumerate(source))
        elif shape == 'value':
            records.append({'kind': 'input_value', 'value': source})

        def fits_records(values):
            return self.fits({'protocol': self.wire_protocol, 'section': 'context',
                'index': 999, 'total': 999, 'records': values, 'next_read_key': 'f' * 64,
                'catalog_read_key': self.catalog_key})

        empty = {'protocol': self.wire_protocol, 'section': 'context', 'index': 999,
            'total': 999, 'records': [], 'next_read_key': 'f' * 64,
            'catalog_read_key': self.catalog_key}
        overhead = len(dumps({'jsonrpc': '2.0', 'id': 'x' * 8192,
            'result': {'structuredContent': empty, 'content': [], 'isError': False}}).encode('utf8'))
        entries, tail_bytes, tail_count = [], 0, 0

        def append_entry(entry):
            nonlocal tail_bytes, tail_count
            size = len(dumps(entry).encode('utf8'))
            if tail_count and overhead + tail_bytes + 1 + size > INDEX_REPLY_BYTES:
                tail_bytes, tail_count = 0, 0
            tail_bytes += size + (1 if tail_count else 0)
            tail_count += 1
            entries.append(entry)

        for record_index, value in enumerate(records):
            whole = {'record_index': record_index, 'encoding': 'json', 'value': value}
            if fits_records([whole]):
                append_entry(whole)
                continue
            raw, offset, fragments = dumps(value), 0, []
            while offset < len(raw):
                def fragment(size):
                    return {'record_index': record_index, 'encoding': 'json_fragment',
                        'fragment_index': 999, 'fragment_total': 999,
                        'json_fragment': raw[offset:offset + size]}
                # A v3 record fragment is already structured JSON. The legacy
                # 32K character cap leaves ASCII-heavy records unnecessarily
                # split; the complete encoded RPC budget is the real bound.
                # At most INDEX_REPLY_BYTES characters are considered, and
                # fits_records still accounts for escaping, Unicode and IDs.
                def fits_fragment(size):
                    return overhead + tail_bytes + (1 if tail_count else 0) \
                        + len(dumps(fragment(size)).encode('utf8')) <= INDEX_REPLY_BYTES
                if tail_count and not fits_fragment(1):
                    tail_bytes, tail_count = 0, 0
                lower, upper = 0, min(INDEX_REPLY_BYTES, len(raw) - offset)
                while lower < upper:
                    middle = (lower + upper + 1) // 2
                    if fits_fragment(middle): lower = middle
                    else: upper = middle - 1
                require(lower > 0, 'web_mcp_index_page_too_large')
                part = fragment(lower)
                fragments.append(part)
                append_entry(part)
                offset += lower
                require(len(fragments) <= 24, 'web_mcp_index_section_too_large')
            for index, entry in enumerate(fragments):
                entry.update(fragment_index=index, fragment_total=len(fragments))

        # Structured mode has one JSON layer. Use exact serialized entry sizes
        # for packing, avoiding repeated serialization of a growing long page.
        pages, pending, pending_bytes = [], [], 0
        for entry in entries:
            entry_bytes = len(dumps(entry).encode('utf8'))
            if pending and overhead + pending_bytes + 1 + entry_bytes > INDEX_REPLY_BYTES:
                pages.append({'records': pending})
                pending, pending_bytes = [], 0
                require(len(pages) < 24, 'web_mcp_index_section_too_large')
            require(fits_records([entry]), 'web_mcp_index_page_too_large')
            pending_bytes += entry_bytes + (1 if pending else 0)
            pending.append(entry)
        if pending: pages.append({'records': pending})
        require(0 < len(pages) <= 24, 'web_mcp_index_section_too_large')
        return self.store_pages('context', pages,
            final_fields={'catalog_read_key': self.catalog_key})

    def store_pages(self, section, pieces, *, name=None, final_fields=None):
        keys = [secrets.token_hex(32) for _ in pieces]
        self.expected[(section, name)] = keys[0]
        for index, (key, contents) in enumerate(zip(keys, pieces)):
            final = index == len(pieces)-1
            page = {'protocol': self.wire_protocol, 'section': section,
                'index': index, 'total': len(pieces), **contents,
                'next_read_key': None if final else keys[index+1],
                **((final_fields or {}) if final else {})}
            require(self.fits(page), 'web_mcp_index_page_too_large')
            require(key not in self.pages and len(self.pages) < 4096, 'web_mcp_index_capacity')
            self.pages[key] = (page, section, name, final)
        return keys[0]

    def read(self, key):
        require(isinstance(key, str) and key in self.pages, 'web_mcp_read_key_unavailable')
        require(self.reads < INDEX_READ_LIMIT, 'web_mcp_read_limit')
        page, section, name, final = self.pages[key]
        require(section == 'context' or self.context_complete, 'web_mcp_context_not_read')
        if section == 'schema':
            if self.wire_protocol in INDEX_PROTOCOLS[1:]:
                require(name in self.discovered, 'web_mcp_catalog_entry_not_read')
            else:
                require(self.catalog_complete, 'web_mcp_catalog_not_read')
        require(self.expected[(section, name)] == key, 'web_mcp_read_out_of_order')
        # Consume before returning; uncertain deliveries cannot replay this page.
        del self.pages[key]
        self.expected[(section, name)] = page['next_read_key']
        self.reads += 1
        self.page_reads[section] += 1
        if section == 'catalog' and self.wire_protocol in INDEX_PROTOCOLS[1:]:
            self.discovered.update(entry['name'] for entry in page['entries'])
        if section == 'context' and final: self.context_complete = True
        if section == 'catalog' and final: self.catalog_complete = True
        if section == 'schema' and final: self.described.add(name)
        return deepcopy(page)

    def read_observation(self):
        """Consumed local pages, not delivery, model comprehension or execution.

        Retain fixed counts after close without exporting keys, tool names,
        fragments, argument schemas or source identities.
        """
        return {'context_pages_read': self.page_reads['context'],
            'context_pages_total': self.page_totals['context'],
            'catalog_pages_read': self.page_reads['catalog'],
            'catalog_pages_total': self.page_totals['catalog'],
            'schema_pages_read': self.page_reads['schema'],
            'schemas_complete': len(self.described)}


class WebMcpTurn:
    """Single-loop, single-call transport; all state transitions are explicit."""

    def __init__(self, protocol, *, timeout=180, call_limit=16, check_call=None,
                 web_page_search_binding=None):
        require(10 <= timeout <= 900 and 1 <= call_limit <= 32, "web_mcp_limits_invalid")
        self.protocol = protocol
        # Keep 256 random bits while avoiding punctuation that the public JSON
        # representation escapes. A model must still copy the exact current key.
        self.key = secrets.token_hex(32)
        self.deadline = time.monotonic() + timeout
        self.call_limit = call_limit
        self.check_call = check_call
        self._web_page_search_binding = deepcopy(web_page_search_binding)
        self.begun = False
        self.closed = False
        self.client_cancelled = False
        self.pending = None
        self.calls = 0
        self.released_calls = 0
        self.results = 0
        self.final_returned = False
        self.frames = asyncio.Queue(maxsize=1)
        self._seen_rpc = set()
        self._waiting_native = False
        self._final_queued = False
        self._input = deepcopy(protocol.request().get("input"))
        self._source_input = protocol.source_input()
        self._contract = protocol.continuation_contract()
        self._tools = protocol.mcp_tools()
        self.indexed = None
        self.binding_changes = None

    def guard(self, key):
        require(isinstance(key, str) and secrets.compare_digest(key, self.key), "web_mcp_turn_rejected")
        require(not self.closed and time.monotonic() < self.deadline, "web_mcp_turn_closed")

    def preview_begin(self):
        """Preflight the exact complete MCP payload without consuming begin."""
        request = {"request": self.protocol.request(), "tools": deepcopy(self._tools),
            "resultRepresentation": "Complete original Codex function result as labelled JSON; no local execution by this server."}
        encoded(request, 16 * 1024 * 1024)
        return request

    def prepare_indexed(self, *, wire_protocol=INDEX_PROTOCOLS[0], begin_result_mode='text_v1', source_user_preview=None):
        self.guard(self.key)
        require(not self.begun and self.indexed is None, 'web_mcp_index_already_prepared')
        self.preview_begin()  # Preserve the existing complete-data bound.
        try:
            self.indexed = IndexedWebRequest(self.protocol, wire_protocol=wire_protocol,
                begin_result_mode=begin_result_mode, source_user_preview=source_user_preview)
        except RouterError as error:
            if str(error) == 'web_mcp_index_section_too_large':
                # Only this local, complete-data preflight can classify capacity.
                # No page, browser request or executable call has been released.
                raise WebRequestCapacityError() from None
            raise

    def begin(self, key):
        if self.indexed is not None:
            self.guard(self.key)
            require(not self._final_queued and self.pending is None, 'web_mcp_call_out_of_order')
            if isinstance(key, str) and secrets.compare_digest(key, self.key):
                require(not self.begun, 'web_mcp_begin_already_consumed')
                page = self.indexed.read(self.indexed.first_key)
                self.begun = True
                return page
            require(self.begun, 'web_mcp_turn_rejected')
            return self.indexed.read(key)
        self.guard(key)
        require(not self.begun, "web_mcp_begin_already_consumed")
        request = self.preview_begin()
        self.begun = True
        return request

    async def invoke(self, key, rpc_id, name, arguments, *, session_id=None):
        self.guard(key)
        require(self.begun and not self._final_queued and self.pending is None and self.frames.empty(), "web_mcp_call_out_of_order")
        if self.indexed is not None:
            require(self.indexed.context_complete, 'web_mcp_context_not_read')
            require(isinstance(name, str) and name in self.indexed.described, 'web_mcp_schema_not_read')
        require(type(rpc_id) in (str, int), "web_mcp_request_id_required")
        require(session_id is None or isinstance(session_id, str) and 0 < len(session_id) <= 128,
            "web_mcp_session_invalid")
        identity = (session_id, type(rpc_id).__name__, rpc_id)
        require(identity not in self._seen_rpc, "web_mcp_duplicate_no_retry")
        require(self.calls < self.call_limit, "web_mcp_call_limit")
        require(isinstance(name, str) and any(t["name"] == name for t in self._tools), "web_mcp_unknown_tool")
        require(isinstance(arguments, dict), "web_mcp_object_arguments_required")
        argument_json = encoded(arguments, MAX_ARGUMENT_BYTES)
        if self.check_call is not None:
            self.check_call(name, deepcopy(arguments))
        call_id = "call_operator_web_" + secrets.token_hex(16)
        call = {"type": "function_call", "id": "fc_" + secrets.token_hex(12),
            "call_id": call_id, "name": name, "arguments": argument_json, "status": "completed"}
        # The existing terminal validator applies declared names, tool choice,
        # argument bounds, and custom-wrapper identity before releasing a call.
        response, events = self.protocol.complete({"id": "resp_" + secrets.token_hex(16),
            "object": "response", "status": "completed", "model": self.protocol.route.model,
            "output": [call], "usage": None})
        future = asyncio.get_running_loop().create_future()
        self.pending = {"call": call, "future": future, "released": False, "rpc_identity": identity}
        self._seen_rpc.add(identity)
        self.calls += 1
        self.frames.put_nowait((response, events))
        try:
            return await asyncio.wait_for(asyncio.shield(future), max(0.01, self.deadline - time.monotonic()))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.close()
            raise

    async def next_response(self):
        self.guard(self.key)
        require(not self._waiting_native, "web_mcp_native_wait_already_owned")
        self._waiting_native = True
        try:
            frame = await asyncio.wait_for(self.frames.get(), max(0.01, self.deadline - time.monotonic()))
            self.guard(self.key)
            if self.pending is not None:
                require(not self.pending["released"], "web_mcp_call_already_released")
                self.pending["released"] = True
                self.released_calls += 1
            elif self._final_queued:
                self.final_returned = True
            return frame
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.close()
            raise
        finally:
            self._waiting_native = False

    def accept_result(self, protocol):
        try:
            self._accept_result(protocol)
        except RouterError:
            # A rejected continuation is terminal, including for direct users
            # of this transport. Never wait for a repaired or replayed result.
            self.close()
            raise

    def _accept_result(self, protocol):
        self.guard(self.key)
        pending = self.pending
        require(pending is not None and pending["released"], "web_mcp_result_without_call")
        request = protocol.request()
        route_changed = protocol.route != self.protocol.route
        tools_changed = protocol.mcp_tools() != self._tools
        contract_changed = protocol.continuation_contract() != self._contract
        if route_changed or tools_changed or contract_changed:
            self.binding_changes = {'route': route_changed, 'tools': tools_changed,
                'controls': protocol.continuation_changes(self.protocol)}
            raise RouterError('web_mcp_request_binding_changed')
        items = request.get("input")
        require(isinstance(self._input, list) and isinstance(items, list)
            and same_json(items[:len(self._input)], self._input), "web_mcp_history_changed")
        suffix = items[len(self._input):]
        require(len(suffix) == 2, "web_mcp_exact_call_result_required")
        call, result = suffix
        original = pending["call"]
        require(isinstance(call, dict) and call.get("type") == "function_call"
            and all(call.get(k) == original[k] for k in ("call_id", "name", "arguments")),
            "web_mcp_call_identity_changed")
        require(isinstance(result, dict) and result.get("type") == "function_call_output"
            and result.get("call_id") == original["call_id"], "web_mcp_result_identity_changed")
        output = result.get("output")
        require(isinstance(output, str) or isinstance(output, list) and all(
            isinstance(p, dict) and p.get("type") in ("input_text", "output_text", "text")
            and isinstance(p.get("text"), str) for p in output), "web_mcp_text_result_required")
        # Label and preserve the entire original object, rather than inventing
        # success or extracting/normalizing its text. Executable code stays data.
        original_input = protocol.source_input()
        require(isinstance(self._source_input, list) and isinstance(original_input, list)
            and len(original_input) == len(self._source_input) + 2
            and same_json(original_input[:len(self._source_input)], self._source_input),
            "web_mcp_history_changed")
        require(isinstance(original_input[-1], dict)
            and original_input[-1].get("call_id") == original["call_id"], "web_mcp_original_result_required")
        value = {"codex_function_result": original_input[-1]}
        encoded(value)
        self.protocol = protocol
        self._input = deepcopy(items)
        self._source_input = original_input
        self.pending = None
        self.results += 1
        pending["future"].set_result(value)

    def finish(self, public_message):
        self.guard(self.key)
        if self.indexed is not None:
            require(self.indexed.context_complete, 'web_mcp_context_not_read')
        require(self.begun and not self._final_queued and self.pending is None and self.frames.empty(), "web_mcp_final_with_pending_call")
        frame = self.protocol.complete_public_message("resp_" + secrets.token_hex(16), public_message)
        self._final_queued = True
        self.frames.put_nowait(frame)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.indexed is not None:
            self.indexed.pages.clear()
            self.indexed.expected.clear()
            self.indexed.discovered.clear()
        if self.pending is not None and not self.pending["future"].done():
            self.pending["future"].cancel()
        while not self.frames.empty():
            self.frames.get_nowait()
        self.frames.put_nowait(None)  # Wake a pending native waiter without releasing a call.

    def observation(self):
        """Fixed transport facts, never tool success or task completion.

        A paired result may itself report denial or failure. Do not inspect its
        text to classify it, and never retain arguments, names or identities in
        this projection. An outstanding call remains visible after closure.
        """
        pending = self.pending
        return {'request_read': self.begun and (self.indexed is None or self.indexed.context_complete), 'calls_accepted': self.calls,
            'calls_released': self.released_calls, 'results_received': self.results,
            'pending_call': ('released_without_result' if pending['released'] else 'not_released')
                if pending is not None else None,
            'public_final_returned': self.final_returned,
            **({'search_route': 'web_page_auto_v1'} if self._web_page_search_binding is not None else {}),
            **({'indexed_reads': self.indexed.read_observation()} if self.indexed is not None else {}),
            **({'binding_changes': deepcopy(self.binding_changes)} if self.binding_changes is not None else {})}


MCP_TOOLS = [
    {"name": "operator_begin", "description": "Read the active Codex request from structuredContent. Each key is single-use: begin with the current turn_key, then use exact returned read keys. In mcp_context_records_v3, context records remain in record_index order: encoding=json carries one complete value; encoding=json_fragment must be joined only within that record in fragment_index order. The first request_fields record preserves all non-input request fields and input_format; subsequent input_item values rebuild the input array by request_input_index, or input_value preserves its scalar representation. Older context and schema pages use json_fragment joined in section index order. In v2/v3 each catalog page has complete entries: a discovered entry's exact schema may be read immediately; further pages remain available. Read every context page and the selected tool's complete schema before operator_call. Historical messages stay history; act on the final current input. No execution or retry.",
     "inputSchema": {"type": "object", "properties": {"turn_key": {"type": "string"}},
         "required": ["turn_key"], "additionalProperties": False},
     "outputSchema": {"type": "object", "oneOf": [
         {"type": "object", "properties": {
             "protocol": {"type": "string", "const": "mcp_indexed_request_v1"},
             "section": {"type": "string", "enum": ["context", "catalog", "schema"]},
             "index": {"type": "integer", "minimum": 0, "maximum": 23},
             "total": {"type": "integer", "minimum": 1, "maximum": 24},
             "json_fragment": {"type": "string"},
             "next_read_key": {"type": ["string", "null"]},
             "catalog_read_key": {"type": ["string", "null"]}},
          "required": ["protocol", "section", "index", "total", "json_fragment", "next_read_key"],
          "additionalProperties": False},
         {"type": "object", "properties": {"request": {"type": "object"},
             "tools": {"type": "array", "items": {"type": "object"}},
             "resultRepresentation": {"type": "string"}},
          "required": ["request", "tools", "resultRepresentation"], "additionalProperties": False}]},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "operator_call", "description": "Submit exactly one declared Codex tool call and wait for its real result. Use a name and object arguments from operator_begin. Codex owns execution and permissions. Never retry a failed or uncertain call.",
     "inputSchema": {"type": "object", "properties": {"turn_key": {"type": "string"},
         "name": {"type": "string"}, "arguments": {"type": "object", "additionalProperties": True}},
         "required": ["turn_key", "name", "arguments"], "additionalProperties": False},
     # The registered native tool may access a network or external application.
     # The proxy cannot promise a closed world; native approvals still apply.
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}},
]

# Preserve both original output shapes and advertise the explicitly selected
# paged catalog contract. Tools, arguments and risk annotations do not change.
_INDEX_V2_FRAGMENT_SCHEMA = deepcopy(MCP_TOOLS[0]['outputSchema']['oneOf'][0])
_INDEX_V2_FRAGMENT_SCHEMA['properties']['protocol']['const'] = INDEX_PROTOCOLS[1]
_INDEX_V2_FRAGMENT_SCHEMA['properties']['section']['enum'] = ['context', 'schema']
_INDEX_V2_CATALOG_SCHEMA = deepcopy(_INDEX_V2_FRAGMENT_SCHEMA)
_INDEX_V2_CATALOG_SCHEMA['properties']['section']['enum'] = ['catalog']
_INDEX_V2_CATALOG_SCHEMA['properties'].pop('json_fragment')
_INDEX_V2_CATALOG_SCHEMA['properties'].pop('catalog_read_key')
_INDEX_V2_CATALOG_SCHEMA['required'].remove('json_fragment')
_INDEX_V2_CATALOG_SCHEMA['required'].append('entries')
_INDEX_V2_CATALOG_SCHEMA['properties']['entries'] = {'type': 'array', 'minItems': 1,
    'items': {'type': 'object', 'properties': {
        'index': {'type': 'integer', 'minimum': 0}, 'name': {'type': 'string'},
        'source': {'type': 'object', 'properties': {
            'type': {'type': 'string', 'enum': ['function', 'custom', 'tool_search']},
            'namespace': {'type': ['string', 'null']}, 'name': {'type': 'string'}},
            'required': ['type', 'namespace', 'name'], 'additionalProperties': False},
        'schema_read_key': {'type': 'string'}},
        'required': ['index', 'name', 'source', 'schema_read_key'], 'additionalProperties': False}}
MCP_TOOLS[0]['outputSchema']['oneOf'].extend([_INDEX_V2_FRAGMENT_SCHEMA, _INDEX_V2_CATALOG_SCHEMA])

_INDEX_V3_SCHEMA = deepcopy(_INDEX_V2_FRAGMENT_SCHEMA)
_INDEX_V3_SCHEMA['properties']['protocol']['const'] = INDEX_PROTOCOLS[2]
_INDEX_V3_SCHEMA['properties']['section']['enum'] = ['schema']
_INDEX_V3_CATALOG_SCHEMA = deepcopy(_INDEX_V2_CATALOG_SCHEMA)
_INDEX_V3_CATALOG_SCHEMA['properties']['protocol']['const'] = INDEX_PROTOCOLS[2]
_INDEX_V3_CONTEXT_SCHEMA = deepcopy(_INDEX_V3_SCHEMA)
_INDEX_V3_CONTEXT_SCHEMA['properties']['section']['enum'] = ['context']
_INDEX_V3_CONTEXT_SCHEMA['properties'].pop('json_fragment')
_INDEX_V3_CONTEXT_SCHEMA['required'].remove('json_fragment')
_INDEX_V3_CONTEXT_SCHEMA['required'].append('records')
_INDEX_V3_CONTEXT_SCHEMA['properties']['records'] = {'type': 'array', 'minItems': 1,
    'items': {'type': 'object', 'oneOf': [
        {'type': 'object', 'properties': {
            'record_index': {'type': 'integer', 'minimum': 0},
            'encoding': {'type': 'string', 'const': 'json'},
            'value': {'type': 'object'}},
         'required': ['record_index', 'encoding', 'value'], 'additionalProperties': False},
        {'type': 'object', 'properties': {
            'record_index': {'type': 'integer', 'minimum': 0},
            'encoding': {'type': 'string', 'const': 'json_fragment'},
            'fragment_index': {'type': 'integer', 'minimum': 0, 'maximum': 23},
            'fragment_total': {'type': 'integer', 'minimum': 1, 'maximum': 24},
            'json_fragment': {'type': 'string'}},
         'required': ['record_index', 'encoding', 'fragment_index', 'fragment_total', 'json_fragment'],
         'additionalProperties': False}]}}
MCP_TOOLS[0]['outputSchema']['oneOf'].extend([
    _INDEX_V3_SCHEMA, _INDEX_V3_CATALOG_SCHEMA, _INDEX_V3_CONTEXT_SCHEMA])


class WebRequestCapacityError(RouterError):
    """Local indexed-data preflight exceeded its unchanged section bound."""
    def __init__(self):
        super().__init__('web_mcp_request_capacity_exceeded_before_dispatch')


class WebDesktopUnavailable(RouterError):
    """Fixed pre-dispatch state, never arbitrary browser exception text."""
    def __init__(self, state):
        require(state in ('locked', 'disconnected'), 'web_desktop_state_invalid')
        super().__init__('web_desktop_locked_before_dispatch' if state == 'locked'
            else 'web_desktop_unavailable_before_dispatch')


class WebBrowserAssistanceRequired(RouterError):
    """Pre-dispatch readiness gate; preparation need not require human action."""
    def __init__(self, code):
        require(code in ('web_browser_preparing_before_dispatch',
            'web_browser_login_required_before_dispatch',
            'web_browser_challenge_required_before_dispatch',
            'web_browser_assistance_pending_before_dispatch'), 'web_browser_assistance_code_invalid')
        super().__init__(code)


class WebBrowserHttpError(RouterError):
    """A bounded status for the dispatched model request, without response data."""
    def __init__(self, status):
        require(type(status) is int and 400 <= status <= 599, 'web_model_http_status_invalid')
        self.upstream_status = status
        super().__init__('web_model_http_rejected_no_retry')


class WebBrowserNetworkError(RouterError):
    """Observed transport failure of the dispatched model request, without URLs."""
    codes = frozenset(('net::ERR_TIMED_OUT', 'net::ERR_CONNECTION_RESET',
        'net::ERR_HTTP2_PROTOCOL_ERROR', 'net::ERR_NETWORK_CHANGED',
        'net::ERR_NAME_NOT_RESOLVED', 'net::ERR_INTERNET_DISCONNECTED',
        'net::ERR_CONNECTION_CLOSED', 'net::ERR_CONNECTION_REFUSED',
        'net::ERR_PROXY_CONNECTION_FAILED', 'net::ERR_TUNNEL_CONNECTION_FAILED'))

    def __init__(self, network_error):
        require(network_error in self.codes, 'web_model_network_error_invalid')
        self.network_error = network_error
        super().__init__('web_model_network_interrupted_no_retry')


class WebBrowserFinalTimeout(RouterError):
    """An observed browser final-wait expiry, not evidence of expired login."""
    def __init__(self):
        super().__init__('web_browser_final_timeout_no_retry')


class WebBrowserUiError(RouterError):
    """Observed, bounded public UI state; never a model's prose attribution."""
    codes = frozenset((
        'web_tool_confirmation_required_no_retry',
        'web_session_expired_during_generation_no_retry',
        'web_subscription_unavailable_during_generation_no_retry',
        'web_response_error_no_retry'))

    def __init__(self, code):
        require(code in self.codes, 'web_browser_ui_error_invalid')
        super().__init__(code)


class WebResponsesBridge:
    """Own native-request/browser lifetime; never execute a requested tool.

    A caller supplies the authenticated HTTP boundary and a browser coroutine
    returning one validated public message. One browser generation runs at a
    time. Exact native thread/turn metadata binds continuation; other callers
    receive busy instead of inheriting its context. Admission memory is bounded
    and process-local, so this alone is not restart recovery or a service install.
    These metadata values are correlation data, never caller authentication.
    """
    def __init__(self, route, endpoint, run_browser, *, timeout=300, call_limit=16,
                 check_call=None, citation_mode='none', routes=None):
        require(citation_mode in ('none', 'markdown_links_v1'), 'web_public_citation_mode_required')
        self.citation_mode = citation_mode
        self.route = route
        self.routes = {candidate.slug: candidate for candidate in (routes or (route,))}
        require(self.routes.get(route.slug) == route, 'web_explicit_route_required')
        self.endpoint = endpoint
        self.run_browser = run_browser
        self.timeout = timeout
        self.call_limit = call_limit
        self.check_call = check_call
        self.closed = False
        self.admitted = set()
        self.owner = None
        self.turn = None
        self.driver = None
        self.failure = None
        self.exchanging = False
        self.turn_sequence = 0
        self.last_turn = None

    def diagnostics(self):
        """One current/last local observation; no history, secrets or replay data."""
        return {'scope': 'transport_only',
            'active_turn': {'sequence': self.turn_sequence, **self.turn.observation()}
                if self.turn is not None else None,
            'last_turn': deepcopy(self.last_turn)}

    @staticmethod
    def identity(payload):
        metadata = payload.get('client_metadata') if isinstance(payload, dict) else None
        require(isinstance(metadata, dict), 'web_native_turn_identity_required')
        values = tuple(metadata.get(key) for key in ('thread_id', 'turn_id'))
        require(all(isinstance(value, str) and 0 < len(value) <= 128 for value in values),
            'web_native_turn_identity_required')
        return values

    async def _drive(self, turn):
        try:
            message = await asyncio.wait_for(self.run_browser(turn),
                max(0.01, turn.deadline - time.monotonic()))
            try:
                turn.finish(message)
            except RouterError as error:
                # This classification belongs only to our terminal gate after
                # the browser returned, never to browser exception text. It
                # proves incomplete retrieval, not why a remote reader stopped.
                if (str(error) == 'web_mcp_context_not_read' and turn.indexed is not None
                        and not turn.indexed.context_complete):
                    self.failure = 'web_mcp_context_not_read'
                    turn.close()
                elif str(error) in PUBLIC_CITATION_ERRORS:
                    # Fixed local terminal-validation codes only. An exception
                    # raised by the browser itself still takes the redacted path.
                    self.failure = str(error)
                    turn.close()
                else:
                    raise
        except asyncio.CancelledError:
            turn.close()
            raise
        except (WebDesktopUnavailable, WebBrowserAssistanceRequired) as error:
            self.failure = str(error)
            turn.close()
        except (WebRequestCapacityError, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout) as error:
            self.failure = error
            turn.close()
        except Exception:
            # Browser exception details may contain page data or private URLs.
            self.failure = 'web_browser_driver_failed_no_retry'
            turn.close()

    async def _end(self, outcome='stopped'):
        turn, driver = self.turn, self.driver
        self.turn = self.driver = self.owner = None
        if turn is not None:
            turn.client_cancelled = outcome == 'cancelled'
            turn.close()
            self.last_turn = {'sequence': self.turn_sequence, 'outcome': outcome,
                **turn.observation()}
            if self.endpoint.turn is turn:
                self.endpoint.turn = None
        if driver is not None:
            if not driver.done():
                driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    async def exchange(self, payload, *, on_failure=None):
        require(not self.closed, 'web_bridge_closed')
        identity = self.identity(payload)
        # No awaits before admission. A concurrent HTTP request must not cancel
        # the browser generation already owned by another request or task.
        require(not self.exchanging, 'web_bridge_response_busy')
        require(self.owner is None or self.owner == identity
            or self.turn is not None and self.turn.closed, 'web_bridge_browser_busy')
        self.exchanging = True
        # Request-local ownership, not the global last_turn snapshot. A rejected
        # new/replayed request must never inherit another request's observation.
        same_owner = self.owner == identity
        request_turn = self.turn if same_owner and not self.turn.closed else None
        request_sequence = self.turn_sequence
        try:
            if self.turn is not None and self.turn.closed:
                await self._end('failed')
                if not same_owner:
                    # A previous browser can fail between native tool steps.
                    # Its error cannot become a new caller's validation error.
                    self.failure = None
            route = self.routes.get(payload.get('model'))
            require(route is not None, 'web_explicit_route_required')
            projected, search_binding = web_page_search_projection(payload)
            protocol = WebModelProtocol(route, projected, citation_mode=self.citation_mode)
            if self.owner is None:
                require(identity not in self.admitted, 'web_bridge_turn_consumed_no_retry')
                require(len(self.admitted) < 128, 'web_bridge_admission_limit')
                require(self.endpoint.turn is None, 'web_bridge_endpoint_already_owned')
                turn = WebMcpTurn(protocol, timeout=self.timeout, call_limit=self.call_limit,
                    check_call=self.check_call, web_page_search_binding=search_binding)
                self.admitted.add(identity)
                self.turn_sequence += 1
                request_turn, request_sequence = turn, self.turn_sequence
                self.owner, self.turn = identity, turn
                self.failure = None
                self.endpoint.turn = turn
                self.driver = asyncio.create_task(self._drive(turn))
            else:
                turn = self.turn
                require(same_json(search_binding, turn._web_page_search_binding),
                    'web_mcp_request_binding_changed')
                turn.accept_result(protocol)
            frame = await turn.next_response()
            if turn._final_queued:
                await self._end('public_final_returned')
            return frame
        except asyncio.CancelledError:
            await self._end('cancelled')
            self.failure = None
            raise
        except Exception:
            failure, self.failure = self.failure, None
            await self._end('failed')
            # Driver cancellation cleanup can itself fail and set failure while
            # _end awaits it. That is not another request's browser failure.
            self.failure = None
            if request_turn is not None and on_failure is not None:
                on_failure({'scope': 'transport_only', 'turn': {
                    'sequence': request_sequence, **request_turn.observation()}})
            if failure:
                if isinstance(failure, (WebRequestCapacityError, WebBrowserHttpError, WebBrowserNetworkError, WebBrowserUiError, WebBrowserFinalTimeout)):
                    raise failure from None
                raise RouterError(failure) from None
            raise
        finally:
            self.exchanging = False

    async def stop(self):
        self.closed = True
        await self._end()


_MCP_DIAGNOSTIC_METHODS = frozenset(('initialize', 'ping', 'tools/list', 'tools/call',
    'notifications/initialized', 'notifications/cancelled', 'server/discover'))
_MCP_DIAGNOSTIC_CODES = frozenset((
    'web_mcp_endpoint_rejected', 'web_mcp_post_required', 'web_mcp_json_required',
    'web_mcp_rpc_required', 'web_mcp_method_invalid', 'web_mcp_session_required',
    'web_mcp_session_expired', 'web_mcp_notification_rejected', 'web_mcp_request_id_required',
    'web_mcp_request_id_too_large', 'web_mcp_duplicate_no_retry', 'web_mcp_session_request_limit',
    'web_mcp_initialize_session_invalid', 'web_mcp_version_unsupported', 'web_mcp_session_limit',
    'web_mcp_call_required', 'web_mcp_no_active_turn', 'web_mcp_begin_arguments_invalid',
    'web_mcp_call_arguments_invalid', 'web_mcp_unknown_method_tool', 'web_mcp_method_rejected',
    'web_mcp_invalid_request', 'web_mcp_turn_rejected', 'web_mcp_turn_closed',
    'web_mcp_begin_already_consumed', 'web_mcp_call_out_of_order', 'web_mcp_session_invalid',
    'web_mcp_call_limit', 'web_mcp_unknown_tool', 'web_mcp_object_arguments_required',
    'web_mcp_payload_too_large', 'web_mcp_http_body_too_large', 'web_mcp_unexpected_error',
    'web_mcp_read_key_unavailable', 'web_mcp_read_limit', 'web_mcp_read_out_of_order',
    'web_mcp_context_not_read', 'web_mcp_catalog_not_read', 'web_mcp_catalog_entry_not_read', 'web_mcp_schema_not_read'))


class WebMcpEndpoint:
    """Private path, loopback host/origin guard, bounded JSON Streamable HTTP.

    A public tunnel must rewrite Host to this exact loopback endpoint. This is
    opt-in transient path authentication plus an independent short-lived turn
    secret, not account identity attestation or a production OAuth implementation.
    """
    def __init__(self, *, begin_result_mode='text_v1', indexed_protocol=INDEX_PROTOCOLS[0],
            call_result_mode='text_v1'):
        require(begin_result_mode in ('text_v1', 'structured_begin_v1'), 'web_mcp_result_mode_invalid')
        require(call_result_mode in ('text_v1', 'structured_call_v1'), 'web_mcp_result_mode_invalid')
        require(indexed_protocol in INDEX_PROTOCOLS and (indexed_protocol == INDEX_PROTOCOLS[0]
            or begin_result_mode == 'structured_begin_v1'), 'web_mcp_index_protocol_invalid')
        self.begin_result_mode = begin_result_mode
        self.call_result_mode = call_result_mode
        self.indexed_protocol = indexed_protocol
        self.path = "/mcp/" + secrets.token_urlsafe(32)
        self.unsupported_oauth_metadata = False
        self.turn = None
        self.host = None
        self.runner = None
        self.requests = 0
        self.methods = {}
        self.sessions = {}
        self.sessions_reclaimed = 0
        self.sessions_expired = 0
        self._diagnostic_generation = secrets.token_hex(16)
        self._diagnostic_sequence = 0
        self._diagnostic_events = deque(maxlen=128)

    def _trace(self, event, stage, method=None, tool=None, code=None):
        self._diagnostic_sequence += 1
        self._diagnostic_events.append({'sequence': self._diagnostic_sequence,
            'event': event, 'stage': stage,
            'method': method if isinstance(method, str) and method in _MCP_DIAGNOSTIC_METHODS else 'other',
            'tool': tool if tool in ('operator_begin', 'operator_call') else None,
            'code': None if code is None else code if code in _MCP_DIAGNOSTIC_CODES
                else 'web_mcp_other_rejection'})

    def diagnostics(self):
        """Bounded local observations, not upstream denial or delivery attestation.

        Never retain request/session ids, paths, keys, arguments, results or
        arbitrary method/tool/error strings. A prepared reply does not prove
        receipt by ChatGPT or successful execution of the enclosed native result.
        """
        return {'generation': self._diagnostic_generation,
            'requests': self.requests, 'methods': dict(self.methods),
            'session_pool': {'limit': 64, 'size': len(self.sessions),
                'busy': sum(self._session_busy(key, item) for key, item in self.sessions.items()),
                'reclaimed': self.sessions_reclaimed, 'expired': self.sessions_expired},
            'eventsTotal': self._diagnostic_sequence,
            'eventsDropped': self._diagnostic_sequence - len(self._diagnostic_events),
            'events': deepcopy(list(self._diagnostic_events))}

    def _session_busy(self, key, item):
        pending = self.turn.pending if self.turn is not None else None
        return bool(item.get('in_flight', 0) or (pending is not None
            and not pending['future'].done() and pending['rpc_identity'][0] == key))

    def _reserve_session_slot(self, now):
        # MCP permits server-side session termination with subsequent HTTP 404.
        # Keep the fixed memory bound, pending native calls and handshake-only
        # sessions. A completed RPC makes an idle session eligible for LRU
        # retirement, not for replay; its old ID is never recreated or adopted.
        expired = [key for key, item in self.sessions.items()
            if item['deadline'] <= now and not self._session_busy(key, item)]
        for key in expired:
            del self.sessions[key]
        self.sessions_expired += len(expired)
        if len(self.sessions) >= 64:
            idle = [(item['last_used'], key) for key, item in self.sessions.items()
                if item.get('reclaimable', False) and not self._session_busy(key, item)]
            if idle:
                del self.sessions[min(idle)[1]]
                self.sessions_reclaimed += 1
        require(len(self.sessions) < 64, 'web_mcp_session_limit')

    async def start(self, *, port=0):
        require(type(port) is int and 0 <= port <= 65535, "web_mcp_port_invalid")
        application = web.Application(client_max_size=2 * 1024 * 1024)
        application.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(application, access_log=None, handler_cancellation=True)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", port)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.host = f"127.0.0.1:{port}"
        return "http://" + self.host + self.path

    async def stop(self):
        if self.turn is not None:
            self.turn.close()
        if self.runner is not None:
            await self.runner.cleanup()
        self.sessions.clear()

    async def handle(self, request):
        if (self.unsupported_oauth_metadata and request.method == 'GET'
                and request.host == self.host and not request.query_string
                and request.headers.get('Origin') in (None, 'http://' + self.host)
                and request.path in ('/.well-known/oauth-protected-resource',
                    '/.well-known/oauth-protected-resource' + self.path,
                    self.path + '/.well-known/oauth-protected-resource')):
            # The fixed tunnel's local server has no OAuth metadata. A 404
            # declares that absence; it grants no MCP access or identity.
            return web.Response(status=404)
        if (request.host != self.host or request.headers.get("Origin") not in (None, "http://" + self.host)
                or not secrets.compare_digest(request.path, self.path) or request.query_string):
            self._trace('rejected', 'http', code='web_mcp_endpoint_rejected')
            return web.json_response({"error": "web_mcp_endpoint_rejected"}, status=403)
        if request.method != "POST":
            self._trace('rejected', 'http', code='web_mcp_post_required')
            return web.Response(status=405, headers={"Allow": "POST"})
        rpc_id = None
        method = tool = None
        pinned_session = None
        stage = 'body'
        try:
            require(request.content_type == "application/json", "web_mcp_json_required")
            # Reserve a known live session before awaiting a slow request body.
            # This does not authenticate the RPC or extend its fixed deadline.
            candidate = self.sessions.get(request.headers.get('Mcp-Session-Id'))
            if candidate is not None and time.monotonic() < candidate['deadline']:
                candidate['in_flight'] = candidate.get('in_flight', 0) + 1
                pinned_session = candidate
            body = await asyncio.wait_for(request.read(), 10)
            value = loads(body.decode("utf-8"))
            stage = 'rpc'
            require(isinstance(value, dict) and value.get("jsonrpc") == "2.0", "web_mcp_rpc_required")
            rpc_id = value.get("id")
            method = value.get("method")
            require(isinstance(method, str) and len(method) < 64, "web_mcp_method_invalid")
            self.requests += 1
            method_bucket = method if method in _MCP_DIAGNOSTIC_METHODS else 'other'
            self.methods[method_bucket] = self.methods.get(method_bucket, 0) + 1
            if method == 'tools/call' and isinstance(value.get('params'), dict):
                candidate = value['params'].get('name')
                tool = candidate if candidate in ('operator_begin', 'operator_call') else None
            self._trace('received', stage, method, tool)
            stage = 'session'
            session_id = request.headers.get("Mcp-Session-Id")
            response_headers = {}
            session = None
            if method != "initialize":
                if session_id is None:
                    self._trace('rejected', stage, method, tool, 'web_mcp_session_required')
                    return web.json_response({"error": "web_mcp_session_required"}, status=400)
                session = self.sessions.get(session_id)
                if session is None or time.monotonic() >= session["deadline"]:
                    self._trace('rejected', stage, method, tool, 'web_mcp_session_expired')
                    return web.json_response({"error": "web_mcp_session_expired"}, status=404)
                # No await occurs between lookup and pinning. The finally block
                # releases the exact object even on cancellation or shutdown;
                # it never inserts a removed session back into the pool.
                if pinned_session is None:
                    session['in_flight'] = session.get('in_flight', 0) + 1
                    pinned_session = session
            stage = 'rpc'
            if "id" not in value:
                require(method in ("notifications/initialized", "notifications/cancelled"), "web_mcp_notification_rejected")
                if method == "notifications/cancelled" and self.turn is not None:
                    cancelled_id = value.get("params", {}).get("requestId")
                    pending = self.turn.pending
                    if type(cancelled_id) in (str, int) and pending is not None and pending["rpc_identity"] == (
                            session_id, type(cancelled_id).__name__, cancelled_id):
                        self.turn.close()
                self._trace('reply_prepared', stage, method, tool)
                return web.Response(status=202)
            require(type(rpc_id) in (str, int), "web_mcp_request_id_required")
            require(not isinstance(rpc_id, str) or len(rpc_id) <= 128, "web_mcp_request_id_too_large")
            if session is not None:
                rpc_identity = (type(rpc_id).__name__, rpc_id)
                require(rpc_identity not in session["seen"], "web_mcp_duplicate_no_retry")
                require(len(session["seen"]) < 64, "web_mcp_session_request_limit")
                session["seen"].add(rpc_identity)
            if method == "initialize":
                require(session_id is None, "web_mcp_initialize_session_invalid")
                version = value.get("params", {}).get("protocolVersion")
                require(version in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"), "web_mcp_version_unsupported")
                now = time.monotonic()
                self._reserve_session_slot(now)
                session_id = secrets.token_urlsafe(32)
                self.sessions[session_id] = {"deadline": now + 900,
                    'last_used': now, 'in_flight': 0, 'reclaimable': False,
                    "seen": {(type(rpc_id).__name__, rpc_id)}}
                response_headers["Mcp-Session-Id"] = session_id
                result = {"protocolVersion": version, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "operator-web-tools", "version": "0.2.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": deepcopy(MCP_TOOLS)}
                if self.begin_result_mode == 'text_v1':
                    result['tools'][0].pop('outputSchema')
                    result['tools'][0]['description'] = "Read the active Codex request. Each key is single-use: begin with the current turn_key, then use exact read keys returned in an indexed response. Read every context page before answering; discover and read exact tool schemas before operator_call. No execution or retry."
                if self.call_result_mode == 'structured_call_v1':
                    result['tools'][1]['outputSchema'] = {
                        'type': 'object', 'properties': {'codex_function_result': {
                            'type': 'object', 'properties': {'call_id': {'type': 'string'}},
                            'required': ['call_id'], 'additionalProperties': True}},
                        'required': ['codex_function_result'], 'additionalProperties': False}
                    result['tools'][1]['description'] += (
                        ' structuredContent.codex_function_result preserves the entire original native result, '
                        'including text part boundaries and any failure or denial. A returned result does not imply success.')
            elif method == "tools/call":
                stage = 'tool_arguments'
                params = value.get("params")
                require(isinstance(params, dict) and isinstance(params.get("arguments"), dict), "web_mcp_call_required")
                args, name = params["arguments"], params.get("name")
                require(self.turn is not None, "web_mcp_no_active_turn")
                if name == "operator_begin":
                    require(set(args) == {"turn_key"}, "web_mcp_begin_arguments_invalid")
                    require(self.turn.indexed is None or
                        self.turn.indexed.begin_result_mode == self.begin_result_mode,
                        'web_mcp_page_representation_changed')
                    stage = 'tool_dispatch'
                    answer = self.turn.begin(args["turn_key"])
                elif name == "operator_call":
                    require(set(args) == {"turn_key", "name", "arguments"}, "web_mcp_call_arguments_invalid")
                    stage = 'tool_dispatch'
                    answer = await self.turn.invoke(args["turn_key"], rpc_id, args["name"], args["arguments"], session_id=session_id)
                else:
                    raise RouterError("web_mcp_unknown_method_tool")
                stage = 'serialize'
                if name == 'operator_begin' and self.begin_result_mode == 'structured_begin_v1':
                    # Indexed fields are model-visible structured data. Do not
                    # duplicate pages as giant JSON text blocks, or put any of
                    # their contents in model-hidden metadata. The default
                    # text_v1 endpoint retains its original representation.
                    indexed = self.turn.indexed is not None
                    result = {'structuredContent': answer, 'content': [], 'isError': False}
                    if indexed:
                        encoded({'jsonrpc': '2.0', 'id': rpc_id, 'result': result}, INDEX_REPLY_BYTES)
                elif name == 'operator_call' and self.call_result_mode == 'structured_call_v1':
                    # This is the exact already-paired source result, not a
                    # synthesized success or an extraction of its text. Keep
                    # legacy text transport independently selectable.
                    result = {'structuredContent': answer, 'content': [], 'isError': False}
                else:
                    result = {"content": [{"type": "text", "text": encoded(answer, 16 * 1024 * 1024)}], "isError": False}
            else:
                raise RouterError("web_mcp_method_rejected")
            stage = 'serialize'
            response = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
            if method == 'tools/call' and name == 'operator_begin' and self.turn.indexed is not None:
                encoded(response, INDEX_REPLY_BYTES)
            encoded(response, 16 * 1024 * 1024)
            self._trace('reply_prepared', stage, method, tool)
            if pinned_session is not None:
                pinned_session['reclaimable'] = True
            return web.json_response(response, dumps=dumps, headers=response_headers)
        except asyncio.CancelledError:
            self._trace('cancelled', stage, method, tool)
            raise
        except web.HTTPRequestEntityTooLarge:
            self._trace('rejected', stage, method, tool, 'web_mcp_http_body_too_large')
            raise
        except (RouterError, ValueError, TypeError, KeyError, asyncio.TimeoutError) as error:
            code = str(error) if isinstance(error, RouterError) else "web_mcp_invalid_request"
            self._trace('rejected', stage, method, tool, code)
            return web.json_response({"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32602, "message": code}})
        except Exception:
            self._trace('rejected', stage, method, tool, 'web_mcp_unexpected_error')
            raise
        finally:
            if pinned_session is not None:
                pinned_session['in_flight'] -= 1
                pinned_session['last_used'] = time.monotonic()
