"""Read-only inventory and real-home preview for a future unified Desktop entry.

This module owns no installation or activation. Its candidate digest describes
only the supplied router identity and the configuration bytes observed now.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import operator_unified_desktop as candidate


RECOVERY_FILES = ("restore-codex-official-route.ps1", "恢复官方默认路由.cmd")
ROUTE_CONFLICTS = frozenset({
    "candidate_existing_route_conflict", "candidate_existing_managed_block",
    "candidate_provider_collision", "candidate_voice_route_conflict",
})
INVENTORY_BASE = "http://127.0.0.1:4318/" + "0" * 64 + "/backend-api/codex"


class PreviewError(ValueError):
    """A fixed, content-free public failure reason."""


def _directory(value: Path) -> Path:
    if not value.is_absolute():
        raise PreviewError("unified_preview_absolute_path_required")
    try:
        candidate._plain(value)
        if not value.is_dir():
            raise PreviewError("unified_preview_directory_unavailable")
        return value.resolve(strict=True)
    except candidate.CandidateError as exc:
        raise PreviewError("unified_preview_plain_path_required") from exc


def _read(path: Path, *, optional: bool = False, limit: int = candidate.LIMIT) -> bytes | None:
    try:
        raw = candidate._read(path, allow_missing=optional)
    except (candidate.CandidateError, OSError) as exc:
        raise PreviewError("unified_preview_file_unavailable") from exc
    if raw is not None and len(raw) > limit:
        raise PreviewError("unified_preview_file_unavailable")
    return raw


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _verify_shortcut(project: Path, link: Path) -> bool:
    """Inspect the current Desktop link without executing it or exposing its paths."""
    if os.name != "nt":
        return False
    bundle = project / ".codex/operator-native-recovery"
    script = r'''
try {
    $ErrorActionPreference = 'Stop'
    $item = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    if (-not $desktop) { exit 1 }
    $expected = Join-Path $desktop '恢复官方默认路由.lnk'
    if (-not [IO.Path]::GetFullPath($item.link).Equals(
            [IO.Path]::GetFullPath($expected), [StringComparison]::OrdinalIgnoreCase)) { exit 1 }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($item.link)
    if (-not $shortcut.TargetPath.Equals($item.target, [StringComparison]::OrdinalIgnoreCase) -or
        $shortcut.Arguments -or
        -not $shortcut.WorkingDirectory.Equals($item.directory, [StringComparison]::OrdinalIgnoreCase)) {
        exit 1
    }
    exit 0
} catch { exit 1 }
'''
    system = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(system), "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps({"link": str(link), "target": str(bundle / "恢复官方默认路由.cmd"),
                              "directory": str(bundle)}),
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except (KeyError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def verify_owned_entry(project: Path, bundle: Path, *, test_shortcuts: tuple[Path, Path] | None = None,
                       recovered_config: dict | None = None) -> str:
    """Read the current two shortcuts and their exact ownership before entry activation.

    The optional paths exist solely for disposable tests; production callers
    always use the Windows current-user Desktop and Programs known folders.
    A recovered configuration row must already have been checked by the caller
    against the retained recovery intent, completion and exact native bytes.
    This inspection binds that row to the entry without proving its provenance.
    """
    if os.name != "nt" or not shutil.which("pwsh"):
        raise PreviewError("unified_entry_shortcuts_unverified")
    project, bundle = _directory(project), _directory(bundle)
    if bundle != project / ".codex/operator-desktop-entry":
        raise PreviewError("unified_entry_shortcuts_unverified")
    if test_shortcuts is not None:
        # The injected paths may never redirect production checks to arbitrary
        # links. Tests own both their temporary project and its fake Desktop.
        temporary = Path(tempfile.gettempdir()).resolve(strict=True)
        if (not project.is_relative_to(temporary) or project == temporary
                or len(test_shortcuts) != 2 or len(set(test_shortcuts)) != 2
                or any(not link.is_absolute() or not link.is_relative_to(project)
                       for link in test_shortcuts)):
            raise PreviewError("unified_entry_shortcuts_unverified")
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json -AsHashtable
    . $request.setup -ProjectRoot $request.project -Library
    if ($request.test_shortcuts) {
        $script:ownedLinksForTest = @($request.test_shortcuts)
        function Get-OperatorDesktopPaths { @($script:ownedLinksForTest) }
    }
    $project = [IO.Path]::GetFullPath($request.project).TrimEnd('\')
    $bundle = Join-Path $project '.codex/operator-desktop-entry'
    $binary = Join-Path $bundle 'Codex拓展入口.exe'
    if ($request.bundle -ine $bundle -or (Test-Path -LiteralPath (Join-Path $bundle 'native-only'))) {
        throw 'entry scope'
    }
    $migrationFile = Join-Path $project '.codex/operator-entry-migration/journal.json'
    $ownershipFile = Join-Path $project '.codex/operator-installation/ownership.json'
    $hasMigration = Test-Path -LiteralPath (Join-Path $project '.codex/operator-entry-migration')
    $hasOwnership = Test-Path -LiteralPath (Join-Path $project '.codex/operator-installation')
    if ($hasMigration -eq (Test-Path -LiteralPath $ownershipFile) -or
        ($hasMigration -and -not (Test-Path -LiteralPath $migrationFile)) -or
        ($hasOwnership -and -not (Test-Path -LiteralPath $ownershipFile) -and -not $hasMigration)) {
        throw 'entry ownership'
    }
    $pairRoot = Join-Path $project '.codex/operator-desktop-pair'
    if ((Test-Path -LiteralPath $pairRoot) -and $hasMigration) {
        # A legacy pair keeps its original entry-only ownership. Its module
        # verifies the renamed Desktop entity and unchanged Programs link;
        # it never manufactures normal installation ownership.
        $pairFile = Join-Path $pairRoot 'ownership.json'
        $originFile = Join-Path $pairRoot 'legacy-origin.json'
        $pairDigest = Get-OperatorFingerprint $pairFile
        $originDigest = Get-OperatorFingerprint $originFile
        $legacyModule = Import-Module $request.legacy_pair_module -Force -DisableNameChecking -PassThru
        if ($request.test_shortcuts) {
            Assert-OperatorPlainPath $pairFile
            $fixtureInfo = Get-Item -LiteralPath $pairFile
            if ($fixtureInfo.PSIsContainer -or $fixtureInfo.Length -gt 1048576) { throw 'entry pair fixture' }
            $fixture = [IO.File]::ReadAllText($pairFile) | ConvertFrom-Json -AsHashtable
            $legacyLinks = @($fixture.legacy.desktop, $fixture.legacy.start)
            if ($legacyLinks.Count -ne 2 -or $legacyLinks[0] -ieq $legacyLinks[1]) { throw 'entry pair fixture' }
            foreach ($path in $legacyLinks) {
                if ($path -isnot [string] -or -not [IO.Path]::IsPathFullyQualified($path) -or
                    [IO.Path]::GetFullPath($path) -ine $path -or
                    -not $path.StartsWith($project+'\', [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'entry pair fixture'
                }
                Assert-OperatorPlainPath $path
            }
            $script:ownedLinksForTest = $legacyLinks
            & $legacyModule {
                param($desktop, $start)
                & $script:LegacyEntry {
                    param($desktop, $start)
                    $script:legacyPairFixtureDesktop = $desktop
                    $script:legacyPairFixtureStart = $start
                    function script:Get-OperatorDesktopPaths {
                        @($script:legacyPairFixtureDesktop, $script:legacyPairFixtureStart)
                    }
                } $desktop $start
            } $legacyLinks[0] $legacyLinks[1]
        }
        $stateArguments = @{ProjectRoot=$project;CheckCurrent=$true}
        if ($null -ne $request.recovered_config) {
            $recovered = $request.recovered_config
            if ($recovered -isnot [Collections.IDictionary] -or $recovered.Count -ne 4 -or
                $recovered.name -isnot [string] -or $recovered.target -isnot [string] -or
                $recovered.before_sha256 -isnot [string] -or $recovered.after_sha256 -isnot [string] -or
                $recovered.name -cne 'desktop-entry.json' -or
                $recovered.target -ine (Join-Path $bundle 'desktop-entry.json') -or
                $recovered.before_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
                $recovered.after_sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'recovered entry scope' }
            $stateArguments.RecoveredConfig = $recovered
        }
        $record = Get-OperatorDesktopLegacyPairState @stateArguments
        if ($record.schema_version -ne 1 -or $record.scope -cne 'legacy_entry_only' -or
            $record.phase -cne 'installed' -or $record.origin_sha256 -cne $originDigest -or
            $record.project -ine $project -or $record.links.Count -ne 2) { throw 'entry legacy pair scope' }
        if ($null -ne $request.recovered_config -and
            ($request.recovered_config.before_sha256 -cne $record.build['desktop-entry.json'] -or
             $request.recovered_config.after_sha256 -cne (Get-OperatorFingerprint (Join-Path $bundle 'desktop-entry.json')))) {
            throw 'recovered entry original'
        }
        $links = @((Join-Path $record.desktop 'ChatGPT 原生入口.lnk'),
            (Join-Path $record.desktop ('ChatGPT 拓展模型 '+$record.build_date.Substring(5)+' 入口.lnk')))
        if ($request.test_shortcuts) {
            if (@($request.test_shortcuts).Count -ne 2 -or
                @($links | Where-Object {$_ -notin $request.test_shortcuts}).Count) { throw 'entry pair fixture' }
        } else {
            $desktop = [Environment]::GetFolderPath('DesktopDirectory')
            if (-not $desktop -or [IO.Path]::GetFullPath($record.desktop).TrimEnd('\') -ine
                [IO.Path]::GetFullPath($desktop).TrimEnd('\')) { throw 'entry pair desktop' }
        }
        $nativeFolder = Join-Path $pairRoot ('generations/'+$record.generation)
        $nativeScript = Join-Path $nativeFolder 'operator_native_entry.ps1'
        $nativeShell = Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
        $nativeArguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+$nativeScript+'"'
        $shell = New-Object -ComObject WScript.Shell
        $fingerprints = [ordered]@{}
        for ($index=0; $index -lt $links.Count; $index++) {
            $linkPath = $links[$index]
            Assert-OperatorPlainPath $linkPath
            $current = Get-OperatorFingerprint $linkPath
            if ($current -ceq 'absent' -or $current -cne $record.links[$linkPath].after) { throw 'entry pair changed' }
            $shortcut = $shell.CreateShortcut($linkPath)
            $target = if ($index -eq 0) {$nativeShell} else {$binary}
            $arguments = if ($index -eq 0) {$nativeArguments} else {''}
            $directory = if ($index -eq 0) {$nativeFolder} else {$bundle}
            if ($shortcut.TargetPath -ine $target -or $shortcut.Arguments -cne $arguments -or
                $shortcut.WorkingDirectory -ine $directory) { throw 'entry pair shortcut target' }
            $fingerprints[$linkPath] = $current
        }
        $confirmed = Get-OperatorDesktopLegacyPairState @stateArguments
        if ($confirmed.phase -cne 'installed' -or $confirmed.origin_sha256 -cne $originDigest -or
            (Get-OperatorFingerprint $pairFile) -cne $pairDigest -or
            (Get-OperatorFingerprint $originFile) -cne $originDigest) { throw 'entry pair changed' }
        $result = [ordered]@{scope='legacy_pair';owner_sha256=$record.origin.migration_sha256;
            pair_receipt_sha256=$pairDigest;pair_origin_sha256=$originDigest;
            upgrade_receipt_sha256=$(if ($record.origin.upgrade_receipt_sha256 -ceq 'absent') {$null}
                else {$record.origin.upgrade_receipt_sha256});
            adoption_receipt_sha256=$(if ($record.origin.adoption_receipt_sha256 -ceq 'absent') {$null}
                else {$record.origin.adoption_receipt_sha256});shortcuts=$fingerprints}
        [Console]::WriteLine(($result | ConvertTo-Json -Depth 5 -Compress))
        exit 0
    }
    if (Test-Path -LiteralPath $pairRoot) {
        # Pair ownership supplements the normal installation record; it cannot
        # adopt an entry-only migration or reinterpret native recovery evidence.
        if ($hasMigration -or $null -ne $request.recovered_config) { throw 'entry pair scope' }
        Import-Module $request.pair_module -Force -DisableNameChecking
        $ownerDigest = Get-OperatorFingerprint $ownershipFile
        $state = Get-OperatorOwnership $project
        if ((Get-OperatorFingerprint $ownershipFile) -cne $ownerDigest) { throw 'entry owner changed' }
        $pairDigest = Get-OperatorFingerprint (Join-Path $pairRoot 'ownership.json')
        $pair = Get-OperatorDesktopPairRestorePlan $project
        if ($pair.status -cne 'ready' -or $pair.receipt_sha256 -cne $pairDigest) { throw 'entry pair unavailable' }
        $record = $pair.record
        $links = @((Join-Path $record.desktop 'ChatGPT 原生入口.lnk'),
            (Join-Path $record.desktop ('ChatGPT 拓展模型 '+$record.build_date.Substring(5)+' 入口.lnk')))
        if ($request.test_shortcuts) {
            if (@($request.test_shortcuts).Count -ne 2 -or
                @($links | Where-Object {$_ -notin $request.test_shortcuts}).Count) { throw 'entry pair fixture' }
        } else {
            $desktop = [Environment]::GetFolderPath('DesktopDirectory')
            if (-not $desktop -or [IO.Path]::GetFullPath($record.desktop).TrimEnd('\') -ine
                [IO.Path]::GetFullPath($desktop).TrimEnd('\')) { throw 'entry pair desktop' }
        }
        $nativeFolder = Join-Path $pairRoot ('generations/'+$record.generation)
        $nativeScript = Join-Path $nativeFolder 'operator_native_entry.ps1'
        $nativeShell = Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
        $nativeArguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "'+$nativeScript+'"'
        $shell = New-Object -ComObject WScript.Shell
        $fingerprints = [ordered]@{}
        for ($index=0; $index -lt $links.Count; $index++) {
            $linkPath = $links[$index]
            Assert-OperatorPlainPath $linkPath
            $current = Get-OperatorFingerprint $linkPath
            if ($current -ceq 'absent' -or $current -cne $record.links[$linkPath].after) { throw 'entry pair changed' }
            $shortcut = $shell.CreateShortcut($linkPath)
            $target = if ($index -eq 0) {$nativeShell} else {$binary}
            $arguments = if ($index -eq 0) {$nativeArguments} else {''}
            $directory = if ($index -eq 0) {$nativeFolder} else {$bundle}
            if ($shortcut.TargetPath -ine $target -or $shortcut.Arguments -cne $arguments -or
                $shortcut.WorkingDirectory -ine $directory) { throw 'entry pair shortcut target' }
            $fingerprints[$linkPath] = $current
        }
        $confirmed = Get-OperatorDesktopPairRestorePlan $project
        if ($confirmed.status -cne 'ready' -or $confirmed.receipt_sha256 -cne $pair.receipt_sha256 -or
            (Get-OperatorFingerprint $ownershipFile) -cne $ownerDigest) { throw 'entry pair changed' }
        $result = [ordered]@{scope='desktop_pair';owner_sha256=$ownerDigest;
            pair_receipt_sha256=$pair.receipt_sha256;upgrade_receipt_sha256=$null;
            adoption_receipt_sha256=$null;shortcuts=$fingerprints}
        [Console]::WriteLine(($result | ConvertTo-Json -Depth 5 -Compress))
        exit 0
    }
    $links = @(Get-OperatorDesktopPaths)
    if ($links.Count -ne 2) { throw 'entry links' }
    if ($hasMigration) {
        $state = Get-OperatorEntryMigrationState $project
        if ($state.phase -cne 'installed' -or $state.runtime_ownership -cne 'unresolved' -or
            $state.entries.Count -ne 2) { throw 'entry migration' }
        $build = Get-OperatorEntryUpgradeBuild $project $state
        if ($build.Count -ne 5) { throw 'entry build' }
        foreach ($name in $build.Keys) {
            $expected = $build[$name]
            if ($name -ceq 'desktop-entry.json' -and $request.recovered_config) {
                if ($request.recovered_config.before_sha256 -cne $expected) { throw 'recovered entry original' }
                $expected = $request.recovered_config.after_sha256
            }
            if ((Get-OperatorFingerprint (Join-Path $bundle $name)) -cne $expected) {
                throw 'entry build'
            }
        }
        $ownerFile = $migrationFile
    } else {
        $state = Get-OperatorOwnership $project
        $ownerFile = $ownershipFile
    }
    $fingerprints = [ordered]@{}
    $shell = New-Object -ComObject WScript.Shell
    foreach ($linkPath in $links) {
        Assert-OperatorPlainPath $linkPath
        if (-not $state.entries.Contains($linkPath)) { throw 'entry link ownership' }
        $row = $state.entries[$linkPath]
        $current = Get-OperatorFingerprint $linkPath
        $ownedAfter = if ($hasMigration) {
            Get-OperatorEntryAdoptionAfter $project $state $linkPath -CheckCurrent
        } else { $row.after }
        if ($row.status -cne 'installed' -or $current -eq 'absent' -or $current -cne $ownedAfter) {
            throw 'entry link changed'
        }
        $originalRoot = if ($hasMigration) {'operator-entry-migration'} else {'operator-installation'}
        if ($row.before -ne 'absent' -and
            (Get-OperatorFingerprint (Join-Path $project ('.codex/'+$originalRoot+'/originals/'+$row.before+'.bin'))) -cne $row.before) {
            throw 'entry original changed'
        }
        $shortcut = $shell.CreateShortcut($linkPath)
        if ($shortcut.TargetPath -ine $binary -or $shortcut.Arguments -or
            $shortcut.WorkingDirectory -ine $bundle) { throw 'entry shortcut target' }
        $fingerprints[$linkPath] = $current
    }
    $upgradeFile = Join-Path $project '.codex/operator-entry-upgrade/receipt.json'
    $result = [ordered]@{scope=$(if ($hasMigration) {'entry_only_migration'} else {'installation'});
        owner_sha256=(Get-OperatorFingerprint $ownerFile);
        upgrade_receipt_sha256=$(if (Test-Path -LiteralPath $upgradeFile) {Get-OperatorFingerprint $upgradeFile} else {$null});
        adoption_receipt_sha256=$(if ($hasMigration -and (Test-Path -LiteralPath (Join-Path $project '.codex/operator-entry-shortcut-adoption/receipt.json'))) {
            Get-OperatorFingerprint (Join-Path $project '.codex/operator-entry-shortcut-adoption/receipt.json')
        } else {$null});
        shortcuts=$fingerprints}
    [Console]::WriteLine(($result | ConvertTo-Json -Depth 5 -Compress))
    exit 0
} catch { exit 1 }
'''
    request = {"setup": str(Path(__file__).resolve().with_name("operator_desktop_setup.ps1")),
               "pair_module": str(Path(__file__).resolve().with_name("operator_desktop_pair.psm1")),
               "legacy_pair_module": str(Path(__file__).resolve().with_name("operator_desktop_pair_legacy.psm1")),
               "project": str(project), "bundle": str(bundle),
               "recovered_config": recovered_config,
               "test_shortcuts": None if test_shortcuts is None else [str(p) for p in test_shortcuts]}
    try:
        result = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps(request), text=True, encoding="utf-8", capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise ValueError("entry not owned")
        value = json.loads(result.stdout)
        expected_keys = {"scope", "owner_sha256", "upgrade_receipt_sha256", "adoption_receipt_sha256", "shortcuts"}
        if isinstance(value, dict) and value.get("scope") in {"desktop_pair", "legacy_pair"}:
            expected_keys.add("pair_receipt_sha256")
        if isinstance(value, dict) and value.get("scope") == "legacy_pair":
            expected_keys.add("pair_origin_sha256")
        if (not isinstance(value, dict) or set(value) !=
                expected_keys
                or value["scope"] not in {"entry_only_migration", "installation", "desktop_pair", "legacy_pair"}
                or not re.fullmatch(r"[a-f0-9]{64}", value["owner_sha256"])
                or not isinstance(value["shortcuts"], dict)
                or len(value["shortcuts"]) != 2
                or any(not re.fullmatch(r"[a-f0-9]{64}", digest)
                       for digest in value["shortcuts"].values())
                or (value["upgrade_receipt_sha256"] is not None and
                    not re.fullmatch(r"[a-f0-9]{64}", value["upgrade_receipt_sha256"]))
                or (value["adoption_receipt_sha256"] is not None and
                    not re.fullmatch(r"[a-f0-9]{64}", value["adoption_receipt_sha256"]))
                or (value["scope"] in {"desktop_pair", "legacy_pair"} and
                    (not isinstance(value["pair_receipt_sha256"], str)
                     or not re.fullmatch(r"[a-f0-9]{64}", value["pair_receipt_sha256"])))
                or (value["scope"] == "desktop_pair" and
                    (value["upgrade_receipt_sha256"] is not None
                     or value["adoption_receipt_sha256"] is not None))
                or (value["scope"] == "legacy_pair" and
                    (not isinstance(value["pair_origin_sha256"], str)
                     or not re.fullmatch(r"[a-f0-9]{64}", value["pair_origin_sha256"])))):
            raise ValueError("entry evidence malformed")
        return candidate.digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        raise PreviewError("unified_entry_shortcuts_unverified") from exc


def _recovery_blockers(project: Path) -> list[str]:
    bundle = project / ".codex/operator-native-recovery"
    if not bundle.is_dir():
        return ["unified_recovery_shortcut_unverified"]
    try:
        _directory(bundle)
        raw = _read(bundle / "ownership.json", limit=16384)
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict)
                or set(receipt) != {"schema_version", "project", "shortcut", "shortcut_sha256", "files"}
                or receipt["schema_version"] != 1 or receipt["project"] != str(project)
                or not isinstance(receipt["files"], dict)
                or set(receipt["files"]) != set(RECOVERY_FILES)
                or not isinstance(receipt["shortcut"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", receipt["shortcut_sha256"])):
            return ["unified_recovery_shortcut_unverified"]
        installed = {name: _read(bundle / name) for name in RECOVERY_FILES}
        if any(receipt["files"][name] != candidate.digest(installed[name]) for name in RECOVERY_FILES):
            return ["unified_recovery_shortcut_unverified"]
        sources = Path(__file__).resolve().parent
        if any(_read(sources / name) != installed[name] for name in RECOVERY_FILES):
            return ["unified_recovery_source_mismatch"]
        link = Path(receipt["shortcut"])
        if (not link.is_absolute() or link.name != "恢复官方默认路由.lnk"
                or not _verify_shortcut(project, link)
                or candidate.digest(_read(link)) != receipt["shortcut_sha256"]):
            return ["unified_recovery_shortcut_unverified"]
    except (PreviewError, candidate.CandidateError, OSError, ValueError, TypeError, KeyError):
        return ["unified_recovery_shortcut_unverified"]
    return []


def _render_blocker(before: bytes, base: str) -> tuple[str | None, bytes | None]:
    try:
        _, _, rendered = candidate.render(before, base)
        return None, rendered
    except candidate.CandidateError as exc:
        return ("unified_existing_route_conflict" if str(exc) in ROUTE_CONFLICTS
                else "unified_candidate_config_incompatible"), None


def _inventory(project: Path, home: Path) -> tuple[bytes, dict]:
    project, home = _directory(project), _directory(home)
    raw = _read(home / "config.toml", optional=True)
    before = b"" if raw is None else raw
    blockers = []
    if _present(home / "operator-native-route-only"):
        blockers.append("unified_native_route_lock_active")
    old = project / ".codex/operator-web-startup"
    retirement_artifacts = ("legacy-activation-retirement.json", "legacy-activation-original.json",
                            "legacy-activation-retired.json")
    if _present(old / "activation.json"):
        blockers.append("unified_old_activation_record_requires_review")
    elif any(_present(old / name) for name in retirement_artifacts):
        from operator_web_activation_retire import retirement_status
        if retirement_status(old / "web-startup.json") != "retired":
            blockers.append("unified_old_activation_record_requires_review")
    blockers.extend(_recovery_blockers(project))
    render_blocker, _ = _render_blocker(before, INVENTORY_BASE)
    if render_blocker is not None:
        blockers.append(render_blocker)
    report = {"status": "blocked" if blockers else "inspected",
              "blockers": blockers, "current_sha256": candidate.digest(before),
              "candidate_sha256": None, "configuration_changed": False,
              "activation_available": False, "model_requests": 0}
    return before, report


def inventory(project: Path, home: Path) -> dict:
    """Inspect local blockers without requiring a router token or service."""
    return _inventory(project, home)[1]


def preview(project: Path, home: Path, router_state: Path, port: int) -> dict:
    """Hash a possible config; never persist it or test a model request."""
    before, report = _inventory(project, home)
    state = _directory(router_state)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PreviewError("unified_preview_router_identity_unavailable")
    token = _read(state / "token", limit=128)
    try:
        token_text = token.decode("ascii").strip()
    except UnicodeError as exc:
        raise PreviewError("unified_preview_router_identity_unavailable") from exc
    if re.fullmatch(r"[a-f0-9]{64}", token_text) is None:
        raise PreviewError("unified_preview_router_identity_unavailable")
    base = f"http://127.0.0.1:{port}/{token_text}/backend-api/codex"
    blocker, rendered = _render_blocker(before, base)
    blockers = [value for value in report["blockers"] if value not in
                ("unified_existing_route_conflict", "unified_candidate_config_incompatible")]
    if blocker is not None:
        blockers.append(blocker)
    report.update(status="blocked" if blockers else "candidate_preview",
                  blockers=blockers,
                  candidate_sha256=None if rendered is None else candidate.digest(rendered))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "preview"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--router-state", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    try:
        if args.action == "inventory":
            if args.router_state is not None or args.port is not None:
                parser.error("inventory does not select a router")
            result = inventory(args.project_root, args.codex_home)
        else:
            if args.router_state is None or args.port is None:
                parser.error("preview requires router state and port")
            result = preview(args.project_root, args.codex_home, args.router_state, args.port)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (PreviewError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, PreviewError) else "unified_preview_unavailable"
        print(json.dumps({"status": "unavailable", "reason": reason,
                          "configuration_changed": False, "model_requests": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
