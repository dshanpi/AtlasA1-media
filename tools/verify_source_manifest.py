#!/usr/bin/env python3
"""Verify exported source bytes, optionally directly from a Git revision."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess


def git(root, *args, data=None):
    return subprocess.run(['git', '-C', str(root), *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def verify(root, revision=None):
    root = Path(root).resolve()
    if revision:
        revision = git(root, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
        manifest = json.loads(git(root, 'show', revision + ':SOURCE-MANIFEST.json'))
        tree = {}
        for item in git(root, 'ls-tree', '-r', '-z', revision).split(b'\0'):
            if item:
                meta, name = item.split(b'\t', 1)
                mode, kind, oid = meta.split()
                if kind == b'blob' and mode in (b'100644', b'100755'):
                    tree[name.decode()] = oid
    else:
        manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_bytes())
    entries = manifest['files']
    names = set()
    errors = []
    for entry in entries:
        name = entry['path']
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or name in names:
            raise ValueError('Unsafe or duplicate manifest path: ' + name)
        names.add(name)
    blobs = {}
    if revision:
        # A single Git process avoids thousands of subprocesses on Windows.
        requested = [(e['path'], tree[e['path']]) for e in entries if e['path'] in tree]
        response = io.BytesIO(git(root, 'cat-file', '--batch', data=b''.join(oid + b'\n' for _, oid in requested)))
        for name, oid in requested:
            header = response.readline().split()
            if len(header) != 3 or header[:2] != [oid, b'blob']:
                raise ValueError('Unexpected Git blob response for ' + name)
            size = int(header[2])
            blobs[name] = response.read(size)
            if len(blobs[name]) != size or response.read(1) != b'\n':
                raise ValueError('Truncated Git blob response for ' + name)
    for entry in entries:
        name = entry['path']
        try:
            if revision:
                data = blobs[name]
            else:
                path = root / name
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('Manifest file escapes checkout: ' + name)
                data = path.read_bytes()
        except (KeyError, FileNotFoundError):
            errors.append({'path': name, 'error': 'missing regular file'})
            continue
        actual = hashlib.sha256(data).hexdigest()
        if len(data) != entry['size'] or actual != entry['sha256']:
            errors.append({'path': name, 'error': 'size or SHA-256 mismatch', 'actual_sha256': actual})
    return {'repository': manifest['repository'], 'git_revision': revision,
            'files_checked': len(entries), 'passed': not errors, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('--git-ref', help='Verify committed objects, independent of checkout newline conversion')
    args = parser.parse_args()
    result = verify(args.repository, args.git_ref)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
