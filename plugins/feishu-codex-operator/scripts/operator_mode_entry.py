"""Prepare and launch a separate custom-model home; never switch the native home."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib

from operator_native_models import NativeModelsError, checked_path, decode, digest, json_bytes, read, lock, replace_file
from operator_core.model_registry import ModelRegistry, RouterError
from operator_core.web_browser_driver import private_directory
from operator_mode_onboarding import inspect_contract, initial_state, CONTRACT as ONBOARDING_CONTRACT
from operator_core import native_search


CONTRACT = 'operator_isolated_mode_entry_v1'
HOST_CONTRACT = 'operator_isolated_mode_host_v1'
PROVIDER = 'operator_extension'
SCRIPTS = Path(__file__).resolve().parent


class ModeEntryError(ValueError):
    pass


def failure_reason(error):
    if isinstance(error, (ModeEntryError, NativeModelsError, RouterError)) and re.fullmatch(
            r'[a-z][a-z0-9_]{1,127}', str(error)):
        return str(error)
    return 'mode_operation_failed'


def require(condition, reason):
    if not condition:
        raise ModeEntryError('mode_' + reason)


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    raw = value if isinstance(value, bytes) else json_bytes(value)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def file_hash(path, limit=536870912):
    checked_path(path)
    require(path.stat().st_size <= limit, 'file_bound')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def native_home():
    require(bool(os.environ.get('USERPROFILE')), 'native_home_unavailable')
    return checked_path(Path(os.environ['USERPROFILE']) / '.codex', directory=True)


def validate_scope(project, root, native):
    project = checked_path(project, directory=True)
    native = checked_path(native, directory=True)
    root = checked_path(root, directory=True, exists=False)
    require(root.parent == project / '.codex' / 'operator-mode-entry'
            and re.fullmatch('[a-f0-9]{32}', root.name), 'root_scope_invalid')
    require(root != native and native not in root.parents and root not in native.parents,
            'native_home_rejected')
    return project, root, native


def inspect_package():
    # Fixed read-only PowerShell program, with no interpolated arguments.
    command = r'''$ErrorActionPreference='Stop'
$packages=@(Get-AppxPackage -Name OpenAI.Codex)
if($packages.Count -ne 1){throw 'mode_package_ambiguous'}
$p=$packages[0]
[xml]$m=Get-Content -LiteralPath (Join-Path $p.InstallLocation 'AppxManifest.xml') -Raw
$apps=@($m.Package.Applications.Application|Where-Object {$_.Id -ceq 'App'})
if($m.Package.Identity.Name -cne 'OpenAI.Codex' -or $apps.Count -ne 1 -or $apps[0].Executable -cne 'app/ChatGPT.exe' -or $apps[0].EntryPoint -cne 'Windows.FullTrustApplication'){throw 'mode_package_changed'}
[ordered]@{full_name=$p.PackageFullName;family=$p.PackageFamilyName;version=$p.Version.ToString();executable=(Join-Path $p.InstallLocation 'app\ChatGPT.exe')}|ConvertTo-Json -Compress
'''
    pwsh = shutil.which('pwsh.exe')
    require(pwsh is not None, 'powershell_unavailable')
    result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    require(result.returncode == 0 and len(result.stdout) <= 8192, 'package_inspection_failed')
    package = decode(result.stdout)
    require(isinstance(package, dict) and set(package) == {'full_name', 'family', 'version', 'executable'}
        and re.fullmatch(r'OpenAI\.Codex_[0-9.]+_x64__[a-z0-9]+', package['full_name'])
        and re.fullmatch(r'OpenAI\.Codex_[a-z0-9]+', package['family']), 'package_invalid')
    package['executable_sha256'] = file_hash(Path(package['executable']))
    return package


def inspect_runtime(python):
    checked_path(python)
    result = subprocess.run([str(python), '-I', '-c',
        'import sys,aiohttp; assert sys.version_info >= (3,11); print("operator_router_runtime_ready")'],
        capture_output=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    require(result.returncode == 0 and result.stdout.strip() == b'operator_router_runtime_ready',
            'router_runtime_dependencies_missing')
    return {'path': str(python), 'sha256': file_hash(python)}


def source_bindings():
    names = {'operator_mode_entry.py', 'operator_mode_entry.ps1', 'operator_mode_host.cs',
             'operator_mode_picker.cs', 'operator_model_router.py', 'operator_native_models.py',
             'operator_web_service.py', 'operator_mode_onboarding.py', 'operator_mode_native.cs',
             'operator_mode_maintenance.py', 'operator_mode_pair_refresh.ps1', 'operator_mode_backends.py'}
    paths = [SCRIPTS / name for name in names]
    paths += [path for path in (SCRIPTS / 'operator_core').rglob('*')
              if path.is_file() and path.suffix in {'.py', '.json'}]
    return {path.relative_to(SCRIPTS).as_posix(): file_hash(path) for path in sorted(paths)}


def config_bytes(root, port, token, model, effort, *, search_policy=None):
    require(search_policy in (None, native_search.CONTRACT, 'unavailable'), 'search_policy_invalid')
    values = {'model': model, 'model_provider': PROVIDER, 'model_reasoning_effort': effort,
              'model_catalog_json': str(root / 'home' / 'models.json'), 'web_search': 'live'}
    if search_policy == 'unavailable':
        values['web_search'] = 'disabled'
    endpoint = {'name': 'Codex Operator Extension',
                'base_url': f'http://127.0.0.1:{port}/{token}/v1',
                'wire_api': 'responses', 'requires_openai_auth': False,
                'request_max_retries': 0, 'stream_max_retries': 0, 'supports_websockets': False}
    if search_policy == native_search.CONTRACT:
        endpoint['supports_standalone_web_search'] = True
    lines = ['# Codex-Operator isolated extension home. Native settings remain separate.']
    lines += [f'{key} = {json.dumps(value)}' for key, value in values.items()]
    lines += ['', '[model_providers.' + PROVIDER + ']']
    lines += [f'{key} = {json.dumps(value)}' for key, value in endpoint.items()]
    if search_policy == native_search.CONTRACT:
        lines += ['', '[features]', 'standalone_web_search = true']
    return ('\n'.join(lines) + '\n').encode('utf-8')


def compile_host(root):
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    # Windows servicing legitimately hard-links this system compiler. It is a
    # read-only build dependency, not an owned mutable state file.
    checked_path(compiler.parent, directory=True)
    require(compiler.is_file() and not compiler.is_symlink()
            and not getattr(compiler.lstat(), 'st_file_attributes', 0) & 0x400, 'compiler_invalid')
    outputs = {}
    for source, output, references in (
        ('operator_mode_host.cs', 'operator-mode-host.exe', ['System.Web.Extensions.dll', 'System.Windows.Forms.dll']),
        ('operator_mode_picker.cs', 'operator-mode-picker.exe', ['System.Windows.Forms.dll', 'System.Drawing.dll', 'System.Web.Extensions.dll']),
        ('operator_mode_native.cs', 'operator-mode-native.exe', []),
    ):
        target = root / output
        result = subprocess.run([str(compiler), '/nologo', '/target:winexe',
            *['/r:' + reference for reference in references], '/out:' + str(target), str(SCRIPTS / source)],
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        require(result.returncode == 0, 'compile_failed')
        outputs[output] = file_hash(target, 4194304)
    return outputs


def prepare(project, root, registry_path, port, default_model, *, credentials=None, runtime_python=None,
            package=None, native=None, compiler=compile_host, search_policy=None):
    native = native_home() if native is None else native
    project, root, native = validate_scope(project, root, native)
    if search_policy == native_search.CONTRACT:
        native_search.load_headers(native)  # Check availability without copying or refreshing sign-in.
    require(not root.exists(), 'existing_preparation_retained')
    require(type(port) is int and 1024 <= port <= 65535, 'port_invalid')
    parsed_native = tomllib.loads(read(native / 'config.toml').decode('utf-8-sig'))
    require(parsed_native.get('model_provider', 'openai') == 'openai'
        and not any(key in parsed_native for key in ('openai_base_url', 'model_catalog_json', 'profile')),
        'native_baseline_not_direct')
    registry, registry_sha = ModelRegistry.load_snapshot(checked_path(registry_path))
    require(default_model in registry.routes, 'default_model_unregistered')
    registry_raw = read(registry_path)
    require(digest(registry_raw) == registry_sha, 'registry_changed')
    package = inspect_package() if package is None else package
    python = inspect_runtime(Path(runtime_python or sys.executable).resolve())
    onboarding = inspect_contract(package)
    credential_binding = None
    if credentials is not None:
        credentials = checked_path(credentials)
        require(project / '.codex' in credentials.parents and credentials.suffix == '.clixml',
                'credential_file_scope_invalid')
        names = sorted({route.api_key_env for route in registry.routes.values() if route.api_key_env})
        require(names and all(re.fullmatch(r'[A-Z][A-Z0-9_]*_(?:API_KEY|API_TOKEN|AUTH_TOKEN)', name)
                              for name in names), 'credential_environment_invalid')
        credential_binding = {'path': str(credentials), 'sha256': file_hash(credentials, 1048576),
                              'environment_names': names, 'storage': 'windows_current_user_clixml'}
    bindings = source_bindings()
    before = digest(read(native / 'config.toml'))
    if not root.parent.exists():
        private_directory(root.parent)
    private_directory(root)
    try:
        write_new(root / 'preparing.json', {'contract': CONTRACT, 'started_utc': utc(),
            'native_config_sha256': before, 'registry_sha256': registry_sha})
        for directory in ('home', 'user-data', 'router', 'launches', 'router-launches', 'activations'):
            private_directory(root / directory)
        outputs = compiler(root)
        token = secrets.token_hex(32)
        write_new(root / 'router' / 'registry.json', registry_raw)
        write_new(root / 'router' / 'token', token.encode('ascii'))
        write_new(root / 'home' / 'models.json', registry.extension_catalog())
        configuration = config_bytes(root, port, token, default_model,
                                     registry.routes[default_model].reasoning_efforts[0], search_policy=search_policy)
        write_new(root / 'home' / 'config.toml', configuration)
        welcome = initial_state(onboarding)
        if welcome is not None:
            write_new(root / 'home' / '.codex-global-state.json', welcome)
        write_new(root / 'entry.ps1', read(SCRIPTS / 'operator_mode_entry.ps1'))
        descriptor = {'schema_version': 1, 'contract': CONTRACT, 'created_utc': utc(),
            'project': str(project), 'root': str(root), 'native_home': str(native),
            'package': package, 'python': python['path'], 'search_policy': search_policy,
            'python_sha256': python['sha256'], 'source_bindings': bindings,
            'compiled': outputs, 'entry_sha256': file_hash(root / 'entry.ps1'),
            'registry_sha256': registry_sha, 'catalog_sha256': file_hash(root / 'home' / 'models.json'),
            'initial_config_sha256': digest(configuration), 'port': port,
            'native_config_at_prepare': before, 'native_enabled': False,
            'window_app_id': 'CodexOperator.Extension.' + root.name,
            'initial_model': default_model, 'installed': False, 'onboarding': onboarding,
            'credentials': credential_binding}
        require(source_bindings() == bindings, 'source_changed_during_prepare')
        require(digest(read(native / 'config.toml')) == before, 'native_changed_during_prepare')
        write_new(root / 'entry.json', descriptor)
        return report(root, descriptor, phase='prepared', native_config_unchanged=True)
    except Exception as error:
        write_new(root / 'preparation-failed.json', {'reason': failure_reason(error), 'retained_utc': utc()})
        raise


def load(root, *, check_source=True):
    check_refreshes(root)
    descriptor = decode(read(root / 'entry.json'))
    require(isinstance(descriptor, dict) and descriptor.get('schema_version') == 1
        and descriptor.get('contract') == CONTRACT and descriptor.get('root') == str(root)
        and descriptor.get('native_enabled') is False, 'entry_invalid')
    validate_scope(Path(descriptor['project']), root, Path(descriptor['native_home']))
    if check_source:
        require(descriptor['source_bindings'] == source_bindings(), 'source_changed')
    for name, expected in descriptor['compiled'].items():
        require(name in {'operator-mode-host.exe', 'operator-mode-picker.exe', 'operator-mode-native.exe'}
            and file_hash(root / name, 4194304) == expected, 'compiled_changed')
    require(file_hash(root / 'entry.ps1') == descriptor['entry_sha256'], 'entry_script_changed')
    require(file_hash(Path(descriptor['python'])) == descriptor['python_sha256'], 'python_changed')
    require(file_hash(root / 'router' / 'registry.json') == descriptor['registry_sha256'], 'registry_changed')
    require(file_hash(root / 'home' / 'models.json') == descriptor['catalog_sha256'], 'catalog_changed')
    configuration = tomllib.loads(read(root / 'home' / 'config.toml').decode('utf-8-sig'))
    token = (root / 'router' / 'token').read_text('ascii')
    require(re.fullmatch('[a-f0-9]{64}', token), 'token_invalid')
    original = tomllib.loads(config_bytes(root, descriptor['port'], token, descriptor['initial_model'], 'low',
                                         search_policy=descriptor.get('search_policy')).decode())
    require(configuration.get('model_provider') == PROVIDER
        and configuration.get('model_catalog_json') == original['model_catalog_json']
        and configuration.get('model_providers', {}).get(PROVIDER) == original['model_providers'][PROVIDER]
        and not any(key in configuration for key in ('openai_base_url', 'profile')), 'route_settings_changed')
    if descriptor.get('search_policy') == native_search.CONTRACT:
        require(configuration.get('features', {}).get('standalone_web_search') is True,
                'search_settings_changed')
    registry = ModelRegistry.load(root / 'router' / 'registry.json')
    from operator_mode_backends import validate_web
    validate_web(descriptor)
    require(configuration.get('model') in set(registry.routes) | set(descriptor.get('web', {}).get('models', [])),
            'model_unregistered')
    credentials = descriptor.get('credentials')
    if credentials is not None:
        require(credentials.get('storage') == 'windows_current_user_clixml'
                and Path(descriptor['project']) / '.codex' in Path(credentials['path']).parents
                and file_hash(Path(credentials['path']), 1048576) == credentials['sha256']
                and credentials['environment_names'] == sorted({route.api_key_env
                    for route in registry.routes.values() if route.api_key_env}), 'credentials_changed')
    return descriptor


def check_refreshes(root):
    pairs = root / 'pair-refreshes'
    if pairs.exists():
        checked_path(pairs, directory=True)
        for attempt in pairs.iterdir():
            checked_path(attempt, directory=True)
            if (attempt / 'retired.json').exists():
                from operator_mode_maintenance import retired_pair_valid
                require(retired_pair_valid(attempt), 'pair_retirement_changed')
                continue
            require(re.fullmatch('[a-f0-9]{32}', attempt.name)
                    and not (attempt / 'failed.json').exists()
                    and (not (attempt / 'apply-intent.json').exists()
                         or (attempt / 'completed.json').is_file()), 'previous_pair_refresh_uncertain_no_retry')
    directory = root / 'refreshes'
    if not directory.exists():
        return
    checked_path(directory, directory=True)
    for attempt in directory.iterdir():
        checked_path(attempt, directory=True)
        require(re.fullmatch('[a-f0-9]{32}', attempt.name)
                and (attempt / 'completed.json').is_file()
                and not (attempt / 'failed.json').exists(), 'previous_refresh_uncertain_no_retry')


def search_configuration(raw):
    """Add reviewed search declarations, preserving every other original byte."""
    text = raw.decode('utf-8-sig')
    parsed = tomllib.loads(text)
    require(parsed.get('web_search') == 'live', 'search_mode_requires_review')
    require('supports_standalone_web_search' not in parsed['model_providers'][PROVIDER]
            and 'standalone_web_search' not in parsed.get('features', {}), 'search_declaration_conflict')
    newline = '\r\n' if '\r\n' in text else '\n'
    provider_header = '[model_providers.' + PROVIDER + ']'
    require(text.count(provider_header) == 1, 'search_provider_table_ambiguous')
    text = text.replace(provider_header, provider_header + newline + 'supports_standalone_web_search = true', 1)
    if 'features' in parsed:
        require(text.count('[features]') == 1, 'search_features_table_ambiguous')
        text = text.replace('[features]', '[features]' + newline + 'standalone_web_search = true', 1)
    else:
        text += newline + '[features]' + newline + 'standalone_web_search = true' + newline
    encoded = text.encode('utf-8')
    if raw.startswith(b'\xef\xbb\xbf'):
        encoded = b'\xef\xbb\xbf' + encoded
    after = tomllib.loads(encoded.decode('utf-8-sig'))
    del after['model_providers'][PROVIDER]['supports_standalone_web_search']
    del after['features']['standalone_web_search']
    if 'features' not in parsed:
        del after['features']
    require(after == parsed, 'search_configuration_changed')
    return encoded


def package_update_snapshot(previous, current):
    """Explicit upgrade of the same official Windows package, never a launch."""
    keys = {'full_name', 'family', 'version', 'executable', 'executable_sha256'}
    require(all(isinstance(p, dict) and set(p) == keys for p in (previous, current)),
            'package_update_identity_invalid')
    for package in (previous, current):
        require(all(isinstance(value, str) for value in package.values())
                and re.fullmatch(r'OpenAI\.Codex_[a-z0-9]+', package['family'])
                and re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', package['version'])
                and package['full_name'] == ('OpenAI.Codex_' + package['version'] + '_x64__'
                                             + package['family'].split('_', 1)[1])
                and re.fullmatch('[a-f0-9]{64}', package['executable_sha256']),
                'package_update_identity_invalid')
    require(previous['family'] == current['family']
            and tuple(map(int, current['version'].split('.'))) > tuple(map(int, previous['version'].split('.'))),
            'package_update_not_same_family_upgrade')
    return {'contract': 'operator_mode_official_package_update_v1', 'before': previous,
            'after': current, 'onboarding': {'contract': ONBOARDING_CONTRACT, 'supported': False, 'preferences': {}}}


def package_update_descriptor(original, update):
    candidate = decode(json_bytes(original))
    if update is not None:
        require(original['package'] == update['before'], 'package_update_baseline_changed')
        candidate.update(package=update['after'], onboarding=update['onboarding'])
    return candidate


def router_terminal(root, attempt):
    """A reviewed absence is distinct from a server-confirmed clean stop."""
    if (attempt / 'stopped.json').is_file():
        running = decode(read(attempt / 'running.json'))
        stopped = decode(read(attempt / 'stopped.json'))
        require(stopped.get('process') == running.get('process')
                and stopped.get('server_confirmed_request_free') is True
                and not process_matches(running.get('process')), 'router_stop_uncertain')
        return True
    if (attempt / 'absence-reviewed.json').exists():
        from operator_mode_maintenance import reviewed_router_absence
        return reviewed_router_absence(root, attempt)
    return False


def refresh_snapshot(root, *, enable_native_search=False, bound_pair=False, registry_path=None, web_profile=None,
                     package_update=False):
    """Read-only, stopped update boundary. Old source is retained, never replayed."""
    descriptor = load(root, check_source=False)
    installed = Path(descriptor['project']) / '.codex/operator-desktop-entry/desktop-entry.json'
    if installed.exists():
        installed_record = decode(read(installed))
        selected = (installed_record.get('mode') == 'isolated_mode'
                    and installed_record.get('startup_bundle') == root.relative_to(Path(descriptor['project'])).as_posix())
        require(bound_pair or not selected, 'installed_pair_requires_bound_upgrade')
        require(not bound_pair or selected, 'installed_pair_binding_required')
    else:
        require(not bound_pair, 'installed_pair_binding_required')
    require(active_desktop(root) is None, 'close_extension_before_refresh')
    current_package = inspect_package()
    package_change = None
    if package_update:
        require(bound_pair, 'package_update_requires_bound_pair')
        from operator_mode_maintenance import stopped_desktops, activation_hosts_absent, isolated_processes_absent
        stopped_desktops(root)
        activation_hosts_absent(root)
        isolated_processes_absent(root)
        package_change = package_update_snapshot(descriptor['package'], current_package)
    else:
        require(current_package == descriptor['package'], 'official_package_changed')
    attempt = router_attempt(root)
    if attempt is not None:
        require(router_terminal(root, attempt), 'stop_router_before_refresh')
    managed = {name: file_hash(root / name) for name in
               ('entry.json', 'entry.ps1', *sorted(descriptor['compiled']))}
    search_update = None
    if enable_native_search:
        require(descriptor.get('search_policy') is None, 'search_already_selected')
        native_search.load_headers(Path(descriptor['native_home']))
        replacement = search_configuration(read(root / 'home/config.toml'))
        managed['home/config.toml'] = file_hash(root / 'home/config.toml')
        search_update = {'policy': native_search.CONTRACT, 'sha256': digest(replacement)}
    for name in ('operator-mode-host.exe', 'operator-mode-picker.exe', 'operator-mode-native.exe'):
        require(name in managed or not (root / name).exists(), 'unowned_compiled_file')
        managed.setdefault(name, None)
    plan = {'contract': 'operator_mode_bound_pair_refresh_v1' if bound_pair else 'operator_mode_stopped_refresh_v1', 'root': str(root),
            'managed_files': managed, 'sources': source_bindings(),
            'search_update': search_update,
            'protected_files': {str(path): file_hash(path) for path in (
                Path(descriptor['native_home']) / 'config.toml', root / 'home/config.toml',
                root / 'home/models.json', root / 'router/registry.json', root / 'router/token')},
            'package': current_package, 'port': descriptor['port']}
    if package_change is not None:
        plan['package_update'] = package_change
        plan['protected_files'][current_package['executable']] = current_package['executable_sha256']
    if attempt is not None and (attempt / 'absence-reviewed.json').exists():
        for name in ('intent.json', 'running.json', 'absence-original-entry.json', 'absence-reviewed.json'):
            plan['protected_files'][str(attempt / name)] = file_hash(attempt / name)
    if registry_path is not None or web_profile is not None:
        require(bound_pair, 'backend_update_requires_bound_pair')
        from operator_mode_backends import snapshot, BACKEND_FILES
        update, _, _ = snapshot(root, registry_path, web_profile)
        plan['backend_update'] = update
        for name in BACKEND_FILES:
            plan['managed_files'][name] = file_hash(root / name)
            del plan['protected_files'][str(root / name)]
        plan['protected_files'][update['registry_file']] = update['registry_sha256']
        if update['web'] is not None:
            profile_file = Path(update['web']['profile']) / 'profile.json'
            plan['protected_files'][str(profile_file)] = update['web']['profile_sha256']
    return plan


def refresh_preview(root, *, enable_native_search=False):
    import operator_model_router as router
    with lock(root):
        plan = refresh_snapshot(root, enable_native_search=enable_native_search)
        with router.reserve_inactive_port(plan['port']):
            return {'contract': plan['contract'], 'phase': 'refresh_ready', 'root': str(root),
                    'preview_sha256': digest(json_bytes(plan)), 'native_config_writes': 0,
                    'model_requests_sent_by_controller': 0, 'desktop_launch': False}


def refresh(root, expected_preview_sha256, *, compiler=compile_host, enable_native_search=False):
    """Explicit replacement of owned launch files, preserving this same home."""
    import operator_model_router as router
    with lock(root):
        plan = refresh_snapshot(root, enable_native_search=enable_native_search)
        require(re.fullmatch('[a-f0-9]{64}', expected_preview_sha256 or '')
                and digest(json_bytes(plan)) == expected_preview_sha256, 'refresh_preview_changed')
        with router.reserve_inactive_port(plan['port']):
            parent = root / 'refreshes'
            if not parent.exists():
                private_directory(parent)
            attempt = parent / secrets.token_hex(16)
            private_directory(attempt)
            write_new(attempt / 'intent.json', plan)
            try:
                for name in ('originals', 'staged'):
                    private_directory(attempt / name)
                original = {}
                for name, expected in plan['managed_files'].items():
                    raw = read(root / name) if expected is not None else b''
                    require((digest(raw) if expected is not None else None) == expected,
                            'refresh_target_changed')
                    original[name] = (raw, expected is not None)
                    if expected is not None:
                        (attempt / 'originals' / name).parent.mkdir(parents=True, exist_ok=True)
                        write_new(attempt / 'originals' / name, raw)
                descriptor = decode(original['entry.json'][0])
                outputs = compiler(attempt / 'staged')
                require(set(outputs) == {'operator-mode-host.exe', 'operator-mode-picker.exe',
                                         'operator-mode-native.exe'}, 'refresh_build_incomplete')
                descriptor.update(source_bindings=plan['sources'], compiled=outputs,
                                  entry_sha256=file_hash(SCRIPTS / 'operator_mode_entry.ps1'))
                if plan['search_update'] is not None:
                    replacement = search_configuration(original['home/config.toml'][0])
                    require(digest(replacement) == plan['search_update']['sha256'], 'search_preview_changed')
                    (attempt / 'staged/home').mkdir()
                    write_new(attempt / 'staged/home/config.toml', replacement)
                    descriptor['search_policy'] = plan['search_update']['policy']
                write_new(attempt / 'staged/entry.ps1', read(SCRIPTS / 'operator_mode_entry.ps1'))
                write_new(attempt / 'staged/entry.json', descriptor)
                require(source_bindings() == plan['sources'], 'source_changed_during_refresh')
                require(inspect_package() == plan['package'], 'official_package_changed')
                require(active_desktop(root) is None, 'close_extension_before_refresh')
                for path, expected in plan['protected_files'].items():
                    require(file_hash(Path(path)) == expected, 'protected_file_changed_during_refresh')
                for name, expected in plan['managed_files'].items():
                    require((file_hash(root / name) if (root / name).exists() else None) == expected,
                            'refresh_target_changed')
                # Descriptor is last: an interrupted partial update cannot launch.
                for name in (*sorted(outputs), 'entry.ps1',
                             *(['home/config.toml'] if plan['search_update'] else []), 'entry.json'):
                    replacement = read(attempt / 'staged' / name)
                    replace_file(root / name, original[name], replacement)
                    require(read(root / name) == replacement, 'refresh_write_unconfirmed')
                write_new(attempt / 'completed.json', {'completed_utc': utc(),
                    'preview_sha256': expected_preview_sha256, 'entry_sha256': file_hash(root / 'entry.json')})
            except Exception as error:
                write_new(attempt / 'failed.json', {'reason': failure_reason(error),
                    'retained_utc': utc(), 'automatically_retried': False})
                raise
        return report(root, load(root), phase='refreshed', refresh=attempt.name,
                      home_preserved=True, desktop_launch=False)


def report(root, descriptor, *, phase, **extra):
    return {'contract': CONTRACT, 'phase': phase, 'root': str(root),
            'native_enabled': False, 'native_config_writes': 0, 'history_copies': 0,
            'login_copies': 0, 'model_requests_sent_by_controller': 0,
            'search_policy': descriptor.get('search_policy'),
            'desktop_acceptance': 'unverified', 'registered_models':
            len(ModelRegistry.load(root / 'router' / 'registry.json').routes), **extra}


def process_matches(record):
    from operator_web_service import process_identity
    return (isinstance(record, dict) and type(record.get('pid')) is int
            and process_identity(record['pid']) == record)


def active_desktop(root):
    for activation in (root / 'activations').iterdir():
        checked_path(activation, directory=True)
        if (activation / 'focus-reviewed.json').exists():
            from operator_mode_maintenance import reviewed_focus_failure
            require(reviewed_focus_failure(root, activation), 'previous_window_activation_uncertain')
            continue
        require(re.fullmatch('[a-f0-9]{32}', activation.name)
                and (activation / 'completed.json').exists()
                and not any((activation / name).exists() for name in ('failed.json', 'controller-failed.json')),
                'previous_window_activation_uncertain')
    active = []
    for attempt in sorted((root / 'launches').iterdir()):
        checked_path(attempt, directory=True)
        require(re.fullmatch('[a-f0-9]{32}', attempt.name), 'launch_record_invalid')
        if (attempt / 'startup-reviewed.json').exists():
            from operator_mode_maintenance import reviewed_startup_failure
            require(reviewed_startup_failure(root, attempt), 'previous_launch_running_or_uncertain')
            continue
        require(not any((attempt / name).exists() for name in ('host-failed.json', 'controller-failed.json')),
                'previous_launch_running_or_uncertain')
        if (attempt / 'desktop-exited.json').exists():
            exited = decode(read(attempt / 'desktop-exited.json'))
            started = decode(read(attempt / 'desktop-started.json'))
            require(exited.get('window_was_bound') is True and exited.get('pid') == started.get('pid')
                    and not process_matches(started.get('process')), 'previous_launch_running_or_uncertain')
            continue
        require((attempt / 'windows-bound.json').exists() and (attempt / 'dispatched.json').exists(),
                'previous_launch_running_or_uncertain')
        started = decode(read(attempt / 'desktop-started.json'))
        bound = decode(read(attempt / 'windows-bound.json'))
        require(process_matches(started.get('process')) and bound.get('pid') == started['process']['pid']
                and bound.get('native_config_unchanged') is True, 'previous_launch_running_or_uncertain')
        active.append((attempt, started))
    require(len(active) <= 1, 'multiple_desktops_rejected')
    return active[0] if active else None


def activate_desktop(root, descriptor, active):
    attempt, record = active
    require(read(root / 'host-plan.json') == read(attempt / 'host-plan.json'), 'active_plan_changed')
    # A hidden background Desktop needs the same package/profile activation to
    # reopen its window. Never send an ambiguous ordinary official activation.
    pwsh = shutil.which('pwsh.exe')
    require(pwsh is not None, 'powershell_unavailable')
    activation = root / 'activations' / secrets.token_hex(16)
    private_directory(activation)
    plan_sha = file_hash(root / 'host-plan.json')
    write_new(activation / 'intent.json', {'original_pid': record['process']['pid'],
        'attempt': attempt.name, 'plan_sha256': plan_sha, 'created_utc': utc()})
    try:
        result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            str(root / 'entry.ps1'), '-Action', 'package-activate', '-Root', str(root),
            '-PlanSha256', plan_sha, '-Attempt', attempt.name, '-Activation', activation.name], timeout=20,
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        require(result.returncode == 0, 'existing_window_activation_dispatch_failed')
        # Broker acceptance is not completion evidence.
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if (activation / 'failed.json').exists():
                value = decode(read(activation / 'failed.json'))
                code = value.get('reason')
                raise ModeEntryError(code if isinstance(code, str) and re.fullmatch('mode_[a-z_]+', code)
                                     else 'mode_existing_window_not_activated')
            if (activation / 'completed.json').exists():
                value = decode(read(activation / 'completed.json'))
                require(value.get('original_pid') == record['process']['pid']
                        and value.get('attempt') == attempt.name and value.get('new_desktop_instances') == 0,
                        'window_activation_identity_changed')
                break
            time.sleep(.1)
        else:
            raise ModeEntryError('mode_existing_window_activation_unconfirmed')
    except Exception as error:
        write_new(activation / 'controller-failed.json', {'reason': failure_reason(error), 'retained_utc': utc()})
        raise
    require(process_matches(record['process']), 'desktop_identity_changed')
    return report(root, descriptor, phase='opened_existing', attempt=attempt.name,
                  process_id=record['process']['pid'], new_desktop_instances=0,
                  window_handle=value.get('window_handle'), window_process=record['process'],
                  foreground_activated=value.get('foreground_activated', True))


def start_router(root, descriptor, *, check_web_service=True):
    import operator_model_router as router
    from operator_web_service import process_identity
    from operator_mode_backends import checked_web_binding, validate_web
    web_profile = validate_web(descriptor)
    current_attempt = router_attempt(root)
    terminal = current_attempt is not None and router_terminal(root, current_attempt)
    require(check_web_service or (current_attempt is not None and not terminal),
            'identity_check_requires_running_router')
    if current_attempt is not None and not terminal:
        require((current_attempt / 'running.json').exists()
                and not (current_attempt / 'stop-intent.json').exists(), 'router_launch_uncertain_no_retry')
        running = decode(read(current_attempt / 'running.json'))
        require(process_matches(running.get('process')), 'router_process_uncertain')
        if check_web_service and web_profile is not None:
            require(file_hash(web_profile / 'profile.json') == descriptor['web']['profile_sha256'],
                    'web_generation_changed_review_required')
        current = router.control(root / 'router', descriptor['port'])
        require(current.get('pid') == running['process']['pid']
            and current.get('service') == running['service']
            and current.get('diagnostics', {}).get('native_enabled') is False
            and current.get('diagnostics', {}).get('registry_sha256') == descriptor['registry_sha256'],
            'router_identity_changed')
        require(current.get('diagnostics', {}).get('native_search_identity') == native_search.identity(
            Path(descriptor['native_home']) if descriptor.get('search_policy') == native_search.CONTRACT else None),
            'router_search_identity_changed')
        require(current.get('diagnostics', {}).get('web_profile_identity') == router.web_profile_identity(web_profile),
                'router_web_profile_changed')
        if web_profile is not None:
            diagnostics = current['diagnostics']
            require(diagnostics.get('web_route_bound') is True and all(
                diagnostics.get('web_route_' + key) == descriptor['web'][key]
                for key in ('profile_sha256','session_sha256')), 'router_web_generation_changed')
        return current
    if current_attempt is not None:
        require(router_terminal(root, current_attempt), 'router_stop_uncertain')
    require(importlib.util.find_spec('aiohttp') is not None, 'router_runtime_dependencies_missing')
    if web_profile is not None:
        checked_web_binding(descriptor)  # New publication requires this exact idle live generation.
    for route in ModelRegistry.load(root / 'router' / 'registry.json').routes.values():
        require(not route.api_key_env or bool(os.environ.get(route.api_key_env)),
                'credential_environment_unavailable')
    with router.reserve_inactive_port(descriptor['port']):
        attempt = root / 'router-launches' / secrets.token_hex(16)
        private_directory(attempt)
        write_new(attempt / 'intent.json', {'started_utc': utc(), 'native_enabled': False})
    current = router.start(root / 'router', descriptor['port'], require_fresh=True, native_enabled=False,
        **({'web_profile': web_profile} if web_profile is not None else {}),
        **({'native_search_home': Path(descriptor['native_home'])}
           if descriptor.get('search_policy') == native_search.CONTRACT else {}))
    identity = process_identity(current['pid'])
    require(identity is not None and current['diagnostics'].get('native_enabled') is False,
            'router_identity_unverified')
    write_new(attempt / 'running.json', {'process': identity, 'service': current['service'], 'started_utc': utc()})
    if web_profile is not None:
        bound = router.bind_web(root / 'router', descriptor['port'], web_profile)
        require(all(bound.get(key) == descriptor['web'][key] for key in ('profile_sha256','session_sha256')),
                'router_web_bind_unconfirmed')
        current = router.control(root / 'router', descriptor['port'])
    return current


def router_attempt(root):
    attempts = []
    for attempt in (root / 'router-launches').iterdir():
        checked_path(attempt, directory=True)
        require(re.fullmatch('[a-f0-9]{32}', attempt.name), 'router_record_invalid')
        intent = decode(read(attempt / 'intent.json'))
        attempts.append((intent['started_utc'], attempt))
    attempts.sort()
    for _, previous in attempts[:-1]:
        require(router_terminal(root, previous), 'router_previous_attempt_uncertain')
    return attempts[-1][1] if attempts else None


def stop_router(root):
    """Explicit normal stop, only after Desktop exited and the server is idle."""
    import operator_model_router as router
    with lock(root):
        descriptor = load(root)
        require(active_desktop(root) is None, 'close_extension_before_service_stop')
        attempt = router_attempt(root)
        if attempt is None:
            return report(root, descriptor, phase='service_not_started')
        if (attempt / 'stopped.json').exists():
            stopped = decode(read(attempt / 'stopped.json'))
            require(not process_matches(stopped.get('process')), 'router_stop_uncertain')
            with router.reserve_inactive_port(descriptor['port']):
                return report(root, descriptor, phase='service_stopped')
        if (attempt / 'absence-reviewed.json').exists():
            require(router_terminal(root, attempt), 'router_absence_review_changed')
            with router.reserve_inactive_port(descriptor['port']):
                return report(root, descriptor, phase='service_absence_reviewed', normal_stop_claimed=False)
        require(not (attempt / 'stop-intent.json').exists(), 'router_stop_uncertain_no_retry')
        running = decode(read(attempt / 'running.json'))
        require(process_matches(running.get('process')), 'router_process_uncertain')
        before = start_router(root, descriptor, check_web_service=False)  # The frozen router identity remains stoppable.
        write_new(attempt / 'stop-intent.json', {'created_utc': utc(), 'process': running['process']})
        stopped = router.control(root / 'router', descriptor['port'], stop=True)
        require(stopped.get('service') == before['service'] and stopped.get('pid') == before['pid']
                and stopped.get('status') == 'stopping', 'router_stop_unconfirmed')
        deadline = time.monotonic() + 10
        while process_matches(running['process']) and time.monotonic() < deadline:
            time.sleep(.1)
        require(not process_matches(running['process']), 'router_process_not_exited')
        with router.reserve_inactive_port(descriptor['port']):
            write_new(attempt / 'stopped.json', {'process': running['process'], 'stopped_utc': utc(),
                                              'server_confirmed_request_free': True})
        return report(root, descriptor, phase='service_stopped')


def host_plan(root, descriptor):
    package = descriptor['package']
    return {'schema_version': 1, 'contract': HOST_CONTRACT, 'root': str(root),
        'native_home': descriptor['native_home'], 'home': str(root / 'home'),
        'user_data': str(root / 'user-data'), 'package_full_name': package['full_name'],
        'official_executable': package['executable'], 'official_sha256': package['executable_sha256'],
        'host_sha256': descriptor['compiled']['operator-mode-host.exe'],
        'config_sha256': file_hash(root / 'home' / 'config.toml'),
        'catalog_sha256': descriptor['catalog_sha256'], 'window_app_id': descriptor['window_app_id']}


def launch(root, *, start_service=True):
    with lock(root):
        return launch_checked(root, start_service=start_service)


def launch_checked(root, *, start_service=True):
    descriptor = load(root)
    require(inspect_package() == descriptor['package'], 'official_package_changed')
    if descriptor.get('onboarding', {}).get('supported') is True:
        require(inspect_contract(descriptor['package']) == descriptor['onboarding'], 'onboarding_contract_changed')
    active = active_desktop(root)
    if active is not None:
        if start_service:
            start_router(root, descriptor)
        return activate_desktop(root, descriptor, active)
    previous = sorted((root / 'launches').iterdir())
    attempt = root / 'launches' / secrets.token_hex(16)
    private_directory(attempt)
    write_new(attempt / 'intent.json', {'contract': CONTRACT, 'created_utc': utc(), 'start_service': start_service})
    try:
        if start_service:
            start_router(root, descriptor)
        plan = host_plan(root, descriptor)
        plan_bytes = json_bytes(plan)
        # Each attempt retains its exact plan; the root pointer only dispatches
        # the current explicit launch. An uncertain attempt blocks another one.
        write_new(attempt / 'host-plan.json', plan_bytes)
        target = root / 'host-plan.json'
        if target.exists():
            require(previous, 'unexpected_host_plan')
            temporary = root / ('host-plan-' + secrets.token_hex(16) + '.json')
            write_new(temporary, plan_bytes)
            os.replace(temporary, target)
        else:
            write_new(target, plan_bytes)
        pwsh = shutil.which('pwsh.exe')
        require(pwsh is not None, 'powershell_unavailable')
        result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(root / 'entry.ps1'), '-Action', 'package-launch', '-Root', str(root),
            '-Attempt', attempt.name, '-PlanSha256', digest(plan_bytes)], capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        require(result.returncode == 0, 'package_dispatch_failed')
        write_new(attempt / 'dispatched.json', {'dispatched_utc': utc(), 'accepted': True})
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            if (attempt / 'host-failed.json').exists():
                raise ModeEntryError(decode(read(attempt / 'host-failed.json'))['reason'])
            if (attempt / 'windows-bound.json').exists():
                value = decode(read(attempt / 'windows-bound.json'))
                require(value.get('native_config_unchanged') is True, 'native_configuration_changed')
                return report(root, descriptor, phase='window_bound', attempt=attempt.name,
                              process_id=value['pid'], native_config_unchanged=True,
                              window_handle=value.get('window_handle'),
                              window_process=decode(read(attempt / 'desktop-started.json'))['process'])
            if (attempt / 'desktop-exited.json').exists():
                raise ModeEntryError('mode_desktop_exited_before_window')
            time.sleep(.2)
        raise ModeEntryError('mode_launch_observation_timeout')
    except Exception as error:
        reason = failure_reason(error)
        write_new(attempt / 'controller-failed.json', {'reason': reason, 'retained_utc': utc(),
                                                     'automatically_retried': False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'status', 'launch', 'service-start', 'service-stop',
                                         'refresh-preview', 'refresh'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--port', type=int)
    parser.add_argument('--model')
    parser.add_argument('--credentials', type=Path)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--expected-preview-sha256')
    parser.add_argument('--search', choices=['official-current-user', 'unavailable'])
    parser.add_argument('--enable-native-search', action='store_true')
    parser.add_argument('--request-free-startup-probe', action='store_true')
    args = parser.parse_args()
    try:
        require(args.root.is_absolute(), 'absolute_root_required')
        if args.action == 'prepare':
            require(args.search is not None, 'explicit_search_selection_required')
            require(all(value is not None for value in (args.project, args.registry, args.port, args.model)),
                    'prepare_arguments_required')
            value = prepare(args.project, args.root, args.registry, args.port, args.model,
                            credentials=args.credentials, runtime_python=args.python,
                            search_policy=native_search.CONTRACT if args.search == 'official-current-user' else 'unavailable')
        elif args.action == 'launch':
            value = launch(args.root, start_service=not args.request_free_startup_probe)
        elif args.action == 'service-start':
            require(not args.request_free_startup_probe, 'probe_only_for_launch')
            with lock(args.root):
                descriptor = load(args.root)
                require(active_desktop(args.root) is not None, 'desktop_required_before_service_start')
                current = start_router(args.root, descriptor)
                value = report(args.root, descriptor, phase='service_ready', process_id=current['pid'])
        elif args.action == 'service-stop':
            require(not args.request_free_startup_probe, 'probe_only_for_launch')
            value = stop_router(args.root)
        elif args.action in {'refresh-preview', 'refresh'}:
            require(not args.request_free_startup_probe, 'probe_only_for_launch')
            value = refresh_preview(args.root, enable_native_search=args.enable_native_search) if args.action == 'refresh-preview' else refresh(
                args.root, args.expected_preview_sha256, enable_native_search=args.enable_native_search)
        else:
            require(not args.request_free_startup_probe, 'probe_only_for_launch')
            descriptor = load(args.root)
            value = report(args.root, descriptor, phase='checked',
                           official_package_matches=inspect_package() == descriptor['package'])
        print(json.dumps(value, ensure_ascii=True))
        return 0
    except Exception as error:
        reason = failure_reason(error)
        print(json.dumps({'contract': CONTRACT, 'phase': 'failed', 'reason': reason,
                          'native_config_writes': 0, 'automatically_retried': False}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
