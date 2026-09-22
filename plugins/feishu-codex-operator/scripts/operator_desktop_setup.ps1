#requires -Version 7.0
[CmdletBinding()]
param([ValidateSet('preview','install','restore','preview-migration','migrate','restore-migration')][string]$Action = 'preview',
      [Parameter(Mandatory=$true)][string]$ProjectRoot,
      [string]$StartupBundle, [string]$LegacyReceipt, [string]$ExpectedPlanSha256, [switch]$Library)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'operator_installation.psm1') -Force -DisableNameChecking
. (Join-Path $PSScriptRoot 'operator_entry_migration.ps1')

function Show-OperatorInstallationNotice {
    @'
初始化说明：将配置当前用户桌面和开始菜单的“Codex拓展入口”，并先保存同名原快捷方式。官方 Codex 入口保持独立。
Codex 已运行时只打开现有窗口；已配置的 Web 后台或本地模型同步在 Codex 完全退出后的启动时准备。
原生任务栏固定项可能需要手动重新固定。不会修改应用程序本体、默认模型、审批或沙箱设置。
安全卸载会按安装记录恢复入口、项目规则和 Hooks，遇到后续修改则停止并保留原件。
请先执行 operator uninstall 预览，再执行 operator uninstall -Apply 完成恢复，最后在 Desktop 移除插件。
直接删除插件不能保证恢复项目配置。任务、模型文件、凭据和业务数据会保留；卸载后保留一个只打开原生 Codex 的小启动程序，避免任务栏固定项失效。
'@ | Write-Output
}

function Install-OperatorDesktopEntry {
    param([string]$ProjectRoot, [string]$StartupBundle, [switch]$EntryMigration)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $bundle = Join-Path $project '.codex/operator-desktop-entry'
    Assert-OperatorPlainPath $bundle
    $targets = @(Get-OperatorDesktopPaths)
    if (Test-Path -LiteralPath (Join-Path $bundle 'Codex.exe')) {
        throw 'The previous launcher name requires a reviewed ownership migration before setup.'
    }
    # Upgrades must preserve later edits just as native-only reinstalls do.
    # Validate before publishing a new ownership generation or replacing files.
    $executable = Join-Path $bundle 'Codex拓展入口.exe'
    $entry = Join-Path $bundle 'operator_desktop_entry.ps1'
    $buildFile = Join-Path $bundle 'launcher-manifest.json'
    $configurationPath = Join-Path $bundle 'desktop-entry.json'
    if (@($executable,$entry,$buildFile,$configurationPath | Where-Object { Test-Path -LiteralPath $_ }).Count) {
        foreach ($path in @($executable,$entry,$buildFile,$configurationPath)) {
            Assert-OperatorPlainPath $path
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'The existing launcher build is incomplete; setup stopped.' }
        }
        if ((Get-Item -LiteralPath $buildFile).Length -gt 16384 -or
            (Get-Item -LiteralPath $configurationPath).Length -gt 16384) { throw 'Invalid existing launcher records.' }
        $oldBuild = Get-Content -LiteralPath $buildFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        $oldConfiguration = Get-Content -LiteralPath $configurationPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        if ($oldBuild.schema_version -ne 1 -or $oldBuild.native_fallback -cne 'native-only-v1' -or
            $oldBuild.binary_sha256 -cne (Get-OperatorFingerprint $executable) -or
            $oldBuild.entry_script_sha256 -cne (Get-OperatorFingerprint $entry) -or
            $oldConfiguration.schema_version -ne 1 -or $oldConfiguration.mode -notin @('native','reviewed_startup') -or
            $oldConfiguration.entry_script_sha256 -cne $oldBuild.entry_script_sha256) {
            throw 'The existing launcher changed; setup preserved it for review.'
        }
    }
    if ($EntryMigration) {
        $state = Get-OperatorEntryMigrationState $project
        if ($state.phase -cne 'installing') { throw 'Entry migration not prepared.' }
    } else {
        Start-OperatorInstallation -ProjectRoot $project -LinkPaths $targets
        $state = Get-OperatorOwnership $project
    }
    $nativeMarker = Join-Path $bundle 'native-only'
    $reactivate = Test-Path -LiteralPath $nativeMarker
    if ($reactivate) {
        Assert-OperatorPlainPath $nativeMarker
        if ($state.reactivate_native_launcher -ne $true) { throw 'Complete uninstall before reinstalling the launcher.' }
    }
    $packages = @(Get-AppxPackage -Name OpenAI.Codex)
    if ($packages.Count -ne 1) { throw 'Cannot identify the installed Codex package.' }
    $nativeRoot = [IO.Path]::GetFullPath($packages[0].InstallLocation).TrimEnd('\') + '\'
    $nativeExe = Join-Path $nativeRoot 'app/ChatGPT.exe'
    $shell = New-Object -ComObject WScript.Shell
    # Never adopt an unrelated shortcut merely because its filename says Codex.
    foreach ($target in $targets) {
        $fingerprint = Get-OperatorFingerprint $target
        if ($state.entries.Contains($target)) {
            $owned = $state.entries[$target]
            if ($owned.after -ceq $fingerprint -or
                ($owned.status -eq 'pending' -and $owned.previous -ceq $fingerprint)) { continue }
            throw 'Managed shortcut changed after installation; setup preserved it for review.'
        }
        if ($fingerprint -eq 'absent') { continue }
        $link = $shell.CreateShortcut($target)
        $native = $link.TargetPath -and [IO.Path]::GetFullPath($link.TargetPath).StartsWith($nativeRoot,[StringComparison]::OrdinalIgnoreCase)
        if (-not $native) { throw 'An existing Codex shortcut needs a reviewed ownership migration.' }
    }
    $configuration = @{schema_version=1; mode='native'}
    if (-not $reactivate -and (Test-Path -LiteralPath $configurationPath)) {
        $configuration = Get-Content -LiteralPath $configurationPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        if ($configuration.schema_version -ne 1 -or $configuration.mode -notin @('native','reviewed_startup')) { throw 'Desktop entry configuration changed.' }
    }
    if ($StartupBundle) {
        $workflow = [IO.Path]::GetFullPath($StartupBundle).TrimEnd('\')
        if ((Split-Path -Parent $workflow) -ine (Join-Path $project '.codex')) { throw 'Startup workflow must belong to this project.' }
        $plan = Get-Content -LiteralPath (Join-Path $workflow 'startup-sync-plan.json') -Raw -Encoding utf8 | ConvertFrom-Json
        $startupName = 'start-codex-with-lmstudio.ps1'
        if ($plan.schema_version -eq 2) {
            if ($plan.startup_script -cne 'start-codex-with-web.ps1') { throw 'Unknown startup workflow.' }
            $startupName = $plan.startup_script
        } elseif ($null -ne $plan.schema_version -and $plan.schema_version -ne 1) { throw 'Unknown startup workflow version.' }
        if ((Get-OperatorFingerprint (Join-Path $workflow $startupName)) -cne $plan.entry_files.$startupName) {
            throw 'Startup workflow digest changed.'
        }
        $configuration.mode = 'reviewed_startup'
        $configuration.startup_bundle = [IO.Path]::GetRelativePath($project,$workflow)
    }
    $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant())))
    $mutex = [Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-' + $hash))
    $owns = $false
    try {
        try { $owns = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owns = $true }
        if (-not $owns) { throw 'Desktop entry is busy; setup did not retry.' }
        New-Item -ItemType Directory -Force -Path $bundle | Out-Null
        $compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows C# compiler is unavailable.' }
        $candidate = Join-Path $bundle ('candidate-' + [Guid]::NewGuid().ToString('N') + '.exe')
        $icon = Join-Path $bundle 'Codex拓展入口.ico'
        if (-not (Test-Path -LiteralPath $icon)) {
            Add-Type -AssemblyName System.Drawing
            $nativeIcon = [Drawing.Icon]::ExtractAssociatedIcon($nativeExe)
            $stream = [IO.File]::Open($icon,[IO.FileMode]::CreateNew)
            try { $nativeIcon.Save($stream) } finally { $stream.Dispose(); $nativeIcon.Dispose() }
        }
        & $compiler /nologo /target:winexe /optimize+ /platform:anycpu /reference:System.Windows.Forms.dll "/win32icon:$icon" "/out:$candidate" (Join-Path $PSScriptRoot 'operator_desktop_entry.cs')
        if ($LASTEXITCODE -ne 0) { throw 'Desktop entry build failed.' }
        Write-OperatorAtomicBytes $entry ([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'operator_desktop_entry.ps1')))
        $configuration.entry_script_sha256 = Get-OperatorFingerprint $entry
        Write-OperatorAtomicBytes $configurationPath ([Text.UTF8Encoding]::new($false).GetBytes(($configuration | ConvertTo-Json)))
        [IO.File]::Move($candidate,$executable,$true)
        $build = @{schema_version=1; native_fallback='native-only-v1'; binary_sha256=(Get-OperatorFingerprint $executable);
                   entry_script_sha256=$configuration.entry_script_sha256}
        Write-OperatorAtomicBytes (Join-Path $bundle 'launcher-manifest.json') ([Text.UTF8Encoding]::new($false).GetBytes(($build | ConvertTo-Json)))
        foreach ($target in $targets) {
            $temporary = Join-Path $bundle ('shortcut-' + [Guid]::NewGuid().ToString('N') + '.lnk')
            try {
                $link = $shell.CreateShortcut($temporary)
                $link.TargetPath = $executable; $link.WorkingDirectory = $bundle
                $link.IconLocation = $icon + ',0'; $link.WindowStyle = 7
                $link.Description = 'Codex拓展入口：项目提供的独立启动器；已配置的模型同步在完全退出后启动时执行。'
                $link.Save()
                if ($EntryMigration) {
                    Set-OperatorEntryMigrationFile $project $target ([IO.File]::ReadAllBytes($temporary))
                } else {
                    Set-OperatorManagedFile -ProjectRoot $project -Path $target -Bytes ([IO.File]::ReadAllBytes($temporary)) -LinkPaths $targets
                }
            } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
        }
        if ($reactivate) { Remove-Item -LiteralPath $nativeMarker }
        return [pscustomobject]@{entry_installed=$true; mode=$configuration.mode; taskbar_pin_automatic=$false}
    } finally { if ($owns) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
}

if ($Library) { return }
switch ($Action) {
    'preview' { Get-OperatorRestorePlan $ProjectRoot @(Get-OperatorDesktopPaths -IncludeLegacy) | ConvertTo-Json -Depth 6 }
    'install' { Show-OperatorInstallationNotice; Install-OperatorDesktopEntry $ProjectRoot $StartupBundle | ConvertTo-Json }
    'restore' { throw 'Use operator uninstall so routing is detached before restoring the entry.' }
    'preview-migration' { Get-OperatorEntryMigrationPlan $ProjectRoot $LegacyReceipt $StartupBundle | ConvertTo-Json -Depth 10 }
    'migrate' {
        Write-Output '本次只迁移当前用户的 Codex拓展入口，保留迁移前快捷方式原件及缺失状态。不会重建旧运行时、规则或 Hooks 的初装归属，不更改模型路由；任务栏可能需要手动重新固定。可用 restore-migration 单独恢复入口；完整卸载仍需处理旧安装记录。'
        Invoke-OperatorEntryMigration $ProjectRoot $LegacyReceipt $StartupBundle $ExpectedPlanSha256 | ConvertTo-Json
    }
    'restore-migration' { Restore-OperatorEntryMigration $ProjectRoot | ConvertTo-Json }
}
