"""Run the canonical plugin's tests after the service/callback safety check.

Python tests are grouped with their owning module. Their existing module names
remain importable so shared fixtures keep their original identity. Quarantined
material is never discovered or placed on the import path. Node tests are opt-in.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


TEST_AREAS = ("channels", "models", "shared", "development")
EXCLUDED_DIRECTORIES = {"_quarantine", "__pycache__", "node_modules"}


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
    parser.add_argument("-p", "--pattern", default="test_*.py", help="Python test filename pattern")
    parser.add_argument("--node", action="store_true", help="Also run the opt-in Node test files")
    parser.add_argument("--node-pattern", default="test_*.cjs", help="Node test filename pattern")
    parser.add_argument("--list", action="store_true", help="List files without importing or running tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    parser.add_argument("-b", "--buffer", action="store_true")
    args = parser.parse_args(argv)
    root = plugin_root()
    python_files = test_files(root, args.pattern)
    node_files = test_files(root, args.node_pattern) if args.node else []
    if args.list:
        for path in [*python_files, *node_files]:
            print(path.relative_to(root).as_posix())
        return 0
    if not args.names and not python_files:
        parser.error("No Python tests match the requested pattern.")
    if args.node and not node_files:
        parser.error("No Node tests match the requested pattern.")
    node = shutil.which("node") if args.node else None
    if args.node and node is None:
        parser.error("Node.js is required when --node is selected.")
    prepare_test_imports(root)
    loader = unittest.TestLoader()
    if args.names:
        available = {path.stem for path in test_files(root, "test_*.py")}
        for name in args.names:
            if name.split(".", 1)[0] not in available:
                parser.error(f"Unknown test module: {name}")
        suite = loader.loadTestsFromNames(args.names)
    else:
        suite = loader.loadTestsFromNames([path.stem for path in python_files])
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 0 if args.quiet else 1,
        failfast=args.failfast, buffer=args.buffer).run(suite)
    success = result.wasSuccessful()
    if args.node and not (args.failfast and not success):
        child = subprocess.run([node, "--test", *map(str, node_files)], cwd=root, check=False)
        success = success and child.returncode == 0
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
