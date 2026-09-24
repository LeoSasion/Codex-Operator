#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Action,
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [string]$Settings,
    [string]$PythonExecutable,
    [switch]$ReplaceClosedBrowser,
    [int]$DrainSeconds = 0,
    [string]$RecoveryDigest,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
$entryStage = 'request'
$entryReason = 'web_entry_invalid_request'
$profileState = 'unknown'
$reuseSavedSettings = $false

function Write-WebEntryResult($Result) {
    if ($Json) { $Result | ConvertTo-Json -Depth 8 -Compress -EscapeHandling EscapeNonAscii }
    else { Write-Output $Result.summary }
}

function Get-WebEntryItem([string]$Path) {
    # Test-Path can hide a denied read as absence. Only actual absence allows setup.
    try { Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { return $null }
}

function Test-WebEntryAccessDenied($Record) {
    if ($Record.CategoryInfo.Category -in @('PermissionDenied','SecurityError')) { return $true }
    $exception = $Record.Exception
    for ($depth = 0; $null -ne $exception -and $depth -lt 8; $depth++) {
        if ($exception -is [UnauthorizedAccessException] -or $exception -is [System.Security.SecurityException]) {
            return $true
        }
        $exception = $exception.InnerException
    }
    return $false
}

try {
    if ($Action -cnotin @('configure','start','status','assist','inspect','stop','recover','verify',
            'desktop-prepare','desktop-connect','desktop-rebind','desktop-disconnect','desktop-status','desktop-check') -or
        ($Settings -and $Action -cne 'configure') -or
        ($PythonExecutable -and $Action -cne 'configure') -or
        ($ReplaceClosedBrowser -and $Action -cne 'assist') -or
        ($RecoveryDigest -and ($Action -cne 'recover' -or $RecoveryDigest -cnotmatch '^[a-f0-9]{64}$')) -or
        $DrainSeconds -lt 0 -or $DrainSeconds -gt 30 -or
        ($DrainSeconds -ne 0 -and $Action -cne 'stop')) { throw 'Invalid operation.' }
    $entryStage = 'project'
    $entryReason = 'web_entry_project_unavailable'
    Import-Module (Join-Path $PSScriptRoot 'operator_installation.psm1') -Force -DisableNameChecking
    if (-not [IO.Path]::IsPathFullyQualified($ProjectRoot)) { throw 'Absolute project required.' }
    $project = [IO.Path]::GetFullPath($ProjectRoot)
    Assert-OperatorPlainPath $project
    if (-not (Test-Path -LiteralPath $project -PathType Container)) { throw 'Project unavailable.' }
    $profile = Join-Path $project '.codex/operator-web-service'
    $profileFile = Join-Path $profile 'profile.json'
    $entryStage = 'profile'
    $entryReason = 'web_entry_profile_unreadable'
    Assert-OperatorPlainPath $profileFile
    $saved = $null
    $profileItem = Get-WebEntryItem $profileFile
    $profileState = if ($null -eq $profileItem) { 'absent' } else { 'present' }
    if ($null -ne $profileItem) {
        $entryReason = 'web_entry_profile_invalid'
        if ($profileItem.PSIsContainer -or $profileItem.Length -gt 65536) { throw 'Profile bound exceeded.' }
        $saved = Get-Content -LiteralPath $profileFile -Raw -Encoding utf8 | ConvertFrom-Json
        if ($null -eq $saved -or $saved.version -ne 1 -or
            $saved.runtime.source_root -isnot [string] -or $saved.runtime.backend -isnot [string] -or
            -not [IO.Path]::IsPathFullyQualified($saved.runtime.source_root) -or
            -not [IO.Path]::IsPathFullyQualified($saved.runtime.backend)) { throw 'Invalid profile.' }
        $entryStage = 'runtime'
        $entryReason = 'web_entry_runtime_mismatch'
        if (
            [IO.Path]::GetFullPath([string]$saved.runtime.source_root) -ine [IO.Path]::GetFullPath($PSScriptRoot) -or
            [IO.Path]::GetFullPath([string]$saved.runtime.backend) -ine (Join-Path $PSScriptRoot 'operator_web_model.py')) {
            throw 'Profile belongs to another runtime.'
        }
    } elseif ($Action -cne 'configure') {
        Write-WebEntryResult ([ordered]@{status='not_configured'; profile_state='absent';
            summary='尚未保存 Web 后台配置；由助手接入已有连接后即可使用，无需先启动服务。'})
        if ($Action -cin @('status','desktop-status')) { exit 0 } else { exit 2 }
    }
    $entryStage = 'settings'
    $entryReason = 'web_entry_settings_required'
    if ($Action -ceq 'configure' -and -not $Settings -and $null -ne $saved) {
        # A parameter-free configure only verifies this saved reference. Updating a
        # changed generation still needs an explicit settings selection and lifecycle check.
        $entryReason = 'web_entry_settings_unavailable'
        if ($saved.settings.path -isnot [string] -or
            -not [IO.Path]::IsPathFullyQualified($saved.settings.path)) { throw 'Saved settings unavailable.' }
        $Settings = $saved.settings.path
        $reuseSavedSettings = $true
    }
    if ($Action -ceq 'configure' -and -not $Settings) { throw 'Existing settings required.' }
    $entryStage = 'python'
    $entryReason = 'web_entry_python_unavailable'
    $python = if ($PythonExecutable) { $PythonExecutable } elseif ($saved) { [string]$saved.runtime.python } else { $null }
    if (-not $python -or -not [IO.Path]::IsPathFullyQualified($python)) { throw 'Explicit Python required.' }
    Assert-OperatorPlainPath $python
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python unavailable.' }
    $entryReason = 'web_entry_python_changed'
    if (-not $PythonExecutable -and ((Get-OperatorFingerprint $python) -cne [string]$saved.runtime.python_sha256)) {
        throw 'Saved Python changed.'
    }
    if (-not $PythonExecutable) {
        $entryStage = 'worker'
        $entryReason = 'web_entry_worker_changed'
        $worker = [string]$saved.runtime.worker_python
        if (-not [IO.Path]::IsPathFullyQualified($worker) -or
            (Get-OperatorFingerprint $worker) -cne [string]$saved.runtime.worker_python_sha256) {
            throw 'Saved Python worker changed.'
        }
    }
    $entryStage = 'manager'
    $entryReason = 'web_entry_manager_unavailable'
    $manager = Join-Path $PSScriptRoot $(if ($Action -ceq 'verify') {'operator_web_acceptance.py'}
        elseif ($Action.StartsWith('desktop-')) {'operator_web_desktop.py'} else {'operator_web_service.py'})
    Assert-OperatorPlainPath $manager
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { throw 'Manager unavailable.' }
    $managerAction = if ($reuseSavedSettings) { 'status' } else { $Action }
    $arguments = @('-X','utf8','-E','-s','-B',$manager,$managerAction,'--profile',$profile)
    if ($Settings) {
        $entryStage = 'settings'
        $entryReason = 'web_entry_settings_unavailable'
        if (-not [IO.Path]::IsPathFullyQualified($Settings)) { throw 'Absolute settings required.' }
        Assert-OperatorPlainPath $Settings
        if (-not (Test-Path -LiteralPath $Settings -PathType Leaf)) { throw 'Settings unavailable.' }
        if ($reuseSavedSettings) {
            $entryReason = 'web_entry_settings_changed'
            if ($saved.settings.sha256 -isnot [string] -or $saved.settings.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
                (Get-OperatorFingerprint $Settings) -cne $saved.settings.sha256) { throw 'Saved settings changed.' }
        }
        if (-not $reuseSavedSettings) {
            $arguments += @('--settings',$Settings)
            New-Item -ItemType Directory -Path (Split-Path -Parent $profile) -Force | Out-Null
        }
    }
    if ($ReplaceClosedBrowser) { $arguments += '--replace-closed-browser' }
    if ($Action -ceq 'stop') { $arguments += @('--drain-seconds',[string]$DrainSeconds) }
    if ($RecoveryDigest) { $arguments += @('--expected-preview',$RecoveryDigest) }
    # The manager emits fixed, secret-free results. Never echo Python exceptions,
    # private session files, credentials, or the invocation arguments.
    $entryStage = 'manager'
    $entryReason = 'web_entry_manager_launch_failed'
    $output = (& $python @arguments 2>$null | Out-String)
    $resultCode = $LASTEXITCODE
    $entryStage = 'result'
    $entryReason = 'web_entry_manager_result_invalid'
    if ($output.Length -gt 16384) { throw 'Result bound exceeded.' }
    $result = $output | ConvertFrom-Json
    if (-not ($result.status -is [string]) -or -not ($result.summary -is [string])) { throw 'Invalid manager result.' }
    if ($reuseSavedSettings -and $resultCode -eq 0) {
        $entryReason = 'web_entry_reuse_unverified'
        if ($result.configuration_current -isnot [bool] -or -not $result.configuration_current -or
            $result.status -cnotin @('ready','assistance','starting','connection','reconnecting','draining','configured','stopped')) {
            throw 'Saved configuration reuse unverified.'
        }
        $result = [ordered]@{status='configured'; reused=$true; configuration_current=$true;
            summary='已核对并沿用保存的入口，无需重复填写设置、运行程序、连接或密钥；未启动或重配后台。'}
    }
    Write-WebEntryResult $result
    exit $resultCode
} catch {
    if (Test-WebEntryAccessDenied $_) { $entryReason = 'web_entry_access_denied' }
    $summary = switch ($entryReason) {
        'web_entry_access_denied' { '当前检查环境没有读取入口所需文件的权限；由助手核对访问范围，现有登录与连接保留，无需重新配置。' }
        'web_entry_invalid_request' { '入口参数不适用于本次操作；由助手修正调用，未重新配置或启动后台。' }
        'web_entry_profile_invalid' { '已找到保存的入口，但登记格式无法验证；由助手核对原登记，无需重新登录或创建连接。' }
        'web_entry_runtime_mismatch' { '已找到保存的入口，但它属于另一份程序；由助手核对原程序位置，未切换后台或覆盖登记。' }
        'web_entry_python_changed' { '保存的运行程序已变化；由助手核对版本和原登记，现有登录与固定连接保留。' }
        'web_entry_worker_changed' { '保存的后台运行程序已变化或不可用；由助手核对原登记，现有登录与固定连接保留。' }
        'web_entry_python_unavailable' { '保存的运行程序暂时不可用；由助手核对原位置，未寻找替代程序或重新配置连接。' }
        'web_entry_settings_required' { '首次保存入口需要已有连接设置；由助手接入该设置，不需要重新创建连接或密钥。' }
        'web_entry_settings_changed' { '原设置文件内容已变化，暂未采用新内容；由助手核对后明确选择设置，原登记与固定连接保留。' }
        'web_entry_reuse_unverified' { '暂时无法确认原入口可直接复用；由助手核对保存登记，未更新配置、启动后台或要求重新登录。' }
        'web_entry_manager_result_invalid' { '后台检查未返回可验证结果；由助手检查管理程序及依赖，现有配置保留，未自动重试。' }
        default { '当前步骤暂时无法检查；由助手核对管理入口，现有配置保留，无需重新登录或创建连接。' }
    }
    Write-WebEntryResult ([ordered]@{status='unavailable'; code='web_entry_unavailable';
        reason=$entryReason; stage=$entryStage; profile_state=$profileState; summary=$summary})
    exit 1
}
