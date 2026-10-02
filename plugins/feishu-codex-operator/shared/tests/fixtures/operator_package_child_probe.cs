// Request-free diagnostic for a package-context child process. Never starts Codex.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

internal static class OperatorPackageChildProbe
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(ref int length, StringBuilder name);

    private static string PackageIdentity()
    {
        int length = 0;
        if (GetCurrentPackageFullName(ref length, null) != 122 || length < 1 || length > 1024)
            return null;
        StringBuilder value = new StringBuilder(length);
        return GetCurrentPackageFullName(ref length, value) == 0 ? value.ToString() : null;
    }

    private static void Save(string path, object value)
    {
        using (FileStream file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        using (StreamWriter writer = new StreamWriter(file, new UTF8Encoding(false)))
            writer.WriteLine(new JavaScriptSerializer().Serialize(value));
    }

    [STAThread]
    private static int Main(string[] arguments)
    {
        if (arguments.Length != 3 || (arguments[0] != "--parent" && arguments[0] != "--child"))
            return 2;
        string root = Path.GetFullPath(arguments[1]);
        if (!Path.IsPathRooted(arguments[1]) || !Directory.Exists(root) ||
            (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0 ||
            !arguments[2].StartsWith("OpenAI.Codex_", StringComparison.Ordinal)) return 2;
        string identity = PackageIdentity();
        if (arguments[0] == "--child") {
            bool matches = Environment.GetEnvironmentVariable("CODEX_HOME") == Path.Combine(root, "home") &&
                Environment.GetEnvironmentVariable("CODEX_ELECTRON_USER_DATA_PATH") == Path.Combine(root, "user-data");
            Save(Path.Combine(root, "child.json"), new {
                package_identity = identity, environment_matches = matches,
                model_requests = 0, task_operations = 0, native_config_writes = 0
            });
            return identity == arguments[2] && matches ? 0 : 3;
        }
        if (identity != arguments[2]) {
            Save(Path.Combine(root, "parent.json"), new { package_identity = identity, child_started = false });
            return 3;
        }
        ProcessStartInfo start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location);
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.Arguments = "--child \"" + root + "\" \"" + arguments[2] + "\"";
        start.EnvironmentVariables["CODEX_HOME"] = Path.Combine(root, "home");
        start.EnvironmentVariables["CODEX_ELECTRON_USER_DATA_PATH"] = Path.Combine(root, "user-data");
        using (Process child = Process.Start(start)) {
            bool exited = child.WaitForExit(10000);
            Save(Path.Combine(root, "parent.json"), new {
                package_identity = identity, child_started = true,
                child_exited = exited, child_exit_code = exited ? (int?)child.ExitCode : null,
                model_requests = 0, task_operations = 0, native_config_writes = 0
            });
            return exited && child.ExitCode == 0 ? 0 : 4;
        }
    }
}
