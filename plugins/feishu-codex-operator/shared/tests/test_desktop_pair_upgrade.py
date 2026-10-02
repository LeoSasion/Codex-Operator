"""Reviewed build replacement using disposable real links and compiled candidates."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PWSH = shutil.which("pwsh")


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(value):
    return hashlib.sha256(value).hexdigest()


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell required")
class DesktopPairUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="operator-pair-upgrade-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.desktop = self.project / "desktop"
        self.home = self.project / "home"
        self.desktop.mkdir()
        self.home.mkdir()
        self.bundle = self.project / ".codex/operator-desktop-entry"
        self.bundle.mkdir(parents=True)
        self.root = self.project / ".codex/operator-desktop-pair"
        binary = b"synthetic fixture, never executed"
        entry = b"synthetic installed entry"
        (self.bundle / "Codex拓展入口.exe").write_bytes(binary)
        (self.bundle / "operator_desktop_entry.ps1").write_bytes(entry)
        self.old_date = "2025-01-01"
        self.manifest = {"schema_version": 1, "native_fallback": "native-only-v1",
            "binary_sha256": digest(binary), "entry_script_sha256": digest(entry),
            "build_date": self.old_date, "product_version": "1.2.0-preview.1",
            "shortcut_layout": "paired", "source_sha256": "a" * 64}
        (self.bundle / "launcher-manifest.json").write_text(json.dumps(self.manifest), encoding="utf8")
        (self.bundle / "desktop-entry.json").write_text(json.dumps({"schema_version": 1,
            "mode": "native", "entry_script_sha256": digest(entry)}), encoding="utf8")
        owner = self.project / ".codex/operator-installation/ownership.json"
        owner.parent.mkdir()
        owner.write_text(json.dumps({"schema_version": 1, "project": str(self.project), "entries": {}}))
        self.args = f"-ProjectRoot {q(self.project)} -CodexHome {q(self.home)} -DesktopDirectory {q(self.desktop)}"
        self.ok(self.ps("Install-OperatorDesktopPair " + self.args +
            f" -BuildDate {q(self.old_date)} -Version '1.2.0-preview.1' -SourceDigest {q('a' * 64)} | Out-Null"))
        self.original = self.snapshot()

    def ps(self, code):
        driver = self.project / "driver.ps1"
        prefix = "$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
        prefix += "Import-Module " + q(SCRIPTS / "operator_desktop_pair.psm1") + " -DisableNameChecking\n"
        prefix += "& (Get-Module operator_desktop_pair) {function script:Get-OperatorPairDefaultHome {return " + q(self.home) + "}}\n"
        prefix += "Import-Module " + q(SCRIPTS / "operator_desktop_pair_upgrade.psm1") + " -DisableNameChecking\n"
        driver.write_text(prefix + code, encoding="utf8")
        return subprocess.run([PWSH, "-NoProfile", "-File", str(driver)], capture_output=True,
            text=True, encoding="utf8", timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, "CODEX_HOME": str(self.home), "OPENAI_BASE_URL": ""})

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes() for folder in (self.bundle, self.desktop)
            for p in folder.rglob("*") if p.is_file()} | {
                "pair-receipt": (self.root / "ownership.json").read_bytes()}

    def prepare(self):
        result = self.ok(self.ps(f"New-OperatorEntryBuildCandidate -ProjectRoot {q(self.project)} | ConvertTo-Json -Compress"))
        self.candidate = Path(json.loads(result.stdout)["candidate_directory"])
        return self.candidate

    def review(self):
        result = self.ok(self.ps(f"Get-OperatorDesktopPairUpgrade -ProjectRoot {q(self.project)} "
            f"-CandidateDirectory {q(self.candidate)} | ConvertTo-Json -Depth 30 -Compress"))
        return json.loads(result.stdout)

    def apply(self, sha, prefix=""):
        return self.ps(prefix + f"Invoke-OperatorDesktopPairUpgrade -ProjectRoot {q(self.project)} "
            f"-CandidateDirectory {q(self.candidate)} -ExpectedPlanSha256 {q(sha)} | ConvertTo-Json -Compress")

    def test_compile_preview_upgrade_and_restore_keep_old_native_helpers(self):
        old = json.loads((self.root / "ownership.json").read_text(encoding="utf8"))
        self.prepare()
        self.assertEqual(self.snapshot(), self.original)
        self.assertEqual((self.candidate / "Codex拓展入口.exe").read_bytes()[:2], b"MZ")
        review = self.review()
        self.assertEqual(self.snapshot(), self.original)
        self.ok(self.apply(review["sha256"]))
        current = json.loads((self.root / "ownership.json").read_text(encoding="utf8"))
        self.assertEqual(current["build_date"], datetime.date.today().isoformat())
        self.assertEqual(set(p.name for p in self.desktop.glob("*.lnk")), {
            "ChatGPT 原生入口.lnk", f"ChatGPT 拓展模型 {current['build_date'][5:]} 入口.lnk"})
        self.assertTrue((self.root / "generations" / old["generation"] / "operator_native_entry.ps1").is_file())
        for name in ("Codex拓展入口.exe", "operator_desktop_entry.ps1", "desktop-entry.json", "launcher-manifest.json"):
            self.assertEqual((self.bundle / name).read_bytes(), (self.candidate / name).read_bytes())
        self.ok(self.ps(f"Get-OperatorDesktopPairRestorePlan -ProjectRoot {q(self.project)} | Out-Null\n"
            f"Restore-OperatorDesktopPair -ProjectRoot {q(self.project)} | Out-Null"))
        self.assertEqual(list(self.desktop.glob("*.lnk")), [])
        self.assertTrue((self.root / "generations" / current["generation"] / "operator_native_entry.ps1").is_file())

    def test_stale_review_and_tampered_candidate_do_not_publish(self):
        self.prepare()
        review = self.review()
        result = self.apply("0" * 64)
        self.assertIn("pair_upgrade_preview_changed", result.stderr)
        self.assertEqual(self.snapshot(), self.original)
        (self.candidate / "operator_desktop_entry.ps1").write_bytes(b"tampered")
        result = self.apply(review["sha256"])
        self.assertIn("pair_candidate_changed", result.stderr)
        self.assertEqual(self.snapshot(), self.original)

    def test_pending_direct_cycle_blocks_unbound_build_upgrade(self):
        self.prepare()
        pending=self.home/'operator-direct-entry/cycles'/('f'*32);pending.mkdir(parents=True)
        (pending/'intent.json').write_bytes(b'{"fixture":"pending"}')
        result=self.ps(f"Get-OperatorDesktopPairUpgrade -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('direct_cycle_maintenance_requires_bound_python',result.stderr)
        self.assertEqual(self.snapshot(),self.original)

    def test_direct_picker_build_binds_index_and_preserves_live_entries(self):
        folder = self.project / '.codex/operator-direct-startup'
        plan = folder / ('plans/' + 'c'*32 + '/plan.json')
        plan.parent.mkdir(parents=True)
        controller = self.project / 'plugins/feishu-codex-operator/scripts/operator_direct_entry.py'
        controller.parent.mkdir(parents=True)
        controller.write_bytes((SCRIPTS/'operator_direct_entry.py').read_bytes())
        plan.write_text(json.dumps({'schema_version':1,'contract':'operator_direct_entry_plan_v1',
            'project':str(self.project),'home':str(self.home),'profile':'operator-local-fixture','display_name':'Local fixture',
            'python':{'path':sys.executable,'sha256':digest(Path(sys.executable).read_bytes())},
            'native_helper':{'path':str(SCRIPTS/'restore-codex-official-route.ps1'),'sha256':digest((SCRIPTS/'restore-codex-official-route.ps1').read_bytes())},
            'entry_script':{'path':str(controller.parent/'operator_desktop_entry.ps1'),'sha256':digest((SCRIPTS/'operator_desktop_entry.ps1').read_bytes())}}),encoding='utf8')
        picker = {'schema_version': 1, 'contract': 'direct_profile_picker_v1',
            'project': str(self.project), 'home': str(self.home),
            'python': sys.executable, 'python_sha256': digest(Path(sys.executable).read_bytes()),
            'native_helper': str(SCRIPTS/'restore-codex-official-route.ps1'),
            'native_helper_sha256': digest((SCRIPTS/'restore-codex-official-route.ps1').read_bytes()),
            'controller': str(controller), 'controller_sha256': digest(controller.read_bytes()),
            'entry_script_sha256': digest((SCRIPTS/'operator_desktop_entry.ps1').read_bytes()),
            'profiles': [{'profile': 'operator-local-fixture', 'display_name': 'Local fixture',
                'plan': str(plan), 'plan_sha256': digest(plan.read_bytes())}]}
        index = folder/'direct-entry-plan.json'
        index.write_text(json.dumps(picker), encoding='utf8')
        prepared = self.ok(self.ps(f"New-OperatorEntryBuildCandidate -ProjectRoot {q(self.project)} "
            f"-DirectPickerPath {q(index)} | ConvertTo-Json -Compress"))
        candidate = Path(json.loads(prepared.stdout)['candidate_directory'])
        self.assertEqual(self.snapshot(), self.original)
        config = json.loads((candidate/'desktop-entry.json').read_text(encoding='utf8'))
        self.assertEqual(config['mode'], 'direct_profile')
        self.assertEqual(config['direct_entry_plan_sha256'], digest(index.read_bytes()))
        self.ok(self.ps(f"Get-OperatorEntryBuildCandidate {q(self.project)} {q(candidate)} | Out-Null"))
        index.write_bytes(index.read_bytes()+b'changed')
        result = self.ps(f"Get-OperatorEntryBuildCandidate {q(self.project)} {q(candidate)} | Out-Null")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('direct_picker_changed', result.stderr)
        self.assertEqual(self.snapshot(), self.original)

    def test_public_preview_hash_survives_independent_processes_and_upgrade(self):
        self.prepare()
        setup = q(SCRIPTS / 'operator_desktop_setup.ps1')
        arguments = (f" -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}"
                     f" -CodexHome {q(self.home)}")
        previews = [json.loads(self.ok(self.ps(f"& {setup} -Action preview-pair-upgrade" + arguments)).stdout)
                    for _ in range(3)]
        self.assertEqual({preview['plan_sha256'] for preview in previews}, {previews[0]['plan_sha256']})
        self.assertTrue(all(preview['scope'] == 'desktop_pair_build_upgrade' for preview in previews))
        self.assertEqual(self.snapshot(), self.original)
        result = self.ok(self.ps(f"& {setup} -Action upgrade-pair" + arguments +
                                f" -ExpectedPlanSha256 {q(previews[0]['plan_sha256'])}"))
        self.assertEqual(json.loads(result.stdout)['status'], 'pair_upgraded')
        current = json.loads((self.root / 'ownership.json').read_text(encoding='utf8'))
        self.assertEqual(current['generation'], self.candidate.name)
        for name in ('Codex拓展入口.exe', 'operator_desktop_entry.ps1', 'desktop-entry.json', 'launcher-manifest.json'):
            self.assertEqual((self.bundle / name).read_bytes(), (self.candidate / name).read_bytes())
        self.ok(self.ps(f"Get-OperatorDesktopPairRestorePlan -ProjectRoot {q(self.project)} | Out-Null"))

    def test_preview_canonicalization_keeps_array_order_and_scalar_shapes(self):
        result = self.ok(self.ps(r'''
& (Get-Module operator_desktop_pair_upgrade) {
    $first=[ordered]@{z=@([ordered]@{b=2;a=1},$null,@(),@(7));a=[ordered]@{b=$false;A='';null=$null}}
    $second=[ordered]@{a=[ordered]@{null=$null;A='';b=$false};z=@([ordered]@{a=1;b=2},$null,@(),@(7))}
    $changed=[ordered]@{a=$first.a;z=@($null,[ordered]@{b=2;a=1},@(),@(7))}
    $value=ConvertTo-OperatorPairPreviewValue $first
    $edge=[Collections.Specialized.OrderedDictionary]::new([StringComparer]::Ordinal)
    $edge.Add('keys','literal');$edge.Add('a',2);$edge.Add('A',1)
    $edge.Add('nested',@(@(),@('x'),@($null)));$edge.Add('single',@($null));$edge.Add('zero',0)
    @{first=(Get-OperatorPairPreviewHash $first);second=(Get-OperatorPairPreviewHash $second);
      changed=(Get-OperatorPairPreviewHash $changed);value=$value;edge=(ConvertTo-OperatorPairPreviewValue $edge);
      original_keys=@($first.Keys);original_nested_keys=@($first.z[0].Keys)} | ConvertTo-Json -Depth 20 -Compress
}
'''))
        data = json.loads(result.stdout)
        self.assertEqual(data['first'], data['second'])
        self.assertNotEqual(data['first'], data['changed'])
        self.assertEqual(data['value'], {'a': {'A': '', 'b': False, 'null': None},
                                         'z': [{'a': 1, 'b': 2}, None, [], [7]]})
        self.assertEqual(list(data['value']), ['a', 'z'])
        self.assertEqual(list(data['value']['a']), ['A', 'b', 'null'])
        self.assertEqual(data['original_keys'], ['z', 'a'])
        self.assertEqual(data['original_nested_keys'], ['b', 'a'])
        self.assertEqual(data['edge'], {'A': 1, 'a': 2, 'keys': 'literal',
                                        'nested': [[], ['x'], [None]], 'single': [None], 'zero': 0})
        self.assertEqual(list(data['edge']), ['A', 'a', 'keys', 'nested', 'single', 'zero'])

    def test_same_day_upgrade_replaces_owned_link_without_accumulating_dates(self):
        self.ok(self.ps(f"Restore-OperatorDesktopPair -ProjectRoot {q(self.project)} | Out-Null"))
        today = datetime.date.today().isoformat()
        self.manifest["build_date"] = today
        (self.bundle / "launcher-manifest.json").write_text(json.dumps(self.manifest), encoding="utf8")
        self.ok(self.ps("Install-OperatorDesktopPair " + self.args +
            f" -BuildDate {q(today)} -Version '1.2.0-preview.1' -SourceDigest {q('a' * 64)} | Out-Null"))
        self.prepare()
        review = self.review()
        self.ok(self.apply(review["sha256"]))
        self.assertEqual(len(list(self.desktop.glob("*.lnk"))), 2)
        self.assertEqual(json.loads((self.root / "ownership.json").read_text(encoding="utf8"))["build_date"], today)

    def test_candidate_keeps_config_fields_and_rejects_forged_mode_even_with_updated_file_hash(self):
        config_file = self.bundle / "desktop-entry.json"
        original = json.loads(config_file.read_text(encoding="utf8"))
        original["additional_state"] = {"explicit_null": None, "value": "retained"}
        config_file.write_text(json.dumps(original), encoding="utf8")
        self.prepare()
        result = self.ps(f"Get-OperatorEntryBuildCandidate -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)} | Out-Null")
        self.ok(result)
        candidate_config = self.candidate / "desktop-entry.json"
        altered = json.loads(candidate_config.read_text(encoding="utf8"))
        self.assertEqual(altered["additional_state"], original["additional_state"])
        altered["mode"] = "reviewed_startup"
        candidate_config.write_text(json.dumps(altered), encoding="utf8")
        candidate_file = self.candidate / "candidate.json"
        record = json.loads(candidate_file.read_text(encoding="utf8"))
        record["files"]["desktop-entry.json"] = digest(candidate_config.read_bytes())
        candidate_file.write_text(json.dumps(record), encoding="utf8")
        result = self.ps(f"Get-OperatorEntryBuildCandidate -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}")
        self.assertIn("pair_candidate_config_changed", result.stderr)
        self.assertEqual(json.loads(config_file.read_text(encoding="utf8")), original)

    def test_pending_activation_route_and_native_marker_block_before_live_write(self):
        self.prepare()
        review = self.review()
        pending = self.home / "operator-unified-activation"
        pending.mkdir()
        self.assertIn("pair_activation_requires_separate_review", self.apply(review["sha256"]).stderr)
        pending.rmdir()
        (self.bundle / "native-only").write_bytes(b"\x01")
        self.assertIn("pair_native_only_requires_review", self.apply(review["sha256"]).stderr)
        (self.bundle / "native-only").unlink()
        (self.home / "config.toml").write_text('# BEGIN FEISHU OPERATOR MODEL ROUTER\nopenai_base_url = "http://127.0.0.1:4317/' + "a" * 64 + '/v1"\n# END FEISHU OPERATOR MODEL ROUTER\n', encoding="utf8")
        self.assertIn("pair_upgrade_native_route_required", self.apply(review["sha256"]).stderr)
        self.assertEqual(self.snapshot(), self.original)

    def test_new_dated_name_collision_and_legacy_origin_are_not_adopted(self):
        self.prepare()
        today = datetime.date.today().isoformat()[5:]
        collision = self.desktop / f"ChatGPT 拓展模型 {today} 入口.lnk"
        collision.write_bytes(b"user link")
        result = self.ps(f"Get-OperatorDesktopPairUpgrade -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}")
        self.assertIn("pair_shortcut_name_conflict", result.stderr)
        self.assertEqual(collision.read_bytes(), b"user link")
        collision.unlink()
        receipt = json.loads((self.root / "ownership.json").read_text(encoding="utf8"))
        receipt["origin"] = {"scope": "legacy_entry_only"}
        (self.root / "ownership.json").write_text(json.dumps(receipt), encoding="utf8")
        result = self.ps(f"Get-OperatorDesktopPairUpgrade -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}")
        self.assertIn("pair_upgrade_normal_owner_required", result.stderr)

    def test_failed_link_write_rolls_back_all_build_bytes_and_keeps_terminal_intent(self):
        self.prepare()
        review = self.review()
        prefix = r'''
& (Get-Module operator_desktop_pair_upgrade) {
    $script:realWrite=(Get-Command Write-OperatorUpgradeChange).ScriptBlock
    function script:Write-OperatorUpgradeChange($Change) {
        if ($Change.path -like '*ChatGPT 拓展模型*.lnk' -and $null -eq $Change.before) {throw 'synthetic_link_failure'}
        & $script:realWrite $Change
    }
}
'''
        result = self.apply(review["sha256"], prefix)
        self.assertIn("synthetic_link_failure", result.stderr)
        self.assertEqual(self.snapshot(), self.original)
        self.assertTrue((self.root / "upgrades" / self.candidate.name / "pending.json").is_file())
        self.assertIn("pair_upgrade_pending_requires_review", self.apply(review["sha256"]).stderr)
        self.assertEqual(self.snapshot(), self.original)

    def test_source_and_native_config_changes_invalidate_preview(self):
        self.prepare()
        review = self.review()
        (self.home / "config.toml").write_text('model = "native-fixture"\n', encoding="utf8")
        self.assertIn("pair_upgrade_preview_changed", self.apply(review["sha256"]).stderr)
        self.assertEqual(self.snapshot(), self.original)
        data = json.loads((self.candidate / "candidate.json").read_text(encoding="utf8"))
        data["sources"]["operator_native_entry.ps1"] = "0" * 64
        (self.candidate / "candidate.json").write_text(json.dumps(data), encoding="utf8")
        result = self.ps(f"Get-OperatorEntryBuildCandidate -ProjectRoot {q(self.project)} -CandidateDirectory {q(self.candidate)}")
        self.assertIn("pair_candidate_source_changed", result.stderr)

    def test_low_level_partial_failure_preserves_later_edit_and_pending(self):
        first = self.project / "one"
        second = self.project / "two"
        first.write_bytes(b"first before")
        second.write_bytes(b"second before")
        transaction = self.project / ".codex/exact-test"
        code = r'''
& (Get-Module operator_desktop_pair_upgrade) {
    $script:realWrite=(Get-Command Write-OperatorUpgradeChange).ScriptBlock
    function script:Write-OperatorUpgradeChange($Change) {
        if ($Change.path -eq ''' + q(second) + r''') {
            [IO.File]::WriteAllText(''' + q(first) + r''','later user edit')
            throw 'synthetic_failure'
        }
        & $script:realWrite $Change
    }
}
$changes=@(
@{path=''' + q(first) + r''';before=[IO.File]::ReadAllBytes(''' + q(first) + r''');after=[Text.Encoding]::UTF8.GetBytes('first after')},
@{path=''' + q(second) + r''';before=[IO.File]::ReadAllBytes(''' + q(second) + r''');after=[Text.Encoding]::UTF8.GetBytes('second after')})
Invoke-OperatorEntryExactTransaction -TransactionRoot ''' + q(transaction) + r''' -Changes $changes -Boundary {}
'''
        result = self.ps(code)
        self.assertIn("synthetic_failure", result.stderr)
        self.assertEqual(first.read_bytes(), b"later user edit")
        self.assertEqual(second.read_bytes(), b"second before")
        self.assertTrue((transaction / "pending.json").is_file())
        self.assertEqual((transaction / "0.before").read_bytes(), b"first before")

    def test_unchanged_locked_file_retains_identity_and_full_transaction(self):
        unchanged = self.project / 'running-launcher-fixture.exe'
        changed = self.project / 'entry-fixture.json'
        unchanged.write_bytes(b'unchanged running launcher bytes')
        changed.write_bytes(b'before')
        transaction = self.project / '.codex/noop-transaction'
        code = r'''
$identity=Get-OperatorEntryMoveIdentity ''' + q(unchanged) + r'''
$bytes=[IO.File]::ReadAllBytes(''' + q(unchanged) + r''')
$held=[IO.File]::Open(''' + q(unchanged) + r''',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try {
    $changes=@(
      @{path=''' + q(unchanged) + r''';before=$bytes;after=$bytes},
      @{path=''' + q(changed) + r''';before=[IO.File]::ReadAllBytes(''' + q(changed) + r''');after=[Text.Encoding]::UTF8.GetBytes('after')})
    Invoke-OperatorEntryExactTransaction -TransactionRoot ''' + q(transaction) + r''' -Changes $changes -Boundary {}
    if ((Get-OperatorEntryMoveIdentity ''' + q(unchanged) + r''') -cne $identity) {throw 'unchanged_file_identity_changed'}
} finally {$held.Dispose()}
'''
        self.ok(self.ps(code))
        self.assertEqual(changed.read_bytes(), b'after')
        self.assertEqual((transaction / '0.before').read_bytes(), unchanged.read_bytes())
        self.assertEqual((transaction / '0.after').read_bytes(), unchanged.read_bytes())
        self.assertTrue((transaction / 'completed.json').is_file())

    def test_exact_move_keeps_file_identity_and_rolls_back_on_later_failure(self):
        source = self.project / "old.lnk"
        destination = self.project / "new.lnk"
        source.write_bytes(b"retained link bytes")
        failing = self.project / "later"
        failing.write_bytes(b"before")
        transaction = self.project / ".codex/move-failure"
        prefix = "$identity=Get-OperatorEntryMoveIdentity " + q(source) + "\n"
        move = "@{source=" + q(source) + ";destination=" + q(destination) + ";sha256=" + q(digest(source.read_bytes())) + ";identity=$identity}"
        code = prefix + r'''
& (Get-Module operator_desktop_pair_upgrade) {
    function script:Write-OperatorUpgradeChange($Change) {throw 'after_move_failure'}
}
$changes=@(@{path=''' + q(failing) + r''';before=[IO.File]::ReadAllBytes(''' + q(failing) + r''');after=[Text.Encoding]::UTF8.GetBytes('after')})
try {Invoke-OperatorEntryExactTransaction -TransactionRoot ''' + q(transaction) + " -Changes $changes -Moves @(" + move + r''') -Boundary {}} catch {
    if ((Get-OperatorEntryMoveIdentity ''' + q(source) + r''') -cne $identity) {throw 'identity changed'}
    throw
}
'''
        result = self.ps(code)
        self.assertIn("after_move_failure", result.stderr)
        self.assertEqual(source.read_bytes(), b"retained link bytes")
        self.assertFalse(destination.exists())
        self.assertTrue((transaction / "pending.json").is_file())
        success = self.project / ".codex/move-success"
        result = self.ok(self.ps(prefix + "Invoke-OperatorEntryExactTransaction -TransactionRoot " + q(success) +
            " -Moves @(" + move + ") -Boundary {}\nif ((Get-OperatorEntryMoveIdentity " + q(destination) +
            ") -cne $identity) {throw 'identity changed'}"))
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_bytes(), b"retained link bytes")
        self.assertTrue((success / "completed.json").is_file())

    def test_activation_arriving_during_private_preparation_preserves_live_pair(self):
        self.prepare()
        review = self.review()
        prefix = r'''
& (Get-Module operator_desktop_pair) {
    $script:realShortcut=(Get-Command New-OperatorPairShortcut).ScriptBlock
    function script:New-OperatorPairShortcut($Path,$Target,$Arguments,$WorkingDirectory,$Description) {
        $bytes=& $script:realShortcut $Path $Target $Arguments $WorkingDirectory $Description
        [void][IO.Directory]::CreateDirectory(''' + q(self.home / "operator-unified-activation") + r''')
        return ,$bytes
    }
}
'''
        result = self.apply(review["sha256"], prefix)
        self.assertIn("pair_activation_requires_separate_review", result.stderr)
        self.assertEqual(self.snapshot(), self.original)

    def test_move_rollback_preserves_a_replaced_destination_with_identical_bytes(self):
        source = self.project / "old.lnk"
        destination = self.project / "new.lnk"
        source.write_bytes(b"same bytes")
        later = self.project / "later"
        later.write_bytes(b"before")
        transaction = self.project / ".codex/move-identity-change"
        code = "$identity=Get-OperatorEntryMoveIdentity " + q(source) + "\n" + r'''
& (Get-Module operator_desktop_pair_upgrade) {
    function script:Write-OperatorUpgradeChange($Change) {
        [IO.File]::Delete(''' + q(destination) + r''')
        [IO.File]::WriteAllText(''' + q(destination) + r''','same bytes')
        throw 'replaced_destination'
    }
}
$moves=@(@{source=''' + q(source) + ";destination=" + q(destination) + ";sha256=" + q(digest(source.read_bytes())) + r''';identity=$identity})
$changes=@(@{path=''' + q(later) + r''';before=[IO.File]::ReadAllBytes(''' + q(later) + r''');after=[Text.Encoding]::UTF8.GetBytes('after')})
try {Invoke-OperatorEntryExactTransaction -TransactionRoot ''' + q(transaction) + r''' -Moves $moves -Changes $changes -Boundary {}} catch {
    if ((Get-OperatorEntryMoveIdentity ''' + q(destination) + r''') -ceq $identity) {throw 'fixture did not replace identity'}
    throw
}
'''
        result = self.ps(code)
        self.assertIn("replaced_destination", result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_bytes(), b"same bytes")
        self.assertEqual(later.read_bytes(), b"before")
        self.assertTrue((transaction / "pending.json").is_file())


if __name__ == "__main__":
    unittest.main()
