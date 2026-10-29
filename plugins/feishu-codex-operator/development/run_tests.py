"""Run the canonical plugin's tests after the service/callback safety check.

Python tests are grouped with their owning module. Their existing module names
remain importable so shared fixtures keep their original identity. Quarantined
material is never discovered or placed on the import path. Node tests are opt-in.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest


TEST_AREAS = ("channels", "models", "shared", "development")
EXCLUDED_DIRECTORIES = {"_quarantine", "__pycache__", "node_modules"}
# Owner groups discover new modules automatically. Quick is a deliberately
# smaller local feedback set, never evidence of full or native CLI acceptance.
GROUP_AREAS = {
    "full": TEST_AREAS,
    "channels": ("channels",),
    "models": ("models",),
    "web": ("models/web",),
    "shared": ("shared",),
    "development": ("development",),
}
QUICK_MODULES = frozenset((
    "test_config", "test_rate_limits", "test_responses_tools",
    "test_responses_events", "test_responses_metrics", "test_web_model_protocol",
    "test_lmstudio_template", "test_release_rules", "test_runner",
))


def select_group_files(root: Path, paths: list[Path], groups: list[str]) -> list[Path]:
    """Union groups in discovery order; overlapping scopes never repeat a file."""
    unknown = set(groups) - (set(GROUP_AREAS) | {"quick"})
    if unknown:
        raise ValueError("unknown_test_group: " + ", ".join(sorted(unknown)))
    prefixes = tuple(prefix + "/" for group in groups
                     for prefix in GROUP_AREAS.get(group, ()))
    return [path for path in paths if path.relative_to(root).as_posix().startswith(prefixes)
            or ("quick" in groups and path.suffix == ".py" and path.stem in QUICK_MODULES)]


def case_ids(suite: unittest.TestSuite) -> list[str]:
    ids = []
    for item in suite:
        ids.extend(case_ids(item) if isinstance(item, unittest.TestSuite) else [item.id()])
    return ids


class TimedResult(unittest.TextTestResult):
    """Observe cases without changing unittest outcomes, order or failfast."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.durations = []

    def startTest(self, test):
        self._case_started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.durations.append((time.perf_counter() - self._case_started, test.id()))
        super().stopTest(test)


def plugin_root(start: Path | None = None) -> Path:
    origin = Path(start or __file__).resolve()
    for candidate in origin.parents:
        manifest = candidate / ".codex-plugin/plugin.json"
        if manifest.is_file() and (candidate / "scripts/source_route_contract.py").is_file():
            if json.loads(manifest.read_text(encoding="utf-8"))["name"] != "codex-operator":
                raise ValueError("unexpected_plugin_identity")
            return candidate
    raise ValueError("canonical_plugin_root_not_found")


def test_files(root: Path, pattern: str) -> list[Path]:
    found = []
    for area in TEST_AREAS:
        base = root / area
        if not base.is_dir() or base.is_symlink() or (hasattr(Path, "is_junction") and base.is_junction()):
            continue
        for directory, child_dirs, names in os.walk(base, followlinks=False):
            current = Path(directory)
            child_dirs[:] = sorted(name for name in child_dirs
                if name.casefold() not in EXCLUDED_DIRECTORIES and not name.startswith(".")
                and not (current / name).is_symlink()
                and not (hasattr(Path, "is_junction") and (current / name).is_junction()))
            relative = current.relative_to(base)
            if "tests" not in relative.parts or "_quarantine" in {part.casefold() for part in relative.parts}:
                continue
            for name in sorted(names):
                path = current / name
                if fnmatch.fnmatchcase(name, pattern) and not path.is_symlink():
                    found.append(path)
    return sorted(found, key=lambda path: path.name)


def prepare_test_imports(root: Path | None = None) -> Path:
    root = plugin_root() if root is None else root.resolve()
    paths = test_files(root, "test_*.py")
    names = [path.stem for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_test_module_name")
    directories = [root / "scripts", root / "development", *sorted({path.parent for path in paths})]
    for directory in reversed(directories):
        value = str(directory)
        if value not in sys.path:
            sys.path.insert(0, value)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="Optional test_module[.TestCase[.test_method]] names")
    parser.add_argument("--group", action="append", choices=["quick", *GROUP_AREAS],
                        help="Repeat to union owning areas; without a selection run full Python")
    parser.add_argument("-p", "--pattern", default="test_*.py", help="Python test filename pattern")
    parser.add_argument("--node", action="store_true", help="Also run the opt-in Node test files")
    parser.add_argument("--node-pattern", default="test_*.cjs", help="Node test filename pattern")
    parser.add_argument("--list", action="store_true", help="List files without importing or running tests")
    parser.add_argument("--collect-only", action="store_true", help="Import and list exact Python case IDs; do not execute")
    parser.add_argument("--durations", type=int, default=0, metavar="N", help="Report the N slowest Python cases")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    parser.add_argument("-b", "--buffer", action="store_true")
    args = parser.parse_args(argv)
    if args.group and args.names:
        parser.error("Select groups or explicit test names, not both.")
    if args.list and args.collect_only:
        parser.error("--list is import-free; --collect-only imports test modules. Select one.")
    if args.durations < 0:
        parser.error("--durations must be nonnegative.")
    root = plugin_root()
    python_files = test_files(root, args.pattern)
    node_files = test_files(root, args.node_pattern) if args.node else []
    if args.group:
        if "quick" in args.group:
            missing = QUICK_MODULES - {path.stem for path in test_files(root, "test_*.py")}
            if missing:
                parser.error("Quick group has missing modules: " + ", ".join(sorted(missing)))
        python_files = select_group_files(root, python_files, args.group)
        node_files = select_group_files(root, node_files, args.group)
    if args.names:
        available = {path.stem: path for path in test_files(root, "test_*.py")}
        for name in args.names:
            if name.split(".", 1)[0] not in available:
                parser.error(f"Unknown test module: {name}")
        python_files = sorted({available[name.split(".", 1)[0]] for name in args.names}, key=lambda path: path.name)
    if not python_files:
        parser.error("No Python tests match the requested selection.")
    if args.node and not node_files:
        parser.error("No Node tests match the requested selection.")
    if args.list:
        for path in [*python_files, *node_files]:
            print(path.relative_to(root).as_posix())
        return 0
    node = shutil.which("node") if args.node and not args.collect_only else None
    if args.node and not args.collect_only and node is None:
        parser.error("Node.js is required when --node is selected.")
    prepare_test_imports(root)
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromNames(args.names or [path.stem for path in python_files])
    except Exception as exc:
        parser.error(f"Test collection failed: {type(exc).__name__}: {exc}")
    if loader.errors:
        parser.error("Test collection failed:\n" + "\n".join(loader.errors))
    ids = case_ids(suite)
    duplicates = [name for name, count in Counter(ids).items() if count > 1]
    if duplicates:
        parser.error("Duplicate test IDs (overlapping names or imported TestCase): " + ", ".join(duplicates))
    if not ids:
        parser.error("No Python cases collected.")
    if args.collect_only:
        print("\n".join(ids))
        print(f"Collected {len(ids)} unique Python cases; none executed.", file=sys.stderr)
        if args.node:
            print("Node cases are not collected; use --list --node for their file inventory.", file=sys.stderr)
        return 0
    print(f"Selected {len(python_files)} Python modules / {len(ids)} cases; "
          f"{len(node_files)} Node files. Scope: {', '.join(args.group or (['explicit names'] if args.names else ['full']))}.",
          file=sys.stderr)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 0 if args.quiet else 1,
        failfast=args.failfast, buffer=args.buffer, resultclass=TimedResult).run(suite)
    if args.durations:
        print("Slowest Python cases (including per-case setup/cleanup; excluding class/module fixtures):", file=sys.stderr)
        for seconds, name in sorted(result.durations, reverse=True)[:args.durations]:
            print(f"{seconds:9.3f}s {name}", file=sys.stderr)
    success = result.wasSuccessful()
    if args.node and not (args.failfast and not success):
        child = subprocess.run([node, "--test", *map(str, node_files)], cwd=root, check=False)
        success = success and child.returncode == 0
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
