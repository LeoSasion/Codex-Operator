"""Reversible preparation for an explicitly selected, independent Desktop trial.

Only an additional provider is registered. No task is created or sent,
no default/catalog/permission is replaced, and no service is started or retried.
The private trial pins one service generation. Explicit rebind retains the
provider name when that saved service is restarted; it never replays a turn.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
import tomllib

from operator_core.model_registry import ModelRegistry
from operator_web_service import (checked_path, digest, file_digest, load_profile,
    operation_lock, private_directory, read_bytes, read_json, resolve_route, resolve_routes,
    route_preview, service, current_record, session_snapshot, state_path)
from operator_core.web_mcp_transport import require


LIMIT = 1024 * 1024
BEGIN = b'# BEGIN OPERATOR WEB DESKTOP TRIAL\n'
END = b'# END OPERATOR WEB DESKTOP TRIAL\n'
TRIAL = re.compile(r'trial-[a-f0-9]{32}')


def parse(raw):
    return tomllib.loads(raw.decode('utf-8-sig'))


def config_bytes(home):
    home = checked_path(home, directory=True)
    target = checked_path(home / 'config.toml', exists=False)
    require(not target.exists() or (target.is_file() and target.stat().st_nlink == 1),
        'web_desktop_regular_config_required')
    raw = read_bytes(target, LIMIT) if target.exists() else b''
    parse(raw)
    return target, raw, target.exists()


def check_binding_files(profile, expected):
    require(digest(read_bytes(profile / 'profile.json')) == expected['profile_sha256'],
        'web_desktop_profile_changed')
    record = current_record(profile)
    require(record is not None, 'web_desktop_session_changed')
    require(session_snapshot(state_path(profile, record), record)[1] == expected['session_sha256'],
        'web_desktop_session_changed')


def catalogue(route):
    routes = (route,) if hasattr(route, 'slug') else tuple(route)
    template = read_json(Path(__file__).with_name('operator_core') / 'beeper_model_catalog.json')
    registry = ModelRegistry({'version': 2, 'models': []}, template)
    for route in routes:
        registry = registry.with_web_route(route)
    native = {'models': [{**template['models'][0], 'slug': 'synthetic-native'}]}
    rows = [row for row in registry.merge(native)['models'] if row['slug'] in {route.slug for route in routes}]
    for row in rows:
        for level in row['supported_reasoning_levels']:
            level['description'] = {'none': '即时', 'medium': '中', 'high': '高', 'xhigh': '极高',
                'max': 'Pro（网页固定模式）'}[level['effort']]
    return {'models': rows}


def addition(route, provider):
    # This is a local, random service token, not a ChatGPT account credential or
    # fixed-tunnel key. It stays in private files and is never returned to stdout.
    sections = {
        'model_providers.' + provider: {
            'name': 'ChatGPT Web · 独立原生验收', 'base_url': route.api_base,
            'experimental_bearer_token': route.key(), 'wire_api': 'responses',
            'requires_openai_auth': False, 'request_max_retries': 0,
            'stream_max_retries': 0, 'supports_websockets': False}}
    lines = []
    for section, values in sections.items():
        lines.append('[' + section + ']')
        lines.extend(key + ' = ' + json.dumps(value, ensure_ascii=True) for key, value in values.items())
    return b'\n' + BEGIN + ('\n'.join(lines) + '\n').encode() + END


def check_scope(before, after, fragment):
    original, candidate, added = parse(before), parse(after), parse(fragment)
    require(set(added) == {'model_providers'}, 'web_desktop_scope_invalid')
    expected = deepcopy(original)
    for group in added:
        expected.setdefault(group, {})
        require(isinstance(expected[group], dict)
            and not set(expected[group]) & set(added[group]), 'web_desktop_name_collision')
        expected[group].update(added[group])
    require(candidate == expected, 'web_desktop_scope_invalid')


def result(status, **extra):
    summaries = {
        'absent': '尚未准备独立原生验收；现有任务和默认模型保持原样。',
        'prepared': '独立原生验收配置已准备好；尚未登记到 Codex，也未创建任务或发送请求。',
        'connected': '独立 Web 提供方已登记，官方默认模型和现有任务保持原样；真实 Desktop 验收仍待完成。',
        'stale': '独立 Web 提供方仍指向旧后台实例；可显式重新绑定当前已就绪的后台。',
        'disconnected': '独立 Web 验收登记已撤回，其他配置保持原样；任务历史和后台服务保留。',
        'changed': '独立 Web 验收登记或准备文件已变化，请核对现有记录；未覆盖或重新登记。',
        'checked': '已检查原生进程的模型目录和提供方；此结果不代表运行中的 Desktop 菜单已接入。',
        'unavailable': '原生验收准备当前不可用，请核对已保存的后台和准备记录；未重试、创建任务或发送请求。'}
    return {'status': status, 'summary': summaries[status], 'desktop_acceptance': False, **extra}


def load_trial(profile, home):
    profile = checked_path(profile, directory=True)
    root = profile / 'desktop'
    if not (root / 'current.json').exists():
        return None
    pointer = read_json(root / 'current.json')
    require(set(pointer) == {'trial'} and isinstance(pointer['trial'], str)
        and TRIAL.fullmatch(pointer['trial']), 'web_desktop_pointer_invalid')
    folder = checked_path(root / pointer['trial'], directory=True)
    plan = read_json(folder / 'plan.json')
    require(plan.get('version') == 1 and plan.get('home') == str(checked_path(home, directory=True))
        and plan.get('profile') == str(profile), 'web_desktop_plan_invalid')
    require(set(plan.get('files', {})) == {'before.toml', 'addition.toml', 'catalog.json'},
        'web_desktop_plan_invalid')
    files = {name: read_bytes(folder / name, LIMIT) for name in plan['files']}
    require(all(digest(raw) == plan['files'][name] for name, raw in files.items()),
        'web_desktop_preparation_changed')
    fragment = files['addition.toml']
    require(fragment.startswith(b'\n' + BEGIN) and fragment.endswith(END)
        and fragment.count(BEGIN) == fragment.count(END) == 1, 'web_desktop_plan_invalid')
    check_scope(files['before.toml'], files['before.toml'] + fragment, fragment)
    journal = read_json(folder / 'journal.json')
    require(journal.get('phase') in ('prepared', 'connecting', 'connected', 'disconnecting', 'disconnected'),
        'web_desktop_journal_invalid')
    return folder, plan, files, journal


def prepare(profile, home):
    profile, _ = load_profile(profile)
    target, before, existed = config_bytes(home)
    existing = load_trial(profile, target.parent)
    if existing is not None and existing[3]['phase'] != 'disconnected':
        report = status(profile, target.parent)
        require(report['status'] in ('prepared', 'connected'), 'web_desktop_existing_changed')
        resolve_routes(profile, existing[1]['binding'])
        return {**report, 'reused': True}
    expected = route_preview(profile)
    routes = resolve_routes(profile, expected)
    route = routes[0]
    require(BEGIN not in before and END not in before, 'web_desktop_unowned_block')
    with operation_lock(profile):
        require(config_bytes(target.parent)[1:] == (before, existed), 'web_desktop_config_changed')
        # Recheck after taking the lifecycle lock without another health read.
        check_binding_files(profile, expected)
        root = profile / 'desktop'
        if not root.exists(): private_directory(root)
        checked_path(root, directory=True)
        require(load_trial(profile, target.parent) == existing, 'web_desktop_concurrent_preparation')
        folder = root / ('trial-' + secrets.token_hex(16))
        private_directory(folder)
        provider = 'operator_web_' + folder.name[6:22]
        fragment = addition(route, provider)
        require(len(before) + len(fragment) <= LIMIT, 'web_desktop_config_bound')
        check_scope(before, before + fragment, fragment)
        files = {'before.toml': before, 'addition.toml': fragment,
            'catalog.json': json.dumps(catalogue(routes), ensure_ascii=False).encode('utf-8')}
        for name, raw in files.items():
            with (folder / name).open('xb') as handle: handle.write(raw)
        plan = {'version': 1, 'home': str(target.parent), 'profile': str(profile),
            'existed': existed, 'binding': expected, 'provider': provider,
            'source_sha256': file_digest(Path(__file__).resolve()),
            'files': {name: digest(raw) for name, raw in files.items()}}
        service.write_json(folder / 'plan.json', plan)
        service.write_json(folder / 'journal.json', {'phase': 'prepared'})
        service.write_json(root / 'current.json', {'trial': folder.name})
    return result('prepared', reused=False, provider=provider)


def replace_config(target, expected, replacement, *, existed):
    require(len(replacement) <= LIMIT, 'web_desktop_config_bound')
    # Only the exact reviewed snapshot may change. Preserve an original copy in
    # the private trial before reaching this function; never log config bytes.
    checked_path(target, exists=False)
    require(target.exists() == existed and (read_bytes(target, LIMIT) if existed else b'') == expected,
        'web_desktop_config_changed')
    descriptor, name = tempfile.mkstemp(prefix='.operator-web-', suffix='.pending', dir=target.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if existed: pending.chmod(target.stat().st_mode & 0o777)
        checked_path(target, exists=False)
        require(target.exists() == existed and (read_bytes(target, LIMIT) if existed else b'') == expected,
            'web_desktop_config_changed')
        os.replace(pending, target)
    finally:
        if pending.exists(): pending.unlink()


def connect(profile, home):
    trial = load_trial(profile, home)
    require(trial is not None, 'web_desktop_prepare_required')
    folder, plan, files, journal = trial
    routes = resolve_routes(profile, plan['binding'])  # idle, exact process/session; zero inference
    route = routes[0]
    require(addition(route, plan['provider']) == files['addition.toml']
        and json.loads(files['catalog.json']) == catalogue(routes), 'web_desktop_preparation_changed')
    with operation_lock(profile):
        require(load_trial(profile, home) == trial, 'web_desktop_preparation_changed')
        check_binding_files(profile, plan['binding'])
        target, current, existed = config_bytes(home)
        if journal['phase'] == 'connected':
            require(owned_fragment(current, files['addition.toml']), 'web_desktop_config_changed')
            return result('connected', reused=True, provider=plan['provider'])
        require(plan['source_sha256'] == file_digest(Path(__file__).resolve()), 'web_desktop_source_changed')
        require(journal['phase'] == 'prepared' and existed == plan['existed']
            and current == files['before.toml'], 'web_desktop_config_changed')
        service.write_json(folder / 'journal.json', {'phase': 'connecting'})
        replace_config(target, current, current + files['addition.toml'], existed=existed)
        service.write_json(folder / 'journal.json', {'phase': 'connected'})
    return result('connected', reused=False, provider=plan['provider'])


def owned_fragment(current, fragment):
    if current.count(BEGIN) != 1 or current.count(END) != 1 or current.count(fragment) != 1:
        return False
    remaining = current.replace(fragment, b'', 1)
    check_scope(remaining, current, fragment)
    return True


def disconnect(profile, home):
    # Recovery needs the recorded bytes, never a live browser, source revision,
    # current token, new provider binding, or automatic task replay.
    with operation_lock(profile):
        trial = load_trial(profile, home)
        require(trial is not None, 'web_desktop_prepare_required')
        folder, plan, files, journal = trial
        target, current, existed = config_bytes(home)
        if journal['phase'] == 'disconnected':
            require(BEGIN not in current and END not in current, 'web_desktop_config_changed')
            return result('disconnected', reused=True)
        fragment = files['addition.toml']
        if journal['phase'] == 'disconnecting' and digest(current) == journal.get('remaining_sha256'):
            # A prior atomic removal completed but its final journal write did
            # not. Recognize only those exact post-removal bytes; do not replay.
            if journal.get('remove_empty') is True and current == b'' and existed:
                checked_path(target)
                require(read_bytes(target, LIMIT) == b'', 'web_desktop_config_changed')
                target.unlink()
            service.write_json(folder / 'journal.json', {'phase': 'disconnected'})
            return result('disconnected', reused=True)
        if journal['phase'] == 'prepared' or (journal['phase'] == 'connecting' and current == files['before.toml']):
            require(BEGIN not in current and END not in current, 'web_desktop_config_changed')
        else:
            require(owned_fragment(current, fragment), 'web_desktop_config_changed')
            remaining = current.replace(fragment, b'', 1)
            # Preserve every unrelated byte, including edits after registration.
            backup = folder / ('before-disconnect-' + secrets.token_hex(16) + '.toml')
            with backup.open('xb') as handle: handle.write(current)
            service.write_json(folder / 'journal.json', {'phase': 'disconnecting',
                'remaining_sha256': digest(remaining), 'remove_empty': not plan['existed'] and remaining == b''})
            replace_config(target, current, remaining, existed=existed)
            if not plan['existed'] and remaining == b'':
                checked_path(target)
                require(read_bytes(target, LIMIT) == b'', 'web_desktop_config_changed')
                target.unlink()
        service.write_json(folder / 'journal.json', {'phase': 'disconnected'})
    return result('disconnected', reused=False)


def status(profile, home):
    trial = load_trial(profile, home)
    if trial is None: return result('absent')
    folder, plan, files, journal = trial
    _, current, existed = config_bytes(home)
    phase = journal['phase']
    if phase == 'prepared' and (current != files['before.toml'] or existed != plan['existed']): phase = 'changed'
    if phase == 'connected' and not owned_fragment(current, files['addition.toml']): phase = 'changed'
    if phase == 'disconnected' and (BEGIN in current or END in current): phase = 'changed'
    if phase in ('connecting', 'disconnecting'): phase = 'changed'
    pending = folder.parent / 'rebind.json'
    if pending.exists():
        transaction = read_json(pending)
        require(transaction.get('phase') in ('prepared', 'completed')
            and isinstance(transaction.get('from_trial'), str)
            and isinstance(transaction.get('to_trial'), str), 'web_desktop_rebind_record_invalid')
        if transaction['phase'] != 'completed': phase = 'changed'
    if phase == 'connected':
        try:
            record = current_record(profile)
            current_binding = (record is not None
                and digest(read_bytes(profile / 'profile.json')) == plan['binding']['profile_sha256']
                and session_snapshot(state_path(profile, record), record)[1] == plan['binding']['session_sha256'])
        except (OSError, ValueError, KeyError, TypeError):
            current_binding = None
        if current_binding is False:
            return {**result('stale', provider=plan['provider']),
                'reason': 'service_generation_changed', 'next_action': 'desktop-rebind'}
        if current_binding is None: phase = 'changed'
    return result(phase, provider=plan['provider'])


def rebind(profile, home):
    """Explicitly replace only this owned provider's checked local service route.

    Preserve the exact provider ID so a native task keeps its binding after the
    Desktop process reloads configuration. A failed transaction is review-only.
    """
    trial = load_trial(profile, home)
    require(trial is not None, 'web_desktop_prepare_required')
    old_folder, old_plan, old_files, old_journal = trial
    require(old_journal['phase'] == 'connected', 'web_desktop_connected_required')
    pending = old_folder.parent / 'rebind.json'
    if pending.exists():
        require(read_json(pending).get('phase') == 'completed', 'web_desktop_rebind_uncertain')
    require(isinstance(old_plan.get('provider'), str)
        and re.fullmatch(r'operator_web_[a-f0-9]{16}', old_plan['provider']),
        'web_desktop_provider_invalid')
    target, before, existed = config_bytes(home)
    require(existed and owned_fragment(before, old_files['addition.toml']),
        'web_desktop_config_changed')
    expected = route_preview(profile)
    routes = resolve_routes(profile, expected)
    fragment = addition(routes[0], old_plan['provider'])
    if expected == old_plan['binding'] and fragment == old_files['addition.toml']:
        return result('connected', reused=True, provider=old_plan['provider'])
    require(expected != old_plan['binding'], 'web_desktop_binding_changed')
    remaining = before.replace(old_files['addition.toml'], b'', 1)
    after = before.replace(old_files['addition.toml'], fragment, 1)
    require(len(after) <= LIMIT, 'web_desktop_config_bound')
    check_scope(remaining, after, fragment)
    with operation_lock(profile):
        require(load_trial(profile, home) == trial and config_bytes(home) == (target, before, existed),
            'web_desktop_config_changed')
        check_binding_files(profile, expected)
        root = old_folder.parent
        transaction_path = root / 'rebind.json'
        if transaction_path.exists():
            previous = read_json(transaction_path)
            require(previous.get('phase') == 'completed', 'web_desktop_rebind_uncertain')
        folder = root / ('trial-' + secrets.token_hex(16))
        service.write_json(transaction_path, {'phase': 'prepared',
            'from_trial': old_folder.name, 'to_trial': folder.name,
            'before_sha256': digest(before), 'after_sha256': digest(after)})
        private_directory(folder)
        files = {'before.toml': remaining, 'addition.toml': fragment,
            'catalog.json': json.dumps(catalogue(routes), ensure_ascii=False).encode('utf-8')}
        for name, raw in {**files, 'before-rebind.toml': before}.items():
            with (folder / name).open('xb') as handle: handle.write(raw)
        plan = {'version': 1, 'home': str(target.parent), 'profile': str(profile),
            'existed': old_plan['existed'], 'binding': expected,
            'provider': old_plan['provider'], 'rebind_from': old_folder.name,
            'before_rebind_sha256': digest(before),
            'source_sha256': file_digest(Path(__file__).resolve()),
            'files': {name: digest(raw) for name, raw in files.items()}}
        service.write_json(folder / 'plan.json', plan)
        service.write_json(folder / 'journal.json', {'phase': 'rebinding'})
        replace_config(target, before, after, existed=existed)
        service.write_json(folder / 'journal.json', {'phase': 'connected'})
        service.write_json(root / 'current.json', {'trial': folder.name})
        service.write_json(transaction_path, {'phase': 'completed',
            'from_trial': old_folder.name, 'to_trial': folder.name,
            'before_sha256': digest(before), 'after_sha256': digest(after)})
    return result('connected', reused=False, provider=old_plan['provider'],
        binding_updated=True, live_desktop_adoption_unverified=True)


def native_models(home):
    """Read one fresh native process, never load/resume a task or refresh Desktop.

    The stdio client inherits CODEX_HOME. Refuse a different home rather than
    silently assessing the user's real configuration for a private trial.
    """
    from operator_core.app_server import AppServerSession
    from operator_core.beeper_relay import discover_codex_executable
    inherited = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    require(checked_path(home, directory=True) == checked_path(inherited, directory=True),
        'web_desktop_check_home_mismatch')
    executable = discover_codex_executable()
    executable_hash = file_digest(executable)
    with AppServerSession(executable, 15) as client:
        client.deadline = time.monotonic() + 15
        configuration = client.request('config/read', {'includeLayers': False})
        rows, cursor, cursors = [], None, set()
        for _ in range(4):
            page = client.request('model/list', {'includeHidden': True, 'cursor': cursor, 'limit': 100})
            require(isinstance(page, dict) and isinstance(page.get('data'), list)
                and len(page['data']) <= 100, 'web_desktop_invalid_model_page')
            rows.extend(page['data'])
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            require(isinstance(cursor, str) and 0 < len(cursor) <= 4096 and cursor not in cursors,
                'web_desktop_invalid_model_cursor')
            cursors.add(cursor)
        else:
            raise ValueError('web_desktop_model_page_limit')
    require(file_digest(executable) == executable_hash, 'web_desktop_cli_changed')
    require(isinstance(configuration, dict) and isinstance(configuration.get('config'), dict),
        'web_desktop_invalid_native_config')
    return configuration['config'], rows, executable_hash


def assess_models(configuration, rows, provider, slug):
    """Report independent prerequisites, never infer a live menu or a route.

    A model name is not a provider binding. A custom catalog may affect menu
    filtering but does not give a model its own provider. In particular this
    diagnostic never recommends installing the trial's Web-only catalog as the
    user's global catalog, which would omit their native models.
    """
    require(isinstance(configuration, dict) and isinstance(rows, list),
        'web_desktop_invalid_native_config')
    seen, web_row = set(), None
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('model'), str)
            and row['model'] and row['model'] not in seen
            and type(row.get('hidden')) is bool, 'web_desktop_invalid_model_row')
        seen.add(row['model'])
        if row['model'] == slug:
            web_row = row
    providers = configuration.get('model_providers', {})
    require(isinstance(providers, dict), 'web_desktop_invalid_native_config')
    configured_catalog = configuration.get('model_catalog_json')
    default_provider = configuration.get('model_provider') or 'openai'
    require(isinstance(default_provider, str) and
        (configured_catalog is None or isinstance(configured_catalog, str)),
        'web_desktop_invalid_native_config')
    checks = {
        'provider_registered': provider in providers,
        'web_model_listed': web_row is not None,
        'web_model_hidden': web_row['hidden'] if web_row else None,
        'startup_catalog_configured': bool(configured_catalog and configured_catalog.strip()),
        'default_provider_is_trial': default_provider == provider,
        'default_provider_is_native': default_provider == 'openai',
        'other_models_listed': sum(row['model'] != slug and not row['hidden'] for row in rows),
    }
    missing = []
    if not checks['provider_registered']: missing.append('provider_not_loaded')
    if web_row is None: missing.append('web_model_not_listed')
    elif web_row['hidden']: missing.append('web_model_hidden')
    # The current Desktop has an additional availability filter for native
    # account catalogs. These flags explain the inputs, not its live decision.
    if not checks['startup_catalog_configured'] and checks['default_provider_is_native']:
        missing.append('native_menu_filter_not_verified')
    if not checks['default_provider_is_trial']:
        missing.append('per_model_route_not_verified')
    elif checks['other_models_listed']:
        missing.append('mixed_catalog_route_not_verified')
    missing.append('live_desktop_menu_not_verified')
    return {**checks, 'missing_checks': missing, 'native_picker_acceptance': False,
        'live_desktop_checked': False, 'restart_alone_sufficient': False}


def check(profile, home):
    before = config_bytes(home)
    trial = load_trial(profile, home)
    if trial is None:
        return result('absent')
    folder, plan, files, journal = trial
    registration = status(profile, home)
    if registration['status'] != 'connected':
        return registration
    configuration, rows, executable_hash = native_models(home)
    report = assess_models(configuration, rows, plan['provider'], service.SLUG)
    require(config_bytes(home) == before and load_trial(profile, home) == trial,
        'web_desktop_check_snapshot_changed')
    return result('checked', observation='fresh_native_app_server',
        cli_sha256=executable_hash, configuration_changed=False, model_requests=0,
        **report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['desktop-prepare', 'desktop-connect', 'desktop-rebind', 'desktop-disconnect', 'desktop-status', 'desktop-check'])
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--codex-home', type=Path,
        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    args = parser.parse_args()
    try:
        report = globals()[args.action.removeprefix('desktop-')](args.profile, args.codex_home)
    except Exception:
        report = result('unavailable')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] not in ('changed', 'unavailable') else 1


if __name__ == '__main__':
    raise SystemExit(main())
