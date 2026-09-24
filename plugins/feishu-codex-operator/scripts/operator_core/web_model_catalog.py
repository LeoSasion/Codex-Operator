"""Dated public Web picker contract, separate from API model capabilities.

Pro is a distinct Web model entry. Its sole native max setting selects the
observed Pro position, not an assertion about API reasoning effort equivalence.
"""
import json
from pathlib import Path

from .responses_capabilities import RouterError

CATALOG_PATH = Path(__file__).with_suffix('.json')
CATALOG = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
MODELS = CATALOG['models']
PREFIX = 'api/chatgpt-web/'


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
