#requires -Version 7.0
$ErrorActionPreference = 'Stop'
# Import functions without letting the recovery script's parameters overwrite
# the installer's ProjectRoot, CodexHome or Apply variables through dot-sourcing.
$pairRecoveryModule=New-Module -Name OperatorDesktopPairRecovery -ArgumentList (Join-Path $PSScriptRoot 'restore-codex-official-route.ps1') -ScriptBlock {
    param($Source)
    . $Source -Library
    Export-ModuleMember -Function *
}
Import-Module $pairRecoveryModule -Scope Local -DisableNameChecking
$script:RecoveryUtf8=[Text.UTF8Encoding]::new($false,$true)

function Get-OperatorPairJson([string]$Path) {
    $raw = Read-RecoveryBytes $Path
    if ($null -eq $raw) { return $null }
    return $script:RecoveryUtf8.GetString($raw) | ConvertFrom-Json -AsHashtable
}

function Write-OperatorPairJson([string]$Path, $Value) {
    $raw = $script:RecoveryUtf8.GetBytes(($Value | ConvertTo-Json -Depth 20))
    Write-RecoveryChange @{path=$Path;before=(Read-RecoveryBytes $Path);after=$raw}
}

function New-OperatorPairPrivateDirectory([string]$Path) {
    Assert-RecoveryPlainPath $Path
    [void][IO.Directory]::CreateDirectory($Path)
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,
            [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($Path),$acl)
}

function Get-OperatorPairRoot([string]$ProjectRoot) {
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    Assert-RecoveryPlainPath $project
    if (-not (Test-Path -LiteralPath $project -PathType Container)) { throw 'pair_project_missing' }
    return Join-Path $project '.codex/operator-desktop-pair'
}

function Get-OperatorPairDefaultHome {
    return Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'
}

function Assert-OperatorDesktopPairEnvironment {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CodexHome,
        [string]$DesktopDirectory,[string]$BuildDate)
    $nativeHome=[IO.Path]::GetFullPath($CodexHome).TrimEnd('\')
    $defaultHome=[IO.Path]::GetFullPath((Get-OperatorPairDefaultHome)).TrimEnd('\')
    if ($nativeHome -ine $defaultHome -or ($env:CODEX_HOME -and
        [IO.Path]::GetFullPath($env:CODEX_HOME).TrimEnd('\') -ine $defaultHome)) { throw 'pair_default_home_required' }
    if (-not $DesktopDirectory) { $DesktopDirectory=[Environment]::GetFolderPath('DesktopDirectory') }
    foreach ($path in @($nativeHome,$DesktopDirectory)) {
        Assert-RecoveryPlainPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'pair_directory_missing' }
    }
    if (Test-Path -LiteralPath (Join-Path $nativeHome 'operator-unified-activation')) {
        throw 'pair_activation_requires_separate_review'
    }
    $root=Get-OperatorPairRoot $ProjectRoot
    if (Test-Path -LiteralPath $root) {
        Get-OperatorDesktopPairRestorePlan -ProjectRoot $ProjectRoot | Out-Null
    } else {
        if (-not $BuildDate) { $BuildDate=[DateTime]::Now.ToString('yyyy-MM-dd') }
        if ($BuildDate -cnotmatch '^\d{4}-\d{2}-\d{2}$') { throw 'pair_build_metadata_invalid' }
        if (Test-Path -LiteralPath (Join-Path $DesktopDirectory 'Codex拓展入口.lnk')) { throw 'pair_legacy_migration_required' }
        foreach ($name in @('ChatGPT 原生入口.lnk',('ChatGPT 拓展模型 '+$BuildDate.Substring(5)+' 入口.lnk'))) {
            if (Test-Path -LiteralPath (Join-Path $DesktopDirectory $name)) { throw 'pair_shortcut_name_conflict' }
        }
    }
}

function Get-OperatorPairBuild([string]$ProjectRoot) {
    $entry = Get-RecoveryEntryPlan $ProjectRoot
    if ($entry.state -notin @('native','reviewed_startup')) { throw 'pair_entry_build_required' }
    $bundle = Join-Path $ProjectRoot '.codex/operator-desktop-entry'
    $result = @{}
    foreach ($name in @('Codex拓展入口.exe','operator_desktop_entry.ps1','launcher-manifest.json')) {
        $result[$name] = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $bundle $name) 16777216)
    }
    return $result
}

function Assert-OperatorPairRecord([string]$ProjectRoot, $Record) {
    $root = Get-OperatorPairRoot $ProjectRoot
    if (-not $Record -or $Record.schema_version -ne 1 -or $Record.project -ine $ProjectRoot -or
        $Record.phase -notin @('installed','restored') -or $Record.generation -cnotmatch '^[a-f0-9]{32}$' -or
        $Record.files -isnot [Collections.IDictionary] -or $Record.links -isnot [Collections.IDictionary] -or
        $Record.links.Count -ne 2 -or $Record.build_date -cnotmatch '^\d{4}-\d{2}-\d{2}$' -or
        $Record.source_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        -not [IO.Path]::IsPathFullyQualified($Record.desktop) -or -not [IO.Path]::IsPathFullyQualified($Record.home)) {
        throw 'pair_ownership_invalid'
    }
    $expected = @((Join-Path $Record.desktop 'ChatGPT 原生入口.lnk'),
        (Join-Path $Record.desktop ('ChatGPT 拓展模型 '+$Record.build_date.Substring(5)+' 入口.lnk')))
    foreach ($path in $expected) {
        if (-not $Record.links.Contains($path) -or $Record.links[$path].before -cne 'absent' -or
            $Record.links[$path].after -cnotmatch '^[a-f0-9]{64}$') { throw 'pair_ownership_invalid' }
        $actual = Get-RecoveryHash (Read-RecoveryBytes $path)
        $wanted = if ($Record.phase -eq 'installed') { $Record.links[$path].after } else { 'absent' }
        if ($actual -cne $wanted) { throw 'pair_shortcut_changed' }
    }
    $generation = Join-Path $root ('generations/'+$Record.generation)
    if (@($Record.files.Keys).Count -ne 4) { throw 'pair_ownership_invalid' }
    foreach ($name in @('operator_native_entry.ps1','operator_desktop_entry.ps1','restore-codex-official-route.ps1','native-entry.json')) {
        if ($Record.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-RecoveryHash (Read-RecoveryBytes (Join-Path $generation $name))) -cne $Record.files[$name]) {
            throw 'pair_native_files_changed'
        }
    }
}

function Get-OperatorDesktopPairRestorePlan {
    param([Parameter(Mandatory)][string]$ProjectRoot)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $root = Get-OperatorPairRoot $project
    if (Test-Path -LiteralPath (Join-Path $root 'pending.json')) { throw 'pair_pending_requires_review' }
    $upgrades=Join-Path $root 'upgrades'
    Assert-RecoveryPlainPath $upgrades
    if (Test-Path -LiteralPath $upgrades) {
        foreach ($folder in @(Get-ChildItem -LiteralPath $upgrades -Directory)) {
            Assert-RecoveryPlainPath $folder.FullName
            if ((Test-Path -LiteralPath (Join-Path $folder.FullName 'pending.json')) -or
                -not (Test-Path -LiteralPath (Join-Path $folder.FullName 'completed.json') -PathType Leaf) -or
                -not (Test-Path -LiteralPath (Join-Path $folder.FullName 'committed-intent.json') -PathType Leaf)) {throw 'pair_upgrade_pending_requires_review'}
        }
    }
    $record = Get-OperatorPairJson (Join-Path $root 'ownership.json')
    if (-not $record) {
        if (Test-Path -LiteralPath $root) { throw 'pair_ownership_missing' }
        return @{status='not_installed';configuration_changed=$false}
    }
    if ($record.scope -ceq 'legacy_entry_only' -or (Test-Path -LiteralPath (Join-Path $root 'legacy-origin.json'))) {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -DisableNameChecking
        $record=Get-OperatorDesktopLegacyPairState -ProjectRoot $project -CheckCurrent
        return @{status=$(if ($record.phase -ceq 'installed') {'ready'} else {'restored'});record=$record;
            receipt_sha256=(Get-RecoveryHash (Read-RecoveryBytes (Join-Path $root 'ownership.json')));configuration_changed=$false}
    }
    Assert-OperatorPairRecord $project $record
    if ($record.phase -eq 'installed') {
        $build = Get-OperatorPairBuild $project
        if ($record.build.Count -ne $build.Count -or @($build.Keys | Where-Object {$record.build[$_] -cne $build[$_]}).Count) {
            throw 'pair_extension_build_changed'
        }
    }
    return @{status=$(if ($record.phase -eq 'installed') {'ready'} else {'restored'});
        record=$record;receipt_sha256=(Get-RecoveryHash (Read-RecoveryBytes (Join-Path $root 'ownership.json')));
        configuration_changed=$false}
}

function Get-OperatorDesktopPairPlan {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CodexHome,
        [Parameter(Mandatory)][string]$BuildDate,[Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$SourceDigest,[string]$DesktopDirectory)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $nativeHome = [IO.Path]::GetFullPath($CodexHome).TrimEnd('\')
    if (-not $DesktopDirectory) { $DesktopDirectory=[Environment]::GetFolderPath('DesktopDirectory') }
    $desktop = [IO.Path]::GetFullPath($DesktopDirectory).TrimEnd('\')
    Assert-OperatorDesktopPairEnvironment -ProjectRoot $project -CodexHome $nativeHome -DesktopDirectory $desktop -BuildDate $BuildDate
    $parsedDate = [DateTime]::MinValue
    if (-not [DateTime]::TryParseExact($BuildDate,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,[ref]$parsedDate) -or $SourceDigest -cnotmatch '^[a-f0-9]{64}$' -or
        $Version -cnotmatch '^[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}$') { throw 'pair_build_metadata_invalid' }
    $owner = Get-OperatorPairJson (Join-Path $project '.codex/operator-installation/ownership.json')
    if (-not $owner -or $owner.schema_version -ne 1 -or $owner.project -ine $project -or
        $owner.entries -isnot [Collections.IDictionary]) { throw 'pair_legacy_migration_required' }
    $legacyLink=Join-Path $desktop 'Codex拓展入口.lnk'
    if ($null -ne (Read-RecoveryBytes $legacyLink) -or $owner.entries.Contains($legacyLink)) {
        throw 'pair_legacy_migration_required'
    }
    $build = Get-OperatorPairBuild $project
    $buildMetadata=Get-OperatorPairJson (Join-Path $project '.codex/operator-desktop-entry/launcher-manifest.json')
    if ($buildMetadata.build_date -cne $BuildDate -or $buildMetadata.product_version -cne $Version -or
        $buildMetadata.source_sha256 -cne $SourceDigest) { throw 'pair_build_metadata_mismatch' }
    if (Test-Path -LiteralPath (Join-Path $nativeHome 'operator-unified-activation')) {
        throw 'pair_activation_requires_separate_review'
    }
    $existing = Get-OperatorDesktopPairRestorePlan $project
    $links = @((Join-Path $desktop 'ChatGPT 原生入口.lnk'),
        (Join-Path $desktop ('ChatGPT 拓展模型 '+$BuildDate.Substring(5)+' 入口.lnk')))
    $sources = @{}
    foreach ($name in @('operator_native_entry.ps1','operator_desktop_entry.ps1','restore-codex-official-route.ps1')) {
        $sources[$name] = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $PSScriptRoot $name))
        if ($sources[$name] -eq 'absent') { throw 'pair_source_missing' }
    }
    $status='install_available'
    if ($existing.status -eq 'ready') {
        $old=$existing.record
        if ($old.desktop -ine $desktop -or $old.home -ine $nativeHome) { throw 'pair_target_changed' }
        if (@($sources.Keys | Where-Object {$old.files[$_] -cne $sources[$_]}).Count) { throw 'pair_helper_upgrade_requires_review' }
        if ($old.build_date -cne $BuildDate -or $old.version -cne $Version -or $old.source_sha256 -cne $SourceDigest) {
            throw 'pair_build_upgrade_requires_review'
        }
        $status='already_installed'
    }
    foreach ($path in $links) {
        $owned = $existing.status -eq 'ready' -and $existing.record.links.Contains($path)
        if (-not $owned -and $null -ne (Read-RecoveryBytes $path)) { throw 'pair_shortcut_name_conflict' }
    }
    return @{status=$status;project=$project;home=$nativeHome;desktop=$desktop;build_date=$BuildDate;
        version=$Version;source_sha256=$SourceDigest;build=$build;sources=$sources;links=$links;
        owner_sha256=(Get-RecoveryHash (Read-RecoveryBytes (Join-Path $project '.codex/operator-installation/ownership.json')));
        previous=$existing;configuration_changed=$false}
}

function Assert-OperatorPairInstallBoundary($Plan) {
    if (Test-Path -LiteralPath (Join-Path $Plan.home 'operator-unified-activation')) { throw 'pair_activation_requires_separate_review' }
    if ((Get-RecoveryHash (Read-RecoveryBytes (Join-Path $Plan.project '.codex/operator-installation/ownership.json'))) -cne $Plan.owner_sha256) {
        throw 'pair_installation_owner_changed'
    }
    $root=Get-OperatorPairRoot $Plan.project
    $expected=if ($Plan.previous.receipt_sha256) {$Plan.previous.receipt_sha256} else {'absent'}
    if ((Get-RecoveryHash (Read-RecoveryBytes (Join-Path $root 'ownership.json'))) -cne $expected) { throw 'pair_receipt_changed' }
    $build=Get-OperatorPairBuild $Plan.project
    if (@($build.Keys | Where-Object {$build[$_] -cne $Plan.build[$_]}).Count) { throw 'pair_extension_build_changed' }
    foreach ($path in @($Plan.home,$Plan.desktop)) {
        Assert-RecoveryPlainPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'pair_directory_missing' }
    }
}

function New-OperatorPairShortcut([string]$Path,[string]$Target,[string]$Arguments,[string]$WorkingDirectory,[string]$Description) {
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut($Path)
    $link.TargetPath=$Target;$link.Arguments=$Arguments;$link.WorkingDirectory=$WorkingDirectory
    $link.WindowStyle=7;$link.Description=$Description;$link.Save()
    $read=$shell.CreateShortcut($Path)
    if ($read.TargetPath -ine $Target -or $read.Arguments -cne $Arguments -or $read.WorkingDirectory -ine $WorkingDirectory) { throw 'pair_shortcut_verification_failed' }
    return ,(Read-RecoveryBytes $Path)
}

function Invoke-OperatorPairTransaction([string]$Root,$AfterRecord,$Changes) {
    if (Test-Path -LiteralPath (Join-Path $Root 'pending.json')) { throw 'pair_pending_requires_review' }
    $transaction=Join-Path $Root ('transactions/'+[Guid]::NewGuid().ToString('N'))
    New-OperatorPairPrivateDirectory $transaction
    $receipt=Join-Path $Root 'ownership.json'
    $receiptBefore=Read-RecoveryBytes $receipt
    $rows=@()
    foreach ($change in $Changes) {
        if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -cne (Get-RecoveryHash $change.before)) { throw 'pair_shortcut_changed' }
        $index=$rows.Count
        if ($null -ne $change.before) { [IO.File]::WriteAllBytes((Join-Path $transaction "$index.before"),$change.before) }
        if ($null -ne $change.after) { [IO.File]::WriteAllBytes((Join-Path $transaction "$index.after"),$change.after) }
        $rows+=@{path=$change.path;before=(Get-RecoveryHash $change.before);after=(Get-RecoveryHash $change.after)}
    }
    if ($null -ne $receiptBefore) { [IO.File]::WriteAllBytes((Join-Path $transaction 'ownership.before.json'),$receiptBefore) }
    $intent=@{schema_version=1;transaction=$transaction;changes=$rows;receipt_before=(Get-RecoveryHash $receiptBefore)}
    Write-OperatorPairJson (Join-Path $transaction 'intent.json') $intent
    Write-OperatorPairJson (Join-Path $Root 'pending.json') $intent
    try {
        foreach ($change in $Changes) {
            if ($null -eq $change.after) {
                if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -cne (Get-RecoveryHash $change.before)) { throw 'pair_shortcut_changed' }
                [IO.File]::Delete($change.path)
            } else { Write-RecoveryChange $change }
        }
        if ((Get-RecoveryHash (Read-RecoveryBytes $receipt)) -cne (Get-RecoveryHash $receiptBefore)) { throw 'pair_receipt_changed' }
        Write-OperatorPairJson $receipt $AfterRecord
        Write-OperatorPairJson (Join-Path $transaction 'completed.json') @{status='completed';receipt_sha256=(Get-RecoveryHash (Read-RecoveryBytes $receipt))}
        [IO.File]::Move((Join-Path $Root 'pending.json'),(Join-Path $transaction 'committed-intent.json'))
    } catch {
        # Roll back only exact bytes this transaction wrote. Later user edits
        # remain untouched. The retained pending record requires explicit review.
        for ($i=$Changes.Count-1;$i -ge 0;$i--) {
            $change=$Changes[$i]
            if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -ceq (Get-RecoveryHash $change.after)) {
                if ($null -eq $change.before) { [IO.File]::Delete($change.path) }
                else { Write-RecoveryChange @{path=$change.path;before=$change.after;after=$change.before} }
            }
        }
        throw
    }
}

function Install-OperatorDesktopPair {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CodexHome,
        [Parameter(Mandatory)][string]$BuildDate,[Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$SourceDigest,[string]$DesktopDirectory)
    $arguments=@{ProjectRoot=$ProjectRoot;CodexHome=$CodexHome;BuildDate=$BuildDate;Version=$Version;SourceDigest=$SourceDigest;DesktopDirectory=$DesktopDirectory}
    $plan=Get-OperatorDesktopPairPlan @arguments
    if ($plan.status -eq 'already_installed') { return @{status='ready';changed=$false;build_date=$BuildDate;routing_changed=$false} }
    $projectHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($plan.project.ToLowerInvariant())))
    $entryMutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$projectHash))
    $ownsEntry=$false
    try { $ownsEntry=$entryMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsEntry=$true }
    if (-not $ownsEntry) {$entryMutex.Dispose();throw 'pair_entry_busy'}
    $lock=$null
    try {
    $root=Get-OperatorPairRoot $plan.project
    Assert-OperatorPairInstallBoundary $plan
    New-OperatorPairPrivateDirectory $root
    $lock=[IO.File]::Open((Join-Path $root 'transaction.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        # A brand-new root contains only its lock until the first receipt exists.
        $first=$plan.previous.status -eq 'not_installed'
        if (-not $first) { $plan=Get-OperatorDesktopPairPlan @arguments }
        $changes=@()
        if ($plan.status -eq 'install_available') {
            $generation=[Guid]::NewGuid().ToString('N')
            $folder=Join-Path $root ('generations/'+$generation)
            New-OperatorPairPrivateDirectory $folder
            $files=@{}
            foreach ($name in $plan.sources.Keys) {
                $bytes=Read-RecoveryBytes (Join-Path $PSScriptRoot $name)
                if ((Get-RecoveryHash $bytes) -cne $plan.sources[$name]) { throw 'pair_source_changed' }
                [IO.File]::WriteAllBytes((Join-Path $folder $name),$bytes)
                $files[$name]=Get-RecoveryHash $bytes
            }
            $nativeConfig=@{schema_version=1;project=$plan.project;home=$plan.home;files=@{
                'operator_desktop_entry.ps1'=$files['operator_desktop_entry.ps1'];
                'restore-codex-official-route.ps1'=$files['restore-codex-official-route.ps1']}}
            Write-OperatorPairJson (Join-Path $folder 'native-entry.json') $nativeConfig
            $files['native-entry.json']=Get-RecoveryHash (Read-RecoveryBytes (Join-Path $folder 'native-entry.json'))
            $shell=Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
            if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) { throw 'pair_powershell_missing' }
            $nativeScript=Join-Path $folder 'operator_native_entry.ps1'
            $nativeBytes=New-OperatorPairShortcut (Join-Path $folder 'native.lnk') $shell ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+$nativeScript+'"') $folder '打开官方原生模式；需要切换时先确认正常退出。'
            $bundle=Join-Path $plan.project '.codex/operator-desktop-entry'
            $extensionBytes=New-OperatorPairShortcut (Join-Path $folder 'extension.lnk') (Join-Path $bundle 'Codex拓展入口.exe') '' $bundle '使用已配置的拓展模型；不会自动解除官方直连保护。'
            $changes+=@{path=$plan.links[0];before=$null;after=$nativeBytes}
            $changes+=@{path=$plan.links[1];before=$null;after=$extensionBytes}
            $record=@{schema_version=1;project=$plan.project;home=$plan.home;desktop=$plan.desktop;phase='installed';
                generation=$generation;build_date=$BuildDate;version=$Version;source_sha256=$SourceDigest;build=$plan.build;files=$files;links=@{}}
            foreach ($change in $changes) { $record.links[$change.path]=@{before='absent';after=(Get-RecoveryHash $change.after)} }
        }
        Assert-OperatorPairInstallBoundary $plan
        Invoke-OperatorPairTransaction $root $record $changes
        return @{status='ready';changed=$true;build_date=$BuildDate;routing_changed=$false;desktop_acceptance='unverified'}
    } finally { if ($lock) {$lock.Dispose()};$entryMutex.ReleaseMutex();$entryMutex.Dispose() }
}

function Restore-OperatorDesktopPair {
    param([Parameter(Mandatory)][string]$ProjectRoot)
    $plan=Get-OperatorDesktopPairRestorePlan $ProjectRoot
    if ($plan.status -in @('not_installed','restored')) { return @{status=$plan.status;changed=$false} }
    if ($plan.record.scope -ceq 'legacy_entry_only') {
        Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair_legacy.psm1') -DisableNameChecking
        return Restore-OperatorDesktopLegacyPair -ProjectRoot $ProjectRoot
    }
    $root=Get-OperatorPairRoot $plan.record.project
    $lock=[IO.File]::Open((Join-Path $root 'transaction.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $plan=Get-OperatorDesktopPairRestorePlan $ProjectRoot
        $changes=@($plan.record.links.Keys | ForEach-Object {@{path=$_;before=(Read-RecoveryBytes $_);after=$null}})
        $record=$plan.record;$record.phase='restored'
        Invoke-OperatorPairTransaction $root $record $changes
        return @{status='restored';changed=$true;native_pin_helpers_retained=$true;routing_changed=$false}
    } finally { $lock.Dispose() }
}

Export-ModuleMember -Function Assert-OperatorDesktopPairEnvironment,Get-OperatorDesktopPairPlan,Get-OperatorDesktopPairRestorePlan,Install-OperatorDesktopPair,Restore-OperatorDesktopPair
