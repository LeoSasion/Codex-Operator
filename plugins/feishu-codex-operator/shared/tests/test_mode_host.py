"""Kernel image identity is available before a child's module loader runs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_mode_entry import mode


@unittest.skipUnless(os.name == 'nt', 'Windows kernel process metadata required')
class ModeHostTests(unittest.TestCase):
    def test_picker_projects_only_bound_fixed_failure_reasons_without_opening_a_window(self):
        generic = '启动未完成，检查记录已保留。请关闭此窗口后检查。'
        package = '官方应用版本或安装身份已变化；原配置保留，请检查升级记录。'
        process = '无法确认原拓展进程状态；检查记录已保留，请先核对原实例。'
        uncertain = '启动或窗口派发未确认；原记录已保留，本次不会自动重试。'

        def failure(reason, **changes):
            value = {'contract': mode.CONTRACT, 'phase': 'failed', 'reason': reason,
                     'native_config_writes': 0, 'automatically_retried': False}
            value.update(changes)
            return json.dumps(value)

        def case(output='', error='', exit_code=1, overflow=False,
                 expected_reason='mode_picker_dispatch_failed', expected_status=generic):
            return {'output': output, 'error': error, 'exit_code': exit_code, 'overflow': overflow,
                    'expected_reason': expected_reason, 'expected_status': expected_status}

        cases = [
            case(failure('official_package_changed'), 'mode_extension_launch_incomplete\r\n',
                 expected_reason='official_package_changed', expected_status=package),
            case(failure('web_manager_process_observation_unavailable'),
                 expected_reason='web_manager_process_observation_unavailable', expected_status=process),
            case(failure('previous_launch_running_or_uncertain'),
                 expected_reason='previous_launch_running_or_uncertain', expected_status=uncertain),
            case(failure('existing_window_activation_dispatch_failed'),
                 expected_reason='existing_window_activation_dispatch_failed', expected_status=uncertain),
            case(failure('mode_launch_observation_timeout'),
                 expected_reason='mode_launch_observation_timeout', expected_status=uncertain),
            case(error='mode_official_package_changed\r\n',
                 expected_reason='mode_official_package_changed', expected_status=package),
            case(error='mode_package_ambiguous\n',
                 expected_reason='mode_package_ambiguous', expected_status=package),
            case(error='mode_package_changed', expected_reason='mode_package_changed', expected_status=package),
            case(failure('unregistered_reason_with_private_data')),
            case(failure('official_package_changed', contract='other_contract')),
            case(failure('official_package_changed', phase='window_bound')),
            case(failure('official_package_changed', native_config_writes=1)),
            case(failure('official_package_changed', native_config_writes=False)),
            case(failure('official_package_changed', automatically_retried=True)),
            case(failure('official_package_changed', automatically_retried=0)),
            case(failure('official_package_changed', private_detail='fixture-secret-do-not-display')),
            case(failure('official_package_changed'), exit_code=0),
            case(failure('official_package_changed'), overflow=True),
            case(failure('official_package_changed') + ' ' * 65536),
            case(failure('official_package_changed'), error='x' * 4097),
            case(failure('official_package_changed').replace('"reason":', '"phase": "failed", "reason":')),
            case(failure('official_package_changed').replace('"contract":', '"con\\u0074ract":')),
            case(failure('official_package_changed') + failure('official_package_changed')),
            case('not-json', 'mode_package_changed\n'),
            case(error='mode_package_changed\nmode_package_changed\n'),
            case(error='exception: mode_package_changed; fixture-secret-do-not-display'),
            case(error='web_manager_process_observation_unavailable\n'),
            case(error='mode_unregistered_fixed_reason\n'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            mode.compile_host(root)
            fixture = root / 'cases.json'
            fixture.write_text(json.dumps(cases), encoding='utf-8')
            source = root / 'diagnostic-probe.cs'
            source.write_text(r'''
using System; using System.Collections; using System.Collections.Generic; using System.IO;
using System.Reflection; using System.Text; using System.Web.Script.Serialization;
internal static class Probe {
    private static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false, true);
        Type picker = Assembly.LoadFrom(args[0]).GetType("OperatorModePicker");
        MethodInfo parse = picker.GetMethod("FixedFailureReason", BindingFlags.NonPublic | BindingFlags.Static);
        MethodInfo status = picker.GetMethod("FailureStatus", BindingFlags.NonPublic | BindingFlags.Static);
        var serializer = new JavaScriptSerializer();
        object[] cases = serializer.Deserialize<object[]>(File.ReadAllText(args[1], new UTF8Encoding(false, true)));
        var observed = new List<object>();
        foreach (Dictionary<string, object> item in cases) {
            string reason = (string)parse.Invoke(null, new object[] {
                item["output"], item["error"], item["exit_code"], item["overflow"] });
            observed.Add(new { reason = reason, status = (string)status.Invoke(null, new object[] { reason }) });
        }
        Console.WriteLine(serializer.Serialize(observed));
        return 0; // Only static parser/projection methods were called; no Form was constructed.
    }
}
''', encoding='utf-8')
            compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            executable = root / 'diagnostic-probe.exe'
            built = subprocess.run([str(compiler), '/nologo', '/target:exe', '/r:System.Web.Extensions.dll',
                                    '/out:' + str(executable), str(source)], capture_output=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(built.returncode, 0, built.stderr.decode(errors='replace'))
            observed = subprocess.run([str(executable), str(root / 'operator-mode-picker.exe'), str(fixture)],
                                      capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(observed.returncode, 0, observed.stderr.decode(errors='replace'))
            self.assertNotIn(b'fixture-secret-do-not-display', observed.stdout)
            values = json.loads(observed.stdout)
            self.assertEqual(len(values), len(cases))
            for index, (value, expected) in enumerate(zip(values, cases)):
                with self.subTest(case=index):
                    self.assertEqual(value, {'reason': expected['expected_reason'], 'status': expected['expected_status']})

    def test_suspended_private_child_has_an_image_without_a_ready_main_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            mode.compile_host(root)
            source = root / 'probe.cs'
            source.write_text(r'''
using System;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
internal static class Probe {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct Startup {
        public int size; public string reserved, desktop, title;
        public int x,y,cx,cy,xchars,ychars,fill,flags;
        public short show,reservedSize; public IntPtr reservedData,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct Child { public IntPtr process,thread; public int pid,tid; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool CreateProcess(string app, StringBuilder command,
        IntPtr processAttrs, IntPtr threadAttrs, bool inherit, uint flags,
        IntPtr environment, string directory, ref Startup startup, out Child child);
    [DllImport("kernel32.dll")] private static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    private static int Main(string[] args) {
        string self=Assembly.GetExecutingAssembly().Location;
        Startup startup=new Startup { size=Marshal.SizeOf(typeof(Startup)) };
        Child child;
        if(!CreateProcess(self,new StringBuilder("\""+self+"\""),IntPtr.Zero,IntPtr.Zero,
            false,0x4|0x08000000,IntPtr.Zero,null,ref startup,out child)) return 2;
        bool matches=false, moduleUnavailable=false, stopped=false;
        try {
            using(Process process=Process.GetProcessById(child.pid)) {
                try { moduleUnavailable=process.MainModule==null; }
                catch(System.ComponentModel.Win32Exception) { moduleUnavailable=true; }
                MethodInfo method=Assembly.LoadFrom(args[0]).GetType("OperatorModeHost")
                    .GetMethod("ProcessExecutable",BindingFlags.NonPublic|BindingFlags.Static);
                string image=(string)method.Invoke(null,new object[] { process });
                matches=String.Equals(image,self,StringComparison.OrdinalIgnoreCase);
            }
        } finally {
            // This test owns the still-suspended private fixture, never Desktop.
            stopped=TerminateProcess(child.process,0) && WaitForSingleObject(child.process,5000)==0;
            CloseHandle(child.thread); CloseHandle(child.process);
        }
        Console.WriteLine("{\"image_matches\":"+matches.ToString().ToLowerInvariant()+
            ",\"main_module_unavailable\":"+moduleUnavailable.ToString().ToLowerInvariant()+
            ",\"private_child_stopped\":"+stopped.ToString().ToLowerInvariant()+"}");
        return matches && moduleUnavailable && stopped ? 0 : 3;
    }
}
''', encoding='utf-8')
            compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            executable = root / 'probe.exe'
            built = subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(executable),
                                    str(source)], capture_output=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(built.returncode, 0, built.stderr.decode(errors='replace'))
            observed = subprocess.run([str(executable), str(root / 'operator-mode-host.exe')],
                                      capture_output=True, timeout=20,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(observed.returncode, 0, observed.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(observed.stdout), {'image_matches': True,
                'main_module_unavailable': True, 'private_child_stopped': True})
