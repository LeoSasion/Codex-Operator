"""Dated public Web picker contract, separate from API model capabilities.

Pro is a distinct Web model entry. Its sole native max setting selects the
observed Pro position, not an assertion about API reasoning effort equivalence.
"""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .responses_capabilities import RouterError

CATALOG_PATH = Path(__file__).with_suffix('.json')
CATALOG = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
MODELS = CATALOG['models']
PREFIX = 'api/chatgpt-web/'
UNVERIFIED_ROUTE_CONTEXT_WINDOW = 16000


def route_context_window(model, definition):
    """Use a model-bound Web capacity only after its evidence is recorded.

    The fallback is an existing provisional route value, not a claim about the
    selected ChatGPT Web model or its separate composer/request size limit.
    A single catalog slug covers all its advertised efforts, so a recorded
    capacity must cover precisely that complete effort set.
    """
    record = definition.get('context_window', {'status': 'unverified'})
    if record == {'status': 'unverified'}:
        return UNVERIFIED_ROUTE_CONTEXT_WINDOW
    if (not isinstance(record, dict)
            or set(record) != {'status', 'model', 'reasoning_efforts', 'tokens', 'source'}
            or record['status'] != 'verified' or record['model'] != model
            or record['reasoning_efforts'] != definition['reasoning_efforts']
            or type(record['tokens']) is not int
            or not 1024 <= record['tokens'] <= 2000000):
        raise RouterError('web_context_record_invalid')
    source = record['source']
    if not isinstance(source, dict) or set(source) != {'kind', 'reference'}:
        raise RouterError('web_context_record_invalid')
    reference = source['reference']
    if not isinstance(reference, str) or not 1 <= len(reference) <= 512:
        raise RouterError('web_context_record_invalid')
    if source['kind'] == 'official_web_documentation':
        try:
            parsed = urlsplit(reference)
            port = parsed.port
        except ValueError:
            raise RouterError('web_context_record_invalid') from None
        if (parsed.scheme != 'https' or parsed.hostname not in {
                'openai.com', 'help.openai.com', 'chatgpt.com', 'developers.openai.com'}
                or parsed.username or parsed.password or parsed.query
                or port not in (None, 443) or not parsed.path or parsed.path == '/'
                or any(ord(char) <= 32 or ord(char) == 127 for char in reference)):
            raise RouterError('web_context_record_invalid')
    elif source['kind'] == 'observed_web_account':
        if not re.fullmatch(r'web-context-[a-z0-9-]{8,80}', reference):
            raise RouterError('web_context_record_invalid')
    else:
        raise RouterError('web_context_record_invalid')
    return record['tokens']


def browser_selection(protocol):
    model = protocol.route.model
    definition = MODELS.get(model)
    if definition is None:
        raise RouterError('web_explicit_model_required')
    effort = (protocol.request().get('reasoning') or {}).get('effort')
    if effort is None:
        effort = definition['reasoning_efforts'][0]
    if effort not in definition['reasoning_efforts']:
        raise RouterError('web_explicit_effort_required')
    return {'model': model, 'effort': effort}


def matches_selection(value, selection):
    return (value.get('model') == selection['model']
        and type(value.get('effortIndex')) is int
        and value['effortIndex'] == CATALOG['efforts'][selection['effort']]['index'])
