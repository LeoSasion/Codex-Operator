"""Pure direct-provider Desktop config candidate and bounded read-only preview.

There is deliberately no activation, application launch, service control or
business request here. Desktop must be closed before a separately reviewed
transaction can use the candidate. Existing native profiles supply the endpoint
contract; this module never translates model input/output or changes histories.
"""
from copy import deepcopy
from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

import operator_native_models as native

LIMIT = 1024 * 1024
SELECTORS = ('model', 'model_provider', 'model_catalog_json', 'model_reasoning_effort', 'web_search')
BEGIN = b'# BEGIN OPERATOR DIRECT DESKTOP\n'
END = b'# END OPERATOR DIRECT DESKTOP\n'
PROVIDER_BEGIN = b'\n# BEGIN OPERATOR DIRECT DESKTOP PROVIDER\n'
PROVIDER_END = b'# END OPERATOR DIRECT DESKTOP PROVIDER\n'
SAVED = b'# OPERATOR DIRECT SAVED SELECTOR '
BOM = b'\xef\xbb\xbf'
LEGACY = re.compile(rb'\A# BEGIN FEISHU OPERATOR MODEL ROUTER\r?\n'
    rb'# [ \t]*openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:([0-9]{1,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n'
    rb'# END FEISHU OPERATOR MODEL ROUTER\r?\n')
SELECTOR = re.compile(rb'^[ \t]*(model|model_provider|model_catalog_json|model_reasoning_effort|web_search)[ \t]*=')

class DirectProfileError(ValueError):
    pass

def require(value, code):
    if not value:
        raise DirectProfileError('direct_profile_' + code)

def parse(raw):
    require(isinstance(raw, bytes) and len(raw) <= LIMIT, 'config_bound')
    try:
        return tomllib.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise DirectProfileError('direct_profile_invalid_config') from None

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class Candidate:
    data: bytes
    # A private projection description, never installation ownership or authority.
    recovery: dict

def _leading(raw):
    bom = BOM if raw.startswith(BOM) else b''
    text = raw[len(bom):]
    legacy = LEGACY.match(text)
    if legacy:
        require(1 <= int(legacy[1]) <= 65535, 'legacy_port_invalid')
        lead = bom + legacy[0]
        text = text[len(legacy[0]):]
    else:
        lead = bom
    require(text.count(b'# BEGIN FEISHU OPERATOR MODEL ROUTER') == 0
        and text.count(b'# END FEISHU OPERATOR MODEL ROUTER') == 0, 'legacy_marker_conflict')
    return lead, text

def render(before, manifest, home, *, selector_mutation=False):
    """Keep native selectors as exact commented lines and all other bytes intact."""
    original = parse(before)
    manifest = native.validate_manifest(manifest)
    require(isinstance(home, Path) and home.is_absolute(), 'absolute_home_required')
    require(original.get('model_provider', 'openai') == 'openai', 'native_baseline_required')
    require('profile' not in original, 'legacy_profile_conflict')
    require(original.get('openai_base_url') in (None, 'https://api.openai.com/v1',
        'https://chatgpt.com/backend-api/codex'), 'native_endpoint_conflict')
    require(not any(marker in before for marker in
        (BEGIN.rstrip(), END.rstrip(), PROVIDER_BEGIN.strip(), PROVIDER_END.rstrip(), SAVED,
         b'# BEGIN OPERATOR UNIFIED', b'# BEGIN OPERATOR MODEL ROUTER')), 'managed_marker_conflict')
    outputs, provider_id = native.artifacts(manifest, home)
    profile = parse(outputs['profile'])
    settings = {key: profile[key] for key in SELECTORS}
    provider = profile['model_providers'][provider_id]
    require(provider_id not in original.get('model_providers', {}), 'provider_collision')
    lead, body = _leading(before)
    lines = body.splitlines(keepends=True)
    root = True
    saved = []
    modified = []
    for line in lines:
        if line.lstrip().startswith(b'['):
            root = False
        match = SELECTOR.match(line) if root else None
        if match:
            key = match[1].decode('ascii')
            require(key in original and key not in [entry['key'] for entry in saved], 'selector_shape')
            saved.append({'key': key, 'line_hex': line.hex()})
            modified.append(SAVED + line)
        else:
            modified.append(line)
    require(set(entry['key'] for entry in saved) == set(SELECTORS) & set(original), 'selector_shape')
    prefix = BEGIN + ('# profile: ' + manifest['profile'] + '\n').encode('ascii')
    prefix += ''.join(key + ' = ' + json.dumps(settings[key], ensure_ascii=True) + '\n'
        for key in SELECTORS).encode('ascii') + END
    suffix = PROVIDER_BEGIN + ('[model_providers.' + provider_id + ']\n').encode('ascii')
    suffix += ''.join(key + ' = ' + json.dumps(value, ensure_ascii=True) + '\n'
        for key, value in provider.items()).encode('ascii') + PROVIDER_END
    # The new separator belongs to the suffix and disappears on recovery.
    require(not body or body.endswith(b'\n'), 'final_newline_required')
    data = lead + prefix + b''.join(modified) + suffix
    wanted = deepcopy(original)
    wanted.update(settings)
    wanted.setdefault('model_providers', {})[provider_id] = provider
    require(parse(data) == wanted, 'scope_changed')
    recovery = {'version': 1, 'contract': 'direct_profile_projection_v1',
        'before_sha256': digest(before), 'candidate_sha256': digest(data),
        'leading_hex': lead.hex(), 'prefix_hex': prefix.hex(), 'suffix_hex': suffix.hex(),
        'saved': saved, 'settings': settings, 'provider_id': provider_id, 'provider': provider,
        'profile': manifest['profile'], 'efforts': manifest['model']['reasoning_efforts']}
    if selector_mutation:
        require(selector_mutation is True, 'mutation_contract_invalid')
        recovery.update(version=2, contract='direct_profile_projection_v2',
            selector_mutation={'contract': 'model_effort_v1', 'model': manifest['model']['id'],
                'efforts': manifest['model']['reasoning_efforts']})
    return Candidate(data, recovery)

def restore(current, recovery):
    """Pure recovery; preserve later edits outside the exact owned projection."""
    keys = {
        'version', 'contract', 'before_sha256', 'candidate_sha256', 'leading_hex', 'prefix_hex',
        'suffix_hex', 'saved', 'settings', 'provider_id', 'provider', 'profile', 'efforts'}
    require(isinstance(recovery, dict), 'recovery_invalid')
    mutation = recovery.get('version') == 2
    require(set(recovery) == keys | ({'selector_mutation'} if mutation else set())
        and recovery.get('version') == (2 if mutation else 1)
        and recovery.get('contract') == ('direct_profile_projection_v2' if mutation
            else 'direct_profile_projection_v1'), 'recovery_invalid')
    parsed = parse(current)
    try:
        lead, prefix, suffix = [bytes.fromhex(recovery[key]) for key in ('leading_hex', 'prefix_hex', 'suffix_hex')]
        saved = [(entry['key'], bytes.fromhex(entry['line_hex'])) for entry in recovery['saved']]
    except (KeyError, TypeError, ValueError):
        raise DirectProfileError('direct_profile_recovery_invalid') from None
    require(lead == _leading(current)[0] and prefix.startswith(BEGIN) and prefix.endswith(END)
        and suffix.startswith(PROVIDER_BEGIN) and suffix.endswith(PROVIDER_END), 'recovery_invalid')
    require(isinstance(recovery['settings'], dict) and set(recovery['settings']) == set(SELECTORS)
        and native.PROFILE.fullmatch(recovery['profile']) is not None
        and recovery['provider_id'] == native.provider_name(recovery['profile']), 'recovery_invalid')
    require(parse(prefix) == recovery['settings']
        and parse(suffix) == {'model_providers': {recovery['provider_id']: recovery['provider']}}, 'recovery_invalid')
    owned_prefix = prefix
    if mutation:
        policy = recovery['selector_mutation']
        require(isinstance(policy, dict) and set(policy) == {'contract', 'model', 'efforts'}
            and policy['contract'] == 'model_effort_v1' and policy['model'] == recovery['settings']['model']
            and policy['efforts'] == recovery['efforts'] and isinstance(policy['efforts'], list)
            and bool(policy['efforts']) and all(isinstance(effort, str) and effort in native.EFFORTS for effort in policy['efforts'])
            and len(set(policy['efforts'])) == len(policy['efforts']), 'mutation_contract_invalid')
        effort = parsed.get('model_reasoning_effort')
        require(parsed.get('model') == policy['model'] and effort in policy['efforts'], 'selection_changed')
        original_line = ('model_reasoning_effort = ' + json.dumps(recovery['settings']['model_reasoning_effort']) + '\n').encode('ascii')
        selected_line = ('model_reasoning_effort = ' + json.dumps(effort) + '\n').encode('ascii')
        require(prefix.count(original_line) == 1, 'recovery_invalid')
        owned_prefix = prefix.replace(original_line, selected_line, 1)
    require(current.startswith(lead + owned_prefix), 'selection_changed')
    require(current.count(BEGIN) == current.count(END) == 1 and current.count(PROVIDER_BEGIN) ==
        current.count(PROVIDER_END) == 1 and current.count(suffix) == 1, 'owned_block_changed')
    require(parsed.get('model_providers', {}).get(recovery['provider_id']) == recovery['provider'], 'provider_changed')
    body = current[len(lead + owned_prefix):].replace(suffix, b'', 1)
    for key, line in saved:
        require(key in SELECTORS and b'\n' not in line.rstrip(b'\r\n')
            and b'\r' not in line.rstrip(b'\r\n')
            and set(parse(line)) == {key} and body.count(SAVED + line) == 1, 'saved_selector_changed')
        body = body.replace(SAVED + line, line, 1)
    require(SAVED not in body, 'saved_selector_changed')
    result = lead + body
    expected = deepcopy(parsed)
    for key in SELECTORS:
        expected.pop(key, None)
    native_selectors = parse(b''.join(line for _, line in saved))
    require(set(native_selectors) == {key for key, _ in saved}
        and native_selectors.get('model_provider', 'openai') == 'openai', 'recovery_invalid')
    expected.update(native_selectors)
    expected['model_providers'].pop(recovery['provider_id'])
    if not expected['model_providers']:
        expected.pop('model_providers')
    restored = parse(result)
    if not expected.get('model_providers') and 'model_providers' in restored:
        expected['model_providers'] = {}
    require(restored == expected, 'recovery_scope_changed')
    return result

def preview(state, home, *, baseline=None):
    """Review an installed native profile without touching its real base config."""
    state, home = native.checked_path(state, directory=True), native.checked_path(home, directory=True)
    status = native.status(state, home)
    require(status['status'] == 'installed', 'profile_not_installed')
    _, manifest, files, _ = native.load(state, home)
    generated, _ = native.artifacts(manifest, home)
    require(all(generated[kind] == files[kind]['prepared'][0] for kind in ('profile', 'catalog')), 'profile_source_changed')
    source = home / 'config.toml' if baseline is None else native.checked_path(baseline)
    before = native.read(source)
    candidate = render(before, manifest, home)
    require(restore(candidate.data, candidate.recovery) == before, 'roundtrip_failed')
    return {'status': 'preview', 'model': manifest['model']['id'], 'kind': manifest['kind'],
        'profile': manifest['profile'], 'before_sha256': digest(before),
        'candidate_sha256': digest(candidate.data), 'config_bytes_preserved_on_restore': True,
        'baseline_is_live_config': baseline is None, 'model_requests': 0, 'configuration_changed': False,
        'router_required': False, 'desktop_launch': False, 'desktop_acceptance': 'unverified'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    try:
        value = preview(args.state, args.home, baseline=args.baseline)
    except (DirectProfileError, native.NativeModelsError) as error:
        reason = str(error)
        if re.fullmatch(r'(?:direct_profile|native_models)_[a-z_]{1,80}', reason) is None:
            reason = 'direct_profile_preview_rejected'
        print(json.dumps({'status': 'needs_review', 'model_requests': 0, 'configuration_changed': False,
            'reason': reason}))
        return 1
    print(json.dumps(value, ensure_ascii=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
