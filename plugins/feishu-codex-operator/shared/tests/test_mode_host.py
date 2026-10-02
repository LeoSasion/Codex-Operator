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
