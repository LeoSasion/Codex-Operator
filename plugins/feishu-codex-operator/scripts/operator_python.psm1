# Read-only interpreter discovery. Never install, edit PATH, or replay a script.
function Get-OperatorPythonCandidates {
    param([switch]$McpCommand)
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $names = if ($McpCommand) { @('python.exe') } else { @('python.exe', 'python3.exe', 'py.exe') }
    foreach ($name in $names) {
        $commands = @(Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)
        if ($McpCommand) { $commands = @($commands | Select-Object -First 1) }
        foreach ($command in $commands) {
            $path = [string]$command.Source
            if (-not $path -or -not [IO.Path]::IsPathRooted($path) -or -not $seen.Add($path)) { continue }
            # Unconfigured Windows python aliases can open the Store during a probe.
            if ($path -match '(?i)\\Microsoft\\WindowsApps\\.*python(?:3)?\.exe$') { continue }
            [pscustomobject]@{ Source=$path; Prefix=@(); Command=$name }
        }
    }
}

function Invoke-OperatorPythonProbe {
    param([Parameter(Mandatory=$true)][string]$Executable,
        [ValidateSet('--version', '-0p')][string]$Argument,
        [ValidateRange(1,1500)][int]$TimeoutMs=1500)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    $start.Arguments = $Argument
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables['PYTHON_MANAGER_AUTOMATIC_INSTALL'] = 'false'
    $start.EnvironmentVariables.Remove('PYLAUNCHER_ALLOW_INSTALL')
    $start.EnvironmentVariables.Remove('PYLAUNCHER_ALWAYS_INSTALL')
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { return $null }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMs)) {
            $process.Kill()
            $null = $process.WaitForExit(1000)
            return $null
        }
        if ($process.ExitCode -ne 0 -or -not $stdout.Wait(1000) -or -not $stderr.Wait(1000)) { return $null }
        $output = $stdout.Result + $stderr.Result
        if ($output.Length -gt 65536) { return $null }
        return $output
    } catch { return $null }
    finally { $process.Dispose() }
}

function Get-OperatorPythonFromLauncher {
    param([Parameter(Mandatory=$true)]$Candidate, [int]$TimeoutMs=1500)
    # Both launcher generations support this installed-only listing. A launch
    # such as py -3 --version may install a runtime when none is available.
    $output = Invoke-OperatorPythonProbe -Executable $Candidate.Source -Argument '-0p' -TimeoutMs $TimeoutMs
    if ($null -eq $output -or $output.Length -gt 65536) { return }
    $lines = @($output -split '\r?\n')
    if ($lines.Count -gt 64) { return }
    foreach ($line in $lines) {
        if ($line -notmatch '^\s*-(?:V:)?[^\s]+\s+(?:\*\s+)?(?<path>[A-Za-z]:\\[^\x00-\x1f"<>|]*\\python(?:3)?(?:\.\d+)?\.exe)\s*$') { continue }
        $path = $Matches.path.TrimEnd()
        if ($path -match '(?i)\\Microsoft\\WindowsApps\\' -or
            -not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        [pscustomobject]@{Source=$path;Prefix=@();Command='py.exe'}
    }
}

function Get-OperatorPythonVersion {
    param([Parameter(Mandatory=$true)]$Candidate, [int]$TimeoutMs=1500)
    $output = Invoke-OperatorPythonProbe -Executable $Candidate.Source -Argument '--version' -TimeoutMs $TimeoutMs
    if ($null -eq $output) { return $null }
    $output = $output.Trim()
    if ($output.Length -gt 128 -or $output -notmatch '^Python (\d+)\.(\d+)(?:\.\S+)?$') { return $null }
    return [version]("{0}.{1}" -f $Matches[1], $Matches[2])
}

function Get-OperatorPython {
    param([switch]$Required, [switch]$McpCommand, [string]$PreferredExecutable='')
    # Discovery is bounded; selecting a later interpreter never retries a job.
    $checked = 0
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $candidates = @()
    if ($PreferredExecutable -and -not $McpCommand -and
        [IO.Path]::IsPathRooted($PreferredExecutable) -and
        $PreferredExecutable -notmatch '(?i)\\Microsoft\\WindowsApps\\' -and
        (Test-Path -LiteralPath $PreferredExecutable -PathType Leaf)) {
        $candidates += [pscustomobject]@{Source=$PreferredExecutable;Prefix=@();Command='preferred'}
    }
    $candidates += @(Get-OperatorPythonCandidates -McpCommand:$McpCommand | Select-Object -First 8)
    foreach ($candidate in $candidates) {
        if ($McpCommand -and $candidate.Command -cne 'python.exe') { continue }
        $remaining = [Math]::Min(1500, 3000 - $clock.ElapsedMilliseconds)
        if ($remaining -le 0 -or $checked -ge 8) { break }
        $resolved = @($candidate)
        if ($candidate.Command -ceq 'py.exe') {
            $resolved = @(Get-OperatorPythonFromLauncher $candidate -TimeoutMs $remaining)
        }
        foreach ($runtime in $resolved) {
            if (-not $seen.Add($runtime.Source)) { continue }
            $remaining = [Math]::Min(1500, 3000 - $clock.ElapsedMilliseconds)
            if ($remaining -le 0 -or ++$checked -gt 8) { break }
            $version = Get-OperatorPythonVersion $runtime -TimeoutMs $remaining
            if ($null -ne $version -and $version -ge [version]'3.11') {
                return [pscustomobject]@{ Available=$true; Source=$runtime.Source;
                    Prefix=@(); Version=$version; Detail=("Python {0}" -f $version) }
            }
        }
    }
    if ($Required) { throw 'Python 3.11+ is required. No job was started and existing settings were preserved.' }
    return [pscustomobject]@{ Available=$false; Source=''; Prefix=@(); Version=$null;
        Detail=$(if ($McpCommand) { 'Python 3.11+ must be available as python.exe for the plugin MCP servers.' }
            else { 'Python 3.11+ was not found through python.exe, python3.exe or py.exe.' }) }
}

Export-ModuleMember -Function Get-OperatorPython
