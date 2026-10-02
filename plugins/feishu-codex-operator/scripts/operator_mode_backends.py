"""Explicit stopped extension-backend updates; secrets stay in live Web memory."""
from copy import deepcopy
from pathlib import Path

from operator_core.model_registry import ModelRegistry

BACKEND_FILES = ('router/registry.json', 'home/models.json')


def snapshot(root, registry_path=None, web_profile=None):
    import operator_mode_entry as mode
    from operator_web_service import route_preview, resolve_routes, load_profile, read_json
    descriptor = mode.load(root, check_source=False)
    before = mode.decode(mode.read(root / 'router/registry.json'))
    selected = root / 'router/registry.json' if registry_path is None else mode.checked_path(registry_path)
    project = Path(descriptor['project'])
    mode.require(project / '.codex' in selected.parents, 'backend_registry_scope_invalid')
    registry, registry_sha = ModelRegistry.load_snapshot(selected)
    after = mode.decode(mode.read(selected))
    mode.require(after.get('version') == before.get('version') == 2
        and len(after['models']) == len(before['models']), 'backend_registration_identity_changed')
    for old, new in zip(before['models'], after['models']):
        # This maintenance operation changes an explicit protocol contract or
        # lowers its existing capacity. Additions/identity/credential changes
        # belong to the separate registration workflow.
        mode.require({k:v for k,v in old.items() if k not in ('responses', 'context_window')}
            == {k:v for k,v in new.items() if k not in ('responses', 'context_window')}
            and new['context_window'] <= old['context_window'], 'backend_registration_identity_changed')
    web = descriptor.get('web')
    if web_profile is not None:
        profile = mode.checked_path(web_profile, directory=True)
        mode.require(project / '.codex' in profile.parents, 'backend_web_profile_scope_invalid')
        _, configuration = load_profile(profile)
        settings = read_json(Path(configuration['settings']['path']))
        mode.require(settings.get('native_cancellation_mode') == 'app_server_metadata_v1'
            and settings.get('native_cancellation_home') == str(root / 'home'), 'backend_web_cancellation_home_mismatch')
        expected = route_preview(profile)
        routes = resolve_routes(profile, expected, require_bound_session=True)
        web = {'profile':str(profile), **expected, 'models':[r.slug for r in routes]}
        registry = registry.with_web_routes(routes)
    elif web is not None:
        profile = Path(web['profile'])
        expected = {k:web[k] for k in ('profile_sha256','session_sha256')}
        routes = resolve_routes(profile, expected, require_bound_session=True)
        mode.require([r.slug for r in routes] == web['models'], 'backend_web_catalog_changed')
        registry = registry.with_web_routes(routes)
    catalog = mode.json_bytes(registry.extension_catalog())
    mode.require(mode.file_hash(selected) == registry_sha, 'backend_registry_changed')
    return {'registry_file':str(selected), 'registry_sha256':registry_sha,
            'catalog_sha256':mode.digest(catalog), 'web':deepcopy(web)}, mode.read(selected), catalog


def candidate_descriptor(original, update):
    value = deepcopy(original)
    if update is not None:
        value.update(registry_sha256=update['registry_sha256'], catalog_sha256=update['catalog_sha256'])
        if update['web'] is not None:
            value['web'] = deepcopy(update['web'])
    return value


def validate_web(descriptor):
    import operator_mode_entry as mode
    value = descriptor.get('web')
    if value is None:
        return None
    mode.require(isinstance(value, dict) and set(value) == {'profile','profile_sha256','session_sha256','models'}
        and all(isinstance(value.get(k), str) and mode.re.fullmatch('[a-f0-9]{64}', value[k])
                for k in ('profile_sha256','session_sha256'))
        and isinstance(value['models'], list) and 0 < len(value['models']) <= 100
        and all(isinstance(s,str) and s.startswith('api/chatgpt-web/') and len(s) <= 160
                for s in value['models'])
        and len(set(value['models'])) == len(value['models']), 'web_binding_invalid')
    profile = mode.checked_path(Path(value['profile']), directory=True)
    mode.require(Path(descriptor['project']) / '.codex' in profile.parents, 'backend_web_profile_scope_invalid')
    return profile


def checked_web_binding(descriptor):
    import operator_mode_entry as mode
    from operator_web_service import route_preview, resolve_routes
    profile = validate_web(descriptor)
    if profile is None:
        return None
    expected = {k:descriptor['web'][k] for k in ('profile_sha256','session_sha256')}
    mode.require(route_preview(profile) == expected, 'web_generation_changed_review_required')
    routes = resolve_routes(profile, expected, require_bound_session=True)
    mode.require([r.slug for r in routes] == descriptor['web']['models'], 'backend_web_catalog_changed')
    registry = ModelRegistry.load(Path(descriptor['root']) / 'router/registry.json').with_web_routes(routes)
    mode.require(mode.digest(mode.json_bytes(registry.extension_catalog())) == descriptor['catalog_sha256'],
                 'backend_web_catalog_changed')
    return profile
