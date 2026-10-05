// Default/--preview and --select remain side-effect-free mode-choice views.
// --launch dispatches the digest-bound entry and retains the user-clicked window
// until it can focus the exact checked Desktop. It never edits native settings.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Codex-Operator 启动方式")]
[assembly: AssemblyProduct("Codex-Operator")]
[assembly: AssemblyDescription("Native or extension mode selection")]

internal enum OperatorModeChoice
{
    Cancelled = 0,
    Native = 10,
    Extension = 20
}

internal sealed class OperatorModePicker : Form
{
    private readonly bool preview;
    private readonly Button nativeButton;
    private readonly Button extensionButton;
    private readonly Label status;
    private readonly string entryRoot;
    private readonly string entryDigest;
    private Dictionary<string, object> readyWindow;
    private bool preparing;
    internal OperatorModeChoice Choice { get; private set; }

    internal OperatorModePicker(bool previewOnly, string root = null, string digest = null)
    {
        preview = previewOnly;
        entryRoot = root;
        entryDigest = digest;
        Choice = OperatorModeChoice.Cancelled;
        Text = preview ? "Codex-Operator 启动方式预览" : "Codex-Operator";
        ClientSize = new Size(516, 282);
        AutoScaleDimensions = new SizeF(96F, 96F);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(247, 248, 250);
        Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ShowInTaskbar = true;
        KeyPreview = true;
        AccessibleName = Text;

        Label brand = MakeLabel("Codex-Operator", 28, 20, 460, 23, 10F,
            FontStyle.Bold, Color.FromArgb(95, 107, 121));
        Label title = MakeLabel("选择启动方式", 27, 49, 460, 35, 18F,
            FontStyle.Bold, Color.FromArgb(26, 36, 49));
        nativeButton = MakeButton("原生", 28, false);
        nativeButton.TabIndex = 0;
        extensionButton = MakeButton("拓展", 266, true);
        extensionButton.TabIndex = 1;
        nativeButton.Click += delegate { SelectMode(OperatorModeChoice.Native); };
        extensionButton.Click += delegate { SelectMode(OperatorModeChoice.Extension); };

        Label nativeDescription = MakeLabel("原生设置 · 官方直连", 28, 173, 222, 27,
            9.5F, FontStyle.Regular, Color.FromArgb(89, 99, 113));
        nativeDescription.TextAlign = ContentAlignment.MiddleCenter;
        Label extensionDescription = MakeLabel("统一路由 · 多模型切换", 266, 173, 222, 27,
            9.5F, FontStyle.Regular, Color.FromArgb(89, 99, 113));
        extensionDescription.TextAlign = ContentAlignment.MiddleCenter;
        Panel divider = new Panel();
        divider.SetBounds(28, 216, 460, 1);
        divider.BackColor = Color.FromArgb(222, 226, 232);
        status = MakeLabel(preview ? "界面预览 · 具体模型在 Codex 内选择" :
            "具体模型在 Codex 内选择", 28, 230, 460, 38, 9F,
            FontStyle.Regular, Color.FromArgb(95, 107, 121));
        status.AccessibleName = "启动状态";

        Controls.AddRange(new Control[] { brand, title, nativeButton, extensionButton,
            nativeDescription, extensionDescription, divider, status });
        KeyDown += delegate(object sender, KeyEventArgs args) {
            if (args.KeyCode == Keys.Escape) {
                Choice = OperatorModeChoice.Cancelled;
                Close();
                args.Handled = true;
            }
        };
    }

    private static Label MakeLabel(string text, int left, int top, int width,
        int height, float size, FontStyle weight, Color color)
    {
        Label label = new Label();
        label.Text = text;
        label.SetBounds(left, top, width, height);
        label.Font = new Font("Microsoft YaHei UI", size, weight, GraphicsUnit.Point);
        label.ForeColor = color;
        label.UseCompatibleTextRendering = false;
        label.TabStop = false;
        return label;
    }

    private static Button MakeButton(string text, int left, bool extension)
    {
        Button button = new Button();
        button.Text = text;
        button.AccessibleName = text;
        button.AccessibleRole = AccessibleRole.PushButton;
        button.SetBounds(left, 103, 222, 64);
        button.Font = new Font("Microsoft YaHei UI", 15F, FontStyle.Bold, GraphicsUnit.Point);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 1;
        button.FlatAppearance.BorderColor = extension ? Color.FromArgb(37, 75, 115) :
            Color.FromArgb(194, 203, 214);
        button.BackColor = extension ? Color.FromArgb(37, 75, 115) : Color.White;
        button.ForeColor = extension ? Color.White : Color.FromArgb(26, 36, 49);
        button.FlatAppearance.MouseOverBackColor = extension ? Color.FromArgb(46, 91, 137) :
            Color.FromArgb(236, 240, 245);
        button.FlatAppearance.MouseDownBackColor = extension ? Color.FromArgb(30, 61, 94) :
            Color.FromArgb(224, 231, 240);
        button.UseVisualStyleBackColor = false;
        button.Cursor = Cursors.Hand;
        return button;
    }

    private void SelectMode(OperatorModeChoice selected)
    {
        if (preview) {
            // Preview clicks stay in this window; they cannot launch a backend.
            string name = selected == OperatorModeChoice.Native ? "原生" : "拓展";
            status.Text = "已选择" + name + "。当前为界面预览，尚未启动 Codex。";
            status.ForeColor = Color.FromArgb(37, 75, 115);
            Choice = OperatorModeChoice.Cancelled;
            return;
        }
        if (entryRoot != null && selected == OperatorModeChoice.Extension) {
            if (preparing) return;
            if (readyWindow != null) { FocusReadyWindow(); return; }
            PrepareExtension();
            return;
        }
        Choice = selected;
        DialogResult = selected == OperatorModeChoice.Native ? DialogResult.Yes : DialogResult.No;
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs args)
    {
        if (preparing) { args.Cancel = true; return; }
        // Closing the caption button, Escape and preview never select a mode.
        if (DialogResult != DialogResult.Yes && DialogResult != DialogResult.No)
            Choice = OperatorModeChoice.Cancelled;
        base.OnFormClosing(args);
    }

    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] private static extern bool ShowWindowAsync(IntPtr window, int command);

    private static void Require(bool condition, string reason) {
        if (!condition) throw new InvalidOperationException(reason);
    }
    private static string Hash(string path, long bound) {
        using (FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            Require(file.Length <= bound, "mode_picker_file_bound");
            using (SHA256 sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
        }
    }
    private Dictionary<string, object> CheckedEntry() {
        Require(Hash(Path.Combine(entryRoot, "entry.json"), 1048576) == entryDigest, "mode_picker_entry_changed");
        var entry = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            File.ReadAllText(Path.Combine(entryRoot, "entry.json"), new UTF8Encoding(false, true)));
        Require((string)entry["contract"] == "operator_isolated_mode_entry_v1" &&
            (string)entry["root"] == entryRoot && entry["native_enabled"] is bool && !(bool)entry["native_enabled"] &&
            Hash(Path.Combine(entryRoot, "entry.ps1"), 1048576) == (string)entry["entry_sha256"], "mode_picker_entry_changed");
        var compiled = entry["compiled"] as Dictionary<string, object>;
        Require(compiled != null && Hash(Assembly.GetExecutingAssembly().Location, 4194304) ==
            (string)compiled["operator-mode-picker.exe"], "mode_picker_program_changed");
        return entry;
    }
    private static string FailureStatus(string reason) {
        switch (reason) {
            case "official_package_changed":
            case "mode_official_package_changed":
            case "mode_package_changed":
            case "mode_package_ambiguous":
                return "官方应用版本或安装身份已变化；原配置保留，请检查升级记录。";
            case "web_manager_process_observation_unavailable":
                return "无法确认原拓展进程状态；检查记录已保留，请先核对原实例。";
            case "previous_launch_running_or_uncertain":
            case "previous_window_activation_uncertain":
            case "mode_picker_dispatch_unconfirmed":
            case "mode_picker_result_unconfirmed":
            case "mode_launch_observation_timeout":
            case "package_dispatch_failed":
            case "existing_window_activation_dispatch_failed":
            case "mode_existing_window_activation_unconfirmed":
            case "window_activation_identity_changed":
                return "启动或窗口派发未确认；原记录已保留，本次不会自动重试。";
            default:
                return "启动未完成，检查记录已保留。请关闭此窗口后检查。";
        }
    }
    private static string FixedFailureReason(string output, string error, int exitCode, bool overflow) {
        const string fallback = "mode_picker_dispatch_failed";
        if (exitCode == 0 || overflow || output == null || error == null) return fallback;
        try {
            if (new UTF8Encoding(false, true).GetByteCount(output) > 65536 || error.Length > 4096)
                return fallback;
            string reason;
            if (!String.IsNullOrWhiteSpace(output)) {
                var serializer = new JavaScriptSerializer();
                var value = serializer.Deserialize<Dictionary<string, object>>(output);
                if (value == null || value.Count != 5 || !value.ContainsKey("contract") ||
                    !value.ContainsKey("phase") || !value.ContainsKey("reason") ||
                    !value.ContainsKey("native_config_writes") || !value.ContainsKey("automatically_retried") ||
                    !(value["contract"] is string) || (string)value["contract"] != "operator_isolated_mode_entry_v1" ||
                    !(value["phase"] is string) || (string)value["phase"] != "failed" ||
                    !(value["reason"] is string) || !(value["native_config_writes"] is int) ||
                    (int)value["native_config_writes"] != 0 || !(value["automatically_retried"] is bool) ||
                    (bool)value["automatically_retried"]) return fallback;
                reason = (string)value["reason"];
                // Accepted values are fixed ASCII tokens. This comparison also
                // rejects duplicate/escaped keys and any extra JSON document.
                if (FailureStatus(reason) == FailureStatus(fallback) ||
                    Regex.Replace(output, @"\s+", "") != serializer.Serialize(value)) return fallback;
            } else {
                // Early PowerShell failures have no JSON. Never display raw stderr.
                var match = Regex.Match(error, @"\A(mode_[a-z_]+)(?:\r?\n)?\z");
                if (!match.Success) return fallback;
                reason = match.Groups[1].Value;
                if (FailureStatus(reason) == FailureStatus(fallback)) return fallback;
            }
            return reason;
        } catch { return fallback; }
    }
    private void PrepareExtension() {
        preparing = true;
        nativeButton.Enabled = false;
        extensionButton.Enabled = false;
        status.Text = "正在打开拓展模式…";
        BackgroundWorker worker = new BackgroundWorker();
        worker.DoWork += delegate(object sender, DoWorkEventArgs args) {
            CheckedEntry();
            string shell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "PowerShell", "7", "pwsh.exe");
            ProcessStartInfo start = new ProcessStartInfo(shell);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = new UTF8Encoding(false, true);
            start.Arguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File \"" +
                Path.Combine(entryRoot, "entry.ps1") + "\" -Action extension -Headless -Root \"" + entryRoot + "\"";
            StringBuilder output = new StringBuilder();
            StringBuilder errorOutput = new StringBuilder();
            bool overflow = false;
            bool errorOverflow = false;
            using (Process child = new Process()) {
                child.StartInfo = start;
                child.OutputDataReceived += delegate(object source, DataReceivedEventArgs line) {
                    if (line.Data == null) return;
                    lock (output) {
                        if (output.Length + line.Data.Length + 1 > 65536) overflow = true;
                        else output.AppendLine(line.Data);
                    }
                };
                child.ErrorDataReceived += delegate(object source, DataReceivedEventArgs line) {
                    if (line.Data == null) return;
                    lock (errorOutput) {
                        if (errorOutput.Length + line.Data.Length + 1 > 4096) errorOverflow = true;
                        else errorOutput.AppendLine(line.Data);
                    }
                };
                Require(child.Start(), "mode_picker_dispatch_failed");
                child.BeginOutputReadLine(); child.BeginErrorReadLine();
                Require(child.WaitForExit(120000), "mode_picker_dispatch_unconfirmed");
                child.WaitForExit();
                if (child.ExitCode != 0)
                    throw new InvalidOperationException(FixedFailureReason(output.ToString(), errorOutput.ToString(),
                        child.ExitCode, overflow || errorOverflow));
                Require(!overflow, "mode_picker_dispatch_failed");
            }
            CheckedEntry();
            var result = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(output.ToString());
            Require((string)result["contract"] == "operator_isolated_mode_entry_v1" && (string)result["root"] == entryRoot &&
                ((string)result["phase"] == "window_bound" || (string)result["phase"] == "opened_existing"),
                "mode_picker_result_unconfirmed");
            args.Result = result;
        };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs args) {
            preparing = false;
            if (args.Error != null) {
                status.Text = FailureStatus(args.Error is InvalidOperationException ? args.Error.Message : null);
                return;
            }
            readyWindow = (Dictionary<string, object>)args.Result;
            extensionButton.Enabled = true;
            extensionButton.Text = "打开窗口";
            FocusReadyWindow();
        };
        worker.RunWorkerAsync();
    }
    private void FocusReadyWindow() {
        try {
            var entry = CheckedEntry();
            var identity = readyWindow["window_process"] as Dictionary<string, object>;
            var package = entry["package"] as Dictionary<string, object>;
            Require(identity != null && identity["pid"] is int && package != null, "mode_picker_process_invalid");
            long raw;
            Require(readyWindow["window_handle"] is string && Int64.TryParse((string)readyWindow["window_handle"],
                NumberStyles.None, CultureInfo.InvariantCulture, out raw), "mode_picker_window_invalid");
            IntPtr window = new IntPtr(Int64.Parse((string)readyWindow["window_handle"], CultureInfo.InvariantCulture));
            using (Process desktop = Process.GetProcessById((int)identity["pid"])) {
                Require(!desktop.HasExited && desktop.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture) ==
                    (string)identity["birth"] && String.Equals(desktop.MainModule.FileName, (string)identity["executable"],
                    StringComparison.OrdinalIgnoreCase) && String.Equals(desktop.MainModule.FileName,
                    (string)package["executable"], StringComparison.OrdinalIgnoreCase), "mode_picker_process_changed");
                uint owner; GetWindowThreadProcessId(window, out owner);
                Require(owner == (uint)desktop.Id && IsWindowVisible(window), "mode_picker_window_changed");
                if (IsIconic(window)) ShowWindowAsync(window, 9);
                if (SetForegroundWindow(window) || GetForegroundWindow() == window) {
                    Choice = OperatorModeChoice.Cancelled; // Work was already dispatched exactly once.
                    Close();
                } else {
                    // Another user input may revoke foreground permission. A new click
                    // focuses this ready window only; it cannot replay the launch or a turn.
                    status.Text = "拓展模式已就绪。点击“打开窗口”切换过去。";
                }
            }
        } catch {
            extensionButton.Enabled = false;
            status.Text = "窗口状态已变化，检查记录已保留。请关闭此窗口后检查。";
        }
    }
}

internal static class OperatorModePickerProgram
{
    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [STAThread]
    private static int Main(string[] arguments)
    {
        // No arguments is deliberately a harmless preview. Actual selection is
        // an explicit child-process contract, not a standalone app launcher.
        bool select = arguments.Length == 1 && arguments[0] == "--select";
        bool preview = arguments.Length == 0 ||
            arguments.Length == 1 && arguments[0] == "--preview";
        bool launch = arguments.Length == 3 && arguments[0] == "--launch" &&
            Path.IsPathRooted(arguments[1]) && arguments[1] == Path.GetFullPath(arguments[1]) &&
            arguments[1].IndexOfAny(new char[] { '"', '\r', '\n' }) < 0 &&
            Regex.IsMatch(arguments[2], "\\A[a-f0-9]{64}\\z");
        if (!select && !preview && !launch) return 2;
        if (Environment.OSVersion.Version.Major >= 6) SetProcessDPIAware();
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (OperatorModePicker dialog = new OperatorModePicker(preview, launch ? arguments[1] : null,
                launch ? arguments[2] : null)) {
            Application.Run(dialog);
            return (int)dialog.Choice;
        }
    }
}
