#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('choose','native','extension','service-start','service-stop','package-launch','package-activate')][string]$Action='choose',
    [Parameter(Mandatory)][string]$Root,
    [string]$Attempt,
    [string]$Activation,
    [string]$PlanSha256,
    [switch]$Headless
)
$ErrorActionPreference='Stop'

function Get-ModePackage {
    $packages=@(Get-AppxPackage -Name OpenAI.Codex)
    if($packages.Count -ne 1){throw 'mode_package_ambiguous'}
    $package=$packages[0]
    [xml]$manifest=Get-Content -LiteralPath (Join-Path $package.InstallLocation 'AppxManifest.xml') -Raw
    $apps=@($manifest.Package.Applications.Application|Where-Object {$_.Id -ceq 'App'})
    if($manifest.Package.Identity.Name -cne 'OpenAI.Codex' -or $apps.Count -ne 1 -or
       $apps[0].Executable -cne 'app/ChatGPT.exe' -or $apps[0].EntryPoint -cne 'Windows.FullTrustApplication'){
        throw 'mode_package_changed'
    }
    return $package
}

function Get-ModeHash([string]$Path){
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

try {
    if(-not [IO.Path]::IsPathFullyQualified($Root) -or $Root -match '["\r\n]'){throw 'mode_root_invalid'}
    $Root=[IO.Path]::GetFullPath($Root)
    $entry=Get-Content -LiteralPath (Join-Path $Root 'entry.json') -Raw|ConvertFrom-Json
    if($entry.contract -cne 'operator_isolated_mode_entry_v1' -or $entry.root -cne $Root -or
       $entry.native_enabled -ne $false){throw 'mode_entry_invalid'}
    if((Get-ModeHash $PSCommandPath) -cne $entry.entry_sha256){throw 'mode_entry_script_changed'}
    $package=Get-ModePackage
    if($Action -eq 'choose'){
        $picker=Join-Path $Root 'operator-mode-picker.exe'
        if((Get-ModeHash $picker) -cne $entry.compiled.'operator-mode-picker.exe'){throw 'mode_picker_changed'}
        # Keep the user-clicked picker alive through extension preparation so it
        # owns the final foreground operation under ordinary Windows rules.
        $pickerArguments='--launch "'+$Root+'" '+(Get-ModeHash (Join-Path $Root 'entry.json'))
        $selection=Start-Process -FilePath $picker -ArgumentList $pickerArguments -PassThru
        # Start-Process -Wait tracks the entire descendant tree on Windows.
        # Background router/Desktop lifetime must not retain this entry lock.
        $selection.WaitForExit()
        if($selection.ExitCode -eq 0){exit 0}
        if($selection.ExitCode -eq 10){$Action='native'}
        elseif($selection.ExitCode -eq 20){$Action='extension'}
        else{throw 'mode_selection_failed'}
    }
    if($Action -eq 'native'){
        # Activate the registered application contract. Explorer may only focus
        # its most recent shell window when multiple package instances exist.
        $native=Join-Path $Root 'operator-mode-native.exe'
        if((Get-ModeHash $native) -cne $entry.compiled.'operator-mode-native.exe'){throw 'mode_native_launcher_changed'}
        $opened=Start-Process -FilePath $native -WindowStyle Hidden -Wait -PassThru -ArgumentList ($package.PackageFamilyName+'!App')
        if($opened.ExitCode -ne 0){throw 'mode_native_activation_failed'}
        exit 0
    }
    if($package.PackageFullName -cne $entry.package.full_name){throw 'mode_official_package_changed'}
    if($Action -in @('package-launch','package-activate')){
        if($Attempt -cnotmatch '\A[a-f0-9]{32}\z' -or $PlanSha256 -cnotmatch '\A[a-f0-9]{64}\z'){
            throw 'mode_launch_arguments_invalid'
        }
        $hostProgram=Join-Path $Root 'operator-mode-host.exe'
        if((Get-ModeHash $hostProgram) -cne $entry.compiled.'operator-mode-host.exe' -or
           (Get-ModeHash (Join-Path $Root 'host-plan.json')) -cne $PlanSha256){throw 'mode_launch_dependency_changed'}
        $hostAction=if($Action -eq 'package-activate'){'--activate'}else{'--launch'}
        $hostArguments=$hostAction+' "'+$Root+'" '+$PlanSha256+' '+$Attempt
        if($Action -eq 'package-activate'){
            if($Activation -cnotmatch '\A[a-f0-9]{32}\z'){throw 'mode_activation_invalid'}
            $hostArguments+=' '+$Activation
        }
        Invoke-CommandInDesktopPackage -PackageFamilyName $package.PackageFamilyName -AppId App -Command $hostProgram -Args $hostArguments -PreventBreakaway
        exit 0
    }
    $controller=Join-Path $entry.project 'plugins/feishu-codex-operator/scripts/operator_mode_entry.py'
    if((Get-ModeHash $controller) -cne $entry.source_bindings.'operator_mode_entry.py' -or
       (Get-ModeHash $entry.python) -cne $entry.python_sha256){throw 'mode_controller_changed'}
    $priorSecrets=@{}
    try {
        if($entry.credentials -and $Action -ne 'service-stop'){
            $saved=$entry.credentials
            if($saved.storage -cne 'windows_current_user_clixml' -or
               (Get-ModeHash $saved.path) -cne $saved.sha256){throw 'mode_credentials_changed'}
            $items=Import-Clixml -LiteralPath $saved.path
            foreach($name in $saved.environment_names){
                if($name -cnotmatch '\A[A-Z][A-Z0-9_]*_(?:API_KEY|API_TOKEN|AUTH_TOKEN)\z' -or
                   $items[$name] -isnot [Security.SecureString]){throw 'mode_credential_environment_invalid'}
                $priorSecrets[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
                $plain=[Net.NetworkCredential]::new('', $items[$name]).Password
                if([string]::IsNullOrEmpty($plain)){throw 'mode_credential_unavailable'}
                [Environment]::SetEnvironmentVariable($name,$plain,'Process')
                $plain=$null
            }
        }
        $controllerAction=if($Action -in @('service-start','service-stop')){$Action}else{'launch'}
        & $entry.python -B $controller $controllerAction --root $Root
        if($LASTEXITCODE -ne 0){throw 'mode_extension_launch_incomplete'}
    } finally {
        foreach($name in $priorSecrets.Keys){[Environment]::SetEnvironmentVariable($name,$priorSecrets[$name],'Process')}
    }
} catch {
    $reason=$_.Exception.Message
    if($reason -cnotmatch '\Amode_[a-z_]+\z'){$reason='mode_entry_failed'}
    # The visible picker/EXE owns error UI. A MessageBox in this hidden
    # PowerShell process can be invisible while retaining the entry mutex.
    [Console]::Error.WriteLine($reason)
    exit 1
}
