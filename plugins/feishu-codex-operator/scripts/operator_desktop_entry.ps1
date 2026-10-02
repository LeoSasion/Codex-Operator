#requires -Version 7.0
[CmdletBinding()]
param([string]$StartupBundle, [switch]$CheckOnly, [switch]$Library)
$ErrorActionPreference = 'Stop'
$script:OperatorDirectEntrySourcePath=$PSCommandPath

function Get-OperatorPackagedApplication {
    $packages = @(Get-AppxPackage -Name 'OpenAI.Codex')
    if ($packages.Count -ne 1) { throw 'Cannot identify the installed Codex application.' }
    $package = $packages[0]
    $appRoot = [IO.Path]::GetFullPath($package.InstallLocation).TrimEnd('\') + '\'
    $executable = Join-Path $appRoot 'app\ChatGPT.exe'
    $manifestPath = Join-Path $appRoot 'AppxManifest.xml'
    $explorer = Join-Path $env:SystemRoot 'explorer.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf) -or
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        (Get-Item -LiteralPath $manifestPath).Length -gt 1048576 -or
        -not (Test-Path -LiteralPath $explorer -PathType Leaf) -or
        $package.PackageFamilyName -cnotmatch '\AOpenAI\.Codex_[a-z0-9]+\z') {
        throw 'The installed Codex package identity changed.'
    }
    [xml]$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8
    $apps = @($manifest.Package.Applications.Application | Where-Object { $_.Id -ceq 'App' })
    if ($manifest.Package.Identity.Name -cne 'OpenAI.Codex' -or $apps.Count -ne 1 -or
        $apps[0].Executable -cne 'app/ChatGPT.exe' -or
        $apps[0].EntryPoint -cne 'Windows.FullTrustApplication') {
        throw 'The installed Codex package identity changed.'
    }
    return [pscustomobject]@{root=$appRoot; executable=$executable;
        aumid=($package.PackageFamilyName + '!App'); explorer=$explorer}
}

function Open-OperatorPackagedApplication($Application) {
    # Activate the registered launch contract even when an isolated window is
    # already open. Explorer's AppsFolder forwarding can leave that window in front.
    if (-not ('OperatorRegisteredActivation' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class OperatorRegisteredActivation {
    [ComImport,Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IActivation {
        [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string app,
            [MarshalAs(UnmanagedType.LPWStr)] string arguments,uint options,out uint pid);
        [PreserveSig] int ActivateForFile([MarshalAs(UnmanagedType.LPWStr)] string app,IntPtr items,
            [MarshalAs(UnmanagedType.LPWStr)] string verb,out uint pid);
        [PreserveSig] int ActivateForProtocol([MarshalAs(UnmanagedType.LPWStr)] string app,IntPtr items,out uint pid);
    }
    public static void Open(string app) {
        if(app!="OpenAI.Codex_2p2nqsd0c76g0!App") throw new InvalidOperationException("native_application_changed");
        object manager=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
        try { uint pid; Marshal.ThrowExceptionForHR(((IActivation)manager).ActivateApplication(app,null,0,out pid));
            if(pid==0) throw new InvalidOperationException("native_activation_unconfirmed"); }
        finally {Marshal.ReleaseComObject(manager);}
    }
}
'@
    }
    [OperatorRegisteredActivation]::Open($Application.aumid)
}

function Read-OperatorDirectEntryBytes([string]$Path,[int]$Limit=1048576) {
    if (-not [IO.Path]::IsPathFullyQualified($Path)) {throw 'direct_entry_absolute_path_required'}
    $cursor=[IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and
            ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {throw 'direct_entry_linked_path'}
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if ($stream.Length -gt $Limit) {throw 'direct_entry_file_bound'}
        $reader=[IO.BinaryReader]::new($stream)
        try {return ,$reader.ReadBytes($Limit+1)} finally {$reader.Dispose()}
    } finally {$stream.Dispose()}
}

function Get-OperatorDirectEntryHash([byte[]]$Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Get-OperatorIsolatedModeEntry([string]$Project,[string]$HomePath,[string]$Path,[string]$ExpectedSha256) {
    $project=[IO.Path]::GetFullPath($Project).TrimEnd('\')
    $homePath=[IO.Path]::GetFullPath($HomePath).TrimEnd('\')
    $path=[IO.Path]::GetFullPath($Path)
    $root=Split-Path -Parent $path
    if ((Split-Path -Leaf $path) -cne 'entry.json' -or (Split-Path -Leaf $root) -cnotmatch '^[a-f0-9]{32}$' -or
        (Split-Path -Parent $root) -ine (Join-Path $project '.codex/operator-mode-entry') -or
        $ExpectedSha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'isolated_entry_scope_invalid'}
    $raw=Read-OperatorDirectEntryBytes $path 1048576
    if ((Get-OperatorDirectEntryHash $raw) -cne $ExpectedSha256) {throw 'isolated_entry_changed'}
    $entry=[Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json -AsHashtable
    if ($entry.schema_version -ne 1 -or $entry.contract -cne 'operator_isolated_mode_entry_v1' -or
        $entry.project -ine $project -or $entry.root -ine $root -or $entry.native_home -ine $homePath -or
        $entry.native_enabled -ne $false -or $entry.entry_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes (Join-Path $root 'entry.ps1'))) -cne $entry.entry_sha256) {throw 'isolated_entry_invalid'}
    return $entry
}

function Test-OperatorIsolatedModeEntry($Entry) {
    $controller=Join-Path $Entry.project 'plugins/feishu-codex-operator/scripts/operator_mode_entry.py'
    if ((Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $Entry.python 16777216)) -cne $Entry.python_sha256 -or
        (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $controller)) -cne $Entry.source_bindings.'operator_mode_entry.py') {throw 'isolated_entry_dependency_changed'}
    $output=@(& $Entry.python -E -s -B $controller status --root $Entry.root 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or ([string]$output[0]).Length -gt 65536) {throw 'isolated_entry_status_failed'}
    $status=([string]$output[0])|ConvertFrom-Json -AsHashtable
    if ($status.phase -cne 'checked' -or $status.official_package_matches -ne $true -or
        $status.native_enabled -ne $false -or $status.native_config_writes -ne 0 -or
        $status.model_requests_sent_by_controller -ne 0) {throw 'isolated_entry_status_invalid'}
}

function Get-OperatorDirectPicker([string]$Project,[string]$HomePath,[string]$Path,[string]$ExpectedSha256) {
    $project=[IO.Path]::GetFullPath($Project).TrimEnd('\')
    $homePath=[IO.Path]::GetFullPath($HomePath).TrimEnd('\')
    if ([IO.Path]::GetFullPath($Path) -ine (Join-Path $project '.codex/operator-direct-startup/direct-entry-plan.json') -or
        $ExpectedSha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'direct_picker_scope_invalid'}
    $raw=Read-OperatorDirectEntryBytes $Path 65536
    if ((Get-OperatorDirectEntryHash $raw) -cne $ExpectedSha256) {throw 'direct_picker_changed'}
    $plan=[Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json -AsHashtable
    $keys=@('schema_version','contract','project','home','python','python_sha256','native_helper',
        'native_helper_sha256','controller','controller_sha256','entry_script_sha256','profiles')
    if (@(Compare-Object @($plan.Keys|Sort-Object) @($keys|Sort-Object)).Count -or
        $plan.schema_version -ne 1 -or $plan.contract -cne 'direct_profile_picker_v1' -or
        $plan.project -ine $project -or $plan.home -ine $homePath -or
        $plan.profiles -isnot [array] -or $plan.profiles.Count -lt 1 -or $plan.profiles.Count -gt 32 -or
        $plan.controller -ine (Join-Path $project 'plugins/feishu-codex-operator/scripts/operator_direct_entry.py') -or
        $plan.entry_script_sha256 -cne (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $script:OperatorDirectEntrySourcePath))) {throw 'direct_picker_invalid'}
    foreach ($pair in @(@('python','python_sha256'),@('native_helper','native_helper_sha256'),@('controller','controller_sha256'))) {
        if ($plan[$pair[1]] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $plan[$pair[0]] $(if ($pair[0] -eq 'python') {16777216} else {1048576}))) -cne $plan[$pair[1]]) {throw 'direct_picker_dependency_changed'}
    }
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($row in $plan.profiles) {
        if ($row -isnot [Collections.IDictionary] -or
            @(Compare-Object @($row.Keys|Sort-Object) @('display_name','plan','plan_sha256','profile')).Count -or
            $row.profile -cnotmatch '^operator-[a-z0-9][a-z0-9-]{0,49}$' -or -not $seen.Add($row.profile) -or
            $row.display_name -isnot [string] -or $row.display_name.Length -lt 1 -or $row.display_name.Length -gt 128 -or
            $row.display_name -match '[\x00-\x1f\x7f]' -or
            $row.plan_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'direct_picker_profile_invalid'}
        $profilePlan=[IO.Path]::GetFullPath($row.plan)
        $parent=Split-Path -Parent $profilePlan
        if ((Split-Path -Leaf $profilePlan) -cne 'plan.json' -or (Split-Path -Leaf $parent) -cnotmatch '^[a-f0-9]{32}$' -or
            (Split-Path -Parent $parent) -ine (Join-Path $project '.codex/operator-direct-startup/plans') -or
            (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $profilePlan)) -cne $row.plan_sha256) {throw 'direct_picker_profile_changed'}
        $profileValue=[Text.UTF8Encoding]::new($false,$true).GetString((Read-OperatorDirectEntryBytes $profilePlan))|ConvertFrom-Json -AsHashtable
        if ($profileValue.schema_version -ne 1 -or $profileValue.contract -cne 'operator_direct_entry_plan_v1' -or
            $profileValue.project -ine $project -or $profileValue.home -ine $homePath -or
            $profileValue.profile -cne $row.profile -or $profileValue.display_name -cne $row.display_name -or
            $profileValue.python.path -ine $plan.python -or $profileValue.python.sha256 -cne $plan.python_sha256 -or
            $profileValue.native_helper.path -ine $plan.native_helper -or $profileValue.native_helper.sha256 -cne $plan.native_helper_sha256 -or
            $profileValue.entry_script.path -ine (Join-Path $project 'plugins/feishu-codex-operator/scripts/operator_desktop_entry.ps1') -or
            $profileValue.entry_script.sha256 -cne $plan.entry_script_sha256) {throw 'direct_picker_profile_binding_changed'}
    }
    return $plan
}

function Select-OperatorDirectProfile($Plan) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form=[Windows.Forms.Form]::new();$form.Text='ChatGPT 拓展模型入口'
    $form.ClientSize=[Drawing.Size]::new(480,175);$form.StartPosition='CenterScreen'
    $form.FormBorderStyle='FixedDialog';$form.MaximizeBox=$false;$form.MinimizeBox=$false
    $label=[Windows.Forms.Label]::new();$label.Text='选择本次使用的模型提供方。切换前请正常完全退出 Codex。'
    $label.SetBounds(20,20,440,35);$form.Controls.Add($label)
    $choices=[Windows.Forms.ComboBox]::new();$choices.DropDownStyle='DropDownList'
    $choices.SetBounds(20,60,440,30);[void]$choices.Items.Add('官方原生模型')
    foreach ($row in $Plan.profiles) {[void]$choices.Items.Add($row.display_name)}
    $choices.SelectedIndex=0;$form.Controls.Add($choices)
    $open=[Windows.Forms.Button]::new();$open.Text='打开';$open.SetBounds(270,115,90,32);$open.DialogResult='OK'
    $cancel=[Windows.Forms.Button]::new();$cancel.Text='取消';$cancel.SetBounds(370,115,90,32);$cancel.DialogResult='Cancel'
    $form.Controls.AddRange([Windows.Forms.Control[]]@($open,$cancel));$form.AcceptButton=$open;$form.CancelButton=$cancel
    try {
        if ($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) {return -1}
        return $choices.SelectedIndex
    } finally {$form.Dispose()}
}

function Invoke-OperatorDirectController($Plan,$Row,[string]$Action,[string]$CurrentConfigSha256) {
    $arguments=@('-E','-s','-B',$Plan.controller,$Action,'--plan',$Row.plan)
    if ($Action -ceq 'activate') {$arguments+=@('--expected-plan-sha256',$Row.plan_sha256,'--expected-current-config-sha256',$CurrentConfigSha256)}
    $output=@(& $Plan.python @arguments 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or ([string]$output[0]).Length -gt 65536) {throw 'direct_controller_stopped'}
    $value=([string]$output[0])|ConvertFrom-Json -AsHashtable
    if ($value.model_requests -ne 0 -or $value.desktop_launch -eq $true) {throw 'direct_controller_result_invalid'}
    return $value
}

function New-OperatorDirectLaunchIntent($Plan,$Row,[string]$PickerSha256,$Applied,$Application) {
    if ($Applied.cycle -cnotmatch '^[a-f0-9]{32}$') {throw 'direct_launch_cycle_invalid'}
    $root=Join-Path $Plan.home 'operator-direct-entry'
    $active=[Text.UTF8Encoding]::new($false,$true).GetString((Read-OperatorDirectEntryBytes (Join-Path $root 'active.json') 16384))|ConvertFrom-Json -AsHashtable
    $cycle=Join-Path $root ('cycles/'+$Applied.cycle)
    $raw=Read-OperatorDirectEntryBytes (Join-Path $cycle 'intent.json') 4194304
    $intent=[Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json -AsHashtable
    if ($active.schema_version -ne 1 -or $active.contract -cne 'operator_direct_entry_active_v1' -or
        $active.cycle -cne $Applied.cycle -or $active.intent_sha256 -cne (Get-OperatorDirectEntryHash $raw) -or
        $intent.contract -cne 'operator_direct_entry_cycle_v1' -or $intent.cycle -cne $Applied.cycle -or
        $intent.home -ine $Plan.home -or $intent.project -ine $Plan.project -or
        $intent.plan_sha256 -cne $Row.plan_sha256 -or $intent.native_helper_sha256 -cne $Plan.native_helper_sha256 -or
        @(Compare-Object @($intent.files.Keys|Sort-Object) @('config-before.bin','config-candidate.bin','plan.json','profile.json','projection.json')).Count) {throw 'direct_launch_cycle_invalid'}
    foreach ($name in $intent.files.Keys) {
        if ($intent.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes (Join-Path $cycle $name) 4194304)) -cne $intent.files[$name]) {throw 'direct_launch_cycle_changed'}
    }
    $appliedRaw=Read-OperatorDirectEntryBytes (Join-Path $cycle 'applied.json') 65536
    $witness=[Text.UTF8Encoding]::new($false,$true).GetString($appliedRaw)|ConvertFrom-Json -AsHashtable
    if ($witness.schema_version -ne 1 -or $witness.contract -cne 'operator_direct_entry_applied_v1' -or
        $witness.cycle -cne $Applied.cycle -or $witness.intent_sha256 -cne $active.intent_sha256 -or
        $witness.status -cne 'applied' -or $witness.reason -cne 'applied_witnessed' -or
        -not [IO.Path]::IsPathFullyQualified($witness.transaction) -or
        (Split-Path -Parent $witness.transaction) -ine $cycle -or
        (Split-Path -Leaf $witness.transaction) -cnotmatch '^\.operator-config-transaction-[a-f0-9]{32}$') {throw 'direct_launch_witness_invalid'}
    $verified=[Text.UTF8Encoding]::new($false,$true).GetString((Read-OperatorDirectEntryBytes (Join-Path $witness.transaction 'verified.json') 16384))|ConvertFrom-Json -AsHashtable
    $boundary=[Text.UTF8Encoding]::new($false,$true).GetString((Read-OperatorDirectEntryBytes (Join-Path $witness.transaction 'intent.json') 65536))|ConvertFrom-Json -AsHashtable
    if ($verified.status -cne 'applied_witnessed' -or $boundary.target -ine (Join-Path $Plan.home 'config.toml') -or
        $boundary.expected_sha256 -cne $intent.files['config-before.bin'] -or
        $boundary.candidate_sha256 -cne $intent.files['config-candidate.bin']) {throw 'direct_launch_witness_invalid'}
    if ((Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes (Join-Path $Plan.home 'config.toml'))) -cne $intent.files['config-candidate.bin'] -or
        (Test-Path -LiteralPath (Join-Path $cycle 'launch-intent.json')) -or
        (Test-Path -LiteralPath (Join-Path $cycle 'launch-result.json'))) {throw 'direct_launch_not_replayable'}
    $launch=[ordered]@{schema_version=1;contract='operator_direct_entry_launch_v1';cycle=$Applied.cycle;
        intent_sha256=$active.intent_sha256;plan_sha256=$Row.plan_sha256;picker_sha256=$PickerSha256;
        applied_sha256=(Get-OperatorDirectEntryHash $appliedRaw);
        entry_script_sha256=$Plan.entry_script_sha256;config_sha256=$intent.files['config-candidate.bin'];
        aumid=$Application.aumid;executable_sha256=(Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes $Application.executable 536870912));
        manifest_sha256=(Get-OperatorDirectEntryHash (Read-OperatorDirectEntryBytes (Join-Path $Application.root 'AppxManifest.xml')));
        requested_utc=[DateTime]::UtcNow.ToString('o');model_requests=0}
    $launchRaw=[Text.UTF8Encoding]::new($false).GetBytes(($launch|ConvertTo-Json -Depth 5 -Compress))
    $file=[IO.File]::Open((Join-Path $cycle 'launch-intent.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$file.Write($launchRaw);$file.Flush($true)} finally {$file.Dispose()}
    return @{directory=$cycle;sha256=(Get-OperatorDirectEntryHash $launchRaw)}
}

function Write-OperatorDirectLaunchResult($Launch,[string]$Outcome) {
    if ($Outcome -cnotin @('shell_requested','shell_failed')) {throw 'direct_launch_result_invalid'}
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes((@{schema_version=1;contract='operator_direct_entry_launch_result_v1';
        launch_intent_sha256=$Launch.sha256;outcome=$Outcome;desktop_acceptance='unverified';model_requests=0}|ConvertTo-Json -Compress))
    $file=[IO.File]::Open((Join-Path $Launch.directory 'launch-result.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$file.Write($bytes);$file.Flush($true)} finally {$file.Dispose()}
}

function Invoke-OperatorDirectPicker($Plan,[string]$PickerPath,[string]$PickerSha256,$Application,[switch]$InspectOnly) {
    if ($InspectOnly) {return @{status='ready';action='choose_provider';configuration_changed=$false;launch_requested=$false;model_requests=0}}
    $running=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'")
    if ($running.Count) {
        if (@($running|Where-Object {[string]::IsNullOrWhiteSpace($_.ExecutablePath) -or
            [IO.Path]::GetFullPath($_.ExecutablePath) -ine [IO.Path]::GetFullPath($Application.executable)}).Count) {throw 'direct_running_application_unknown'}
        # Open the running app without interpreting its selected task or route.
        Open-OperatorPackagedApplication $Application
        return @{status='opened_existing';configuration_changed=$false;launch_requested=$true;model_requests=0}
    }
    $selection=Select-OperatorDirectProfile $Plan
    if ($selection -lt 0) {return @{status='cancelled';configuration_changed=$false;launch_requested=$false;model_requests=0}}
    if ($selection -gt $Plan.profiles.Count) {throw 'direct_picker_selection_invalid'}
    $checked=Get-OperatorDirectPicker $Plan.project $Plan.home $PickerPath $PickerSha256
    if (@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'").Count) {throw 'direct_desktop_running'}
    # This is the user's selected new mode, never a replay of the old turn.
    . $checked.native_helper -Library
    $recovery=Invoke-OfficialRouteRecovery $checked.home $checked.project $true
    if ($recovery.status -cne 'completed' -or $recovery.warnings.Count) {throw 'direct_native_recovery_stopped'}
    $changed=[bool]$recovery.config_changed
    if ($selection -gt 0) {
        $row=$checked.profiles[$selection-1]
        $preview=Invoke-OperatorDirectController $checked $row 'preview' ''
        if ($preview.status -cne 'preview' -or $preview.profile -cne $row.profile -or
            $preview.plan_sha256 -cne $row.plan_sha256 -or $preview.current_config_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'direct_profile_preview_stopped'}
        $applied=Invoke-OperatorDirectController $checked $row 'activate' $preview.current_config_sha256
        if ($applied.status -cne 'config_applied' -or -not $applied.configuration_changed) {throw 'direct_profile_activation_stopped'}
        $changed=$true
    }
    if (@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'").Count) {throw 'direct_desktop_running_after_selection'}
    $freshApplication=Get-OperatorPackagedApplication
    if ($freshApplication.aumid -cne $Application.aumid -or $freshApplication.executable -ine $Application.executable) {throw 'direct_package_changed'}
    $launch=$null
    if ($selection -gt 0) {$launch=New-OperatorDirectLaunchIntent $checked $row $PickerSha256 $applied $freshApplication}
    try {Open-OperatorPackagedApplication $freshApplication}
    catch {
        if ($launch) {Write-OperatorDirectLaunchResult $launch 'shell_failed'}
        return @{status='launch_failed';configuration_changed=$changed;launch_requested=$true;model_requests=0;desktop_acceptance='unverified'}
    }
    if ($launch) {Write-OperatorDirectLaunchResult $launch 'shell_requested'}
    return @{status='launch_requested';configuration_changed=$changed;launch_requested=$true;model_requests=0;desktop_acceptance='unverified'}
}

if ($Library) { return }
$entryMutex = $null
$ownsMutex = $false
$entryLog = $null
try {
    if (-not $StartupBundle) { throw 'The startup bundle is required.' }
    $bundle = [IO.Path]::GetFullPath($StartupBundle).TrimEnd('\')
    $privateRoot = Split-Path -Parent $bundle
    if ((Split-Path -Leaf $privateRoot) -cne '.codex') { throw 'The startup bundle must belong to the selected project.' }
    $projectRoot = Split-Path -Parent $privateRoot
    $expectedScripts = [IO.Path]::GetFullPath((Join-Path $projectRoot 'plugins\feishu-codex-operator\scripts'))
    $entryConfigFile = Join-Path $bundle 'desktop-entry.json'
    $entryConfig = if (Test-Path -LiteralPath $entryConfigFile) {
        if ((Get-Item -LiteralPath $entryConfigFile).Length -gt 16384) { throw 'Invalid desktop entry configuration.' }
        Get-Content -LiteralPath $entryConfigFile -Raw -Encoding utf8 | ConvertFrom-Json
    } else { $null }
    if ([IO.Path]::GetFullPath($PSScriptRoot) -ine $expectedScripts) {
        if ([IO.Path]::GetFullPath($PSScriptRoot) -ine $bundle -or -not $entryConfig -or
            (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entryConfig.entry_script_sha256) {
            throw 'The installed entry identity changed.'
        }
    }
    $workflowBundle = $bundle
    $nativeOnly = $false
    if ($entryConfig) {
        if ($entryConfig.schema_version -ne 1 -or $entryConfig.mode -notin @('native','reviewed_startup','direct_profile','isolated_mode')) { throw 'Invalid desktop entry mode.' }
        $nativeOnly = $entryConfig.mode -eq 'native'
        if (-not $nativeOnly) {
            $workflowBundle = [IO.Path]::GetFullPath((Join-Path $projectRoot $entryConfig.startup_bundle))
            if ($entryConfig.mode -cne 'isolated_mode' -and (Split-Path -Parent $workflowBundle) -ine $privateRoot) { throw 'Startup workflow is outside the selected project.' }
        }
    }
    $routeHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    $directPicker=$null
    $isolatedEntry=$null
    if ($entryConfig -and $entryConfig.mode -ceq 'isolated_mode') {
        $isolatedEntry=Get-OperatorIsolatedModeEntry $projectRoot $routeHome (Join-Path $workflowBundle 'entry.json') $entryConfig.mode_entry_sha256
    } elseif ($entryConfig -and $entryConfig.mode -ceq 'direct_profile') {
        $defaultHome=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'
        if ([IO.Path]::GetFullPath($routeHome).TrimEnd('\') -ine $defaultHome -or
            -not (Test-Path -LiteralPath (Join-Path $routeHome 'operator-native-route-only'))) {throw 'direct_native_protection_required'}
        $pickerPath=Join-Path $workflowBundle 'direct-entry-plan.json'
        $directPicker=Get-OperatorDirectPicker $projectRoot $routeHome $pickerPath $entryConfig.direct_entry_plan_sha256
    } elseif (Test-Path -LiteralPath (Join-Path $routeHome 'operator-native-route-only')) { $nativeOnly = $true }
    if (-not $CheckOnly) {
        $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))
        $entryMutex = [Threading.Mutex]::new($false, ('Local\CodexOperatorDesktopEntry-' + $hash))
        try { $ownsMutex = $entryMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
        if (-not $ownsMutex) { Write-Output 'Codex startup is already in progress.'; exit 0 }
        $logDirectory = Join-Path $bundle 'startup-logs'
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $entryLog = Join-Path $logDirectory ('unified-' + [Guid]::NewGuid().ToString('N') + '.log')
        New-Item -ItemType File -Path $entryLog | Out-Null
        $entryLog | Set-Content -LiteralPath (Join-Path $bundle 'unified-startup-last-log.txt') -Encoding utf8
    }
    $application = Get-OperatorPackagedApplication
    if ($isolatedEntry) {
        if ($CheckOnly) {
            Test-OperatorIsolatedModeEntry $isolatedEntry
            @{action='choose_native_or_extension';configuration_changed=$false;model_requests=0}|ConvertTo-Json -Compress
        } else {
            & (Join-Path $isolatedEntry.root 'entry.ps1') -Action choose -Root $isolatedEntry.root
            if ($LASTEXITCODE -ne 0) {throw 'isolated_entry_stopped'}
        }
        exit 0
    }
    if ($directPicker) {
        $directResult=Invoke-OperatorDirectPicker $directPicker $pickerPath $entryConfig.direct_entry_plan_sha256 $application -InspectOnly:$CheckOnly
        if ($CheckOnly) {$directResult|ConvertTo-Json -Compress}
        if ($directResult.status -notin @('ready','opened_existing','cancelled','launch_requested')) {throw 'direct_entry_stopped'}
        exit 0
    }
    $appRoot = $application.root
    $running = $false
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'")) {
        if ([string]::IsNullOrWhiteSpace($process.ExecutablePath)) { throw 'Cannot identify a running Desktop process.' }
        if ([IO.Path]::GetFullPath($process.ExecutablePath).StartsWith($appRoot, [StringComparison]::OrdinalIgnoreCase)) { $running = $true }
    }
    if ($CheckOnly) {
        [ordered]@{action=$(if ($running) {'open_existing'} elseif ($nativeOnly) {'open_native'} else {'synchronize_then_open'}); configuration_changed=$false} | ConvertTo-Json -Compress
        exit 0
    }
    if (-not $running) {
        foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'")) {
            if ([string]::IsNullOrWhiteSpace($process.ExecutablePath)) { throw 'Cannot identify a running Desktop process.' }
            if ([IO.Path]::GetFullPath($process.ExecutablePath).StartsWith($appRoot, [StringComparison]::OrdinalIgnoreCase)) { $running = $true }
        }
    }
    if ($running -or $nativeOnly) {
        # Launch the user's interactive single-instance app to bring it back;
        # no sync, service restart, configuration edit or task is dispatched.
        Open-OperatorPackagedApplication $application
        Write-Output 'Opened the Codex application.'
        exit 0
    }
    $plan = Get-Content -LiteralPath (Join-Path $workflowBundle 'startup-sync-plan.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $startupName = 'start-codex-with-lmstudio.ps1'
    if ($plan.schema_version -eq 2) {
        if ($plan.startup_script -cne 'start-codex-with-web.ps1') { throw 'Unknown startup workflow.' }
        $startupName = $plan.startup_script
    } elseif ($null -ne $plan.schema_version -and $plan.schema_version -ne 1) { throw 'Unknown startup workflow version.' }
    $startup = Join-Path $workflowBundle $startupName
    if ((Get-FileHash -LiteralPath $startup -Algorithm SHA256).Hash.ToLowerInvariant() -cne $plan.entry_files.$startupName) {
        throw 'The reviewed startup workflow changed.'
    }
    & $startup *> $entryLog
    if ($LASTEXITCODE -ne 0) { throw 'The startup workflow stopped. No automatic retry was attempted.' }
    if ($startupName -ceq 'start-codex-with-web.ps1') {
        # The Web workflow prepares services only. Desktop still owns every task.
        Open-OperatorPackagedApplication $application
    }
    exit 0
} catch {
    $message = 'STOPPED: ' + $_.Exception.Message
    if ($entryLog) { $message | Add-Content -LiteralPath $entryLog -Encoding utf8 }
    Write-Output $message
    exit 1
} finally {
    if ($ownsMutex) { $entryMutex.ReleaseMutex() }
    if ($entryMutex) { $entryMutex.Dispose() }
}
