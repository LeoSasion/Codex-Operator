#requires -Version 7.0
[CmdletBinding()]
param([ValidateSet('preview','install','restore','preview-migration','migrate','restore-migration',
        'preview-entry-upgrade','upgrade-entry','preview-shortcut-adoption','adopt-shortcut',
        'preview-pair','install-pair','pair-status','restore-pair','prepare-pair-build','preview-pair-upgrade','upgrade-pair')][string]$Action = 'preview',
      [Parameter(Mandatory=$true)][string]$ProjectRoot,
      [string]$StartupBundle, [string]$LegacyReceipt, [string]$ExpectedPlanSha256,
      [string]$CodexHome, [string]$RecoveryReceipt, [switch]$OwnerApprovedShortcutAdoption,
      [string]$CandidateDirectory, [string]$BuildDate, [string]$DirectPickerPath, [string]$IsolatedModePath,
      [ValidateRange(1024,65535)][int]$RouterPort = 4317,
      [switch]$Library)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'operator_installation.psm1') -Force -DisableNameChecking
. (Join-Path $PSScriptRoot 'operator_entry_migration.ps1')
. (Join-Path $PSScriptRoot 'operator_entry_shortcut_adoption.ps1')
. (Join-Path $PSScriptRoot 'operator_entry_upgrade.ps1')

function Show-OperatorInstallationNotice {
    @'
初始化说明：新安装在当前用户桌面提供“ChatGPT 原生入口”和“ChatGPT 拓展模型 MM-DD 入口”；日期来自成功构建记录。同名未知快捷方式会保留并停止安装。
已有“Codex拓展入口”安装按原归属记录维护，不自动改名。原生入口核对配置，切换路由时需先正常退出；两个入口不表示可同时运行两种模式。
Codex 已运行时只打开现有窗口；已配置的 Web 后台或本地模型同步在 Codex 完全退出后的启动时准备。
原生任务栏固定项可能需要手动重新固定。不会修改应用程序本体、默认模型、审批或沙箱设置。
安全卸载会按安装记录恢复入口、项目规则和 Hooks，遇到后续修改则停止并保留原件。
请先执行 operator uninstall 预览，再执行 operator uninstall -Apply 完成恢复，最后在 Desktop 移除插件。
直接删除插件不能保证恢复项目配置。任务、模型文件、凭据和业务数据会保留；卸载后保留一个只打开原生 Codex 的小启动程序，避免任务栏固定项失效。
'@ | Write-Output
}

function Install-OperatorDesktopEntry {
    param([string]$ProjectRoot, [string]$StartupBundle, [switch]$EntryMigration, [switch]$NoShortcuts)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $bundle = Join-Path $project '.codex/operator-desktop-entry'
    Assert-OperatorPlainPath $bundle
    $targets = @(Get-OperatorDesktopPaths)
    $pairRoot = Join-Path $project '.codex/operator-desktop-pair'
    if (Test-Path -LiteralPath $pairRoot) {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
        $pair = Get-OperatorDesktopPairRestorePlan -ProjectRoot $project
        if ($pair.status -ne 'restored') {
            throw 'The desktop pair owns this build; use its reviewed maintenance path before replacing it.'
        }
    }
    if ($NoShortcuts) {
        # Prepare the internal launcher for a new separately owned entry pair.
        # Never erase/skip ownership checks for an already installed launcher.
        $reactivatingPair = (Test-Path -LiteralPath $pairRoot) -and
            (Test-Path -LiteralPath (Join-Path $bundle 'native-only')) -and
            (Get-OperatorOwnership $project).reactivate_native_launcher -eq $true
        if ($EntryMigration -or ((Test-Path -LiteralPath $bundle) -and -not $reactivatingPair) -or
            @($targets | Where-Object { Test-Path -LiteralPath $_ }).Count) {
            throw 'Shortcut-free launcher preparation requires a fresh installation.'
        }
        $targets = @()
    }
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
    $pluginVersion = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '../.codex-plugin/plugin.json') -Raw -Encoding utf8 | ConvertFrom-Json).version
    if ($pluginVersion -isnot [string] -or $pluginVersion -cnotmatch '\A[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\z') {
        throw 'The source plugin version is unavailable.'
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
        $sourceDigestInput = (Get-OperatorFingerprint (Join-Path $PSScriptRoot 'operator_desktop_entry.cs')) + "`n" +
            $configuration.entry_script_sha256
        $build = @{schema_version=1; native_fallback='native-only-v1'; binary_sha256=(Get-OperatorFingerprint $executable);
                   entry_script_sha256=$configuration.entry_script_sha256; build_date=[DateTime]::Now.ToString('yyyy-MM-dd');
                   shortcut_layout=$(if ($NoShortcuts) {'paired'} else {'legacy'});
                   product_version=$pluginVersion; source_sha256=[Convert]::ToHexString(
                       [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($sourceDigestInput))).ToLowerInvariant()}
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
        if ($reactivate) {
            Remove-Item -LiteralPath $nativeMarker
            if (-not $EntryMigration) {
                $completedState=Get-OperatorOwnership $project
                $completedState.reactivate_native_launcher=$false
                & (Get-Module operator_installation) {
                    param($Project,$State)
                    Save-OperatorOwnership $Project $State
                } $project $completedState
            }
        }
        return [pscustomobject]@{entry_installed=$true; mode=$configuration.mode; taskbar_pin_automatic=$false}
    } finally { if ($owns) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
}

function Get-OperatorPairArguments {
    param([string]$ProjectRoot, [string]$CodexHome)
    if (-not $CodexHome) {
        $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    }
    $manifest = Join-Path $ProjectRoot '.codex/operator-desktop-entry/launcher-manifest.json'
    Assert-OperatorPlainPath $manifest
    if ((Get-Item -LiteralPath $manifest).Length -gt 16384) { throw 'Invalid entry build record.' }
    $built = Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    return @{ProjectRoot=$ProjectRoot;CodexHome=$CodexHome;BuildDate=$built.build_date;
        Version=$built.product_version;SourceDigest=$built.source_sha256}
}

function Install-OperatorDesktopExperience {
    param([string]$ProjectRoot, [string]$StartupBundle, [string]$CodexHome, [switch]$PairOnly)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $bundle = Join-Path $project '.codex/operator-desktop-entry'
    $pairRoot = Join-Path $project '.codex/operator-desktop-pair'
    $pairedBuild = Test-OperatorPairedBuild $project
    if ((Test-Path -LiteralPath $bundle) -and -not (Test-Path -LiteralPath $pairRoot) -and -not $pairedBuild -and -not $PairOnly) {
        # Historical installations retain their exact names and ownership.
        return Install-OperatorDesktopEntry -ProjectRoot $project -StartupBundle $StartupBundle
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
    if (-not $CodexHome) { $CodexHome=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    Assert-OperatorDesktopPairEnvironment -ProjectRoot $project -CodexHome $CodexHome
    if (-not (Test-Path -LiteralPath $bundle)) {
        Install-OperatorDesktopEntry -ProjectRoot $project -StartupBundle $StartupBundle -NoShortcuts | Out-Null
    } elseif ($StartupBundle) {
        $current = Get-Content -LiteralPath (Join-Path $bundle 'desktop-entry.json') -Raw -Encoding utf8 | ConvertFrom-Json
        if ($current.mode -ne 'reviewed_startup' -or -not $current.startup_bundle -or
            [IO.Path]::GetFullPath((Join-Path $project $current.startup_bundle)) -ine [IO.Path]::GetFullPath($StartupBundle)) {
            throw 'A desktop-pair workflow change requires reviewed entry maintenance.'
        }
    }
    if (Test-Path -LiteralPath (Join-Path $bundle 'native-only')) {
        Start-OperatorInstallation -ProjectRoot $project -LinkPaths @(Get-OperatorDesktopPaths -IncludeLegacy)
        Install-OperatorDesktopEntry -ProjectRoot $project -StartupBundle $StartupBundle -NoShortcuts | Out-Null
    }
    $pairArguments = Get-OperatorPairArguments $project $CodexHome
    return Install-OperatorDesktopPair @pairArguments
}

function Test-OperatorPairedBuild {
    param([string]$ProjectRoot)
    $manifest=Join-Path $ProjectRoot '.codex/operator-desktop-entry/launcher-manifest.json'
    Assert-OperatorPlainPath $manifest
    if (-not (Test-Path -LiteralPath $manifest)) { return $false }
    if ((Get-Item -LiteralPath $manifest).Length -gt 16384) { throw 'Invalid entry build record.' }
    $built=Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($built.ContainsKey('shortcut_layout') -and $built.shortcut_layout -notin @('paired','legacy')) {
        throw 'Unknown desktop shortcut layout; preserved for review.'
    }
    return $built['shortcut_layout'] -ceq 'paired'
}

function Assert-OperatorDesktopExperiencePreflight {
    param([string]$ProjectRoot, [string]$CodexHome)
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.codex/operator-desktop-entry')) -or
        (Test-OperatorPairedBuild $ProjectRoot)) {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
        if (-not $CodexHome) { $CodexHome=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
        Assert-OperatorDesktopPairEnvironment -ProjectRoot $ProjectRoot -CodexHome $CodexHome
    }
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.codex/operator-desktop-pair')) {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
        $pairState = Get-OperatorDesktopPairRestorePlan -ProjectRoot $ProjectRoot
        if ($pairState.status -eq 'ready') {
            $pairArguments = Get-OperatorPairArguments $ProjectRoot $CodexHome
            Get-OperatorDesktopPairPlan @pairArguments | Out-Null
        }
    }
}

function Restore-OperatorDesktopExperience {
    param([string]$ProjectRoot, [string]$CodexHome, [int]$RouterPort = 4317)
    Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
    $pairState = Get-OperatorDesktopPairRestorePlan -ProjectRoot $ProjectRoot
    if ($pairState.status -in @('not_installed','restored')) {
        return Restore-OperatorDesktopPair -ProjectRoot $ProjectRoot
    }
    if ($CodexHome -and [IO.Path]::GetFullPath($CodexHome).TrimEnd('\') -ine $pairState.record.home) {
        throw 'The desktop pair belongs to another native home.'
    }
    $nativeHome = $pairState.record.home
    # Entry-only restoration precedes legacy migration/runtime recovery. Reuse
    # all route/service/request checks without claiming runtime ownership.
    $operatorPath=Join-Path $ProjectRoot '.codex/feishu-codex-operator-runtime/operator_main.py'
    $running=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python' -and $_.CommandLine -and
        $_.CommandLine.Replace('/','\').IndexOf($operatorPath,[StringComparison]::OrdinalIgnoreCase) -ge 0})
    if ($running.Count) {throw 'Stop the exact Operator before restoring its desktop pair.'}
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -DisableNameChecking
    $python=Get-OperatorPython -Required
    $preflightOutput=& $python.Source @($python.Prefix) -B (Join-Path $PSScriptRoot 'operator_uninstall.py') `
        inspect-entry --project-root $ProjectRoot --codex-config (Join-Path $nativeHome 'config.toml') --port $RouterPort
    if ($LASTEXITCODE -ne 0) { throw 'Desktop pair restoration requires the existing routing/lifecycle recovery first.' }
    $preflight = $preflightOutput | ConvertFrom-Json
    if ($preflight.owned_router_entry -or $preflight.pending_callbacks -or $preflight.active_router_requests) {
        throw 'Detach the reviewed route and finish pending work before restoring the desktop pair.'
    }
    $nativeOutput = & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -NonInteractive -File `
        (Join-Path $PSScriptRoot 'restore-codex-official-route.ps1') -ProjectRoot $ProjectRoot -CodexHome $nativeHome -Json
    if ($LASTEXITCODE -ne 0) { throw 'The native route could not be verified; desktop entries were preserved.' }
    $native = $nativeOutput | ConvertFrom-Json
    if ($native.status -ne 'preview' -or $native.route_before -ne 'native' -or @($native.warnings).Count) {
        throw 'Recover the official route before restoring the desktop pair.'
    }
    return Restore-OperatorDesktopPair -ProjectRoot $ProjectRoot
}

if ($Library) { return }
# The reviewed CLI envelope includes Chinese notices before its JSON result.
# A detached Windows parent may inherit a legacy console code page; bind this
# invocation's output bytes without changing the library caller's environment.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
switch ($Action) {
    'preview' { Get-OperatorRestorePlan $ProjectRoot @(Get-OperatorDesktopPaths -IncludeLegacy) | ConvertTo-Json -Depth 6 }
    'install' { Show-OperatorInstallationNotice; Install-OperatorDesktopExperience $ProjectRoot $StartupBundle $CodexHome | ConvertTo-Json }
    'install-pair' { Show-OperatorInstallationNotice; Install-OperatorDesktopExperience $ProjectRoot $StartupBundle $CodexHome -PairOnly | ConvertTo-Json }
    'preview-pair' {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.codex/operator-desktop-entry'))) {
            @{status='launcher_preparation_required';configuration_changed=$false} | ConvertTo-Json
        } else {
            $pairArguments = Get-OperatorPairArguments $ProjectRoot $CodexHome
            Get-OperatorDesktopPairPlan @pairArguments | ConvertTo-Json -Depth 12
        }
    }
    'pair-status' {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -Force -DisableNameChecking
        Get-OperatorDesktopPairRestorePlan -ProjectRoot $ProjectRoot | ConvertTo-Json -Depth 12
    }
    'restore-pair' {
        Restore-OperatorDesktopExperience $ProjectRoot $CodexHome $RouterPort | ConvertTo-Json
    }
    'prepare-pair-build' {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_upgrade.psm1') -DisableNameChecking
        New-OperatorEntryBuildCandidate -ProjectRoot $ProjectRoot -BuildDate $BuildDate -DirectPickerPath $DirectPickerPath -IsolatedModePath $IsolatedModePath | ConvertTo-Json
    }
    'preview-pair-upgrade' {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_upgrade.psm1') -DisableNameChecking
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.codex/operator-entry-migration')) {
            Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -DisableNameChecking
            $review=Get-OperatorDesktopLegacyPairPlan -ProjectRoot $ProjectRoot -CandidateDirectory $CandidateDirectory -CodexHome $CodexHome
        } else {$review=Get-OperatorDesktopPairUpgrade -ProjectRoot $ProjectRoot -CandidateDirectory $CandidateDirectory}
        @{status='reviewed_preview';plan_sha256=$review.sha256;scope=$review.plan.scope;candidate_directory=$CandidateDirectory;
            build_date=$review.candidate.record.build_date;routing_changed=$false;configuration_changed=$false} | ConvertTo-Json
    }
    'upgrade-pair' {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_upgrade.psm1') -DisableNameChecking
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.codex/operator-entry-migration')) {
            Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -DisableNameChecking
            Write-Output '本次保留旧入口回执及运行时未决归属，将原桌面入口同目录改名为构建日期入口，并新增独立原生入口。开始菜单原文件保持不变，原生辅助文件保留给任务栏；不改变模型路由。'
            Invoke-OperatorDesktopLegacyPair -ProjectRoot $ProjectRoot -CandidateDirectory $CandidateDirectory -ExpectedPlanSha256 $ExpectedPlanSha256 -CodexHome $CodexHome | ConvertTo-Json
        } else {Invoke-OperatorDesktopPairUpgrade -ProjectRoot $ProjectRoot -CandidateDirectory $CandidateDirectory -ExpectedPlanSha256 $ExpectedPlanSha256 | ConvertTo-Json}
    }
    'restore' { throw 'Use operator uninstall so routing is detached before restoring the entry.' }
    'preview-migration' { Get-OperatorEntryMigrationPlan $ProjectRoot $LegacyReceipt $StartupBundle | ConvertTo-Json -Depth 10 }
    'migrate' {
        Write-Output '本次只迁移当前用户的 Codex拓展入口，保留迁移前快捷方式原件及缺失状态。不会重建旧运行时、规则或 Hooks 的初装归属，不更改模型路由；任务栏可能需要手动重新固定。可用 restore-migration 单独恢复入口；完整卸载仍需处理旧安装记录。'
        Invoke-OperatorEntryMigration $ProjectRoot $LegacyReceipt $StartupBundle $ExpectedPlanSha256 | ConvertTo-Json
    }
    'restore-migration' { Restore-OperatorEntryMigration $ProjectRoot | ConvertTo-Json }
    'preview-entry-upgrade' {
        $review = Get-OperatorEntryUpgradePlan $ProjectRoot $StartupBundle $CodexHome $RecoveryReceipt
        [ordered]@{status='reviewed_preview'; plan_sha256=$review.sha256;
            before_sha256=$review.plan.before_sha256; after_sha256=$review.plan.after_sha256;
            config_changed=$false; routing_changed=$false; runtime_ownership='unresolved'} | ConvertTo-Json
    }
    'upgrade-entry' {
        Invoke-OperatorEntryUpgrade $ProjectRoot $StartupBundle $ExpectedPlanSha256 $CodexHome $RecoveryReceipt | ConvertTo-Json
    }
    'preview-shortcut-adoption' {
        $review = Get-OperatorEntryShortcutAdoptionPlan $ProjectRoot $CodexHome
        [ordered]@{status='reviewed_preview';plan_sha256=$review.sha256;
            difference=$review.summary;shortcut_changed=$false;configuration_changed=$false;
            routing_changed=$false;runtime_ownership='unresolved'} | ConvertTo-Json -Depth 5
    }
    'adopt-shortcut' {
        Invoke-OperatorEntryShortcutAdoption $ProjectRoot $CodexHome $ExpectedPlanSha256 -OwnerApprovedShortcutAdoption:$OwnerApprovedShortcutAdoption | ConvertTo-Json
    }
}
