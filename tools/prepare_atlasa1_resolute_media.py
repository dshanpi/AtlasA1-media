#!/usr/bin/env python3
"""Stage the native AtlasA1 Cedar service and PowerVR firmware for Ubuntu 26.04."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile


WC_ARCHIVE_SHA = 'fb2644eaf61ad5d2f06c6fecd00e8ec64c6695d79d4eff9cf915eeac3a15b7ba'
GPU_PACKAGE_SHA = '1455889d0c10ec5d0b49e839e0e9d3f7560869e65da5fbee02e477039c78e16e'
SERVICE_HASHES = {'cedar-broker': '1910bf0ce66653d27fe67f99d2a1ce8b813dafec3893f981a8d7c662a61f3b04',
                  'libcedar_backend.so': '2185f2019b4aea60933c34d387d290e808848e420f8899b0b401783293145583'}
FIRMWARE = {'rgx.fw.36.56.104.183': '43eb5d054ee98bc975274198d2ed440e2f0f50b7ffcd0996a4022949f2c7909f',
            'rgx.sh.36.56.104.183': '71e1b1da9b4c6b42468e378e8b835306920568088bc6669879db4a108a7747c9'}
RELEASE = '6.18.63-t736-media-v30'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified(path, expected):
    if digest(path) != expected:
        raise ValueError(f'Unexpected contents in {path}')
    return path


def prepare(args, root, tmp):
    browser = Path(__file__).resolve().parent / 'browser'
    wc = root / 'opt/t736-cedar-wc-v5'
    service = root / 'opt/t736-cedar-transport-v2'
    systemd = root / 'etc/systemd/system'

    def install(source, dest, mode=0o644):
        dest.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(source, dest)
        dest.chmod(mode)

    def write(dest, value, mode=0o644):
        dest.parent.mkdir(exist_ok=True, parents=True)
        dest.write_text(value)
        dest.chmod(mode)

    with tarfile.open(verified(args.wc_archive, WC_ARCHIVE_SHA), 'r:gz') as tar:
        for item in tar:
            rel = PurePosixPath(item.name)
            if item.isfile() and rel.parts[:2] == ('t736-cedar-wc-v5', 'lib'):
                if '..' in rel.parts or rel.suffix != '.so':
                    raise ValueError(f'Unexpected runtime file {rel}')
                dest = wc.joinpath(*rel.parts[1:])
                dest.parent.mkdir(exist_ok=True, parents=True)
                with tar.extractfile(item) as source, dest.open('xb') as stream:
                    shutil.copyfileobj(source, stream)
                dest.chmod(0o644)
    if b't736_broker_4k_buffers' not in args.omx_vdec.read_bytes():
        raise ValueError('The OMX decoder was not built with the 4K broker buffer patch')
    install(args.omx_vdec, wc/'lib/libOmxVdec.so')
    for name, sha in SERVICE_HASHES.items():
        source = verified(args.service_build/name, sha)
        if name == 'cedar-broker':
            install(source, service/'bin'/name, 0o755)
        else:
            install(source, root/'opt/t736-cedar-browser-backend-v5'/name)
    shm = browser/'shm_v2'
    # PrivateTmp is writable by the broker; the client's socket directory is root-owned.
    script = (shm/'cedar-service').read_text().replace(
        'GST_REGISTRY_1_0=/run/t736-cedar/registry.bin', 'GST_REGISTRY_1_0=/tmp/t736-cedar-registry.bin')
    write(service/'bin/cedar-service', script, 0o755)
    install(browser/'gstomx.conf', service/'config/gstomx.conf')
    config = (browser/'cedarc.conf').read_text().rstrip() + '\nt736_broker_4k_buffers = 1\n'
    write(service/'config/cedarc.conf', config)
    write(root/'etc/cedarc.conf', '# Service-specific configuration is bind-mounted by t736-cedar.service.\n')
    install(shm/'70-t736-cedar.rules', root/'etc/udev/rules.d/70-t736-cedar.rules')
    unit = (shm/'t736-cedar-experiment.service').read_text().replace(
        'Description=T736 isolated Cedar ordinary-RAM transport experiment',
        'Description=AtlasA1 Cedar hardware video decoder').replace('CPUAffinity=6 7', 'CPUAffinity=4 5 6 7')
    write(systemd/'t736-cedar.service', unit.split('# Deliberately no Install section')[0].rstrip()+'\n')
    socket = (shm/'t736-cedar.socket').read_text().replace('t736-cedar-experiment.service', 't736-cedar.service')
    write(systemd/'t736-cedar.socket', socket)
    enabled = systemd/'sockets.target.wants'
    enabled.mkdir(exist_ok=True)
    (enabled/'t736-cedar.socket').symlink_to('../t736-cedar.socket')
    vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', args.pvr_module], text=True).split()
    if vermagic[:1] != [RELEASE]:
        raise ValueError('PowerVR module kernel ABI mismatch')
    install(args.pvr_module, root/'usr/lib/modules'/RELEASE/'extra/pvrsrvkm.ko')
    write(root/'etc/modules-load.d/atlasa1-pvr.conf', 'pvrsrvkm\n')
    subprocess.run(['dpkg-deb', '-x', verified(args.gpu_deb, GPU_PACKAGE_SHA), tmp/'gpu'], check=True)
    for name, sha in FIRMWARE.items():
        source = verified(tmp/'gpu/opt/t736-img-ddk-24.2-x11/firmware'/name, sha)
        install(source, root/'usr/lib/firmware'/name)
    receipts = {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()}
    write(root/'usr/share/doc/atlasa1-board/media-sha256.json', json.dumps(receipts, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('wc-archive', 'service-build', 'omx-vdec', 'pvr-module', 'gpu-deb', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output requires a new directory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='.media-') as temporary:
        tmp = Path(temporary)
        stage = tmp/'overlay'
        prepare(args, stage, tmp)
        stage.rename(args.output)


if __name__ == '__main__':
    main()
