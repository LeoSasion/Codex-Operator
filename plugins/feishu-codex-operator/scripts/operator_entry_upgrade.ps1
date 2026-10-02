#requires -Version 7.0
# A separate one-shot config attachment for a reviewed entry-only migration.
# It never claims runtime, Hook, rule, or first-install shortcut ownership.
function Get-OperatorEntryUpgradePlan {
    param([string]$ProjectRoot, [string]$StartupBundle, [string]$CodexHome,
          [string]$RecoveryReceipt, [switch]$IgnoreExisting)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $private = Join-Path $project '.codex'
    $bundle = Join-Path $private 'operator-desktop-entry'
    $workflow = [IO.Path]::GetFullPath($StartupBundle).TrimEnd('\')
    $selectedHome = Get-OperatorLauncherHome $CodexHome
    $upgrade = Join-Path $private 'operator-entry-upgrade'
    foreach ($path in @($project,$bundle,$workflow,$upgrade,$selectedHome)) { Assert-OperatorPlainPath $path }
    if ((Split-Path -Parent $workflow) -ine $private -or
        ((Test-Path -LiteralPath $upgrade) -and -not $IgnoreExisting)) {
        throw 'Existing or out-of-scope entry upgrade requires review.'
    }
    $pendingPlan = Join-Path $selectedHome 'operator-unified-activation'
    Assert-OperatorPlainPath $pendingPlan
    if (Test-Path -LiteralPath $pendingPlan) { throw 'Unified activation plan requires review before entry upgrade.' }
    $marker = Join-Path $selectedHome 'operator-native-route-only'
    Assert-OperatorPlainPath $marker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { throw 'Native route protection is required.' }
    $markerBytes = [IO.File]::ReadAllBytes($marker)
    if ($markerBytes.Length -ne 30 -or
        [Text.Encoding]::ASCII.GetString($markerBytes) -cne "operator-native-route-only-v1`n") {
        throw 'Native route protection changed.'
    }
    $migration = Get-OperatorEntryMigrationState $project
    if ($migration.phase -cne 'installed' -or $migration.runtime_ownership -cne 'unresolved' -or
        $migration.build.Count -ne 5) { throw 'Installed entry-only migration required.' }
    $migrationFile = Join-Path $private 'operator-entry-migration/journal.json'
    $migrationHash = Get-OperatorFingerprint $migrationFile
    $buildNames = @('Codex拓展入口.exe','operator_desktop_entry.ps1','desktop-entry.json',
        'launcher-manifest.json','Codex拓展入口.ico')
    foreach ($name in $buildNames) {
        if ($name -ne 'desktop-entry.json' -and
            (Get-OperatorFingerprint (Join-Path $bundle $name)) -cne $migration.build[$name]) {
            throw 'Migrated entry build changed.'
        }
    }
    $binary = Join-Path $bundle 'Codex拓展入口.exe'
    $entryScript = Join-Path $bundle 'operator_desktop_entry.ps1'
    $scriptHash = Get-OperatorFingerprint $entryScript
    $binaryHash = Get-OperatorFingerprint $binary
    if ($scriptHash -cne (Get-OperatorFingerprint (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1'))) {
        throw 'Entry build source changed; config-only upgrade refused.'
    }
    $build = Get-Content -LiteralPath (Join-Path $bundle 'launcher-manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($build.schema_version -ne 1 -or $build.native_fallback -cne 'native-only-v1' -or
        $build.binary_sha256 -cne $binaryHash -or $build.entry_script_sha256 -cne $scriptHash) {
        throw 'Migrated entry manifest changed.'
    }
    $targets = @(Get-OperatorDesktopPaths)
    if ($targets.Count -ne 2 -or $migration.entries.Count -ne 2) { throw 'Entry shortcut scope changed.' }
    $shell = New-Object -ComObject WScript.Shell
    $shortcuts = [ordered]@{}
    foreach ($target in $targets) {
        Assert-OperatorPlainPath $target
        if (-not $migration.entries.Contains($target)) { throw 'Entry shortcut ownership changed.' }
        $row = $migration.entries[$target]
        $current = Get-OperatorFingerprint $target
        $ownedAfter = Get-OperatorEntryAdoptionAfter $project $migration $target -CheckCurrent
        if ($row.status -cne 'installed' -or $current -eq 'absent' -or $current -cne $ownedAfter) {
            throw 'Managed entry shortcut changed.'
        }
        $link = $shell.CreateShortcut($target)
        if ($link.TargetPath -ine $binary -or $link.Arguments -or $link.WorkingDirectory -ine $bundle) {
            throw 'Managed entry shortcut target changed.'
        }
        if ($row.before -ne 'absent' -and
            (Get-OperatorFingerprint (Join-Path $private ('operator-entry-migration/originals/'+$row.before+'.bin'))) -cne $row.before) {
            throw 'Migration shortcut original changed.'
        }
        $shortcuts[$target] = $current
    }
    $metadata = Join-Path $workflow 'startup-sync-plan.json'
    $startup = Join-Path $workflow 'start-codex-with-web.ps1'
    if ((Get-Item -LiteralPath $metadata).Length -gt 16384) { throw 'Unified startup metadata too large.' }
    $workflowPlan = Get-Content -LiteralPath $metadata -Raw -Encoding utf8 | ConvertFrom-Json
    if ($workflowPlan.schema_version -ne 2 -or $workflowPlan.startup_script -cne 'start-codex-with-web.ps1' -or
        (Get-OperatorFingerprint $startup) -cne $workflowPlan.entry_files.'start-codex-with-web.ps1') {
        throw 'Reviewed unified startup workflow changed.'
    }
    $configFile = Join-Path $bundle 'desktop-entry.json'
    if ((Get-Item -LiteralPath $configFile).Length -gt 16384) { throw 'Migrated entry config too large.' }
    $before = [IO.File]::ReadAllBytes($configFile)
    $config = [Text.UTF8Encoding]::new($false,$true).GetString($before) | ConvertFrom-Json -AsHashtable
    $keys = @($config.Keys | Sort-Object)
    $expected = @('entry_script_sha256','mode','schema_version','startup_bundle')
    if (@(Compare-Object $keys $expected).Count -or $config.schema_version -ne 1 -or
        $config.mode -notin @('native','reviewed_startup') -or
        $config.entry_script_sha256 -cne $scriptHash) {
        throw 'Migrated entry config is not the reviewed startup shape.'
    }
    $beforeHash = Get-OperatorFingerprint $configFile
    $recoveryPath = $null
    $recoveryIntentHash = $null
    $recoveryCompletedHash = $null
    if ($beforeHash -cne $migration.build['desktop-entry.json']) {
        if (-not $RecoveryReceipt) { throw 'Exact native recovery receipt required.' }
        $recoveryPath = [IO.Path]::GetFullPath($RecoveryReceipt)
        Assert-OperatorPlainPath $recoveryPath
        $recoveryFolder = Split-Path -Parent $recoveryPath
        if ((Split-Path -Leaf $recoveryPath) -cne 'intent.json' -or
            (Split-Path -Leaf (Split-Path -Parent $recoveryFolder)) -cne 'operator-route-recovery' -or
            (Split-Path -Parent (Split-Path -Parent $recoveryFolder)) -ine $selectedHome) {
            throw 'Recovery receipt scope changed.'
        }
        $completedPath = Join-Path $recoveryFolder 'completed.json'
        $originalPath = Join-Path $recoveryFolder 'desktop-entry.json.before'
        foreach ($path in @($recoveryPath,$completedPath,$originalPath)) {
            Assert-OperatorPlainPath $path
            if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
                (Get-Item -LiteralPath $path).Length -gt 65536) { throw 'Recovery evidence unavailable.' }
        }
        $recovery = Get-Content -LiteralPath $recoveryPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        $completed = Get-Content -LiteralPath $completedPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        $rows = @($recovery.files | Where-Object { $_.name -ceq 'desktop-entry.json' })
        if ($recovery.schema_version -ne 1 -or $recovery.purpose -cne 'operator_official_route_recovery' -or
            $rows.Count -ne 1 -or $rows[0].target -ine $configFile -or
            $rows[0].before_sha256 -cne $migration.build['desktop-entry.json'] -or
            $rows[0].after_sha256 -cne $beforeHash -or
            (Get-OperatorFingerprint $originalPath) -cne $migration.build['desktop-entry.json'] -or
            $completed.schema_version -ne 1 -or
            @($completed.completed | Where-Object { $_ -ceq 'desktop-entry.json' }).Count -ne 1) {
            throw 'Recovery evidence does not bind migrated entry.'
        }
        $originalConfig = [IO.File]::ReadAllBytes($originalPath)
        $previous = [Text.UTF8Encoding]::new($false,$true).GetString($originalConfig) | ConvertFrom-Json -AsHashtable
        if ($previous.mode -cne 'reviewed_startup' -or $config.mode -cne 'native' -or
            $previous.Count -ne $config.Count) { throw 'Recovered entry changed beyond native mode.' }
        foreach ($key in $previous.Keys) {
            if (-not $config.ContainsKey($key) -or
                ($key -ne 'mode' -and $previous[$key] -cne $config[$key])) {
                throw 'Recovered entry changed beyond native mode.'
            }
        }
        $recoveryIntentHash = Get-OperatorFingerprint $recoveryPath
        $recoveryCompletedHash = Get-OperatorFingerprint $completedPath
    } elseif ($RecoveryReceipt) { throw 'Unexpected recovery receipt for unchanged entry.' }
    $relative = [IO.Path]::GetRelativePath($project,$workflow).Replace('\','/')
    if ($relative.StartsWith('..') -or [IO.Path]::IsPathRooted($relative)) { throw 'Startup scope changed.' }
    if ($config.mode -ceq 'reviewed_startup' -and $config.startup_bundle -ceq $relative) {
        throw 'Entry already selects this startup workflow.'
    }
    $config.mode = 'reviewed_startup'
    $config.startup_bundle = $relative
    $after = [Text.UTF8Encoding]::new($false).GetBytes(($config | ConvertTo-Json -Depth 30))
    $afterHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($after)).ToLowerInvariant()
    $plan = [ordered]@{schema_version=1; scope='entry_only_config_upgrade'; project=$project;
        migration_sha256=$migrationHash; runtime_ownership='unresolved';
        migration_config_sha256=$migration.build['desktop-entry.json'];
        before_sha256=$beforeHash; after_sha256=$afterHash;
        codex_home=$selectedHome; native_marker_sha256=(Get-OperatorFingerprint $marker);
        recovery_receipt=$recoveryPath; recovery_intent_sha256=$recoveryIntentHash;
        recovery_completed_sha256=$recoveryCompletedHash;
        startup_bundle=$workflow; startup_metadata_sha256=(Get-OperatorFingerprint $metadata);
        startup_script_sha256=(Get-OperatorFingerprint $startup);
        entry_script_sha256=$scriptHash; binary_sha256=$binaryHash; shortcuts=$shortcuts}
    $raw = [Text.UTF8Encoding]::new($false).GetBytes(($plan | ConvertTo-Json -Depth 10 -Compress))
    return @{plan=$plan; sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant();
        before=$before; after=$after}
}

function Invoke-OperatorEntryUpgrade {
    param([string]$ProjectRoot, [string]$StartupBundle, [string]$ExpectedPlanSha256,
          [string]$CodexHome, [string]$RecoveryReceipt)
    $review = Get-OperatorEntryUpgradePlan $ProjectRoot $StartupBundle $CodexHome $RecoveryReceipt
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $review.sha256 -cne $ExpectedPlanSha256) {
        throw 'Entry upgrade preview changed.'
    }
    $project = $review.plan.project
    $migrationLock = Join-Path $project '.codex/operator-entry-migration/transaction.lock'
    $guard = [IO.File]::Open($migrationLock,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $repeat = Get-OperatorEntryUpgradePlan $project $StartupBundle $CodexHome $RecoveryReceipt
        if ($repeat.sha256 -cne $review.sha256) { throw 'Entry upgrade changed before intent.' }
        $folder = Join-Path $project '.codex/operator-entry-upgrade'
        Assert-OperatorPlainPath $folder
        if (Test-Path -LiteralPath $folder) { throw 'Existing or uncertain entry upgrade requires review.' }
        New-Item -ItemType Directory -Path $folder | Out-Null
        $lock = [IO.File]::Open((Join-Path $folder 'transaction.lock'),[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        try {
            $config = Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json'
            Write-OperatorAtomicBytes (Join-Path $folder 'before.json') $review.before
            Write-OperatorAtomicBytes (Join-Path $folder 'after.json') $review.after
            if ((Get-OperatorFingerprint (Join-Path $folder 'before.json')) -cne $review.plan.before_sha256 -or
                (Get-OperatorFingerprint (Join-Path $folder 'after.json')) -cne $review.plan.after_sha256) {
                throw 'Entry upgrade backup verification failed.'
            }
            $intent = [ordered]@{schema_version=1; phase='may_have_updated'; plan=$review.plan;
                plan_sha256=$review.sha256}
            $intentRaw = [Text.UTF8Encoding]::new($false).GetBytes(($intent | ConvertTo-Json -Depth 12))
            Write-OperatorAtomicBytes (Join-Path $folder 'intent.json') $intentRaw
            $again = Get-OperatorEntryUpgradePlan $project $StartupBundle $CodexHome $RecoveryReceipt -IgnoreExisting
            if ($again.sha256 -cne $review.sha256 -or (Get-OperatorFingerprint $config) -cne $review.plan.before_sha256) {
                throw 'Entry upgrade changed after intent.'
            }
            Write-OperatorAtomicBytes $config $review.after
            if ((Get-OperatorFingerprint $config) -cne $review.plan.after_sha256) {
                throw 'Entry upgrade write verification failed.'
            }
            $receipt = [ordered]@{schema_version=1; phase='applied'; plan_sha256=$review.sha256;
                intent_sha256=(Get-OperatorFingerprint (Join-Path $folder 'intent.json'));
                before_sha256=$review.plan.before_sha256; after_sha256=$review.plan.after_sha256}
            Write-OperatorAtomicBytes (Join-Path $folder 'receipt.json') (
                [Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 8)))
            return @{status='entry_config_upgraded'; config_changed=$true; routing_changed=$false;
                runtime_ownership='unresolved'; model_requests=0}
        } finally { $lock.Dispose() }
    } finally { $guard.Dispose() }
}
