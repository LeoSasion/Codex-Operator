"""Real shortcut identity and legacy evidence in disposable Windows folders."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

from test_entry_migration import EntryMigrationTests, ROOT


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class LegacyPairTests(EntryMigrationTests):
    # Reuse only the fixture, not its inherited test methods (see load_tests).
    def setUp(self):
        super().setUp()
        self.project = self.root
        self.desktop = self.root/'fake-desktop'
        self.start = self.root/'fake-programs/Codex拓展入口.lnk'
        self.home = self.root/'disposable-home'
        self.bundle = self.root/'.codex/operator-desktop-entry'
        self.pair_root = self.root/'.codex/operator-desktop-pair'
        self.assert_ok(self.run_ps("""
$review=Get-OperatorEntryMigrationPlan $p $receipt $startup
Invoke-OperatorEntryMigration $p $receipt $startup $review.sha256 | Out-Null
$selectedHome=Join-Path $p 'disposable-home';New-Item -ItemType Directory -Path $selectedHome | Out-Null
[IO.File]::WriteAllText((Join-Path $selectedHome 'config.toml'),'# disposable native configuration')
"""))
        self.bootstrap += """
Import-Module UPGRADE -DisableNameChecking
$legacy=Import-Module LEGACY -PassThru -DisableNameChecking
& $legacy {
 param($P)
 $script:FixtureHome=Join-Path $P 'disposable-home'
 function script:Get-LegacyPairHome {return $script:FixtureHome}
 & $script:LegacyEntry {
  param($P)
  $script:FixtureDesktop=Join-Path $P 'fake-desktop/Codex拓展入口.lnk'
  $script:FixtureStart=Join-Path $P 'fake-programs/Codex拓展入口.lnk'
  function script:Get-OperatorDesktopPaths { @($script:FixtureDesktop,$script:FixtureStart) }
 } $P
} $p
""".replace('LEGACY', self.q(ROOT/'scripts/operator_desktop_pair_legacy.psm1')).replace('UPGRADE', self.q(ROOT/'scripts/operator_desktop_pair_upgrade.psm1'))
        self.assert_ok(self.run_ps("""
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p
[IO.File]::WriteAllText((Join-Path $p 'candidate-path.txt'),$candidate.candidate_directory)
"""))
        self.candidate = Path((self.root/'candidate-path.txt').read_text(encoding='utf8'))

    def apply(self):
        result = self.run_ps("""
$candidate=[IO.File]::ReadAllText((Join-Path $p 'candidate-path.txt'))
$review=Get-OperatorDesktopLegacyPairPlan -ProjectRoot $p -CandidateDirectory $candidate
Invoke-OperatorDesktopLegacyPair -ProjectRoot $p -CandidateDirectory $candidate -ExpectedPlanSha256 $review.sha256 | ConvertTo-Json -Compress
""")
        self.assert_ok(result)
        return json.loads(result.stdout)

    def direct_candidate(self):
        folder = self.project / '.codex/operator-direct-startup'
        plan = folder / ('plans/' + 'c' * 32 + '/plan.json')
        plan.parent.mkdir(parents=True)
        controller = self.project / 'plugins/feishu-codex-operator/scripts/operator_direct_entry.py'
        controller.parent.mkdir(parents=True)
        controller.write_bytes((ROOT/'scripts/operator_direct_entry.py').read_bytes())
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        python_hash = digest(Path(sys.executable).read_bytes())
        helper = ROOT/'scripts/restore-codex-official-route.ps1'
        helper_hash = digest(helper.read_bytes())
        entry_hash = digest((ROOT/'scripts/operator_desktop_entry.ps1').read_bytes())
        plan.write_text(json.dumps({'schema_version': 1, 'contract': 'operator_direct_entry_plan_v1',
            'fixture': 'immutable bindings, never executed',
            'project': str(self.project), 'home': str(self.home),
            'profile': 'operator-local-fixture', 'display_name': 'Local fixture',
            'python': {'path': sys.executable, 'sha256': python_hash},
            'native_helper': {'path': str(helper), 'sha256': helper_hash},
            'entry_script': {'path': str(self.project/'plugins/feishu-codex-operator/scripts/operator_desktop_entry.ps1'),
                             'sha256': entry_hash}}), encoding='utf8')
        index = folder/'direct-entry-plan.json'
        index.write_text(json.dumps({'schema_version': 1, 'contract': 'direct_profile_picker_v1',
            'project': str(self.project), 'home': str(self.home),
            'python': sys.executable, 'python_sha256': python_hash,
            'native_helper': str(helper), 'native_helper_sha256': helper_hash,
            'controller': str(controller), 'controller_sha256': digest(controller.read_bytes()),
            'entry_script_sha256': entry_hash,
            'profiles': [{'profile': 'operator-local-fixture', 'display_name': 'Local fixture',
                          'plan': str(plan), 'plan_sha256': digest(plan.read_bytes())}]}), encoding='utf8')
        self.assert_ok(self.run_ps(f"""
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p -DirectPickerPath {self.q(index)}
[IO.File]::WriteAllText((Join-Path $p 'candidate-path.txt'),$candidate.candidate_directory)
"""))
        self.candidate = Path((self.root/'candidate-path.txt').read_text(encoding='utf8'))
        return index, controller

    def test_direct_workflow_retains_index_and_legacy_origin(self):
        self.apply()
        before = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        original = {p: p.read_bytes() for p in (self.start,
            self.root/'.codex/operator-entry-migration/journal.json',
            self.pair_root/'legacy-origin.json')}
        config = (self.home/'config.toml').read_bytes()
        index, _ = self.direct_candidate()
        self.apply()
        after = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        self.assertEqual(after['steps'][0], before['steps'][0])
        self.assertEqual(after['steps'][-1]['workflow']['contract'], 'direct_profile_picker_v1')
        saved = self.pair_root/'generations'/after['generation']/'direct-entry-plan.after.json'
        self.assertEqual(saved.read_bytes(), index.read_bytes())
        self.assertEqual(after['runtime_ownership'], 'unresolved')
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        self.assertEqual((self.home/'config.toml').read_bytes(), config)
        self.assertFalse((self.root/'.codex/operator-installation/ownership.json').exists())
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))

    def isolated_candidate(self):
        folder = self.project / '.codex/operator-mode-entry' / ('d' * 32)
        folder.mkdir(parents=True)
        (folder / 'entry.ps1').write_bytes(b'# isolated fixture; never launched\n')
        controller = self.project / 'plugins/feishu-codex-operator/scripts/operator_mode_entry.py'
        controller.parent.mkdir(parents=True, exist_ok=True)
        controller.write_text("import json\nprint(json.dumps({'phase':'checked','official_package_matches':True,"
                              "'native_enabled':False,'native_config_writes':0,'model_requests_sent_by_controller':0}))\n",
                              encoding='utf8')
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        index = folder / 'entry.json'
        index.write_text(json.dumps({'schema_version': 1, 'contract': 'operator_isolated_mode_entry_v1',
            'project': str(self.project), 'root': str(folder), 'native_home': str(self.home),
            'native_enabled': False, 'entry_sha256': digest(folder / 'entry.ps1'),
            'python': sys.executable, 'python_sha256': digest(Path(sys.executable)),
            'source_bindings': {'operator_mode_entry.py': digest(controller)}}), encoding='utf8')
        self.assert_ok(self.run_ps(f"""
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p -IsolatedModePath {self.q(index)}
[IO.File]::WriteAllText((Join-Path $p 'candidate-path.txt'),$candidate.candidate_directory)
"""))
        self.candidate = Path((self.root / 'candidate-path.txt').read_text(encoding='utf8'))
        return index

    def test_isolated_mode_upgrade_retains_legacy_chain_and_native_activation_contract(self):
        self.apply()
        before = json.loads((self.pair_root / 'ownership.json').read_text(encoding='utf8'))
        preserved = {p: p.read_bytes() for p in (self.start, self.home / 'config.toml',
                     self.root / '.codex/operator-entry-migration/journal.json', self.pair_root / 'legacy-origin.json')}
        index = self.isolated_candidate()
        self.apply()
        after = json.loads((self.pair_root / 'ownership.json').read_text(encoding='utf8'))
        self.assertEqual(after['steps'][:-1], before['steps'])
        self.assertEqual(after['steps'][-1]['workflow']['contract'], 'operator_isolated_mode_entry_v1')
        generation = self.pair_root / 'generations' / after['generation']
        self.assertEqual((generation / 'isolated-entry.after.json').read_bytes(), index.read_bytes())
        native = json.loads((generation / 'native-entry.json').read_text(encoding='utf8'))
        self.assertEqual(native['activation_mode'], 'registered_application_v1')
        self.assertEqual({p: p.read_bytes() for p in preserved}, preserved)
        self.assertEqual(after['runtime_ownership'], 'unresolved')
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))
        self.assert_ok(self.run_ps('Restore-OperatorDesktopLegacyPair $p | Out-Null'))

    def test_isolated_descriptor_change_rejects_pair_publish_without_overwriting(self):
        self.apply()
        index = self.isolated_candidate()
        before = {p: p.read_bytes() for folder in (self.bundle, self.desktop, self.start.parent)
                  for p in folder.iterdir() if p.is_file()}
        result = self.run_ps(f"""
$candidate=[IO.File]::ReadAllText((Join-Path $p 'candidate-path.txt'))
$review=Get-OperatorDesktopLegacyPairPlan $p $candidate
[IO.File]::AppendAllText({self.q(index)},' ')
Invoke-OperatorDesktopLegacyPair $p $candidate $review.sha256
""")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('isolated_entry_changed', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_direct_dependency_change_blocks_before_entry_writes(self):
        self.apply()
        _, controller = self.direct_candidate()
        before = {p: p.read_bytes() for folder in (self.bundle, self.desktop, self.start.parent)
                  for p in folder.iterdir() if p.is_file()}
        receipt = (self.pair_root/'ownership.json').read_bytes()
        result = self.run_ps(f"""
$candidate=[IO.File]::ReadAllText((Join-Path $p 'candidate-path.txt'))
$review=Get-OperatorDesktopLegacyPairPlan $p $candidate
[IO.File]::AppendAllText({self.q(controller)},'# changed after reviewed preview')
Invoke-OperatorDesktopLegacyPair $p $candidate $review.sha256
""")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dependency_changed', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertEqual((self.pair_root/'ownership.json').read_bytes(), receipt)

    def test_synthetic_recovery_transition_preserves_prior_build_chain(self):
        # The archive verifier is tested with real retained transactions in
        # test_unified_retire. Here only its returned, exact witness is mocked.
        self.apply()
        before = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        target = self.bundle/'desktop-entry.json'
        old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        config = json.loads(target.read_text(encoding='utf8'))
        config['mode'] = 'native'
        target.write_text(json.dumps(config), encoding='utf8')
        native_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        self.bootstrap += f"""
& $legacy {{
 function script:Get-LegacyArchivedEntryWitness {{
  param($Project,$Home,$BeforeSha256,$AfterSha256,$Workflow,[switch]$Historical)
  if ($BeforeSha256 -cne '{old_hash}' -or $AfterSha256 -cne '{native_hash}') {{throw 'fixture_witness_mismatch'}}
  return @{{contract='archived_unified_entry_recovery_v1';before_sha256=$BeforeSha256;after_sha256=$AfterSha256;
   archive_witness_sha256='{('a' * 64)}';retirement_intent_sha256='{('b' * 64)}'}}
 }}
}}
"""
        self.direct_candidate()
        self.apply()
        after = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        self.assertEqual(after['steps'][0], before['steps'][0])
        self.assertEqual(after['steps'][-1]['before']['desktop-entry.json'], native_hash)
        self.assertEqual(after['steps'][-1]['recovered_entry']['before_sha256'], old_hash)
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))
        record = self.pair_root/'ownership.json'
        after['steps'][-1]['before']['operator_desktop_entry.ps1'] = 'e' * 64
        record.write_text(json.dumps(after), encoding='utf8')
        result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_recovery_chain_invalid', result.stderr)

    def test_legacy_pair_rename_keeps_identity_receipts_and_restores_original_path(self):
        journal = self.root/'.codex/operator-entry-migration/journal.json'
        original = journal.read_bytes()
        old = self.desktop/'Codex拓展入口.lnk'
        old_bytes = old.read_bytes()
        start_bytes = self.start.read_bytes()
        self.assertEqual(self.apply()['status'], 'legacy_pair_installed')
        record = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        dated = self.desktop/f"ChatGPT 拓展模型 {record['build_date'][5:]} 入口.lnk"
        self.assertFalse(old.exists())
        self.assertEqual(dated.read_bytes(), old_bytes)
        self.assertEqual(journal.read_bytes(), original)
        self.assertEqual(self.start.read_bytes(), start_bytes)
        self.assertFalse((self.root/'.codex/operator-installation/ownership.json').exists())
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))
        self.assert_ok(self.run_ps('Restore-OperatorDesktopLegacyPair $p | Out-Null'))
        self.assertEqual(old.read_bytes(), old_bytes)
        self.assertFalse(dated.exists())
        self.assertFalse((self.desktop/'ChatGPT 原生入口.lnk').exists())
        self.assert_ok(self.run_ps('Restore-OperatorEntryMigration $p | Out-Null'))
        self.assertTrue((self.bundle/'native-only').exists())
        self.assertTrue((self.pair_root/'generations'/record['generation']/'operator_native_entry.ps1').exists())

    def test_public_preview_hash_survives_independent_processes_and_upgrade(self):
        setup = self.q(ROOT/'scripts/operator_desktop_setup.ps1')
        arguments = (f" -ProjectRoot $p -CandidateDirectory {self.q(self.candidate)}"
                     f" -CodexHome {self.q(self.home)}")
        journal = self.root/'.codex/operator-entry-migration/journal.json'
        old = self.desktop/'Codex拓展入口.lnk'
        before = {path: path.read_bytes() for folder in (self.bundle, self.desktop, self.start.parent,
                  journal.parent) for path in folder.rglob('*') if path.is_file()}
        previews = []
        for _ in range(3):
            result = self.run_ps(f"& {setup} -Action preview-pair-upgrade" + arguments)
            self.assert_ok(result)
            previews.append(json.loads(result.stdout))
        self.assertEqual({preview['plan_sha256'] for preview in previews}, {previews[0]['plan_sha256']})
        self.assertTrue(all(preview['scope'] == 'legacy_pair_upgrade' for preview in previews))
        self.assertFalse(self.pair_root.exists())
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        # Detached maintenance may inherit CP936. The public CLI must emit its
        # complete Chinese notice and JSON as UTF-8, without a decoding fallback.
        result = self.run_ps("[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936)\n"+
                             f"& {setup} -Action upgrade-pair" + arguments +
                             f" -ExpectedPlanSha256 {self.q(previews[0]['plan_sha256'])}")
        self.assert_ok(result)
        self.assertIn('本次保留旧入口回执及运行时未决归属', result.stdout)
        self.assertIn('legacy_pair_installed', result.stdout)
        record = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        dated = self.desktop/f"ChatGPT 拓展模型 {record['build_date'][5:]} 入口.lnk"
        self.assertFalse(old.exists())
        self.assertEqual(dated.read_bytes(), before[old])
        self.assertEqual(journal.read_bytes(), before[journal])
        self.assertEqual(self.start.read_bytes(), before[self.start])
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))

    def test_legacy_pair_later_edits_pending_and_origin_changes_rejected(self):
        self.apply()
        record = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        native = self.desktop/'ChatGPT 原生入口.lnk'
        original = native.read_bytes()
        native.write_bytes(b'later user edit')
        result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_native_link_changed', result.stderr)
        native.write_bytes(original)
        pending = self.pair_root/'upgrades'/('f'*32)
        pending.mkdir(); (pending/'pending.json').write_text('{}')
        result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertIn('legacy_pair_pending_requires_review', result.stderr)
        shutil.rmtree(pending)
        origin = self.pair_root/'legacy-origin.json'
        origin.write_bytes(origin.read_bytes()+b' ')
        result = self.run_ps('Restore-OperatorDesktopLegacyPair $p')
        self.assertIn('legacy_pair_origin_invalid', result.stderr)
        self.assertEqual(native.read_bytes(), original)

    def test_legacy_pair_build_upgrade_retains_link_entity_and_validates_chain(self):
        self.apply()
        before = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        result = self.run_ps("""
$candidate=New-OperatorEntryBuildCandidate -ProjectRoot $p
$review=Get-OperatorDesktopLegacyPairPlan -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory
Invoke-OperatorDesktopLegacyPair -ProjectRoot $p -CandidateDirectory $candidate.candidate_directory -ExpectedPlanSha256 $review.sha256 | Out-Null
Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null
""")
        self.assert_ok(result)
        after = json.loads((self.pair_root/'ownership.json').read_text(encoding='utf8'))
        self.assertEqual(len(after['steps']), 2)
        self.assertEqual(after['steps'][1]['before'], before['build'])
        self.assertEqual(after['legacy'], before['legacy'])
        self.assertNotEqual(after['generation'], before['generation'])

    def test_preview_rejects_changed_originals_and_workflow_before_public_writes(self):
        migration=json.loads((self.root/'.codex/operator-entry-migration/journal.json').read_text(encoding='utf8'))
        originals=[Path(migration['plan']['receipt']),Path(migration['plan']['legacy_executable'])]
        originals += [self.root/'.codex/operator-entry-migration/originals'/f"{r['before']}.bin"
                      for r in migration['entries'].values() if r['before'] != 'absent']
        for path in originals:
            with self.subTest(original=path.name):
                before=path.read_bytes();path.write_bytes(before+b'changed')
                result=self.run_ps('Get-OperatorDesktopLegacyPairPlan $p '+self.q(self.candidate))
                self.assertNotEqual(result.returncode,0)
                self.assertIn('legacy_pair_original_evidence_changed',result.stderr)
                self.assertFalse(self.pair_root.exists())
                path.write_bytes(before)
        result=self.run_ps("""
$candidate=[IO.File]::ReadAllText((Join-Path $p 'candidate-path.txt'))
$review=Get-OperatorDesktopLegacyPairPlan $p $candidate
[IO.File]::AppendAllText((Join-Path $startup 'start-codex-with-web.ps1'),'# changed after preview')
Invoke-OperatorDesktopLegacyPair $p $candidate $review.sha256
""")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('legacy_pair_workflow_changed',result.stderr)
        self.assertFalse(self.pair_root.exists())

    def test_corrupted_new_backup_blocks_before_rename_and_build_writes(self):
        before={str(p):p.read_bytes() for d in (self.bundle,self.desktop,self.start.parent) for p in d.iterdir() if p.is_file()}
        result=self.run_ps("""
& $legacy {
 param($P)
 & $script:LegacyPair {
  param($P)
  $script:FixtureProject=$P
  $script:SavedShortcut=${function:New-OperatorPairShortcut}
  function script:New-OperatorPairShortcut {
   param($Path,$Target,$Arguments,$WorkingDirectory,$Description)
   $bytes=& $script:SavedShortcut $Path $Target $Arguments $WorkingDirectory $Description
   [IO.File]::AppendAllText((Join-Path $script:FixtureProject '.codex/operator-desktop-pair/originals/migration.json'),' ')
   return ,$bytes
  }
 } $P
} $p
$candidate=[IO.File]::ReadAllText((Join-Path $p 'candidate-path.txt'))
$review=Get-OperatorDesktopLegacyPairPlan $p $candidate
Invoke-OperatorDesktopLegacyPair $p $candidate $review.sha256
""")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('legacy_pair_backup_changed',result.stderr)
        self.assertEqual({p:Path(p).read_bytes() for p in before},before)
        self.assertFalse((self.pair_root/'ownership.json').exists())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(LegacyPairTests(name) for name in LegacyPairTests.__dict__ if name.startswith('test_'))
