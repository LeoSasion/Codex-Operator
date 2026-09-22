#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$CodexHome,
    [string]$ProjectRoot,
    [switch]$Apply,
    [switch]$Json,
    [switch]$Library
)

# This escape hatch deliberately imports neither the runtime nor Python.
$ErrorActionPreference = 'Stop'
$script:RecoveryUtf8 = New-Object Text.UTF8Encoding($false, $true)
$script:NativeRouteMarker = 'operator-native-route-only'
if (-not $Library) { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) }

function Assert-RecoveryPlainPath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'linked_path'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}

function Read-RecoveryBytes([string]$Path, [int]$Limit = 1048576) {
    Assert-RecoveryPlainPath $Path
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'not_regular_file' }
    if (-not ('OperatorRecoveryFile' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OperatorRecoveryFile {
    [StructLayout(LayoutKind.Sequential)]
    private struct Info {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    public static byte[] Read(string path, int limit) {
        using (var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            Info i;
            if (!GetFileInformationByHandle(f.SafeFileHandle, out i)) throw new IOException("file_identity_unavailable");
            if (i.Links != 1) throw new IOException("linked_path");
            if (f.Length > limit) throw new IOException("file_too_large");
            using (var r = new BinaryReader(f)) {
                byte[] data = r.ReadBytes(limit + 1);
                if (data.Length > limit) throw new IOException("file_too_large");
                return data;
            }
        }
    }
}
'@
    }
    return ,([OperatorRecoveryFile]::Read($Path, $Limit))
}

function Get-RecoveryHash([AllowNull()][byte[]]$Bytes) {
    if ($null -eq $Bytes) { return 'absent' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-RecoveryConfigPlan([AllowNull()][byte[]]$Bytes) {
    if ($null -eq $Bytes) { return @{ state='native'; changed=$false; bytes=$null } }
    $text = $script:RecoveryUtf8.GetString($Bytes)
    $begin = '# BEGIN FEISHU OPERATOR MODEL ROUTER'
    $end = '# END FEISHU OPERATOR MODEL ROUTER'
    $begins = [regex]::Matches($text, [regex]::Escape($begin)).Count
    $ends = [regex]::Matches($text, [regex]::Escape($end)).Count
    $changed = $false
    $remaining = $text
    if ($begins -or $ends) {
        # Only the documented leading three-line block is removable. Comments
        # before it are retained. This cannot match inside a TOML value/table.
        $pattern = '\A\uFEFF?(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*?(?<block>' +
            [regex]::Escape($begin) + '\r?\n[ \t]*(?<disabled>#[ \t]*)?' +
            'openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:(?<port>[0-9]{4,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n' +
            [regex]::Escape($end) + '(?:\r?\n|\z))'
        $match = [regex]::Match($text, $pattern)
        if ($begins -ne 1 -or $ends -ne 1 -or -not $match.Success -or
            [int]$match.Groups['port'].Value -lt 1024 -or [int]$match.Groups['port'].Value -gt 65535) {
            throw 'unrecognized_managed_block'
        }
        $block = $match.Groups['block']
        $remaining = $text.Remove($block.Index, $block.Length)
        $changed = -not $match.Groups['disabled'].Success
    }
    # Conservative detection, not a general TOML parser. Inactive profiles or
    # unusual multiline syntax can require review; never reset them by guessing.
    $selection = '(?m)^[ \t]*["'']?(openai_base_url|model_provider|profile|model_catalog_json)["'']?[ \t]*='
    $nativeTable = '(?m)^[ \t]*(?:\[[^\r\n]*model_providers[^\r\n]*openai[^\r\n]*\]|["'']?model_providers["'']?\s*[.=])'
    $inspection = [regex]::Replace($remaining, '(?m)^[ \t]*model_provider[ \t]*=[ \t]*["'']openai["''][ \t]*(?:#[^\r\n]*)?$', '')
    if ([regex]::IsMatch($inspection, $selection) -or [regex]::IsMatch($inspection, $nativeTable)) {
        throw 'other_route_settings_require_review'
    }
    return @{ state=$(if ($changed) {'plugin_route'} else {'native'}); changed=$changed;
        bytes=$(if ($changed) { $script:RecoveryUtf8.GetBytes($remaining) } else { $Bytes }) }
}

function Get-RecoveryEntryPlan([string]$Project) {
    if (-not $Project) { return @{ state='not_selected'; change=$null } }
    $bundle = Join-Path $Project '.codex/operator-desktop-entry'
    Assert-RecoveryPlainPath $bundle
    if (-not (Test-Path -LiteralPath $bundle)) { return @{ state='not_installed'; change=$null } }
    $buildBytes = Read-RecoveryBytes (Join-Path $bundle 'launcher-manifest.json') 16384
    $configPath = Join-Path $bundle 'desktop-entry.json'
    $configBytes = Read-RecoveryBytes $configPath 16384
    if ($null -eq $buildBytes -or $null -eq $configBytes) { throw 'entry_requires_review' }
    $build = $script:RecoveryUtf8.GetString($buildBytes) | ConvertFrom-Json
    $config = $script:RecoveryUtf8.GetString($configBytes) | ConvertFrom-Json
    $scriptHash = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $bundle 'operator_desktop_entry.ps1'))
    $binaryHash = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $bundle 'Codex拓展入口.exe') 16777216)
    if ($build.schema_version -ne 1 -or $build.native_fallback -cne 'native-only-v1' -or
        $scriptHash -eq 'absent' -or $binaryHash -eq 'absent' -or
        $build.binary_sha256 -cne $binaryHash -or $build.entry_script_sha256 -cne $scriptHash -or
        $config.schema_version -ne 1 -or $config.mode -notin @('native','reviewed_startup') -or
        $config.entry_script_sha256 -cne $scriptHash) { throw 'entry_requires_review' }
    if ($config.mode -eq 'native') { return @{ state='native'; change=$null } }
    $config.mode = 'native'
    return @{ state='reviewed_startup'; change=@{ name='desktop-entry.json'; path=$configPath;
        before=$configBytes; after=$script:RecoveryUtf8.GetBytes(($config | ConvertTo-Json -Depth 30)) } }
}

function Write-RecoveryChange($Change) {
    Assert-RecoveryPlainPath $Change.path
    if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.before)) {
        throw 'file_changed_during_recovery'
    }
    $temporary = Join-Path (Split-Path -Parent $Change.path) ('.operator-recovery-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($Change.after, 0, $Change.after.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.before)) {
            throw 'file_changed_during_recovery'
        }
        if ($null -eq $Change.before) { [IO.File]::Move($temporary, $Change.path) }
        else { [IO.File]::Replace($temporary, $Change.path, [NullString]::Value) }
        if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.after)) {
            throw 'write_verification_failed'
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function New-RecoveryBackup([string]$HomePath, $Changes) {
    $directory = Join-Path $HomePath ('operator-route-recovery/' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
    Assert-RecoveryPlainPath $directory
    [void][IO.Directory]::CreateDirectory($directory)
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,
                      (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    # Do not autoload modules from an inherited PSModulePath (which may belong
    # to another PowerShell edition). Both implementations are built into .NET.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($directory), $acl)
    } else { [IO.Directory]::SetAccessControl($directory, $acl) }
    $records = @()
    foreach ($change in $Changes) {
        if ($null -ne $change.before) {
            $original = Join-Path $directory ($change.name + '.before')
            [IO.File]::WriteAllBytes($original, $change.before)
            if ((Get-RecoveryHash (Read-RecoveryBytes $original)) -cne (Get-RecoveryHash $change.before)) { throw 'backup_verification_failed' }
        }
        $records += @{ name=$change.name; target=$change.path; before_sha256=(Get-RecoveryHash $change.before); after_sha256=(Get-RecoveryHash $change.after) }
    }
    [IO.File]::WriteAllBytes((Join-Path $directory 'intent.json'), $script:RecoveryUtf8.GetBytes((@{
        schema_version=1; purpose='operator_official_route_recovery'; files=$records
    } | ConvertTo-Json -Depth 6)))
    return $directory
}

function Invoke-OfficialRouteRecovery([string]$HomePath, [string]$Project, [bool]$Commit) {
    $homePath = [IO.Path]::GetFullPath($HomePath).TrimEnd('\')
    Assert-RecoveryPlainPath $homePath
    if (-not (Test-Path -LiteralPath $homePath -PathType Container)) { throw 'codex_home_missing' }
    $mutexes = @()
    $backup = $null
    $completed = @()
    try {
        if ($Commit) {
            $names = @('Local\CodexOperatorRouteRecovery-' + (Get-RecoveryHash $script:RecoveryUtf8.GetBytes($homePath.ToLowerInvariant())))
            if ($Project) { $names += 'Local\CodexOperatorDesktopEntry-' + (Get-RecoveryHash $script:RecoveryUtf8.GetBytes($Project.ToLowerInvariant())).ToUpperInvariant() }
            foreach ($name in $names) {
                $mutex = New-Object Threading.Mutex($false, $name)
                $owns = $false
                try { $owns = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owns=$true }
                if (-not $owns) { $mutex.Dispose(); throw 'startup_or_recovery_busy' }
                $mutexes += $mutex
            }
        }
        $configPath = Join-Path $homePath 'config.toml'
        $before = Read-RecoveryBytes $configPath
        $plan = Get-RecoveryConfigPlan $before
        $warnings = @()
        foreach ($scope in @('Process','User','Machine')) {
            if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL', $scope)) { $warnings += 'environment_override'; break }
        }
        # A broken/changed optional launcher must not prevent detaching a known
        # global override. Report the remaining entry issue, never overwrite it.
        try { $entry = Get-RecoveryEntryPlan $Project }
        catch { $entry = @{ state='requires_review'; change=$null }; $warnings += 'entry_requires_review' }
        $markerPath = Join-Path $homePath $script:NativeRouteMarker
        $markerBytes = Read-RecoveryBytes $markerPath
        $changes = @()
        if ($null -eq $markerBytes) {
            $changes += @{ name=$script:NativeRouteMarker; path=$markerPath; before=$null;
                after=$script:RecoveryUtf8.GetBytes("operator-native-route-only-v1`n") }
        }
        if ($entry.change) { $changes += $entry.change }
        if ($plan.changed) { $changes += @{name='config.toml'; path=$configPath; before=$before; after=$plan.bytes} }
        if ($Commit -and $changes.Count) {
            $backup = New-RecoveryBackup $homePath $changes
            # Validate all snapshots again before releasing any write.
            foreach ($change in $changes) {
                if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -cne (Get-RecoveryHash $change.before)) { throw 'file_changed_during_recovery' }
            }
            foreach ($change in $changes) { Write-RecoveryChange $change; $completed += $change.name }
            [IO.File]::WriteAllBytes((Join-Path $backup 'completed.json'), $script:RecoveryUtf8.GetBytes((@{
                schema_version=1; completed=$completed; warnings=$warnings
            } | ConvertTo-Json -Depth 4)))
        }
        return @{ status=$(if ($warnings.Count) {'needs_review'} elseif ($Commit) {'completed'} else {'preview'});
            route_before=$plan.state; config_changed=($Commit -and $plan.changed); would_change=@($changes | ForEach-Object { $_.name });
            recovery_lock_present=($Commit -or $null -ne $markerBytes); entry_before=$entry.state;
            backup=$backup; warnings=$warnings; completed=$completed; restart_required=$true }
    } catch {
        # Never print exception text: it can contain configuration or URLs.
        $reason = 'recovery_not_completed'
        $known = @('linked_path','not_regular_file','unrecognized_managed_block','other_route_settings_require_review',
            'file_changed_during_recovery','write_verification_failed','backup_verification_failed','startup_or_recovery_busy')
        if ($_.Exception.Message -cin $known) { $reason=$_.Exception.Message }
        return @{status='stopped'; reason=$reason; backup=$backup; completed=$completed;
            config_changed=($completed -contains 'config.toml'); restart_required=($completed -contains 'config.toml')}
    } finally {
        foreach ($mutex in $mutexes) { $mutex.ReleaseMutex(); $mutex.Dispose() }
    }
}

if ($Library) { return }
try {
    if (-not $CodexHome) {
        $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    }
    if (-not $ProjectRoot) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
        if ([IO.Path]::GetFullPath((Join-Path $candidate 'plugins/feishu-codex-operator/scripts')) -ieq $PSScriptRoot) { $ProjectRoot=$candidate }
        $installedProject = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
        if ([IO.Path]::GetFullPath((Join-Path $installedProject '.codex/feishu-codex-operator-runtime')) -ieq $PSScriptRoot) { $ProjectRoot=$installedProject }
        if ([IO.Path]::GetFullPath((Join-Path $installedProject '.codex/operator-native-recovery')) -ieq $PSScriptRoot) { $ProjectRoot=$installedProject }
    }
    if ($ProjectRoot) { $ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') }
    $result = Invoke-OfficialRouteRecovery $CodexHome $ProjectRoot $Apply.IsPresent
} catch { $result=@{status='stopped'; reason='recovery_not_completed'; backup=$null; completed=@()} }
if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
else {
    Write-Output 'Operator：恢复官方默认路由'
    if ($result.status -eq 'preview') {
        Write-Output '检查完成，尚未修改任何文件。双击插件目录中的“恢复官方默认路由.cmd”即可应用。'
    } elseif ($result.status -eq 'completed') {
        Write-Output '已停用插件全局路由，并保留官方直连保护。账户、历史、插件和项目文件均保留。'
        Write-Output '请自行彻底退出 Codex，再从官方 Codex 入口打开，选择官方模型。此操作不会关闭正在运行的任务。'
    } elseif ($result.status -eq 'needs_review') {
        Write-Output '插件路由检查或恢复已完成，但还有环境变量或拓展入口需要核对；尚不能确认全部路由已恢复。'
        Write-Output '请使用官方 Codex 入口启动。将本窗口结果交给维护者；不要删除整个配置或登录资料。'
    } else {
        Write-Output '恢复未完成。未覆盖无法识别的设置；请保留本窗口信息和备份，交给维护者核对。'
        if ($result.reason -eq 'other_route_settings_require_review') { Write-Output '检测到其他模型供应商、配置档案或路由设置，不能当作本插件配置删除。' }
        elseif ($result.reason -eq 'unrecognized_managed_block') { Write-Output '插件路由标记的内容或位置已改变，需要核对后再处理。' }
        elseif ($result.reason -eq 'startup_or_recovery_busy') { Write-Output '另一个启动或恢复操作仍在进行；本次未重复执行。' }
        Write-Output ('诊断代码：' + $result.reason)
    }
    if ($result.backup) { Write-Output ('恢复记录和原件：' + $result.backup) }
    if ($result.completed.Count) { Write-Output ('已完成项目：' + ($result.completed -join ', ')) }
    Write-Output ('结果：' + $result.status)
}
if ($result.status -in @('completed','preview')) { exit 0 }
exit 1
