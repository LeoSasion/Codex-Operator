"""Read-only product overview. No model request, service control or account probe."""
import argparse
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tomllib


SCRIPTS = Path(__file__).resolve().parent
BOUND = 1024 * 1024
READINESS_GATES = {'runtime_running', 'runtime_manifest', 'health_current', 'feishu_consumer',
    'access_configured', 'minimal_beeper_relay', 'init_catalog', 'final_callback'}
WEB_ENTRY_STAGES = {'request', 'project', 'profile', 'runtime', 'python', 'worker', 'manager', 'settings', 'result'}
WEB_ENTRY_FAILURES = {
    'web_entry_access_denied': ('unavailable', '当前检查环境无法读取所需文件，现有登录与连接保留', '由助手核对当前检查环境的文件访问范围'),
    'web_entry_invalid_request': ('unavailable', '状态检查参数不适用，现有配置仍保留', '由助手修正入口调用'),
    'web_entry_project_unavailable': ('unavailable', '项目入口暂时无法读取，现有配置仍保留', '由助手核对项目入口及访问范围'),
    'web_entry_profile_unreadable': ('unavailable', '保存的入口暂时无法读取，未判定配置丢失', '由助手核对入口文件及访问范围'),
    'web_entry_profile_invalid': ('needs_review', '已找到入口登记，但格式无法验证，原文件保留', '由助手核对原登记格式；无需重新登录'),
    'web_entry_runtime_mismatch': ('needs_review', '保存的入口属于另一份程序，未切换或覆盖', '由助手核对原程序位置和入口归属'),
    'web_entry_python_unavailable': ('unavailable', '保存的运行程序暂时不可用，固定连接保留', '由助手核对原运行程序位置及访问范围'),
    'web_entry_python_changed': ('needs_review', '保存的运行程序发生变化，固定连接保留', '由助手核对版本与原登记；无需重新登录'),
    'web_entry_worker_changed': ('needs_review', '后台运行程序变化或不可用，固定连接保留', '由助手核对后台运行程序与原登记'),
    'web_entry_manager_unavailable': ('unavailable', '管理程序暂时不可用，现有配置仍保留', '由助手核对管理程序及访问范围'),
    'web_entry_manager_launch_failed': ('unavailable', '管理程序未能完成检查，现有配置仍保留', '由助手核对管理程序及依赖'),
    'web_entry_settings_required': ('needs_review', '入口需要接入已有连接设置，未覆盖保存内容', '由助手核对已有设置；无需创建新连接或密钥'),
    'web_entry_settings_unavailable': ('unavailable', '已有连接设置暂时无法读取，保存内容保留', '由助手核对原设置位置及访问范围'),
    'web_entry_settings_changed': ('needs_review', '原设置内容发生变化，暂未采用新内容', '由助手核对设置变化后明确选择；无需重新创建连接'),
    'web_entry_reuse_unverified': ('unavailable', '保存入口的直接复用尚未确认，未更新配置或启动后台', '由助手核对原登记；无需重新登录'),
    'web_entry_manager_result_invalid': ('unavailable', '管理程序未返回可验证结果，现有配置保留', '由助手核对管理程序及依赖'),
}
CHECK_FAILURES = {
    'check_launcher_unavailable': ('unavailable', '状态检查程序暂时不可用，现有配置仍保留', '由助手核对状态检查程序'),
    'check_timed_out': ('unavailable', '本次状态检查未能及时完成，后台状态尚未确认', '由助手检查管理入口耗时；不重启或重配后台'),
    'check_result_invalid': ('unavailable', '本次状态检查结果无法验证，后台状态尚未确认', '由助手核对管理入口的状态输出'),
    'check_failed': ('unavailable', '本次状态检查未完成，现有登录与连接保留', '由助手核对管理入口；无需重新配置'),
}


def check_failure(reason):
    return {'status': 'unavailable', 'code': 'product_check_unavailable', 'reason': reason}


def web_failure(observation):
    """Project only fixed diagnostics; never echo child prose, paths or exceptions."""
    code, reason = observation.get('code'), observation.get('reason')
    if observation.get('status') != 'unavailable' or not isinstance(reason, str):
        return None
    choices = WEB_ENTRY_FAILURES if code == 'web_entry_unavailable' else CHECK_FAILURES if code == 'product_check_unavailable' else {}
    if reason not in choices:
        return None
    diagnostic = {'code': code, 'reason': reason}
    if isinstance(observation.get('stage'), str) and observation['stage'] in WEB_ENTRY_STAGES:
        diagnostic['stage'] = observation['stage']
    if observation.get('profile_state') in ('unknown', 'present', 'absent'):
        diagnostic['profile_state'] = observation['profile_state']
    return choices[reason], diagnostic


def file_state(path):
    """Absence is distinct from access failure, a linked path or a wrong type."""
    try:
        for item in [*reversed(path.parents), path]:
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return 'unavailable'
            if item != path and not stat.S_ISDIR(info.st_mode):
                return 'unavailable'
        return 'present' if stat.S_ISREG(info.st_mode) else 'unavailable'
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'unavailable'


def observe(inspect, project, scope, action):
    try:
        value = inspect(project, scope, action)
    except (OSError, ValueError, TimeoutError):
        return {'status': 'unavailable'}
    return value if isinstance(value, dict) else {'status': 'unavailable'}


def read_object(path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('linked_state')
    with path.open('rb') as stream:
        raw = stream.read(BOUND + 1)
    if len(raw) > BOUND:
        raise ValueError('state_size')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('state_shape')
    return value


def inspect_entry(project, scope, action):
    """Only these three existing read-only operations are admitted."""
    if (scope, action) not in {('operator', 'readiness'), ('web', 'status'), ('web', 'desktop-status')}:
        raise ValueError('read_only_operation_required')
    shell = shutil.which('pwsh')
    if not shell:
        return check_failure('check_launcher_unavailable')
    try:
        child = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            str(SCRIPTS / 'feishu-codex-operator.ps1'), scope, action,
            '-ProjectRoot', str(project), '-Json'], capture_output=True, timeout=25,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if len(child.stdout) > 65536:
            return check_failure('check_result_invalid')
        value = json.loads(child.stdout.decode('utf-8-sig'))
        if not isinstance(value, dict):
            return check_failure('check_result_invalid')
        if child.returncode in (0, 2):
            return value
        # Failed entry checks carry useful bounded evidence, not successful service state.
        failure = web_failure(value) if scope == 'web' and child.returncode == 1 else None
        if failure:
            return {'status': 'unavailable', **failure[1]}
        return check_failure('check_failed')
    except subprocess.TimeoutExpired:
        return check_failure('check_timed_out')
    except OSError:
        return check_failure('check_launcher_unavailable')
    except ValueError:
        return check_failure('check_result_invalid')


def inspect_isolated_entry(project):
    """Check the exact saved entry; never substitute a legacy provider or launch."""
    path = project / '.codex/operator-desktop-entry/desktop-entry.json'
    state = file_state(path)
    if state == 'absent':
        return None
    unknown = {'scope': 'isolated_mode', 'state': 'unavailable',
               'package_current': None, 'web_state': 'unavailable'}
    search_path = None
    def bounded_bytes(target):
        if file_state(target) != 'present':
            raise ValueError('entry_unavailable')
        with target.open('rb') as stream:
            raw = stream.read(BOUND + 1)
        if len(raw) > BOUND:
            raise ValueError('entry_size')
        return raw
    def child_observation(executable, helper, timeout):
        child = subprocess.run([str(executable), '-X', 'utf8', '-E', '-s', '-B',
            str(helper), '--project-root', str(project), '--isolated-entry-only'],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if child.returncode != 0 or len(child.stdout) > 4096:
            raise ValueError('entry_child_unavailable')
        observed = json.loads(child.stdout.decode('utf-8-sig'))
        if (not isinstance(observed, dict) or set(observed) != set(unknown)
                or observed['scope'] != 'isolated_mode'
                or observed['state'] not in ('configured', 'needs_review', 'unavailable')
                or observed['web_state'] not in ('absent', 'bound', 'changed', 'unavailable')
                or (observed['package_current'] is not None
                    and type(observed['package_current']) is not bool)):
            raise ValueError('entry_child_result_invalid')
        return observed
    try:
        if state != 'present':
            return unknown
        before = bounded_bytes(path)
        entry = read_object(path)
        if json.loads(before) != entry:
            return unknown
        if entry.get('mode') in ('native', 'reviewed_startup', 'direct_profile'):
            return None
        if (type(entry.get('schema_version')) is not int or entry['schema_version'] != 1
                or entry.get('mode') != 'isolated_mode'
                or not isinstance(entry.get('startup_bundle'), str)
                or not re.fullmatch(r'\.codex/operator-mode-entry/[a-f0-9]{32}', entry['startup_bundle'])):
            return unknown
        root = project / entry['startup_bundle']
        retained = {}
        for key, target in (
                ('entry_script_sha256', path.parent / 'operator_desktop_entry.ps1'),
                ('mode_entry_sha256', root / 'entry.json')):
            expected = entry.get(key)
            raw = bounded_bytes(target)
            if (not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)
                    or hashlib.sha256(raw).hexdigest() != expected):
                return unknown
            retained[target] = raw
        if SCRIPTS == project / '.codex/feishu-codex-operator-runtime':
            # Mode maintenance stays canonical. The installed status helper may
            # delegate only to the same exact read-only source generation.
            caller = SCRIPTS / 'operator_product.py'
            helper = project / 'plugins/feishu-codex-operator/scripts/operator_product.py'
            retained[caller] = bounded_bytes(caller)
            retained[helper] = bounded_bytes(helper)
            if retained[caller] != retained[helper]:
                return unknown
            observed = child_observation(sys.executable, helper, 40)
            if (bounded_bytes(path) != before
                    or any(bounded_bytes(target) != raw for target, raw in retained.items())):
                return unknown
            return observed
        # Validate the retained canonical source generation before importing its
        # controller. Missing or linked project files must never use site-packages.
        saved = json.loads(retained[root / 'entry.json'])
        bindings = saved.get('source_bindings') if isinstance(saved, dict) else None
        top = {'operator_mode_entry.py', 'operator_mode_entry.ps1', 'operator_mode_host.cs',
            'operator_mode_picker.cs', 'operator_model_router.py', 'operator_native_models.py',
            'operator_web_service.py', 'operator_mode_onboarding.py', 'operator_mode_native.cs',
            'operator_mode_maintenance.py', 'operator_mode_pair_refresh.ps1', 'operator_mode_backends.py'}
        if (not isinstance(bindings, dict) or not 0 < len(bindings) <= 128
                or not top | {'operator_core/__init__.py'} <= set(bindings)):
            return unknown
        module_paths = {}
        for name, expected in bindings.items():
            if (not isinstance(name, str) or (name not in top and not re.fullmatch(
                    r'operator_core/(?:[a-z0-9_]+/)*[a-z0-9_]+\.(?:py|json)', name))
                    or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)):
                return unknown
            target = SCRIPTS / name
            raw = bounded_bytes(target)
            if hashlib.sha256(raw).hexdigest() != expected:
                return unknown
            retained[target] = raw
            if target.suffix == '.py':
                module_name = name[:-3].replace('/', '.')
                module_paths[module_name.removesuffix('.__init__')] = target
        current_core = set()
        for target in (SCRIPTS / 'operator_core').rglob('*'):
            info = target.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return unknown
            if stat.S_ISREG(info.st_mode) and target.suffix in ('.py', '.json'):
                current_core.add(target.relative_to(SCRIPTS).as_posix())
                if len(current_core) > 128:
                    return unknown
        if current_core != {name for name in bindings if name.startswith('operator_core/')}:
            return unknown
        profile_changed = False
        if saved.get('web') is not None:
            web = saved['web']
            if not isinstance(web, dict) or not isinstance(web.get('profile'), str):
                return unknown
            profile = Path(web['profile']) / 'profile.json'
            if not profile.is_absolute() or project / '.codex' not in profile.parents:
                return unknown
            profile_raw = bounded_bytes(profile)
            expected_profile = web.get('profile_sha256')
            if not isinstance(expected_profile, str) or not re.fullmatch('[a-f0-9]{64}', expected_profile):
                return unknown
            retained[profile] = profile_raw
            profile_changed = hashlib.sha256(profile_raw).hexdigest() != expected_profile
            if not profile_changed:
                configuration = json.loads(profile_raw)
                runtime = configuration.get('runtime', {}) if isinstance(configuration, dict) else {}
                expected = runtime.get('sources', {}).get('operator_web_model.py') if isinstance(runtime, dict) else None
                target = SCRIPTS / 'operator_web_model.py'
                raw = bounded_bytes(target)
                if (runtime.get('source_root') != str(SCRIPTS) or not isinstance(expected, str)
                        or hashlib.sha256(raw).hexdigest() != expected):
                    return unknown
                retained[target] = raw
                module_paths['operator_web_model'] = target
        # Check what Python will select without importing a parent package.
        # A same-named package or extension must not execute before rejection.
        for name, target in module_paths.items():
            package = target.name == '__init__.py'
            parent = target.parent.parent if package else target.parent
            spec = importlib.machinery.PathFinder.find_spec(name, [str(parent)])
            if spec is None or not isinstance(spec.origin, str) or Path(spec.origin) != target:
                return unknown
            locations = spec.submodule_search_locations
            if package:
                if locations is None or [Path(p) for p in locations] != [target.parent]:
                    return unknown
            elif locations is not None:
                return unknown
        def checked_origins():
            for name, target in module_paths.items():
                if name not in sys.modules:
                    continue
                module = sys.modules[name]
                origin = getattr(module, '__file__', None)
                if not isinstance(origin, str) or Path(origin) != target:
                    raise ValueError('entry_module_origin_changed')
                if name == 'operator_core' and [Path(p) for p in module.__path__] != [target.parent]:
                    raise ValueError('entry_package_origin_changed')
        checked_origins()
        search_path = list(sys.path)
        sys.path.insert(0, str(SCRIPTS))
        import operator_mode_entry as mode
        from operator_mode_backends import checked_web_binding
        checked_origins()
        if any(bounded_bytes(target) != raw for target, raw in retained.items()):
            return unknown
        descriptor = mode.load(root)
        selected_python = Path(descriptor['python'])
        if selected_python.resolve() != Path(sys.executable).resolve():
            # Manager identity includes its saved interpreter. PATH's Python
            # must not turn an intact service into a runtime-change diagnosis.
            observed = child_observation(selected_python, SCRIPTS / 'operator_product.py', 20)
            if (bounded_bytes(path) != before or mode.load(root) != descriptor
                    or any(bounded_bytes(target) != raw for target, raw in retained.items())):
                return unknown
            checked_origins()
            return observed
        current_package = mode.inspect_package() == descriptor['package']
        web_state = 'absent'
        if descriptor.get('web') is not None:
            if profile_changed:
                web_state = 'changed'
            else:
                try:
                    checked_web_binding(descriptor)
                    web_state = 'bound'
                except ValueError as error:
                    web_state = ('changed' if str(error) in {
                        'mode_web_generation_changed_review_required', 'mode_backend_web_catalog_changed',
                        'web_manager_route_digest_changed', 'web_manager_model_catalog_changed'} else 'unavailable')
        # The entry and controller must remain bound across all observations.
        if (bounded_bytes(path) != before or mode.load(root) != descriptor
                or any(bounded_bytes(target) != raw for target, raw in retained.items())):
            return unknown
        checked_origins()
        return {'scope': 'isolated_mode',
                'state': 'configured' if current_package and web_state != 'changed' else 'needs_review',
                'package_current': current_package, 'web_state': web_state}
    except Exception:
        # Fixed projections only: no private paths, configuration or exception text.
        return unknown
    finally:
        if search_path is not None:
            sys.path[:] = search_path


def project_overview(project, home, inspect=inspect_entry, inspect_isolated=inspect_isolated_entry):
    project = Path(project)
    home = Path(home)
    if not project.is_absolute() or not project.is_dir() or project.is_symlink():
        raise ValueError('absolute_project_required')
    report = {'schema_version': 2, 'command': 'product.status', 'channel': 'preview',
        'read_only': True, 'model_requests': 0, 'components': {}}
    components = report['components']
    runtime = project / '.codex/feishu-codex-operator-runtime'
    runtime_state = file_state(runtime / 'runtime-manifest.json')
    ownership_state = (file_state(project / '.codex/operator-installation/ownership.json')
        if runtime_state == 'present' else 'absent')
    if runtime_state == 'absent':
        feishu = ('not_installed', '尚未安装', 'channels install')
    elif runtime_state == 'unavailable':
        feishu = ('unavailable', '无法读取通道安装状态，现有设置仍保留', 'channels readiness')
    else:
        observation = observe(inspect, project, 'operator', 'readiness')
        gates = observation.get('gates', {})
        valid = (isinstance(gates, dict) and set(gates) == READINESS_GATES
            and all(type(v) is bool for v in gates.values())
            and type(observation.get('ready')) is bool
            and observation['ready'] == all(gates.values())
            and observation.get('status') == ('ready' if observation['ready'] else 'not_ready'))
        if not valid:
            feishu = ('unavailable', '通道状态暂时无法确认，现有登录与设置仍保留', 'channels readiness')
        elif observation['ready']:
            feishu = ('ready', '接收与回传服务就绪，飞书消息仍需实际验证', '已有绑定可直接发送消息；需要绑定或改绑时使用 /init')
        elif ownership_state == 'absent':
            feishu = ('needs_review', '通道服务尚未就绪；旧通道安装缺少归属记录，现有运行时与配置已保留',
                '由助手审核旧安装与原件，确定单独迁移方案；不要直接重装或重投消息')
        elif ownership_state == 'unavailable':
            feishu = ('unavailable', '通道安装归属记录暂时无法核对，现有文件已保留',
                '由助手核对记录文件及访问范围；不要覆盖现有安装')
        elif not gates['runtime_manifest'] and all(value for name, value in gates.items() if name != 'runtime_manifest'):
            feishu = ('needs_review', '接收与回传服务检查通过，安装清单仍需核对；尚未满足完整就绪条件', '由助手核对安装清单与当前源码；保留已有登录和任务绑定')
        else:
            feishu = ('needs_setup', '通道尚未就绪，已有登录与配置保留；需核对服务及接收回传状态', 'channels readiness')
    components['channels'] = {**dict(zip(('state', 'summary', 'next_action'), feishu)), 'implemented': ['feishu']}

    profile = project / '.codex/operator-web-service/profile.json'
    profile_state = file_state(profile)
    observation = observe(inspect, project, 'web', 'status') if profile_state == 'present' else {}
    # Check the entry after the Web observation used below. A service generation
    # change during earlier checks must not reuse an old successful binding.
    isolated = inspect_isolated(project)
    web_diagnostic = None
    if profile_state == 'absent':
        web = ('not_configured', '尚未保存 Web 连接', '由助手引导首次登录和固定连接配置')
    elif profile_state == 'unavailable':
        web = ('unavailable', '无法读取已有 Web 配置，未要求重新登录或创建连接', 'web status')
    else:
        state = observation.get('status')
        failure = web_failure(observation)
        if failure:
            web, web_diagnostic = failure
        elif state == 'unavailable' and observation.get('configuration_current') is False:
            web = ('unavailable', 'Web 后台当前不可用，保存配置与当前程序也不一致；原件保留',
                '由助手核对准确实例与失败记录，再检查更新登记；不要重发失败请求或要求重新登录')
        elif observation.get('configuration_current') is False:
            web = ('changed', '已有配置与当前程序不一致，保留原配置等待核对',
                '由助手核对原登记与空闲状态，再按受控流程更新；无需重新登录')
        elif observation.get('configuration_current') is not True or not isinstance(state, str) or state not in {
                'ready', 'assistance', 'starting', 'preparing', 'connection', 'reconnecting', 'draining', 'configured', 'stopped'}:
            web = ('unavailable', '后台状态暂时无法确认，现有登录与配置仍保留', 'web status')
        elif state == 'draining':
            web = ('stopping', '后台正在结束当前工作，保存的连接仍保留', '等待结束后查看 models web status')
        elif state in ('ready', 'connection', 'reconnecting', 'assistance') and observation.get('active') is True:
            web = ('busy', 'Web 正在处理当前请求', '等待当前任务结束；不重复提交')
        elif observation.get('needs_assistance') is True:
            web = ('needs_review', '后台留有辅助标记，尚未确认当前页面是否需要操作', '由助手先检查准确当前页面；确见登录或验证要求后再请用户操作')
        elif state == 'assistance' and observation.get('needs_assistance') is False:
            web = ('assistance_open', '辅助或查看窗口已打开，保存的登录与配置仍保留', '完成当前查看或操作后关闭辅助窗口')
        elif state == 'starting':
            web = ('starting', '后台正在启动，沿用保存的配置', '稍后查看 models web status')
        elif state == 'preparing':
            web = ('preparing', '后台正在准备空白聊天，沿用保存的登录与配置', '稍后查看 models web status')
        elif state in ('connection', 'reconnecting'):
            web = ('connecting', '后台正在建立连接，沿用保存的登录与配置', '稍后查看 models web status')
        elif state == 'ready' and observation.get('active') is False and observation.get('session_bound') is False:
            web = ('needs_registration', '后台已就绪，启动登记尚未完成；显式复用当前实例即可继续接入', 'web start')
        elif state == 'ready' and observation.get('active') is False:
            if isolated is not None:
                # The current isolated entry owns its binding. A retained legacy
                # native provider cannot supply its state or a rebind action.
                isolated_web = isolated.get('web_state')
                if isolated.get('state') == 'unavailable' or isolated_web == 'unavailable':
                    web = ('unavailable', '后台就绪；当前拓展入口的连接暂时无法核对',
                        '由助手核对当前拓展入口与保存记录；不要重绑历史提供方')
                elif isolated_web == 'bound':
                    web = ('ready', '后台就绪，当前拓展入口的 Web 绑定已核对；实际执行仍需分别确认',
                        '受控更新拓展入口后使用已接入 Web 的任务' if isolated.get('package_current') is False
                        else '从拓展入口使用已接入 Web 的任务')
                elif isolated_web == 'absent':
                    web = ('needs_connection', '后台就绪，当前拓展入口尚未接入 Web',
                        '由助手按拓展入口的受控流程接入保存的 Web 服务')
                else:
                    web = ('needs_review', '后台就绪，当前拓展入口保存的 Web 绑定需要核对',
                        '由助手核对当前拓展入口与服务代次；保留原件和失败记录')
            else:
                binding_observation = observe(inspect, project, 'web', 'desktop-status')
                binding = binding_observation.get('status')
                binding_failure = web_failure(binding_observation)
                if binding == 'stale' and binding_observation.get('reason') == 'service_generation_changed':
                    web = ('needs_review', '后台已换实例，原生 Web 提供方仍指向旧连接', 'web desktop-rebind')
                elif binding == 'connected':
                    web = ('ready', '后台就绪，独立提供方已登记；任务绑定和实际执行需分别确认', '在已接入 Web 的 Codex 任务中提出需求')
                elif binding in ('absent', 'disconnected'):
                    web = ('needs_connection', '后台就绪，待登记独立提供方', 'web desktop-prepare')
                elif binding == 'prepared':
                    web = ('needs_connection', '独立提供方已准备，待登记', 'web desktop-connect')
                elif binding_failure:
                    web, web_diagnostic = binding_failure
                    web = (web[0], '后台就绪；提供方登记检查：' + web[1], web[2])
                elif binding in (None, 'unavailable'):
                    web = ('unavailable', '后台就绪，暂时无法确认提供方登记；现有连接仍保留', 'web desktop-status')
                else:
                    web = ('changed', '后台可用，已有提供方登记需核对', 'web desktop-status')
        elif state in ('configured', 'stopped'):
            if observation.get('start_available') is False:
                web = ('needs_review', '旧连接仍有占用记录，需核对后再启动', 'web recover')
            else:
                web = ('stopped', '连接配置已保存，后台未运行', 'web start')
        else:
            web = ('unavailable', '后台状态暂时无法确认，现有登录与配置仍保留', 'web status')
    web_status = dict(zip(('state', 'summary', 'next_action'), web))
    if web_diagnostic:
        web_status['diagnostic'] = web_diagnostic
    if web_status['next_action'].startswith('web '):
        web_status['next_action'] = 'models ' + web_status['next_action']

    registry = runtime / 'model-router/registry.json'
    count = 0
    model_state = 'not_configured'
    registry_state = file_state(registry)
    if registry_state == 'unavailable':
        model_state = 'unavailable'
    elif registry_state == 'present':
        try:
            value = read_object(registry)
            rows = value.get('models')
            if type(value.get('version')) is not int or value['version'] not in (1, 2) or not isinstance(rows, list) or len(rows) > 1024 or not all(isinstance(r, dict) for r in rows):
                raise ValueError('registry_shape')
            count = len(rows)
            model_state = 'registered' if count else 'not_configured'
        except (OSError, ValueError):
            model_state = 'needs_review'
    overall_state = 'not_configured'
    if model_state == 'unavailable' or web_status['state'] == 'unavailable':
        overall_state = 'unavailable'
    elif model_state == 'needs_review' or web_status['state'] in ('changed', 'needs_review'):
        overall_state = 'needs_review'
    elif count or web_status['state'] != 'not_configured':
        overall_state = 'configured'
    components['models'] = {'state': overall_state, 'registry_state': model_state, 'registered_count': count,
        'summary': '模型按端点单独接入；登记数量不代表可用或已出现在菜单中',
        'next_action': '由助手按官方 provider 优先流程接入所选在线、本地或 Web 模型',
        'providers': {
            'api': {'state': 'endpoint_check_required', 'summary': '按所选 API 端点分别检查，不从登记总数推断可用性'},
            'local': {'state': 'endpoint_check_required', 'summary': '按所选本地服务分别检查，不自动加载或下载模型'},
            'web': web_status}}
    if isolated is not None:
        entry_state = isolated.get('state')
        package_current = isolated.get('package_current')
        if (entry_state == 'unavailable' or entry_state not in ('configured', 'needs_review')
                or type(package_current) is not bool):
            entry = {'scope': 'isolated_mode', 'state': 'unavailable',
                'summary': '当前拓展入口暂时无法核对，已保存聊天与原件保留',
                'next_action': '由助手核对准确入口与归属记录；不重启或重配后台'}
            components['models']['state'] = 'unavailable'
        elif package_current is False:
            entry = {'scope': 'isolated_mode', 'state': 'needs_review',
                'summary': '拓展入口绑定的官方包与当前应用不一致；原聊天与原件保留',
                'next_action': '由助手受控更新拓展入口；先核对旧进程与路由退出证据'}
            if components['models']['state'] != 'unavailable':
                components['models']['state'] = 'needs_review'
        elif entry_state == 'needs_review':
            entry = {'scope': 'isolated_mode', 'state': 'needs_review',
                'summary': '官方包一致，当前拓展入口的 Web 绑定需要核对；原聊天与原件保留',
                'next_action': '由助手核对当前拓展入口与服务代次；保留原件和失败记录'}
            if components['models']['state'] != 'unavailable':
                components['models']['state'] = 'needs_review'
        else:
            entry = {'scope': 'isolated_mode', 'state': entry_state,
                'summary': '当前拓展入口已核对；窗口启动与实际模型执行需分别确认',
                'next_action': '使用当前拓展入口；实际模型能力按已验收范围判断'}
        components['models']['entry'] = entry
        if entry['state'] != 'configured':
            components['models']['next_action'] = entry['next_action']

    routing = 'unknown'
    try:
        config_path = home / 'config.toml'
        config_state = file_state(config_path)
        if config_state == 'absent':
            routing = 'custom' if os.environ.get('OPENAI_BASE_URL') else 'default'
        elif config_state == 'unavailable':
            routing = 'unknown'
        else:
            with config_path.open('rb') as stream:
                raw = stream.read(BOUND + 1)
            if len(raw) > BOUND:
                raise ValueError('config_size')
            config = tomllib.loads(raw.decode('utf-8-sig'))
            providers = config.get('model_providers', {})
            if not isinstance(providers, dict):
                raise ValueError('config_provider_shape')
            # As in the Channels catalog guard, the name "openai" alone does
            # not establish the official route when its endpoint is overridden.
            redirected = (bool(os.environ.get('OPENAI_BASE_URL'))
                or config.get('openai_base_url') is not None
                or config.get('model_provider', 'openai') != 'openai'
                or bool(providers.get('openai')))
            routing = 'custom' if redirected else 'official_direct'
    except (OSError, ValueError):
        pass
    report['native_routing'] = routing
    protection = file_state(home / 'operator-native-route-only')
    report['native_only_protection'] = None if protection == 'unavailable' else protection == 'present'
    partial = (any(row['state'] == 'unavailable' for row in components.values())
        or routing == 'unknown' or protection == 'unavailable')
    report['status'] = 'partial' if partial else 'checked'
    report['summary'] = ('部分状态暂时无法确认；现有设置仍保留，不应据此重新配置。' if partial else
        '已检查本机配置与服务状态；未登录、启动服务、发送模型请求或修改设置。')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--isolated-entry-only', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_entry_only:
        print(json.dumps(inspect_isolated_entry(args.project_root), ensure_ascii=True))
        return 0
    try:
        result = project_overview(args.project_root,
            Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    except (OSError, ValueError):
        result = {'status': 'unavailable', 'summary': '当前项目无法检查；未修改配置或启动服务。'}
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print('Codex-Operator 预览版 · 使用进度')
        for key, label in [('channels', 'Channels（飞书）'), ('models', 'Models（API / Local / Web）')]:
            if key in result.get('components', {}):
                row = result['components'][key]
                print(f"{label}：{row['summary']}\n  下一步：{row['next_action']}")
                if 'entry' in row:
                    print(f"  拓展入口：{row['entry']['summary']}")
                for provider, status in row.get('providers', {}).items():
                    print(f"  {provider.capitalize()}：{status['summary']}")
                    if 'next_action' in status:
                        print(f"    下一步：{status['next_action']}")
        print(result['summary'])
    return 1 if result.get('status') == 'unavailable' else 2 if result.get('status') == 'partial' else 0


if __name__ == '__main__':
    raise SystemExit(main())
