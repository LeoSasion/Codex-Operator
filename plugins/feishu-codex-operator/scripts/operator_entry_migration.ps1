#requires -Version 7.0
# Explicit entry-only ownership, independent of unknown legacy runtime origins.
function Get-OperatorEntryMigrationPlan {
    param([string]$ProjectRoot, [string]$LegacyReceipt, [string]$StartupBundle)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $private = Join-Path $project '.codex'
    $receipt = [IO.Path]::GetFullPath($LegacyReceipt)
    $startup = [IO.Path]::GetFullPath($StartupBundle).TrimEnd('\')
    foreach ($path in @($receipt,$startup)) { Assert-OperatorPlainPath $path }
    if (-not $receipt.StartsWith($private+'\',[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Parent $startup) -ine $private) { throw 'Migration inputs must belong to this project.' }
    if ((Get-Item -LiteralPath $receipt).Length -gt 65536) { throw 'Legacy receipt too large.' }
    $legacy = Get-Content -LiteralPath $receipt -Raw -Encoding utf8 | ConvertFrom-Json
    if ($legacy.status -cne 'completed' -or $legacy.operation -cne 'owner_requested_reviewed_legacy_entry_rename') {
        throw 'A completed reviewed legacy entry receipt is required.'
    }
    $oldExe = [IO.Path]::GetFullPath($legacy.new_executable)
    if (-not $oldExe.StartsWith($private+'\',[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $oldExe) -cne 'Codex拓展入口.exe' -or
        $legacy.launcher_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        (Get-OperatorFingerprint $oldExe) -cne $legacy.launcher_sha256) { throw 'Legacy launcher identity changed.' }
    $targets = @(Get-OperatorDesktopPaths)
    if (@($legacy.installed_links).Count -ne 2 -or $targets.Count -ne 2) { throw 'Ambiguous legacy shortcuts.' }
    $shell = New-Object -ComObject WScript.Shell
    $entries = [ordered]@{}
    foreach ($target in $targets) {
        $rows = @($legacy.installed_links | Where-Object { $_.path -ieq $target })
        if ($rows.Count -ne 1 -or $rows[0].target -ine $oldExe) { throw 'Legacy shortcut scope changed.' }
        $before = Get-OperatorFingerprint $target
        if ($before -ne 'absent' -and ($before -cne $rows[0].sha256 -or
            $shell.CreateShortcut($target).TargetPath -ine $oldExe)) { throw 'Legacy shortcut changed; preserved for review.' }
        $entries[$target] = $before
    }
    $metadata = Join-Path $startup 'startup-sync-plan.json'
    Assert-OperatorPlainPath $metadata
    if ((Get-Item -LiteralPath $metadata).Length -gt 16384) { throw 'Startup metadata too large.' }
    $plan = Get-Content -LiteralPath $metadata -Raw -Encoding utf8 | ConvertFrom-Json
    $workflow = Join-Path $startup 'start-codex-with-web.ps1'
    if ($plan.schema_version -ne 2 -or $plan.startup_script -cne 'start-codex-with-web.ps1' -or
        (Get-OperatorFingerprint $workflow) -cne $plan.entry_files.'start-codex-with-web.ps1') { throw 'Reviewed Web workflow required.' }
    $source = [ordered]@{}
    foreach ($name in @('operator_desktop_setup.ps1','operator_entry_migration.ps1','operator_desktop_entry.ps1','operator_desktop_entry.cs','operator_installation.psm1')) {
        $source[$name] = Get-OperatorFingerprint (Join-Path $PSScriptRoot $name)
    }
    $value = [ordered]@{schema_version=1; scope='desktop_entry_only'; project=$project;
        receipt=$receipt; receipt_sha256=(Get-OperatorFingerprint $receipt); legacy_executable=$oldExe;
        legacy_executable_sha256=$legacy.launcher_sha256; startup_bundle=$startup;
        metadata_sha256=(Get-OperatorFingerprint $metadata); workflow_sha256=(Get-OperatorFingerprint $workflow);
        source=$source; entries=$entries; rollback_baseline='immediately_before_migration'; runtime_ownership='unresolved'}
    $raw = [Text.UTF8Encoding]::new($false).GetBytes(($value | ConvertTo-Json -Depth 8 -Compress))
    return @{plan=$value; sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()}
}

function Get-OperatorEntryMigrationState([string]$ProjectRoot) {
    $path = Join-Path $ProjectRoot '.codex/operator-entry-migration/journal.json'
    Assert-OperatorPlainPath $path
    if ((Get-Item -LiteralPath $path).Length -gt 1048576) { throw 'Migration journal too large.' }
    $state = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($state.schema_version -ne 1 -or $state.scope -cne 'desktop_entry_only' -or
        $state.project -ine [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') -or
        $state.runtime_ownership -cne 'unresolved' -or $state.entries.Count -ne 2 -or
        @($state.entries.Keys | Where-Object { $_ -notin @(Get-OperatorDesktopPaths) }).Count) { throw 'Migration journal scope changed.' }
    foreach ($path in $state.entries.Keys) {
        $row = $state.entries[$path]
        if ($row.before -cnotmatch '^(absent|[a-f0-9]{64})$' -or $row.after -cnotmatch '^(absent|[a-f0-9]{64})$' -or
            $row.status -notin @('prepared','pending','installed') -or $row.before -cne $state.plan.entries[$path]) { throw 'Invalid migration file record.' }
    }
    return $state
}

function Save-OperatorEntryMigrationState([string]$ProjectRoot, $State) {
    Write-OperatorAtomicBytes (Join-Path $ProjectRoot '.codex/operator-entry-migration/journal.json') (
        [Text.UTF8Encoding]::new($false).GetBytes(($State | ConvertTo-Json -Depth 12)))
}

function Set-OperatorEntryMigrationFile([string]$ProjectRoot, [string]$Path, [byte[]]$Bytes) {
    $state = Get-OperatorEntryMigrationState $ProjectRoot
    if ($state.phase -cne 'installing' -or -not $state.entries.Contains($Path)) { throw 'Entry-only migration scope rejected.' }
    $row = $state.entries[$Path]
    if ($row.status -cne 'prepared' -or (Get-OperatorFingerprint $Path) -cne $row.before) { throw 'Shortcut changed before migration.' }
    $row.after = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
    $row.status = 'pending'
    Save-OperatorEntryMigrationState $ProjectRoot $state
    if ((Get-OperatorFingerprint $Path) -cne $row.before) { throw 'Shortcut changed during migration.' }
    Write-OperatorAtomicBytes $Path $Bytes
    $row.status = 'installed'
    Save-OperatorEntryMigrationState $ProjectRoot $state
}

function Invoke-OperatorEntryMigration {
    param([string]$ProjectRoot, [string]$LegacyReceipt, [string]$StartupBundle, [string]$ExpectedPlanSha256)
    $review = Get-OperatorEntryMigrationPlan $ProjectRoot $LegacyReceipt $StartupBundle
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $review.sha256 -cne $ExpectedPlanSha256) { throw 'Migration preview changed.' }
    $project = $review.plan.project
    $folder = Join-Path $project '.codex/operator-entry-migration'
    $bundle = Join-Path $project '.codex/operator-desktop-entry'
    foreach ($path in @($folder,$bundle)) {
        Assert-OperatorPlainPath $path
        if (Test-Path -LiteralPath $path) { throw 'Existing or uncertain entry migration requires review; no retry.' }
    }
    # Reserve this one transaction. No project/runtime ownership record is made.
    New-Item -ItemType Directory -Path $folder | Out-Null
    $lock = [IO.File]::Open((Join-Path $folder 'transaction.lock'),[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $state = @{schema_version=1;scope='desktop_entry_only';project=$project;phase='preparing';runtime_ownership='unresolved';
            plan=$review.plan;plan_sha256=$review.sha256;entries=@{};build=@{}}
        foreach ($path in $review.plan.entries.Keys) {
            $before = $review.plan.entries[$path]
            if ((Get-OperatorFingerprint $path) -cne $before) { throw 'Shortcut changed before backup.' }
            if ($before -ne 'absent') {
                $backup = Join-Path $folder ('originals/'+$before+'.bin')
                Write-OperatorAtomicBytes $backup ([IO.File]::ReadAllBytes($path))
                if ((Get-OperatorFingerprint $backup) -cne $before) { throw 'Migration original backup failed.' }
            }
            $state.entries[$path] = @{before=$before;after=$before;status='prepared'}
        }
        $again = Get-OperatorEntryMigrationPlan $project $LegacyReceipt $StartupBundle
        if ($again.sha256 -cne $review.sha256) { throw 'Migration changed during preparation.' }
        $state.phase='installing';Save-OperatorEntryMigrationState $project $state
        Install-OperatorDesktopEntry $project $StartupBundle -EntryMigration | Out-Null
        $state = Get-OperatorEntryMigrationState $project
        foreach ($name in @('Codex拓展入口.exe','operator_desktop_entry.ps1','desktop-entry.json','launcher-manifest.json','Codex拓展入口.ico')) {
            $state.build[$name] = Get-OperatorFingerprint (Join-Path $bundle $name)
            if ($state.build[$name] -ceq 'absent') { throw 'Incomplete migration build.' }
        }
        $state.phase='installed';Save-OperatorEntryMigrationState $project $state
        return @{entry_installed=$true;scope='desktop_entry_only';runtime_ownership='unresolved';routing_changed=$false;taskbar_pin_automatic=$false}
    } finally { $lock.Dispose() }
}

function Get-OperatorEntryConfigUpgradeBuild([string]$ProjectRoot, $Migration) {
    # A separate completed config-only attachment may replace exactly one
    # migrated build hash. Incomplete evidence never becomes restoration owner.
    $folder = Join-Path $ProjectRoot '.codex/operator-entry-upgrade'
    Assert-OperatorPlainPath $folder
    if (-not (Test-Path -LiteralPath $folder)) { return $Migration.build }
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        throw 'Entry upgrade transaction requires review.'
    }
    $intentFile = Join-Path $folder 'intent.json'
    $receiptFile = Join-Path $folder 'receipt.json'
    foreach ($path in @($intentFile,$receiptFile,(Join-Path $folder 'before.json'),
            (Join-Path $folder 'after.json'))) {
        Assert-OperatorPlainPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-Item -LiteralPath $path).Length -gt 65536) {
            throw 'Entry upgrade transaction requires review.'
        }
    }
    $intent = Get-Content -LiteralPath $intentFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $receipt = Get-Content -LiteralPath $receiptFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $before = Get-OperatorFingerprint (Join-Path $folder 'before.json')
    $after = Get-OperatorFingerprint (Join-Path $folder 'after.json')
    $planBytes = [Text.UTF8Encoding]::new($false).GetBytes(($intent.plan | ConvertTo-Json -Depth 10 -Compress))
    $planHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($planBytes)).ToLowerInvariant()
    if ($intent.schema_version -ne 1 -or $intent.phase -cne 'may_have_updated' -or
        $intent.plan.schema_version -ne 1 -or $intent.plan.scope -cne 'entry_only_config_upgrade' -or
        $intent.plan.project -ine [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') -or
        $intent.plan.runtime_ownership -cne 'unresolved' -or
        ($Migration.phase -ceq 'installed' -and
         $intent.plan.migration_sha256 -cne (Get-OperatorFingerprint (Join-Path $ProjectRoot '.codex/operator-entry-migration/journal.json'))) -or
        $intent.plan_sha256 -cne $planHash -or
        $intent.plan.migration_config_sha256 -cne $Migration.build['desktop-entry.json'] -or
        $intent.plan.before_sha256 -cne $before -or $intent.plan.after_sha256 -cne $after -or
        $receipt.schema_version -ne 1 -or $receipt.phase -cne 'applied' -or
        $receipt.plan_sha256 -cne $intent.plan_sha256 -or
        $receipt.intent_sha256 -cne (Get-OperatorFingerprint $intentFile) -or
        $receipt.before_sha256 -cne $before -or $receipt.after_sha256 -cne $after) {
        throw 'Entry upgrade transaction requires review.'
    }
    if ($before -cne $Migration.build['desktop-entry.json']) {
        $recoveryPath = $intent.plan.recovery_receipt
        if (-not $recoveryPath -or
            (Get-OperatorFingerprint $recoveryPath) -cne $intent.plan.recovery_intent_sha256 -or
            (Get-OperatorFingerprint (Join-Path (Split-Path -Parent $recoveryPath) 'completed.json')) -cne
                $intent.plan.recovery_completed_sha256 -or
            (Get-OperatorFingerprint (Join-Path (Split-Path -Parent $recoveryPath) 'desktop-entry.json.before')) -cne
                $Migration.build['desktop-entry.json']) {
            throw 'Entry upgrade recovery evidence changed.'
        }
    } elseif ($intent.plan.recovery_receipt) { throw 'Unexpected entry upgrade recovery evidence.' }
    $build = @{}
    foreach ($name in $Migration.build.Keys) { $build[$name] = $Migration.build[$name] }
    $build['desktop-entry.json'] = $after
    return $build
}

function Get-OperatorEntryPairAttachment([string]$ProjectRoot, $Migration, $BeforeBuild) {
    $pairRoot=Join-Path $ProjectRoot '.codex/operator-desktop-pair'
    Assert-OperatorPlainPath $pairRoot
    if (-not (Test-Path -LiteralPath $pairRoot)) { return $null }
    Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -DisableNameChecking
    return Get-OperatorLegacyPairAttachment -ProjectRoot $ProjectRoot -Migration $Migration -BeforeBuild $BeforeBuild
}

function Get-OperatorEntryUpgradeBuild([string]$ProjectRoot, $Migration) {
    # A pair attachment follows the complete old config-only chain. It cannot
    # replace validation of that chain, even after migration restoration starts.
    $before=Get-OperatorEntryConfigUpgradeBuild $ProjectRoot $Migration
    $attachment=Get-OperatorEntryPairAttachment $ProjectRoot $Migration $before
    if ($attachment) { return $attachment.after }
    return $before
}

function Get-OperatorUnifiedRetirementStatus([string]$PlanPath, [string]$WorkflowPath) {
    # Run the same read-only verifier used by unified teardown, under the
    # reviewed workflow's exact interpreter. Its exit status is authoritative.
    $scriptPath = Join-Path $WorkflowPath 'start-codex-with-web.ps1'
    Assert-OperatorPlainPath $scriptPath
    $script = [IO.File]::ReadAllText($scriptPath,[Text.UTF8Encoding]::new($false,$true))
    $pathMatch = [regex]::Matches($script,"(?m)^\`$python = '((?:[^']|'')*)'\r?$")
    $hashMatch = [regex]::Matches($script,
        '(?m)^if \(\(Get-FileHash -LiteralPath \$python -Algorithm SHA256\)\.Hash\.ToLowerInvariant\(\) -cne ''([a-f0-9]{64})''\) \{ throw ''Saved Python changed\.'' \}\r?$')
    if ($pathMatch.Count -ne 1 -or $hashMatch.Count -ne 1) {
        throw 'Reviewed unified workflow interpreter unavailable.'
    }
    $python = $pathMatch[0].Groups[1].Value.Replace("''", "'")
    Assert-OperatorPlainPath $python
    if (-not [IO.Path]::IsPathFullyQualified($python) -or
        (Get-OperatorFingerprint $python) -cne $hashMatch[0].Groups[1].Value) {
        throw 'Reviewed unified workflow interpreter changed.'
    }
    $verifier = Join-Path $PSScriptRoot 'operator_unified_retire.py'
    Assert-OperatorPlainPath $verifier
    $output = @(& $python -X utf8 -E -s -B $verifier status --plan $PlanPath 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) {
        throw 'Unified retirement is not witnessed.'
    }
    try { return ($output[0] | ConvertFrom-Json -AsHashtable) }
    catch { throw 'Unified retirement status is invalid.' }
}

function Get-OperatorUnifiedRetiredEntryHash([string]$ProjectRoot, $Build) {
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $migration=Get-OperatorEntryMigrationState $project
    $oldBuild=Get-OperatorEntryConfigUpgradeBuild $project $migration
    $pair=Get-OperatorEntryPairAttachment $project $migration $oldBuild
    $upgrade = Join-Path $project '.codex/operator-entry-upgrade'
    if ($pair) {
        if ($pair.after.Count -ne $Build.Count -or
            @($Build.Keys | Where-Object {$pair.after[$_] -cne $Build[$_]}).Count) {
            throw 'Unified retirement does not bind this pair build.'
        }
        $selectedCodexHome=Get-OperatorLauncherHome $pair.codex_home
        $baselinePath=$pair.config_after_path
        $expectedWorkflow=$pair.startup_bundle
        $expectedScript=$pair.startup_script_sha256
        $expectedMetadata=$pair.startup_metadata_sha256
    } else {
        $upgradeIntent = Join-Path $upgrade 'intent.json'
        Assert-OperatorPlainPath $upgradeIntent
        $attachment = Get-Content -LiteralPath $upgradeIntent -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        if ($attachment.plan.scope -cne 'entry_only_config_upgrade' -or
            $attachment.plan.after_sha256 -cne $Build['desktop-entry.json']) {
            throw 'Unified retirement does not bind this entry upgrade.'
        }
        $selectedCodexHome=Get-OperatorLauncherHome $attachment.plan.codex_home
        $baselinePath=Join-Path $upgrade 'after.json'
        $expectedWorkflow=$attachment.plan.startup_bundle
        $expectedScript=$attachment.plan.startup_script_sha256
        $expectedMetadata=$attachment.plan.startup_metadata_sha256
    }
    $planPath = Join-Path $selectedCodexHome 'operator-unified-activation/plan.json'
    Assert-OperatorPlainPath $planPath
    $plan = Get-Content -LiteralPath $planPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $workflow = Join-Path $project '.codex/operator-unified-startup'
    $startup = Join-Path $workflow 'start-codex-with-web.ps1'
    $metadata = Join-Path $workflow 'startup-sync-plan.json'
    $configPath = Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json'
    foreach ($path in @($workflow,$startup,$metadata,$configPath,$baselinePath)) { Assert-OperatorPlainPath $path }
    $currentHash = Get-OperatorFingerprint $configPath
    if ($expectedWorkflow -ine $workflow -or
        (Get-OperatorFingerprint $baselinePath) -cne $Build['desktop-entry.json'] -or
        $plan.schema_version -ne 1 -or $plan.project -ine $project -or $plan.home -ine $selectedCodexHome -or
        $plan.startup_bundle.path -ine $workflow -or
        $plan.startup_bundle.startup_script_sha256 -cne (Get-OperatorFingerprint $startup) -or
        $plan.startup_bundle.sync_plan_sha256 -cne (Get-OperatorFingerprint $metadata) -or
        $expectedScript -cne (Get-OperatorFingerprint $startup) -or
        $expectedMetadata -cne (Get-OperatorFingerprint $metadata)) {
        throw 'Unified retirement does not bind this entry upgrade.'
    }
    $before = Get-Content -LiteralPath $baselinePath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $current = Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($before.mode -cne 'reviewed_startup' -or $current.mode -cne 'native' -or
        $before.Count -ne $current.Count -or
        @($before.Keys | Where-Object { -not $current.ContainsKey($_) -or
            ($_ -cne 'mode' -and $before[$_] -cne $current[$_]) }).Count) {
        throw 'Recovered unified entry changed beyond native mode.'
    }
    $status = Get-OperatorUnifiedRetirementStatus $planPath $workflow
    if ($status.status -cne 'retired_witnessed' -or
        $status.recovery.entry_before_sha256 -cne $Build['desktop-entry.json'] -or
        $status.recovery.entry_recovered_sha256 -cne $currentHash) {
        throw 'Unified retirement does not witness this recovered entry.'
    }
    return $currentHash
}

function Restore-OperatorEntryMigration([string]$ProjectRoot) {
    $state = Get-OperatorEntryMigrationState $ProjectRoot
    if ($state.phase -notin @('installed','restoring','restored')) { throw 'Incomplete entry migration requires review.' }
    $folder = Join-Path $ProjectRoot '.codex/operator-entry-migration'
    $lock = [IO.File]::Open((Join-Path $folder 'transaction.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $state = Get-OperatorEntryMigrationState $ProjectRoot
        $bundle = Join-Path $ProjectRoot '.codex/operator-desktop-entry'
        if ($state.build.Count -ne 5) { throw 'Incomplete migration build record.' }
        $beforeBuild=Get-OperatorEntryConfigUpgradeBuild $ProjectRoot $state
        $pair=Get-OperatorEntryPairAttachment $ProjectRoot $state $beforeBuild
        if ($pair -and $pair.phase -cne 'restored') { throw 'Restore the desktop pair before restoring the legacy migration.' }
        $currentBuild=if ($pair) {$pair.after} else {$beforeBuild}
        $configPath = Join-Path $bundle 'desktop-entry.json'
        $currentConfigHash = Get-OperatorFingerprint $configPath
        $restoredUnifiedHash = $null
        if ($currentConfigHash -cne $currentBuild['desktop-entry.json']) {
            $restoredUnifiedHash = Get-OperatorUnifiedRetiredEntryHash $ProjectRoot $currentBuild
        }
        foreach ($name in $currentBuild.Keys) {
            if ($name -notin @('Codex拓展入口.exe','operator_desktop_entry.ps1','desktop-entry.json','launcher-manifest.json','Codex拓展入口.ico') -or
                (Get-OperatorFingerprint (Join-Path $bundle $name)) -cne
                    $(if ($name -ceq 'desktop-entry.json' -and $restoredUnifiedHash) {
                        $restoredUnifiedHash
                    } else { $currentBuild[$name] })) { throw 'Migrated launcher changed.' }
        }
        if ((Get-OperatorFingerprint $state.plan.legacy_executable) -cne $state.plan.legacy_executable_sha256) { throw 'Legacy rollback launcher changed.' }
        $desktopLink = @(Get-OperatorDesktopPaths)[0]
        foreach ($path in $state.entries.Keys) {
            $row = $state.entries[$path];$current = Get-OperatorFingerprint $path
            $ownedAfter = Get-OperatorEntryAdoptionAfter $ProjectRoot $state $path -CheckCurrent:($path -ieq $desktopLink -and $current -cne $row.before)
            if ($current -cne $row.before -and $current -cne $ownedAfter) { throw 'Shortcut edited after migration; retained.' }
            if ($row.before -ne 'absent' -and (Get-OperatorFingerprint (Join-Path $folder ('originals/'+$row.before+'.bin'))) -cne $row.before) { throw 'Migration backup changed.' }
        }
        $marker = Join-Path $bundle 'native-only'
        $one = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([byte[]]@(1))).ToLowerInvariant()
        if ((Get-OperatorFingerprint $marker) -notin @('absent',$one)) { throw 'Native fallback marker changed.' }
        $checkedState=Get-OperatorEntryMigrationState $ProjectRoot
        $checkedBefore=Get-OperatorEntryConfigUpgradeBuild $ProjectRoot $checkedState
        $checkedPair=Get-OperatorEntryPairAttachment $ProjectRoot $checkedState $checkedBefore
        if ([bool]$checkedPair -ne [bool]$pair -or ($checkedPair -and
            ($checkedPair.phase -cne 'restored' -or $checkedPair.origin_sha256 -cne $pair.origin_sha256 -or
             $checkedPair.receipt_sha256 -cne $pair.receipt_sha256))) {
            throw 'Pair restoration evidence changed before legacy restoration.'
        }
        $state.phase='restoring';Save-OperatorEntryMigrationState $ProjectRoot $state
        # Pins to the new binary remain usable after removing its shortcuts.
        Write-OperatorAtomicBytes $marker ([byte[]]@(1))
        foreach ($path in $state.entries.Keys) {
            $row = $state.entries[$path];$current=Get-OperatorFingerprint $path
            # The first pass verified both identities before writes. Start may
            # already be restored by this pass when Desktop comes next.
            $ownedAfter = Get-OperatorEntryAdoptionAfter $ProjectRoot $state $path -CheckCurrentDesktopOnly:($path -ieq $desktopLink -and $current -cne $row.before)
            if ($current -cne $row.before -and $current -cne $ownedAfter) { throw 'Shortcut changed during restoration.' }
            if ($current -cne $row.before) {
                if ($row.before -eq 'absent') { Remove-Item -LiteralPath $path }
                else { Write-OperatorAtomicBytes $path ([IO.File]::ReadAllBytes((Join-Path $folder ('originals/'+$row.before+'.bin')))) }
            }
        }
        $state.phase='restored';Save-OperatorEntryMigrationState $ProjectRoot $state
        return @{entry_restored=$true;runtime_removed=$false;routing_changed=$false;runtime_ownership='unresolved'}
    } finally { $lock.Dispose() }
}
