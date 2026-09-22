"""Build an allowlisted, content-screened source preview. Never publish or install."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


PLUGIN = PurePosixPath('plugins/feishu-codex-operator')
PUBLIC_DOCS = {
    'README.md': 'README.md',
    'models/web/docs/native-web-experience.md': 'native-web-experience.md',
    'models/web/docs/chatgpt-web-integration.md': 'chatgpt-web-integration.md',
    'development/docs/release-audit.md': 'release-audit.md',
    'development/docs/testing.md': 'tests-README.md',
}
EXTENSIONS = {'.md', '.json', '.py', '.ps1', '.psm1', '.cjs', '.cs', '.cmd', '.yaml', '.txt'}
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
PATTERNS = {
    'credential': re.compile(r'(?<![\w-])(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|xox[baprs]-[A-Za-z0-9-]{20,})'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'local_owner_path': re.compile(r'C:[/\\]+Users[/\\]+(?:Administrator|ADMINI~1)(?:[/\\]|$)', re.I),
    'private_task': re.compile(r'\b01a0[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'),
    'private_app': re.compile(r'\basdk_app_[0-9a-f]{24,}\b'),
}
# Two existing unit fixtures are deliberately credential-shaped. Allow only their
# exact bytes in its exact test file; never exempt tests or credential prefixes.
FIXTURES = {(str(PLUGIN / 'models/web/tests/test_web_service_manager.py'),
    hashlib.sha256(b'sk-' + suffix).hexdigest()) for suffix in
    (b'fixture-private-never-copy', b'fixture-private-never-read')}


def safe_path(value):
    if not isinstance(value, str) or re.search(r'[<>:"\\|?*\x00-\x1f]', value):
        raise ValueError('unsafe_inventory_path')
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p.casefold() in ('.', '..', '.codex', '.tmp', '__pycache__', '.git', '_quarantine') for p in path.parts) or path.as_posix() != value:
        raise ValueError('unsafe_inventory_path')
    if any(p.endswith(('.', ' ')) or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])',
            p.split('.', 1)[0], re.I) for p in path.parts):
        raise ValueError('unsafe_inventory_path')
    if path.name not in ('.gitignore', 'LICENSE') and path.suffix not in EXTENSIONS:
        raise ValueError('unexpected_file_type')
    return path


def read_source(root, relative):
    path = root.joinpath(*safe_path(relative).parts)
    for item in [path, *path.parents]:
        if item == root.parent:
            break
        if item.is_symlink() or getattr(item.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_source')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise ValueError('source_file_bound')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError('source_file_bound')
    raw.decode('utf-8-sig')
    return raw


def collect(root):
    root = Path(root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('absolute_repository_required')
    inventory = json.loads(read_source(root, str(PLUGIN / 'assets/release-inventory.json')))
    if inventory.get('schema_version') != 1:
        raise ValueError('inventory_version')
    components = inventory.get('components', [])
    if len(components) != 1 or components[0].get('root_role') != 'plugin_root':
        raise ValueError('inventory_components')
    paths = [str(safe_path(p)) for p in inventory['repository_files']] + [str(PLUGIN / safe_path(p)) for p in components[0]['paths']]
    if len(paths) != len({p.casefold() for p in paths}):
        raise ValueError('duplicate_inventory_path')
    if any(p.casefold() in ('agents.md', 'release-manifest.json') for p in paths):
        raise ValueError('generated_inventory_path')
    data, provenance = {}, {}
    for relative in paths:
        selected = relative
        plugin_relative = relative.removeprefix(str(PLUGIN) + '/')
        if relative.startswith(str(PLUGIN) + '/') and plugin_relative in PUBLIC_DOCS:
            selected = str(PLUGIN / 'assets/public-docs' / PUBLIC_DOCS[plugin_relative])
            provenance[relative] = selected
        data[relative] = read_source(root, selected)
    # Distribution checks use this exact mirrored policy, never private root history.
    data['AGENTS.md'] = read_source(root, str(PLUGIN / 'assets/AGENTS.feishu-codex-operator.md'))
    provenance['AGENTS.md'] = str(PLUGIN / 'assets/AGENTS.feishu-codex-operator.md')
    if sum(map(len, data.values())) > MAX_TOTAL:
        raise ValueError('release_size_bound')
    findings = []
    for name, raw in data.items():
        text = raw.decode('utf-8-sig')
        for rule, pattern in PATTERNS.items():
            matches = list(pattern.finditer(text))
            if any(rule != 'credential' or (name, hashlib.sha256(m.group().encode()).hexdigest()) not in FIXTURES for m in matches):
                findings.append({'path': name, 'rule': rule})
    if findings:
        # Locations and fixed rules only; never echo a matched credential or value.
        raise ValueError('release_content_findings:' + json.dumps(findings, separators=(',', ':')))
    manifest = json.loads(data[str(PLUGIN / '.codex-plugin/plugin.json')])
    if manifest.get('name') != 'codex-operator' or not re.fullmatch(r'[a-zA-Z0-9.+-]{1,100}', manifest.get('version', '')):
        raise ValueError('release_identity')
    if 'LICENSE' not in data or str(PLUGIN / 'LICENSE') not in data:
        raise ValueError('license_missing')
    return data, provenance, manifest['version']


def build(root, output):
    output = Path(output)
    if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('new_absolute_output_required')
    if output.suffix != '.zip' or output.with_suffix('.receipt.json').exists():
        raise ValueError('new_zip_and_receipt_required')
    data, provenance, version = collect(root)
    files = {p: hashlib.sha256(b).hexdigest() for p, b in sorted(data.items())}
    metadata = {'product': 'Codex-Operator', 'version': version, 'channel': 'preview',
        'license': 'MIT', 'files': files, 'public_document_sources': provenance,
        'published': False, 'live_acceptance': False}
    data['RELEASE-MANIFEST.json'] = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf8')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative, raw in sorted(data.items()):
            info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    payload = buffer.getvalue()
    with output.open('xb') as stream:
        stream.write(payload)
    receipt = {'product': 'Codex-Operator', 'version': version, 'files': len(data),
        'zip_sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
        'public_document_overrides': len(PUBLIC_DOCS), 'content_screen': 'passed',
        'published': False}
    with output.with_suffix('.receipt.json').open('x', encoding='utf8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.repository_root, args.output), ensure_ascii=True))
    except (ValueError, OSError, KeyError) as exc:
        if isinstance(exc, ValueError):
            print(json.dumps({'status': 'stopped', 'reason': str(exc)}, ensure_ascii=True))
        else:
            print(json.dumps({'status': 'stopped', 'reason': 'release_files_unavailable'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
