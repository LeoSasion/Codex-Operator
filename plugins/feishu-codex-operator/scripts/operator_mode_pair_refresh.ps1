#requires -Version 7.0
# Internal transaction applier. The Python maintenance controller holds the
# isolated-home lock and exclusively reserves its stopped router port.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('preview','apply')][string]$Action,
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$StageDirectory,
    [string]$ExpectedPlanSha256
)
$ErrorActionPreference='Stop'
$utf8=[Text.UTF8Encoding]::new($false,$true)
Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_upgrade.psm1') -DisableNameChecking
$legacy=Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -PassThru -DisableNameChecking

function Read-BoundBytes([string]$Path) {
    return ,(& $legacy {param($P) Read-LegacyPairBytes $P} $Path)
}
function Hash-BoundBytes([byte[]]$Bytes) {
    return & $legacy {param($B) Get-LegacyPairHash $B} $Bytes
}
function Read-BoundJson([string]$Path) {
    return & $legacy {param($P) Get-LegacyPairJson $P} $Path
}
function Encode-BoundJson($Value) {
    return ,(& $legacy {param($V) ConvertTo-LegacyPairBytes $V} $Value)
}
function Get-BoundOfficialPackage {
    $packages=@(Get-AppxPackage -Name OpenAI.Codex)
    if ($packages.Count -ne 1) {throw 'mode_pair_package_ambiguous'}
    $package=$packages[0]
    [xml]$xml=Get-Content -LiteralPath (Join-Path $package.InstallLocation 'AppxManifest.xml') -Raw
    $apps=@($xml.Package.Applications.Application|Where-Object {$_.Id -ceq 'App'})
    if ($xml.Package.Identity.Name -cne 'OpenAI.Codex' -or $apps.Count -ne 1 -or
        $apps[0].Executable -cne 'app/ChatGPT.exe' -or $apps[0].EntryPoint -cne 'Windows.FullTrustApplication') {
        throw 'mode_pair_package_identity_changed'
    }
    $executable=Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    return @{full_name=$package.PackageFullName;family=$package.PackageFamilyName;
        version=$package.Version.ToString();executable=$executable;
        executable_sha256=(Hash-BoundBytes (Read-BoundBytes $executable))}
}
function Assert-BoundPackageUpdate($Update,$Previous) {
    if ($Update -isnot [Collections.IDictionary] -or
        @(Compare-Object @($Update.Keys|Sort-Object) @('contract','before','after','onboarding'|Sort-Object)).Count -or
        $Update.contract -cne 'operator_mode_official_package_update_v1' -or
        -not (& $legacy {param($A,$B) Test-LegacyPairEqual $A $B} $Update.before $Previous)) {
        throw 'mode_pair_package_update_invalid'
    }
    foreach ($package in @($Update.before,$Update.after)) {
        if ($package -isnot [Collections.IDictionary] -or
            @(Compare-Object @($package.Keys|Sort-Object) @('full_name','family','version','executable','executable_sha256'|Sort-Object)).Count -or
            $package.family -cnotmatch '^OpenAI\.Codex_[a-z0-9]+$' -or
            $package.version -cnotmatch '^[0-9]+(\.[0-9]+){3}$' -or
            $package.full_name -cne ('OpenAI.Codex_'+$package.version+'_x64__'+$package.family.Split('_',2)[1]) -or
            $package.executable_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'mode_pair_package_update_invalid'}
    }
    $onboarding=@{contract='operator_desktop_welcome_preference_20261002_v1';supported=$false;preferences=@{}}
    if ($Update.before.family -cne $Update.after.family -or
        [version]$Update.after.version -le [version]$Update.before.version -or
        -not (& $legacy {param($A,$B) Test-LegacyPairEqual $A $B} $Update.onboarding $onboarding) -or
        -not (& $legacy {param($A,$B) Test-LegacyPairEqual $A $B} $Update.after (Get-BoundOfficialPackage))) {
        throw 'mode_pair_package_update_changed'
    }
}
function Get-BoundReview {
    $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $stage=[IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
    if ((Split-Path -Parent $stage) -ine (Join-Path $rootPath 'pair-refreshes') -or
        (Split-Path -Leaf $stage) -cnotmatch '^[a-f0-9]{32}$') {throw 'mode_pair_stage_scope_invalid'}
    $manifest=Read-BoundJson (Join-Path $stage 'prepared.json')
    if ($manifest.contract -cne 'operator_mode_bound_pair_refresh_v1' -or $manifest.root -cne $rootPath -or
        $manifest.generation -cne (Split-Path -Leaf $stage)) {throw 'mode_pair_stage_invalid'}
    $entry=Read-BoundJson (Join-Path $stage 'staged/entry.json')
    $project=$entry.project;$pairRoot=Join-Path $project '.codex/operator-desktop-pair'
    if ($entry.root -cne $rootPath -or $entry.native_enabled -ne $false -or
        $rootPath -ine (Join-Path $project ('.codex/operator-mode-entry/'+(Split-Path -Leaf $rootPath)))) {throw 'mode_pair_entry_invalid'}
    $old=Get-OperatorDesktopLegacyPairState $project -CheckCurrent
    if ($old.phase -cne 'installed' -or $old.scope -cne 'legacy_entry_only' -or
        $old.steps[-1].workflow.contract -cne 'operator_isolated_mode_entry_v1' -or
        $old.steps[-1].workflow.path -cne $rootPath) {throw 'mode_pair_installed_owner_required'}
    $bundle=Join-Path $project '.codex/operator-desktop-entry'
    $config=Read-BoundJson (Join-Path $bundle 'desktop-entry.json')
    if ($config.mode_entry_sha256 -cne $manifest.files.'entry.json'.before -or
        $old.steps[-1].workflow.entry_plan_sha256 -cne $config.mode_entry_sha256) {throw 'mode_pair_baseline_changed'}
    $expected=@('entry.json','entry.ps1','operator-mode-host.exe','operator-mode-native.exe','operator-mode-picker.exe')
    if ($manifest.ContainsKey('backend_update')) {
        $update=$manifest.backend_update
        if (@(Compare-Object @($update.Keys|Sort-Object) @('registry_file','registry_sha256','catalog_sha256','web'|Sort-Object)).Count -or
            $update.registry_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $update.catalog_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $manifest.files.'router/registry.json'.after -cne $update.registry_sha256 -or
            $manifest.files.'home/models.json'.after -cne $update.catalog_sha256) {throw 'mode_pair_backend_invalid'}
        $expected+=@('router/registry.json','home/models.json')
    }
    if (@(Compare-Object @($manifest.files.Keys|Sort-Object) @($expected|Sort-Object)).Count) {throw 'mode_pair_files_invalid'}
    $checks=[ordered]@{}
    $checks[(Join-Path $stage 'prepared.json')]=Hash-BoundBytes (Read-BoundBytes (Join-Path $stage 'prepared.json'))
    $checks[(Join-Path $pairRoot 'ownership.json')]=Hash-BoundBytes (Read-BoundBytes (Join-Path $pairRoot 'ownership.json'))
    foreach ($name in $expected) {
        $row=$manifest.files[$name]
        if ($row.before -cnotmatch '^[a-f0-9]{64}$' -or $row.after -cnotmatch '^[a-f0-9]{64}$' -or
            (Hash-BoundBytes (Read-BoundBytes (Join-Path $rootPath $name))) -cne $row.before -or
            (Hash-BoundBytes (Read-BoundBytes (Join-Path $stage ('staged/'+$name)))) -cne $row.after -or
            (Hash-BoundBytes (Read-BoundBytes (Join-Path $stage ('originals/'+$name)))) -cne $row.before) {throw 'mode_pair_stage_changed'}
        $checks[(Join-Path $rootPath $name)]=$row.before
        $checks[(Join-Path $stage ('staged/'+$name))]=$row.after
        $checks[(Join-Path $stage ('originals/'+$name))]=$row.before
    }
    $expectedEntry=Read-BoundJson (Join-Path $rootPath 'entry.json')
    $expectedEntry.entry_sha256=$manifest.files.'entry.ps1'.after
    $expectedEntry.source_bindings=$entry.source_bindings
    $expectedEntry.compiled=@{}
    foreach ($name in @('operator-mode-host.exe','operator-mode-native.exe','operator-mode-picker.exe')) {
        $expectedEntry.compiled[$name]=$manifest.files[$name].after
    }
    if ($manifest.ContainsKey('backend_update')) {
        $expectedEntry.registry_sha256=$manifest.backend_update.registry_sha256
        $expectedEntry.catalog_sha256=$manifest.backend_update.catalog_sha256
        if ($null -ne $manifest.backend_update.web) {$expectedEntry.web=$manifest.backend_update.web}
    }
    if ($manifest.ContainsKey('package_update')) {
        Assert-BoundPackageUpdate $manifest.package_update $expectedEntry.package
        $expectedEntry.package=$manifest.package_update.after
        $expectedEntry.onboarding=$manifest.package_update.onboarding
        if ($manifest.protected_files[$expectedEntry.package.executable] -cne $expectedEntry.package.executable_sha256) {
            throw 'mode_pair_package_protection_missing'
        }
    }
    if (-not (& $legacy {param($A,$B) Test-LegacyPairEqual $A $B} $expectedEntry $entry)) {throw 'mode_pair_descriptor_changed'}
    foreach ($path in $manifest.protected_files.Keys) {$checks[$path]=$manifest.protected_files[$path]}
    foreach ($name in $entry.source_bindings.Keys) {
        $sourceRoot=[IO.Path]::GetFullPath((Join-Path $project 'plugins/feishu-codex-operator/scripts'))
        $sourcePath=[IO.Path]::GetFullPath((Join-Path $sourceRoot $name))
        if (-not $sourcePath.StartsWith($sourceRoot+'\',[StringComparison]::OrdinalIgnoreCase)) {throw 'mode_pair_source_scope_invalid'}
        $checks[$sourcePath]=$entry.source_bindings[$name]
    }
    foreach ($name in $old.build.Keys) {$checks[(Join-Path $bundle $name)]=$old.build[$name]}
    foreach ($path in $old.links.Keys) {$checks[$path]=$old.links[$path].after}
    foreach ($name in $old.files.Keys) {$checks[(Join-Path $pairRoot ('generations/'+$old.generation+'/'+$name))]=$old.files[$name]}
    $checks[(Join-Path $project '.codex/operator-entry-migration/journal.json')]=$old.origin.migration_sha256
    foreach ($name in @('operator_desktop_pair_upgrade.psm1','operator_desktop_pair_legacy.psm1','operator_mode_pair_refresh.ps1')) {
        $checks[(Join-Path $PSScriptRoot $name)]=Hash-BoundBytes (Read-BoundBytes (Join-Path $PSScriptRoot $name))
    }
    $plan=[ordered]@{contract='operator_mode_bound_pair_refresh_v1';project=$project;root=$rootPath;
        stage=$stage;generation=$manifest.generation;checks=$checks;runtime_ownership='unresolved'}
    $sha=& $legacy {param($P) & $script:LegacyUpgrade {param($V) Get-OperatorPairPreviewHash $V} $P} $plan
    return @{plan=$plan;sha256=$sha;old=$old;entry=$entry;config=$config;manifest=$manifest}
}
function Assert-BoundReview($Review) {
    if ($Review.manifest.ContainsKey('package_update')) {
        Assert-BoundPackageUpdate $Review.manifest.package_update $Review.manifest.package_update.before
    }
    foreach ($path in $Review.plan.checks.Keys) {
        if ((Hash-BoundBytes (Read-BoundBytes $path)) -cne $Review.plan.checks[$path]) {throw 'mode_pair_preview_changed'}
    }
}

try {
    $review=Get-BoundReview
    Assert-BoundReview $review
    if ($Action -ceq 'preview') {
        $probeKey=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($utf8.GetBytes($review.plan.project.ToLowerInvariant())))
        $probe=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$probeKey));$probeOwned=$false
        try {
            try {$probeOwned=$probe.WaitOne(0)} catch [Threading.AbandonedMutexException] {$probeOwned=$true}
            if (-not $probeOwned) {throw 'mode_pair_entry_busy'}
        } finally {if ($probeOwned) {$probe.ReleaseMutex()};$probe.Dispose()}
        @{phase='pair_refresh_ready';preview_sha256=$review.sha256;native_config_writes=0;desktop_launch=$false}|ConvertTo-Json -Compress
        exit 0
    }
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $ExpectedPlanSha256 -cne $review.sha256) {throw 'mode_pair_preview_changed'}
    $plan=$review.plan;$project=$plan.project;$pairRoot=Join-Path $project '.codex/operator-desktop-pair'
    $mutexKey=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($utf8.GetBytes($project.ToLowerInvariant())))
    $mutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$mutexKey));$owns=$false;$pairLock=$null
    try {
        try {$owns=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$owns=$true}
        if (-not $owns) {throw 'mode_pair_entry_busy'}
        $pairLock=[IO.File]::Open((Join-Path $pairRoot 'transaction.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        Assert-BoundReview $review
        $old=$review.old;$generation=Join-Path $pairRoot ('generations/'+$plan.generation)
        if (Test-Path -LiteralPath $generation) {throw 'mode_pair_generation_consumed'}
        & $legacy {param($P) New-LegacyPairDirectory $P} $generation
        foreach ($name in $old.files.Keys) {
            [IO.File]::WriteAllBytes((Join-Path $generation $name),
                (Read-BoundBytes (Join-Path $pairRoot ('generations/'+$old.generation+'/'+$name))))
        }
        $config=$review.config
        $config.mode_entry_sha256=$review.manifest.files.'entry.json'.after
        $configBytes=Encode-BoundJson $config
        [IO.File]::WriteAllBytes((Join-Path $generation 'entry-config.after.json'),$configBytes)
        [IO.File]::WriteAllBytes((Join-Path $generation 'isolated-entry.after.json'),(Read-BoundBytes (Join-Path $plan.stage 'staged/entry.json')))
        $changes=@();$build=@{};$bundle=Join-Path $project '.codex/operator-desktop-entry'
        foreach ($name in $old.build.Keys) {
            $path=Join-Path $bundle $name
            $bytes=if ($name -ceq 'desktop-entry.json') {$configBytes} else {Read-BoundBytes $path}
            $build[$name]=Hash-BoundBytes $bytes
            if ($name -cne 'Codex拓展入口.ico') {$changes+=@{path=$path;before=(Read-BoundBytes $path);after=[byte[]]$bytes}}
        }
        $workflow=@{contract='operator_isolated_mode_entry_v1';path=$plan.root;
            entry_plan_sha256=$config.mode_entry_sha256;entry_script_sha256=$config.entry_script_sha256}
        $record=Read-BoundJson (Join-Path $pairRoot 'ownership.json')
        $record.steps=@($record.steps)+@{generation=$plan.generation;before=$old.build;after=$build;workflow=$workflow}
        $record.generation=$plan.generation;$record.transaction=$plan.generation;$record.build=$build
        # Native link bytes and their original helper generation remain intact.
        # The copied helper files retain the existing receipt's exact hashes.
        $modeFiles=@('operator-mode-host.exe','operator-mode-picker.exe','operator-mode-native.exe','entry.ps1')
        if ($review.manifest.ContainsKey('backend_update')) {$modeFiles+=@('router/registry.json','home/models.json')}
        $modeFiles+=@('entry.json')
        foreach ($name in $modeFiles) {
            $changes+=@{path=(Join-Path $plan.root $name);before=(Read-BoundBytes (Join-Path $plan.root $name));
                after=(Read-BoundBytes (Join-Path $plan.stage ('staged/'+$name)))}
        }
        $receipt=Join-Path $pairRoot 'ownership.json'
        $changes+=@{path=$receipt;before=(Read-BoundBytes $receipt);after=(Encode-BoundJson $record)}
        $boundary={
            Assert-BoundReview $review
            foreach ($name in $old.files.Keys) {
                if ((Hash-BoundBytes (Read-BoundBytes (Join-Path $generation $name))) -cne $old.files[$name]) {throw 'mode_pair_helper_changed'}
            }
            if ((Hash-BoundBytes (Read-BoundBytes (Join-Path $generation 'entry-config.after.json'))) -cne $build['desktop-entry.json'] -or
                (Hash-BoundBytes (Read-BoundBytes (Join-Path $generation 'isolated-entry.after.json'))) -cne $config.mode_entry_sha256) {throw 'mode_pair_backup_changed'}
        }
        Invoke-OperatorEntryExactTransaction -TransactionRoot (Join-Path $pairRoot ('upgrades/'+$plan.generation)) -Changes $changes -Boundary $boundary
        Get-OperatorDesktopLegacyPairState $project -CheckCurrent | Out-Null
        @{phase='pair_refreshed';generation=$plan.generation;native_config_writes=0;desktop_launch=$false;
            legacy_receipts_preserved=$true;runtime_ownership='unresolved'}|ConvertTo-Json -Compress
    } finally {if ($pairLock) {$pairLock.Dispose()};if ($owns) {$mutex.ReleaseMutex()};$mutex.Dispose()}
} catch {
    $reason=$_.Exception.Message
    if ($reason -cnotmatch '^[a-z][a-z0-9_]{1,127}$') {$reason='mode_pair_refresh_failed'}
    @{phase='failed';reason=$reason;automatically_retried=$false}|ConvertTo-Json -Compress
    exit 1
}
