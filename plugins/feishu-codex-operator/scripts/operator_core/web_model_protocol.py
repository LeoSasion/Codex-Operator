"""Operator-owned Web protocol conversion, independent of any reference app.

This module performs no network, browser, credential, process or tool execution.
The authenticated transport binds the actual browser document/model/turn before
supplying public messages or completed structured calls. Page text can never
declare or invoke a tool here.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import urlsplit

from .model_registry import ModelRoute
from .responses_capabilities import RouterError
from .responses_events import MAX_EVENT_BYTES, completed_response_events
from .responses_tool_adapter import (
    MAX_OUTPUT_ITEMS, bounded_string, identifier, loads, prepare_request, restore_response,
)


PUBLIC_CITATION_ERRORS = frozenset({
    'web_public_citations_invalid', 'web_public_citation_sources_invalid',
    'web_public_citation_source_invalid', 'web_public_citation_title_invalid',
    'web_public_citation_url_invalid', 'web_public_citation_type_unsupported',
    'web_public_citation_position_invalid', 'web_public_sources_footnote_invalid',
    'web_public_citation_marker_invalid', 'web_public_citation_overlap',
    'web_public_sources_footnote_mismatch', 'web_public_citation_text_mismatch',
    'web_public_citation_unmapped',
})

# ChatGPT's public reference metadata binds each citation to an exact text
# span and source URL. Search/view IDs are opaque; a URL marker's trailing
# value may instead be the exact URL of its bound public source.
PUBLIC_CITATION_ID = r'[A-Za-z0-9_-]{1,128}'


def _public_links(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise RouterError('web_public_citation_sources_invalid')
    result = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {'title', 'url'}:
            raise RouterError('web_public_citation_source_invalid')
        title = bounded_string(value['title'], maximum=8192)
        url = bounded_string(value['url'], maximum=8192)
        if not title or any(ord(c) < 32 for c in title):
            raise RouterError('web_public_citation_title_invalid')
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                and parsed.username is None and parsed.password is None
                and not any(c.isspace() or ord(c) < 32 or c in '<>\\"' for c in url))
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise RouterError('web_public_citation_url_invalid')
        label = re.sub(r'([\\`*_{}\[\]()<>!#|~])', r'\\\1', title)
        result.append((title, url, '[' + label + '](<' + url + '>)'))
    return result


def _citation_url_variants(url):
    """Only ChatGPT's observed attribution suffix may differ from a source URL."""
    variants = {url}
    head, sep, fragment = url.partition('#')
    base, query_sep, query = head.partition('?')
    attribution = 'utm_source=chatgpt.com'
    if query_sep and query == attribution:
        variants.add(base + sep + fragment)
    elif query_sep and query.endswith('&' + attribution):
        variants.add(head[:-len('&' + attribution)] + sep + fragment)
    return variants


def render_public_citations(parts, references):
    """Render the dated Web citation spans, without changing any other text.

    2026-09-16's emoji probe establishes Unicode-scalar offsets. The observed
    sources_footnote is virtual metadata and supplies no invented character or
    search event. The 2026-09-19 probe observed zero-width trailing footnotes;
    a 2026-09-26 public page also placed one at a zero-width position inside
    the answer. Labelled url/item references remain separate.
    Footnotes cover grouped citations, not the separately labelled links.
    Original parts/references
    remain untouched in the caller's bound public message.
    """
    if not isinstance(references, list) or len(references) > 128:
        raise RouterError('web_public_citations_invalid')
    total = sum(len(part) for part in parts)
    grouped, footnotes, cited = [], [], set()

    links = _public_links

    for reference in references:
        if not isinstance(reference, dict):
            raise RouterError('web_public_citations_invalid')
        kind = reference.get('type')
        if not isinstance(kind, str):
            raise RouterError('web_public_citation_type_unsupported')
        expected_keys = {'type', 'matched_text', 'start_idx', 'end_idx'} | {
            'grouped_webpages': {'items'}, 'sources_footnote': {'sources'},
            'url': {'title', 'item'},
        }.get(kind, set())
        if kind not in ('grouped_webpages', 'sources_footnote', 'url') or set(reference) != expected_keys:
            raise RouterError('web_public_citation_type_unsupported')
        start, end = reference['start_idx'], reference['end_idx']
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= total + 1:
            raise RouterError('web_public_citation_position_invalid')
        matched = bounded_string(reference['matched_text'], maximum=8192)
        if kind == 'sources_footnote':
            if (start > total or end not in (start, start + 1) or matched != ' ' or footnotes
                    or end == start + 1 and start < total
                    and ''.join(parts)[start:end] != matched):
                raise RouterError('web_public_sources_footnote_invalid')
            footnotes.append(links(reference['sources']))
            continue
        if start == end:
            raise RouterError('web_public_citation_position_invalid')
        if kind == 'url':
            marker = re.fullmatch(r'\ue200url\ue202([^\ue200\ue201\ue202]+)\ue202'
                r'([^\ue200\ue201\ue202]+)\ue201', matched)
            if marker is None or marker[1] != reference['title']:
                raise RouterError('web_public_citation_marker_invalid')
            # The page's displayed label and source title have distinct roles.
            # A URL-valued marker must match its validated source URL. The
            # public page may append one observed ChatGPT attribution suffix
            # to that source link; only that exact suffix may differ.
            source = links([reference['item']])[0]
            source_urls = _citation_url_variants(source[1])
            if not re.fullmatch(PUBLIC_CITATION_ID, marker[2]) and marker[2] not in source_urls:
                raise RouterError('web_public_citation_marker_invalid')
            values = links([{'title': reference['title'], 'url': source[1]}])
        else:
            if not re.fullmatch(r'\ue200cite\ue202' + PUBLIC_CITATION_ID
                    + r'(?:\ue202' + PUBLIC_CITATION_ID + r')*\ue201', matched):
                raise RouterError('web_public_citation_marker_invalid')
            values = links(reference['items'])
            cited.update((title, url) for title, url, _ in values)
        grouped.append((start, end, matched, values))
    grouped.sort(key=lambda entry: entry[0])
    if any(left[1] > right[0] for left, right in zip(grouped, grouped[1:])):
        raise RouterError('web_public_citation_overlap')
    # The public footer can list only a subset (observed 2026-09-19 AX),
    # independently of earlier inline groups. Every inline group is rendered;
    # accepting a bound subset never removes a source from the answer.
    if footnotes and not {(title, url) for title, url, _ in footnotes[0]} <= cited:
        raise RouterError('web_public_sources_footnote_mismatch')
    rendered, position, used = [], 0, 0
    for part in parts:
        cursor, chunks = 0, []
        for start, end, matched, values in grouped:
            if position <= start < position + len(part):
                a, b = start - position, end - position
                if b > len(part) or part[a:b] != matched:
                    raise RouterError('web_public_citation_text_mismatch')
                chunks.extend((part[cursor:a], ' '.join(link for _, _, link in values)))
                cursor, used = b, used + 1
        chunks.append(part[cursor:])
        value = ''.join(chunks)
        if '\ue200cite\ue202' in value or '\ue200url\ue202' in value:
            raise RouterError('web_public_citation_unmapped')
        rendered.append(value)
        position += len(part)
    if used != len(grouped):
        raise RouterError('web_public_citation_position_invalid')
    return rendered


def _modern_public_links(body):
    """Read bounded Markdown destinations without rewriting their source bytes."""
    pattern = re.compile(r'\[(?:\\.|[^\]\\\r\n]){1,2048}\]'
        r'\((?:<(?P<angle>https?://[^<>\r\n]{1,8192})>\)|(?P<plain>https?://))')
    consumed = 0
    for match in pattern.finditer(body):
        if match.start() < consumed:
            continue
        url = match.group('angle')
        end = match.end()
        if url is None:
            start = end = match.start('plain')
            depth = 0
            # An unescaped closing parenthesis at depth zero ends the link.
            # Scan at most 8192 characters; _public_links also retains the
            # 8192-byte gate. Never recurse or accept an oversized URL prefix.
            while end < len(body) and end - start <= 8192:
                char = body[end]
                if char == ')' and depth == 0:
                    break
                if char.isspace() or ord(char) < 32 or char in '<>\\"':
                    raise RouterError('web_public_citation_unmapped')
                if char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                end += 1
            else:
                raise RouterError('web_public_citation_unmapped')
            url = body[start:end]
            end += 1
        consumed = end
        yield end, url


def render_modern_public_citations(parts, references):
    """Accept only already-rendered links bound to the current public sources.

    The newer page's content string contains Markdown links while its reference
    offsets still describe an earlier marker-bearing representation. Never
    apply those offsets to the rendered string. A bare display marker cannot
    identify a source; only an adjacent validated link may retain its citation.
    """
    if (len(parts) != 1 or not isinstance(references, list) or len(references) > 128):
        raise RouterError('web_public_citations_invalid')
    body = parts[0]
    if '\ue200cite\ue202' in body or '\ue200url\ue202' in body:
        raise RouterError('web_public_citation_unmapped')
    if not references:
        if ':chatgpt-content-reference' in body:
            raise RouterError('web_public_citation_marker_invalid')
        return parts
    sources_by_index, grouped_sources = [], set()
    footnote_sources = []
    for reference in references:
        if not isinstance(reference, dict):
            raise RouterError('web_public_citations_invalid')
        kind = reference.get('type')
        expected = {'type', 'matched_text', 'start_idx', 'end_idx'} | {
            'grouped_webpages': {'items'}, 'sources_footnote': {'sources'},
            'url': {'title', 'item'},
        }.get(kind, set())
        if kind not in ('grouped_webpages', 'sources_footnote', 'url') or set(reference) != expected:
            raise RouterError('web_public_citation_type_unsupported')
        start, end = reference['start_idx'], reference['end_idx']
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= 1024 * 1024 + 1:
            raise RouterError('web_public_citation_position_invalid')
        matched = bounded_string(reference['matched_text'], maximum=8192)
        if kind == 'sources_footnote':
            if matched != ' ' or end not in (start, start + 1) or footnote_sources:
                raise RouterError('web_public_sources_footnote_invalid')
            footnote_sources = _public_links(reference['sources'])
            sources_by_index.append({url for _, url, _ in footnote_sources})
        elif kind == 'grouped_webpages':
            if not re.fullmatch(r'\ue200cite\ue202' + PUBLIC_CITATION_ID
                    + r'(?:\ue202' + PUBLIC_CITATION_ID + r')*\ue201', matched):
                raise RouterError('web_public_citation_marker_invalid')
            values = _public_links(reference['items'])
            grouped_sources.update((title, url) for title, url, _ in values)
            sources_by_index.append({url for _, url, _ in values})
        else:
            marker = re.fullmatch(r'\ue200url\ue202([^\ue200\ue201\ue202]+)\ue202'
                r'([^\ue200\ue201\ue202]+)\ue201', matched)
            if marker is None or marker[1] != reference['title']:
                raise RouterError('web_public_citation_marker_invalid')
            source = _public_links([reference['item']])[0]
            if not re.fullmatch(PUBLIC_CITATION_ID, marker[2]) and marker[2] not in _citation_url_variants(source[1]):
                raise RouterError('web_public_citation_marker_invalid')
            sources_by_index.append({source[1]})
    if footnote_sources and not {(title, url) for title, url, _ in footnote_sources} <= grouped_sources:
        raise RouterError('web_public_sources_footnote_mismatch')

    links = list(_modern_public_links(body))
    validated_urls = set().union(*sources_by_index) if sources_by_index else set()
    for _, url in links:
        _public_links([{'title': 'source', 'url': url}])
        if not any(_citation_url_variants(url) & _citation_url_variants(source)
                for source in validated_urls):
            raise RouterError('web_public_citation_unmapped')

    marker_pattern = re.compile(r':chatgpt-content-reference\{index="([0-9]{1,3})"\}')
    markers = list(marker_pattern.finditer(body))
    if body.count(':chatgpt-content-reference') != len(markers):
        raise RouterError('web_public_citation_marker_invalid')
    if references and not links and not markers:
        raise RouterError('web_public_citation_unmapped')
    replacements = []
    for marker in markers:
        # The regex bounds the page's display number to three decimal digits.
        # Its value does not index contentReferences or a grouped source list.
        adjacent = next((link for link in reversed(links)
            if link[0] <= marker.start() and not body[link[0]:marker.start()].strip()), None)
        if adjacent is not None:
            url = adjacent[1]
            # The rendered marker's number is a page presentation index, not
            # a stable contentReferences array position. An adjacent link is
            # already complete; require its URL in the validated public set.
            if not any(_citation_url_variants(url) & _citation_url_variants(source)
                    for source in validated_urls):
                raise RouterError('web_public_citation_unmapped')
            replacements.append('')
        else:
            # This renderer's display index is not a stable reference-array
            # index. A bare marker cannot establish which source it cites.
            raise RouterError('web_public_citation_unmapped')
    rendered = body
    for marker, replacement in reversed(list(zip(markers, replacements))):
        rendered = rendered[:marker.start()] + replacement + rendered[marker.end():]
    return [rendered]


def public_web_message(message, *, citation_mode='none'):
    """Project one dated public page-message shape; preserve every text part.

    The shape is a compatibility contract, not browser identity attestation.
    No React traversal, HTML conversion, hidden reasoning, text-field fallback,
    Markdown repair, part concatenation or inferred function call is permitted.
    """
    if not isinstance(message, dict):
        raise RouterError("web_public_message_required")
    author, content = message.get("author"), message.get("content")
    if (not isinstance(author, dict) or author.get("role") != "assistant"
            or message.get("recipient") not in (None, "all")
            or message.get("status") != "finished_successfully"
            or message.get("channel") not in ("final", "commentary")):
        raise RouterError("web_public_message_not_finished_or_public")
    metadata = message.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RouterError("web_hidden_message_rejected")
    for key in ("is_visually_hidden_from_conversation", "is_visually_hidden"):
        flag = metadata.get(key)
        if flag is not None and flag is not False:
            raise RouterError("web_hidden_message_rejected")
    final = message["channel"] == "final"
    if message.get("end_turn") is not final:
        raise RouterError("web_public_message_end_turn_mismatch")
    if not isinstance(content, dict) or content.get("content_type") != "text":
        raise RouterError("web_public_text_required")
    parts = content.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_OUTPUT_ITEMS:
        raise RouterError("web_public_text_parts_required")
    parts = [bounded_string(part, maximum=MAX_EVENT_BYTES) for part in parts]
    if citation_mode == 'markdown_links_v1':
        if metadata.get('operator_web_renderer') == 'modern_content_references_v1':
            parts = render_modern_public_citations(parts, message.get('public_references'))
        else:
            parts = render_public_citations(parts, message.get('public_references'))
    elif citation_mode != 'none' or message.get('public_references'):
        raise RouterError('web_public_citation_mode_required')
    projected = []
    for part in parts:
        projected.append({"type": "output_text", "text": bounded_string(
            part, maximum=MAX_EVENT_BYTES), "annotations": []})
    # A public Web UUID belongs to the browser document, not the Responses ID
    # namespace. Derive a stable, bounded Responses message ID at projection
    # time only. Keep the original page object, historical inputs and tool/call
    # identities unchanged; this mapping is not authentication or attestation.
    source_id = identifier(message.get("id"))
    item_id = "msg_ow_" + hashlib.sha256(
        b"operator_web_message_v1\0" + source_id.encode("utf-8")).hexdigest()[:48]
    return {"type": "message", "id": item_id,
            "role": "assistant", "status": "completed",
            "phase": "final_answer" if final else "commentary", "content": projected}


def workspace_telemetry(value):
    """Validate observed CLI Git telemetry; never interpret it as permission.

    0.155.0-alpha.2.6 adds remotes and the HEAD hash to the earlier dirty flag.
    Both absent telemetry and its later arrival were observed. All original
    bytes remain in request(); this only permits comparison across tool steps.
    """
    if not isinstance(value, dict) or len(value) > 32:
        return False
    for root, state in value.items():
        if (not isinstance(root, str) or not 1 <= len(root) <= 4096
                or not isinstance(state, dict) or 'has_changes' not in state
                or set(state) - {'has_changes', 'associated_remote_urls', 'latest_git_commit_hash'}
                or type(state['has_changes']) is not bool):
            return False
        if 'latest_git_commit_hash' in state:
            commit = state['latest_git_commit_hash']
            if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
                return False
        if 'associated_remote_urls' in state:
            remotes = state['associated_remote_urls']
            if (not isinstance(remotes, dict) or len(remotes) > 32
                    or any(not isinstance(name, str) or not 1 <= len(name) <= 256
                        or not isinstance(url, str) or not 1 <= len(url) <= 8192
                        for name, url in remotes.items())):
                return False
    return True


def _tool_declaration_change_kinds(before, after):
    """Classify rejected declarations by fixed labels, without retaining values.

    An identity replacement cannot establish a rename. Duplicate or malformed
    identities cannot be paired safely, so leave their fields unclassified.
    Counts describe source declarations, not effective permissions. The only
    interpreted default is the adapter's absent defer_loading=False.
    """
    if not isinstance(before, list) or not isinstance(after, list) or len(before) > 1024 or len(after) > 1024:
        return {'classified': False}

    def indexed(values, *, nested=False):
        result, order = {}, []
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get('type'), str):
                return None
            kind = value['type']
            if nested:
                # A namespace may contain only directly declared function or
                # custom tools; never descend into an unknown nested shape.
                if kind == 'function':
                    if (set(value) - {'type', 'name', 'description', 'parameters',
                            'strict', 'defer_loading'}
                            or not isinstance(value.get('parameters'), dict)):
                        return None
                elif kind == 'custom':
                    if (set(value) - {'type', 'name', 'description', 'format',
                            'defer_loading'}
                            or 'format' in value and not isinstance(value['format'], dict)):
                        return None
                else:
                    return None
                if ('defer_loading' in value and type(value['defer_loading']) is not bool
                        or 'description' in value and value['description'] is not None
                        and not isinstance(value['description'], str)):
                    return None
            if kind == 'tool_search':
                if 'name' in value:
                    return None
                identity = (kind, '')
            elif kind in ('function', 'custom', 'namespace') and isinstance(value.get('name'), str) and value['name']:
                identity = (kind, value['name'])
            else:
                return None
            if identity in result:
                return None
            result[identity] = value
            order.append(identity)
        return result, order

    old, new = indexed(before), indexed(after)
    if old is None or new is None:
        return {'classified': False}
    old_map, old_order = old
    new_map, new_order = new

    def same_field(left, right, key):
        return ((key in left) == (key in right)
            and (key not in left or json.dumps(left[key], ensure_ascii=False,
                sort_keys=True, separators=(',', ':'), allow_nan=False)
                == json.dumps(right[key], ensure_ascii=False, sort_keys=True,
                    separators=(',', ':'), allow_nan=False)))

    def same_declaration(left, right):
        return all(same_field(left, right, key) for key in left.keys() | right.keys())

    counts = {key + '_changed_count': 0 for key in ('description', 'parameters', 'strict',
        'defer_loading', 'other')}
    counts.update(defer_loading_true_to_false_count=0,
        defer_loading_false_to_true_count=0, defer_loading_presence_only_count=0,
        namespace_tools_changed_count=0, custom_format_changed_count=0,
        tool_search_execution_changed_count=0)
    counts.update({kind + '_changed_count': 0 for kind in
        ('function', 'custom', 'namespace', 'tool_search')})
    nested_pairs = []
    for identity in old_map.keys() & new_map.keys():
        left, right = old_map[identity], new_map[identity]
        kind = identity[0]
        counts[kind + '_changed_count'] += not same_declaration(left, right)
        for key in ('description', 'parameters', 'strict'):
            counts[key + '_changed_count'] += not same_field(left, right, key)
        other_keys = (left.keys() | right.keys()) - {'type', 'name', 'description', 'parameters', 'strict'}
        for field, owner, label in (
                ('tools', 'namespace', 'namespace_tools_changed_count'),
                ('format', 'custom', 'custom_format_changed_count'),
                ('execution', 'tool_search', 'tool_search_execution_changed_count')):
            if kind == owner:
                counts[label] += not same_field(left, right, field)
                if field == 'tools' and not same_field(left, right, field):
                    nested_pairs.append((left.get('tools'), right.get('tools')))
                other_keys.discard(field)
        if not same_field(left, right, 'defer_loading'):
            prior, current = left.get('defer_loading', False), right.get('defer_loading', False)
            if type(prior) is bool and type(current) is bool:
                if prior != current:
                    counts['defer_loading_changed_count'] += 1
                    direction = 'defer_loading_true_to_false_count' if prior else 'defer_loading_false_to_true_count'
                    counts[direction] += 1
                else:
                    counts['defer_loading_presence_only_count'] += 1
                other_keys.discard('defer_loading')
        counts['other_changed_count'] += any(not same_field(left, right, key) for key in other_keys)
    nested = {'bounded': True, 'identity_added_count': 0, 'identity_removed_count': 0,
        'same_identity_changed_count': 0, 'order_only_count': 0,
        'unclassifiable_count': 0}
    nested_fields = dict.fromkeys(('description', 'parameters', 'strict', 'format',
        'defer_loading_true_to_false', 'defer_loading_false_to_true',
        'defer_loading_presence_only'), 0)
    before_size = sum(len(left) for left, _ in nested_pairs if isinstance(left, list))
    after_size = sum(len(right) for _, right in nested_pairs if isinstance(right, list))
    if before_size > 1024 or after_size > 1024:
        nested['bounded'] = False
        nested['unclassifiable_count'] = len(nested_pairs)
    else:
        for left, right in nested_pairs:
            if not isinstance(left, list) or not isinstance(right, list):
                nested['unclassifiable_count'] += 1
                continue
            old_nested, new_nested = indexed(left, nested=True), indexed(right, nested=True)
            if old_nested is None or new_nested is None:
                nested['unclassifiable_count'] += 1
                continue
            old_items, old_sequence = old_nested
            new_items, new_sequence = new_nested
            nested['identity_added_count'] += len(new_items.keys() - old_items.keys())
            nested['identity_removed_count'] += len(old_items.keys() - new_items.keys())
            changed = sum(not same_declaration(old_items[key], new_items[key])
                for key in old_items.keys() & new_items.keys())
            nested['same_identity_changed_count'] += changed
            for key in old_items.keys() & new_items.keys():
                prior, current = old_items[key], new_items[key]
                for field in ('description', 'parameters', 'strict', 'format'):
                    nested_fields[field] += not same_field(prior, current, field)
                if not same_field(prior, current, 'defer_loading'):
                    old_defer, new_defer = prior.get('defer_loading', False), current.get('defer_loading', False)
                    label = ('defer_loading_presence_only' if old_defer == new_defer else
                        'defer_loading_true_to_false' if old_defer else 'defer_loading_false_to_true')
                    nested_fields[label] += 1
            nested['order_only_count'] += (old_items.keys() == new_items.keys()
                and old_sequence != new_sequence and changed == 0)
    if nested['same_identity_changed_count']:
        nested['field_changes'] = nested_fields
    return {'classified': True,
        'identity_added_count': len(new_map.keys() - old_map.keys()),
        'identity_removed_count': len(old_map.keys() - new_map.keys()),
        **counts, 'namespace_nested': nested,
        'order_changed': old_map.keys() == new_map.keys() and old_order != new_order}


class WebModelProtocol:
    """Reuse the existing route, tool map and terminal validator for one request.

    The transport owns lifetime and authentication. Calling these pure conversion
    methods does not admit a request, register a model or execute any returned call.
    """

    def __init__(self, route: ModelRoute, payload: dict, *, citation_mode='none'):
        if (route.responses is None or not route.slug.startswith("api/chatgpt-web/")
                or not isinstance(payload, dict) or payload.get("model") != route.slug):
            raise RouterError("web_explicit_route_required")
        if citation_mode not in ('none', 'markdown_links_v1'):
            raise RouterError('web_public_citation_mode_required')
        self.citation_mode = citation_mode
        prepared, context = prepare_request(payload, route.responses, route.reasoning_efforts)
        # MCP declarations have JSON-object arguments; registered custom sources
        # must use the existing explicit wrapper rather than a second exec codec.
        for tool in prepared.get("tools", []):
            if tool.get("type") != "function":
                raise RouterError("web_mcp_function_representation_required")
            if tool["parameters"].get("type") != "object":
                raise RouterError("web_mcp_object_schema_required")
            if "description" in tool and not isinstance(tool["description"], str):
                raise RouterError("web_mcp_text_description_required")
        self.route = route
        self._source_input = deepcopy(payload.get("input"))
        # A single browser generation has already consumed these controls.
        # Bind the original declarations too: MCP projection omits e.g. strict
        # and compilation may narrow parallel permission. JSON preserves the
        # distinction between boolean/number and absent/null; key order is not
        # significant. This representation stays in memory, never in receipts.
        controls = deepcopy({key: value for key, value in payload.items() if key != "input"})
        metadata = controls.get("client_metadata")
        if isinstance(metadata, dict) and "x-codex-turn-metadata" in metadata:
            # Observed CLI 0.154.0-alpha.6.2 serializes this JSON-object transport
            # field in different key orders between tool steps. Compare its
            # complete data, without changing the original request or history.
            raw = metadata["x-codex-turn-metadata"]
            if not isinstance(raw, str):
                raise RouterError("web_turn_metadata_json_object_required")
            decoded = loads(raw)
            if not isinstance(decoded, dict):
                raise RouterError("web_turn_metadata_json_object_required")
            # Only the dated Git telemetry shapes are excluded from comparison.
            # Unknown fields, tool grants and sandbox overrides remain rejected.
            if "workspaces" in decoded:
                if not workspace_telemetry(decoded["workspaces"]):
                    raise RouterError("web_workspace_telemetry_shape_unsupported")
                del decoded["workspaces"]
            metadata["x-codex-turn-metadata"] = decoded
        self._continuation_contract = json.dumps(controls,
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._prepared = prepared
        self._context = context

    def request(self):
        """Return the complete mapped request, not a rewritten privileged prompt."""
        return {**deepcopy(self._prepared), "model": self.route.model}

    def mcp_tools(self):
        """Describe only the tools actually visible in this Codex request."""
        return [{"name": tool["name"], "description": tool.get("description", ""),
                 "inputSchema": deepcopy(tool["parameters"])}
                for tool in self._prepared.get("tools", [])]

    def source_input(self):
        """Original validated history, for lossless labelled MCP result return."""
        return deepcopy(self._source_input)

    def mcp_tool_sources(self):
        """Exact source identities for the current visible inventory only."""
        return {tool['name']: {'type': spec.kind, 'name': spec.name,
            'namespace': spec.namespace}
            for tool in self._prepared.get('tools', [])
            for spec in [self._context.upstream[tool['name']]]}

    def continuation_contract(self):
        """Exact original non-history controls for one browser generation."""
        return self._continuation_contract

    def description_refresh_candidates(self, previous):
        """Return visible aliases only when leaf descriptions are the sole change.

        This does not authorize a refresh. The indexed transport must prove that
        none of these schemas has been read, then validate the exact native result
        before publishing them. Namespace descriptions and hidden declarations
        remain bound, as do every non-description value, presence and array order.
        """
        def canonical(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True,
                separators=(',', ':'), allow_nan=False)

        before, after = (json.loads(item.continuation_contract()) for item in (previous, self))
        old_tools, new_tools = before.pop('tools', None), after.pop('tools', None)
        if canonical(before) != canonical(after):
            return None
        changed = set()

        def visit(old, new, namespace=None):
            if not isinstance(old, list) or not isinstance(new, list) or len(old) != len(new):
                return False
            for left, right in zip(old, new):
                if canonical(left) == canonical(right):
                    continue
                if not isinstance(left, dict) or not isinstance(right, dict) or left.keys() != right.keys():
                    return False
                if left.get('type') == 'namespace' and namespace is None:
                    if (canonical({k: v for k, v in left.items() if k != 'tools'})
                            != canonical({k: v for k, v in right.items() if k != 'tools'})
                            or not visit(left.get('tools'), right.get('tools'), left.get('name'))):
                        return False
                elif (left.get('type') in ('function', 'custom')
                        and isinstance(left.get('description'), str)
                        and isinstance(right.get('description'), str)
                        and canonical({k: v for k, v in left.items() if k != 'description'})
                            == canonical({k: v for k, v in right.items() if k != 'description'})):
                    changed.add((left['type'], namespace, left['name']))
                else:
                    return False
            return True

        if not visit(old_tools, new_tools) or not changed:
            return None
        sources = self.mcp_tool_sources()
        if sources != previous.mcp_tool_sources():
            return None
        names = {name for name, source in sources.items()
            if (source['type'], source['namespace'], source['name']) in changed}
        if len(names) != len(changed):
            return None  # No refresh of a deferred/hidden source via this path.
        old, new = previous._prepared.get('tools', []), self._prepared.get('tools', [])
        if len(old) != len(new):
            return None
        for left, right in zip(old, new):
            if left['name'] in names:
                if (canonical({k: v for k, v in left.items() if k != 'description'})
                        != canonical({k: v for k, v in right.items() if k != 'description'})):
                    return None
            elif canonical(left) != canonical(right):
                return None
        return names

    def continuation_changes(self, previous):
        """Fixed field labels only; never values, arbitrary keys or permissions.

        This observes a rejected binding. It does not make any changed field
        acceptable and does not retain the source contract outside memory.
        """
        before = json.loads(previous.continuation_contract())
        after = json.loads(self.continuation_contract())

        def changed(left, right, known):
            left = left if isinstance(left, dict) else {}
            right = right if isinstance(right, dict) else {}
            keys = {key for key in left.keys() | right.keys()
                if key not in left or key not in right or json.dumps(left[key], sort_keys=True,
                    ensure_ascii=False, allow_nan=False) != json.dumps(right[key], sort_keys=True,
                    ensure_ascii=False, allow_nan=False)}
            return sorted({key if key in known else 'other' for key in keys})

        fields = changed(before, after, {'model', 'tools', 'tool_choice', 'parallel_tool_calls',
            'instructions', 'reasoning', 'text', 'stream', 'store', 'include', 'metadata',
            'client_metadata', 'prompt_cache_key', 'service_tier', 'max_output_tokens',
            'previous_response_id', 'temperature', 'top_p'})
        result = {'fields': fields}
        if 'tools' in fields:
            original, continued = before.get('tools', []), after.get('tools', [])
            if not isinstance(original, list) or not isinstance(continued, list):
                result['tool_declarations'] = {'bounded': False}
            elif len(original) > 1024 or len(continued) > 1024:
                result['tool_declarations'] = {'bounded': False,
                    'before_count': min(len(original), 1024),
                    'after_count': min(len(continued), 1024)}
            else:
                # Source descriptions, schemas, names and digests never leave
                # this rejected turn, including in the fixed-label field count.
                def inventory(values):
                    return Counter(json.dumps(value, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':'), allow_nan=False) for value in values)
                old, new = inventory(original), inventory(continued)
                result['tool_declarations'] = {'bounded': True,
                    'before_count': len(original), 'after_count': len(continued),
                    'added_count': sum((new - old).values()),
                    'removed_count': sum((old - new).values()),
                    'change_kinds': _tool_declaration_change_kinds(original, continued)}
        if 'client_metadata' in fields:
            left, right = before.get('client_metadata'), after.get('client_metadata')
            result['client_metadata'] = changed(left, right,
                {'thread_id', 'turn_id', 'x-codex-turn-metadata', 'session_id', 'originator'})
            if 'x-codex-turn-metadata' in result['client_metadata']:
                result['turn_metadata'] = changed(
                    left.get('x-codex-turn-metadata') if isinstance(left, dict) else None,
                    right.get('x-codex-turn-metadata') if isinstance(right, dict) else None,
                    {'thread_id', 'turn_id', 'session_id', 'turn_source', 'sandbox',
                        'sandbox_mode', 'auto_review_enabled', 'approval_policy',
                        'model', 'reasoning_effort', 'cwd', 'workspaces'})
        return result

    def complete(self, response):
        """Validate the complete structured result before returning any tool/event.

        Only the authenticated transport may submit a response. A tool-call
        boundary and a browser's final answer are separate transport facts.
        This is buffered event serialization, never first-token timing evidence.
        """
        if not isinstance(response, dict) or response.get("model") != self.route.model:
            raise RouterError("web_response_model_mismatch")
        restored = restore_response(response, self._context)
        restored["model"] = self.route.slug
        # The existing serializer preflights actual event and cumulative UTF-8
        # limits, including repeated snapshots, before exposing the first event.
        events = tuple(completed_response_events(restored))
        return restored, events

    def complete_public_message(self, response_id, message):
        """Accept a final public message from an already-bound browser turn."""
        item = public_web_message(message, citation_mode=self.citation_mode)
        if item["phase"] != "final_answer":
            raise RouterError("web_commentary_is_not_final_answer")
        return self.complete({"id": identifier(response_id), "object": "response",
            "status": "completed", "model": self.route.model, "output": [item],
            # The browser does not supply API billing counters. Do not invent them.
            "usage": None})
