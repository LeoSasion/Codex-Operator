"""Explicit development MCP connection, owned by one bounded Web service.

Only the MCP listener is exposed. Native Responses credentials never enter the
tunnel. A fresh address requires an explicit connector binding; no registration,
authorization, service installation or request replay is performed. An explicit
idle_v1 policy may retain the same child/address through an idle transport loss.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess

from .web_browser_driver import child_environment
from .web_mcp_transport import QuickTunnelAnnouncement, require

IDLE_RECONNECT_SECONDS = 60


def idle_disconnect_report(text):
    # Dated cloudflared 2026.9.1 HTTP/2 control/supervisor reports. Unknown
    # errors remain terminal; a request/proxy error is not a reconnect signal.
    return bool(re.fullmatch(r'\S+ (?:ERR (?:failed to serve incoming request|Serve tunnel error|Connection terminated) '
        r'error="(?:Error shutting down control stream: (?:client disconnected|context canceled)|connection with edge closed)"'
        r'(?: connIndex=0)?(?: event=0)?(?: ip=[0-9a-fA-F:.]+)?'
        r'|INF (?:Unregistered tunnel connection|Lost connection with the edge|Retrying connection in up to [0-9.ms]+)'
        r'(?: connIndex=0)?(?: event=0)?(?: ip=[0-9a-fA-F:.]+)?)', text))


class WebMcpConnection:
    def __init__(self, settings, endpoint, state):
        require(isinstance(settings, dict) and 'cloudflared' in settings
            and set(settings) <= {'cloudflared', 'reconnect_policy'},
            'web_connection_settings_invalid')
        self.reconnect_policy = settings.get('reconnect_policy', 'never')
        require(self.reconnect_policy in ('never', 'idle_v1'), 'web_connection_reconnect_policy_invalid')
        value = settings['cloudflared']
        require(isinstance(value, str), 'web_tunnel_executable_required')
        self.executable = Path(value)
        require(self.executable.is_absolute() and self.executable.is_file()
            and not self.executable.is_symlink(), 'web_tunnel_executable_required')
        self.digest = hashlib.sha256(self.executable.read_bytes()).digest()
        self.endpoint, self.directory = endpoint, Path(state)
        self.id = secrets.token_hex(16)
        self.child = None
        self.tasks = []
        self.announcement = QuickTunnelAnnouncement()
        self.announced = asyncio.Event()
        self.failed = asyncio.Event()
        self.failure = None
        self.closed = False
        self.started = False
        self.connector = None
        self._close_task = None
        self.reconnecting = False
        self.interruptions = self.recoveries = 0
        self._reconnect_timer = None
        self.request_active = lambda: self.endpoint.turn is not None

    @property
    def connected(self):
        return (not self.closed and not self.failed.is_set() and self.announcement.connected
            and self.child is not None and self.child.returncode is None)

    @property
    def ready(self):
        return self.connected and self.connector is not None

    def status(self):
        return {'mode': 'quick_tunnel_v1',
            'state': 'stopped' if self.closed else 'unavailable' if self.failed.is_set()
                else 'reconnecting' if self.reconnecting
                else 'ready' if self.ready else 'awaiting_connector' if self.connected else 'starting',
            'connected': self.connected, 'connector_bound': self.connector is not None,
            'process_running': self.child is not None and self.child.returncode is None,
            'failure': self.failure, 'restarts': 0, 'reconnect_policy': self.reconnect_policy,
            'idle_interruptions': self.interruptions, 'idle_recoveries': self.recoveries,
            'mcp': self.endpoint.diagnostics()}

    def setup(self):
        require(self.connected, 'web_connection_unavailable')
        return {'version': 1, 'connection_id': self.id,
            'endpoint_url': self.announcement.origin + self.endpoint.path,
            'connector': self.connector, 'kind': 'temporary_development_connection'}

    def bind(self, value):
        require(self.connected and self.connector is None, 'web_connection_bind_unavailable')
        require(isinstance(value, dict) and set(value) == {'connection_id', 'endpoint_url', 'connector'}
            and value['connection_id'] == self.id
            and value['endpoint_url'] == self.announcement.origin + self.endpoint.path,
            'web_connection_binding_changed')
        # Driver validation is shared with independently owned connections.
        from .web_browser_driver import validate_connector
        self.connector = validate_connector(value['connector'])
        return dict(self.connector)

    def fail(self, code):
        if not self.closed and self.failure is None:
            self.failure = code
            self.failed.set()
            self.announced.set()
            if self.child is not None and self.child.returncode is None:
                try:
                    self.child.terminate()
                except ProcessLookupError:
                    pass

    def pause_idle_connection(self):
        if (self.reconnect_policy != 'idle_v1' or self.closed or self.failed.is_set()
                or not self.announcement.origin or not (self.connected or self.reconnecting)
                or self.request_active()):
            return False
        if not self.reconnecting:
            self.announcement.connected = False
            self.reconnecting = True
            self.interruptions += 1
            self._reconnect_timer = asyncio.get_running_loop().call_later(IDLE_RECONNECT_SECONDS,
                self.fail, 'web_tunnel_idle_reconnect_timeout_no_retry')
        return True

    async def collect(self, stream):
        total = 0
        try:
            while line := await stream.readline():
                total += len(line)
                require(len(line) <= 16384 and total <= 2 * 1024 * 1024,
                    'web_tunnel_output_bound')
                text = line.decode('utf-8', errors='strict').strip()
                # Normal logs are discarded. Preserve only the first bounded
                # failure in the private service directory for diagnosis; raw
                # text and private URLs never enter status or HTTP errors.
                interrupted = idle_disconnect_report(text)
                if interrupted and self.pause_idle_connection():
                    if self.interruptions == 1 and not (self.directory / 'tunnel.interruption.txt').exists():
                        with (self.directory / 'tunnel.interruption.txt').open('xb') as interruption:
                            interruption.write(line)
                    continue
                # Active/unknown failures remain terminal even under idle_v1.
                if interrupted or ' ERR ' in text or 'Unregistered tunnel connection' in text:
                    if not self.closed and self.failure is None:
                        with (self.directory / 'tunnel.failure.txt').open('xb') as failure:
                            failure.write(line)
                    self.fail('web_tunnel_connection_failed_no_retry')
                    return
                if self.announcement.feed(text):
                    if self.reconnecting:
                        require(re.search(r' INF Registered tunnel connection connIndex=0 ', text)
                            and not self.request_active(), 'web_tunnel_idle_reconnect_invalid')
                        self.reconnecting = False
                        self.recoveries += 1
                        self._reconnect_timer.cancel()
                        self._reconnect_timer = None
                    self.announced.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.fail('web_tunnel_output_rejected_no_retry')

    async def watch(self):
        await self.child.wait()
        self.fail('web_tunnel_exited_no_retry')

    async def start(self):
        require(not self.started and not self.closed, 'web_connection_already_started_or_closed')
        self.started = True
        try:
            require(hashlib.sha256(self.executable.read_bytes()).digest() == self.digest,
                'web_tunnel_executable_changed')
            await self.endpoint.start()
            config = self.directory / 'tunnel.yml'
            with config.open('x', encoding='utf-8') as stream:
                stream.write('no-autoupdate: true\n')
            env = {k: v for k, v in child_environment().items()
                if not k.upper().startswith(('TUNNEL_', 'CLOUDFLARED_', 'CF_'))}
            self.child = await asyncio.create_subprocess_exec(str(self.executable),
                'tunnel', '--config', str(config), '--no-autoupdate',
                '--url', 'http://' + self.endpoint.host, '--http-host-header', self.endpoint.host,
                '--protocol', 'http2', '--retries', '5' if self.reconnect_policy == 'idle_v1' else '0',
                '--ha-connections', '1',
                '--metrics', '127.0.0.1:0', '--loglevel', 'info',
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, cwd=self.directory,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                limit=16385)
            self.tasks = [asyncio.create_task(self.collect(self.child.stdout)),
                asyncio.create_task(self.collect(self.child.stderr)), asyncio.create_task(self.watch())]
            await asyncio.wait_for(self.announced.wait(), 55)
            require(self.connected, self.failure or 'web_tunnel_not_connected')
        except BaseException:
            await self.close()
            raise

    async def close(self):
        if self._close_task is None:
            self.closed = True
            self._close_task = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise

    async def _close(self):
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            self._reconnect_timer = None
        try:
            if self.child is not None and self.child.returncode is None:
                self.child.terminate()
                try:
                    await asyncio.wait_for(self.child.wait(), 5)
                except asyncio.TimeoutError:
                    self.child.kill()
                    await asyncio.wait_for(self.child.wait(), 5)
        finally:
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.endpoint.stop()
