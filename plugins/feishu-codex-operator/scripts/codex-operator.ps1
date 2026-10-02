#requires -Version 7.0
[CmdletBinding(PositionalBinding=$false)]
param(
    [Parameter(Position=0)][ValidateSet('status','channels','models','uninstall','help')][string]$Module='status',
    [Parameter(Position=1)][string]$Action='status',
    [string]$ProjectRoot=(Get-Location).Path,
    [switch]$Json,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ModuleArguments
)
$ErrorActionPreference='Stop'
$ModuleArguments=@($ModuleArguments | Where-Object { $null -ne $_ })
# Installed copies use the exact source entry recorded during installation. The
# runtime is not a second plugin tree and must not guess an entry from PATH/cwd.
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'feishu-codex-operator.ps1') -PathType Leaf)) {
    try {
        $manifestPath=Join-Path $PSScriptRoot 'runtime-manifest.json'
        $manifestInfo=Get-Item -LiteralPath $manifestPath -ErrorAction Stop
        if ($manifestInfo.Length -gt 1048576 -or $manifestInfo.PSIsContainer) { throw 'Invalid manifest.' }
        $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
        $entry=$manifest.public_entry
        if ($manifest.schema_version -ne 1 -or $null -eq $entry -or
            $entry.path -isnot [string] -or $entry.sha256 -isnot [string] -or
            $entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            -not [IO.Path]::IsPathFullyQualified($entry.path)) { throw 'Invalid entry record.' }
        $target=[IO.Path]::GetFullPath($entry.path)
        if ([IO.Path]::GetFileName($target) -cne 'codex-operator.ps1' -or
            $target -ieq $PSCommandPath) { throw 'Invalid entry target.' }
        foreach ($path in @($manifestPath,$target)) {
            $cursor=$path
            while ($cursor) {
                if ((Get-Item -LiteralPath $cursor -Force -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw 'Linked entry path.'
                }
                $cursor=[IO.Path]::GetDirectoryName($cursor)
            }
        }
        $targetInfo=Get-Item -LiteralPath $target -ErrorAction Stop
        if ($targetInfo.PSIsContainer -or $targetInfo.Length -gt 2097152 -or
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256 -or
            -not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $target) 'feishu-codex-operator.ps1') -PathType Leaf)) {
            throw 'Saved source entry changed.'
        }
    } catch {
        throw 'Operator entry is unavailable or changed. Use the plugin source entry to review and upgrade this stopped installation; existing settings were preserved.'
    }
    & $target @PSBoundParameters
    exit $LASTEXITCODE
}
if ($Module -eq 'status' -and ($Action -ne 'status' -or @($ModuleArguments).Count -gt 0)) {
    throw 'Use status [-Json] without a subcommand or extra arguments.'
}
if ($Module -eq 'help') {
    @'
Codex-Operator · Windows preview
  codex-operator.ps1 status [-Json]
  codex-operator.ps1 channels init|install|start|stop|readiness
  codex-operator.ps1 channels cli-install|configure|login
  codex-operator.ps1 channels user-tasks-configure -GrantFile <saved owner grant>
  codex-operator.ps1 channels user-tasks-status|user-tasks-revoke
  codex-operator.ps1 models web configure|start|status|assist|inspect|stop
  codex-operator.ps1 models web desktop-prepare|desktop-connect|desktop-rebind|desktop-status|desktop-check|desktop-disconnect
  codex-operator.ps1 models native prepare|install|status|restore --state <private directory> --home <Codex home>
  codex-operator.ps1 models mode-entry prepare|status|refresh-preview|refresh --root <isolated directory> [reviewed arguments]
  codex-operator.ps1 models mode-maintenance <focus-preview|focus-review|startup-preview|startup-review|service-stop|pair-prepare|pair-preview|pair-apply|retire-pair-preview|retire-pair> --root <isolated directory> [reviewed arguments]
  codex-operator.ps1 models desktop-pair preview|install|status|restore [-CodexHome <native home>]
  codex-operator.ps1 models desktop-pair prepare-build|preview-upgrade|upgrade [-CandidateDirectory <prepared build>] [-ExpectedPlanSha256 <preview digest>]
  codex-operator.ps1 models unified-retire preview|retire|status|archive-preview|archive --plan <saved plan> [reviewed arguments]
  codex-operator.ps1 models unified-failed preview|archive|status --plan <saved plan> [exact failed-handoff evidence]
  codex-operator.ps1 models unified-withdraw preview|withdraw|status --plan <unused prepared plan> [--expected-review-sha256 <digest>]
  codex-operator.ps1 models unified-withdraw preview-empty|withdraw-empty --project-root <project> --codex-home <home> --failure-evidence <failed prepare JSON> --expected-failure-sha256 <digest> [--expected-review-sha256 <digest>]
  codex-operator.ps1 models <router action> --state-dir <absolute private directory>
  codex-operator.ps1 uninstall [reviewed product-removal arguments]
Use -ProjectRoot to select the Codex project. Modules are configured independently.
Channels currently implements Feishu. Other IM adapters are not included yet.
'@ | Write-Output
    exit 0
}
$scope=$Module
if ($Module -eq 'models' -and $Action -eq 'desktop-pair') {
    $pairAction = 'status'
    if (@($ModuleArguments).Count -gt 0) {
        $pairAction = $ModuleArguments[0]
        $ModuleArguments = @($ModuleArguments | Select-Object -Skip 1)
    }
    $pairActions = @{preview='preview-pair';install='install-pair';status='pair-status';restore='restore-pair';
        'prepare-build'='prepare-pair-build';'preview-upgrade'='preview-pair-upgrade';upgrade='upgrade-pair'}
    if (-not $pairActions.ContainsKey($pairAction)) { throw 'Use models desktop-pair preview, install, status, restore, prepare-build, preview-upgrade or upgrade.' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'operator_desktop_setup.ps1') `
        -Action $pairActions[$pairAction] -ProjectRoot $ProjectRoot @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'mode-entry') {
    if (@($ModuleArguments).Count -eq 0 -or $ModuleArguments[0] -notin @('prepare','status','refresh-preview','refresh')) {
        throw 'Use models mode-entry prepare, status, refresh-preview or refresh. Open the prepared or installed entry to launch.'
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_mode_entry.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'mode-maintenance') {
    if (@($ModuleArguments).Count -eq 0 -or $ModuleArguments[0] -notin @('focus-preview','focus-review','startup-preview','startup-review','service-stop','pair-prepare','pair-preview','pair-apply','retire-pair-preview','retire-pair')) {
        throw 'Use models mode-maintenance with one explicit reviewed maintenance action.'
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_mode_maintenance.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'native') {
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_native_models.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'unified-withdraw') {
    if (@($ModuleArguments).Count -eq 0 -or $ModuleArguments[0] -notin @('preview','withdraw','status','preview-empty','withdraw-empty')) {
        throw 'Use models unified-withdraw preview, withdraw, status, preview-empty or withdraw-empty for the exact reviewed scope.'
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -DisableNameChecking
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_unified_withdraw.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'unified-failed') {
    if (@($ModuleArguments).Count -eq 0 -or $ModuleArguments[0] -notin @('preview','archive','status')) {
        throw 'Use models unified-failed preview, archive or status with the exact failed plan and evidence.'
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $selectedPython=''
    $pythonFlag=[Array]::IndexOf([string[]]$ModuleArguments, '--python')
    if ($pythonFlag -ge 0 -and $pythonFlag + 1 -lt @($ModuleArguments).Count) {
        $selectedPython=[string]$ModuleArguments[$pythonFlag + 1]
    }
    $python=Get-OperatorPython -Required -PreferredExecutable $selectedPython
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_unified_failed_archive.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'unified-retire') {
    if (@($ModuleArguments).Count -eq 0 -or $ModuleArguments[0] -notin @('preview','retire','status','archive-preview','archive')) {
        throw 'Use models unified-retire preview, retire, status, archive-preview or archive with its exact saved plan.'
    }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_unified_retire.py') @ModuleArguments
    exit $LASTEXITCODE
} elseif ($Module -eq 'models' -and $Action -eq 'web') {
    $scope='web'
    $Action='status'
    if (@($ModuleArguments).Count -gt 0) {
        $Action=$ModuleArguments[0]
        $ModuleArguments=@($ModuleArguments | Select-Object -Skip 1)
    }
} elseif ($Module -eq 'models') {
    if ($Json) { throw 'Models commands select their own output format.' }
    Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
    $python=Get-OperatorPython -Required
    & $python.Source @($python.Prefix) -X utf8 -E -s -B (Join-Path $PSScriptRoot 'operator_model_router.py') $Action @ModuleArguments
    exit $LASTEXITCODE
}
if ($Module -eq 'status') { $scope='product'; $Action='status' }
if ($Module -eq 'uninstall') {
    if ($Action -ne 'status') { throw 'Use uninstall with the reviewed removal arguments; it removes the whole product.' }
    $scope='operator'; $Action='uninstall'
}
if ($Module -eq 'channels') {
    if ($Action -eq 'uninstall') { throw 'Uninstall removes the whole product. Use codex-operator.ps1 uninstall; use channels stop to stop only the channel.' }
    if ($Action -in @('cli-install','configure','login','desktop-status','desktop-install')) {
        $scope='feishu'
        if ($Action -eq 'cli-install') { $Action='install' }
    } else { $scope='operator' }
}
$arguments=@('-NoLogo','-NoProfile','-NonInteractive','-File',
    (Join-Path $PSScriptRoot 'feishu-codex-operator.ps1'),$scope,$Action,'-ProjectRoot',$ProjectRoot)
if ($Json) { $arguments+='-Json' }
$arguments+=@($ModuleArguments)
& (Join-Path $PSHOME 'pwsh.exe') @arguments
exit $LASTEXITCODE
