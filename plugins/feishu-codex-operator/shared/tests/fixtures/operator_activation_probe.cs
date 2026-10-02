// One owner-requested ordinary Windows app activation; no model request or settings change.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class OperatorActivationProbe
{
    [ComImport, Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IApplicationActivationManager
    {
        [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string app,
            [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
        [PreserveSig] int ActivateForFile([MarshalAs(UnmanagedType.LPWStr)] string app,
            IntPtr items, [MarshalAs(UnmanagedType.LPWStr)] string verb, out uint processId);
        [PreserveSig] int ActivateForProtocol([MarshalAs(UnmanagedType.LPWStr)] string app,
            IntPtr items, out uint processId);
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 1 || !Path.IsPathRooted(args[0]) || File.Exists(args[0])) return 2;
        using (FileStream stream = new FileStream(args[0], FileMode.CreateNew, FileAccess.Write, FileShare.None))
        using (StreamWriter output = new StreamWriter(stream, new UTF8Encoding(false)))
        {
            object manager = Activator.CreateInstance(Type.GetTypeFromCLSID(
                new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
            try
            {
                uint pid;
                int result = ((IApplicationActivationManager)manager).ActivateApplication(
                    "OpenAI.Codex_2p2nqsd0c76g0!App", null, 0, out pid);
                output.WriteLine("{\"contract\":\"ordinary_activation_probe_v1\",\"hresult\":" +
                    result + ",\"pid\":" + pid + "}");
                return result < 0 ? 1 : 0;
            }
            finally { Marshal.ReleaseComObject(manager); }
        }
    }
}
