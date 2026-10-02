#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$CodexHome,
    [string]$ProjectRoot,
    [switch]$Apply,
    [switch]$Json,
    [switch]$Library
)

# This escape hatch deliberately imports neither the runtime nor Python.
$ErrorActionPreference = 'Stop'
$script:RecoveryUtf8 = New-Object Text.UTF8Encoding($false, $true)
$script:NativeRouteMarker = 'operator-native-route-only'
$script:RecoverySourcePath = $PSCommandPath
if (-not $Library) { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) }

function Assert-RecoveryPlainPath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'linked_path'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}

function Read-RecoveryBytes([string]$Path, [int]$Limit = 1048576) {
    Assert-RecoveryPlainPath $Path
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'not_regular_file' }
    if (-not ('OperatorRecoveryFile' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OperatorRecoveryFile {
    [StructLayout(LayoutKind.Sequential)]
    private struct Info {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    public static byte[] Read(string path, int limit) {
        using (var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            Info i;
            if (!GetFileInformationByHandle(f.SafeFileHandle, out i)) throw new IOException("file_identity_unavailable");
            if (i.Links != 1) throw new IOException("linked_path");
            if (f.Length > limit) throw new IOException("file_too_large");
            using (var r = new BinaryReader(f)) {
                byte[] data = r.ReadBytes(limit + 1);
                if (data.Length > limit) throw new IOException("file_too_large");
                return data;
            }
        }
    }
}
'@
    }
    return ,([OperatorRecoveryFile]::Read($Path, $Limit))
}

function Get-RecoveryHash([AllowNull()][byte[]]$Bytes) {
    if ($null -eq $Bytes) { return 'absent' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Assert-RecoveryKeys($Value, [string[]]$Keys) {
    if ($null -eq $Value -or $Value -isnot [Collections.IDictionary] -or
        @($Value.Keys).Count -ne $Keys.Count -or @($Value.Keys | Where-Object { $_ -cnotin $Keys }).Count) {
        throw 'direct_record_invalid'
    }
}

function ConvertFrom-RecoveryJson([byte[]]$Bytes) {
    try {
        # PS 5.1 lacks -AsHashtable. Recursively retain the bounded JSON shape.
        function Convert-RecoveryObject($Value) {
            if ($Value -is [Management.Automation.PSCustomObject]) {
                $result=@{}; foreach ($property in $Value.PSObject.Properties) {$result[$property.Name]=Convert-RecoveryObject $property.Value};return $result
            }
            if ($Value -is [Collections.IList]) {return ,@($Value | ForEach-Object {Convert-RecoveryObject $_})}
            return $Value
        }
        return Convert-RecoveryObject ($script:RecoveryUtf8.GetString($Bytes) | ConvertFrom-Json)
    } catch {throw 'direct_record_invalid'}
}

function ConvertFrom-RecoveryHex($Value) {
    if ($Value -isnot [string] -or $Value.Length -gt 2097152 -or $Value -cnotmatch '^(?:[a-f0-9]{2})*$') {throw 'direct_record_invalid'}
    $result=New-Object byte[] ($Value.Length/2)
    for ($index=0;$index -lt $result.Length;$index++) {$result[$index]=[Convert]::ToByte($Value.Substring($index*2,2),16)}
    return ,$result
}

function Test-RecoveryAbsolutePath($Value) {
    if ($Value -isnot [string] -or -not [IO.Path]::IsPathRooted($Value)) {return $false}
    try {return [IO.Path]::GetFullPath($Value).TrimEnd('\') -ieq $Value.TrimEnd('\')} catch {return $false}
}

function Get-RecoveryDirectProjection([byte[]]$Current, [byte[]]$Candidate, [byte[]]$Original, $Projection, $Manifest, [string]$HomePath) {
    $keys=@('version','contract','before_sha256','candidate_sha256','leading_hex','prefix_hex','suffix_hex','saved','settings','provider_id','provider','profile','efforts')
    $variable=$Projection.version -eq 2 -and $Projection.contract -ceq 'direct_profile_projection_v2'
    if ($variable) {$keys+='selector_mutation'}
    Assert-RecoveryKeys $Projection $keys
    if ((-not $variable -and ($Projection.version -ne 1 -or $Projection.contract -cne 'direct_profile_projection_v1')) -or
        $Projection.before_sha256 -cne (Get-RecoveryHash $Original) -or $Projection.candidate_sha256 -cne (Get-RecoveryHash $Candidate)) {throw 'direct_record_invalid'}
    Assert-RecoveryKeys $Manifest @('version','contract','kind','profile','provider','model','web_search')
    Assert-RecoveryKeys $Manifest.provider @('name','base_url','env_key')
    Assert-RecoveryKeys $Manifest.model @('id','display_name','context_window','reasoning_efforts','default_reasoning_effort','input_modalities','tool_mode','supports_search_tool')
    if ($Manifest.version -ne 1 -or $Manifest.contract -cne 'native_responses_v1' -or $Manifest.kind -cnotin @('api','local') -or
        $Manifest.profile -cnotmatch '^operator-[a-z0-9][a-z0-9-]{0,49}$' -or $Projection.profile -cne $Manifest.profile -or
        $Manifest.web_search -cnotin @('disabled','cached','live')) {throw 'direct_record_invalid'}
    $providerId='operator_native_'+$Manifest.profile.Substring(9).Replace('-','_')
    if ($Projection.provider_id -cne $providerId) {throw 'direct_record_invalid'}
    $efforts=@($Manifest.model.reasoning_efforts)
    if (-not $efforts.Count -or $efforts.Count -gt 7 -or @($efforts | Select-Object -Unique).Count -ne $efforts.Count -or
        @($efforts | Where-Object {$_ -isnot [string] -or $_ -cnotin @('none','minimal','low','medium','high','xhigh','max')}).Count -or
        $Manifest.model.default_reasoning_effort -cnotin $efforts -or @($Projection.efforts).Count -ne $efforts.Count) {throw 'direct_record_invalid'}
    for ($index=0;$index -lt $efforts.Count;$index++) {if ($Projection.efforts[$index] -cne $efforts[$index]) {throw 'direct_record_invalid'}}
    if ($variable) {
        Assert-RecoveryKeys $Projection.selector_mutation @('contract','model','efforts')
        if ($Projection.selector_mutation.contract -cne 'model_effort_v1' -or $Projection.selector_mutation.model -cne $Manifest.model.id -or
            @($Projection.selector_mutation.efforts).Count -ne $efforts.Count) {throw 'direct_record_invalid'}
        for ($index=0;$index -lt $efforts.Count;$index++) {if ($Projection.selector_mutation.efforts[$index] -cne $efforts[$index]) {throw 'direct_record_invalid'}}
    }
    $selectorKeys=@('model','model_provider','model_catalog_json','model_reasoning_effort','web_search')
    Assert-RecoveryKeys $Projection.settings $selectorKeys
    if ($Projection.settings.model -cne $Manifest.model.id -or $Projection.settings.model_provider -cne $providerId -or
        $Projection.settings.model_catalog_json -cne (Join-Path $HomePath ($Manifest.profile+'.catalog.json')) -or
        $Projection.settings.model_reasoning_effort -cne $Manifest.model.default_reasoning_effort -or $Projection.settings.web_search -cne $Manifest.web_search) {throw 'direct_record_invalid'}
    $providerKeys=@('name','base_url','wire_api','requires_openai_auth','request_max_retries','stream_max_retries','supports_websockets')
    if ($Manifest.provider.env_key) {$providerKeys+='env_key'}
    Assert-RecoveryKeys $Projection.provider $providerKeys
    if ($Projection.provider.name -cne $Manifest.provider.name -or $Projection.provider.base_url -cne $Manifest.provider.base_url -or
        $Projection.provider.wire_api -cne 'responses' -or $Projection.provider.requires_openai_auth -isnot [bool] -or $Projection.provider.requires_openai_auth -or
        $Projection.provider.request_max_retries -ne 0 -or $Projection.provider.stream_max_retries -ne 0 -or
        $Projection.provider.supports_websockets -isnot [bool] -or $Projection.provider.supports_websockets -or
        ($Manifest.provider.env_key -and ($Manifest.provider.env_key -cnotmatch '^[A-Z][A-Z0-9_]{0,100}$' -or $Projection.provider.env_key -cne $Manifest.provider.env_key))) {throw 'direct_record_invalid'}
    $endpoint=$null
    if (-not [Uri]::TryCreate($Manifest.provider.base_url,[UriKind]::Absolute,[ref]$endpoint) -or $endpoint.UserInfo -or $endpoint.Query -or $endpoint.Fragment -or
        ($Manifest.kind -ceq 'api' -and $endpoint.Scheme -cne 'https') -or
        ($Manifest.kind -ceq 'local' -and $endpoint.Host -cnotin @('127.0.0.1','[::1]','::1'))) {throw 'direct_record_invalid'}
    $lead=$script:RecoveryUtf8.GetString((ConvertFrom-RecoveryHex $Projection.leading_hex))
    $prefix=$script:RecoveryUtf8.GetString((ConvertFrom-RecoveryHex $Projection.prefix_hex))
    $suffix=$script:RecoveryUtf8.GetString((ConvertFrom-RecoveryHex $Projection.suffix_hex))
    if (-not [regex]::IsMatch($lead,'\A\uFEFF?(?:# BEGIN FEISHU OPERATOR MODEL ROUTER\r?\n# [ \t]*openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:(?<port>[0-9]{1,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n# END FEISHU OPERATOR MODEL ROUTER\r?\n)?\z')) {throw 'direct_record_invalid'}
    $leadPort=[regex]::Match($lead,':(?<port>[0-9]{1,5})/')
    if ($leadPort.Success -and ([int]$leadPort.Groups['port'].Value -lt 1 -or [int]$leadPort.Groups['port'].Value -gt 65535)) {throw 'direct_record_invalid'}
    $stringValue='"(?:[^"\\\r\n]|\\(?:["\\/bfnrt]|u[a-fA-F0-9]{4}))*"'
    $prefixPattern='\A# BEGIN OPERATOR DIRECT DESKTOP\n# profile: '+[regex]::Escape($Manifest.profile)+'\n'
    foreach ($key in $selectorKeys) {$prefixPattern += [regex]::Escape($key)+' = (?<'+$key+'>'+$stringValue+')\n'}
    $prefixPattern+='# END OPERATOR DIRECT DESKTOP\n\z'
    $prefixMatch=[regex]::Match($prefix,$prefixPattern)
    if (-not $prefixMatch.Success) {throw 'direct_record_invalid'}
    foreach ($key in $selectorKeys) {if (($prefixMatch.Groups[$key].Value | ConvertFrom-Json) -cne $Projection.settings[$key]) {throw 'direct_record_invalid'}}
    $suffixPattern='\A\n# BEGIN OPERATOR DIRECT DESKTOP PROVIDER\n\[model_providers\.'+[regex]::Escape($providerId)+'\]\n'
    foreach ($key in $providerKeys) {
        $value=if ($key -in @('requires_openai_auth','supports_websockets')) {'false'} elseif ($key -in @('request_max_retries','stream_max_retries')) {'0'} else {$stringValue}
        $suffixPattern += [regex]::Escape($key)+' = (?<'+$key+'>'+$value+')\n'
    }
    $suffixPattern+='# END OPERATOR DIRECT DESKTOP PROVIDER\n\z'
    $suffixMatch=[regex]::Match($suffix,$suffixPattern)
    if (-not $suffixMatch.Success) {throw 'direct_record_invalid'}
    foreach ($key in $providerKeys) {if (($suffixMatch.Groups[$key].Value | ConvertFrom-Json) -cne $Projection.provider[$key]) {throw 'direct_record_invalid'}}
    $saved=@($Projection.saved)
    if ($saved.Count -gt 5) {throw 'direct_record_invalid'}
    $savedKeys=@();$savedLines=@()
    foreach ($entry in $saved) {
        Assert-RecoveryKeys $entry @('key','line_hex')
        if ($entry.key -cnotin $selectorKeys -or $entry.key -cin $savedKeys) {throw 'direct_record_invalid'}
        $line=$script:RecoveryUtf8.GetString((ConvertFrom-RecoveryHex $entry.line_hex))
        if (-not [regex]::IsMatch($line,'\A[ \t]*'+[regex]::Escape($entry.key)+'[ \t]*=[^\r\n]*\r?\n\z')) {throw 'direct_record_invalid'}
        if ($entry.key -ceq 'model_provider' -and -not [regex]::IsMatch($line,'\A[ \t]*model_provider[ \t]*=[ \t]*["'']openai["''][ \t]*(?:#[^\r\n]*)?\r?\n\z')) {throw 'direct_record_invalid'}
        $savedKeys+=$entry.key;$savedLines+=$line
    }
    function Restore-DirectOwnedText([string]$Text,[bool]$AllowEffort) {
        $expectedPrefix=$prefix
        if ($AllowEffort) {
            $currentPrefix=[regex]::Match($Text.Substring($lead.Length),$prefixPattern.Replace('\z',''))
            if (-not $currentPrefix.Success -or ($currentPrefix.Groups['model_reasoning_effort'].Value | ConvertFrom-Json) -cnotin $efforts) {throw 'direct_owned_changed'}
            $expectedPrefix=$currentPrefix.Value
            $normalized=$expectedPrefix.Replace('model_reasoning_effort = '+$currentPrefix.Groups['model_reasoning_effort'].Value+"`n",'model_reasoning_effort = '+$prefixMatch.Groups['model_reasoning_effort'].Value+"`n")
            if ($normalized -cne $prefix) {throw 'direct_owned_changed'}
        }
        if (-not $Text.StartsWith($lead+$expectedPrefix,[StringComparison]::Ordinal)) {throw 'direct_owned_changed'}
        foreach ($marker in @("# BEGIN OPERATOR DIRECT DESKTOP`n","# END OPERATOR DIRECT DESKTOP`n","# BEGIN OPERATOR DIRECT DESKTOP PROVIDER`n","# END OPERATOR DIRECT DESKTOP PROVIDER`n")) {
            if ([regex]::Matches($Text,[regex]::Escape($marker)).Count -ne 1) {throw 'direct_owned_changed'}
        }
        if ([regex]::Matches($Text,[regex]::Escape($suffix)).Count -ne 1) {throw 'direct_owned_changed'}
        if ([regex]::Matches($Text,'(?m)^[ \t]*\[model_providers\.'+[regex]::Escape($providerId)+'\][ \t]*(?:#[^\r\n]*)?\r?$').Count -ne 1) {throw 'direct_owned_changed'}
        $providerIndex=$Text.IndexOf($suffix,[StringComparison]::Ordinal)
        $afterProvider=$Text.Substring($providerIndex+$suffix.Length)
        if ($afterProvider -and -not [regex]::IsMatch($afterProvider,'\A(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*(?:[ \t]*\[[^\r\n]+\]|[ \t]*#[^\r\n]*\z|\z)')) {throw 'direct_owned_changed'}
        $body=$Text.Substring(($lead+$expectedPrefix).Length).Replace($suffix,'')
        $table=[regex]::Match($body,'(?m)^[ \t]*\[')
        $rootBody=if ($table.Success) {$body.Substring(0,$table.Index)} else {$body}
        if ([regex]::IsMatch($rootBody,'(?m)^[ \t]*["'']?(?:model|model_provider|model_catalog_json|model_reasoning_effort|web_search)["'']?[ \t]*=')) {throw 'direct_owned_changed'}
        foreach ($line in $savedLines) {
            $wrapped='# OPERATOR DIRECT SAVED SELECTOR '+$line
            if ([regex]::Matches($body,[regex]::Escape($wrapped)).Count -ne 1) {throw 'direct_owned_changed'}
            $body=$body.Replace($wrapped,$line)
        }
        if ($body.Contains('# OPERATOR DIRECT SAVED SELECTOR ')) {throw 'direct_owned_changed'}
        return $lead+$body
    }
    $candidateText=$script:RecoveryUtf8.GetString($Candidate)
    if ((Get-RecoveryHash ($script:RecoveryUtf8.GetBytes((Restore-DirectOwnedText $candidateText $false)))) -cne (Get-RecoveryHash $Original)) {throw 'direct_record_invalid'}
    return ,($script:RecoveryUtf8.GetBytes((Restore-DirectOwnedText ($script:RecoveryUtf8.GetString($Current)) $variable)))
}

function Get-RecoveryDirectConfigPlan([byte[]]$Bytes, [string]$HomePath, [string]$Project) {
    $text=$script:RecoveryUtf8.GetString($Bytes)
    if (-not $text.Contains('# BEGIN OPERATOR DIRECT') -and -not $text.Contains('# END OPERATOR DIRECT') -and
        -not $text.Contains('# OPERATOR DIRECT SAVED SELECTOR ')) {return $null}
    if (-not $HomePath -or -not $Project) {throw 'direct_record_invalid'}
    $root=Join-Path $HomePath 'operator-direct-entry'
    $activeBytes=Read-RecoveryBytes (Join-Path $root 'active.json') 16384
    if ($null -eq $activeBytes) {throw 'direct_record_invalid'}
    $active=ConvertFrom-RecoveryJson $activeBytes
    Assert-RecoveryKeys $active @('schema_version','contract','cycle','intent_sha256')
    if ($active.schema_version -ne 1 -or $active.contract -cne 'operator_direct_entry_active_v1' -or
        $active.cycle -cnotmatch '^[a-f0-9]{32}$' -or $active.intent_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'direct_record_invalid'}
    $cycle=Join-Path (Join-Path $root 'cycles') $active.cycle
    $intentBytes=Read-RecoveryBytes (Join-Path $cycle 'intent.json') 65536
    if ($null -eq $intentBytes -or (Get-RecoveryHash $intentBytes) -cne $active.intent_sha256) {throw 'direct_record_invalid'}
    $intent=ConvertFrom-RecoveryJson $intentBytes
    Assert-RecoveryKeys $intent @('schema_version','contract','home','project','cycle','plan_sha256','native_helper_sha256','source_sha256','config_before_present','before_identity','files')
    Assert-RecoveryKeys $intent.files @('config-before.bin','config-candidate.bin','projection.json','profile.json','plan.json')
    Assert-RecoveryKeys $intent.before_identity @('volume','file_id')
    if ($intent.schema_version -ne 1 -or $intent.contract -cne 'operator_direct_entry_cycle_v1' -or $intent.cycle -cne $active.cycle -or
        -not (Test-RecoveryAbsolutePath $intent.home) -or -not (Test-RecoveryAbsolutePath $intent.project) -or
        [IO.Path]::GetFullPath($intent.home).TrimEnd('\') -ine [IO.Path]::GetFullPath($HomePath).TrimEnd('\') -or
        [IO.Path]::GetFullPath($intent.project).TrimEnd('\') -ine [IO.Path]::GetFullPath($Project).TrimEnd('\') -or
        $intent.config_before_present -isnot [bool] -or -not $intent.config_before_present -or
        $intent.plan_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $intent.native_helper_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $intent.before_identity.volume -isnot [ValueType] -or $intent.before_identity.file_id -isnot [string] -or
        $intent.source_sha256 -isnot [Collections.IDictionary] -or $intent.source_sha256.Count -lt 5 -or $intent.source_sha256.Count -gt 256 -or
        @($intent.source_sha256.Keys | Where-Object { $_ -isnot [string] -or $_ -cnotmatch '^[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.(?:py|json)$' }).Count -or
        @($intent.source_sha256.Values | Where-Object { $_ -isnot [string] -or $_ -cnotmatch '^[a-f0-9]{64}$' }).Count -or
        $intent.native_helper_sha256 -cne (Get-RecoveryHash (Read-RecoveryBytes $script:RecoverySourcePath))) {throw 'direct_record_invalid'}
    $files=@{}
    foreach ($name in $intent.files.Keys) {
        $limit=if ($name -ceq 'projection.json') {4194304} else {1048576}
        $files[$name]=Read-RecoveryBytes (Join-Path $cycle $name) $limit
        if ($null -eq $files[$name] -or $intent.files[$name] -cnotmatch '^[a-f0-9]{64}$' -or
            (Get-RecoveryHash $files[$name]) -cne $intent.files[$name]) {throw 'direct_record_invalid'}
    }
    if ((Get-RecoveryHash $files['plan.json']) -cne $intent.plan_sha256) {throw 'direct_record_invalid'}
    $plan=ConvertFrom-RecoveryJson $files['plan.json']
    Assert-RecoveryKeys $plan @('schema_version','contract','project','home','state','profile','model','kind','display_name','python','native_helper','entry_script','source_sha256','profile_binding','router_port')
    foreach ($name in @('python','native_helper','entry_script')) {Assert-RecoveryKeys $plan[$name] @('path','sha256')}
    Assert-RecoveryKeys $plan.profile_binding @('manifest','plan','journal','profile','catalog')
    if ($plan.schema_version -ne 1 -or $plan.contract -cne 'operator_direct_entry_plan_v1' -or
        $plan.home -cne $intent.home -or $plan.project -cne $intent.project -or $plan.native_helper.sha256 -cne $intent.native_helper_sha256 -or
        @('operator_direct_entry.py','operator_direct_profile.py','operator_native_models.py','operator_core/windows_config_transaction.py','operator_core/responses_labels.py' | Where-Object {-not $intent.source_sha256.Contains($_)}).Count -or
        $plan.source_sha256 -isnot [Collections.IDictionary] -or $plan.source_sha256.Count -ne $intent.source_sha256.Count -or
        @($intent.source_sha256.Keys | Where-Object { $plan.source_sha256[$_] -cne $intent.source_sha256[$_] }).Count) {throw 'direct_record_invalid'}
    foreach ($name in @('python','native_helper','entry_script')) {
        if (-not (Test-RecoveryAbsolutePath $plan[$name].path) -or $plan[$name].sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'direct_record_invalid'}
    }
    if (@($plan.profile_binding.Values | Where-Object { $_ -isnot [string] -or $_ -cnotmatch '^[a-f0-9]{64}$' }).Count -or
        $plan.profile_binding.manifest -cne $intent.files['profile.json']) {throw 'direct_record_invalid'}
    $manifest=ConvertFrom-RecoveryJson $files['profile.json']
    if ($plan.profile -cne $manifest.profile -or $plan.model -cne $manifest.model.id -or $plan.kind -cne $manifest.kind -or
        $plan.display_name -cne $manifest.model.display_name) {throw 'direct_record_invalid'}
    if (Test-Path -LiteralPath (Join-Path $cycle 'recovered.json')) {throw 'direct_recovery_already_recorded'}
    $restored=Get-RecoveryDirectProjection $Bytes $files['config-candidate.bin'] $files['config-before.bin'] `
        (ConvertFrom-RecoveryJson $files['projection.json']) $manifest $HomePath
    return @{bytes=$restored;cycle=$active.cycle;intent_sha256=$active.intent_sha256;root=$root;
        recovery_change=@{name='direct-cycle-recovery.json';path=(Join-Path $cycle 'recovered.json');before=$null;
            direct_recovery=@{schema_version=1;contract='operator_direct_entry_recovered_v1';cycle=$active.cycle;intent_sha256=$active.intent_sha256;
                config_before_recovery_sha256=(Get-RecoveryHash $Bytes);config_after_recovery_sha256=(Get-RecoveryHash $restored)}}}
}

function Get-RecoveryConfigPlan([AllowNull()][byte[]]$Bytes, [string]$HomePath, [string]$Project) {
    if ($null -eq $Bytes) { return @{ state='native'; changed=$false; bytes=$null } }
    $direct=Get-RecoveryDirectConfigPlan $Bytes $HomePath $Project
    if ($direct) {$Bytes=$direct.bytes}
    $text = $script:RecoveryUtf8.GetString($Bytes)
    $unifiedMarkers = @(
        '# BEGIN OPERATOR UNIFIED CANDIDATE', '# END OPERATOR UNIFIED CANDIDATE',
        '# BEGIN OPERATOR UNIFIED PROVIDER CANDIDATE', '# END OPERATOR UNIFIED PROVIDER CANDIDATE'
    )
    $unifiedCounts = @($unifiedMarkers | ForEach-Object { [regex]::Matches($text, [regex]::Escape($_)).Count })
    $unifiedChanged = $false
    if (@($unifiedCounts | Where-Object { $_ -ne 0 }).Count) {
        if (@($unifiedCounts | Where-Object { $_ -ne 1 }).Count) { throw 'unrecognized_managed_block' }
        # These are the exact bytes emitted by operator_unified_desktop.render.
        # Its provider table was appended at EOF; later independent tables may
        # follow, but loose assignments would still belong to the owned table.
        $topPattern = '\A# BEGIN OPERATOR UNIFIED CANDIDATE\n' +
            'model_provider = "operator_unified_candidate"\n' +
            '(?:experimental_realtime_webrtc_call_base_url = "https://chatgpt\.com/backend-api/codex"\n)?' +
            '(?:experimental_realtime_ws_base_url = "https://chatgpt\.com/backend-api/codex"\n)?' +
            '# END OPERATOR UNIFIED CANDIDATE\n'
        $top = [regex]::Match($text, $topPattern)
        if (-not $top.Success) { throw 'unrecognized_managed_block' }
        $providerPattern = '\n# BEGIN OPERATOR UNIFIED PROVIDER CANDIDATE\n' +
            '\[model_providers\.operator_unified_candidate\]\n' +
            'name = "(?:OpenAI|Codex Operator)"\n' +
            'base_url = "(?<base>http://127\.0\.0\.1:(?<port>[0-9]{4,5})/[a-f0-9]{64}/backend-api/codex)"\n' +
            'model_catalog_url = "(?<catalog>[^"]*)"\n' +
            'wire_api = "responses"\n' +
            'requires_openai_auth = true\n' +
            'request_max_retries = 0\n' +
            'stream_max_retries = 0\n' +
            'supports_websockets = false\n' +
            'supports_standalone_web_search = true\n' +
            '# END OPERATOR UNIFIED PROVIDER CANDIDATE\n'
        $provider = [regex]::Match($text, $providerPattern)
        if (-not $provider.Success -or $provider.Index -lt $top.Length -or
            [int]$provider.Groups['port'].Value -lt 1024 -or
            [int]$provider.Groups['port'].Value -gt 65535 -or
            $provider.Groups['catalog'].Value -cne ($provider.Groups['base'].Value + '/models')) {
            throw 'unrecognized_managed_block'
        }
        $afterProvider = $text.Substring($provider.Index + $provider.Length)
        if ($afterProvider -and -not [regex]::IsMatch($afterProvider,
            '\A(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*(?:[ \t]*\[[^\r\n]+\]|[ \t]*#[^\r\n]*\z|\z)')) {
            throw 'unrecognized_managed_block'
        }
        $beforeProvider = $text.Substring($top.Length, $provider.Index - $top.Length)
        if ($afterProvider -and $beforeProvider.Length -gt 0 -and
            -not $beforeProvider.EndsWith("`n") -and -not $afterProvider.StartsWith("`n")) {
            throw 'unrecognized_managed_block'
        }
        $text = $text.Remove($provider.Index, $provider.Length).Remove(0, $top.Length)
        $unifiedChanged = $true
        if ($text.Contains('operator_unified_candidate')) { throw 'other_route_settings_require_review' }
    }
    $replacement = $text
    $begin = '# BEGIN FEISHU OPERATOR MODEL ROUTER'
    $end = '# END FEISHU OPERATOR MODEL ROUTER'
    $begins = [regex]::Matches($text, [regex]::Escape($begin)).Count
    $ends = [regex]::Matches($text, [regex]::Escape($end)).Count
    if ($unifiedChanged -and $begins -ne $ends) { throw 'unrecognized_managed_block' }
    if ($unifiedChanged -and $begins -gt 1) { throw 'unrecognized_managed_block' }
    $changed = $unifiedChanged -or $null -ne $direct
    $legacyChanged=$false
    $remaining = $text
    if ($begins -or $ends) {
        # Only the known leading legacy block or its exact Voice-protected
        # successor is removable. Comments before either remain untouched.
        $pattern = '\A\uFEFF?(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*?(?<block>' +
            [regex]::Escape($begin) + '\r?\n[ \t]*(?<disabled>#[ \t]*)?' +
            'openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:(?<port>[0-9]{4,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n' +
            '(?<voice>experimental_realtime_webrtc_call_base_url = "https://chatgpt\.com/backend-api/codex"\r?\n)?' +
            '(?<voiceWs>experimental_realtime_ws_base_url = "https://chatgpt\.com/backend-api/codex"\r?\n)?' +
            [regex]::Escape($end) + '(?:\r?\n|\z))'
        $match = [regex]::Match($text, $pattern)
        if (-not $match.Success -or
            [int]$match.Groups['port'].Value -lt 1024 -or [int]$match.Groups['port'].Value -gt 65535 -or
            (($match.Groups['voice'].Success -or $match.Groups['voiceWs'].Success) -and
                $match.Groups['disabled'].Success)) {
            throw 'unrecognized_managed_block'
        }
        $block = $match.Groups['block']
        $remaining = $text.Remove($block.Index, $block.Length)
        if ($unifiedChanged -and -not $match.Groups['disabled'].Success) {
            throw 'unrecognized_managed_block'
        }
        $changed = $changed -or -not $match.Groups['disabled'].Success
        $legacyChanged=-not $match.Groups['disabled'].Success
        if ($begins -ne $ends -or $begins -notin @(1, 2)) {
            throw 'unrecognized_managed_block'
        }
        if ($begins -eq 2) {
            if ($direct) {throw 'unrecognized_managed_block'}
            # Activation may retain exactly one originally commented legacy
            # prefix immediately after the owned active block. Leave its bytes.
            $inactivePattern = '\A' + [regex]::Escape($begin) + '\r?\n' +
                '# [ \t]*openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:(?<port>[0-9]{1,5})/[a-f0-9]{64}/v1"[ \t]*\r?\n' +
                [regex]::Escape($end) + '(?:\r?\n|\z)'
            $inactive = [regex]::Match($remaining, $inactivePattern)
            if (-not $changed -or -not $inactive.Success -or
                [int]$inactive.Groups['port'].Value -lt 1024 -or
                [int]$inactive.Groups['port'].Value -gt 65535) {
                throw 'unrecognized_managed_block'
            }
        }
    }
    # Conservative detection, not a general TOML parser. Inactive profiles or
    # unusual multiline syntax can require review; never reset them by guessing.
    $selection = '(?m)^[ \t]*["'']?(openai_base_url|model_provider|profile|model_catalog_json)["'']?[ \t]*='
    $nativeTable = '(?m)^[ \t]*(?:\[[^\r\n]*model_providers[^\r\n]*openai[^\r\n]*\]|["'']?model_providers["'']?\s*[.=])'
    $inspection = [regex]::Replace($remaining, '(?m)^[ \t]*model_provider[ \t]*=[ \t]*["'']openai["''][ \t]*(?:#[^\r\n]*)?$', '')
    if ([regex]::IsMatch($inspection, $selection) -or [regex]::IsMatch($inspection, $nativeTable)) {
        throw 'other_route_settings_require_review'
    }
    return @{ state=$(if ($changed) {'plugin_route'} else {'native'}); changed=$changed;
        bytes=$(if ($unifiedChanged) { $script:RecoveryUtf8.GetBytes($replacement) }
            elseif ($legacyChanged) { $script:RecoveryUtf8.GetBytes($remaining) } else { $Bytes }); direct=$direct }
}

function Get-RecoveryEntryPlan([string]$Project) {
    if (-not $Project) { return @{ state='not_selected'; change=$null } }
    $bundle = Join-Path $Project '.codex/operator-desktop-entry'
    Assert-RecoveryPlainPath $bundle
    if (-not (Test-Path -LiteralPath $bundle)) { return @{ state='not_installed'; change=$null } }
    $buildBytes = Read-RecoveryBytes (Join-Path $bundle 'launcher-manifest.json') 16384
    $configPath = Join-Path $bundle 'desktop-entry.json'
    $configBytes = Read-RecoveryBytes $configPath 16384
    if ($null -eq $buildBytes -or $null -eq $configBytes) { throw 'entry_requires_review' }
    $build = $script:RecoveryUtf8.GetString($buildBytes) | ConvertFrom-Json
    $config = $script:RecoveryUtf8.GetString($configBytes) | ConvertFrom-Json
    $scriptHash = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $bundle 'operator_desktop_entry.ps1'))
    $binaryHash = Get-RecoveryHash (Read-RecoveryBytes (Join-Path $bundle 'Codex拓展入口.exe') 16777216)
    if ($build.schema_version -ne 1 -or $build.native_fallback -cne 'native-only-v1' -or
        $scriptHash -eq 'absent' -or $binaryHash -eq 'absent' -or
        $build.binary_sha256 -cne $binaryHash -or $build.entry_script_sha256 -cne $scriptHash -or
        $config.schema_version -ne 1 -or $config.mode -notin @('native','reviewed_startup','direct_profile') -or
        $config.entry_script_sha256 -cne $scriptHash) { throw 'entry_requires_review' }
    if ($config.mode -eq 'native') { return @{ state='native'; change=$null } }
    if ($config.mode -ceq 'direct_profile') {
        if ($config.startup_bundle -cne '.codex/operator-direct-startup' -or $config.direct_entry_plan_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'entry_requires_review'}
        $indexPath=Join-Path (Join-Path $Project '.codex/operator-direct-startup') 'direct-entry-plan.json'
        $indexBytes=Read-RecoveryBytes $indexPath 262144
        if ($null -eq $indexBytes -or (Get-RecoveryHash $indexBytes) -cne $config.direct_entry_plan_sha256) {throw 'entry_requires_review'}
        $index=ConvertFrom-RecoveryJson $indexBytes
        Assert-RecoveryKeys $index @('schema_version','contract','project','home','python','python_sha256','native_helper','native_helper_sha256','controller','controller_sha256','entry_script_sha256','profiles')
        if ($index.schema_version -ne 1 -or $index.contract -cne 'direct_profile_picker_v1' -or $index.project -ine $Project -or
            $index.home -ine (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex') -or
            $index.entry_script_sha256 -cne $scriptHash -or $index.native_helper_sha256 -cne (Get-RecoveryHash (Read-RecoveryBytes $script:RecoverySourcePath)) -or
            $index.python_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $index.controller_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            @($index.profiles).Count -lt 1 -or @($index.profiles).Count -gt 32) {throw 'entry_requires_review'}
        foreach ($name in @('python','native_helper','controller')) {
            if (-not (Test-RecoveryAbsolutePath $index[$name])) {throw 'entry_requires_review'}
            Assert-RecoveryPlainPath $index[$name]
        }
        $projectPrefix=[IO.Path]::GetFullPath($Project).TrimEnd('\')+'\'
        foreach ($name in @('native_helper','controller')) {
            if (-not [IO.Path]::GetFullPath($index[$name]).StartsWith($projectPrefix,[StringComparison]::OrdinalIgnoreCase)) {throw 'entry_requires_review'}
        }
        $profiles=@()
        foreach ($row in @($index.profiles)) {
            Assert-RecoveryKeys $row @('profile','display_name','plan','plan_sha256')
            if ($row.profile -cnotmatch '^operator-[a-z0-9][a-z0-9-]{0,49}$' -or $row.profile -cin $profiles -or
                $row.display_name -isnot [string] -or -not $row.display_name.Length -or $row.display_name.Length -gt 128 -or
                $row.plan_sha256 -cnotmatch '^[a-f0-9]{64}$' -or -not (Test-RecoveryAbsolutePath $row.plan) -or
                -not [IO.Path]::GetFullPath($row.plan).StartsWith($projectPrefix,[StringComparison]::OrdinalIgnoreCase)) {throw 'entry_requires_review'}
            Assert-RecoveryPlainPath $row.plan
            $profiles+=$row.profile
        }
        # Recovery validates its retained picker binding without importing the
        # controller or needing its Python/runtime files to remain available.
        # Keep the chooser selected for a later explicitly selected cold launch.
        return @{state='direct_profile';change=$null}
    }
    $config.mode = 'native'
    return @{ state='reviewed_startup'; change=@{ name='desktop-entry.json'; path=$configPath;
        before=$configBytes; after=$script:RecoveryUtf8.GetBytes(($config | ConvertTo-Json -Depth 30)) } }
}

function Write-RecoveryChange($Change) {
    Assert-RecoveryPlainPath $Change.path
    if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.before)) {
        throw 'file_changed_during_recovery'
    }
    $temporary = Join-Path (Split-Path -Parent $Change.path) ('.operator-recovery-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($Change.after, 0, $Change.after.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.before)) {
            throw 'file_changed_during_recovery'
        }
        if ($null -eq $Change.before) { [IO.File]::Move($temporary, $Change.path) }
        else { [IO.File]::Replace($temporary, $Change.path, [NullString]::Value) }
        if ((Get-RecoveryHash (Read-RecoveryBytes $Change.path)) -cne (Get-RecoveryHash $Change.after)) {
            throw 'write_verification_failed'
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function New-RecoveryBackup([string]$HomePath, $Changes) {
    $directory = Join-Path $HomePath ('operator-route-recovery/' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
    Assert-RecoveryPlainPath $directory
    [void][IO.Directory]::CreateDirectory($directory)
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,
                      (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    # Do not autoload modules from an inherited PSModulePath (which may belong
    # to another PowerShell edition). Both implementations are built into .NET.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($directory), $acl)
    } else { [IO.Directory]::SetAccessControl($directory, $acl) }
    $records = @()
    $directCycle=@($Changes | Where-Object {$_.direct_recovery})
    foreach ($change in $Changes) {
        if ($change.direct_recovery) {
            $receipt=@{};foreach ($key in $change.direct_recovery.Keys) {$receipt[$key]=$change.direct_recovery[$key]}
            $receipt.recovery_backup=$directory
            $change.after=$script:RecoveryUtf8.GetBytes(($receipt | ConvertTo-Json -Depth 6))
        }
        if ($null -ne $change.before) {
            $original = Join-Path $directory ($change.name + '.before')
            [IO.File]::WriteAllBytes($original, $change.before)
            if ((Get-RecoveryHash (Read-RecoveryBytes $original)) -cne (Get-RecoveryHash $change.before)) { throw 'backup_verification_failed' }
        }
        if ($directCycle.Count -and $change.name -ceq 'config.toml') {
            $afterPath=Join-Path $directory 'config.toml.after'
            [IO.File]::WriteAllBytes($afterPath,$change.after)
            if ((Get-RecoveryHash (Read-RecoveryBytes $afterPath)) -cne (Get-RecoveryHash $change.after)) {throw 'backup_verification_failed'}
        }
        $records += @{ name=$change.name; target=$change.path; before_sha256=(Get-RecoveryHash $change.before); after_sha256=(Get-RecoveryHash $change.after) }
    }
    [IO.File]::WriteAllBytes((Join-Path $directory 'intent.json'), $script:RecoveryUtf8.GetBytes((@{
        schema_version=1; purpose='operator_official_route_recovery'; files=$records
    } | ConvertTo-Json -Depth 6)))
    return $directory
}

function Invoke-OfficialRouteRecovery([string]$HomePath, [string]$Project, [bool]$Commit) {
    $homePath = [IO.Path]::GetFullPath($HomePath).TrimEnd('\')
    Assert-RecoveryPlainPath $homePath
    if (-not (Test-Path -LiteralPath $homePath -PathType Container)) { throw 'codex_home_missing' }
    $mutexes = @()
    $backup = $null
    $completed = @()
    try {
        if ($Commit) {
            $names = @('Local\CodexOperatorRouteRecovery-' + (Get-RecoveryHash $script:RecoveryUtf8.GetBytes($homePath.ToLowerInvariant())))
            if ($Project) { $names += 'Local\CodexOperatorDesktopEntry-' + (Get-RecoveryHash $script:RecoveryUtf8.GetBytes($Project.ToLowerInvariant())).ToUpperInvariant() }
            foreach ($name in $names) {
                $mutex = New-Object Threading.Mutex($false, $name)
                $owns = $false
                try { $owns = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owns=$true }
                if (-not $owns) { $mutex.Dispose(); throw 'startup_or_recovery_busy' }
                $mutexes += $mutex
            }
        }
        $configPath = Join-Path $homePath 'config.toml'
        $before = Read-RecoveryBytes $configPath
        $plan = Get-RecoveryConfigPlan $before $homePath $Project
        $warnings = @()
        foreach ($scope in @('Process','User','Machine')) {
            if ([Environment]::GetEnvironmentVariable('OPENAI_BASE_URL', $scope)) { $warnings += 'environment_override'; break }
        }
        # A broken/changed optional launcher must not prevent detaching a known
        # global override. Report the remaining entry issue, never overwrite it.
        try { $entry = Get-RecoveryEntryPlan $Project }
        catch { $entry = @{ state='requires_review'; change=$null }; $warnings += 'entry_requires_review' }
        $markerPath = Join-Path $homePath $script:NativeRouteMarker
        $markerBytes = Read-RecoveryBytes $markerPath
        $changes = @()
        if ($null -eq $markerBytes) {
            $changes += @{ name=$script:NativeRouteMarker; path=$markerPath; before=$null;
                after=$script:RecoveryUtf8.GetBytes("operator-native-route-only-v1`n") }
        }
        if ($entry.change) { $changes += $entry.change }
        if ($plan.changed) { $changes += @{name='config.toml'; path=$configPath; before=$before; after=$plan.bytes} }
        if ($plan.direct) {$changes += $plan.direct.recovery_change}
        if ($Commit -and $changes.Count) {
            $backup = New-RecoveryBackup $homePath $changes
            # Validate all snapshots again before releasing any write.
            foreach ($change in $changes) {
                if ((Get-RecoveryHash (Read-RecoveryBytes $change.path)) -cne (Get-RecoveryHash $change.before)) { throw 'file_changed_during_recovery' }
            }
            foreach ($change in $changes) { Write-RecoveryChange $change; $completed += $change.name }
            $completion=@{schema_version=1;completed=$completed;warnings=$warnings}
            if ($plan.direct) {
                $afterSnapshot=Read-RecoveryBytes (Join-Path $backup 'config.toml.after')
                if ((Get-RecoveryHash $afterSnapshot) -cne (Get-RecoveryHash $plan.bytes)) {throw 'backup_verification_failed'}
                $completion.native_epoch=@{contract='operator_direct_native_epoch_v1';
                    completed_utc=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ',[Globalization.CultureInfo]::InvariantCulture);
                    config_after_sha256=(Get-RecoveryHash $afterSnapshot);native_helper_sha256=(Get-RecoveryHash (Read-RecoveryBytes $script:RecoverySourcePath));
                    cycle=$plan.direct.cycle;intent_sha256=$plan.direct.intent_sha256}
            }
            [IO.File]::WriteAllBytes((Join-Path $backup 'completed.json'), $script:RecoveryUtf8.GetBytes(($completion | ConvertTo-Json -Depth 6)))
        }
        return @{ status=$(if ($warnings.Count) {'needs_review'} elseif ($Commit) {'completed'} else {'preview'});
            route_before=$plan.state; config_changed=($Commit -and $plan.changed); would_change=@($changes | ForEach-Object { $_.name });
            recovery_lock_present=($Commit -or $null -ne $markerBytes); entry_before=$entry.state;
            backup=$backup; warnings=$warnings; completed=$completed; restart_required=$true }
    } catch {
        # Never print exception text: it can contain configuration or URLs.
        $reason = 'recovery_not_completed'
        $known = @('linked_path','not_regular_file','unrecognized_managed_block','other_route_settings_require_review',
            'file_changed_during_recovery','write_verification_failed','backup_verification_failed','startup_or_recovery_busy',
            'direct_record_invalid','direct_owned_changed','direct_recovery_already_recorded')
        $exception=$_.Exception
        for ($index=0;$exception -and $index -lt 4;$index++) {
            if ($exception.Message -cin $known) {$reason=$exception.Message;break}
            $exception=$exception.InnerException
        }
        return @{status='stopped'; reason=$reason; backup=$backup; completed=$completed;
            config_changed=($completed -contains 'config.toml'); restart_required=($completed -contains 'config.toml')}
    } finally {
        foreach ($mutex in $mutexes) { $mutex.ReleaseMutex(); $mutex.Dispose() }
    }
}

if ($Library) { return }
try {
    if (-not $CodexHome) {
        $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    }
    if (-not $ProjectRoot) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
        if ([IO.Path]::GetFullPath((Join-Path $candidate 'plugins/feishu-codex-operator/scripts')) -ieq $PSScriptRoot) { $ProjectRoot=$candidate }
        $installedProject = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
        if ([IO.Path]::GetFullPath((Join-Path $installedProject '.codex/feishu-codex-operator-runtime')) -ieq $PSScriptRoot) { $ProjectRoot=$installedProject }
        if ([IO.Path]::GetFullPath((Join-Path $installedProject '.codex/operator-native-recovery')) -ieq $PSScriptRoot) { $ProjectRoot=$installedProject }
    }
    if ($ProjectRoot) { $ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') }
    $result = Invoke-OfficialRouteRecovery $CodexHome $ProjectRoot $Apply.IsPresent
} catch { $result=@{status='stopped'; reason='recovery_not_completed'; backup=$null; completed=@()} }
if ($Json) { $result | ConvertTo-Json -Depth 5 -Compress }
else {
    Write-Output 'Operator：恢复官方默认路由'
    if ($result.status -eq 'preview') {
        Write-Output '检查完成，尚未修改任何文件。双击插件目录中的“恢复官方默认路由.cmd”即可应用。'
    } elseif ($result.status -eq 'completed') {
        Write-Output '已停用插件全局路由，并保留官方直连保护。账户、历史、插件和项目文件均保留。'
        Write-Output '请自行彻底退出 Codex，再从官方 Codex 入口打开，选择官方模型。此操作不会关闭正在运行的任务。'
    } elseif ($result.status -eq 'needs_review') {
        Write-Output '插件路由检查或恢复已完成，但还有环境变量或拓展入口需要核对；尚不能确认全部路由已恢复。'
        Write-Output '请使用官方 Codex 入口启动。将本窗口结果交给维护者；不要删除整个配置或登录资料。'
    } else {
        Write-Output '恢复未完成。未覆盖无法识别的设置；请保留本窗口信息和备份，交给维护者核对。'
        if ($result.reason -eq 'other_route_settings_require_review') { Write-Output '检测到其他模型供应商、配置档案或路由设置，不能当作本插件配置删除。' }
        elseif ($result.reason -eq 'unrecognized_managed_block') { Write-Output '插件路由标记的内容或位置已改变，需要核对后再处理。' }
        elseif ($result.reason -eq 'startup_or_recovery_busy') { Write-Output '另一个启动或恢复操作仍在进行；本次未重复执行。' }
        Write-Output ('诊断代码：' + $result.reason)
    }
    if ($result.backup) { Write-Output ('恢复记录和原件：' + $result.backup) }
    if ($result.completed.Count) { Write-Output ('已完成项目：' + ($result.completed -join ', ')) }
    Write-Output ('结果：' + $result.status)
}
if ($result.status -in @('completed','preview')) { exit 0 }
exit 1
