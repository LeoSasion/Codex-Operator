"""Isolated Hook identity/stop fixtures; never inspect or control real processes."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PWSH = shutil.which("pwsh")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
SOURCES = ("start-feishu-codex-operator.ps1", "stop-feishu-codex-operator.ps1")
EXPECTED = r"C:\Operator fixture 中文\.codex\feishu-codex-operator-runtime\operator_main.py"
PYTHON = r"C:\Python fixture\python.exe"

DRIVER = r"""
param([string]$Source,[string]$Cases,[string]$Lane,[string]$Directory)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'invalid Hook source'}
foreach ($name in @('ConvertFrom-OperatorWindowsCommandLine','Test-OperatorPythonCommandLine','Get-OperatorProcessIdentity')) {
    $definitions=@($ast.FindAll({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
    },$true))
    if ($definitions.Count -ne 1) {throw 'ambiguous fixture function'}
    Invoke-Expression $definitions[0].Extent.Text
}
# The real process APIs are shadowed before any extracted code is invoked.
function Get-Process {param([int]$Id,$ErrorAction)
    $script:processReads += 1
    if ($script:processAbsent) {return $null}
    if ($script:processReads -gt 1 -and $script:after -ceq 'absent') {return $null}
    return [pscustomobject]@{ProcessName=$script:processName;Id=$Id}
}
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)
    $script:reads += 1
    if ($script:cimFails) {throw 'synthetic unavailable metadata'}
    if ($script:reads -gt 1) {
        if ($script:after -ceq 'absent') {$script:processAbsent=$true;return $null}
        if ($script:after -ceq 'reused') {
            $script:commandLine='"C:\Python fixture\python.exe" "C:\different.py"'
        }
        if ($script:after -ceq 'unknown') {return [pscustomobject]@{CommandLine=''}}
    }
    return [pscustomobject]@{CommandLine=$script:commandLine}
}
function Stop-Process {param($InputObject,[switch]$Force,$ErrorAction)
    $script:kills += 1
    if ($InputObject.Id -ne 4242 -or -not $Force) {throw 'invalid synthetic stop'}
}
function Get-Date {
    $script:clock=$script:clock.AddSeconds(30)
    return $script:clock
}
function Start-Sleep {param($Milliseconds) throw 'fixture must not wait'}
$stopBody=$null
if ($Lane -ceq 'stop') {
    # Only the identity/stop decision block is run. All paths point into the
    # disposable fixture; lifecycle/lease setup is never executed.
    $sourceText=[IO.File]::ReadAllText($Source)
    $begin=$sourceText.IndexOf('$operatorScript = Join-Path $runtimeRoot')
    $end=$sourceText.IndexOf(([string][char]10 + '} finally {'),$begin)
    if ($begin -lt 0 -or $end -lt $begin) {throw 'stop fixture source boundary changed'}
    # A production exit is a return from this extracted fixture block; otherwise
    # normal-stop branches would exit the driver before its JSON assertions.
    $stopBody=[scriptblock]::Create($sourceText.Substring($begin,$end-$begin).Replace('exit 0','return'))
}
$results=@()
$caseInputs=Get-Content -LiteralPath $Cases -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($case in $caseInputs) {
    $script:processAbsent=[bool]$case.absent
    $script:processName=if($case.process_name){[string]$case.process_name}else{'python'}
    $script:commandLine=[string]$case.command
    $script:cimFails=[bool]$case.cim_fails
    $script:reads=0;$script:processReads=0;$script:kills=0;$script:after=[string]$case.after
    $script:clock=[DateTime]::new(2026,1,1)
    if ($Lane -ceq 'identity') {
        $value=Get-OperatorProcessIdentity -ProcessId 4242 -OperatorScript $case.expected
        $results += @{exists=$value.Exists;verified=$value.Verified;operator=$value.IsOperator;reason=$value.Reason}
    } else {
        $runtimeRoot=Join-Path $Directory 'runtime'
        New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
        $pidFile=Join-Path $runtimeRoot 'operator.pid'
        Set-Content -LiteralPath $pidFile -Value '4242'
        $operatorPid=4242
        $script:commandLine=$script:commandLine.Replace('EXPECTED_SCRIPT',(Join-Path $runtimeRoot 'operator_main.py'))
        function Write-LifecycleStatus {param($Message)}
        $failure=$false
        try {& $stopBody} catch {$failure=$true}
        $results += @{failed=$failure;kills=$script:kills;pid_retained=(Test-Path -LiteralPath $pidFile)}
    }
}
ConvertTo-Json -InputObject $results -Depth 5 -Compress
"""


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell identity contract")
class ChannelProcessIdentityTests(unittest.TestCase):
    def run_fixture(self, source, cases, *, lane="identity", shell=None):
        with tempfile.TemporaryDirectory(prefix="operator identity fixture ") as temporary:
            directory = Path(temporary)
            driver = directory / "identity.ps1"
            inputs = directory / "cases.json"
            driver.write_text(DRIVER, encoding="utf-8-sig")
            inputs.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8-sig")
            completed = subprocess.run(
                [shell or PWSH, "-NoProfile", "-NonInteractive", "-File", str(driver),
                 "-Source", str(ROOT / "scripts" / source), "-Cases", str(inputs),
                 "-Lane", lane, "-Directory", str(directory)],
                capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

    def test_exact_script_path_and_supported_interpreter_switches(self):
        commands = [
            subprocess.list2cmdline([PYTHON, EXPECTED]),
            subprocess.list2cmdline([PYTHON, "-B", EXPECTED]),
            subprocess.list2cmdline([PYTHON, "-E", "-I", "-s", "-S", "-u", "-b",
                                     "-bb", "-O", "-OO", "-q", "-P", "--", EXPECTED]),
            subprocess.list2cmdline([PYTHON, EXPECTED.upper().replace("\\", "/")]),
            subprocess.list2cmdline([PYTHON, str(Path(EXPECTED).parent) + r"\.\operator_main.py"]),
        ]
        for source in SOURCES:
            with self.subTest(source=source):
                results = self.run_fixture(source, [
                    {"command": command, "expected": EXPECTED} for command in commands
                ])
                self.assertEqual(results, [
                    dict(exists=True, verified=True, operator=True, reason="exact_operator_script")
                    for _ in commands
                ])

    def test_similar_names_and_other_script_arguments_are_never_operator(self):
        commands = [
            [PYTHON, EXPECTED + ".backup"],
            [PYTHON, EXPECTED + ".py"],
            [PYTHON, r"C:\different.py", EXPECTED],
            [PYTHON, EXPECTED, r"C:\different.py"],
            [PYTHON, "-c", "print('synthetic')", EXPECTED],
            [PYTHON, "-m", "synthetic", EXPECTED],
            [PYTHON, "-W", "ignore", EXPECTED],
            [PYTHON, "-X", "dev", EXPECTED],
            [PYTHON, "-i", EXPECTED],
            [PYTHON, "-Bu", EXPECTED],
            [PYTHON, r"C:operator_main.py"],
            [PYTHON, r"\operator_main.py"],
            [PYTHON, "operator_main.py"],
            [PYTHON, "--"],
            [PYTHON, "-"],
            [PYTHON, ""],
            [PYTHON],
        ]
        for source in SOURCES:
            with self.subTest(source=source):
                results = self.run_fixture(source, [
                    {"command": subprocess.list2cmdline(command), "expected": EXPECTED}
                    for command in commands
                ])
                self.assertTrue(all(not result["operator"] for result in results))
                self.assertEqual([result["verified"] for result in results],
                                 [True, True] + [False] * (len(results) - 2))

    def test_missing_or_unreadable_process_is_not_positive_identity(self):
        cases = [
            {"command": "", "expected": EXPECTED, "absent": True},
            {"command": "", "expected": EXPECTED, "process_name": "notepad"},
            {"command": "", "expected": EXPECTED, "cim_fails": True},
            {"command": "", "expected": EXPECTED},
        ]
        expected = [
            dict(exists=False, verified=True, operator=False, reason="process_absent"),
            dict(exists=True, verified=True, operator=False, reason="non_python_process"),
            dict(exists=True, verified=False, operator=False, reason="command_line_unavailable"),
            dict(exists=True, verified=False, operator=False, reason="command_line_unavailable"),
        ]
        for source in SOURCES:
            with self.subTest(source=source):
                self.assertEqual(self.run_fixture(source, cases), expected)

    def test_stop_preserves_unknown_processes_and_handles_exit_or_pid_reuse(self):
        # EXPECTED_SCRIPT is replaced only with the disposable fixture path.
        command = '"' + PYTHON + '" "EXPECTED_SCRIPT"'
        cases = [
            {"command": command, "after": "absent"},
            {"command": command, "after": "reused"},
            {"command": command, "after": "unknown"},
            {"command": command},
            {"command": command.replace("EXPECTED_SCRIPT", "EXPECTED_SCRIPT.backup")},
            {"command": subprocess.list2cmdline([PYTHON, r"C:\different.py", "EXPECTED_SCRIPT"])},
            {"command": command, "cim_fails": True},
        ]
        self.assertEqual(self.run_fixture(SOURCES[1], cases, lane="stop"), [
            dict(failed=False, kills=0, pid_retained=False),
            dict(failed=False, kills=0, pid_retained=False),
            dict(failed=True, kills=0, pid_retained=True),
            dict(failed=False, kills=1, pid_retained=False),
            dict(failed=False, kills=0, pid_retained=False),
            dict(failed=True, kills=0, pid_retained=True),
            dict(failed=True, kills=0, pid_retained=True),
        ])

    @unittest.skipUnless(WINDOWS_POWERSHELL, "Windows PowerShell 5 Hook host")
    def test_windows_powershell_uses_the_same_exact_path_contract(self):
        cases = [
            {"command": subprocess.list2cmdline([PYTHON, "-B", EXPECTED]), "expected": EXPECTED},
            {"command": subprocess.list2cmdline([PYTHON, EXPECTED + ".backup"]), "expected": EXPECTED},
            {"command": subprocess.list2cmdline([PYTHON, "-m", "synthetic", EXPECTED]), "expected": EXPECTED},
        ]
        for source in SOURCES:
            with self.subTest(source=source):
                results = self.run_fixture(source, cases, shell=WINDOWS_POWERSHELL)
                self.assertEqual([result["operator"] for result in results], [True, False, False])
                self.assertEqual([result["verified"] for result in results], [True, True, False])

    def test_both_hooks_retain_identical_self_contained_identity_helpers(self):
        source_texts = [(ROOT / "scripts" / source).read_text(encoding="utf-8-sig")
                        for source in SOURCES]
        helpers = [text[text.index("function ConvertFrom-OperatorWindowsCommandLine {"):
                        text.index("$mutexProjectRoot =")] for text in source_texts]
        self.assertEqual(helpers[0], helpers[1])


if __name__ == "__main__":
    unittest.main()
