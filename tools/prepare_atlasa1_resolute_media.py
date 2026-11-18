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


ROOT = Path(__file__).resolve().parents[1]
SERVICE_HASHES = {'cedar-broker': '2a2790b05dd55a7463e8b11f6eed165cb4f2d904906c5ae8957527054de04f98',
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

    vendor_files = json.loads((ROOT/'config/atlasa1-resolute-vendor-files.json').read_text())
    sdk_libs = vendor_files['cedar_sdk_libraries']
    expected_libs = set(sdk_libs) | set(vendor_files['cedar_rebuilt_libraries'])
    with tarfile.open(args.wc_archive, 'r:gz') as tar:
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
    if {p.relative_to(wc/'lib').as_posix() for p in (wc/'lib').rglob('*.so')} != expected_libs:
        raise ValueError('Cedar library set differs from the board runtime')
    for name, sha in sdk_libs.items():
        verified(wc/'lib'/name, sha)
    for name, symbol in (('libcdc_base.so', b'/dev/dma_heap/t736-ve'),
                         ('libMemAdapter.so', b'T736_WC: first validated WC ordering barrier'),
                         ('gstreamer-1.0/libgstomx.so', b'T736_OMX_DIAG')):
        contents = (wc/'lib'/name).read_bytes()
        if symbol not in contents:
            raise ValueError(f'Missing board-specific code in {name}')
    for library in vendor_files['cedar_rebuilt_libraries']:
        header = subprocess.check_output(['readelf', '-h', wc/'lib'/library], text=True)
        if 'AArch64' not in header:
            raise ValueError(f'Unexpected architecture for {library}')
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
    config = (browser/'cedarc.conf').read_text().rstrip() + '\nt736_broker_4k_buffers = 1\nenable_scaledown_while_4k = 0\n'
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
    if vermagic[:1] != [args.kernel_release]:
        raise ValueError('PowerVR module kernel ABI mismatch')
    install(args.pvr_module, root/'usr/lib/modules'/args.kernel_release/'extra/pvrsrvkm.ko')
    write(root/'etc/modules-load.d/atlasa1-pvr.conf', 'pvrsrvkm\n')
    fields = [subprocess.check_output(['dpkg-deb', '-f', args.gpu_deb, f], text=True).strip()
              for f in ('Package','Version','Architecture')]
    if fields != ['t736-img-userspace-candidate', '24.2.6603887-2', 'arm64']:
        raise ValueError('Unexpected GPU package identity')
    subprocess.run(['dpkg-deb', '-x', args.gpu_deb, tmp/'gpu'], check=True)
    for rel, expected in vendor_files['gpu_sdk_files'].items():
        path = tmp/'gpu'/rel
        if isinstance(expected, str):
            verified(path, expected)
        elif not path.is_symlink() or str(path.readlink()) != expected['symlink']:
            raise ValueError(f'Unexpected GPU library symlink {rel}')
    for name, sha in FIRMWARE.items():
        source = verified(tmp/'gpu/opt/t736-img-ddk-24.2-x11/firmware'/name, sha)
        install(source, root/'usr/lib/firmware'/name)
    receipts = {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()}
    write(root/'usr/share/doc/atlasa1-board/media-sha256.json', json.dumps(receipts, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-release', choices=[RELEASE, '6.18.63-t736-hw-v34'], default=RELEASE)
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
