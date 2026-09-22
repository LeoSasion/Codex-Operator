[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$inventoryPath = Join-Path $pluginRoot 'assets\release-inventory.json'
$inventory = Get-Content -LiteralPath $inventoryPath -Raw -Encoding utf8 |
    ConvertFrom-Json -ErrorAction Stop

if ([int]$inventory.schema_version -ne 1 -or
    [string]$inventory.release_name -cne 'feishu-codex-operator-plugin') {
    throw 'Release inventory identity is invalid.'
}
$desktop = @($inventory.components | Where-Object {
    [string]$_.name -ceq 'desktop_operator' -and [string]$_.root_role -ceq 'plugin_root'
})
if ($desktop.Count -ne 1) {
    throw 'Release inventory must contain one desktop_operator component.'
}

[string[]]$listed = @(
    $desktop[0].paths |
        ForEach-Object { ([string]$_).Replace('\', '/') } |
        Sort-Object -Unique
)
if ($listed.Count -ne @($desktop[0].paths).Count) {
    throw 'Release inventory contains duplicate paths.'
}
foreach ($relative in $listed) {
    if ($relative -match '(^|/)(\.\.?|_quarantine)(/|$)' -or
        [System.IO.Path]::IsPathRooted($relative)) {
        throw "Release inventory contains an unsafe path: $relative"
    }
    $path = Join-Path $pluginRoot ($relative.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Release inventory path is missing: $relative"
    }
}

function Get-ReleaseSourceFiles([string]$Directory) {
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
        if ($item.PSIsContainer -and ($item.Name -in @('_quarantine','__pycache__') -or
            ($item.Name -eq '.tmp' -and (Split-Path -Leaf $Directory) -eq 'tests'))) { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Release source contains a linked path.'
        }
        if ($item.PSIsContainer) { Get-ReleaseSourceFiles $item.FullName } else { $item }
    }
}

[string[]]$actual = @(
    Get-ReleaseSourceFiles $pluginRoot |
        ForEach-Object {
            $_.FullName.Substring($pluginRoot.Length).TrimStart('\', '/').Replace('\', '/')
        } |
        Sort-Object -Unique
)
$missingFromInventory = @($actual | Where-Object { $_ -notin $listed })
if ($missingFromInventory.Count -gt 0) {
    throw "Release inventory omits source files: $($missingFromInventory -join ', ')"
}

$configText = Get-Content -LiteralPath (Join-Path $pluginRoot 'scripts\operator_core\config.py') -Raw -Encoding utf8
if ($configText -notmatch 'OPERATOR_VERSION\s*=\s*["'']([^"'']+)["'']') {
    throw 'Operator source version is unreadable.'
}
if ([string]$inventory.source_version -cne [string]$Matches[1]) {
    throw 'Release inventory source_version does not match Operator source.'
}

$rootRules = Join-Path (Split-Path -Parent (Split-Path -Parent $pluginRoot)) 'AGENTS.md'
$mirrorRules = Join-Path $pluginRoot 'assets\AGENTS.feishu-codex-operator.md'
if (-not (Test-Path -LiteralPath $rootRules -PathType Leaf) -or
    (Get-FileHash -LiteralPath $rootRules -Algorithm SHA256).Hash -cne
    (Get-FileHash -LiteralPath $mirrorRules -Algorithm SHA256).Hash) {
    throw 'Root AGENTS rules and plugin mirror are not byte-identical.'
}

# Behavioral policy belongs in the unit suite, not source-wording regexes.
$python = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1
& $python.Source -B -c "import json,pathlib,sys; root=pathlib.Path(sys.argv[1]); sys.path.insert(0,str(root/'scripts')); from build_codex_operator_release import safe_path; inventory=json.loads((root/'assets/release-inventory.json').read_text(encoding='utf-8')); paths=[safe_path(p) for c in inventory['components'] for p in c['paths']]; files=[root/p for p in paths if p.suffix=='.py']; [compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec') for p in files]" $pluginRoot
if ($LASTEXITCODE -ne 0) { throw 'Python syntax validation failed.' }

foreach ($script in Get-ChildItem -LiteralPath (Join-Path $pluginRoot 'scripts') -File | Where-Object Extension -in @('.ps1','.psm1')) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $script.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    if (@($errors).Count -gt 0) {
        throw "PowerShell parse failed: $($script.Name)"
    }
}

Write-Output (ConvertTo-Json -Compress -InputObject ([ordered]@{
    schema_version = 1
    status = 'passed'
    source_version = [string]$inventory.source_version
    inventory_files = $listed.Count
    python_syntax = $true
    powershell_syntax = $true
}))
