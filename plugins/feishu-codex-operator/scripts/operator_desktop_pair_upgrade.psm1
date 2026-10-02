#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$script:UpgradeUtf8=[Text.UTF8Encoding]::new($false,$true)
$script:PairModule=Import-Module (Join-Path $PSScriptRoot 'operator_desktop_pair.psm1') -PassThru -DisableNameChecking

function Read-OperatorUpgradeBytes([string]$Path,[int]$Limit=16777216) {
    return ,(& $script:PairModule {param($P,$N) Read-RecoveryBytes $P $N} $Path $Limit)
}
function Get-OperatorUpgradeHash([AllowNull()][byte[]]$Bytes) {
    if ($null -eq $Bytes) {return 'absent'}
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}
function Get-OperatorUpgradeJson([string]$Path) {
    $bytes=Read-OperatorUpgradeBytes $Path 1048576
    if ($null -eq $bytes) {throw 'pair_upgrade_record_missing'}
    return $script:UpgradeUtf8.GetString($bytes)|ConvertFrom-Json -AsHashtable
}
function ConvertTo-OperatorUpgradeBytes($Value) {
    return ,$script:UpgradeUtf8.GetBytes((ConvertTo-Json -InputObject $Value -Depth 30 -Compress))
}
function ConvertTo-OperatorPairPreviewValue($Value) {
    # Only new preview plans use this representation. Existing journal, receipt
    # and candidate bytes retain their original serialization and hash rules.
    if ($Value -is [Collections.IDictionary]) {
        $sourceKeys=@($Value.get_Keys())
        foreach ($key in $sourceKeys) {if ($key -isnot [string]) {throw 'pair_preview_key_invalid'}}
        [string[]]$keys=$sourceKeys
        [Array]::Sort($keys,[StringComparer]::Ordinal)
        $ordered=[Collections.Specialized.OrderedDictionary]::new([StringComparer]::Ordinal)
        foreach ($key in $keys) {$ordered.Add($key,(ConvertTo-OperatorPairPreviewValue $Value[$key]))}
        return ,$ordered
    }
    if ($Value -is [Collections.IList]) {
        $items=[object[]]::new($Value.Count)
        for ($index=0;$index -lt $Value.Count;$index++) {$items[$index]=ConvertTo-OperatorPairPreviewValue $Value[$index]}
        return ,$items
    }
    return $Value
}
function Get-OperatorPairPreviewHash($Plan) {
    $ordered=ConvertTo-OperatorPairPreviewValue $Plan
    return Get-OperatorUpgradeHash ($script:UpgradeUtf8.GetBytes(
        (ConvertTo-Json -InputObject $ordered -Depth 40 -Compress)))
}
function Assert-OperatorUpgradePath([string]$Path) {
    & $script:PairModule {param($P) Assert-RecoveryPlainPath $P} $Path
}
function New-OperatorUpgradeDirectory([string]$Path) {
    & $script:PairModule {param($P) New-OperatorPairPrivateDirectory $P} $Path
}
function Write-OperatorUpgradeChange($Change) {
    Assert-OperatorUpgradePath $Change.path
    if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $Change.path)) -cne (Get-OperatorUpgradeHash $Change.before)) {
        throw 'pair_upgrade_file_changed'
    }
    # Retain the complete transaction and its guards, but do not replace an
    # unchanged file. A running launcher can legitimately hold its old bytes.
    if ((Get-OperatorUpgradeHash $Change.before) -ceq (Get-OperatorUpgradeHash $Change.after)) {return}
    if ($null -eq $Change.after) {[IO.File]::Delete($Change.path);return}
    $temp=Join-Path (Split-Path -Parent $Change.path) ('.operator-upgrade-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    try {
        $stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {$stream.Write($Change.after,0,$Change.after.Length);$stream.Flush($true)} finally {$stream.Dispose()}
        if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $Change.path)) -cne (Get-OperatorUpgradeHash $Change.before)) {
            throw 'pair_upgrade_file_changed'
        }
        if ($null -eq $Change.before) {[IO.File]::Move($temp,$Change.path)}
        else {[IO.File]::Replace($temp,$Change.path,[NullString]::Value)}
        if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $Change.path)) -cne (Get-OperatorUpgradeHash $Change.after)) {
            throw 'pair_upgrade_write_failed'
        }
    } finally {if (Test-Path -LiteralPath $temp) {[IO.File]::Delete($temp)}}
}

function Get-OperatorEntryMoveIdentity([string]$Path) {
    Assert-OperatorUpgradePath $Path
    if (-not ('OperatorEntryUpgradeFileIdentity' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OperatorEntryUpgradeFileIdentity {
    [StructLayout(LayoutKind.Sequential)]
    private struct Information {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime, AccessTime, WriteTime;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Information info);
    public static string Read(string path) {
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
            Information info;
            if (!GetFileInformationByHandle(file.SafeFileHandle, out info) || info.Links != 1)
                throw new IOException("Move identity unavailable.");
            ulong index = ((ulong)info.IndexHigh << 32) | info.IndexLow;
            return info.Volume.ToString("x8") + ":" + index.ToString("x16");
        }
    }
}
'@
    }
    return [OperatorEntryUpgradeFileIdentity]::Read($Path)
}

function Assert-OperatorEntryMove($Move,[switch]$Reversed) {
    $source=if ($Reversed) {$Move.destination} else {$Move.source}
    $destination=if ($Reversed) {$Move.source} else {$Move.destination}
    foreach ($path in @($source,$destination)) {Assert-OperatorUpgradePath $path}
    if (Test-Path -LiteralPath $destination) {throw 'entry_transaction_move_target_changed'}
    if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $source)) -cne $Move.sha256 -or
        (Get-OperatorEntryMoveIdentity $source) -cne $Move.identity) {throw 'entry_transaction_move_source_changed'}
}

function Invoke-OperatorEntryExactTransaction {
    param([Parameter(Mandatory)][string]$TransactionRoot,[AllowEmptyCollection()][object[]]$Changes=@(),
        [Parameter(Mandatory)][scriptblock]$Boundary,[AllowEmptyCollection()][object[]]$Moves=@())
    # Policy and mutex ownership belong to the caller. This primitive publishes
    # only its explicitly supplied exact byte changes; uncertainty is terminal.
    Assert-OperatorUpgradePath $TransactionRoot
    if (-not [IO.Path]::IsPathFullyQualified($TransactionRoot)) {throw 'entry_transaction_scope_invalid'}
    if (Test-Path -LiteralPath $TransactionRoot) {throw 'entry_transaction_already_exists'}
    $allPaths=@($Changes.path)+@($Moves.source)+@($Moves.destination)
    $allPaths=@($allPaths|Where-Object {$_})
    if ((-not $Changes.Count -and -not $Moves.Count) -or
        @($allPaths|ForEach-Object {[IO.Path]::GetFullPath($_).ToLowerInvariant()}|Sort-Object -Unique).Count -ne $allPaths.Count) {
        throw 'entry_transaction_scope_invalid'
    }
    foreach ($move in $Moves) {
        if (-not [IO.Path]::IsPathFullyQualified($move.source) -or -not [IO.Path]::IsPathFullyQualified($move.destination) -or
            [IO.Path]::GetFullPath((Split-Path -Parent $move.source)) -ine [IO.Path]::GetFullPath((Split-Path -Parent $move.destination)) -or
            $move.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $move.identity -cnotmatch '^[a-f0-9]{8}:[a-f0-9]{16}$') {
            throw 'entry_transaction_move_scope_invalid'
        }
        Assert-OperatorEntryMove $move
    }
    foreach ($change in $Changes) {
        if (-not [IO.Path]::IsPathFullyQualified($change.path) -or
            ($null -ne $change.before -and $change.before -isnot [byte[]]) -or
            ($null -ne $change.after -and $change.after -isnot [byte[]]) -or
            $change.before.Length -gt 16777216 -or $change.after.Length -gt 16777216) {throw 'entry_transaction_scope_invalid'}
        Assert-OperatorUpgradePath $change.path
        if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $change.path)) -cne (Get-OperatorUpgradeHash $change.before)) {
            throw 'pair_upgrade_file_changed'
        }
    }
    & $Boundary
    New-OperatorUpgradeDirectory $TransactionRoot
    $rows=@()
    foreach ($change in $Changes) {
        $index=$rows.Count
        foreach ($side in @('before','after')) {
            if ($null -ne $change[$side]) {
                $saved=Join-Path $TransactionRoot ($index.ToString()+'.'+$side)
                [IO.File]::WriteAllBytes($saved,$change[$side])
                if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $saved)) -cne (Get-OperatorUpgradeHash $change[$side])) {
                    throw 'entry_transaction_backup_failed'
                }
            }
        }
        $rows+=@{path=$change.path;before=(Get-OperatorUpgradeHash $change.before);after=(Get-OperatorUpgradeHash $change.after)}
    }
    for ($index=0;$index -lt $Moves.Count;$index++) {
        $bytes=Read-OperatorUpgradeBytes $Moves[$index].source
        [IO.File]::WriteAllBytes((Join-Path $TransactionRoot ('move-'+$index+'.before')),$bytes)
        if ((Get-OperatorUpgradeHash $bytes) -cne $Moves[$index].sha256) {throw 'entry_transaction_backup_failed'}
    }
    $intent=ConvertTo-OperatorUpgradeBytes @{schema_version=1;phase='may_have_written';changes=$rows;moves=$Moves}
    [IO.File]::WriteAllBytes((Join-Path $TransactionRoot 'pending.json'),$intent)
    try {
        & $Boundary
        foreach ($move in $Moves) {
            Assert-OperatorEntryMove $move
            [IO.File]::Move($move.source,$move.destination)
            Assert-OperatorEntryMove $move -Reversed
        }
        foreach ($change in $Changes) {Write-OperatorUpgradeChange $change}
        [IO.File]::WriteAllBytes((Join-Path $TransactionRoot 'completed.json'),
            (ConvertTo-OperatorUpgradeBytes @{schema_version=1;phase='committed';intent_sha256=(Get-OperatorUpgradeHash $intent)}))
        [IO.File]::Move((Join-Path $TransactionRoot 'pending.json'),(Join-Path $TransactionRoot 'committed-intent.json'))
    } catch {
        $failure=$_
        for ($i=$Changes.Count-1;$i -ge 0;$i--) {
            $change=$Changes[$i]
            try {
                if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $change.path)) -ceq (Get-OperatorUpgradeHash $change.after)) {
                    Write-OperatorUpgradeChange @{path=$change.path;before=$change.after;after=$change.before}
                }
            } catch { # Keep both originals and the pending intent for explicit review.
            }
        }
        for ($i=$Moves.Count-1;$i -ge 0;$i--) {
            try {
                Assert-OperatorEntryMove $Moves[$i] -Reversed
                [IO.File]::Move($Moves[$i].destination,$Moves[$i].source)
                Assert-OperatorEntryMove $Moves[$i]
            } catch { # A later edit or uncertain identity remains untouched.
            }
        }
        throw $failure
    }
}

function Get-OperatorUpgradeToday {return [DateTime]::Now.ToString('yyyy-MM-dd')}
function Get-OperatorUpgradeCompilerHash([string]$Path) {
    # Windows servicing may hard-link the system compiler. It is a read-only
    # dependency, never an owned mutable file subject to recovery writes.
    Assert-OperatorUpgradePath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -gt 16777216) {
        throw 'pair_candidate_compiler_missing'
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Get-OperatorUpgradeSource {
    param([switch]$Direct,[switch]$Isolated)
    $result=[ordered]@{}
    $names=@('operator_desktop_entry.cs','operator_desktop_entry.ps1','operator_native_entry.ps1',
            'restore-codex-official-route.ps1','operator_desktop_pair_upgrade.psm1','../.codex-plugin/plugin.json')
    if ($Direct -or $Isolated) {$names+=@('operator_direct_entry.py','operator_direct_profile.py','operator_native_models.py','operator_core/windows_config_transaction.py')}
    if ($Isolated) {$names+=@('operator_mode_entry.py','operator_mode_entry.ps1','operator_mode_native.cs','operator_mode_host.cs','operator_mode_picker.cs','operator_mode_onboarding.py')}
    foreach ($name in $names) {
        $bytes=Read-OperatorUpgradeBytes (Join-Path $PSScriptRoot $name)
        if ($null -eq $bytes) {throw 'pair_upgrade_source_missing'}
        $result[$name]=Get-OperatorUpgradeHash $bytes
    }
    return $result
}

function Assert-OperatorDirectEntryUpgradeReady([string]$Project,[string]$HomePath,$Picker) {
    $state=Join-Path $HomePath 'operator-direct-entry'
    Assert-OperatorUpgradePath $state
    if (-not (Test-Path -LiteralPath $state)) {return}
    if (-not $Picker -or $Picker.home -ine $HomePath -or $Picker.project -ine $Project -or
        (Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $Picker.python 16777216)) -cne $Picker.python_sha256) {throw 'direct_cycle_maintenance_requires_bound_python'}
    $controller=Join-Path $Project 'plugins/feishu-codex-operator/scripts/operator_direct_entry.py'
    $output=@(& $Picker.python -E -s -B $controller maintenance-status --home $HomePath 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or ([string]$output[0]).Length -gt 65536) {throw 'direct_cycle_maintenance_requires_review'}
    $checked=([string]$output[0])|ConvertFrom-Json -AsHashtable
    if ($checked.status -cne 'maintenance_ready' -or $checked.configuration_changed -ne $false -or
        $checked.model_requests -ne 0 -or $checked.desktop_launch -ne $false) {throw 'direct_cycle_maintenance_requires_review'}
}

function New-OperatorEntryBuildCandidate {
    param([Parameter(Mandatory)][string]$ProjectRoot,[string]$StageDirectory,[string]$BuildDate,[string]$DirectPickerPath,[string]$IsolatedModePath)
    if ($DirectPickerPath -and $IsolatedModePath) {throw 'pair_candidate_mode_ambiguous'}
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    Assert-OperatorUpgradePath $project
    if (-not (Test-Path -LiteralPath $project -PathType Container)) {throw 'pair_project_missing'}
    if (-not $BuildDate) {$BuildDate=Get-OperatorUpgradeToday}
    if ($BuildDate -cne (Get-OperatorUpgradeToday)) {throw 'pair_candidate_build_date_must_be_today'}
    $parent=Join-Path $project '.codex/operator-entry-build-candidates'
    if (-not $StageDirectory) {$StageDirectory=Join-Path $parent ([Guid]::NewGuid().ToString('N'))}
    $stage=[IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
    if ((Split-Path -Parent $stage) -ine $parent -or (Split-Path -Leaf $stage) -cnotmatch '^[a-f0-9]{32}$') {
        throw 'pair_candidate_scope_invalid'
    }
    Assert-OperatorUpgradePath $stage
    if (Test-Path -LiteralPath $stage) {throw 'pair_candidate_already_exists'}
    $bundle=Join-Path $project '.codex/operator-desktop-entry'
    if (Test-Path -LiteralPath (Join-Path $bundle 'native-only')) {throw 'pair_native_only_requires_review'}
    & $script:PairModule {param($P) Get-RecoveryEntryPlan $P|Out-Null} $project
    $before=Read-OperatorUpgradeBytes (Join-Path $bundle 'desktop-entry.json') 16384
    $config=$script:UpgradeUtf8.GetString($before)|ConvertFrom-Json -AsHashtable
    $picker=$null
    $modeEntry=$null
    if ($DirectPickerPath) {
        . (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1') -Library
        $pickerSha=Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $DirectPickerPath 65536)
        $pickerRaw=Get-OperatorUpgradeJson $DirectPickerPath
        $picker=Get-OperatorDirectPicker $project $pickerRaw.home $DirectPickerPath $pickerSha
    }
    if ($IsolatedModePath) {
        . (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1') -Library
        $modeSha=Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $IsolatedModePath)
        $modeRaw=Get-OperatorUpgradeJson $IsolatedModePath
        $modeEntry=Get-OperatorIsolatedModeEntry $project $modeRaw.native_home $IsolatedModePath $modeSha
        Test-OperatorIsolatedModeEntry $modeEntry
    }
    $sources=Get-OperatorUpgradeSource -Direct:($null -ne $picker) -Isolated:($null -ne $modeEntry)
    $plugin=Get-OperatorUpgradeJson (Join-Path $PSScriptRoot '../.codex-plugin/plugin.json')
    if ($plugin.version -cnotmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {throw 'pair_candidate_version_invalid'}
    $compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {throw 'pair_candidate_compiler_missing'}
    $compilerHash=Get-OperatorUpgradeCompilerHash $compiler
    New-OperatorUpgradeDirectory $stage
    $files=[ordered]@{}
    foreach ($name in @('operator_desktop_entry.ps1','operator_native_entry.ps1','restore-codex-official-route.ps1')) {
        $bytes=Read-OperatorUpgradeBytes (Join-Path $PSScriptRoot $name)
        [IO.File]::WriteAllBytes((Join-Path $stage $name),$bytes)
        $files[$name]=Get-OperatorUpgradeHash $bytes
    }
    $icon=Read-OperatorUpgradeBytes (Join-Path $bundle 'Codex拓展入口.ico') 1048576
    $arguments=@('/nologo','/target:winexe','/optimize+','/platform:anycpu','/reference:System.Windows.Forms.dll')
    if ($null -ne $icon) {
        [IO.File]::WriteAllBytes((Join-Path $stage 'Codex拓展入口.ico'),$icon)
        $files['Codex拓展入口.ico']=Get-OperatorUpgradeHash $icon
        $arguments+=('/win32icon:'+(Join-Path $stage 'Codex拓展入口.ico'))
    }
    $arguments+=('/out:'+(Join-Path $stage 'Codex拓展入口.exe'))
    $arguments+=(Join-Path $PSScriptRoot 'operator_desktop_entry.cs')
    $compilerOutput=@(& $compiler @arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {throw 'pair_candidate_compile_failed'}
    $files['Codex拓展入口.exe']=Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage 'Codex拓展入口.exe'))
    $config.entry_script_sha256=$files['operator_desktop_entry.ps1']
    if ($picker) {
        $config.mode='direct_profile';$config.startup_bundle='.codex/operator-direct-startup'
        $config.direct_entry_plan_sha256=$pickerSha
    }
    if ($modeEntry) {
        $config.mode='isolated_mode';$config.startup_bundle='.codex/operator-mode-entry/'+(Split-Path -Leaf $modeEntry.root)
        $config.mode_entry_sha256=$modeSha
        [void]$config.Remove('direct_entry_plan_sha256')
    }
    [IO.File]::WriteAllBytes((Join-Path $stage 'desktop-entry.json'),(ConvertTo-OperatorUpgradeBytes $config))
    $files['desktop-entry.json']=Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage 'desktop-entry.json'))
    $sourceDigest=Get-OperatorUpgradeHash ($script:UpgradeUtf8.GetBytes($sources['operator_desktop_entry.cs']+"`n"+$files['operator_desktop_entry.ps1']))
    $manifest=[ordered]@{schema_version=1;native_fallback='native-only-v1';binary_sha256=$files['Codex拓展入口.exe'];
        entry_script_sha256=$files['operator_desktop_entry.ps1'];build_date=$BuildDate;shortcut_layout='paired';
        product_version=$plugin.version;source_sha256=$sourceDigest}
    [IO.File]::WriteAllBytes((Join-Path $stage 'launcher-manifest.json'),(ConvertTo-OperatorUpgradeBytes $manifest))
    $files['launcher-manifest.json']=Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage 'launcher-manifest.json'))
    $currentSources=Get-OperatorUpgradeSource -Direct:($null -ne $picker) -Isolated:($null -ne $modeEntry)
    if (@($sources.Keys|Where-Object {$sources[$_] -cne $currentSources[$_]}).Count -or
        (Get-OperatorUpgradeCompilerHash $compiler) -cne $compilerHash -or
        (Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $bundle 'desktop-entry.json'))) -cne (Get-OperatorUpgradeHash $before) -or
        (Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $bundle 'Codex拓展入口.ico'))) -cne (Get-OperatorUpgradeHash $icon)) {
        throw 'pair_candidate_input_changed'
    }
    $record=[ordered]@{schema_version=1;scope='entry_build_candidate';project=$project;candidate=(Split-Path -Leaf $stage);
        build_date=$BuildDate;version=$plugin.version;source_sha256=$sourceDigest;sources=$sources;files=$files;
        config_before_sha256=(Get-OperatorUpgradeHash $before);config_before_base64=[Convert]::ToBase64String($before);
        icon_before_sha256=(Get-OperatorUpgradeHash $icon);
        compiler=$compiler;compiler_sha256=$compilerHash}
    if ($picker) {$record.direct_picker=@{path=[IO.Path]::GetFullPath($DirectPickerPath);sha256=$pickerSha;home=$picker.home}}
    if ($modeEntry) {$record.isolated_mode=@{path=[IO.Path]::GetFullPath($IsolatedModePath);sha256=$modeSha;home=$modeEntry.native_home}}
    [IO.File]::WriteAllBytes((Join-Path $stage 'candidate.json'),(ConvertTo-OperatorUpgradeBytes $record))
    return @{status='candidate_prepared';candidate_directory=$stage;candidate_sha256=(Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage 'candidate.json')));live_changed=$false}
}

function Get-OperatorEntryBuildCandidate {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CandidateDirectory)
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $stage=[IO.Path]::GetFullPath($CandidateDirectory).TrimEnd('\')
    if ((Split-Path -Parent $stage) -ine (Join-Path $project '.codex/operator-entry-build-candidates') -or
        (Split-Path -Leaf $stage) -cnotmatch '^[a-f0-9]{32}$') {throw 'pair_candidate_scope_invalid'}
    $record=Get-OperatorUpgradeJson (Join-Path $stage 'candidate.json')
    if ($record.schema_version -ne 1 -or $record.scope -cne 'entry_build_candidate' -or $record.project -ine $project -or
        $record.candidate -cne (Split-Path -Leaf $stage) -or $record.files -isnot [Collections.IDictionary]) {throw 'pair_candidate_invalid'}
    $expected=@('operator_desktop_entry.ps1','operator_native_entry.ps1','restore-codex-official-route.ps1',
        'Codex拓展入口.exe','desktop-entry.json','launcher-manifest.json')
    if ($record.icon_before_sha256 -ne 'absent') {$expected+='Codex拓展入口.ico'}
    if (@(Compare-Object @($record.files.Keys|Sort-Object) @($expected|Sort-Object)).Count) {throw 'pair_candidate_files_invalid'}
    foreach ($name in $expected) {
        if ($record.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage $name))) -cne $record.files[$name]) {
            throw 'pair_candidate_changed'
        }
    }
    $direct=$record.Contains('direct_picker')
    $isolated=$record.Contains('isolated_mode')
    if ($direct -and $isolated) {throw 'pair_candidate_mode_ambiguous'}
    $sources=Get-OperatorUpgradeSource -Direct:$direct -Isolated:$isolated
    if ($record.sources -isnot [Collections.IDictionary] -or $record.sources.Count -ne $sources.Count -or
        @($sources.Keys|Where-Object {$record.sources[$_] -cne $sources[$_]}).Count) {throw 'pair_candidate_source_changed'}
    $manifest=Get-OperatorUpgradeJson (Join-Path $stage 'launcher-manifest.json')
    $config=Get-OperatorUpgradeJson (Join-Path $stage 'desktop-entry.json')
    $parsedDate=[DateTime]::MinValue
    $plugin=Get-OperatorUpgradeJson (Join-Path $PSScriptRoot '../.codex-plugin/plugin.json')
    $derivedSource=Get-OperatorUpgradeHash ($script:UpgradeUtf8.GetBytes($sources['operator_desktop_entry.cs']+"`n"+$record.files['operator_desktop_entry.ps1']))
    if (-not [DateTime]::TryParseExact($record.build_date,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,[ref]$parsedDate) -or $record.version -cne $plugin.version -or
        $record.source_sha256 -cne $derivedSource) {throw 'pair_candidate_metadata_changed'}
    try {$original=[Convert]::FromBase64String($record.config_before_base64)} catch {throw 'pair_candidate_config_changed'}
    if ($original.Length -gt 16384 -or (Get-OperatorUpgradeHash $original) -cne $record.config_before_sha256) {throw 'pair_candidate_config_changed'}
    $expectedConfig=$script:UpgradeUtf8.GetString($original)|ConvertFrom-Json -AsHashtable
    $expectedConfig.entry_script_sha256=$record.files['operator_desktop_entry.ps1']
    if ($direct) {
        $picker=$record.direct_picker
        if ($picker -isnot [Collections.IDictionary] -or
            @(Compare-Object @($picker.Keys|Sort-Object) @('home','path','sha256')).Count -or
            $picker.sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'pair_candidate_direct_picker_invalid'}
        . (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1') -Library
        $checkedPicker=Get-OperatorDirectPicker $project $picker.home $picker.path $picker.sha256
        Assert-OperatorDirectEntryUpgradeReady $project $picker.home $checkedPicker
        $expectedConfig.mode='direct_profile';$expectedConfig.startup_bundle='.codex/operator-direct-startup'
        $expectedConfig.direct_entry_plan_sha256=$picker.sha256
    }
    if ($isolated) {
        $binding=$record.isolated_mode
        if ($binding -isnot [Collections.IDictionary] -or
            @(Compare-Object @($binding.Keys|Sort-Object) @('home','path','sha256')).Count) {throw 'pair_candidate_isolated_entry_invalid'}
        . (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1') -Library
        $modeEntry=Get-OperatorIsolatedModeEntry $project $binding.home $binding.path $binding.sha256
        Test-OperatorIsolatedModeEntry $modeEntry
        $maintenance=@{project=$project;home=$modeEntry.native_home;python=$modeEntry.python;python_sha256=$modeEntry.python_sha256}
        Assert-OperatorDirectEntryUpgradeReady $project $modeEntry.native_home $maintenance
        $expectedConfig.mode='isolated_mode';$expectedConfig.startup_bundle='.codex/operator-mode-entry/'+(Split-Path -Leaf $modeEntry.root)
        $expectedConfig.mode_entry_sha256=$binding.sha256
        [void]$expectedConfig.Remove('direct_entry_plan_sha256')
    }
    if ($config.Count -ne $expectedConfig.Count -or @($expectedConfig.Keys|Where-Object {
        -not $config.Contains($_) -or
        (Get-OperatorUpgradeHash (ConvertTo-OperatorUpgradeBytes $config[$_])) -cne
            (Get-OperatorUpgradeHash (ConvertTo-OperatorUpgradeBytes $expectedConfig[$_]))
    }).Count) {throw 'pair_candidate_config_changed'}
    if ($manifest.schema_version -ne 1 -or $manifest.shortcut_layout -cne 'paired' -or
        $manifest.native_fallback -cne 'native-only-v1' -or $manifest.build_date -cne $record.build_date -or
        $manifest.product_version -cne $record.version -or $manifest.source_sha256 -cne $record.source_sha256 -or
        $manifest.binary_sha256 -cne $record.files['Codex拓展入口.exe'] -or
        $manifest.entry_script_sha256 -cne $record.files['operator_desktop_entry.ps1'] -or
        $config.schema_version -ne 1 -or $config.mode -notin @('native','reviewed_startup','direct_profile','isolated_mode') -or
        (($config.mode -ceq 'direct_profile') -ne $direct) -or
        (($config.mode -ceq 'isolated_mode') -ne $isolated) -or
        $config.entry_script_sha256 -cne $record.files['operator_desktop_entry.ps1']) {throw 'pair_candidate_contract_changed'}
    return @{directory=$stage;record=$record;sha256=(Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $stage 'candidate.json')))}
}

function Get-OperatorDesktopPairUpgrade {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CandidateDirectory)
    $project=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $pair=Get-OperatorDesktopPairRestorePlan $project
    if ($pair.status -cne 'ready' -or $pair.record.ContainsKey('origin')) {throw 'pair_upgrade_normal_owner_required'}
    $old=$pair.record
    Assert-OperatorDesktopPairEnvironment -ProjectRoot $project -CodexHome $old.home -DesktopDirectory $old.desktop
    $bundle=Join-Path $project '.codex/operator-desktop-entry'
    if (Test-Path -LiteralPath (Join-Path $bundle 'native-only')) {throw 'pair_native_only_requires_review'}
    $config=Read-OperatorUpgradeBytes (Join-Path $old.home 'config.toml')
    $route=& $script:PairModule {param($B) Get-RecoveryConfigPlan $B} $config
    if ($route.state -cne 'native') {throw 'pair_upgrade_native_route_required'}
    foreach ($scope in @('Process','User','Machine')) {
        if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL',$scope)) {throw 'pair_upgrade_environment_override'}
    }
    $ownerFile=Join-Path $project '.codex/operator-installation/ownership.json'
    $owner=Get-OperatorUpgradeJson $ownerFile
    if ($owner.schema_version -ne 1 -or $owner.project -ine $project -or $owner.entries -isnot [Collections.IDictionary] -or
        (Test-Path -LiteralPath (Join-Path $project '.codex/operator-entry-migration'))) {throw 'pair_upgrade_normal_owner_required'}
    $candidate=Get-OperatorEntryBuildCandidate $project $CandidateDirectory
    $record=$candidate.record
    if ((Test-Path -LiteralPath (Join-Path $old.home 'operator-direct-entry')) -and -not $record.Contains('direct_picker') -and -not $record.Contains('isolated_mode')) {throw 'direct_cycle_maintenance_requires_bound_python'}
    if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $bundle 'desktop-entry.json'))) -cne $record.config_before_sha256 -or
        (Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $bundle 'Codex拓展入口.ico'))) -cne $record.icon_before_sha256) {
        throw 'pair_candidate_baseline_changed'
    }
    $newLink=Join-Path $old.desktop ('ChatGPT 拓展模型 '+$record.build_date.Substring(5)+' 入口.lnk')
    if (-not $old.links.Contains($newLink) -and $null -ne (Read-OperatorUpgradeBytes $newLink)) {throw 'pair_shortcut_name_conflict'}
    $upgradeRoot=Join-Path $project '.codex/operator-desktop-pair/upgrades'
    Assert-OperatorUpgradePath $upgradeRoot
    if (Test-Path -LiteralPath $upgradeRoot) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $upgradeRoot -Directory)) {
            Assert-OperatorUpgradePath $dir.FullName
            if (-not (Test-Path -LiteralPath (Join-Path $dir.FullName 'committed-intent.json')) -or
                -not (Test-Path -LiteralPath (Join-Path $dir.FullName 'completed.json')) -or
                (Test-Path -LiteralPath (Join-Path $dir.FullName 'pending.json'))) {throw 'pair_upgrade_pending_requires_review'}
        }
    }
    if (Test-Path -LiteralPath (Join-Path $upgradeRoot $record.candidate)) {throw 'pair_upgrade_candidate_consumed'}
    $plan=[ordered]@{schema_version=1;scope='desktop_pair_build_upgrade';project=$project;home=$old.home;desktop=$old.desktop;
        pair_receipt_sha256=$pair.receipt_sha256;owner_sha256=(Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $ownerFile));
        native_config_sha256=(Get-OperatorUpgradeHash $config);candidate_directory=$candidate.directory;candidate_sha256=$candidate.sha256;
        old_build=$old.build;old_links=$old.links;new_link=$newLink;build_date=$record.build_date}
    return @{plan=$plan;sha256=(Get-OperatorPairPreviewHash $plan);pair=$pair;candidate=$candidate;configuration_changed=$false}
}

function Assert-OperatorPairUpgradeBoundary($Review) {
    # This transaction's own pending intent must not be interpreted as another
    # failed upgrade by public status. Revalidate the bound pre-write state
    # directly; this does not waive any public pending-record guard.
    $plan=$Review.plan;$project=$plan.project;$old=$Review.pair.record
    $root=Join-Path $project '.codex/operator-desktop-pair'
    $bundle=Join-Path $project '.codex/operator-desktop-entry'
    foreach ($path in @($project,$plan.home,$plan.desktop,$root,$bundle)) {Assert-OperatorUpgradePath $path}
    if ((Test-Path -LiteralPath (Join-Path $root 'pending.json')) -or
        (Test-Path -LiteralPath (Join-Path $plan.home 'operator-unified-activation'))) {throw 'pair_activation_requires_separate_review'}
    if (Test-Path -LiteralPath (Join-Path $bundle 'native-only')) {throw 'pair_native_only_requires_review'}
    $defaultHome=& $script:PairModule {Get-OperatorPairDefaultHome}
    if ([IO.Path]::GetFullPath($defaultHome).TrimEnd('\') -ine $plan.home -or
        ($env:CODEX_HOME -and [IO.Path]::GetFullPath($env:CODEX_HOME).TrimEnd('\') -ine $plan.home)) {throw 'pair_default_home_required'}
    foreach ($scope in @('Process','User','Machine')) {
        if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL',$scope)) {throw 'pair_upgrade_environment_override'}
    }
    $checks=@{
        (Join-Path $root 'ownership.json')=$plan.pair_receipt_sha256;
        (Join-Path $project '.codex/operator-installation/ownership.json')=$plan.owner_sha256;
        (Join-Path $plan.home 'config.toml')=$plan.native_config_sha256;
        (Join-Path $bundle 'desktop-entry.json')=$Review.candidate.record.config_before_sha256;
        (Join-Path $bundle 'Codex拓展入口.ico')=$Review.candidate.record.icon_before_sha256}
    foreach ($name in $old.build.Keys) {$checks[(Join-Path $bundle $name)]=$old.build[$name]}
    foreach ($path in $old.links.Keys) {$checks[$path]=$old.links[$path].after}
    if (-not $old.links.Contains($plan.new_link)) {$checks[$plan.new_link]='absent'}
    foreach ($path in $checks.Keys) {
        if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes $path)) -cne $checks[$path]) {throw 'pair_upgrade_preview_changed'}
    }
    $candidate=Get-OperatorEntryBuildCandidate $project $plan.candidate_directory
    if ($candidate.sha256 -cne $plan.candidate_sha256) {throw 'pair_upgrade_preview_changed'}
    & $script:PairModule {param($P,$R) Assert-OperatorPairRecord $P $R} $project $old
}

function Invoke-OperatorDesktopPairUpgrade {
    param([Parameter(Mandatory)][string]$ProjectRoot,[Parameter(Mandatory)][string]$CandidateDirectory,
        [Parameter(Mandatory)][string]$ExpectedPlanSha256)
    $review=Get-OperatorDesktopPairUpgrade $ProjectRoot $CandidateDirectory
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $review.sha256 -cne $ExpectedPlanSha256) {throw 'pair_upgrade_preview_changed'}
    $project=$review.plan.project
    $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:UpgradeUtf8.GetBytes($project.ToLowerInvariant())))
    $mutex=[Threading.Mutex]::new($false,('Local\CodexOperatorDesktopEntry-'+$hash));$owns=$false;$lock=$null
    try {
        try {$owns=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$owns=$true}
        if (-not $owns) {throw 'pair_entry_busy'}
        $root=Join-Path $project '.codex/operator-desktop-pair'
        $lock=[IO.File]::Open((Join-Path $root 'transaction.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $repeat=Get-OperatorDesktopPairUpgrade $project $CandidateDirectory
        if ($repeat.sha256 -cne $ExpectedPlanSha256) {throw 'pair_upgrade_preview_changed'}
        $old=$review.pair.record;$candidate=$review.candidate.record;$stage=$review.candidate.directory
        $generation=Join-Path $root ('generations/'+$candidate.candidate)
        if (Test-Path -LiteralPath $generation) {throw 'pair_upgrade_generation_exists'}
        New-OperatorUpgradeDirectory $generation
        $nativeFiles=@{}
        foreach ($name in @('operator_native_entry.ps1','operator_desktop_entry.ps1','restore-codex-official-route.ps1')) {
            $bytes=Read-OperatorUpgradeBytes (Join-Path $stage $name)
            [IO.File]::WriteAllBytes((Join-Path $generation $name),$bytes)
            $nativeFiles[$name]=Get-OperatorUpgradeHash $bytes
        }
        $nativeValue=@{schema_version=1;project=$project;home=$old.home;files=@{
            'operator_desktop_entry.ps1'=$nativeFiles['operator_desktop_entry.ps1'];
            'restore-codex-official-route.ps1'=$nativeFiles['restore-codex-official-route.ps1']}}
        if ($candidate.Contains('isolated_mode')) {$nativeValue.activation_mode='registered_application_v1'}
        $nativeConfig=ConvertTo-OperatorUpgradeBytes $nativeValue
        [IO.File]::WriteAllBytes((Join-Path $generation 'native-entry.json'),$nativeConfig)
        $nativeFiles['native-entry.json']=Get-OperatorUpgradeHash $nativeConfig
        $shell=Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
        if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) {throw 'pair_powershell_missing'}
        $nativeBytes=& $script:PairModule {param($P,$S,$A,$D) New-OperatorPairShortcut $P $S $A $D '打开官方原生模式；需要切换时先确认正常退出。'} `
            (Join-Path $generation 'native.lnk') $shell ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+(Join-Path $generation 'operator_native_entry.ps1')+'"') $generation
        $bundle=Join-Path $project '.codex/operator-desktop-entry'
        $extensionBytes=& $script:PairModule {param($P,$T,$D) New-OperatorPairShortcut $P $T '' $D '使用已配置的拓展模型；不会自动解除官方直连保护。'} `
            (Join-Path $generation 'extension.lnk') (Join-Path $bundle 'Codex拓展入口.exe') $bundle
        $changes=@()
        $build=@{}
        foreach ($name in @('operator_desktop_entry.ps1','desktop-entry.json','Codex拓展入口.exe','launcher-manifest.json')) {
            $path=Join-Path $bundle $name;$bytes=Read-OperatorUpgradeBytes (Join-Path $stage $name)
            $changes+=@{path=$path;before=(Read-OperatorUpgradeBytes $path);after=$bytes}
            if ($name -ne 'desktop-entry.json') {$build[$name]=Get-OperatorUpgradeHash $bytes}
        }
        $nativePath=Join-Path $old.desktop 'ChatGPT 原生入口.lnk'
        $changes+=@{path=$nativePath;before=(Read-OperatorUpgradeBytes $nativePath);after=[byte[]]$nativeBytes}
        $newLink=$review.plan.new_link
        $changes+=@{path=$newLink;before=(Read-OperatorUpgradeBytes $newLink);after=[byte[]]$extensionBytes}
        foreach ($path in $old.links.Keys) {
            if ($path -ine $nativePath -and $path -ine $newLink) {$changes+=@{path=$path;before=(Read-OperatorUpgradeBytes $path);after=$null}}
        }
        $after=@{schema_version=1;project=$project;home=$old.home;desktop=$old.desktop;phase='installed';
            generation=$candidate.candidate;build_date=$candidate.build_date;version=$candidate.version;
            source_sha256=$candidate.source_sha256;build=$build;files=$nativeFiles;links=@{}}
        $after.links[$nativePath]=@{before='absent';after=(Get-OperatorUpgradeHash ([byte[]]$nativeBytes))}
        $after.links[$newLink]=@{before='absent';after=(Get-OperatorUpgradeHash ([byte[]]$extensionBytes))}
        $receipt=Join-Path $root 'ownership.json'
        $changes+=@{path=$receipt;before=(Read-OperatorUpgradeBytes $receipt);after=(ConvertTo-OperatorUpgradeBytes $after)}
        $transactionPath=Join-Path $root ('upgrades/'+$candidate.candidate)
        $boundary={
            Assert-OperatorPairUpgradeBoundary $review
            foreach ($name in $nativeFiles.Keys) {
                if ((Get-OperatorUpgradeHash (Read-OperatorUpgradeBytes (Join-Path $generation $name))) -cne $nativeFiles[$name]) {throw 'pair_upgrade_native_helper_changed'}
            }
        }
        # Keep staged helper generations, including failures, for explicit review.
        Invoke-OperatorEntryExactTransaction -TransactionRoot $transactionPath -Changes $changes -Boundary $boundary
        return @{status='pair_upgraded';build_date=$candidate.build_date;routing_changed=$false;model_requests=0;desktop_acceptance='unverified'}
    } finally {if ($lock) {$lock.Dispose()};if ($owns) {$mutex.ReleaseMutex()};$mutex.Dispose()}
}

Export-ModuleMember -Function New-OperatorEntryBuildCandidate,Get-OperatorEntryBuildCandidate,Get-OperatorDesktopPairUpgrade,Invoke-OperatorDesktopPairUpgrade,Invoke-OperatorEntryExactTransaction,Get-OperatorEntryMoveIdentity
