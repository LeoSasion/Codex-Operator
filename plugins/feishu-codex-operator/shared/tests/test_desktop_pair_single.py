"""Review an already renamed legacy chooser in disposable Windows folders."""
import json
import hashlib
from pathlib import Path
import unittest

from test_mode_pair_refresh import ModePairRefreshTests


class SingleEntryTests(ModePairRefreshTests):
    def single_fixture(self, *, package=False):
        result = self.staged_package_upgrade() if package else self.staged_refresh()
        self.mode_root, self.stage = result[:2]
        record = json.loads((self.pair_root / 'ownership.json').read_text('utf8'))
        self.native = self.desktop / 'ChatGPT 原生入口.lnk'
        self.dated = self.desktop / ('ChatGPT 拓展模型 ' + record['build_date'][5:] + ' 入口.lnk')
        self.selected = self.desktop / 'ChatGPT 自定义启动.lnk'
        audit = self.project / '.codex/audit/disposable-single-entry'
        audit.mkdir(parents=True)
        self.retained = audit / 'native.lnk'
        self.native.rename(self.retained)
        self.dated.rename(self.selected)
        self.evidence = audit / 'untrusted-claims.json'
        self.evidence.write_text('{"completed":true,"ownership":"not authority"}', encoding='utf8')
        second = audit / 'earlier-sorted-material.json'
        second.write_text('{"different":"untrusted retained material"}', encoding='utf8')
        self.single_root = self.project / '.codex/operator-desktop-single-entry'
        self.review_args = (f'-ProjectRoot $p -RetainedNativeShortcut {self.q(self.retained)} '
                            f'-EvidenceFiles @({self.q(self.evidence)},{self.q(second)})')
        self.preserved = {p: p.read_bytes() for p in (
            self.pair_root / 'ownership.json', self.pair_root / 'legacy-origin.json',
            self.project / '.codex/operator-entry-migration/journal.json',
            self.selected, self.retained, self.start, self.home / 'config.toml')}
        return record

    def preview_single(self):
        result = self.run_ps(f'Get-OperatorDesktopSingleEntryPlan {self.review_args} | ConvertTo-Json -Depth 30 -Compress')
        self.assert_ok(result)
        return json.loads(result.stdout)

    def review_single(self, expected=None):
        expected = expected or self.preview_single()['sha256']
        return self.run_ps(f'Invoke-OperatorDesktopSingleEntryReview {self.review_args} -ExpectedPlanSha256 {expected} | ConvertTo-Json -Compress')

    def test_review_and_package_update_keep_one_entity_and_old_chain(self):
        before = self.single_fixture(package=True)
        denied = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('legacy_pair_shortcut_changed', denied.stderr)
        self.assertFalse(self.single_root.exists())
        self.assert_ok(self.review_single())
        self.assertEqual({p: p.read_bytes() for p in self.preserved}, self.preserved)
        public = self.run_ps('Import-Module PAIR -DisableNameChecking\nGet-OperatorDesktopPairRestorePlan $p | ConvertTo-Json -Depth 30 -Compress'.replace(
            'PAIR', self.q(Path(__file__).resolve().parents[2] / 'scripts/operator_desktop_pair.psm1')))
        self.assert_ok(public)
        self.assertEqual(json.loads(public.stdout)['status'], 'ready')
        preview = self.invoke(self.mode_root, self.stage, 'preview')
        self.assert_ok(preview)
        self.assert_ok(self.invoke(self.mode_root, self.stage, 'apply', json.loads(preview.stdout)['preview_sha256']))
        after = json.loads((self.pair_root / 'ownership.json').read_text('utf8'))
        self.assertEqual(after['steps'][:-1], before['steps'])
        self.assertEqual(after['links'], before['links'])
        self.assertEqual(after['runtime_ownership'], 'unresolved')
        unchanged = {p: raw for p, raw in self.preserved.items() if p != self.pair_root / 'ownership.json'}
        self.assertEqual({p: p.read_bytes() for p in unchanged}, unchanged)
        self.assertEqual(list(self.desktop.glob('*.lnk')), [self.selected])
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))

    def test_same_bytes_replacement_and_fabricated_evidence_grant_nothing(self):
        self.single_fixture()
        raw = self.selected.read_bytes()
        original = self.selected.with_suffix('.original')
        self.selected.rename(original)
        self.selected.write_bytes(raw)
        result = self.run_ps(f'Get-OperatorDesktopSingleEntryPlan {self.review_args}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_shortcut_changed', result.stderr)
        self.assertFalse(self.single_root.exists())
        self.selected.unlink()
        original.rename(self.selected)
        outside = self.project / '.codex/not-an-audit-material.json'
        outside.write_text('{}', encoding='utf8')
        for evidence in (self.retained, outside):
            result = self.run_ps(f'Get-OperatorDesktopSingleEntryPlan -ProjectRoot $p '
                f'-RetainedNativeShortcut {self.q(self.retained)} -EvidenceFiles @({self.q(evidence)})')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('legacy_pair_single_entry_evidence_scope_invalid', result.stderr)
            self.assertFalse(self.single_root.exists())
        self.retained.write_bytes(b'unrelated native shortcut; claimed completed in evidence')
        result = self.run_ps(f'Get-OperatorDesktopSingleEntryPlan {self.review_args}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_retained_changed', result.stderr)
        self.assertFalse(self.single_root.exists())

    def test_preview_binds_evidence_and_no_automatic_second_review(self):
        self.single_fixture()
        sha = self.preview_single()['sha256']
        raw = self.evidence.read_bytes()
        self.evidence.write_bytes(raw + b'\n')
        result = self.review_single(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_preview_changed', result.stderr)
        self.assertFalse(self.single_root.exists())
        self.evidence.write_bytes(raw)
        self.assert_ok(self.review_single(sha))
        receipt = (self.single_root / 'ownership.json').read_bytes()
        result = self.review_single(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_existing_requires_review', result.stderr)
        self.assertEqual((self.single_root / 'ownership.json').read_bytes(), receipt)

    def test_later_shortcut_or_retained_backup_edit_blocks_status_and_refresh(self):
        self.single_fixture()
        self.assert_ok(self.review_single())
        for path in (self.selected, self.retained, self.evidence):
            raw = path.read_bytes()
            path.write_bytes(raw + b'later owner edit')
            result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotEqual(self.invoke(self.mode_root, self.stage, 'preview').returncode, 0)
            self.assertEqual(path.read_bytes(), raw + b'later owner edit')
            path.write_bytes(raw)
        root = self.single_root / 'upgrades' / ('f' * 32)
        root.mkdir()
        (root / 'pending.json').write_text('{}', encoding='utf8')
        result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_transaction_changed', result.stderr)
        (root / 'pending.json').unlink()
        intent = json.dumps({'schema_version': 1, 'phase': 'may_have_written', 'changes': [], 'moves': []}).encode()
        (root / 'committed-intent.json').write_bytes(intent)
        (root / 'completed.json').write_text(json.dumps({'schema_version': 1, 'phase': 'committed',
            'intent_sha256': hashlib.sha256(intent).hexdigest()}), encoding='utf8')
        result = self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_transaction_changed', result.stderr)

    def test_restore_preview_binds_the_exact_transaction_implementation(self):
        self.single_fixture()
        self.assert_ok(self.review_single())
        result = self.run_ps('Get-OperatorDesktopSingleEntryRestorePlan $p | ConvertTo-Json -Depth 30 -Compress')
        self.assert_ok(result)
        sha = json.loads(result.stdout)['sha256']
        # Simulate a changed source read without editing any canonical file.
        altered = self.run_ps(f'''
& $legacy {{
 $script:FixtureSourceReader=(Get-Command Read-LegacyPairBytes).ScriptBlock
 $script:FixtureChangedSource={self.q(Path(__file__).resolve().parents[2] / 'scripts/operator_desktop_pair_upgrade.psm1')}
 $script:FixtureChangedReads=0
 function script:Read-LegacyPairBytes([string]$Path) {{
  $raw=& $script:FixtureSourceReader $Path
  if ($Path -ieq $script:FixtureChangedSource) {{$script:FixtureChangedReads++;return ,([byte[]]($raw+[byte]10))}}
  return ,$raw
 }}
 $original=Get-LegacyPairHash (& $script:FixtureSourceReader $script:FixtureChangedSource)
 $injected=Get-LegacyPairHash (Read-LegacyPairBytes $script:FixtureChangedSource)
 if ($original -ceq $injected -or $script:FixtureChangedReads -ne 1) {{throw 'fixture_changed_source_not_injected'}}
}}
try {{Restore-OperatorDesktopSingleEntry $p -ExpectedPlanSha256 {sha}}} catch {{
 & $legacy {{if ($script:FixtureChangedReads -lt 2) {{throw 'fixture_changed_source_not_observed_by_restore'}}}}
 throw
}}
''')
        self.assertNotEqual(altered.returncode, 0)
        self.assertIn('legacy_pair_single_entry_preview_changed', altered.stderr)
        self.assertTrue(self.selected.exists())
        self.assertTrue(self.retained.exists())
        self.assertFalse(self.dated.exists())
        self.assertFalse(self.native.exists())

    def test_separate_restore_returns_same_entities_before_old_pair_restore(self):
        self.single_fixture()
        self.assert_ok(self.review_single())
        result = self.run_ps('Restore-OperatorDesktopLegacyPair $p')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy_pair_single_entry_restore_required', result.stderr)
        result = self.run_ps('Get-OperatorDesktopSingleEntryRestorePlan $p | ConvertTo-Json -Depth 30 -Compress')
        self.assert_ok(result)
        sha = json.loads(result.stdout)['sha256']
        denied = self.run_ps("Restore-OperatorDesktopSingleEntry $p -ExpectedPlanSha256 ('0'*64)")
        self.assertNotEqual(denied.returncode, 0)
        self.assertTrue(self.selected.exists())
        result = self.run_ps(f'Restore-OperatorDesktopSingleEntry $p -ExpectedPlanSha256 {sha} | ConvertTo-Json -Compress')
        self.assert_ok(result)
        self.assertFalse(self.selected.exists())
        self.assertFalse(self.retained.exists())
        self.assertEqual(self.dated.read_bytes(), self.preserved[self.selected])
        self.assertEqual(self.native.read_bytes(), self.preserved[self.retained])
        self.assertEqual((self.pair_root / 'ownership.json').read_bytes(), self.preserved[self.pair_root / 'ownership.json'])
        self.assert_ok(self.run_ps('Get-OperatorDesktopLegacyPairState $p -CheckCurrent | Out-Null'))
        self.assert_ok(self.run_ps('Restore-OperatorDesktopLegacyPair $p | Out-Null'))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(SingleEntryTests(name) for name in SingleEntryTests.__dict__
                              if name.startswith('test_'))
