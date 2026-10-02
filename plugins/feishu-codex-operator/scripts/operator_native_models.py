"""Explicit native Responses file profiles; no global route or model requests."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import tomllib
from urllib.parse import urlsplit

from operator_core.web_browser_driver import private_directory


LIMIT = 1024 * 1024
PROFILE = re.compile(r'operator-[a-z0-9][a-z0-9-]{0,49}')
EFFORTS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}


class NativeModelsError(ValueError):
    pass


def require(value, code):
    if not value:
        raise NativeModelsError('native_models_' + code)


def checked_path(value, *, directory=False, exists=True):
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'absolute_path_required')
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        # is_junction is unavailable on supported Python 3.11. Reject every
        # Windows reparse point using the metadata of the link itself.
        require(not stat.S_ISLNK(info.st_mode)
            and not getattr(info, 'st_file_attributes', 0) & 0x400,
            'linked_path_rejected')
    if exists:
        require(path.is_dir() if directory else path.is_file(), 'path_unavailable')
    if path.exists() and not directory:
        require(path.is_file() and path.stat().st_nlink == 1, 'regular_file_required')
    return path


def read(path):
    path = checked_path(path)
    with path.open('rb') as stream:
        value = stream.read(LIMIT + 1)
    require(len(value) <= LIMIT, 'file_bound')
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_field')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
            parse_constant=lambda _: require(False, 'invalid_json'))
    except (UnicodeError, json.JSONDecodeError):
        raise NativeModelsError('native_models_invalid_json') from None


def json_bytes(value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    require(len(raw) <= LIMIT, 'file_bound')
    return raw


def text(value, maximum=256):
    require(isinstance(value, str) and 0 < len(value) <= maximum
        and value == value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value),
        'invalid_text')
    return value


def validate_manifest(value):
    require(isinstance(value, dict) and set(value) == {
        'version', 'contract', 'kind', 'profile', 'provider', 'model', 'web_search'}
        and type(value['version']) is int and value['version'] == 1
        and value['contract'] == 'native_responses_v1'
        and value['kind'] in ('api', 'local'), 'explicit_native_contract_required')
    require(isinstance(value['profile'], str) and PROFILE.fullmatch(value['profile']), 'profile_invalid')
    provider, model = value['provider'], value['model']
    require(isinstance(provider, dict) and set(provider) == {'name', 'base_url', 'env_key'},
        'provider_fields_invalid')
    text(provider['name'])
    base = text(provider['base_url'], 2048)
    try:
        url = urlsplit(base)
        valid = (url.scheme in ('http', 'https') and bool(url.hostname)
            and not url.username and not url.password and not url.query and not url.fragment
            and '%' not in url.netloc and '\\' not in base
            and (url.port is None or 1 <= url.port <= 65535))
    except ValueError:
        valid = False
    require(valid, 'base_url_invalid')
    loopback = url.hostname in ('127.0.0.1', '::1')
    require((value['kind'] == 'local' and loopback)
        or (value['kind'] == 'api' and url.scheme == 'https'), 'endpoint_scope_invalid')
    key = provider['env_key']
    require(isinstance(key, str) and (re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}', key)
        or key == '' and value['kind'] == 'local'), 'key_environment_required')
    require(isinstance(model, dict) and set(model) == {'id', 'display_name', 'context_window',
        'reasoning_efforts', 'default_reasoning_effort', 'input_modalities', 'tool_mode',
        'supports_search_tool'}, 'model_fields_invalid')
    text(model['id']); text(model['display_name'])
    require(type(model['context_window']) is int and 1024 <= model['context_window'] <= 2000000,
        'context_window_invalid')
    efforts = model['reasoning_efforts']
    require(isinstance(efforts, list) and bool(efforts) and len(efforts) <= len(EFFORTS)
        and all(isinstance(e, str) and e in EFFORTS for e in efforts)
        and len(set(efforts)) == len(efforts)
        and model['default_reasoning_effort'] in efforts, 'reasoning_invalid')
    require(model['input_modalities'] in (['text'], ['text', 'image'])
        and model['tool_mode'] in ('standard', 'code_mode_only')
        and type(model['supports_search_tool']) is bool, 'model_capabilities_invalid')
    require(value['web_search'] in ('disabled', 'cached', 'live'), 'search_mode_invalid')
    return deepcopy(value)


def artifacts(manifest, home):
    manifest = validate_manifest(manifest)
    model, provider = manifest['model'], manifest['provider']
    profile = manifest['profile']
    provider_id = provider_name(profile)
    template = decode(read(Path(__file__).with_name('operator_core') / 'beeper_model_catalog.json'))
    row = deepcopy(template['models'][0])
    for key in ('comp_hash', 'availability_nux', 'auto_compact_token_limit'):
        row.pop(key, None)
    row.update(slug=model['id'], display_name=model['display_name'],
        description='Explicit native Responses profile; capabilities require separate verification.',
        priority=1000, visibility='list', supported_in_api=True, upgrade=None,
        context_window=model['context_window'], max_context_window=model['context_window'],
        effective_context_window_percent=95, multi_agent_version='disabled',
        input_modalities=model['input_modalities'], supports_search_tool=model['supports_search_tool'],
        default_reasoning_level=model['default_reasoning_effort'],
        supported_reasoning_levels=[{'effort': effort, 'description': effort} for effort in model['reasoning_efforts']],
        tool_mode=None if model['tool_mode'] == 'standard' else 'code_mode_only',
        node_repl_disabled=model['tool_mode'] == 'standard', node_repl_auto_review_required=True,
        apply_patch_tool_type=None if model['tool_mode'] == 'standard' else 'freeform',
        base_instructions='', model_messages={}, use_responses_lite=False)
    catalog_path = home / (profile + '.catalog.json')
    settings = {'model': model['id'], 'model_provider': provider_id,
        'model_catalog_json': str(catalog_path),
        'model_reasoning_effort': model['default_reasoning_effort'], 'web_search': manifest['web_search']}
    endpoint = {'name': provider['name'], 'base_url': provider['base_url'],
        'wire_api': 'responses', 'requires_openai_auth': False,
        'request_max_retries': 0, 'stream_max_retries': 0, 'supports_websockets': False}
    if provider['env_key']:
        endpoint['env_key'] = provider['env_key']
    lines = ['# Codex-Operator: explicit native file profile; global defaults are unchanged.']
    lines += [key + ' = ' + json.dumps(value, ensure_ascii=True) for key, value in settings.items()]
    lines += ['', '[model_providers.' + provider_id + ']']
    lines += [key + ' = ' + json.dumps(value, ensure_ascii=True) for key, value in endpoint.items()]
    profile_bytes = ('\n'.join(lines) + '\n').encode('utf-8')
    tomllib.loads(profile_bytes.decode())
    return {'profile': profile_bytes, 'catalog': json_bytes({'models': [row]})}, provider_id


def provider_name(profile):
    return 'operator_native_' + profile.removeprefix('operator-').replace('-', '_')


def check_base_provider(home, provider):
    # Native file profiles deeply merge provider tables with base config.
    # An omitted header/auth field would otherwise survive onto our endpoint.
    raw, existed = snapshot(Path(home) / 'config.toml')
    if not existed:
        return
    try:
        parsed = tomllib.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise NativeModelsError('native_models_base_config_invalid') from None
    providers = parsed.get('model_providers', {})
    require(isinstance(providers, dict), 'base_config_invalid')
    require(provider not in providers, 'base_provider_collision')


def snapshot(path):
    path = checked_path(path, exists=False)
    return (read(path), True) if path.exists() else (b'', False)


def replace_file(path, expected, replacement):
    """One bounded atomic replacement, rejecting edits immediately before write."""
    require(snapshot(path) == expected, 'target_changed')
    if replacement is None:
        if expected[1]:
            require(snapshot(path) == expected, 'target_changed')
            path.unlink()
        return
    require(len(replacement) <= LIMIT, 'file_bound')
    descriptor, name = tempfile.mkstemp(prefix='.operator-native-', suffix='.pending', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(replacement); stream.flush(); os.fsync(stream.fileno())
        if expected[1]: temporary.chmod(path.stat().st_mode & 0o777)
        require(snapshot(path) == expected, 'target_changed')
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


def write_record(path, value):
    replace_file(path, snapshot(path), json_bytes(value))


@contextmanager
def lock(state):
    state = checked_path(state, directory=True)
    path = state / 'operation.lock'
    marker = secrets.token_hex(16).encode()
    try:
        with path.open('xb') as stream: stream.write(marker)
    except FileExistsError:
        raise NativeModelsError('native_models_operation_in_progress') from None
    try:
        yield
    finally:
        require(read(path) == marker, 'lock_changed')
        path.unlink()


@contextmanager
def target_lock(state, home, plan, *, initial_phase):
    """Serialize a target across state directories; retain uncertain ownership."""
    home = checked_path(home, directory=True)
    path = checked_path(home / ('.' + plan['profile'] + '.operation.lock'), exists=False)
    binding = {'version': 1, 'state': str(state), 'home': str(home),
        'profile': plan['profile'], 'plan_sha256': digest(read(state / 'plan.json'))}
    if initial_phase == 'installing':
        require(path.is_file(), 'target_recovery_ownership_missing')
        marker = read(path)
        saved = decode(marker)
        require(isinstance(saved, dict) and set(saved) == set(binding) | {'nonce'}
            and all(saved[key] == value for key, value in binding.items())
            and isinstance(saved['nonce'], str) and re.fullmatch('[a-f0-9]{32}', saved['nonce']),
            'target_recovery_ownership_changed')
    else:
        marker = json_bytes({**binding, 'nonce': secrets.token_hex(16)})
        try:
            with path.open('xb') as stream:
                stream.write(marker); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            raise NativeModelsError('native_models_target_operation_in_progress') from None
    def verify():
        require(read(path) == marker, 'target_lock_changed')
        require(digest(read(state / 'plan.json')) == binding['plan_sha256'], 'plan_changed')
    mutation = {'started': False}
    try:
        verify()
        yield verify, mutation
    except BaseException:
        # A failed preflight wrote no target or journal. Every started/unknown
        # mutation retains the exact claim for explicit recovery, never a retry.
        phase = None
        if not mutation['started']:
            try:
                phase = decode(read(state / 'journal.json')).get('phase')
            except (OSError, ValueError, TypeError, AttributeError):
                phase = None
        if phase == initial_phase and phase in ('prepared', 'installed', 'restored'):
            verify()
            path.unlink()
        raise
    else:
        verify()
        path.unlink()


def load(state, home):
    state, home = checked_path(state, directory=True), checked_path(home, directory=True)
    plan = decode(read(state / 'plan.json'))
    require(isinstance(plan, dict) and plan.get('version') == 1
        and plan.get('home') == str(home) and plan.get('state') == str(state), 'plan_identity_changed')
    manifest = validate_manifest(decode(read(state / 'manifest.json')))
    provider_id = provider_name(manifest['profile'])
    require(plan.get('provider') == provider_id and plan.get('profile') == manifest['profile']
        and plan.get('manifest_sha256') == digest(read(state / 'manifest.json')), 'plan_changed')
    require(set(plan.get('files', {})) == {'profile', 'catalog'}, 'plan_changed')
    files = {}
    for kind, suffix in (('profile', '.config.toml'), ('catalog', '.catalog.json')):
        record = plan['files'][kind]
        require(isinstance(record, dict) and set(record) == {'existed', 'original_sha256', 'prepared_sha256'}
            and type(record['existed']) is bool, 'plan_changed')
        original, prepared = read(state / ('original.' + kind)), read(state / ('prepared.' + kind))
        require(digest(original) == record['original_sha256']
            and digest(prepared) == record['prepared_sha256']
            and (record['existed'] or original == b''), 'preparation_changed')
        # Recovery validates retained exact bytes, independent of later source.
        files[kind] = {'path': home / (manifest['profile'] + suffix),
            'original': (original, record['existed']), 'prepared': (prepared, True)}
    journal = decode(read(state / 'journal.json'))
    require(isinstance(journal, dict) and journal.get('phase') in (
        'prepared', 'installing', 'installed', 'restoring', 'restored'), 'journal_invalid')
    return plan, manifest, files, journal


def report(phase, plan=None, manifest=None, **extra):
    return {'status': phase, 'global_config_changed': False, 'inference_requests': 0,
        'desktop_verified': False, 'capabilities_verified': False,
        **({'profile': plan['profile'], 'provider': plan['provider'],
            'model_id': manifest['model']['id'], 'kind': manifest['kind'],
            'codex_home': plan['home'],
            'original_files': {kind: plan['files'][kind]['existed']
                for kind in ('profile', 'catalog')}} if plan and manifest else {}), **extra}


def status(state, home):
    state = checked_path(state, directory=True, exists=False)
    checked_path(home, directory=True)
    if not state.exists(): return report('absent')
    plan, manifest, files, journal = load(state, home)
    phase = journal['phase']
    if phase in ('installing', 'restoring'):
        return report('uncertain', plan, manifest, next_action='review')
    expected = 'prepared' if phase == 'installed' else 'original'
    if any(snapshot(row['path']) != row[expected] for row in files.values()):
        return report('changed', plan, manifest, next_action='review')
    if phase in ('prepared', 'installed'):
        try:
            check_base_provider(home, plan['provider'])
        except NativeModelsError as error:
            if str(error) != 'native_models_base_provider_collision':
                raise
            return report('changed', plan, manifest, reason='base_provider_collision', next_action='review')
    return report(phase, plan, manifest)


def prepare(state, home, manifest_path):
    state, home = checked_path(state, directory=True, exists=False), checked_path(home, directory=True)
    manifest = validate_manifest(decode(read(manifest_path)))
    generated, provider = artifacts(manifest, home)
    if state.exists():
        plan, previous, _, journal = load(state, home)
        require(previous == manifest and journal['phase'] in ('prepared', 'installed'), 'existing_plan_conflict')
        current = status(state, home)
        require(current['status'] in ('prepared', 'installed'), 'target_changed')
        return {**current, 'reused': True}
    checked_path(state.parent, directory=True)
    check_base_provider(home, provider)
    originals = {kind: snapshot(home / (manifest['profile'] + suffix))
        for kind, suffix in (('profile', '.config.toml'), ('catalog', '.catalog.json'))}
    # New registrations never claim an existing file, even if its model name
    # matches. It can carry independent approval/sandbox or provider settings.
    require(all(not existed for _, existed in originals.values()), 'unowned_target_exists')
    private_directory(state)
    with lock(state):
        plan = {'version': 1, 'home': str(home), 'state': str(state), 'profile': manifest['profile'],
            'provider': provider, 'source_sha256': digest(read(Path(__file__).resolve())),
            'manifest_sha256': digest(json_bytes(manifest)), 'files': {}}
        for kind, (original, existed) in originals.items():
            plan['files'][kind] = {'existed': existed, 'original_sha256': digest(original),
                'prepared_sha256': digest(generated[kind])}
            for prefix, raw in (('original', original), ('prepared', generated[kind])):
                with (state / (prefix + '.' + kind)).open('xb') as stream: stream.write(raw)
        write_record(state / 'manifest.json', manifest)
        write_record(state / 'plan.json', plan)
        write_record(state / 'journal.json', {'phase': 'prepared'})
    return report('prepared', plan, manifest, reused=False)


def install(state, home):
    with lock(state):
        plan, manifest, files, journal = load(state, home)
        require(journal['phase'] in ('prepared', 'installed'), 'uncertain_transaction')
        with target_lock(Path(state), Path(home), plan,
                initial_phase=journal['phase']) as (verify, mutation):
            plan, manifest, files, journal = load(state, home)
            check_base_provider(home, plan['provider'])
            if journal['phase'] == 'installed':
                current = status(state, home)
                require(current['status'] == 'installed', 'target_changed')
                return {**current, 'reused': True}
            require(journal['phase'] == 'prepared', 'uncertain_transaction')
            generated, _ = artifacts(manifest, Path(home))
            require(plan['source_sha256'] == digest(read(Path(__file__).resolve()))
                and all(row['prepared'][0] == generated[kind] for kind, row in files.items()), 'source_changed')
            require(all(snapshot(row['path']) == row['original'] for row in files.values()), 'target_changed')
            verify(); mutation['started'] = True
            write_record(Path(state) / 'journal.json', {'phase': 'installing'})
            # Publish the complete bound catalog before making the selectable profile visible.
            for kind in ('catalog', 'profile'):
                row = files[kind]
                verify()
                check_base_provider(home, plan['provider'])
                replace_file(row['path'], row['original'], row['prepared'][0])
            verify()
            write_record(Path(state) / 'journal.json', {'phase': 'installed'})
    return report('installed', plan, manifest, reused=False)


def restore(state, home):
    with lock(state):
        plan, manifest, files, journal = load(state, home)
        require(journal['phase'] in ('prepared', 'installed', 'installing', 'restored'), 'uncertain_transaction')
        with target_lock(Path(state), Path(home), plan,
                initial_phase=journal['phase']) as (verify, mutation):
            plan, manifest, files, journal = load(state, home)
            if journal['phase'] == 'restored':
                require(status(state, home)['status'] == 'restored', 'target_changed')
                return report('restored', plan, manifest, reused=True)
            require(journal['phase'] in ('prepared', 'installed', 'installing'), 'uncertain_transaction')
            current = {kind: snapshot(row['path']) for kind, row in files.items()}
            for kind, row in files.items():
                allowed = (row['original'],) if journal['phase'] == 'prepared' else (
                    row['prepared'],) if journal['phase'] == 'installed' else (row['original'], row['prepared'])
                require(current[kind] in allowed, 'target_changed')
            verify(); mutation['started'] = True
            write_record(Path(state) / 'journal.json', {'phase': 'restoring'})
            # Detach the profile before removing its catalog; never undo later edits.
            for kind in ('profile', 'catalog'):
                row = files[kind]
                verify()
                if current[kind] != row['original']:
                    replace_file(row['path'], current[kind], row['original'][0] if row['original'][1] else None)
            verify()
            write_record(Path(state) / 'journal.json', {'phase': 'restored'})
    return report('restored', plan, manifest, reused=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'install', 'status', 'restore'), nargs='?', default='status')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        require((args.action == 'prepare') == (args.manifest is not None), 'manifest_argument_invalid')
        action = globals()[args.action]
        result = action(args.state, args.home, args.manifest) if args.action == 'prepare' else action(args.state, args.home)
        print(json.dumps(result, ensure_ascii=True))
        return 2 if result['status'] in ('changed', 'uncertain') else 0
    except NativeModelsError as error:
        print(json.dumps({'status': 'unavailable', 'code': str(error),
            'inference_requests': 0, 'global_config_changed': False}))
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        # Do not serialize configuration, endpoint, key names or exception text.
        print(json.dumps({'status': 'unavailable', 'code': 'native_models_operation_rejected',
            'inference_requests': 0, 'global_config_changed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
