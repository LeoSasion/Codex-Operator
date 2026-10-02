#requires -Version 7.0
$ErrorActionPreference='Stop'
$script:LegacyUtf8=[Text.UTF8Encoding]::new($false,$true)
$script:LegacyPair=Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -PassThru -DisableNameChecking
$script:LegacyUpgrade=Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_upgrade.psm1') -PassThru -DisableNameChecking
$script:LegacyEntry=New-Module -Name OperatorLegacyPairEntry -ArgumentList $PSScriptRoot -ScriptBlock {
    param($Source)
    Import-Module (Join-Path $Source 'operator_installation.psm1') -DisableNameChecking
    . (Join-Path $Source 'operator_entry_migration.ps1')
    . (Join-Path $Source 'operator_entry_shortcut_adoption.ps1')
    Export-ModuleMember -Function *
}

function Read-LegacyPairBytes([string]$Path) {return ,(& $script:LegacyUpgrade {param($P) Read-OperatorUpgradeBytes $P} $Path)}
function Assert-LegacyPairPath([string]$Path) {& $script:LegacyUpgrade {param($P) Assert-OperatorUpgradePath $P} $Path}
function Get-LegacyPairHash([AllowNull()][byte[]]$Bytes) {return & $script:LegacyUpgrade {param($B) Get-OperatorUpgradeHash $B} $Bytes}
function Get-LegacyPairJson([string]$Path) {return & $script:LegacyUpgrade {param($P) Get-OperatorUpgradeJson $P} $Path}
function ConvertTo-LegacyPairBytes($Value) {return ,$script:LegacyUtf8.GetBytes(($Value|ConvertTo-Json -Depth 40 -Compress))}
function New-LegacyPairDirectory([string]$Path) {& $script:LegacyUpgrade {param($P) New-OperatorUpgradeDirectory $P} $Path}
function Get-LegacyPairIdentity([string]$Path) {return & $script:LegacyEntry {param($P) Get-OperatorShortcutFileIdentity $P} $Path}
function Get-LegacyPairCom([string]$Path) {return & $script:LegacyEntry {param($P) Get-OperatorShortcutCom $P} $Path}
function Get-LegacyPairPaths {return @(& $script:LegacyEntry {Get-OperatorDesktopPaths})}
function Get-LegacyPairHome {return Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'}
function Test-LegacyPairEqual($Left,$Right) {
    if ($null -eq $Left -or $null -eq $Right) {return $null -eq $Left -and $null -eq $Right}
    if ($Left -is [Collections.IDictionary]) {
        if ($Right -isnot [Collections.IDictionary] -or $Left.Count -ne $Right.Count) {return $false}
        foreach ($key in $Left.Keys) {if (-not $Right.Contains($key) -or -not (Test-LegacyPairEqual $Left[$key] $Right[$key])) {return $false}}
        return $true
    }
    if ($Left -is [Collections.IList]) {
        if ($Right -isnot [Collections.IList] -or $Left.Count -ne $Right.Count) {return $false}
        for ($i=0;$i -lt $Left.Count;$i++) {if (-not (Test-LegacyPairEqual $Left[$i] $Right[$i])) {return $false}}
        return $true
    }
    return $Left.GetType() -eq $Right.GetType() -and $Left -ceq $Right
}
function Assert-LegacyPairBuild($Build) {
    $names=@('Codex拓展入口.exe','operator_desktop_entry.ps1','desktop-entry.json','launcher-manifest.json','Codex拓展入口.ico')
    if ($Build -isnot [Collections.IDictionary] -or $Build.Count -ne 5) {throw 'legacy_pair_build_invalid'}
    foreach ($name in $names) {if ($Build[$name] -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_build_invalid'}}
}
function Get-LegacyPairTransaction([string]$Root,[string]$Identity) {
    if ($Identity -cnotmatch '^[a-f0-9]{32}$') {throw 'legacy_pair_transaction_invalid'}
    $folder=Join-Path $Root ('upgrades/'+$Identity)
    if (Test-Path -LiteralPath (Join-Path $folder 'pending.json')) {
        $reviewPath=Join-Path $folder 'rollback-reviewed.json'
        if (-not (Test-Path -LiteralPath $reviewPath)) {throw 'legacy_pair_pending_requires_review'}
        $review=Get-LegacyPairJson $reviewPath
        $project=Split-Path -Parent (Split-Path -Parent $Root)
        if ($review -isnot [Collections.IDictionary] -or
            @(Compare-Object @($review.Keys|Sort-Object) @('contract','root','stage','retirement_sha256'|Sort-Object)).Count -or
            $review.contract -cne 'operator_mode_pair_rollback_review_v1' -or
            -not [IO.Path]::IsPathFullyQualified($review.root) -or
            (Split-Path -Parent $review.root) -ine (Join-Path $project '.codex/operator-mode-entry') -or
            $review.stage -ine (Join-Path $review.root ('pair-refreshes/'+$Identity)) -or
            $review.retirement_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $review.stage 'retired.json'))) -cne $review.retirement_sha256) {
            throw 'legacy_pair_rollback_review_changed'
        }
        $entry=Get-LegacyPairJson (Join-Path $review.stage 'originals/entry.json')
        if ($entry.root -cne $review.root -or $entry.project -cne $project -or
            $entry.python -isnot [string] -or -not [IO.Path]::IsPathFullyQualified($entry.python) -or
            $entry.python_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-LegacyPairHash (Read-LegacyPairBytes $entry.python)) -cne $entry.python_sha256) {
            throw 'legacy_pair_rollback_dependency_changed'
        }
        $arguments=@('-X','utf8','-E','-s','-B',(Join-Path $PSScriptRoot 'operator_mode_maintenance.py'),
            'rollback-pair-status','--root',$review.root,'--stage',$review.stage)
        $output=@(& $entry.python @arguments 2>$null)
        if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or $output[0].Length -gt 4096) {
            throw 'legacy_pair_rollback_review_changed'
        }
        try {$status=$output[0]|ConvertFrom-Json -AsHashtable} catch {throw 'legacy_pair_rollback_review_changed'}
        if ($status.Count -ne 3 -or $status.phase -cne 'pair_rollback_reviewed' -or
            $status.live_files_changed -ne $false -or $status.replayed -ne $false) {throw 'legacy_pair_rollback_review_changed'}
        return $status
    }
    $intent=Get-LegacyPairJson (Join-Path $folder 'committed-intent.json')
    $receipt=Get-LegacyPairJson (Join-Path $folder 'completed.json')
    if ($receipt.schema_version -ne 1 -or $receipt.phase -cne 'committed' -or
        $receipt.intent_sha256 -cne (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $folder 'committed-intent.json'))) -or
        $intent.schema_version -ne 1 -or $intent.phase -cne 'may_have_written') {throw 'legacy_pair_transaction_invalid'}
    return $intent
}

function Get-LegacyArchivedEntryWitness {
    param([string]$Project,[string]$Home,[string]$BeforeSha256,[string]$AfterSha256,$Workflow,[switch]$Historical)
    $expected=Join-Path $Project '.codex/operator-unified-startup'
    if ($Workflow -isnot [Collections.IDictionary] -or $Workflow.path -ine $expected -or
        $Workflow.contract -or
        $Workflow.startup_script_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $Workflow.startup_metadata_sha256 -cnotmatch '^[a-f0-9]{64}$') {
        throw 'legacy_pair_recovery_workflow_changed'
    }
    $currentScript=Read-LegacyPairBytes (Join-Path $expected 'start-codex-with-web.ps1')
    $currentMetadata=Read-LegacyPairBytes (Join-Path $expected 'startup-sync-plan.json')
    $currentScriptHash=Get-LegacyPairHash $currentScript
    $currentMetadataHash=Get-LegacyPairHash $currentMetadata
    $originalScript=$currentScript;$retainedPath=$null
    if ($currentScriptHash -cne $Workflow.startup_script_sha256 -or
        $currentMetadataHash -cne $Workflow.startup_metadata_sha256) {
        # A witnessed renewal moved the original workflow rather than editing it.
        # Select only exact retained bytes to bind Python before executing the
        # read-only canonical verifier. A changed unjournaled workflow still fails.
        $root=Join-Path $Home 'operator-unified-workflow-renewal'
        Assert-LegacyPairPath $root
        if (-not (Test-Path -LiteralPath $root)) {throw 'legacy_pair_recovery_workflow_changed'}
        $runs=@(Get-ChildItem -LiteralPath $root -Force)
        if ($runs.Count -lt 1 -or $runs.Count -gt 32) {throw 'legacy_pair_recovery_workflow_changed'}
        $workflowCandidates=@()
        foreach ($run in $runs) {
            Assert-LegacyPairPath $run.FullName
            if (-not $run.PSIsContainer -or $run.Name -cnotmatch '^generation-[a-f0-9]{32}$') {throw 'legacy_pair_recovery_workflow_changed'}
            $evidence=Join-Path $run.FullName 'evidence'
            $oldScript=Read-LegacyPairBytes (Join-Path $evidence 'start-codex-with-web.ps1')
            $oldMetadata=Read-LegacyPairBytes (Join-Path $evidence 'startup-sync-plan.json')
            if ($null -ne $oldScript -and $null -ne $oldMetadata -and
                (Get-LegacyPairHash $oldScript) -ceq $Workflow.startup_script_sha256 -and
                (Get-LegacyPairHash $oldMetadata) -ceq $Workflow.startup_metadata_sha256) {
                $workflowCandidates+=@{path=$evidence;script=$oldScript}
            }
        }
        if ($workflowCandidates.Count -ne 1) {throw 'legacy_pair_recovery_workflow_changed'}
        $retainedPath=$workflowCandidates[0].path;$originalScript=$workflowCandidates[0].script
    }
    $script=$script:LegacyUtf8.GetString($originalScript)
    $pathMatch=[regex]::Matches($script,"(?m)^\`$python = '((?:[^']|'')*)'\r?$")
    $hashMatch=[regex]::Matches($script,
        '(?m)^if \(\(Get-FileHash -LiteralPath \$python -Algorithm SHA256\)\.Hash\.ToLowerInvariant\(\) -cne ''([a-f0-9]{64})''\) \{ throw ''Saved Python changed\.'' \}\r?$')
    if ($pathMatch.Count -ne 1 -or $hashMatch.Count -ne 1) {throw 'legacy_pair_recovery_interpreter_invalid'}
    $python=$pathMatch[0].Groups[1].Value.Replace("''", "'")
    if (-not [IO.Path]::IsPathFullyQualified($python) -or
        (Get-LegacyPairHash (Read-LegacyPairBytes $python)) -cne $hashMatch[0].Groups[1].Value) {throw 'legacy_pair_recovery_interpreter_changed'}
    if ($retainedPath) {
        $verify=@'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from operator_unified_workflow_renew import retained_workflow
result=retained_workflow(Path(sys.argv[2]),Path(sys.argv[3]))
if result is None or str(result).casefold()!=sys.argv[4].casefold():
    raise ValueError('legacy_pair_retained_workflow_not_witnessed')
print(json.dumps({'status':'retained_workflow_witnessed','path':str(result)}))
'@
        $output=@(& $python -X utf8 -E -s -B -c $verify $PSScriptRoot $Project $Home $retainedPath 2>$null)
        if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or $output[0].Length -gt 4096) {throw 'legacy_pair_retained_workflow_not_witnessed'}
        try {$witnessed=$output[0]|ConvertFrom-Json -AsHashtable} catch {throw 'legacy_pair_retained_workflow_not_witnessed'}
        if ($witnessed.Count -ne 2 -or $witnessed.status -cne 'retained_workflow_witnessed' -or
            $witnessed.path -ine $retainedPath -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $expected 'start-codex-with-web.ps1'))) -cne $currentScriptHash -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $expected 'startup-sync-plan.json'))) -cne $currentMetadataHash) {throw 'legacy_pair_retained_workflow_not_witnessed'}
    }
    $arguments=@('-X','utf8','-E','-s','-B',(Join-Path $PSScriptRoot 'operator_unified_retire.py'),
        'archived-entry-status','--plan',(Join-Path $Home 'operator-unified-activation/plan.json'),
        '--project-root',$Project,'--entry-before-sha256',$BeforeSha256,'--entry-after-sha256',$AfterSha256)
    if ($Historical) {$arguments+='--historical-entry'}
    $output=@(& $python @arguments 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or $output[0].Length -gt 65536) {throw 'legacy_pair_archived_recovery_not_witnessed'}
    try {$status=$output[0]|ConvertFrom-Json -AsHashtable} catch {throw 'legacy_pair_archived_recovery_not_witnessed'}
    if ($status.status -cne 'archived_retired_entry_witnessed' -or
        $status.recovery.entry_before_sha256 -cne $BeforeSha256 -or $status.recovery.entry_recovered_sha256 -cne $AfterSha256 -or
        $status.startup_bundle.path -ine $expected -or
        $status.startup_bundle.startup_script_sha256 -cne $currentScriptHash -or
        $status.startup_bundle.sync_plan_sha256 -cne $currentMetadataHash -or
        $status.archive_witness_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $status.retirement_intent_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $expected 'start-codex-with-web.ps1'))) -cne $currentScriptHash -or
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $expected 'startup-sync-plan.json'))) -cne $currentMetadataHash) {throw 'legacy_pair_archived_recovery_not_witnessed'}
    return @{contract='archived_unified_entry_recovery_v1';before_sha256=$BeforeSha256;after_sha256=$AfterSha256;
        archive_witness_sha256=$status.archive_witness_sha256;retirement_intent_sha256=$status.retirement_intent_sha256}
}

function Get-LegacyDirectWorkflow {
    param([string]$Project,[string]$Home,$Config,[AllowNull()][byte[]]$IndexBytes,[switch]$Historical)
    $path=Join-Path $Project '.codex/operator-direct-startup'
    if ($Config.mode -cne 'direct_profile' -or $Config.startup_bundle -cne '.codex/operator-direct-startup' -or
        $Config.direct_entry_plan_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_direct_workflow_invalid'}
    if ($null -eq $IndexBytes) {$IndexBytes=Read-LegacyPairBytes (Join-Path $path 'direct-entry-plan.json')}
    if ($IndexBytes.Length -gt 65536 -or (Get-LegacyPairHash $IndexBytes) -cne $Config.direct_entry_plan_sha256) {throw 'legacy_pair_direct_workflow_changed'}
    try {$index=$script:LegacyUtf8.GetString($IndexBytes)|ConvertFrom-Json -AsHashtable} catch {throw 'legacy_pair_direct_workflow_invalid'}
    $keys=@('schema_version','contract','project','home','python','python_sha256','native_helper','native_helper_sha256',
        'controller','controller_sha256','entry_script_sha256','profiles')
    if ($index -isnot [Collections.IDictionary] -or @((Compare-Object @($index.Keys|Sort-Object) @($keys|Sort-Object))).Count -or
        $index.schema_version -ne 1 -or $index.contract -cne 'direct_profile_picker_v1' -or $index.project -ine $Project -or
        $index.home -ine $Home -or $index.entry_script_sha256 -cne $Config.entry_script_sha256 -or
        $index.controller -ine (Join-Path $Project 'plugins/feishu-codex-operator/scripts/operator_direct_entry.py') -or
        $index.profiles -isnot [Collections.IList] -or $index.profiles.Count -lt 1 -or $index.profiles.Count -gt 32) {throw 'legacy_pair_direct_workflow_invalid'}
    foreach ($name in @('python','native_helper','controller')) {
        if ($index[$name] -isnot [string] -or -not [IO.Path]::IsPathFullyQualified($index[$name]) -or
            $index[$name+'_sha256'] -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_direct_workflow_invalid'}
        if (-not $Historical -and (Get-LegacyPairHash (Read-LegacyPairBytes $index[$name])) -cne $index[$name+'_sha256']) {throw 'legacy_pair_direct_dependency_changed'}
    }
    $profiles=@{}
    foreach ($row in $index.profiles) {
        if ($row -isnot [Collections.IDictionary] -or
            @((Compare-Object @($row.Keys|Sort-Object) @('display_name','plan','plan_sha256','profile'))).Count -or
            $row.profile -isnot [string] -or $row.profile -cnotmatch '^operator-[a-z0-9][a-z0-9-]{0,49}$' -or $profiles.ContainsKey($row.profile) -or
            $row.display_name -isnot [string] -or $row.display_name.Length -lt 1 -or $row.display_name.Length -gt 256 -or
            $row.display_name -match '[\x00-\x1f\x7f]' -or
            $row.plan -isnot [string] -or -not [IO.Path]::IsPathFullyQualified($row.plan) -or
            $row.plan_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_direct_profile_invalid'}
        $parent=Split-Path -Parent $row.plan
        if ((Split-Path -Leaf $row.plan) -cne 'plan.json' -or (Split-Path -Leaf $parent) -cnotmatch '^[a-f0-9]{32}$' -or
            (Split-Path -Parent $parent) -ine (Join-Path $Project '.codex/operator-direct-startup/plans')) {throw 'legacy_pair_direct_profile_invalid'}
        $profiles[$row.profile]=$true
        if (-not $Historical -and (Get-LegacyPairHash (Read-LegacyPairBytes $row.plan)) -cne $row.plan_sha256) {throw 'legacy_pair_direct_dependency_changed'}
    }
    return @{contract='direct_profile_picker_v1';path=$path;entry_plan_sha256=$Config.direct_entry_plan_sha256;
        entry_script_sha256=$Config.entry_script_sha256}
}

function Get-LegacyIsolatedWorkflow {
    param([string]$Project,[string]$Home,$Config,[AllowNull()][byte[]]$EntryBytes,[switch]$Historical)
    if ($Config.mode -cne 'isolated_mode' -or $Config.startup_bundle -cnotmatch '^\.codex/operator-mode-entry/[a-f0-9]{32}$' -or
        $Config.mode_entry_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_isolated_workflow_invalid'}
    $root=[IO.Path]::GetFullPath((Join-Path $Project $Config.startup_bundle))
    if ($null -eq $EntryBytes) {$EntryBytes=Read-LegacyPairBytes (Join-Path $root 'entry.json')}
    if ((Get-LegacyPairHash $EntryBytes) -cne $Config.mode_entry_sha256) {throw 'legacy_pair_isolated_workflow_changed'}
    try {$entry=$script:LegacyUtf8.GetString($EntryBytes)|ConvertFrom-Json -AsHashtable} catch {throw 'legacy_pair_isolated_workflow_invalid'}
    if ($entry.schema_version -ne 1 -or $entry.contract -cne 'operator_isolated_mode_entry_v1' -or
        $entry.root -ine $root -or $entry.project -ine $Project -or $entry.native_home -ine $Home -or
        $entry.native_enabled -ne $false -or $entry.entry_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_isolated_workflow_invalid'}
    if (-not $Historical -and
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root 'entry.ps1'))) -cne $entry.entry_sha256) {throw 'legacy_pair_isolated_workflow_changed'}
    return @{contract='operator_isolated_mode_entry_v1';path=$root;entry_plan_sha256=$Config.mode_entry_sha256;
        entry_script_sha256=$Config.entry_script_sha256}
}

function Get-OperatorLegacyPairAttachment {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)]$Migration,[Parameter(Mandatory)]$BeforeBuild)
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $root=Join-Path $project '.codex/operator-desktop-pair'
    if (-not (Test-Path -LiteralPath $root)) {return $null}
    foreach ($dir in @(Get-ChildItem -LiteralPath (Join-Path $root 'upgrades') -Directory -ErrorAction SilentlyContinue)) {
        Get-LegacyPairTransaction $root $dir.Name | Out-Null
    }
    $record=Get-LegacyPairJson (Join-Path $root 'ownership.json')
    if ($record.scope -cne 'legacy_entry_only') {throw 'legacy_pair_scope_conflict'}
    $originPath=Join-Path $root 'legacy-origin.json';$origin=Get-LegacyPairJson $originPath
    if ($origin.schema_version -ne 1 -or $origin.scope -cne 'legacy_pair_origin' -or $origin.project -ine $project -or
        $record.schema_version -ne 1 -or $record.project -ine $project -or $record.home -ine $origin.home -or
        $record.phase -notin @('installed','restored') -or $record.runtime_ownership -cne 'unresolved' -or
        $record.origin_sha256 -cne (Get-LegacyPairHash (Read-LegacyPairBytes $originPath)) -or
        -not (Test-LegacyPairEqual $BeforeBuild $origin.before_build)) {throw 'legacy_pair_origin_invalid'}
    Assert-LegacyPairBuild $BeforeBuild
    $originalPath=Join-Path $root 'originals/migration.json'
    if ((Get-LegacyPairHash (Read-LegacyPairBytes $originalPath)) -cne $origin.migration_sha256) {throw 'legacy_pair_migration_backup_changed'}
    $original=Get-LegacyPairJson $originalPath
    if ($original.phase -cne 'installed' -or $Migration.phase -notin @('installed','restoring','restored')) {throw 'legacy_pair_migration_changed'}
    $compare=Get-LegacyPairJson (Join-Path $project '.codex/operator-entry-migration/journal.json')
    if (-not (Test-LegacyPairEqual $Migration $compare)) {throw 'legacy_pair_migration_changed'}
    if ($compare.phase -ceq 'installed' -and
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-migration/journal.json'))) -cne $origin.migration_sha256) {throw 'legacy_pair_migration_changed'}
    $compare.phase='installed'
    if (-not (Test-LegacyPairEqual $original $compare)) {throw 'legacy_pair_migration_changed'}
    foreach ($row in $origin.evidence) {
        if ($row.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-LegacyPairHash (Read-LegacyPairBytes $row.path)) -cne $row.sha256 -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root ('originals/'+$row.sha256+'.bin')))) -cne $row.sha256) {throw 'legacy_pair_evidence_changed'}
    }
    $paths=Get-LegacyPairPaths
    if ($paths.Count -ne 2 -or $origin.desktop -ine $paths[0] -or $origin.start -ine $paths[1] -or
        $record.legacy.desktop -ine $origin.desktop -or $record.legacy.start -ine $origin.start) {throw 'legacy_pair_path_changed'}
    foreach ($path in $paths) {
        $owned=& $script:LegacyEntry {param($P,$M,$L) Get-OperatorEntryAdoptionAfter $P $M $L} $project $Migration $path
        if ($origin.entries[$path].sha256 -cne $owned) {throw 'legacy_pair_adoption_changed'}
    }
    if ($record.steps -isnot [Collections.IList] -or $record.steps.Count -lt 1 -or $record.steps.Count -gt 128) {throw 'legacy_pair_build_chain_invalid'}
    $previous=$BeforeBuild;$previousWorkflow=$null
    foreach ($step in $record.steps) {
        Assert-LegacyPairBuild $step.before;Assert-LegacyPairBuild $step.after
        if ($step.recovered_entry) {
            $witness=$step.recovered_entry
            if ($witness -isnot [Collections.IDictionary] -or $witness.Count -ne 5 -or
                $witness.contract -cne 'archived_unified_entry_recovery_v1' -or
                $witness.before_sha256 -cne $previous['desktop-entry.json'] -or
                $witness.after_sha256 -cne $step.before['desktop-entry.json']) {throw 'legacy_pair_recovery_chain_invalid'}
            $expected=@{};foreach ($name in $previous.Keys) {$expected[$name]=$previous[$name]}
            $expected['desktop-entry.json']=$witness.after_sha256
            if (-not (Test-LegacyPairEqual $expected $step.before)) {throw 'legacy_pair_recovery_chain_invalid'}
            $currentWitness=Get-LegacyArchivedEntryWitness $project $record.home $witness.before_sha256 $witness.after_sha256 $previousWorkflow -Historical
            if (-not (Test-LegacyPairEqual $currentWitness $witness)) {throw 'legacy_pair_recovery_chain_invalid'}
        } elseif (-not (Test-LegacyPairEqual $previous $step.before)) {throw 'legacy_pair_build_chain_invalid'}
        $intent=Get-LegacyPairTransaction $root $step.generation
        foreach ($name in $step.after.Keys) {
            if ($name -ceq 'Codex拓展入口.ico') {
                if ($step.after[$name] -cne $step.before[$name]) {throw 'legacy_pair_icon_changed'}
                continue
            }
            $rows=@($intent.changes|Where-Object {$_.path -ieq (Join-Path $project ('.codex/operator-desktop-entry/'+$name))})
            if ($rows.Count -ne 1 -or $rows[0].before -cne $step.before[$name] -or $rows[0].after -cne $step.after[$name]) {throw 'legacy_pair_build_chain_invalid'}
        }
        $configPath=Join-Path $root ('generations/'+$step.generation+'/entry-config.after.json')
        if ((Get-LegacyPairHash (Read-LegacyPairBytes $configPath)) -cne $step.after['desktop-entry.json']) {throw 'legacy_pair_config_backup_changed'}
        $stepConfig=Get-LegacyPairJson $configPath
        if ($stepConfig.mode -ceq 'direct_profile') {
            $indexPath=Join-Path $root ('generations/'+$step.generation+'/direct-entry-plan.after.json')
            $bound=Get-LegacyDirectWorkflow $project $record.home $stepConfig (Read-LegacyPairBytes $indexPath) -Historical
            if (-not (Test-LegacyPairEqual $bound $step.workflow)) {throw 'legacy_pair_direct_workflow_invalid'}
        } elseif ($stepConfig.mode -ceq 'isolated_mode') {
            $indexPath=Join-Path $root ('generations/'+$step.generation+'/isolated-entry.after.json')
            $bound=Get-LegacyIsolatedWorkflow $project $record.home $stepConfig (Read-LegacyPairBytes $indexPath) -Historical
            if (-not (Test-LegacyPairEqual $bound $step.workflow)) {throw 'legacy_pair_isolated_workflow_invalid'}
        } elseif ($step.workflow.contract) {throw 'legacy_pair_workflow_invalid'}
        $previous=$step.after;$previousWorkflow=$step.workflow
    }
    if (-not (Test-LegacyPairEqual $previous $record.build) -or $record.generation -cne $record.steps[-1].generation) {throw 'legacy_pair_build_chain_invalid'}
    $latest=Get-LegacyPairTransaction $root $record.transaction
    $receiptPath=Join-Path $root 'ownership.json';$receiptHash=Get-LegacyPairHash (Read-LegacyPairBytes $receiptPath)
    $rows=@($latest.changes|Where-Object {$_.path -ieq $receiptPath})
    if ($rows.Count -ne 1 -or $rows[0].after -cne $receiptHash) {throw 'legacy_pair_receipt_changed'}
    $config=Get-LegacyPairJson $configPath
    $workflow=$record.steps[-1].workflow
    if ($config.mode -ceq 'reviewed_startup' -and ($workflow.path -ine [IO.Path]::GetFullPath((Join-Path $project $config.startup_bundle)) -or
        $workflow.startup_script_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $workflow.startup_metadata_sha256 -cnotmatch '^[a-f0-9]{64}$')) {throw 'legacy_pair_workflow_invalid'}
    return @{before=$BeforeBuild;after=$record.build;config_after_path=$configPath;codex_home=$record.home;
        startup_bundle=$workflow.path;startup_script_sha256=$workflow.startup_script_sha256;
        startup_metadata_sha256=$workflow.startup_metadata_sha256;phase=$record.phase;
        origin_sha256=$record.origin_sha256;receipt_sha256=$receiptHash;record=$record}
}

function Assert-LegacyPairShortcut([string]$Path,$Expected,[switch]$Renamed) {
    if ((Get-LegacyPairHash (Read-LegacyPairBytes $Path)) -cne $Expected.sha256 -or
        (Get-LegacyPairIdentity $Path) -cne $Expected.identity) {throw 'legacy_pair_shortcut_changed'}
    $com=Get-LegacyPairCom $Path;$wanted=$Expected.com
    foreach ($key in $wanted.Keys) {
        if ($key -ceq 'full_name' -and $Renamed) {if ($com[$key] -ine $Path) {throw 'legacy_pair_shortcut_changed'}}
        elseif ($com[$key] -cne $wanted[$key]) {throw 'legacy_pair_shortcut_changed'}
    }
}
function Get-OperatorDesktopLegacyPairState {
    param([Parameter(Mandatory)][string]$ProjectRoot,[switch]$CheckCurrent,[Collections.IDictionary]$RecoveredConfig)
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $migration=& $script:LegacyEntry {param($P) Get-OperatorEntryMigrationState $P} $project
    $before=& $script:LegacyEntry {param($P,$M) Get-OperatorEntryConfigUpgradeBuild $P $M} $project $migration
    $attachment=Get-OperatorLegacyPairAttachment $project $migration $before
    if (-not $attachment) {throw 'legacy_pair_not_installed'}
    $record=$attachment.record;$root=Join-Path $project '.codex/operator-desktop-pair'
    $origin=Get-LegacyPairJson (Join-Path $root 'legacy-origin.json')
    if ($record.files -isnot [Collections.IDictionary] -or $record.files.Count -ne 4 -or
        $record.links -isnot [Collections.IDictionary] -or $record.links.Count -ne 2 -or
        $record.build_date -cnotmatch '^\d{4}-\d{2}-\d{2}$' -or $record.desktop -ine (Split-Path -Parent $origin.desktop)) {throw 'legacy_pair_record_invalid'}
    $native=Join-Path $record.desktop 'ChatGPT 原生入口.lnk'
    $extended=Join-Path $record.desktop ('ChatGPT 拓展模型 '+$record.build_date.Substring(5)+' 入口.lnk')
    foreach ($path in @($native,$extended)) {if (-not $record.links.Contains($path) -or $record.links[$path].after -cnotmatch '^[a-f0-9]{64}$') {throw 'legacy_pair_record_invalid'}}
    foreach ($name in @('operator_native_entry.ps1','operator_desktop_entry.ps1','restore-codex-official-route.ps1','native-entry.json')) {
        if ($record.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root ('generations/'+$record.generation+'/'+$name)))) -cne $record.files[$name]) {throw 'legacy_pair_helper_changed'}
    }
    if ($CheckCurrent) {
        $configActual=Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json'))
        if (-not $RecoveredConfig -and $configActual -cne $record.build['desktop-entry.json']) {
            if (Test-Path -LiteralPath (Join-Path $record.home 'operator-unified-activation')) {
                $witness=& $script:LegacyEntry {param($P,$B) Get-OperatorUnifiedRetiredEntryHash $P $B} $project $record.build
                $RecoveredConfig=@{before_sha256=$record.build['desktop-entry.json'];after_sha256=$witness}
            } else {
                $RecoveredConfig=Get-LegacyArchivedEntryWitness $project $record.home $record.build['desktop-entry.json'] $configActual $record.steps[-1].workflow
            }
        }
        foreach ($name in $record.build.Keys) {
            $actual=Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project ('.codex/operator-desktop-entry/'+$name)))
            if ($actual -cne $record.build[$name] -and -not ($name -ceq 'desktop-entry.json' -and $RecoveredConfig -and
                $RecoveredConfig.before_sha256 -ceq $record.build[$name] -and $RecoveredConfig.after_sha256 -ceq $actual)) {throw 'legacy_pair_build_changed'}
        }
        $currentConfig=Get-LegacyPairJson (Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json')
        if ($currentConfig.mode -ceq 'direct_profile') {
            $bound=Get-LegacyDirectWorkflow $project $record.home $currentConfig
            if (-not (Test-LegacyPairEqual $bound $record.steps[-1].workflow)) {throw 'legacy_pair_direct_workflow_changed'}
        } elseif ($currentConfig.mode -ceq 'isolated_mode') {
            $bound=Get-LegacyIsolatedWorkflow $project $record.home $currentConfig
            if (-not (Test-LegacyPairEqual $bound $record.steps[-1].workflow)) {throw 'legacy_pair_isolated_workflow_changed'}
        }
        if ($record.phase -ceq 'installed') {
            if ($null -ne (Read-LegacyPairBytes $origin.desktop)) {throw 'legacy_pair_old_name_conflict'}
            Assert-LegacyPairShortcut $extended $origin.entries[$origin.desktop] -Renamed
            Assert-LegacyPairShortcut $origin.start $origin.entries[$origin.start]
            if ((Get-LegacyPairHash (Read-LegacyPairBytes $native)) -cne $record.links[$native].after) {throw 'legacy_pair_native_link_changed'}
        } else {
            foreach ($path in @($native,$extended)) {if ($null -ne (Read-LegacyPairBytes $path)) {throw 'legacy_pair_restored_name_conflict'}}
            if ($migration.phase -ceq 'installed') {
                Assert-LegacyPairShortcut $origin.desktop $origin.entries[$origin.desktop]
                Assert-LegacyPairShortcut $origin.start $origin.entries[$origin.start]
            }
        }
    }
    return $record
}

function Get-LegacyPairEnvironment([string]$Project,[string]$homePath) {
    if ($homePath -ine (Get-LegacyPairHome) -or ($env:CODEX_HOME -and [IO.Path]::GetFullPath($env:CODEX_HOME).TrimEnd('\') -ine $homePath)) {throw 'pair_default_home_required'}
    if (Test-Path -LiteralPath (Join-Path $homePath 'operator-unified-activation')) {throw 'pair_activation_requires_separate_review'}
    $bytes=Read-LegacyPairBytes (Join-Path $homePath 'config.toml')
    $route=& $script:LegacyPair {param($B) Get-RecoveryConfigPlan $B} $bytes
    if ($route.state -cne 'native') {throw 'legacy_pair_native_route_required'}
    foreach ($scope in @('Process','User','Machine')) {if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL',$scope)) {throw 'legacy_pair_environment_override'}}
    if (Test-Path -LiteralPath (Join-Path $Project '.codex/operator-installation/ownership.json')) {throw 'legacy_pair_owner_conflict'}
    if (Test-Path -LiteralPath (Join-Path $Project '.codex/operator-desktop-entry/native-only')) {throw 'legacy_pair_native_only_requires_review'}
    return Get-LegacyPairHash $bytes
}
function Get-OperatorDesktopLegacyPairPlan {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CandidateDirectory,[string]$CodexHome)
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\');$root=Join-Path $project '.codex/operator-desktop-pair'
    $homePath=if ($CodexHome) {[IO.Path]::GetFullPath($CodexHome).TrimEnd('\')} else {Get-LegacyPairHome}
    $nativeConfig=Get-LegacyPairEnvironment $project $homePath
    $candidate=Get-OperatorEntryBuildCandidate $project $CandidateDirectory
    if ((Test-Path -LiteralPath (Join-Path $homePath 'operator-direct-entry')) -and -not $candidate.record.Contains('direct_picker') -and -not $candidate.record.Contains('isolated_mode')) {throw 'direct_cycle_maintenance_requires_bound_python'}
    $migration=& $script:LegacyEntry {param($P) Get-OperatorEntryMigrationState $P} $project
    if ($migration.phase -cne 'installed') {throw 'legacy_pair_installed_migration_required'}
    if ((Get-LegacyPairHash (Read-LegacyPairBytes $migration.plan.receipt)) -cne $migration.plan.receipt_sha256 -or
        (Get-LegacyPairHash (Read-LegacyPairBytes $migration.plan.legacy_executable)) -cne $migration.plan.legacy_executable_sha256) {throw 'legacy_pair_original_evidence_changed'}
    $migrationPlanBytes=$script:LegacyUtf8.GetBytes(($migration.plan|ConvertTo-Json -Depth 8 -Compress))
    if ((Get-LegacyPairHash $migrationPlanBytes) -cne $migration.plan_sha256) {throw 'legacy_pair_migration_changed'}
    foreach ($row in $migration.entries.Values) {
        if ($row.before -cne 'absent' -and (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project ('.codex/operator-entry-migration/originals/'+$row.before+'.bin')))) -cne $row.before) {throw 'legacy_pair_original_evidence_changed'}
    }
    $base=& $script:LegacyEntry {param($P,$M) Get-OperatorEntryConfigUpgradeBuild $P $M} $project $migration
    $paths=Get-LegacyPairPaths;$previous=$null;$entries=[ordered]@{};$recoveredEntry=$null
    if (Test-Path -LiteralPath $root) {
        $previous=Get-OperatorDesktopLegacyPairState $project -CheckCurrent
        if ($previous.phase -cne 'installed') {throw 'legacy_pair_restored_requires_review'}
        $base=@{};foreach ($name in $previous.build.Keys) {$base[$name]=$previous.build[$name]}
        $actualConfig=Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json'))
        if ($actualConfig -cne $base['desktop-entry.json']) {
            $recoveredEntry=Get-LegacyArchivedEntryWitness $project $homePath $base['desktop-entry.json'] $actualConfig $previous.steps[-1].workflow
            $base['desktop-entry.json']=$actualConfig
        }
        $origin=Get-LegacyPairJson (Join-Path $root 'legacy-origin.json');$entries=$origin.entries
        $oldLink=Join-Path $previous.desktop ('ChatGPT 拓展模型 '+$previous.build_date.Substring(5)+' 入口.lnk')
        $receiptSha=Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root 'ownership.json'))
    } else {
        foreach ($path in $paths) {
            $sha=& $script:LegacyEntry {param($P,$M,$L) Get-OperatorEntryAdoptionAfter $P $M $L -CheckCurrent} $project $migration $path
            if ((Get-LegacyPairHash (Read-LegacyPairBytes $path)) -cne $sha -or $sha -ceq 'absent') {throw 'legacy_pair_shortcut_changed'}
            $entries[$path]=[ordered]@{sha256=$sha;identity=(Get-LegacyPairIdentity $path);com=(Get-LegacyPairCom $path)}
        }
        $oldLink=$paths[0];$receiptSha='absent'
    }
    Assert-LegacyPairBuild $base
    foreach ($name in $base.Keys) {if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project ('.codex/operator-desktop-entry/'+$name)))) -cne $base[$name]) {throw 'legacy_pair_build_changed'}}
    if ($candidate.record.config_before_sha256 -cne $base['desktop-entry.json'] -or $candidate.record.icon_before_sha256 -cne $base['Codex拓展入口.ico']) {throw 'pair_candidate_baseline_changed'}
    $desktop=Split-Path -Parent $paths[0];$native=Join-Path $desktop 'ChatGPT 原生入口.lnk'
    $newLink=Join-Path $desktop ('ChatGPT 拓展模型 '+$candidate.record.build_date.Substring(5)+' 入口.lnk')
    foreach ($path in @($native,$newLink)) {
        if (($null -eq $previous -or -not $previous.links.Contains($path)) -and $null -ne (Read-LegacyPairBytes $path)) {throw 'pair_shortcut_name_conflict'}
    }
    $evidence=[ordered]@{}
    foreach ($path in @($migration.plan.receipt,$migration.plan.legacy_executable)) {$evidence[$path]=Get-LegacyPairHash (Read-LegacyPairBytes $path)}
    foreach ($row in $migration.entries.Values) {
        if ($row.before -cne 'absent') {$evidence[(Join-Path $project ('.codex/operator-entry-migration/originals/'+$row.before+'.bin'))]=$row.before}
    }
    foreach ($relative in @('operator-entry-upgrade/intent.json','operator-entry-upgrade/receipt.json','operator-entry-upgrade/before.json','operator-entry-upgrade/after.json',
            'operator-entry-shortcut-adoption/intent.json','operator-entry-shortcut-adoption/receipt.json','operator-entry-shortcut-adoption/adopted-desktop.lnk')) {
        $path=Join-Path $project ('.codex/'+$relative);$sha=Get-LegacyPairHash (Read-LegacyPairBytes $path)
        if ($sha -cne 'absent') {$evidence[$path]=$sha}
    }
    $config=Get-LegacyPairJson (Join-Path $candidate.directory 'desktop-entry.json');$workflow=$null
    if ($config.mode -ceq 'reviewed_startup') {
        $workflowPath=[IO.Path]::GetFullPath((Join-Path $project $config.startup_bundle))
        if ((Split-Path -Parent $workflowPath) -ine (Join-Path $project '.codex')) {throw 'legacy_pair_workflow_scope_invalid'}
        if ($previous) {$workflow=$previous.steps[-1].workflow}
        elseif (Test-Path -LiteralPath (Join-Path $project '.codex/operator-entry-upgrade/intent.json')) {
            $upgrade=Get-LegacyPairJson (Join-Path $project '.codex/operator-entry-upgrade/intent.json')
            $workflow=@{path=$upgrade.plan.startup_bundle;startup_script_sha256=$upgrade.plan.startup_script_sha256;startup_metadata_sha256=$upgrade.plan.startup_metadata_sha256}
        } else {$workflow=@{path=$migration.plan.startup_bundle;startup_script_sha256=$migration.plan.workflow_sha256;startup_metadata_sha256=$migration.plan.metadata_sha256}}
        $metadata=Get-LegacyPairJson (Join-Path $workflowPath 'startup-sync-plan.json')
        if ($workflow.path -ine $workflowPath -or $metadata.schema_version -ne 2 -or $metadata.startup_script -cne 'start-codex-with-web.ps1' -or
            $metadata.entry_files.'start-codex-with-web.ps1' -cne $workflow.startup_script_sha256 -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $workflowPath 'start-codex-with-web.ps1'))) -cne $workflow.startup_script_sha256 -or
            (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $workflowPath 'startup-sync-plan.json'))) -cne $workflow.startup_metadata_sha256) {throw 'legacy_pair_workflow_changed'}
    } elseif ($config.mode -ceq 'direct_profile') {$workflow=Get-LegacyDirectWorkflow $project $homePath $config}
    elseif ($config.mode -ceq 'isolated_mode') {$workflow=Get-LegacyIsolatedWorkflow $project $homePath $config}
    $sources=[ordered]@{}
    foreach ($name in @('operator_desktop_pair_legacy.psm1','operator_entry_migration.ps1','operator_entry_shortcut_adoption.ps1','operator_desktop_setup.ps1')) {$sources[$name]=Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $PSScriptRoot $name))}
    $plan=[ordered]@{schema_version=1;scope='legacy_pair_upgrade';project=$project;home=$homePath;desktop=$desktop;
        candidate_directory=$candidate.directory;candidate_sha256=$candidate.sha256;native_config_sha256=$nativeConfig;
        migration_sha256=(Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-migration/journal.json')));
        previous_receipt_sha256=$receiptSha;before_build=$base;entries=$entries;old_link=$oldLink;new_link=$newLink;native_link=$native;
        evidence=$evidence;workflow=$workflow;sources=$sources;runtime_ownership='unresolved'}
    if ($recoveredEntry) {$plan.recovered_entry=$recoveredEntry}
    $previewHash=& $script:LegacyUpgrade {param($Plan) Get-OperatorPairPreviewHash $Plan} $plan
    return @{plan=$plan;sha256=$previewHash;candidate=$candidate;previous=$previous;configuration_changed=$false}
}

function Assert-LegacyPairBoundary($Review) {
    $plan=$Review.plan;$project=$plan.project;$root=Join-Path $project '.codex/operator-desktop-pair'
    if ((Get-LegacyPairEnvironment $project $plan.home) -cne $plan.native_config_sha256 -or
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root 'ownership.json'))) -cne $plan.previous_receipt_sha256 -or
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-migration/journal.json'))) -cne $plan.migration_sha256) {throw 'legacy_pair_preview_changed'}
    $candidate=Get-OperatorEntryBuildCandidate $project $plan.candidate_directory
    if ($candidate.sha256 -cne $plan.candidate_sha256) {throw 'legacy_pair_preview_changed'}
    foreach ($name in $plan.sources.Keys) {if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $PSScriptRoot $name))) -cne $plan.sources[$name]) {throw 'legacy_pair_source_changed'}}
    foreach ($path in $plan.evidence.Keys) {if ((Get-LegacyPairHash (Read-LegacyPairBytes $path)) -cne $plan.evidence[$path]) {throw 'legacy_pair_evidence_changed'}}
    if ($plan.workflow.contract -ceq 'direct_profile_picker_v1') {
        $config=Get-LegacyPairJson (Join-Path $candidate.directory 'desktop-entry.json')
        $bound=Get-LegacyDirectWorkflow $project $plan.home $config
        if (-not (Test-LegacyPairEqual $bound $plan.workflow)) {throw 'legacy_pair_direct_workflow_changed'}
    } elseif ($plan.workflow.contract -ceq 'operator_isolated_mode_entry_v1') {
        $config=Get-LegacyPairJson (Join-Path $candidate.directory 'desktop-entry.json')
        $bound=Get-LegacyIsolatedWorkflow $project $plan.home $config
        if (-not (Test-LegacyPairEqual $bound $plan.workflow)) {throw 'legacy_pair_isolated_workflow_changed'}
    } elseif ($plan.workflow -and (
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $plan.workflow.path 'start-codex-with-web.ps1'))) -cne $plan.workflow.startup_script_sha256 -or
        (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $plan.workflow.path 'startup-sync-plan.json'))) -cne $plan.workflow.startup_metadata_sha256)) {throw 'legacy_pair_workflow_changed'}
    if ($plan.recovered_entry) {
        $current=Get-LegacyArchivedEntryWitness $project $plan.home $plan.recovered_entry.before_sha256 $plan.recovered_entry.after_sha256 $Review.previous.steps[-1].workflow
        if (-not (Test-LegacyPairEqual $current $plan.recovered_entry)) {throw 'legacy_pair_recovery_chain_invalid'}
    }
    foreach ($name in $plan.before_build.Keys) {if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project ('.codex/operator-desktop-entry/'+$name)))) -cne $plan.before_build[$name]) {throw 'legacy_pair_build_changed'}}
    $paths=Get-LegacyPairPaths
    Assert-LegacyPairShortcut $plan.old_link $plan.entries[$paths[0]] -Renamed:($plan.old_link -ine $paths[0])
    Assert-LegacyPairShortcut $paths[1] $plan.entries[$paths[1]]
    if ($plan.new_link -ine $plan.old_link -and $null -ne (Read-LegacyPairBytes $plan.new_link)) {throw 'pair_shortcut_name_conflict'}
    $nativeExpected=if ($Review.previous) {$Review.previous.links[$plan.native_link].after} else {'absent'}
    if ((Get-LegacyPairHash (Read-LegacyPairBytes $plan.native_link)) -cne $nativeExpected) {throw 'legacy_pair_native_link_changed'}
}

function Invoke-OperatorDesktopLegacyPair {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CandidateDirectory,
        [Parameter(Mandatory)][string]$ExpectedPlanSha256,[string]$CodexHome)
    $review=Get-OperatorDesktopLegacyPairPlan $ProjectRoot $CandidateDirectory $CodexHome
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $review.sha256 -cne $ExpectedPlanSha256) {throw 'legacy_pair_preview_changed'}
    $plan=$review.plan;$project=$plan.project;$root=Join-Path $project '.codex/operator-desktop-pair'
    $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:LegacyUtf8.GetBytes($project.ToLowerInvariant())))
    $mutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$hash));$owns=$false;$lock=$null
    try {
        try {$owns=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$owns=$true}
        if (-not $owns) {throw 'pair_entry_busy'}
        Assert-LegacyPairBoundary $review
        New-LegacyPairDirectory $root
        $lock=[IO.File]::Open((Join-Path $root 'transaction.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $candidate=$review.candidate.record;$stage=$review.candidate.directory;$generation=$candidate.candidate
        $folder=Join-Path $root ('generations/'+$generation)
        if (Test-Path -LiteralPath $folder) {throw 'legacy_pair_generation_consumed'}
        New-LegacyPairDirectory $folder
        $changes=@();$originPath=Join-Path $root 'legacy-origin.json';$paths=Get-LegacyPairPaths
        if (-not $review.previous) {
            $originals=Join-Path $root 'originals';New-LegacyPairDirectory $originals
            [IO.File]::WriteAllBytes((Join-Path $originals 'migration.json'),(Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-migration/journal.json')))
            $evidence=@()
            foreach ($path in $plan.evidence.Keys) {
                $bytes=Read-LegacyPairBytes $path;$sha=Get-LegacyPairHash $bytes
                if ($sha -cne $plan.evidence[$path]) {throw 'legacy_pair_evidence_changed'}
                [IO.File]::WriteAllBytes((Join-Path $originals ($sha+'.bin')),$bytes)
                $evidence+=@{path=$path;sha256=$sha}
            }
            $origin=[ordered]@{schema_version=1;scope='legacy_pair_origin';project=$project;home=$plan.home;
                migration_sha256=$plan.migration_sha256;before_build=$plan.before_build;evidence=$evidence;
                desktop=$paths[0];start=$paths[1];entries=$plan.entries;runtime_ownership='unresolved'}
            $originBytes=ConvertTo-LegacyPairBytes $origin
            $changes+=@{path=$originPath;before=$null;after=$originBytes}
            $originHash=Get-LegacyPairHash $originBytes
            $steps=@()
            $originSummary=@{migration_sha256=$plan.migration_sha256;
                upgrade_receipt_sha256=(Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-upgrade/receipt.json')));
                adoption_receipt_sha256=(Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project '.codex/operator-entry-shortcut-adoption/receipt.json')))}
        } else {$originHash=$review.previous.origin_sha256;$originSummary=$review.previous.origin;$steps=@($review.previous.steps)}
        $files=@{}
        foreach ($name in @('operator_native_entry.ps1','operator_desktop_entry.ps1','restore-codex-official-route.ps1')) {
            $bytes=Read-LegacyPairBytes (Join-Path $stage $name)
            [IO.File]::WriteAllBytes((Join-Path $folder $name),$bytes);$files[$name]=Get-LegacyPairHash $bytes
        }
        $nativeValue=@{schema_version=1;project=$project;home=$plan.home;files=@{
            'operator_desktop_entry.ps1'=$files['operator_desktop_entry.ps1'];'restore-codex-official-route.ps1'=$files['restore-codex-official-route.ps1']}}
        if ($candidate.Contains('isolated_mode')) {$nativeValue.activation_mode='registered_application_v1'}
        $nativeConfig=ConvertTo-LegacyPairBytes $nativeValue
        [IO.File]::WriteAllBytes((Join-Path $folder 'native-entry.json'),$nativeConfig);$files['native-entry.json']=Get-LegacyPairHash $nativeConfig
        $shell=Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
        if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) {throw 'pair_powershell_missing'}
        $nativeBytes=& $script:LegacyPair {param($P,$S,$A,$D) New-OperatorPairShortcut $P $S $A $D '打开官方原生模式；需要切换时先确认正常退出。'} `
            (Join-Path $folder 'native.lnk') $shell ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+(Join-Path $folder 'operator_native_entry.ps1')+'"') $folder
        $changes+=@{path=$plan.native_link;before=(Read-LegacyPairBytes $plan.native_link);after=[byte[]]$nativeBytes}
        $build=@{}
        foreach ($name in $plan.before_build.Keys) {
            $bytes=Read-LegacyPairBytes (Join-Path $stage $name);$build[$name]=Get-LegacyPairHash $bytes
            if ($name -cne 'Codex拓展入口.ico') {$changes+=@{path=(Join-Path $project ('.codex/operator-desktop-entry/'+$name));before=(Read-LegacyPairBytes (Join-Path $project ('.codex/operator-desktop-entry/'+$name)));after=$bytes}}
            elseif ($build[$name] -cne $plan.before_build[$name]) {throw 'legacy_pair_icon_changed'}
        }
        $configBytes=Read-LegacyPairBytes (Join-Path $stage 'desktop-entry.json')
        [IO.File]::WriteAllBytes((Join-Path $folder 'entry-config.after.json'),$configBytes)
        $workflow=$plan.workflow
        $step=@{generation=$generation;before=$plan.before_build;after=$build;workflow=$workflow}
        if ($plan.recovered_entry) {$step.recovered_entry=$plan.recovered_entry}
        if ($workflow.contract -ceq 'direct_profile_picker_v1') {
            $indexBytes=Read-LegacyPairBytes (Join-Path $workflow.path 'direct-entry-plan.json')
            if ((Get-LegacyPairHash $indexBytes) -cne $workflow.entry_plan_sha256) {throw 'legacy_pair_direct_workflow_changed'}
            [IO.File]::WriteAllBytes((Join-Path $folder 'direct-entry-plan.after.json'),$indexBytes)
        } elseif ($workflow.contract -ceq 'operator_isolated_mode_entry_v1') {
            $indexBytes=Read-LegacyPairBytes (Join-Path $workflow.path 'entry.json')
            if ((Get-LegacyPairHash $indexBytes) -cne $workflow.entry_plan_sha256) {throw 'legacy_pair_isolated_workflow_changed'}
            [IO.File]::WriteAllBytes((Join-Path $folder 'isolated-entry.after.json'),$indexBytes)
        }
        $steps+= $step
        $record=@{schema_version=1;scope='legacy_entry_only';project=$project;home=$plan.home;desktop=$plan.desktop;
            phase='installed';runtime_ownership='unresolved';generation=$generation;transaction=$generation;build_date=$candidate.build_date;
            version=$candidate.version;source_sha256=$candidate.source_sha256;build=$build;files=$files;links=@{};
            origin=$originSummary;origin_sha256=$originHash;legacy=@{desktop=$paths[0];start=$paths[1]};steps=$steps}
        $record.links[$plan.native_link]=@{before='absent';after=(Get-LegacyPairHash ([byte[]]$nativeBytes))}
        $record.links[$plan.new_link]=@{before='absent';after=$plan.entries[$paths[0]].sha256}
        $receipt=Join-Path $root 'ownership.json'
        $changes+=@{path=$receipt;before=(Read-LegacyPairBytes $receipt);after=(ConvertTo-LegacyPairBytes $record)}
        $moves=@()
        if ($plan.old_link -ine $plan.new_link) {$moves+=@{source=$plan.old_link;destination=$plan.new_link;
            sha256=$plan.entries[$paths[0]].sha256;identity=$plan.entries[$paths[0]].identity}}
        $boundary={
            Assert-LegacyPairBoundary $review
            if (-not $review.previous) {
                if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root 'originals/migration.json'))) -cne $plan.migration_sha256) {throw 'legacy_pair_backup_changed'}
                foreach ($sha in $plan.evidence.Values) {
                    if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $root ('originals/'+$sha+'.bin')))) -cne $sha) {throw 'legacy_pair_backup_changed'}
                }
            } elseif ((Get-LegacyPairHash (Read-LegacyPairBytes $originPath)) -cne $originHash) {throw 'legacy_pair_origin_invalid'}
            if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $folder 'entry-config.after.json'))) -cne $build['desktop-entry.json']) {throw 'legacy_pair_backup_changed'}
            foreach ($name in $files.Keys) {if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $folder $name))) -cne $files[$name]) {throw 'legacy_pair_helper_changed'}}
            if ($workflow.contract -ceq 'direct_profile_picker_v1') {
                if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $folder 'direct-entry-plan.after.json'))) -cne $workflow.entry_plan_sha256) {throw 'legacy_pair_backup_changed'}
            } elseif ($workflow.contract -ceq 'operator_isolated_mode_entry_v1') {
                if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $folder 'isolated-entry.after.json'))) -cne $workflow.entry_plan_sha256) {throw 'legacy_pair_backup_changed'}
            } elseif ($workflow) {
                if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $workflow.path 'start-codex-with-web.ps1'))) -cne $workflow.startup_script_sha256 -or
                    (Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $workflow.path 'startup-sync-plan.json'))) -cne $workflow.startup_metadata_sha256) {throw 'legacy_pair_workflow_changed'}
            }
        }
        Invoke-OperatorEntryExactTransaction -TransactionRoot (Join-Path $root ('upgrades/'+$generation)) -Changes $changes -Moves $moves -Boundary $boundary
        Get-OperatorDesktopLegacyPairState $project -CheckCurrent | Out-Null
        return @{status='legacy_pair_installed';build_date=$record.build_date;routing_changed=$false;model_requests=0;
            runtime_ownership='unresolved';desktop_acceptance='unverified';legacy_receipts_preserved=$true}
    } finally {if ($lock) {$lock.Dispose()};if ($owns) {$mutex.ReleaseMutex()};$mutex.Dispose()}
}

function Restore-OperatorDesktopLegacyPair {
    param([Parameter(Mandatory)][string]$ProjectRoot)
    $record=Get-OperatorDesktopLegacyPairState $ProjectRoot -CheckCurrent
    if ($record.phase -ceq 'restored') {return @{status='restored';changed=$false}}
    $project=$record.project;$root=Join-Path $project '.codex/operator-desktop-pair'
    $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:LegacyUtf8.GetBytes($project.ToLowerInvariant())))
    $mutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$hash));$owns=$false;$lock=$null
    try {
        try {$owns=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$owns=$true}
        if (-not $owns) {throw 'pair_entry_busy'}
        $lock=[IO.File]::Open((Join-Path $root 'transaction.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $record=Get-OperatorDesktopLegacyPairState $project -CheckCurrent
        $receipt=Join-Path $root 'ownership.json';$receiptBefore=Read-LegacyPairBytes $receipt
        $original=Get-LegacyPairJson (Join-Path $root 'legacy-origin.json')
        $extended=Join-Path $record.desktop ('ChatGPT 拓展模型 '+$record.build_date.Substring(5)+' 入口.lnk')
        $native=Join-Path $record.desktop 'ChatGPT 原生入口.lnk';$transaction=[Guid]::NewGuid().ToString('N')
        $record.phase='restored';$record.transaction=$transaction
        $changes=@(@{path=$native;before=(Read-LegacyPairBytes $native);after=$null},
            @{path=$receipt;before=$receiptBefore;after=(ConvertTo-LegacyPairBytes $record)})
        $moves=@(@{source=$extended;destination=$original.desktop;sha256=$original.entries[$original.desktop].sha256;identity=$original.entries[$original.desktop].identity})
        $configPath=Join-Path $project '.codex/operator-desktop-entry/desktop-entry.json'
        $configAtReview=Get-LegacyPairHash (Read-LegacyPairBytes $configPath)
        $boundary={
            # Caller performs routing/lifecycle preflight. Repeat the exact file
            # boundary under the same entry mutex without changing native config.
            if ((Get-LegacyPairHash (Read-LegacyPairBytes $receipt)) -cne (Get-LegacyPairHash $receiptBefore)) {throw 'legacy_pair_receipt_changed'}
            Assert-LegacyPairShortcut $extended $original.entries[$original.desktop] -Renamed
            Assert-LegacyPairShortcut $original.start $original.entries[$original.start]
            foreach ($name in $record.build.Keys) {
                $expected=if ($name -ceq 'desktop-entry.json') {$configAtReview} else {$record.build[$name]}
                if ((Get-LegacyPairHash (Read-LegacyPairBytes (Join-Path $project ('.codex/operator-desktop-entry/'+$name)))) -cne $expected) {throw 'legacy_pair_build_changed'}
            }
        }
        Invoke-OperatorEntryExactTransaction -TransactionRoot (Join-Path $root ('upgrades/'+$transaction)) -Changes $changes -Moves $moves -Boundary $boundary
        return @{status='restored';changed=$true;native_pin_helpers_retained=$true;fixed_extension_build_retained=$true;routing_changed=$false;runtime_ownership='unresolved'}
    } finally {if ($lock) {$lock.Dispose()};if ($owns) {$mutex.ReleaseMutex()};$mutex.Dispose()}
}

Export-ModuleMember -Function Get-OperatorLegacyPairAttachment,Get-OperatorDesktopLegacyPairState,Get-OperatorDesktopLegacyPairPlan,Invoke-OperatorDesktopLegacyPair,Restore-OperatorDesktopLegacyPair
