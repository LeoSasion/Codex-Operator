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
  codex-operator.ps1 models <router action> --state-dir <absolute private directory>
  codex-operator.ps1 uninstall [reviewed product-removal arguments]
Use -ProjectRoot to select the Codex project. Modules are configured independently.
Channels currently implements Feishu. Other IM adapters are not included yet.
'@ | Write-Output
    exit 0
}
$scope=$Module
if ($Module -eq 'models' -and $Action -eq 'web') {
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
