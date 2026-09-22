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

function Restore-OperatorEntryMigration([string]$ProjectRoot) {
    $state = Get-OperatorEntryMigrationState $ProjectRoot
    if ($state.phase -notin @('installed','restoring','restored')) { throw 'Incomplete entry migration requires review.' }
    $folder = Join-Path $ProjectRoot '.codex/operator-entry-migration'
    $lock = [IO.File]::Open((Join-Path $folder 'transaction.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $state = Get-OperatorEntryMigrationState $ProjectRoot
        $bundle = Join-Path $ProjectRoot '.codex/operator-desktop-entry'
        if ($state.build.Count -ne 5) { throw 'Incomplete migration build record.' }
        foreach ($name in $state.build.Keys) {
            if ($name -notin @('Codex拓展入口.exe','operator_desktop_entry.ps1','desktop-entry.json','launcher-manifest.json','Codex拓展入口.ico') -or
                (Get-OperatorFingerprint (Join-Path $bundle $name)) -cne $state.build[$name]) { throw 'Migrated launcher changed.' }
        }
        if ((Get-OperatorFingerprint $state.plan.legacy_executable) -cne $state.plan.legacy_executable_sha256) { throw 'Legacy rollback launcher changed.' }
        foreach ($path in $state.entries.Keys) {
            $row = $state.entries[$path];$current = Get-OperatorFingerprint $path
            if ($current -cne $row.before -and $current -cne $row.after) { throw 'Shortcut edited after migration; retained.' }
            if ($row.before -ne 'absent' -and (Get-OperatorFingerprint (Join-Path $folder ('originals/'+$row.before+'.bin'))) -cne $row.before) { throw 'Migration backup changed.' }
        }
        $marker = Join-Path $bundle 'native-only'
        $one = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([byte[]]@(1))).ToLowerInvariant()
        if ((Get-OperatorFingerprint $marker) -notin @('absent',$one)) { throw 'Native fallback marker changed.' }
        $state.phase='restoring';Save-OperatorEntryMigrationState $ProjectRoot $state
        # Pins to the new binary remain usable after removing its shortcuts.
        Write-OperatorAtomicBytes $marker ([byte[]]@(1))
        foreach ($path in $state.entries.Keys) {
            $row = $state.entries[$path];$current=Get-OperatorFingerprint $path
            if ($current -cne $row.before -and $current -cne $row.after) { throw 'Shortcut changed during restoration.' }
            if ($current -cne $row.before) {
                if ($row.before -eq 'absent') { Remove-Item -LiteralPath $path }
                else { Write-OperatorAtomicBytes $path ([IO.File]::ReadAllBytes((Join-Path $folder ('originals/'+$row.before+'.bin')))) }
            }
        }
        $state.phase='restored';Save-OperatorEntryMigrationState $ProjectRoot $state
        return @{entry_restored=$true;runtime_removed=$false;routing_changed=$false;runtime_ownership='unresolved'}
    } finally { $lock.Dispose() }
}
