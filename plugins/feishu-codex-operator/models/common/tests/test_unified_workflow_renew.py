"""Real Windows workflow move/reselection with disposable service evidence."""
from pathlib import Path as _Path
import sys as _sys
_PLUGIN = next(parent for parent in _Path(__file__).resolve().parents
    if (parent / '.codex-plugin/plugin.json').is_file())
_sys.path.insert(0, str(_PLUGIN / 'development'))
from run_tests import prepare_test_imports
prepare_test_imports(_PLUGIN)

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_unified_failed_archive as fixtures
import operator_unified_workflow_renew as renewal
import operator_unified_failed_archive as failed
import operator_unified_retire as records
import operator_unified_prepare as preparation
import operator_unified_cold_start as cold
import operator_unified_upgrade as upgrade
import operator_uninstall as uninstall
from operator_core import windows_config_transaction as transaction


@unittest.skipUnless(os.name == 'nt', 'Windows sharing and file identity required')
class WorkflowRenewalTests(unittest.TestCase):
    fixture = fixtures.FailedArchiveTests.fixture
    recover = fixtures.FailedArchiveTests.recover
    failed_fixture = fixtures.FailedArchiveTests.failed_fixture

    def archived_fixture(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        archive = next((fixture.home / failed.ROOT).iterdir())
        return fixture, archive, recovery

    def test_renewal_keeps_old_workflow_and_reselects_exact_entry_without_activation(self):
        fixture, archive, recovery = self.archived_fixture()
        bundle = fixture.project / '.codex/operator-unified-startup'
        before = failed._tree(bundle)
        directory = failed._directory_identity(bundle)
        config, cache = transaction._snapshot(fixture.config), transaction._snapshot(fixture.cache)
        old_failed = failed._tree(archive)
        original_entry = (recovery.parent / 'desktop-entry.json.before').read_bytes()
        review = renewal.preview(archive, Path(sys.executable))
        result = renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertEqual(result['status'], 'workflow_renewed_witnessed')
        self.assertFalse(result['routing_activated'])
        run = next((fixture.home / renewal.ROOT).iterdir())
        self.assertEqual(failed._tree(run / 'evidence'), before)
        self.assertEqual(failed._directory_identity(run / 'evidence'), directory)
        self.assertEqual(failed._tree(archive), old_failed)
        self.assertEqual(transaction._snapshot(fixture.config), config)
        self.assertEqual(transaction._snapshot(fixture.cache), cache)
        self.assertEqual((fixture.entry / 'desktop-entry.json').read_bytes(), original_entry)
        self.assertFalse(fixture.plan.parent.exists())
        self.assertEqual((bundle / cold.SCRIPT).read_bytes(), cold.render_workflow(Path(sys.executable), fixture.plan))
        self.assertEqual(renewal.status(fixture.home), {'status': 'workflows_retained', 'generations': 1})
        self.assertFalse((run / 'completion-pending.json').exists())
        uninstall.inspect_unified_candidate(fixture.config)
        with self.assertRaises(renewal.RenewalError):
            renewal.preview(archive, Path(sys.executable))
        self.assertEqual(len(list((fixture.home / renewal.ROOT).iterdir())), 1)

    def assert_pending_gate(self, fixture):
        self.assertEqual(renewal.status(fixture.home)['status'], 'uncertain')
        with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict, 'workflow_renewal_requires_review'):
            uninstall.inspect_unified_candidate(fixture.config)
        value = preparation.preview(fixture.project, fixture.home, fixture.router_state, fixture.profile, 4318)
        self.assertIn('unified_workflow_renewal_requires_review', value['blockers'])

    def test_changed_review_and_unknown_old_files_stop_before_allocation(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        fixture.cache.write_bytes(b'new-cache')
        with self.assertRaisesRegex(renewal.RenewalError, 'review_changed'):
            renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertFalse((fixture.home / renewal.ROOT).exists())
        bundle = fixture.project / '.codex/operator-unified-startup'
        (bundle / 'user-file').write_bytes(b'keep')
        with self.assertRaisesRegex(renewal.RenewalError, 'old_workflow_changed'):
            renewal.preview(archive, Path(sys.executable))
        self.assertEqual((bundle / 'user-file').read_bytes(), b'keep')

    def test_retained_workflow_binds_old_and_new_identities_without_writes(self):
        fixture, archive, _ = self.archived_fixture()
        self.assertIsNone(renewal.retained_workflow(fixture.project, fixture.home))
        review = renewal.preview(archive, Path(sys.executable))
        renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        run = next((fixture.home / renewal.ROOT).iterdir())
        before = failed._tree(run)
        self.assertEqual(renewal.retained_workflow(fixture.project, fixture.home), run / 'evidence')
        self.assertEqual(failed._tree(run), before)
        child = fixture.project / '.codex/operator-unified-startup' / cold.SCRIPT
        replacement = child.with_name('replacement')
        replacement.write_bytes(child.read_bytes())
        os.replace(replacement, child)
        with self.assertRaisesRegex(renewal.RenewalError, 'current_changed'):
            renewal.retained_workflow(fixture.project, fixture.home)

    def test_retained_workflow_rejects_changed_original_and_wrong_project(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        with self.assertRaisesRegex(renewal.RenewalError, 'scope_changed'):
            renewal.retained_workflow(fixture.project / 'other', fixture.home)
        run = next((fixture.home / renewal.ROOT).iterdir())
        (run / 'evidence' / cold.SCRIPT).write_bytes(b'changed-original')
        with self.assertRaisesRegex(renewal.RenewalError, 'requires_review'):
            renewal.retained_workflow(fixture.project, fixture.home)

    def test_move_failure_is_retained_and_never_repeated(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        with patch.object(failed, '_rename_handle', side_effect=renewal.RenewalError('synthetic_move')):
            with self.assertRaisesRegex(renewal.RenewalError, 'synthetic_move'):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assert_pending_gate(fixture)
        with self.assertRaisesRegex(renewal.RenewalError, 'requires_review'):
            renewal.preview(archive, Path(sys.executable))

    def test_child_change_at_closed_reader_boundary_keeps_original_and_fence(self):
        fixture, archive, _ = self.archived_fixture()
        bundle = fixture.project / '.codex/operator-unified-startup'
        original = (bundle / cold.SCRIPT).read_bytes()
        review = renewal.preview(archive, Path(sys.executable))
        move = failed._rename_handle
        def change(handle, parent, target, identity):
            (bundle / cold.SCRIPT).write_bytes(b'changed-child')
            move(handle, parent, target, identity)
        with patch.object(failed, '_rename_handle', side_effect=change):
            with self.assertRaisesRegex(renewal.RenewalError, 'original_changed'):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        run = next((fixture.home / renewal.ROOT).iterdir())
        self.assertEqual((run / 'context' / ('original--' + cold.SCRIPT)).read_bytes(), original)
        self.assertEqual((run / 'evidence' / cold.SCRIPT).read_bytes(), b'changed-child')
        self.assert_pending_gate(fixture)

    def test_entry_failure_blocks_even_when_new_workflow_is_complete(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        before = (fixture.entry / 'desktop-entry.json').read_bytes()
        with patch.object(upgrade, 'reselect_entry', side_effect=renewal.RenewalError('synthetic_entry')):
            with self.assertRaisesRegex(renewal.RenewalError, 'synthetic_entry'):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertEqual((fixture.entry / 'desktop-entry.json').read_bytes(), before)
        self.assertIsNotNone(preparation._startup_bundle(fixture.project))
        self.assert_pending_gate(fixture)

    def test_completed_archive_mutation_becomes_uncertain(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        run = next((fixture.home / renewal.ROOT).iterdir())
        (run / 'context' / ('after--' + cold.SCRIPT)).write_bytes(b'changed-proof')
        self.assert_pending_gate(fixture)

    def test_directory_replacement_is_denied_at_move_boundary(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        bundle = fixture.project / '.codex/operator-unified-startup'
        move = failed._rename_handle
        denied = []
        def replace_directory(handle, parent, target, identity):
            try:
                os.rename(bundle, fixture.project / 'later-directory')
            except OSError as exc:
                denied.append(exc.errno)
            else:
                self.fail('Bound source directory must reject replacement')
            move(handle, parent, target, identity)
        with patch.object(failed, '_rename_handle', side_effect=replace_directory):
            renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertEqual(denied, [13])

    def test_cache_writer_blocks_before_allocation(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        with fixture.cache.open('r+b'):
            with self.assertRaises(transaction.TransactionFailure):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertFalse((fixture.home / renewal.ROOT).exists())

    def test_final_source_mutation_retains_pending_fence_and_native_protection(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        verify, sources = renewal._verify, renewal._sources
        changed = False
        def mutate_after_receipt(run, *, pending=False):
            nonlocal changed
            result = verify(run, pending=pending)
            changed = pending
            return result
        def changed_sources():
            value = sources()
            return {**value, 'operator_unified_workflow_renew.py': '0' * 64} if changed else value
        with patch.object(renewal, '_verify', side_effect=mutate_after_receipt), \
                patch.object(renewal, '_sources', side_effect=changed_sources):
            with self.assertRaisesRegex(renewal.RenewalError, 'final_witness_changed'):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assert_pending_gate(fixture)
        self.assertEqual((fixture.home / 'operator-native-route-only').read_bytes(), records.MARKER)

    def test_equal_byte_backup_replacement_is_not_an_identity_witness(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        run = next((fixture.home / renewal.ROOT).iterdir())
        backup = run / 'entry-reselection/boundary.bak'
        replacement = run / 'entry-reselection/new-copy'
        replacement.write_bytes(backup.read_bytes())
        os.replace(replacement, backup)
        self.assert_pending_gate(fixture)

    def test_later_optional_entry_file_blocks_completion_and_is_preserved(self):
        fixture, archive, _ = self.archived_fixture()
        review = renewal.preview(archive, Path(sys.executable))
        verify = renewal._verify
        later = fixture.entry / 'native-only'
        def add_later_file(run, *, pending=False):
            result = verify(run, pending=pending)
            if pending and not later.exists():
                later.write_bytes(b'later-owner-choice')
            return result
        with patch.object(renewal, '_verify', side_effect=add_later_file):
            with self.assertRaisesRegex(renewal.RenewalError, 'final_witness_changed'):
                renewal.renew(archive, Path(sys.executable), review['review_sha256'])
        self.assertEqual(later.read_bytes(), b'later-owner-choice')
        self.assert_pending_gate(fixture)


if __name__ == '__main__':
    unittest.main()
