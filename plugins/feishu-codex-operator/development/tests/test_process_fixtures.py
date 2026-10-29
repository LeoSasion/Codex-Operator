"""Real Windows process ownership checks without Codex, accounts or networking."""
import asyncio
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operator_test_fixtures import processes


@unittest.skipUnless(os.name == 'nt', 'Windows disposable process-tree ownership')
class ProcessFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_exited_root_releases_suspended_descendant_pipes_without_touching_other_process(self):
        # Deliberately reproduce the upstream failure: a root exits with a
        # suspended descendant holding both output handles. No sleep-based race.
        source = '''import subprocess,sys
child=subprocess.Popen([sys.executable,"-c","raise SystemExit(99)"],
    stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr,creationflags=0x08000004)
print(child.pid,flush=True)
sys.stdin.readline()
sys.stdout.buffer.write(b"A"*100000);sys.stdout.flush()
sys.stderr.buffer.write(b"B"*100000);sys.stderr.flush()
raise SystemExit(1)
'''
        other = subprocess.Popen([sys._base_executable, '-c', 'import time;time.sleep(60)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            async with processes.isolated_cli_process(sys._base_executable, '-c', source,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE) as child:
                pid = int(await asyncio.wait_for(child.stdout.readline(), 5))
                handle = kernel.OpenProcess(0x100000, False, pid)
                self.assertTrue(handle)
                self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
                stdout, stderr = await asyncio.wait_for(child.communicate(b'go\n'), 5)
                self.assertEqual((stdout, stderr), (b'A' * 100000, b'B' * 100000))
                self.assertEqual(child.returncode, 1)
                self.assertTrue(child.stdout.at_eof() and child.stderr.at_eof())
                self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0)
                self.assertIsNone(other.poll())
        finally:
            if handle:
                kernel.CloseHandle(handle)
            other.kill()
            other.wait(timeout=5)

    async def test_cancelled_fixture_still_fails_and_reaps_its_root(self):
        children = []

        async def interrupted():
            async with processes.isolated_cli_process(sys._base_executable, '-c',
                    'import time;print("ready",flush=True);time.sleep(60)',
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) as child:
                children.append(child)
                self.assertEqual(await asyncio.wait_for(child.stdout.readline(), 5), b'ready\r\n')
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await interrupted()
        self.assertIsNotNone(children[0].returncode)
        self.assertFalse([task for task in asyncio.all_tasks() if task is not asyncio.current_task()])

    async def test_assignment_failure_never_runs_or_retries_the_suspended_child(self):
        await self.check_failed_launch('assign')

    async def test_resume_failure_never_runs_or_retries_the_suspended_child(self):
        await self.check_failed_launch('resume')

    async def check_failed_launch(self, stage):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'must-not-run'
            children = []

            def reject(job, child):
                children.append(child)
                raise OSError('synthetic_' + stage + '_failure')

            with patch.object(processes.WindowsJob, stage, reject):
                with self.assertRaisesRegex(OSError, 'synthetic_' + stage + '_failure'):
                    async with processes.isolated_cli_process(sys._base_executable, '-c',
                            'from pathlib import Path;import sys;Path(sys.argv[1]).write_text("ran")', str(marker),
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE):
                        self.fail('failed launch was released')
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
            self.assertFalse(marker.exists())
            self.assertFalse([task for task in asyncio.all_tasks() if task is not asyncio.current_task()])


if __name__ == '__main__':
    unittest.main()
