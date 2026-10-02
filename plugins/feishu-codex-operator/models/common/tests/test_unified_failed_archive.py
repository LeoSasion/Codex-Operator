"""Disposable review and Windows sharing evidence for failed-plan archival."""
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
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import operator_unified_cold_start as cold
import operator_unified_failed_archive as failed
import operator_unified_retire as records
import operator_unified_prepare as preparation
import operator_unified_withdraw as withdraw
import operator_legacy_runtime_upgrade as upgrade
import operator_web_service as web
import operator_uninstall as uninstall
from operator_core import windows_config_transaction as transaction
from test_unified_retire import UnifiedRetirementTests


@unittest.skipUnless(os.name == 'nt', 'Windows file identity and sharing required')
class FailedArchiveTests(UnifiedRetirementTests):
    # Inherit the ordinary retirement cases too: the separate path must never
    # admit an uncertain attempt through the existing retirement operation.
    def test_effort_review_is_root_scoped_and_preserves_all_other_settings(self):
        before = (b'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "xhigh"\n'
            b'[profiles.idle]\nmodel_reasoning_effort = "low"\n'
            b"[mcp_servers.node_repl.env]\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'one'\n")
        current = before.replace(b'"xhigh"', b'"high"').replace(b"'one'", b"'two'")
        self.assertEqual(failed._config_delta(before, current),
                         'native_effort_and_desktop_preferences_only')
        with self.assertRaises(records.RetireError):
            records._config_delta(before, current)
        for changed in (current + b'approval_policy="never"\n',
                        current.replace(b'[profiles.idle]', b'[profiles.changed]'),
                        current.replace(b'"low"', b'"medium"'),
                        current.replace(b'"high"', b'"unknown"'),
                        before.replace(b'"low"', b'"high"')):
            with self.assertRaises(failed.FailedArchiveError):
                failed._config_delta(before, changed)

    def failed_fixture(self):
        fixture = self.fixture(locked=True, pipe=True)
        fixture._release_planned_marker()
        cold.arm(fixture.plan, Path(sys.executable))
        source = _PLUGIN / 'models/common/tests/fixtures/cold-cache-prewrite-20260930.py.txt'
        self.assertEqual(records._hash(source.read_bytes()), failed.KNOWN_CONSUMER)
        arm_path = fixture.plan.parent / 'arm.json'
        arm = json.loads(arm_path.read_bytes())
        arm['consumer_sha256'] = failed.KNOWN_CONSUMER
        arm_path.write_bytes(records._json(arm))
        bundle = fixture.project / '.codex/operator-unified-startup'
        script = cold.render_workflow(Path(sys.executable), fixture.plan).replace(
            records._hash(Path(cold.__file__).read_bytes()).encode(), failed.KNOWN_CONSUMER.encode())
        (bundle / cold.SCRIPT).write_bytes(script)
        sync = records._json({'schema_version': 2, 'startup_script': cold.SCRIPT,
                             'entry_files': {cold.SCRIPT: records._hash(script)}})
        (bundle / 'startup-sync-plan.json').write_bytes(sync)
        plan = json.loads(fixture.plan.read_bytes())
        plan['startup_bundle']['startup_script_sha256'] = records._hash(script)
        plan['startup_bundle']['sync_plan_sha256'] = records._hash(sync)
        plan_raw = records._json(plan)
        fixture.plan.write_bytes(plan_raw)
        plan_sha = records._hash(plan_raw)
        # This is a synthetic retained historical failure, never a replay.
        for name in ('journal.json', 'arm.json', 'marker-release/intent.json', 'marker-release/receipt.json'):
            path = fixture.plan.parent / name
            value = json.loads(path.read_bytes())
            value['plan_sha256'] = plan_sha
            path.write_bytes(records._json(value))
        release_intent = fixture.plan.parent / 'marker-release/intent.json'
        release_receipt = fixture.plan.parent / 'marker-release/receipt.json'
        receipt = json.loads(release_receipt.read_bytes())
        receipt['intent_sha256'] = records._hash(release_intent.read_bytes())
        release_receipt.write_bytes(records._json(receipt))
        arm = json.loads(arm_path.read_bytes())
        arm['marker_release_sha256'] = records._hash(release_receipt.read_bytes())
        arm_path.write_bytes(records._json(arm))
        records._record(fixture.plan.parent / 'attempt.json', {'schema_version': 1,
            'phase': 'may_have_activated', 'plan_sha256': plan_sha,
            'cache_backup': 'cache-retired-' + 'a' * 32 + '.bin'})
        run = fixture.project / '.codex/operator-unified-handoff' / ('run-' + 'b' * 32)
        run.mkdir(parents=True)
        result = run / 'result.json'
        result.write_bytes(records._json(failed.FAILURE))
        records._record(run / 'manifest.json', {'schema_version': 1, 'plan': str(fixture.plan),
            'home': str(fixture.home), 'project': str(fixture.project),
            'config_sha256': plan['config_sha256'], 'router_state': str(fixture.router_state),
            'web_profile': str(fixture.profile), 'port': 4318,
            'python': str(Path(sys.executable).resolve()),
            'source_sha256': {'operator_unified_cold_start.py': failed.KNOWN_CONSUMER}})
        recovery = self.recover(fixture)
        fixture.config.write_bytes(fixture.original.replace(b"'one'", b"'two'"))
        fixture.cache.write_bytes(b'{"new":"current-native-catalog"}\n')
        patches = [patch.object(records, '_stopped'),
            patch.object(upgrade, 'process_gate'),
            patch.object(upgrade, 'queue_gate', return_value={'actionable_inbox': 0, 'open_callbacks': 0}),
            patch.object(web, 'status', return_value={'status': 'stopped'}),
            patch.object(web, 'process_identity', return_value=None)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return fixture, result, source, recovery

    def test_archive_preserves_failed_tree_and_current_native_state(self):
        fixture, result, source, recovery = self.failed_fixture()
        original_tree = failed._tree(fixture.plan.parent)
        config = transaction._snapshot(fixture.config)
        cache = transaction._snapshot(fixture.cache)
        marker = transaction._snapshot(fixture.home / 'operator-native-route-only')
        entry = transaction._snapshot(fixture.entry / 'desktop-entry.json')
        review = failed.preview(fixture.plan, result, source, recovery)
        outcome = failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertEqual(outcome['status'], 'failed_original_archived_witnessed')
        self.assertFalse(outcome['replay_performed'])
        self.assertFalse(fixture.plan.parent.exists())
        run = next((fixture.home / failed.ROOT).iterdir())
        self.assertEqual(failed._tree(run / 'evidence'), original_tree)
        self.assertEqual(json.loads((run / 'evidence/attempt.json').read_bytes())['phase'], 'may_have_activated')
        self.assertFalse((run / 'evidence/completion.json').exists())
        for path, expected in [(fixture.config, config), (fixture.cache, cache),
                (fixture.home / 'operator-native-route-only', marker), (fixture.entry / 'desktop-entry.json', entry)]:
            self.assertEqual(transaction._snapshot(path), expected)
        self.assertEqual(failed.archive_status(fixture.home),
                         {'status': 'failed_originals_retained', 'generations': 1})
        uninstall.inspect_unified_candidate(fixture.config)

    def test_unknown_failure_and_incomplete_attempt_never_allocate_archive(self):
        fixture, result, source, recovery = self.failed_fixture()
        original = result.read_bytes()
        for change in ({'reason': 'other_error'}, {'model_requests': False},
                       {'native_reopen_attempted': True}, {'extra': 'unknown'}):
            result.write_bytes(records._json({**failed.FAILURE, **change}))
            with self.assertRaises(failed.FailedArchiveError):
                failed.preview(fixture.plan, result, source, recovery)
            self.assertFalse((fixture.home / failed.ROOT).exists())
        result.write_bytes(original)
        for name in ('completion.json', '.operator-config-transaction-' + 'c' * 32,
                     'cache-retired-' + 'a' * 32 + '.bin', 'unreviewed.txt'):
            path = fixture.plan.parent / name
            path.write_bytes(b'{}')
            with self.assertRaisesRegex(failed.FailedArchiveError, 'partial_or_unknown_attempt'):
                failed.preview(fixture.plan, result, source, recovery)
            path.unlink()
        self.assertFalse((fixture.home / failed.ROOT).exists())

    def test_changed_review_preserves_every_file_before_allocation(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        fixture.cache.write_bytes(b'{"later":"native-cache"}\n')
        before = records._tree(fixture.plan.parent)
        with self.assertRaisesRegex(failed.FailedArchiveError, 'review_changed'):
            failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertEqual(records._tree(fixture.plan.parent), before)
        self.assertFalse((fixture.home / failed.ROOT).exists())

    def test_move_failure_is_terminal_and_keeps_failed_original(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        before = records._tree(fixture.plan.parent)
        with patch.object(failed, '_rename_handle', side_effect=failed.FailedArchiveError('synthetic_move')):
            with self.assertRaisesRegex(failed.FailedArchiveError, 'synthetic_move'):
                failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertEqual(records._tree(fixture.plan.parent), before)
        self.assertEqual(failed.archive_status(fixture.home)['status'], 'uncertain')
        with self.assertRaisesRegex(failed.FailedArchiveError, 'requires_review'):
            failed.preview(fixture.plan, result, source, recovery)
        with self.assertRaisesRegex(uninstall.UnifiedCandidateConflict, 'unified_failed_archive_requires_review'):
            uninstall.inspect_unified_candidate(fixture.config)
        readiness = preparation.preview(fixture.project, fixture.home, fixture.router_state,
                                         fixture.profile, 4318)
        self.assertIn('unified_failed_archive_requires_review', readiness['blockers'])

    def test_changed_final_boundary_keeps_completion_fence(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        original = failed._verify_run
        sources = failed._sources
        changed = False
        def corrupt_after_receipt(run, *, pending=False):
            nonlocal changed
            value = original(run, pending=pending)
            if pending:
                changed = True
            return value
        def changed_sources():
            value = sources()
            return {**value, 'operator_unified_failed_archive.py': '0' * 64} if changed else value
        with patch.object(failed, '_verify_run', side_effect=corrupt_after_receipt), \
                patch.object(failed, '_sources', side_effect=changed_sources):
            with self.assertRaises(failed.FailedArchiveError):
                failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertEqual(failed.archive_status(fixture.home)['status'], 'uncertain')
        run = next((fixture.home / failed.ROOT).iterdir())
        self.assertTrue((run / 'completion-pending.json').exists())

    def test_original_directory_cannot_be_swapped_at_move_boundary(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        rename = failed._rename_handle
        observed = []
        def try_swap(handle, parent, target, identity):
            try:
                os.rename(fixture.plan.parent, fixture.home / 'unowned-replacement')
            except OSError as exc:
                observed.append(exc.errno)
            else:
                self.fail('Moving directory handle must block path replacement')
            rename(handle, parent, target, identity)
        with patch.object(failed, '_rename_handle', side_effect=try_swap):
            failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertEqual(observed, [13])
        self.assertEqual(failed.archive_status(fixture.home)['status'], 'failed_originals_retained')

    def test_child_change_in_required_closed_handle_gap_keeps_original_bytes_and_fence(self):
        fixture, result, source, recovery = self.failed_fixture()
        original = (fixture.plan.parent / 'attempt.json').read_bytes()
        review = failed.preview(fixture.plan, result, source, recovery)
        rename = failed._rename_handle
        def change_child(handle, parent, target, identity):
            (fixture.plan.parent / 'attempt.json').write_bytes(b'{"later":"edit"}')
            rename(handle, parent, target, identity)
        with patch.object(failed, '_rename_handle', side_effect=change_child):
            with self.assertRaisesRegex(failed.FailedArchiveError, 'original_changed'):
                failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        run = next((fixture.home / failed.ROOT).iterdir())
        self.assertEqual((run / 'context/original--attempt.json').read_bytes(), original)
        self.assertEqual((run / 'evidence/attempt.json').read_bytes(), b'{"later":"edit"}')
        self.assertTrue((run / 'completion-pending.json').exists())
        self.assertEqual(failed.archive_status(fixture.home)['status'], 'uncertain')

    def test_held_current_cache_writer_stops_before_archive_allocation(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        before = records._tree(fixture.plan.parent)
        with fixture.cache.open('r+b'):
            with self.assertRaises(transaction.TransactionFailure):
                failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        self.assertFalse((fixture.home / failed.ROOT).exists())
        self.assertEqual(records._tree(fixture.plan.parent), before)

    def test_destination_collision_never_overwrites_foreign_files(self):
        fixture, result, source, recovery = self.failed_fixture()
        review = failed.preview(fixture.plan, result, source, recovery)
        rename = failed._rename_handle
        def occupy_destination(handle, parent, target, identity):
            target.mkdir()
            (target / 'later-user-file.txt').write_bytes(b'keep')
            rename(handle, parent, target, identity)
        with patch.object(failed, '_rename_handle', side_effect=occupy_destination):
            with self.assertRaisesRegex(failed.FailedArchiveError, 'move_failed'):
                failed.archive(fixture.plan, result, source, recovery, review['review_sha256'])
        run = next((fixture.home / failed.ROOT).iterdir())
        self.assertEqual((run / 'evidence/later-user-file.txt').read_bytes(), b'keep')
        self.assertTrue(fixture.plan.exists())
        self.assertEqual(failed.archive_status(fixture.home)['status'], 'uncertain')


class FailedArchiveCliTests(unittest.TestCase):
    def test_status_requires_exact_python_and_plan_scope_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            plan = home / 'operator-unified-activation/plan.json'
            for path, python, expected in (
                    (plan, Path(sys.executable), 0),
                    (plan, home / 'missing-python.exe', 1),
                    (home / 'other/plan.json', Path(sys.executable), 1)):
                result = subprocess.run([sys.executable, failed.__file__, 'status',
                    '--plan', str(path), '--python', str(python)], capture_output=True,
                    timeout=10, check=False)
                self.assertEqual(result.returncode, expected)
                value = json.loads(result.stdout)
                self.assertEqual(value['status'], 'absent' if expected == 0 else 'unavailable')
                self.assertEqual(list(home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
