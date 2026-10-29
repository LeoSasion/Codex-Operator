"""Process-tree ownership for disposable CLI fixtures, never runtime services."""
import asyncio
from contextlib import asynccontextmanager
import ctypes
from ctypes import wintypes
import os


class WindowsJob:
    """Contain a suspended child before its first instruction; refuse fallback."""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', ctypes.c_ulonglong * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
            'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            'Thread32First': ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
            'Thread32Next': ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
            'OpenThread': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            'GetProcessIdOfThread': ([wintypes.HANDLE], wintypes.DWORD),
            'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway or inherited job handle.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, child):
        # CPython retains this exact process handle until transport cleanup.
        # Never reopen a root by a potentially recycled numeric PID.
        handle = int(child._transport._proc._handle)
        if not self.kernel.AssignProcessToJobObject(self.handle, handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, child):
        class Thread(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                ('id', wintypes.DWORD), ('owner', wintypes.DWORD),
                ('base_priority', wintypes.LONG), ('delta_priority', wintypes.LONG), ('flags', wintypes.DWORD)]

        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        ids = []
        try:
            entry = Thread()
            entry.size = ctypes.sizeof(entry)
            more = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.owner == child.pid:
                    ids.append(entry.id)
                more = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(snapshot)
        if len(ids) != 1:
            raise RuntimeError('fixture_suspended_primary_thread_ambiguous')
        thread = self.kernel.OpenThread(0x0800 | 0x0002, False, ids[0])  # QUERY_LIMITED_INFORMATION | SUSPEND_RESUME
        if not thread:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.kernel.GetProcessIdOfThread(thread) != child.pid:
                raise RuntimeError('fixture_thread_owner_changed')
            if self.kernel.ResumeThread(thread) != 1:
                raise RuntimeError('fixture_initial_suspend_count_changed')
        finally:
            self.kernel.CloseHandle(thread)

    def close(self):
        if self.handle is not None:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


@asynccontextmanager
async def isolated_cli_process(*command, **options):
    """Own this fixture's Windows descendants and still require real pipe EOF.

    Normal root exit ends its disposable background work. It never changes the
    root's exit code or substitutes for output/HTTP/assertion checks. The context
    also closes transports on failure/cancellation; it never retries a launch.
    """
    job = WindowsJob() if os.name == 'nt' else None
    child, watcher = None, None
    try:
        if job is not None:
            options['creationflags'] = options.get('creationflags', 0) | 0x08000004  # NO_WINDOW | SUSPENDED
        child = await asyncio.create_subprocess_exec(*command, **options)
        if job is not None:
            job.assign(child)
            job.resume(child)

            async def close_after_root_exit():
                # child.wait() can wait for inherited output pipes, creating the
                # very cycle this fixture must break. returncode is process-only.
                while child.returncode is None:
                    await asyncio.sleep(0.01)
                job.close()

            watcher = asyncio.create_task(close_after_root_exit())
        yield child
    finally:
        watcher_error = None
        try:
            if job is not None:
                job.close()
        finally:
            if watcher is not None:
                watcher.cancel()
                result = (await asyncio.gather(watcher, return_exceptions=True))[0]
                if isinstance(result, Exception):
                    watcher_error = result
            if child is not None:
                # Output collection has already completed or failed at this point.
                # Closing transport here never manufactures a successful EOF.
                if child.returncode is None:
                    try:
                        child.kill()
                    except ProcessLookupError:
                        pass
                child._transport.close()
                await asyncio.wait_for(child.wait(), 5)
            if watcher_error is not None:
                raise watcher_error
