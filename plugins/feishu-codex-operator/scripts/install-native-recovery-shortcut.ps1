#requires -Version 5.1
[CmdletBinding()]
param([string]$ProjectRoot, [string]$DesktopDirectory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$shortcutProject = $ProjectRoot
. (Join-Path $PSScriptRoot 'restore-codex-official-route.ps1') -Library
$ProjectRoot = $shortcutProject
$mutex = $null
$owns = $false
$temporaryLink = $null
try {
    if (-not $ProjectRoot) {
        $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
        if ([IO.Path]::GetFullPath((Join-Path $ProjectRoot 'plugins/feishu-codex-operator/scripts')) -ine $PSScriptRoot) {
            $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
            if ([IO.Path]::GetFullPath((Join-Path $ProjectRoot '.codex/feishu-codex-operator-runtime')) -ine $PSScriptRoot) { throw 'project_identity_unknown' }
        }
    }
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    if (-not $DesktopDirectory) { $DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
    $desktop = [IO.Path]::GetFullPath($DesktopDirectory)
    Assert-RecoveryPlainPath $project
    Assert-RecoveryPlainPath $desktop
    if (-not (Test-Path -LiteralPath $project -PathType Container) -or
        -not (Test-Path -LiteralPath $desktop -PathType Container)) { throw 'directory_missing' }
    $bundle = Join-Path $project '.codex/operator-native-recovery'
    Assert-RecoveryPlainPath $bundle
    $linkPath = Join-Path $desktop '恢复官方默认路由.lnk'
    $receiptPath = Join-Path $bundle 'ownership.json'
    $mutex = New-Object Threading.Mutex($false, ('Local\OperatorRecoveryShortcut-' + (Get-RecoveryHash $script:RecoveryUtf8.GetBytes($desktop.ToLowerInvariant()))))
    try { $owns=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owns=$true }
    if (-not $owns) { throw 'shortcut_setup_busy' }
    $receiptBefore = Read-RecoveryBytes $receiptPath
    $linkBefore = Read-RecoveryBytes $linkPath
    $old = $null
    if ($null -ne $receiptBefore) {
        $old = $script:RecoveryUtf8.GetString($receiptBefore) | ConvertFrom-Json
        if ($old.schema_version -ne 1 -or $old.project -cne $project -or $old.shortcut -cne $linkPath -or
            @($old.files.PSObject.Properties).Count -ne 2) { throw 'shortcut_ownership_conflict' }
        if ($null -ne $linkBefore -and (Get-RecoveryHash $linkBefore) -cne $old.shortcut_sha256) { throw 'shortcut_changed' }
    } elseif ($null -ne $linkBefore) { throw 'shortcut_name_already_owned' }
    $changes = @()
    $hashes = [ordered]@{}
    foreach ($name in @('restore-codex-official-route.ps1','恢复官方默认路由.cmd')) {
        $path = Join-Path $bundle $name
        $before = Read-RecoveryBytes $path
        $after = Read-RecoveryBytes (Join-Path $PSScriptRoot $name)
        if ($null -eq $after) { throw 'recovery_source_missing' }
        if ($old) {
            if (-not $old.files.PSObject.Properties[$name] -or
                ($null -ne $before -and (Get-RecoveryHash $before) -cne $old.files.$name)) { throw 'recovery_file_changed' }
        } elseif ($null -ne $before) { throw 'recovery_ownership_missing' }
        $hashes[$name] = Get-RecoveryHash $after
        if ((Get-RecoveryHash $before) -cne $hashes[$name]) { $changes += @{name=$name; path=$path; before=$before; after=$after} }
    }
    [void][IO.Directory]::CreateDirectory($bundle)
    $target = Join-Path $bundle '恢复官方默认路由.cmd'
    $shell = New-Object -ComObject WScript.Shell
    if ($null -eq $linkBefore) {
        $temporaryLink = Join-Path $bundle ('candidate-' + [Guid]::NewGuid().ToString('N') + '.lnk')
        $link = $shell.CreateShortcut($temporaryLink)
        $link.TargetPath = $target
        $link.WorkingDirectory = $bundle
        $link.WindowStyle = 1
        $link.Description = 'Operator：恢复官方默认路由；先备份，保留账户和历史。'
        $link.Save()
        $linkAfter = Read-RecoveryBytes $temporaryLink
        $changes += @{name='shortcut.lnk'; path=$linkPath; before=$null; after=$linkAfter}
    } else { $linkAfter=$linkBefore }
    if ($changes.Count) {
        $receipt = @{schema_version=1; project=$project; shortcut=$linkPath;
            shortcut_sha256=(Get-RecoveryHash $linkAfter); files=$hashes}
        $changes += @{name='ownership.json'; path=$receiptPath; before=$receiptBefore;
            after=$script:RecoveryUtf8.GetBytes(($receipt | ConvertTo-Json -Depth 5))}
        # Keep originals and intent before replacing any owned file. An interrupted
        # unjournaled setup stops on its next attempt rather than adopting files.
        $backup = New-RecoveryBackup $bundle $changes
        foreach ($change in $changes) {
            if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -cne (Get-RecoveryHash $change.before)) { throw 'file_changed_during_setup' }
        }
        foreach ($change in $changes) { Write-RecoveryChange $change }
    }
    $verified = $shell.CreateShortcut($linkPath)
    if ($verified.TargetPath -ine $target -or $verified.Arguments -or $verified.WorkingDirectory -ine $bundle) { throw 'shortcut_verification_failed' }
    @{status='ready'; shortcut=$linkPath; changed=($changes.Count -gt 0); routing_changed=$false} | ConvertTo-Json -Compress
    exit 0
} catch {
    # No exception text: private paths or source data need not enter diagnostics.
    Write-Output '{"status":"stopped","reason":"recovery_shortcut_setup_failed","routing_changed":false}'
    exit 1
} finally {
    if ($temporaryLink -and (Test-Path -LiteralPath $temporaryLink)) { Remove-Item -LiteralPath $temporaryLink -Force }
    if ($owns) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
