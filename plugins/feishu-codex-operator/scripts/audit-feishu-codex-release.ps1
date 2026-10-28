[CmdletBinding()]
param([ValidateSet('source','release')][string]$Scope = 'source')

$ErrorActionPreference = 'Stop'
$Scope = $Scope.ToLowerInvariant()
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

$configText = Get-Content -LiteralPath (Join-Path $pluginRoot 'scripts\operator_core\config.py') -Raw -Encoding utf8
if ($configText -notmatch 'OPERATOR_VERSION\s*=\s*["'']([^"'']+)["'']') {
    throw 'Operator source version is unreadable.'
}
if ([string]$inventory.source_version -cne [string]$Matches[1]) {
    throw 'Release inventory source_version does not match Operator source.'
}

$rootRules = Join-Path (Split-Path -Parent (Split-Path -Parent $pluginRoot)) 'AGENTS.md'
$mirrorRules = Join-Path $pluginRoot 'assets\AGENTS.feishu-codex-operator.md'
function Get-ReleaseManagedRulesBytes([string]$Path, [switch]$Mirror) {
    $raw = [IO.File]::ReadAllBytes($Path)
    $encoding = [Text.UTF8Encoding]::new($false, $true)
    $text = $encoding.GetString($raw)
    $start = '<!-- FEISHU_CODEX_OPERATOR_RULES_START -->'
    $end = '<!-- FEISHU_CODEX_OPERATOR_RULES_END -->'
    foreach ($marker in @($start, $end)) {
        if ([regex]::Matches($text, [regex]::Escape($marker)).Count -ne 1 -or
            [regex]::Matches($text, ('(?m)(?:^|\A\uFEFF)' + [regex]::Escape($marker) + '(?=\r?$)')).Count -ne 1) {
            throw 'Managed Operator rules require one complete marker pair on separate lines.'
        }
    }
    $first = $text.IndexOf($start, [StringComparison]::Ordinal)
    $last = $text.IndexOf($end, [StringComparison]::Ordinal)
    if ($last -le $first) { throw 'Managed Operator rule markers are reversed.' }
    if ($Mirror -and ($text.Substring(0, $first) -cnotmatch '\A(?:\uFEFF)?\s*\z' -or
            $text.Substring($last + $end.Length) -cnotmatch '\A\s*\z')) {
        throw 'Public Operator rules mirror cannot contain private surrounding content.'
    }
    $offset = $encoding.GetByteCount($text.Substring(0, $first))
    $length = $encoding.GetByteCount($text.Substring($first, $last + $end.Length - $first))
    $block = [byte[]]::new($length)
    [Array]::Copy($raw, $offset, $block, 0, $length)
    return ,$block
}
$rootBlock = Get-ReleaseManagedRulesBytes $rootRules
$mirrorBlock = Get-ReleaseManagedRulesBytes $mirrorRules -Mirror
if ([Convert]::ToBase64String($rootBlock) -cne [Convert]::ToBase64String($mirrorBlock)) {
    throw 'Managed root AGENTS rules and plugin mirror are not byte-identical.'
}

# Behavioral policy belongs in the unit suite, not source-wording regexes.
Import-Module (Join-Path $PSScriptRoot 'operator_python.psm1') -Force
$python = Get-OperatorPython -Required
$sourceValidation = @'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
from build_codex_operator_release import collect, safe_path

inventory = json.loads((root / 'assets/release-inventory.json').read_text(encoding='utf-8'))
scope = sys.argv[2]
collect(root.parent.parent, scope=scope)
selected = inventory['components'][0]['paths'] + (inventory['development_paths'] if scope == 'source' else [])
paths = [safe_path(p) for p in selected]
for path in (root / p for p in paths if p.suffix == '.py'):
    compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
'@
& $python.Source @($python.Prefix) -B -c $sourceValidation $pluginRoot $Scope
if ($LASTEXITCODE -ne 0) { throw 'Python syntax or reviewed source validation failed.' }

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
    scope = $Scope
    source_version = [string]$inventory.source_version
    inventory_files = $listed.Count
    development_files = $(if ($Scope -eq 'source') { @($inventory.development_paths).Count } else { 0 })
    reviewed_documents = @($inventory.reviewed_document_sha256.PSObject.Properties).Count
    content_screen = $true
    python_syntax = $true
    powershell_syntax = $true
}))
