#requires -Version 7.0
# A separate, explicit one-shot recognition of an already changed Desktop link.
# The link and the original entry-only migration journal are never rewritten.
function Get-OperatorShortcutFileIdentity([string]$Path) {
    if (-not ('OperatorShortcutFileIdentity' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OperatorShortcutFileIdentity {
    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInformation info);
    public static string Read(string path) {
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Read,
                   FileShare.ReadWrite | FileShare.Delete)) {
            FileInformation info;
            if (!GetFileInformationByHandle(file.SafeFileHandle, out info) || info.NumberOfLinks != 1)
                throw new IOException("Shortcut identity unavailable.");
            ulong index = ((ulong)info.FileIndexHigh << 32) | info.FileIndexLow;
            return info.VolumeSerialNumber.ToString("x8") + ":" + index.ToString("x16");
        }
    }
}
'@
    }
    Assert-OperatorPlainPath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Shortcut identity unavailable.' }
    return [OperatorShortcutFileIdentity]::Read($Path)
}

function Get-OperatorShortcutCom([string]$Path) {
    Assert-OperatorPlainPath $Path
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    return [ordered]@{full_name=[IO.Path]::GetFullPath($link.FullName);
        target=$link.TargetPath; arguments=$link.Arguments;
        working_directory=$link.WorkingDirectory; icon=$link.IconLocation;
        window_style=[int]$link.WindowStyle; description=$link.Description; hotkey=$link.Hotkey}
}

function Get-OperatorLauncherHome([string]$CodexHome) {
    # The installed Desktop script consults only CODEX_HOME or the user default.
    $effective = if ($env:CODEX_HOME) { [IO.Path]::GetFullPath($env:CODEX_HOME).TrimEnd('\') }
        else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    $selected = if ($CodexHome) { [IO.Path]::GetFullPath($CodexHome).TrimEnd('\') }
        else { $effective }
    foreach ($path in @($effective,$selected)) { Assert-OperatorPlainPath $path }
    if ($selected -ine $effective) { throw 'Selected home differs from Desktop launcher home.' }
    return $selected
}

function Get-OperatorEntryShortcutAdoptionPlan {
    param([string]$ProjectRoot, [string]$CodexHome, [switch]$IgnoreExisting)
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $selectedHome = Get-OperatorLauncherHome $CodexHome
    $private = Join-Path $project '.codex'
    $folder = Join-Path $private 'operator-entry-shortcut-adoption'
    foreach ($path in @($project,$selectedHome,$folder)) { Assert-OperatorPlainPath $path }
    if ((Test-Path -LiteralPath $folder) -and -not $IgnoreExisting) {
        throw 'Existing or uncertain shortcut adoption requires review.'
    }
    if (Test-Path -LiteralPath (Join-Path $selectedHome 'operator-unified-activation')) {
        throw 'Unified activation plan prevents shortcut adoption.'
    }
    $marker = Join-Path $selectedHome 'operator-native-route-only'
    Assert-OperatorPlainPath $marker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf) -or
        [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($marker)) -cne "operator-native-route-only-v1`n") {
        throw 'Native route protection is required.'
    }
    if (Test-Path -LiteralPath (Join-Path $private 'operator-entry-upgrade')) {
        throw 'Entry config already has an upgrade transaction.'
    }
    $state = Get-OperatorEntryMigrationState $project
    if ($state.phase -cne 'installed' -or $state.runtime_ownership -cne 'unresolved' -or
        $state.entries.Count -ne 2 -or $state.build.Count -ne 5) {
        throw 'Installed entry-only migration required.'
    }
    $historicalPlanBytes = [Text.UTF8Encoding]::new($false).GetBytes(($state.plan | ConvertTo-Json -Depth 8 -Compress))
    $historicalPlanHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($historicalPlanBytes)).ToLowerInvariant()
    if ($state.plan_sha256 -cne $historicalPlanHash -or
        (Get-OperatorFingerprint $state.plan.legacy_executable) -cne $state.plan.legacy_executable_sha256) {
        throw 'Migration plan or legacy restoration launcher changed.'
    }
    $paths = @(Get-OperatorDesktopPaths)
    if ($paths.Count -ne 2 -or (Split-Path -Leaf $paths[0]) -cne 'Codex拓展入口.lnk' -or
        (Split-Path -Leaf $paths[1]) -cne 'Codex拓展入口.lnk') { throw 'Shortcut scope changed.' }
    $desktop = [IO.Path]::GetFullPath($paths[0])
    $start = [IO.Path]::GetFullPath($paths[1])
    foreach ($path in @($desktop,$start)) { Assert-OperatorPlainPath $path }
    $desktopRow = $state.entries[$desktop]
    $startRow = $state.entries[$start]
    $desktopSha = Get-OperatorFingerprint $desktop
    if ($desktopRow.status -cne 'installed' -or $startRow.status -cne 'installed' -or
        $desktopSha -eq 'absent' -or
        (Get-OperatorFingerprint $start) -cne $startRow.after) {
        throw 'Shortcut state does not require an exact adoption.'
    }
    if ($desktopSha -ceq $desktopRow.after) { throw 'Desktop shortcut has not changed.' }
    if ((Get-Item -LiteralPath $desktop).Length -gt 65536 -or
        (Get-Item -LiteralPath $start).Length -gt 65536) { throw 'Shortcut too large.' }
    $bundle = Join-Path $private 'operator-desktop-entry'
    $binary = Join-Path $bundle 'Codex拓展入口.exe'
    $icon = Join-Path $bundle 'Codex拓展入口.ico'
    foreach ($name in @('Codex拓展入口.exe','operator_desktop_entry.ps1','launcher-manifest.json','Codex拓展入口.ico')) {
        if ((Get-OperatorFingerprint (Join-Path $bundle $name)) -cne $state.build[$name]) {
            throw 'Migrated entry build changed.'
        }
    }
    # Historical workflow/source hashes remain in the migration plan, but the
    # old workflow was deliberately superseded. Require the *installed* script
    # to match the current launcher source instead of comparing old source SHA.
    if ((Get-OperatorFingerprint (Join-Path $bundle 'operator_desktop_entry.ps1')) -cne
        (Get-OperatorFingerprint (Join-Path $PSScriptRoot 'operator_desktop_entry.ps1'))) {
        throw 'Current launcher source differs from installed entry.'
    }
    $manifest = Get-Content -LiteralPath (Join-Path $bundle 'launcher-manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($manifest.binary_sha256 -cne $state.build['Codex拓展入口.exe'] -or
        $manifest.entry_script_sha256 -cne $state.build['operator_desktop_entry.ps1']) {
        throw 'Entry manifest changed.'
    }
    foreach ($path in @($desktop,$start)) {
        $row = $state.entries[$path]
        if ($row.before -ne 'absent' -and
            (Get-OperatorFingerprint (Join-Path $private ('operator-entry-migration/originals/'+$row.before+'.bin'))) -cne $row.before) {
            throw 'Migration original changed.'
        }
    }
    $reviewFolder = Join-Path $private 'audit/web-startup-comment-fix-20260919'
    $archive = Join-Path $reviewFolder 'desktop-link-at-review.lnk'
    $reviewFile = Join-Path $reviewFolder 'shortcuts-review.json'
    $reportFile = Join-Path $reviewFolder 'report.md'
    foreach ($path in @($archive,$reviewFile,$reportFile)) {
        Assert-OperatorPlainPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-Item -LiteralPath $path).Length -gt 65536) { throw 'Historical shortcut evidence unavailable.' }
    }
    if ((Get-OperatorFingerprint $archive) -cne $desktopSha) { throw 'Archived Desktop bytes differ.' }
    $historical = @(Get-Content -LiteralPath $reviewFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable)
    $desktopHistory = @($historical | Where-Object { $_.path -ieq $desktop })
    $startHistory = @($historical | Where-Object { $_.path -ieq $start })
    if ($historical.Count -ne 2 -or $desktopHistory.Count -ne 1 -or $startHistory.Count -ne 1 -or
        $desktopHistory[0].sha256 -cne $desktopSha -or
        $desktopHistory[0].installed_sha256 -cne $desktopRow.after -or
        $startHistory[0].sha256 -cne $startRow.after -or
        $startHistory[0].installed_sha256 -cne $startRow.after) {
        throw 'Historical shortcut review does not bind migration.'
    }
    $desktopCom = Get-OperatorShortcutCom $desktop
    $startCom = Get-OperatorShortcutCom $start
    foreach ($pair in @(@($desktopCom,$desktopHistory[0]),@($startCom,$startHistory[0]))) {
        $com = $pair[0]; $history = $pair[1]
        if ($com.target -ine $binary -or $com.arguments -or $com.working_directory -ine $bundle -or
            $com.icon -ine ($icon+',0') -or $com.window_style -ne 7 -or $com.hotkey -or
            $history.target -ine $com.target -or $history.arguments -cne $com.arguments -or
            $history.working_directory -ine $com.working_directory -or
            $history.icon -ine $com.icon -or $history.window_style -ne $com.window_style) {
            throw 'Shortcut launch fields differ from reviewed evidence.'
        }
    }
    $identity = Get-OperatorShortcutFileIdentity $desktop
    $startIdentity = Get-OperatorShortcutFileIdentity $start
    $plan = [ordered]@{schema_version=1; scope='desktop_shortcut_adoption'; project=$project;
        codex_home=$selectedHome; migration_sha256=(Get-OperatorFingerprint (Join-Path $private 'operator-entry-migration/journal.json'));
        desktop=$desktop; original_after_sha256=$desktopRow.after; adopted_sha256=$desktopSha;
        adopted_identity=$identity; start=$start; start_sha256=$startRow.after;
        start_identity=$startIdentity;
        archive_sha256=(Get-OperatorFingerprint $archive); review_sha256=(Get-OperatorFingerprint $reviewFile);
        report_sha256=(Get-OperatorFingerprint $reportFile); desktop_com=$desktopCom; start_com=$startCom;
        config_sha256=(Get-OperatorFingerprint (Join-Path $bundle 'desktop-entry.json'));
        adoption_source_sha256=(Get-OperatorFingerprint (Join-Path $PSScriptRoot 'operator_entry_shortcut_adoption.ps1'))}
    $raw = [Text.UTF8Encoding]::new($false).GetBytes(($plan | ConvertTo-Json -Depth 12 -Compress))
    $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()
    return @{plan=$plan; sha256=$digest; current_bytes=[IO.File]::ReadAllBytes($desktop);
        summary=[ordered]@{desktop_path=$desktop; previous_sha256=$desktopRow.after;
            current_sha256=$desktopSha; current_bytes=(Get-Item -LiteralPath $desktop).Length;
            archived_copy_matches=$true; start_unchanged=$true;
            target_unchanged=$true; arguments_empty=$true; working_directory_unchanged=$true;
            icon_unchanged=$true; window_style_unchanged=$true;
            description_matches_start=($desktopCom.description -ceq $startCom.description);
            hotkey_empty=($desktopCom.hotkey -ceq '')}}
}

function Get-OperatorEntryAdoptionAfter {
    param([string]$ProjectRoot, $Migration, [string]$Path, [switch]$CheckCurrent,
          [switch]$CheckCurrentDesktopOnly)
    $folder = Join-Path $ProjectRoot '.codex/operator-entry-shortcut-adoption'
    Assert-OperatorPlainPath $folder
    if (-not (Test-Path -LiteralPath $folder)) { return $Migration.entries[$Path].after }
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw 'Shortcut adoption requires review.' }
    $intentFile = Join-Path $folder 'intent.json'
    $receiptFile = Join-Path $folder 'receipt.json'
    $backupFile = Join-Path $folder 'adopted-desktop.lnk'
    foreach ($file in @($intentFile,$receiptFile,$backupFile)) {
        Assert-OperatorPlainPath $file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or
            (Get-Item -LiteralPath $file).Length -gt 65536) { throw 'Shortcut adoption requires review.' }
    }
    $intent = Get-Content -LiteralPath $intentFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $receipt = Get-Content -LiteralPath $receiptFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    $plan = $intent.plan
    $planBytes = [Text.UTF8Encoding]::new($false).GetBytes(($plan | ConvertTo-Json -Depth 12 -Compress))
    $planHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($planBytes)).ToLowerInvariant()
    $paths = @(Get-OperatorDesktopPaths)
    $desktop = [IO.Path]::GetFullPath($paths[0])
    $start = [IO.Path]::GetFullPath($paths[1])
    $audit = Join-Path $ProjectRoot '.codex/audit/web-startup-comment-fix-20260919'
    if ($paths.Count -ne 2 -or $intent.schema_version -ne 1 -or $intent.phase -cne 'may_have_adopted' -or
        $plan.schema_version -ne 1 -or $plan.scope -cne 'desktop_shortcut_adoption' -or
        $plan.project -ine [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') -or
        $plan.desktop -ine $desktop -or $plan.start -ine $start -or
        $plan.original_after_sha256 -cne $Migration.entries[$desktop].after -or
        $plan.start_sha256 -cne $Migration.entries[$start].after -or
        $plan.archive_sha256 -cne $plan.adopted_sha256 -or
        ($Migration.phase -ceq 'installed' -and
            $plan.migration_sha256 -cne (Get-OperatorFingerprint (Join-Path $ProjectRoot '.codex/operator-entry-migration/journal.json'))) -or
        $intent.plan_sha256 -cne $planHash -or $receipt.schema_version -ne 1 -or
        $receipt.phase -cne 'adopted_witnessed' -or $receipt.plan_sha256 -cne $planHash -or
        $receipt.intent_sha256 -cne (Get-OperatorFingerprint $intentFile) -or
        $receipt.backup_sha256 -cne $plan.adopted_sha256 -or
        $receipt.adopted_identity -cne $plan.adopted_identity -or
        (Get-OperatorFingerprint $backupFile) -cne $plan.adopted_sha256 -or
        (Get-OperatorFingerprint (Join-Path $audit 'desktop-link-at-review.lnk')) -cne $plan.archive_sha256 -or
        (Get-OperatorFingerprint (Join-Path $audit 'shortcuts-review.json')) -cne $plan.review_sha256 -or
        (Get-OperatorFingerprint (Join-Path $audit 'report.md')) -cne $plan.report_sha256) {
        throw 'Shortcut adoption requires review.'
    }
    if ($CheckCurrent -or $CheckCurrentDesktopOnly) {
        if ((Get-OperatorFingerprint $desktop) -cne $plan.adopted_sha256 -or
            (Get-OperatorShortcutFileIdentity $desktop) -cne $plan.adopted_identity -or
            ((Get-OperatorShortcutCom $desktop | ConvertTo-Json -Depth 5 -Compress) -cne
                ($plan.desktop_com | ConvertTo-Json -Depth 5 -Compress))) {
            throw 'Adopted Desktop shortcut changed.'
        }
        if ($CheckCurrent) {
            $startCurrent = Get-OperatorFingerprint $start
            $startAdopted = $startCurrent -ceq $plan.start_sha256 -and
                (Get-OperatorShortcutFileIdentity $start) -ceq $plan.start_identity
            $startOriginal = $false
            if ($Migration.phase -ceq 'restoring' -and
                $startCurrent -ceq $Migration.entries[$start].before) {
                $before = $Migration.entries[$start].before
                $startOriginal = $before -ceq 'absent' -or
                    (Get-OperatorFingerprint (Join-Path $ProjectRoot (
                        '.codex/operator-entry-migration/originals/'+$before+'.bin'))) -ceq $before
            }
            if (-not $startAdopted -and -not $startOriginal) {
                throw 'Adopted Start shortcut changed.'
            }
        }
    }
    if ($Path -ieq $desktop) { return $plan.adopted_sha256 }
    if ($Path -ieq $start) { return $Migration.entries[$start].after }
    throw 'Shortcut adoption scope changed.'
}

function Invoke-OperatorEntryShortcutAdoption {
    param([string]$ProjectRoot, [string]$CodexHome, [string]$ExpectedPlanSha256,
          [switch]$OwnerApprovedShortcutAdoption)
    if (-not $OwnerApprovedShortcutAdoption) { throw 'Explicit owner approval required for changed shortcut adoption.' }
    $review = Get-OperatorEntryShortcutAdoptionPlan $ProjectRoot $CodexHome
    if ($ExpectedPlanSha256 -cnotmatch '^[a-f0-9]{64}$' -or $review.sha256 -cne $ExpectedPlanSha256) {
        throw 'Shortcut adoption preview changed.'
    }
    $project = $review.plan.project
    $migrationLock = Join-Path $project '.codex/operator-entry-migration/transaction.lock'
    $guard = [IO.File]::Open($migrationLock,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $repeat = Get-OperatorEntryShortcutAdoptionPlan $project $CodexHome
        if ($repeat.sha256 -cne $review.sha256) { throw 'Shortcut adoption changed before intent.' }
        $folder = Join-Path $project '.codex/operator-entry-shortcut-adoption'
        if (Test-Path -LiteralPath $folder) { throw 'Existing or uncertain shortcut adoption requires review.' }
        New-Item -ItemType Directory -Path $folder | Out-Null
        $lock = [IO.File]::Open((Join-Path $folder 'transaction.lock'),[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        try {
            Write-OperatorAtomicBytes (Join-Path $folder 'adopted-desktop.lnk') $review.current_bytes
            if ((Get-OperatorFingerprint (Join-Path $folder 'adopted-desktop.lnk')) -cne $review.plan.adopted_sha256) {
                throw 'Shortcut adoption backup changed.'
            }
            $intent = [ordered]@{schema_version=1;phase='may_have_adopted';plan=$review.plan;plan_sha256=$review.sha256}
            Write-OperatorAtomicBytes (Join-Path $folder 'intent.json') (
                [Text.UTF8Encoding]::new($false).GetBytes(($intent | ConvertTo-Json -Depth 15)))
            $again = Get-OperatorEntryShortcutAdoptionPlan $project $CodexHome -IgnoreExisting
            if ($again.sha256 -cne $review.sha256 -or
                (Get-OperatorFingerprint $review.plan.desktop) -cne $review.plan.adopted_sha256 -or
                (Get-OperatorShortcutFileIdentity $review.plan.desktop) -cne $review.plan.adopted_identity) {
                throw 'Shortcut adoption changed after intent.'
            }
            $receipt = [ordered]@{schema_version=1;phase='adopted_witnessed';plan_sha256=$review.sha256;
                intent_sha256=(Get-OperatorFingerprint (Join-Path $folder 'intent.json'));
                backup_sha256=$review.plan.adopted_sha256;adopted_identity=$review.plan.adopted_identity}
            Write-OperatorAtomicBytes (Join-Path $folder 'receipt.json') (
                [Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 6)))
            $state = Get-OperatorEntryMigrationState $project
            [void](Get-OperatorEntryAdoptionAfter $project $state $review.plan.desktop -CheckCurrent)
            return @{status='shortcut_adopted_witnessed';shortcut_changed=$false;configuration_changed=$false;
                routing_changed=$false;runtime_ownership='unresolved';model_requests=0}
        } finally { $lock.Dispose() }
    } finally { $guard.Dispose() }
}
