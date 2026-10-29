"""Keep scoped feedback honest: no lost, duplicated or silently skipped coverage."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

PLUGIN = next(p for p in Path(__file__).resolve().parents if (p / '.codex-plugin/plugin.json').is_file())
sys.path.insert(0, str(PLUGIN / 'development'))
import run_tests as runner


class TestRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='operator-test-runner-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_path = sys.path[:]
        self.addCleanup(self.restore_imports)
        self.modules = []

    def restore_imports(self):
        sys.path[:] = self.original_path
        for name in self.modules:
            sys.modules.pop(name, None)

    def module(self, area='shared', body='def test_one(self): pass'):
        name = 'test_runner_fixture_' + uuid.uuid4().hex
        self.modules.append(name)
        path = self.root / area / 'tests' / (name + '.py')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('import unittest\nclass Cases(unittest.TestCase):\n    ' + body + '\n', encoding='utf-8')
        return path

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(runner, 'plugin_root', return_value=self.root), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = runner.main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_owner_groups_cover_full_inventory_and_quick_is_a_strict_subset(self):
        files = runner.test_files(PLUGIN, 'test_*.py')
        owners = [name for name in runner.GROUP_AREAS if name not in ('full', 'web')]
        self.assertEqual(runner.select_group_files(PLUGIN, files, owners), files)
        quick = runner.select_group_files(PLUGIN, files, ['quick'])
        self.assertEqual({path.stem for path in quick}, runner.QUICK_MODULES)
        self.assertLess(len(quick), len(files))
        for path in runner.test_files(PLUGIN, 'test_*.cjs'):
            self.assertIn(path, runner.select_group_files(PLUGIN, [path], owners))

    def test_overlapping_groups_run_each_case_once(self):
        web = self.module('models/web')
        shared = self.module()
        with mock.patch.object(runner, 'QUICK_MODULES', {web.stem, shared.stem}):
            code, _, errors = self.invoke('--group', 'models', '--group', 'web', '--group', 'quick')
        self.assertEqual(code, 0, errors)
        self.assertIn('2 Python modules / 2 cases', errors)
        self.assertIn('Ran 2 tests', errors)

    def test_list_honors_names_without_importing_or_discovering_quarantine(self):
        selected = self.module()
        selected.write_text("raise AssertionError('must not import')", encoding='utf-8')
        self.module('models/web')
        self.module('shared/_quarantine')
        self.module('shared/.private')
        with mock.patch.object(runner, 'prepare_test_imports', side_effect=AssertionError('must not prepare')):
            code, output, _ = self.invoke(selected.stem + '.Cases.test_one', '--list')
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), [selected.relative_to(self.root).as_posix()])
        self.assertEqual(len(runner.test_files(self.root, 'test_*.py')), 2)

    def test_default_and_explicit_full_collect_identical_ids_without_execution(self):
        self.module(body="def test_one(self): self.fail('must not execute')")
        self.module('channels/feishu')
        default = self.invoke('--collect-only')
        explicit = self.invoke('--group', 'full', '--collect-only')
        self.assertEqual(default, explicit)
        self.assertEqual(default[0], 0)
        self.assertIn('2 unique Python cases; none executed', default[2])

    def test_missing_quick_member_unknown_scope_and_empty_pattern_fail(self):
        self.module()
        for args in (('--group', 'quick'), ('--group', 'unknown'), ('-p', 'test_missing_*.py')):
            with self.subTest(args=args):
                code, _, errors = self.invoke(*args, '--list')
                self.assertEqual(code, 2, errors)

    def test_conflicting_selectors_and_unknown_explicit_name_fail_before_import(self):
        selected = self.module()
        for args in ((selected.stem, '--group', 'shared'), ('test_missing',),
                     ('--list', '--collect-only'), ('--durations', '-1')):
            with self.subTest(args=args), mock.patch.object(runner, 'prepare_test_imports', side_effect=AssertionError('must not import')):
                self.assertEqual(self.invoke(*args)[0], 2)

    def test_overlapping_names_and_imported_case_alias_fail_before_execution(self):
        path = self.module(body="def test_one(self): self.fail('must not execute')")
        code, _, errors = self.invoke(path.stem, path.stem + '.Cases.test_one')
        self.assertEqual(code, 2)
        self.assertIn('Duplicate test IDs', errors)
        sys.modules.pop(path.stem, None)
        with path.open('a', encoding='utf-8') as stream:
            stream.write('ImportedAlias = Cases\n')
        code, _, errors = self.invoke('--collect-only')
        self.assertEqual(code, 2)
        self.assertIn('Duplicate test IDs', errors)

    def test_missing_method_and_failed_import_cannot_pass_collection(self):
        path = self.module()
        self.assertEqual(self.invoke(path.stem + '.Cases.test_missing', '--collect-only')[0], 2)
        sys.modules.pop(path.stem, None)
        path.write_text("raise RuntimeError('fixture import failure')", encoding='utf-8')
        code, _, errors = self.invoke('--collect-only')
        self.assertEqual(code, 2)
        self.assertIn('fixture import failure', errors)

    def test_timing_keeps_failure_skip_and_failfast_outcomes(self):
        self.module(body="def test_a(self): self.fail('retained failure')\n    def test_b(self): self.skipTest('retained skip')")
        code, _, errors = self.invoke('--durations', '2')
        self.assertEqual(code, 1)
        self.assertIn('failures=1, skipped=1', errors)
        self.assertIn('retained failure', errors)
        self.assertIn('Slowest Python cases', errors)
        code, _, errors = self.invoke('--durations', '2', '--failfast')
        self.assertEqual(code, 1)
        self.assertIn('Ran 1 test', errors)
        self.assertNotIn('skipped=1', errors)

    def test_node_scope_lists_without_node_and_preserves_nonzero_exit(self):
        self.module('models/web')
        node = self.root / 'models/web/tests/test_fixture.cjs'
        node.write_text("throw new Error('never run by this fixture');", encoding='utf-8')
        with mock.patch.object(runner.shutil, 'which', return_value=None):
            self.assertEqual(self.invoke('--group', 'web', '--node', '--list')[0], 0)
            self.assertEqual(self.invoke('--group', 'web', '--node', '--collect-only')[0], 0)
            self.assertEqual(self.invoke('--group', 'web', '--node')[0], 2)
        with mock.patch.object(runner.shutil, 'which', return_value='fixture-node'), mock.patch.object(runner.subprocess, 'run') as child:
            child.return_value.returncode = 1
            self.assertEqual(self.invoke('--group', 'web', '--node')[0], 1)
            self.assertEqual(child.call_args.args[0], ['fixture-node', '--test', str(node)])


if __name__ == '__main__':
    unittest.main()
