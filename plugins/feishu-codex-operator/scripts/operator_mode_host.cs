// Package-context bootstrap for one explicitly isolated Desktop launch.
// It never writes the default home, edits the official application, sends a
// model request, or terminates a Desktop process.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Codex-Operator isolated launch host")]
[assembly: AssemblyProduct("Codex-Operator")]

internal static class OperatorModeHost
{
    private const string Contract = "operator_isolated_mode_host_v1";
    private static readonly Guid AppProperties = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
    private static readonly Guid PropertyStoreId = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
    private delegate bool EnumWindow(IntPtr window, IntPtr value);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(ref int length, StringBuilder name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetPackageFullName(IntPtr process, ref int length, StringBuilder name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageName(IntPtr process, uint flags,
        StringBuilder name, ref int length);
    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindow callback, IntPtr value);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr window, int command);
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr window, StringBuilder value, int maximum);
    [DllImport("shell32.dll")]
    private static extern int SHGetPropertyStoreForWindow(IntPtr window, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PropVariant value);

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey { public Guid format; public uint id; }
    [StructLayout(LayoutKind.Explicit, Size = 24)]
    private struct PropVariant {
        [FieldOffset(0)] public ushort type;
        [FieldOffset(8)] public IntPtr pointer;
        [FieldOffset(8)] public short boolean;
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }

    private static void Require(bool condition, string reason) {
        if (!condition) throw new InvalidOperationException(reason);
    }
    private static string Hash(string path, long limit) {
        CheckPath(path, false);
        using (FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            Require(file.Length <= limit, "mode_file_bound");
            using (SHA256 sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
        }
    }
    private static void CheckPath(string path, bool directory) {
        Require(Path.IsPathRooted(path) && path == Path.GetFullPath(path) &&
            path.IndexOf('"') < 0 && path.IndexOf('\r') < 0 && path.IndexOf('\n') < 0,
            "mode_absolute_path_required");
        string cursor = path;
        while (!String.IsNullOrEmpty(cursor)) {
            if (File.Exists(cursor) || Directory.Exists(cursor))
                Require((File.GetAttributes(cursor) & FileAttributes.ReparsePoint) == 0, "mode_linked_path");
            cursor = Path.GetDirectoryName(cursor);
        }
        Require(directory ? Directory.Exists(path) : File.Exists(path), "mode_path_unavailable");
    }
    private static string Value(Dictionary<string, object> plan, string key) {
        Require(plan.ContainsKey(key) && plan[key] is string && ((string)plan[key]).Length > 0,
            "mode_plan_invalid");
        return (string)plan[key];
    }
    private static string PackageIdentity(IntPtr? process) {
        int length = 0;
        int result = process.HasValue ? GetPackageFullName(process.Value, ref length, null) :
            GetCurrentPackageFullName(ref length, null);
        if (result != 122 || length < 1 || length > 1024) return null;
        StringBuilder name = new StringBuilder(length);
        result = process.HasValue ? GetPackageFullName(process.Value, ref length, name) :
            GetCurrentPackageFullName(ref length, name);
        return result == 0 ? name.ToString() : null;
    }
    private static string ProcessExecutable(Process process) {
        Require(!process.HasExited, "mode_desktop_identity_changed");
        StringBuilder name = new StringBuilder(32768);
        int length = name.Capacity;
        // MainModule may still be null just after Process.Start. Query the
        // kernel's image identity without reading the child's module loader.
        Require(QueryFullProcessImageName(process.Handle, 0, name, ref length) &&
            length > 0 && length < name.Capacity, "mode_process_image_unavailable");
        return name.ToString();
    }
    private static void Save(string path, object value) {
        using (FileStream file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        using (StreamWriter writer = new StreamWriter(file, new UTF8Encoding(false)))
            writer.WriteLine(new JavaScriptSerializer().Serialize(value));
    }
    private static void SetWindowIdentity(IntPtr window, string appId) {
        IPropertyStore store;
        Guid iid = PropertyStoreId;
        Marshal.ThrowExceptionForHR(SHGetPropertyStoreForWindow(window, ref iid, out store));
        try {
            PropertyKey key = new PropertyKey { format = AppProperties, id = 5 };
            PropVariant value = new PropVariant { type = 31, pointer = Marshal.StringToCoTaskMemUni(appId) };
            try { Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value)); }
            finally { PropVariantClear(ref value); }
            // Pin the explicit Operator entry, not an ambiguous official EXE.
            PropertyKey noPin = new PropertyKey { format = AppProperties, id = 9 };
            PropVariant pinValue = new PropVariant { type = 11, boolean = -1 };
            Marshal.ThrowExceptionForHR(store.SetValue(ref noPin, ref pinValue));
            Marshal.ThrowExceptionForHR(store.Commit());
            PropVariant observed;
            Marshal.ThrowExceptionForHR(store.GetValue(ref key, out observed));
            try {
                Require(observed.type == 31 && Marshal.PtrToStringUni(observed.pointer) == appId,
                    "mode_window_identity_unverified");
            } finally { PropVariantClear(ref observed); }
        } finally { Marshal.ReleaseComObject(store); }
    }
    private static int BindWindows(Process desktop, string appId) {
        int count = 0;
        Exception failed = null;
        EnumWindow visitor = delegate(IntPtr window, IntPtr ignored) {
            uint pid;
            GetWindowThreadProcessId(window, out pid);
            if (pid != (uint)desktop.Id || !IsWindowVisible(window)) return true;
            StringBuilder className = new StringBuilder(128);
            GetClassName(window, className, className.Capacity);
            if (!className.ToString().StartsWith("Chrome_WidgetWin_", StringComparison.Ordinal)) return true;
            try { SetWindowIdentity(window, appId); count++; }
            catch (Exception error) { failed = error; return false; }
            return true;
        };
        EnumWindows(visitor, IntPtr.Zero);
        if (failed != null) throw failed;
        return count;
    }

    private static bool HasWindowIdentity(IntPtr window, string appId) {
        IPropertyStore store;
        Guid iid = PropertyStoreId;
        Marshal.ThrowExceptionForHR(SHGetPropertyStoreForWindow(window, ref iid, out store));
        try {
            PropertyKey key = new PropertyKey { format = AppProperties, id = 5 };
            PropVariant value;
            Marshal.ThrowExceptionForHR(store.GetValue(ref key, out value));
            try { return value.type == 31 && Marshal.PtrToStringUni(value.pointer) == appId; }
            finally { PropVariantClear(ref value); }
        } finally { Marshal.ReleaseComObject(store); }
    }

    private static List<IntPtr> OwnedWindows(Process desktop, string appId) {
        List<IntPtr> windows = new List<IntPtr>();
        EnumWindow visitor = delegate(IntPtr window, IntPtr ignored) {
            uint pid; GetWindowThreadProcessId(window, out pid);
            if (pid == (uint)desktop.Id && IsWindowVisible(window) && HasWindowIdentity(window, appId))
                windows.Add(window);
            return true;
        };
        EnumWindows(visitor, IntPtr.Zero);
        return windows;
    }

    private static ProcessStartInfo DesktopStart(Dictionary<string, object> plan) {
        ProcessStartInfo start = new ProcessStartInfo(Value(plan, "official_executable"));
        start.UseShellExecute = false;
        start.WorkingDirectory = Value(plan, "root");
        // The native Owl/Chromium singleton runs before the JS userData override.
        start.Arguments = "--user-data-dir=\"" + Path.Combine(Value(plan, "user_data"), "web", "Codex") + "\"";
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.CreateNoWindow = true;
        List<string> remove = new List<string>();
        foreach (DictionaryEntry item in start.EnvironmentVariables) {
            string key = (string)item.Key;
            if (key.StartsWith("CODEX_", StringComparison.OrdinalIgnoreCase) ||
                key.StartsWith("ELECTRON_", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("NODE_OPTIONS", StringComparison.OrdinalIgnoreCase)) remove.Add(key);
        }
        foreach (string key in remove) start.EnvironmentVariables.Remove(key);
        start.EnvironmentVariables["CODEX_HOME"] = Value(plan, "home");
        start.EnvironmentVariables["CODEX_ELECTRON_USER_DATA_PATH"] = Value(plan, "user_data");
        return start;
    }

    private static int Activate(string root, string attemptId, Dictionary<string, object> plan, string activationId) {
        string directory = Path.Combine(root, "launches", attemptId);
        CheckPath(directory, true);
        Require(!File.Exists(Path.Combine(directory, "desktop-exited.json")) &&
            !File.Exists(Path.Combine(directory, "host-failed.json")) &&
            !File.Exists(Path.Combine(directory, "controller-failed.json")), "mode_previous_launch_uncertain");
        string recordPath = Path.Combine(directory, "desktop-started.json");
        CheckPath(recordPath, false);
        Require(new FileInfo(recordPath).Length <= 65536, "mode_process_record_invalid");
        var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            File.ReadAllText(recordPath, new UTF8Encoding(false, true)));
        var identity = record["process"] as Dictionary<string, object>;
        Require(identity != null && identity["pid"] is int, "mode_process_record_invalid");
        using (Process desktop = Process.GetProcessById((int)identity["pid"])) {
            string executable = ProcessExecutable(desktop);
            Require(!desktop.HasExited && desktop.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture) ==
                Value(identity, "birth") && String.Equals(executable, Value(identity, "executable"),
                StringComparison.OrdinalIgnoreCase) && String.Equals(executable,
                Value(plan, "official_executable"), StringComparison.OrdinalIgnoreCase) &&
                PackageIdentity(desktop.Handle) == Value(plan, "package_full_name"), "mode_desktop_identity_changed");
            string activation = Path.Combine(root, "activations", activationId);
            CheckPath(activation, true);
            string intentPath = Path.Combine(activation, "intent.json");
            CheckPath(intentPath, false);
            Require(new FileInfo(intentPath).Length <= 65536, "mode_activation_invalid");
            var intent = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                File.ReadAllText(intentPath, new UTF8Encoding(false, true)));
            Require((int)intent["original_pid"] == desktop.Id && Value(intent, "attempt") == attemptId &&
                Value(intent, "plan_sha256") == Hash(Path.Combine(root, "host-plan.json"), 65536), "mode_activation_invalid");
            Save(Path.Combine(activation, "host-starting.json"), new { original_pid = desktop.Id,
                started_utc = DateTime.UtcNow.ToString("o") });
            try {
                List<IntPtr> windows = OwnedWindows(desktop, Value(plan, "window_app_id"));
                bool reopened = false;
                if (windows.Count == 0) {
                    Require(PackageIdentity(null) == Value(plan, "package_full_name"), "mode_package_context_required");
                    Require(!desktop.HasExited, "mode_desktop_identity_changed");
                    using (Process forwarder = Process.Start(DesktopStart(plan))) {
                        Save(Path.Combine(activation, "forwarder.json"), new {
                            pid = forwarder.Id, birth_utc = forwarder.StartTime.ToUniversalTime().ToString("o") });
                        Require(forwarder.WaitForExit(15000) && forwarder.ExitCode == 0,
                            "mode_window_reopen_unconfirmed");
                    }
                    DateTime deadline = DateTime.UtcNow.AddSeconds(10);
                    while (!desktop.HasExited && DateTime.UtcNow < deadline) {
                        windows = OwnedWindows(desktop, Value(plan, "window_app_id"));
                        if (windows.Count > 0) break;
                        Thread.Sleep(100);
                    }
                    Require(!desktop.HasExited && windows.Count > 0, "mode_window_reopen_unconfirmed");
                    reopened = true;
                }
                Require(windows.Count > 0, "mode_existing_window_unavailable");
                // A forwarder is never accepted as a replacement Desktop.
                IntPtr selected = windows[0];
                if (IsIconic(selected)) ShowWindowAsync(selected, 9);
                bool activated = SetForegroundWindow(selected) || GetForegroundWindow() == selected;
                // Window readiness and Windows foreground permission are separate.
                // The still-open user-clicked picker performs the final focus.
                Save(Path.Combine(activation, "completed.json"), new {
                    original_pid = desktop.Id, attempt = attemptId, new_desktop_instances = 0, model_requests = 0,
                    reopened_window = reopened, foreground_activated = activated,
                    window_handle = selected.ToInt64().ToString(CultureInfo.InvariantCulture),
                    completed_utc = DateTime.UtcNow.ToString("o") });
                return reopened ? 10 : 0;
            } catch (Exception error) {
                Save(Path.Combine(activation, "failed.json"), new {
                    reason = error is InvalidOperationException && Regex.IsMatch(error.Message, "\\Amode_[a-z_]+\\z")
                        ? error.Message : "mode_window_reopen_unconfirmed", automatically_retried = false });
                throw;
            }
        }
    }

    [STAThread]
    private static int Main(string[] arguments)
    {
        string attempt = null;
        bool launched = false;
        string stage = "plan_validation";
        bool activating = arguments.Length > 0 && arguments[0] == "--activate";
        try {
            Require(arguments.Length == (activating ? 5 : 4) && (arguments[0] == "--launch" || activating) &&
                Regex.IsMatch(arguments[2], "\\A[a-f0-9]{64}\\z") &&
                Regex.IsMatch(arguments[3], "\\A[a-f0-9]{32}\\z") &&
                (!activating || Regex.IsMatch(arguments[4], "\\A[a-f0-9]{32}\\z")), "mode_arguments_invalid");
            string root = Path.GetFullPath(arguments[1]);
            CheckPath(root, true);
            string planPath = Path.Combine(root, "host-plan.json");
            Require(Hash(planPath, 65536) == arguments[2], "mode_plan_changed");
            Dictionary<string, object> plan = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                File.ReadAllText(planPath, new UTF8Encoding(false, true)));
            string[] fields = { "schema_version", "contract", "root", "native_home", "home", "user_data",
                "package_full_name", "official_executable", "official_sha256", "host_sha256",
                "config_sha256", "catalog_sha256", "window_app_id" };
            Require(plan.Count == fields.Length, "mode_plan_invalid");
            foreach (string field in fields) Require(plan.ContainsKey(field), "mode_plan_invalid");
            Require(plan["schema_version"] is int && (int)plan["schema_version"] == 1 &&
                Value(plan, "contract") == Contract && Value(plan, "root") == root, "mode_plan_invalid");
            string home = Value(plan, "home"), userData = Value(plan, "user_data");
            Require(home == Path.Combine(root, "home") && userData == Path.Combine(root, "user-data"),
                "mode_home_scope_invalid");
            CheckPath(home, true); CheckPath(userData, true);
            string nativeHome = Value(plan, "native_home");
            CheckPath(nativeHome, true);
            Require(!root.StartsWith(nativeHome.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) &&
                !nativeHome.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) &&
                !String.Equals(root, nativeHome, StringComparison.OrdinalIgnoreCase), "mode_native_home_rejected");
            Require(Regex.IsMatch(Value(plan, "window_app_id"), "\\ACodexOperator\\.Extension\\.[a-f0-9]{32}\\z"),
                "mode_window_identity_invalid");
            if (!activating)
                Require(PackageIdentity(null) == Value(plan, "package_full_name"), "mode_package_context_required");
            string official = Value(plan, "official_executable");
            Require(String.Equals(Path.GetFileName(official), "ChatGPT.exe", StringComparison.OrdinalIgnoreCase) &&
                Path.GetFileName(Path.GetDirectoryName(Path.GetDirectoryName(official))) == Value(plan, "package_full_name"),
                "mode_official_path_invalid");
            Require(Hash(official, 536870912) == Value(plan, "official_sha256") &&
                Hash(Assembly.GetExecutingAssembly().Location, 4194304) == Value(plan, "host_sha256") &&
                (activating || Hash(Path.Combine(home, "config.toml"), 1048576) == Value(plan, "config_sha256")) &&
                Hash(Path.Combine(home, "models.json"), 1048576) == Value(plan, "catalog_sha256"),
                "mode_dependency_changed");
            if (activating) return Activate(root, arguments[3], plan, arguments[4]);
            attempt = Path.Combine(root, "launches", arguments[3]);
            CheckPath(attempt, true);
            string nativeConfig = Path.Combine(nativeHome, "config.toml");
            string nativeBefore = Hash(nativeConfig, 1048576);
            Save(Path.Combine(attempt, "host-starting.json"), new {
                contract = Contract, plan_sha256 = arguments[2], package_identity = PackageIdentity(null),
                started_utc = DateTime.UtcNow.ToString("o"), native_config_sha256 = nativeBefore
            });
            string browserProfile = Path.Combine(userData, "web", "Codex");
            stage = "desktop_start";
            using (Process desktop = Process.Start(DesktopStart(plan))) {
                launched = true;
                stage = "child_identity";
                string executable = ProcessExecutable(desktop);
                Require(String.Equals(executable, official, StringComparison.OrdinalIgnoreCase),
                    "mode_child_image_mismatch");
                Require(PackageIdentity(desktop.Handle) == Value(plan, "package_full_name"),
                    "mode_child_package_mismatch");
                stage = "desktop_record";
                Save(Path.Combine(attempt, "desktop-started.json"), new {
                    pid = desktop.Id, birth_utc = desktop.StartTime.ToUniversalTime().ToString("o"),
                    process = new { pid = desktop.Id,
                        birth = desktop.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture),
                        executable = executable },
                    package_identity = PackageIdentity(desktop.Handle), home = home, user_data = userData,
                    browser_profile = browserProfile, launch_environment_set = true,
                    desktop_acceptance = "unverified"
                });
                bool windowRecorded = false;
                DateTime deadline = DateTime.UtcNow.AddSeconds(60);
                stage = "window_binding";
                while (!desktop.WaitForExit(windowRecorded ? 1000 : 100)) {
                    int windows = BindWindows(desktop, Value(plan, "window_app_id"));
                    if (windows > 0 && !windowRecorded) {
                        Save(Path.Combine(attempt, "windows-bound.json"), new {
                            pid = desktop.Id, window_count = windows,
                            window_handle = OwnedWindows(desktop, Value(plan, "window_app_id"))[0].ToInt64().ToString(CultureInfo.InvariantCulture),
                            window_app_id = Value(plan, "window_app_id"), pinning_disabled = true,
                            native_config_unchanged = Hash(nativeConfig, 1048576) == nativeBefore,
                            desktop_acceptance = "unverified", model_requests_sent_by_host = 0
                        });
                        windowRecorded = true;
                    }
                    if (!windowRecorded && DateTime.UtcNow >= deadline)
                        throw new InvalidOperationException("mode_window_not_observed");
                }
                stage = "exit_record";
                Save(Path.Combine(attempt, "desktop-exited.json"), new {
                    pid = desktop.Id, exit_code = desktop.ExitCode,
                    observed_utc = DateTime.UtcNow.ToString("o"), window_was_bound = windowRecorded,
                    native_config_unchanged = Hash(nativeConfig, 1048576) == nativeBefore
                });
                return windowRecorded ? 0 : 4;
            }
        } catch (Exception error) {
            string reason = error is InvalidOperationException && Regex.IsMatch(error.Message, "\\Amode_[a-z_]+\\z")
                ? error.Message : "mode_host_failed";
            if (attempt != null && Directory.Exists(attempt)) {
                try { Save(Path.Combine(attempt, "host-failed.json"), new {
                    reason = reason, desktop_launched = launched, hresult = error.HResult, failure_stage = stage,
                    automatically_retried = false, desktop_terminated = false
                }); } catch { }
            }
            if (!activating) MessageBox.Show("拓展启动未完成，检查记录已保留。\n原因：" + reason +
                "\n原生设置未由启动器改写。", "Codex-Operator", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
