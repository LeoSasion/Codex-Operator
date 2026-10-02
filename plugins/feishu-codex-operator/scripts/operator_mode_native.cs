// Ordinary registered Windows activation. No profile, environment or config override.
using System;
using System.Runtime.InteropServices;

internal static class OperatorModeNative
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
        if (args.Length != 1 || args[0] != "OpenAI.Codex_2p2nqsd0c76g0!App") return 2;
        object manager = null;
        try
        {
            manager = Activator.CreateInstance(Type.GetTypeFromCLSID(
                new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
            uint pid;
            int result = ((IApplicationActivationManager)manager).ActivateApplication(args[0], null, 0, out pid);
            return result >= 0 && pid != 0 ? 0 : 1;
        }
        catch { return 1; }
        finally { if (manager != null) Marshal.ReleaseComObject(manager); }
    }
}
