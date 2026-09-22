"""Explicit fixed OpenAI MCP tunnel using the reviewed tunnel-client 0.0.12.

Python owns the listener, child and admission; the official client owns polling
and exact response delivery. No model API, admin API, MCP execution, global
profile, browser opening or automatic child restart is introduced here.
See references/web-background-sources.md for the upstream implementation review.
"""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout

from .responses_tool_adapter import loads
from .web_browser_driver import validate_connector
from .web_connection import WebMcpConnection
from .web_mcp_transport import require

START_TIMEOUT = 60
IDLE_TIMEOUT = 60
HEALTH_INTERVAL = 2
POLL_FRESH_SECONDS = 45
TUNNEL_ID = re.compile(r'tunnel_[a-f0-9]{32}')


def regular_bytes(path, limit):
    require(path.is_absolute() and path.is_file() and not path.is_symlink(),
        'web_fixed_tunnel_regular_file_required')
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'web_fixed_tunnel_file_bound')
    return value


def validate_proxy(value):
    if value is None:
        return None
    require(isinstance(value, str) and len(value) <= 512, 'web_fixed_tunnel_proxy_invalid')
    parsed = urlsplit(value)
    require(parsed.scheme in ('http', 'https') and parsed.hostname and parsed.port
        and not parsed.username and not parsed.password and not parsed.query
        and not parsed.fragment and parsed.path in ('', '/')
        and not any(c.isspace() for c in value), 'web_fixed_tunnel_proxy_invalid')
    return value


def tunnel_environment():
    # CLI environment takes precedence over YAML. An allowlist prevents inherited
    # MCP commands, control-plane overrides, debug logging or UI settings from
    # silently changing this exact private profile. Proxy is an explicit field.
    admitted = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'TEMP', 'TMP', 'TMPDIR',
        'USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA', 'HOMEDRIVE', 'HOMEPATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'LC_ALL'}
    return {key: value for key, value in os.environ.items() if key.upper() in admitted}


def publish_new(path, value):
    """Atomic, exclusive publication into an already private directory."""
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.link(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    return raw


def poll_timestamp(raw):
    # Dated official Prometheus metric, not a log message claiming readiness.
    text = raw.decode('utf-8', errors='strict')
    matches = re.findall(r'^commands_poll_last_successful_timestamp_seconds(?:\{[^\r\n]*\})? ([0-9.eE+-]{1,32})$',
        text, re.MULTILINE)
    require(len(matches) <= 1, 'web_fixed_tunnel_poll_metric_ambiguous')
    value = float(matches[0]) if matches else 0.0
    require(math.isfinite(value) and value >= 0 and value.is_integer(),
        'web_fixed_tunnel_poll_metric_invalid')
    return int(value)


class WebOpenAITunnel(WebMcpConnection):
    def __init__(self, settings, endpoint, state):
        required = {'mode', 'tunnel_client', 'tunnel_client_sha256', 'tunnel_id', 'api_key_file', 'binding_file'}
        require(isinstance(settings, dict) and required <= set(settings)
            and set(settings) <= required | {'control_plane_proxy'}
            and settings['mode'] == 'openai_tunnel_v1', 'web_fixed_tunnel_settings_invalid')
        require(isinstance(settings['tunnel_id'], str) and TUNNEL_ID.fullmatch(settings['tunnel_id']),
            'web_fixed_tunnel_id_invalid')
        require(all(isinstance(settings[key], str) for key in ('api_key_file', 'binding_file')),
            'web_fixed_tunnel_path_invalid')
        super().__init__({'cloudflared': settings['tunnel_client']}, endpoint, state)
        require(settings['tunnel_client_sha256'] == self.digest.hex(), 'web_fixed_tunnel_client_changed')
        self.tunnel_id = settings['tunnel_id']
        self.key_file = Path(settings['api_key_file'])
        self.binding_file = Path(settings['binding_file'])
        require(self.binding_file.is_absolute() and self.binding_file.parent.is_dir()
            and not self.binding_file.is_symlink() and not self.binding_file.parent.is_symlink()
            and self.key_file.parent == self.binding_file.parent
            and self.key_file != self.binding_file, 'web_fixed_tunnel_private_profile_required')
        key = regular_bytes(self.key_file, 4096)
        require(re.fullmatch(rb'sk-[A-Za-z0-9_-]{16,4090}\r?\n?', key), 'web_fixed_tunnel_key_invalid')
        self.key_digest = hashlib.sha256(key).digest()
        self.proxy = validate_proxy(settings.get('control_plane_proxy'))
        self.binding_snapshot = self.read_binding()
        self.lock_path = self.binding_file.parent / ('active-' + self.tunnel_id + '.json')
        self.lock_bytes = None
        self.health_file = self.directory / 'tunnel-health.url'
        self.health_url = None
        self.reconnect_policy = 'openai_idle_v1'
        self.observed_ready = False
        self.observed_at = 0
        self.last_poll = self.blocked_poll = 0
        self.start_time = 0

    def read_binding(self):
        if not self.binding_file.exists() and not self.binding_file.is_symlink():
            return None
        raw = regular_bytes(self.binding_file, 4096)
        value = loads(raw)
        require(isinstance(value, dict) and set(value) == {'version', 'tunnel_id', 'connector'}
            and value['version'] == 1 and value['tunnel_id'] == self.tunnel_id,
            'web_fixed_tunnel_saved_binding_changed')
        self.connector = validate_connector(value['connector'])
        return raw

    @property
    def connected(self):
        return (not self.closed and not self.failed.is_set() and self.observed_ready
            and time.monotonic() - self.observed_at < max(5, HEALTH_INTERVAL * 3)
            and self.child is not None and self.child.returncode is None)

    def status(self):
        return {**super().status(), 'mode': 'openai_tunnel_v1',
            'local_ready': self.observed_ready, 'poll_observed': self.last_poll > 0,
            'binding_persistent': self.connector is not None}

    def setup(self):
        require(self.connected, 'web_connection_unavailable')
        return {'version': 1, 'connection_id': self.id, 'tunnel_id': self.tunnel_id,
            'connector': self.connector, 'kind': 'fixed_openai_tunnel'}

    def bind(self, value):
        require(self.connected and self.connector is None, 'web_connection_bind_unavailable')
        require(isinstance(value, dict) and set(value) == {'connection_id', 'tunnel_id', 'connector'}
            and value['connection_id'] == self.id and value['tunnel_id'] == self.tunnel_id,
            'web_connection_binding_changed')
        connector = validate_connector(value['connector'])
        self.binding_snapshot = publish_new(self.binding_file,
            {'version': 1, 'tunnel_id': self.tunnel_id, 'connector': connector})
        self.connector = connector
        return dict(connector)

    def profile(self):
        control = {'base_url': 'https://api.openai.com', 'tunnel_id': self.tunnel_id,
            'api_key': 'file:' + str(self.key_file), 'poll_channels': ['main'],
            'max_inflight_requests': 1, 'poll_timeout': '10000ms', 'poll_deadline_guardrail': '5000ms'}
        if self.proxy:
            control['http_proxy'] = self.proxy
        return {'config_version': 1, 'control_plane': control,
            'health': {'listen_addr': '127.0.0.1:0', 'url_file': str(self.health_file)},
            'admin_ui': {'open_browser': False, 'log_buffer_events': 32},
            'log': {'level': 'info', 'format': 'json'},
            'mcp': {'server_urls': [{'channel': 'main', 'url': 'http://' + self.endpoint.host + self.endpoint.path}],
                'max_concurrent_requests': 2}}

    def pause_idle_connection(self):
        if self.closed or self.failed.is_set():
            return False
        if self.request_active():
            self.fail('web_fixed_tunnel_active_disconnect_no_retry')
            return False
        self.observed_ready = False
        self.blocked_poll = max(self.blocked_poll, self.last_poll)
        if not self.reconnecting:
            self.reconnecting = True
            self.interruptions += 1
            self._reconnect_timer = asyncio.get_running_loop().call_later(IDLE_TIMEOUT,
                self.fail, 'web_fixed_tunnel_idle_timeout_no_retry')
        return True

    async def collect(self, stream):
        try:
            while line := await stream.readline():
                require(len(line) <= 65536, 'web_fixed_tunnel_output_bound')
                # Discard all raw logs: they can contain user-controlled RPC data.
                # Only fixed poll failure fields affect our lifecycle.
                try:
                    value = loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                if value.get('msg') in ('poll failed; backing off', 'poll timed out; backing off'):
                    if value.get('status_code') in (401, 403):
                        self.fail('web_fixed_tunnel_authorization_required')
                    else:
                        self.pause_idle_connection()
                elif value.get('level') == 'ERROR' and self.request_active():
                    self.fail('web_fixed_tunnel_active_error_no_retry')
        except asyncio.CancelledError:
            raise
        except Exception:
            self.fail('web_fixed_tunnel_output_rejected_no_retry')

    async def local_get(self, client, path, bound):
        async with client.get(self.health_url + path, allow_redirects=False) as response:
            raw = await response.content.read(bound + 1)
            require(len(raw) <= bound, 'web_fixed_tunnel_health_bound')
            return response.status, raw

    async def monitor(self):
        try:
            async with ClientSession(timeout=ClientTimeout(total=2), trust_env=False) as client:
                while not self.closed and not self.failed.is_set():
                    if self.health_url is None and self.health_file.exists():
                        value = regular_bytes(self.health_file, 128).decode('ascii').strip()
                        require(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', value),
                            'web_fixed_tunnel_health_url_invalid')
                        self.health_url = value
                    good = False
                    if self.health_url is not None:
                        try:
                            status, body = await self.local_get(client, '/readyz', 4096)
                            metric_status, metrics = await self.local_get(client, '/metrics', 262144)
                            stamp = poll_timestamp(metrics) if metric_status == 200 else 0
                            now = time.time()
                            good = (status == 200 and body == b'ready' and stamp > self.blocked_poll
                                and max(self.start_time - 1, now - POLL_FRESH_SECONDS) <= stamp <= now + 2)
                            if good:
                                self.last_poll = stamp
                        except (OSError, ClientError, asyncio.TimeoutError):
                            good = False
                    if good:
                        self.observed_ready = True
                        self.observed_at = time.monotonic()
                        if self.reconnecting:
                            self.reconnecting = False
                            self.recoveries += 1
                            self._reconnect_timer.cancel()
                            self._reconnect_timer = None
                        self.announced.set()
                    elif self.observed_ready:
                        self.pause_idle_connection()
                    await asyncio.sleep(HEALTH_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.fail('web_fixed_tunnel_health_rejected_no_retry')

    async def start(self):
        require(not self.started and not self.closed, 'web_connection_already_started_or_closed')
        self.started = True
        try:
            require(hashlib.sha256(self.executable.read_bytes()).digest() == self.digest,
                'web_tunnel_executable_changed')
            require(hashlib.sha256(regular_bytes(self.key_file, 4096)).digest() == self.key_digest,
                'web_fixed_tunnel_key_changed')
            require(self.read_binding() == self.binding_snapshot, 'web_fixed_tunnel_saved_binding_changed')
            # A stale marker after a crash requires an explicit process review.
            # Never infer that an old poller is dead or start a competing runtime.
            try:
                self.lock_bytes = publish_new(self.lock_path,
                    {'version': 1, 'instance': self.id, 'pid': os.getpid(), 'state': str(self.directory)})
            except FileExistsError:
                require(False, 'web_fixed_tunnel_profile_already_active')
            self.endpoint.unsupported_oauth_metadata = True
            await self.endpoint.start()
            profile = self.directory / 'openai-tunnel.yaml'
            publish_new(profile, self.profile())  # JSON is a strict YAML subset.
            self.start_time = time.time()
            self.child = await asyncio.create_subprocess_exec(str(self.executable), 'run',
                '--profile-file', str(profile), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self.directory, env=tunnel_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, limit=65537)
            self.tasks = [asyncio.create_task(self.collect(self.child.stdout)),
                asyncio.create_task(self.collect(self.child.stderr)), asyncio.create_task(self.watch()),
                asyncio.create_task(self.monitor())]
            await asyncio.wait_for(self.announced.wait(), START_TIMEOUT)
            require(self.connected, self.failure or 'web_fixed_tunnel_not_connected')
        except BaseException:
            await self.close()
            raise

    async def _close(self):
        try:
            await super()._close()
        finally:
            if self.lock_bytes is not None and (self.child is None or self.child.returncode is not None):
                require(regular_bytes(self.lock_path, 4096) == self.lock_bytes,
                    'web_fixed_tunnel_ownership_changed')
                self.lock_path.unlink()
                self.lock_bytes = None
