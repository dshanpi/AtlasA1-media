#!/usr/bin/env python3
"""Create a checked gzip ARM64 Image for the source U-Boot booti path."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile


def prepare(source, output):
    raw = source.read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    if len(raw) < 64 or raw[56:60] != b'ARM\x64':
        raise ValueError('Expected an ARM64 Linux Image')
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    if len(raw) > 10 * len(compressed):
        raise ValueError('Image exceeds the source U-Boot decompression bound')
    if gzip.decompress(compressed) != raw:
        raise ValueError('Compressed Image verification failed')
    if output.exists() or output.is_symlink():
        if output.is_symlink() or output.read_bytes() != compressed:
            raise FileExistsError(output)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(compressed)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            # Never overwrite an existing boot artifact, including on a race.
            os.link(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return dict(raw_bytes=len(raw), gzip_bytes=len(compressed),
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                gzip_sha256=hashlib.sha256(compressed).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), indent=2))
