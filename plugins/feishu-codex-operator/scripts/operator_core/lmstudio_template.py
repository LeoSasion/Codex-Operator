"""Explicit compatibility for one observed Huihui template; no model control.

The complete source template and model defaults remain private local settings.
This function only prepares a digest-bound candidate. Applying, loading, native
rendering, execution and restoring the retained original are separate actions.
"""

from copy import deepcopy
import hashlib

from .model_registry import RouterError


HUIHUI_MODEL = 'huihui-qwen3.8-27b-abliterated'
HUIHUI_SOURCE_SHA256 = 'd6faec65555d20276f5bb0bed387e7776b484768ff280c18d69161abc4dfb769'
HUIHUI_LOAD_SOURCE_SHA256 = '12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce'
_REJECT = "{{- raise_exception('System message must be at the beginning.') }}"
_ORDERED_BLOCK = "{{- '<|im_start|>system\\n' + render_content(message.content, false, true) + '<|im_end|>\\n' }}"


def _candidate(template, source_sha256):
    if (not isinstance(template, str) or len(template.encode('utf-8')) > 256 * 1024
            or hashlib.sha256(template.encode('utf-8')).hexdigest() != source_sha256
            or template.count(_REJECT) != 1):
        raise RouterError('lmstudio_template_source_changed')
    return template.replace(_REJECT, _ORDERED_BLOCK, 1)


def huihui_candidate(template):
    """Render already privileged text messages at their existing positions.

    Existing leading blocks and every user/assistant/tool branch stay byte
    identical. The new branch preserves edge whitespace and uses the original
    system-content renderer, which rejects images, videos and unknown shapes.
    It never discovers an instruction in ordinary text or changes source roles.
    """
    return _candidate(template, HUIHUI_SOURCE_SHA256)


def huihui_load_candidate(template):
    # The observed engine load representation adds its original tojson safe
    # filter. Retain that separate representation instead of copying prediction
    # bytes over it or accepting arbitrary conversion differences.
    return _candidate(template, HUIHUI_LOAD_SOURCE_SHA256)


def huihui_model_defaults(base_prediction_config, base_load_config=None):
    """Prepare the two matching per-model fields, retaining stop strings."""
    if not isinstance(base_prediction_config, dict):
        raise RouterError('lmstudio_template_config_invalid')
    original = base_prediction_config.get('promptTemplate')
    if (not isinstance(original, dict) or set(original) != {'type', 'jinjaPromptTemplate', 'stopStrings'}
            or original['type'] != 'jinja' or not isinstance(original['jinjaPromptTemplate'], dict)
            or set(original['jinjaPromptTemplate']) != {'template'}
            or not isinstance(original['stopStrings'], list)
            or any(not isinstance(value, str) for value in original['stopStrings'])):
        raise RouterError('lmstudio_template_config_invalid')
    prediction = deepcopy(original)
    prediction['jinjaPromptTemplate']['template'] = huihui_candidate(original['jinjaPromptTemplate']['template'])
    loading = {key: deepcopy(prediction[key]) for key in ('type', 'jinjaPromptTemplate')}
    if base_load_config is not None:
        original_load = base_load_config.get('promptTemplate') if isinstance(base_load_config, dict) else None
        if (not isinstance(original_load, dict) or set(original_load) != {'type', 'jinjaPromptTemplate'}
                or original_load['type'] != 'jinja' or not isinstance(original_load['jinjaPromptTemplate'], dict)
                or set(original_load['jinjaPromptTemplate']) != {'template'}):
            raise RouterError('lmstudio_template_load_config_invalid')
        loading = deepcopy(original_load)
        loading['jinjaPromptTemplate']['template'] = huihui_load_candidate(
            original_load['jinjaPromptTemplate']['template'])
    return {'preset': '', 'operation': {'fields': [
        {'key': 'llm.prediction.promptTemplate', 'value': prediction}]},
        'load': {'fields': [{'key': 'llm.load.promptTemplate', 'value': loading}]}}
