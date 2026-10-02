#requires -Version 7.0
[CmdletBinding()]
param([switch]$Library, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$nativeInspectOnly = $CheckOnly.IsPresent

# The installed copy keeps these dependencies beside it, independently of Python,
# the model router and the removable runtime. Dot-source only after hash checks.
function Get-OperatorNativeDefaultHome {
    return Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'
}

function Get-OperatorNativePipeProjection([byte[]]$Bytes) {
    $text=[Text.UTF8Encoding]::new($false,$true).GetString($Bytes)
    $table=[regex]::Matches($text,'(?m)^\[mcp_servers\.node_repl\.env\][ \t]*\r?$')
    if ($table.Count -ne 1) {return $null}
    $start=$table[0].Index+$table[0].Length
    $next=[regex]::Match($text.Substring($start),'(?m)^[ \t]*\[')
    $length=if ($next.Success) {$next.Index} else {$text.Length-$start}
    $body=$text.Substring($start,$length)
    $pattern='(?m)^(?<before>[ \t]*SKY_CUA_NATIVE_PIPE_DIRECTORY[ \t]*=[ \t]*)(?<value>"(?:[^"\\\r\n]|\\["\\bfnrt]|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8})*"|''[^''\r\n]*'')(?<after>[ \t]*(?:#[^\r\n]*)?\r?)$'
    $matches=[regex]::Matches($body,$pattern)
    if ($matches.Count -ne 1 -or [regex]::Matches($text,'(?m)^[ \t]*SKY_CUA_NATIVE_PIPE_DIRECTORY[ \t]*=').Count -ne 1) {return $null}
    $value=$matches[0].Groups['value']
    return $text.Remove($start+$value.Index,$value.Length).Insert($start+$value.Index,'""')
}

function Get-OperatorNativeRecoveryEpoch([string]$HomePath) {
    # Only a new direct-cycle epoch has this authority. Legacy recovery files
    # and their filesystem dates do not acquire a launch epoch retroactively.
    try {
        $active=ConvertFrom-RecoveryJson (Read-RecoveryBytes (Join-Path $HomePath 'operator-direct-entry/active.json') 16384)
        if ($active.schema_version -ne 1 -or $active.contract -cne 'operator_direct_entry_active_v1' -or
            $active.cycle -cnotmatch '^[a-f0-9]{32}$' -or $active.intent_sha256 -cnotmatch '^[a-f0-9]{64}$') {return $null}
        $cycle=Join-Path $HomePath ('operator-direct-entry/cycles/'+$active.cycle)
        $intentRaw=Read-RecoveryBytes (Join-Path $cycle 'intent.json') 4194304
        if ((Get-RecoveryHash $intentRaw) -cne $active.intent_sha256) {return $null}
        $intent=ConvertFrom-RecoveryJson $intentRaw
        if ($intent.contract -cne 'operator_direct_entry_cycle_v1' -or $intent.home -ine $HomePath -or
            $intent.cycle -cne $active.cycle -or $intent.native_helper_sha256 -cne
            (Get-RecoveryHash (Read-RecoveryBytes $script:RecoverySourcePath))) {return $null}
        foreach ($name in @('config-before.bin','config-candidate.bin','projection.json','profile.json','plan.json')) {
            if ($intent.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
                (Get-RecoveryHash (Read-RecoveryBytes (Join-Path $cycle $name) 4194304)) -cne $intent.files[$name]) {return $null}
        }
        $receiptRaw=Read-RecoveryBytes (Join-Path $cycle 'recovered.json') 65536
        $receipt=ConvertFrom-RecoveryJson $receiptRaw
        if ($receipt.schema_version -ne 1 -or $receipt.contract -cne 'operator_direct_entry_recovered_v1' -or
            $receipt.cycle -cne $active.cycle -or $receipt.intent_sha256 -cne $active.intent_sha256 -or
            -not [IO.Path]::IsPathFullyQualified($receipt.recovery_backup) -or
            (Split-Path -Parent $receipt.recovery_backup) -ine (Join-Path $HomePath 'operator-route-recovery')) {return $null}
        $backup=$receipt.recovery_backup
        $completedRaw=Read-RecoveryBytes (Join-Path $backup 'completed.json') 65536
        $completed=ConvertFrom-RecoveryJson $completedRaw
        $record=ConvertFrom-RecoveryJson (Read-RecoveryBytes (Join-Path $backup 'intent.json'))
        if ($record.schema_version -ne 1 -or $record.purpose -cne 'operator_official_route_recovery' -or
            $completed.schema_version -ne 1 -or $completed.warnings.Count) {return $null}
        $epoch=$completed.native_epoch
        if ($epoch -isnot [Collections.IDictionary] -or
            @(Compare-Object @($epoch.Keys|Sort-Object) @('completed_utc','config_after_sha256','contract','cycle','intent_sha256','native_helper_sha256')).Count -or
            $epoch.contract -cne 'operator_direct_native_epoch_v1' -or $epoch.cycle -cne $active.cycle -or
            $epoch.intent_sha256 -cne $active.intent_sha256 -or $epoch.native_helper_sha256 -cne $intent.native_helper_sha256 -or
            $epoch.config_after_sha256 -cne $receipt.config_after_recovery_sha256) {return $null}
        $rows=@($record.files)
        $receiptRow=@($rows|Where-Object {$_.target -ieq (Join-Path $cycle 'recovered.json')})
        if ($receiptRow.Count -ne 1 -or $receiptRow[0].after_sha256 -cne (Get-RecoveryHash $receiptRaw) -or
            $receiptRow[0].name -cnotin $completed.completed) {return $null}
        $configRow=@($rows|Where-Object {$_.target -ieq (Join-Path $HomePath 'config.toml')})
        if ($configRow.Count -gt 1 -or ($configRow.Count -eq 1 -and
            ($configRow[0].before_sha256 -cne $receipt.config_before_recovery_sha256 -or
             $configRow[0].after_sha256 -cne $receipt.config_after_recovery_sha256 -or
             $configRow[0].name -cnotin $completed.completed)) -or
            ($configRow.Count -eq 0 -and ($receipt.config_before_recovery_sha256 -cne $receipt.config_after_recovery_sha256 -or
              $receipt.config_after_recovery_sha256 -cne $intent.files['config-before.bin']))) {return $null}
        $after=Read-RecoveryBytes (Join-Path $backup 'config.toml.after')
        if ((Get-RecoveryHash $after) -cne $epoch.config_after_sha256) {return $null}
        $current=Read-RecoveryBytes (Join-Path $HomePath 'config.toml')
        if ((Get-RecoveryHash $current) -cne $epoch.config_after_sha256) {
            $a=Get-OperatorNativePipeProjection $after;$b=Get-OperatorNativePipeProjection $current
            if ($null -eq $a -or $null -eq $b -or $a -cne $b) {return $null}
        }
        # Read the original JSON string; PowerShell may coerce ISO strings into
        # DateTime values during ConvertFrom-Json, losing its lexical contract.
        $json=[Text.Json.JsonDocument]::Parse([Text.UTF8Encoding]::new($false,$true).GetString($completedRaw))
        try {$utc=$json.RootElement.GetProperty('native_epoch').GetProperty('completed_utc').GetString()}
        finally {$json.Dispose()}
        $parsed=[DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParseExact($utc,'o',[Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None,[ref]$parsed) -or $parsed.Offset -ne [TimeSpan]::Zero -or $parsed.UtcDateTime -gt [DateTime]::UtcNow) {return $null}
        return $parsed.UtcDateTime
    } catch {return $null}
}

function Invoke-OperatorNativeEntry {
    param([string]$Project, [string]$HomePath, [switch]$InspectOnly,
          [ValidateSet('legacy_recovery_v1','registered_application_v1')][string]$ActivationMode='legacy_recovery_v1')
    $projectKey=[IO.Path]::GetFullPath($Project).TrimEnd('\').ToLowerInvariant()
    $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($projectKey)))
    $mutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$hash))
    $owns=$false
    try {
        try { $owns=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owns=$true }
        if (-not $owns) { return @{status='startup_busy';configuration_changed=$false;launch_requested=$false} }
        return Invoke-OperatorNativeEntryChecked $Project $HomePath -InspectOnly:$InspectOnly -ActivationMode $ActivationMode
    } finally { if ($owns) {$mutex.ReleaseMutex()};$mutex.Dispose() }
}

function Invoke-OperatorNativeEntryChecked {
    param([string]$Project, [string]$HomePath, [switch]$InspectOnly,
          [ValidateSet('legacy_recovery_v1','registered_application_v1')][string]$ActivationMode='legacy_recovery_v1')
    $defaultHome=[IO.Path]::GetFullPath((Get-OperatorNativeDefaultHome)).TrimEnd('\')
    $effectiveHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { $defaultHome }
    if ([IO.Path]::GetFullPath($HomePath).TrimEnd('\') -ine $defaultHome -or
        [IO.Path]::GetFullPath($effectiveHome).TrimEnd('\') -ine $defaultHome) {
        return @{status='needs_review';configuration_changed=$false;launch_requested=$false}
    }
    if ($ActivationMode -ceq 'registered_application_v1') {
        # A reviewed isolated entry never changes the default home. Its native
        # shortcut follows ordinary official activation and keeps working for pins.
        $application=Get-OperatorPackagedApplication
        if ($InspectOnly) {return @{status='ready';action='open_native';configuration_changed=$false;launch_requested=$false}}
        try {Open-OperatorPackagedApplication $application}
        catch {return @{status='launch_failed';configuration_changed=$false;launch_requested=$true;desktop_acceptance='unverified'}}
        return @{status='launch_requested';configuration_changed=$false;launch_requested=$true;desktop_acceptance='unverified'}
    }
    $preview = Invoke-OfficialRouteRecovery $HomePath $Project $false
    if ($preview.status -ne 'preview' -or $preview.warnings.Count) {
        return @{status='needs_review';configuration_changed=$false;launch_requested=$false}
    }
    $native = $preview.route_before -eq 'native'
    $running=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'")
    $configFile=Join-Path $HomePath 'config.toml'
    # A recovery can precede normal application exit. In that case the disk is
    # native but an older running process may still hold the previous route.
    $configTime=if (Test-Path -LiteralPath $configFile) {(Get-Item -LiteralPath $configFile).LastWriteTimeUtc} else {[DateTime]::MinValue}
    $epoch=if ($native -and $running.Count) {Get-OperatorNativeRecoveryEpoch $HomePath} else {$null}
    $routeTime=if ($null -ne $epoch) {$epoch} else {$configTime}
    $oldOrUnknown=@($running | Where-Object {-not $_.CreationDate -or ([DateTime]$_.CreationDate).ToUniversalTime() -le $routeTime}).Count
    if (($running.Count -and -not $native) -or $oldOrUnknown) {
        return @{status='normal_exit_required';configuration_changed=$false;launch_requested=$false}
    }
    # Resolve the official package before any recovery write. The helper uses
    # shell package activation; executing WindowsApps\app\ChatGPT.exe is invalid.
    $application = Get-OperatorPackagedApplication
    if ($InspectOnly) {
        return @{status='ready';action=$(if ($native) {'open_native'} else {'recover_then_open'});
            configuration_changed=$false;launch_requested=$false}
    }
    $changed = $false
    if (-not $native) {
        # Recheck immediately before the existing, mutex-protected recovery.
        if (@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'").Count) {
            return @{status='normal_exit_required';configuration_changed=$false;launch_requested=$false}
        }
        $recovery = Invoke-OfficialRouteRecovery $HomePath $Project $true
        if ($recovery.status -ne 'completed' -or $recovery.warnings.Count) {
            return @{status='needs_review';configuration_changed=[bool]$recovery.config_changed;launch_requested=$false}
        }
        $changed = [bool]$recovery.config_changed
        $checked = Invoke-OfficialRouteRecovery $HomePath $Project $false
        if ($checked.status -ne 'preview' -or $checked.route_before -ne 'native' -or $checked.warnings.Count) {
            return @{status='needs_review';configuration_changed=$changed;launch_requested=$false}
        }
    }
    try { Open-OperatorPackagedApplication $application }
    catch { return @{status='launch_failed';configuration_changed=$changed;launch_requested=$true;desktop_acceptance='unverified'} }
    return @{status='launch_requested';configuration_changed=$changed;launch_requested=$true;desktop_acceptance='unverified'}
}

if ($Library) { return }
try {
    function Read-NativeEntryBytes([string]$Path,[int]$Limit) {
        $cursor=[IO.Path]::GetFullPath($Path)
        while ($cursor) {
            if ((Test-Path -LiteralPath $cursor) -and
                ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'native_entry_linked_path' }
            $cursor=[IO.Path]::GetDirectoryName($cursor)
        }
        $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        try {
            if ($stream.Length -gt $Limit) { throw 'native_entry_file_bound' }
            $reader=[IO.BinaryReader]::new($stream)
            try { return ,$reader.ReadBytes($Limit+1) } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
    }
    $configPath = Join-Path $PSScriptRoot 'native-entry.json'
    $nativeConfig = [Text.UTF8Encoding]::new($false,$true).GetString((Read-NativeEntryBytes $configPath 16384)) | ConvertFrom-Json -AsHashtable
    if ($nativeConfig.schema_version -ne 1 -or
        -not [IO.Path]::IsPathFullyQualified($nativeConfig.project) -or
        -not [IO.Path]::IsPathFullyQualified($nativeConfig.home) -or
        $nativeConfig.files.Count -ne 2) { throw 'native_entry_configuration_invalid' }
    foreach ($name in @('restore-codex-official-route.ps1','operator_desktop_entry.ps1')) {
        $file = Join-Path $PSScriptRoot $name
        if ($nativeConfig.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData((Read-NativeEntryBytes $file 1048576))).ToLowerInvariant() -cne $nativeConfig.files[$name]) {
            throw 'native_entry_dependency_changed'
        }
    }
    . (Join-Path $PSScriptRoot 'restore-codex-official-route.ps1') -Library
    . (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1') -Library
    $activationMode=if ($nativeConfig.Contains('activation_mode')) {$nativeConfig.activation_mode} else {'legacy_recovery_v1'}
    $nativeResult = Invoke-OperatorNativeEntry $nativeConfig.project $nativeConfig.home -InspectOnly:$nativeInspectOnly -ActivationMode $activationMode
    if ($nativeInspectOnly) { $nativeResult | ConvertTo-Json -Compress }
    elseif ($nativeResult.status -ne 'launch_requested') {
        Add-Type -AssemblyName System.Windows.Forms
        $message = if ($nativeResult.status -eq 'normal_exit_required') {
            '请先保存工作并正常完全退出 Codex，再点击“ChatGPT 原生入口”。当前应用仍在运行，配置未改动；不会结束进程或中断任务。'
        } elseif ($nativeResult.status -eq 'launch_failed' -and $nativeResult.configuration_changed) {
            '官方直连配置已恢复，但应用启动尚未确认。恢复记录已保留；请告知助手检查，不必重复恢复。'
        } else { '原生入口尚未完成，应用启动未确认。请保留当前状态并交给助手检查；不要重复恢复或删除配置。' }
        [Windows.Forms.MessageBox]::Show($message,'ChatGPT 原生入口',[Windows.Forms.MessageBoxButtons]::OK,[Windows.Forms.MessageBoxIcon]::Information) | Out-Null
    }
    if ($nativeResult.status -in @('launch_requested','ready')) { exit 0 }
    exit 1
} catch {
    if ($nativeInspectOnly) { '{"status":"needs_review","launch_requested":false}' }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show('原生入口未能完成检查，请保留当前状态并交给助手检查。未自动重试。','ChatGPT 原生入口') | Out-Null
    }
    exit 1
}
