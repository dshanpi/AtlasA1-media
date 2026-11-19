#!/usr/bin/env python3
"""Build an isolated, removable IMG userspace candidate; never access a board."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SDK = Path('/home/ubuntu/t736-aiot/tina')
SOURCE_SUBDIR = Path('platform/allwinner/display/libgpu/img-bxm/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/x11')
PREFIX = Path('opt/t736-img-ddk-24.2-x11')
VERSION = '24.2.6603887-2'
FIRMWARE = {
    'rgx.fw.36.56.104.183': '43eb5d054ee98bc975274198d2ed440e2f0f50b7ffcd0996a4022949f2c7909f',
    'rgx.sh.36.56.104.183': '71e1b1da9b4c6b42468e378e8b835306920568088bc6669879db4a108a7747c9',
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tina', type=Path, default=SDK)
    parser.add_argument('--work', type=Path, default=ROOT/'build/gpu-userspace-v2')
    parser.add_argument('--platform', choices=['x11', 'wayland'], default='x11')
    parser.add_argument('--without-gnome-x11', action='store_true',
                        help='Omit the GNOME Xorg session on distributions with Wayland-only GNOME')
    args = parser.parse_args()
    sdk = args.tina.resolve(strict=True)
    source_subdir = SOURCE_SUBDIR.parent / args.platform
    prefix = PREFIX
    package_name = 't736-img-userspace-candidate'
    version = VERSION
    runner = 't736-img-run'
    environment_file = 'config/gpu-userspace-x11.env'
    runner_file = 'config/gpu-userspace-run.sh'
    if args.platform == 'wayland':
        version = '24.2.6603887-3'
        prefix = Path('opt/atlasa1-img-wayland')
        package_name = 'atlasa1-img-wayland'
        runner = 't736-img-wayland-run'
        environment_file = 'config/gpu-userspace-wayland.env'
        runner_file = 'config/gpu-userspace-wayland-run.sh'
    source = sdk/source_subdir
    assert source.is_dir()
    for name, expected in FIRMWARE.items():
        assert digest(source / 'lib/firmware' / name) == expected, name
    build = args.work.resolve()
    build.mkdir(parents=True, exist_ok=True)
    stage = build / 'package-root'
    stage.mkdir()  # Refuse to overwrite a previous candidate.
    private = stage / prefix
    (private / 'lib').mkdir(parents=True)
    provenance = {}
    for subtree in ['usr/lib', 'usr/local/lib']:
        src = source / subtree
        for entry in sorted(src.iterdir()):
            if entry.name == 'pkgconfig' or entry.name.startswith('libwayland-'):
                continue
            dest = private / 'lib' / entry.name
            assert not dest.exists() and not dest.is_symlink(), dest
            if entry.is_dir():
                shutil.copytree(entry, dest, symlinks=True)
            elif entry.is_symlink():
                dest.symlink_to(entry.readlink())
            else:
                shutil.copy2(entry, dest)
            for original in ([entry] if not entry.is_dir() else sorted(entry.rglob('*'))):
                if original.is_file() or original.is_symlink():
                    target = private / 'lib' / original.relative_to(src)
                    provenance[str(target.relative_to(stage))] = str(original.relative_to(sdk))
    shutil.copytree(source / 'lib/firmware', private / 'firmware')
    for original in (source / 'lib/firmware').iterdir():
        provenance[str(prefix / 'firmware' / original.name)] = str(original.relative_to(sdk))
    (private / 'bin').mkdir()
    command = ['aarch64-linux-gnu-gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               str(ROOT / 'tools/validation/gpu_userspace_probe.c'), '-ldl',
               '-o', str(private / 'bin/gpu-probe')]
    result = subprocess.run(command, text=True, capture_output=True)
    (build / 'probe-build.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    shutil.copy2(ROOT / environment_file, private / 'session.env')
    shutil.copy2(ROOT / runner_file, private / 'bin' / runner)
    (private / 'bin' / runner).chmod(0o755)
    shutil.copy2(ROOT / 'tools/validation/gpu_runtime_view.py', private / 'bin/gpu-runtime-view')
    (private / 'bin/gpu-runtime-view').chmod(0o755)
    (stage / 'usr/bin').mkdir(parents=True)
    (stage / 'usr/bin' / runner).symlink_to('/' + str(prefix / 'bin' / runner))
    if args.platform == 'wayland':
        # Firefox's EGL backend looks up GL entry points in libGL first.
        # Keep this GLES-only lookup private to its native Wayland launcher;
        # it is not a desktop OpenGL/GLX implementation or a system replacement.
        (private / 'firefox-gles').mkdir()
        (private / 'firefox-gles/libGL.so.1').symlink_to('../lib/libGLESv2.so.2')
    if args.platform == 'x11' and not args.without_gnome_x11:
        (stage / 'usr/share/xsessions').mkdir(parents=True)
        shutil.copy2(ROOT / 'config/gpu-userspace-gnome.desktop', stage / 'usr/share/xsessions/t736-img.desktop')
    icd = json.loads((source / 'powervr_icd.json').read_text())
    icd['ICD']['library_path'] = '/' + str(prefix / 'lib/libVK_IMG.so')
    (private / 'powervr_icd.json').write_text(json.dumps(icd, indent=2) + '\n')
    (private / 'README.txt').write_text(
        'Isolated IMG X11 DDK 24.2.6603887 candidate. No system Mesa replacement.\n'
        'This package does not enable services, change GDM defaults or deploy firmware globally.\n'
        'The runtime-gles link view preserves the original vendor libraries but excludes\n'
        'the vendor Vulkan loader; GTK uses the distribution Vulkan loader. The wrapper\n'
        'verifies this view and does not select a vendor Vulkan ICD by default.\n'
        'Firmware remains in this private directory: the image integrator must explicitly\n'
        'pair it with the matching pvrsrvkm kernel using a reviewed firmware search path\n'
        'or copy these exact files into the new candidate image firmware directory.\n'
        'First run t736-img-run probe-gbm /dev/dri/renderD<N> on the known GPU render node.\n'
        'Then run t736-img-run probe-x11 in the intended DISPLAY/XAUTHORITY session.\n'
        'The probes draw/read back pixels and reject software renderer identities.\n'
        'A PASS is not GNOME or physical-display acceptance. No GLX test is claimed.\n'
        'The image-level desktop integration selects the X11 session.\n'
        'Keep the original llvmpipe image and original firmware for kernel rollback.\n')
    if args.platform == 'wayland':
        (private / 'README.txt').write_text(
            'AtlasA1 IMG Wayland DDK 24.2.6603887.\n'
            'Load session.env for EGL/GLES programs running on GNOME Wayland.\n'
            'The runtime uses the distribution Wayland libraries and Vulkan loader.\n'
            'Firmware and pvrsrvkm must match DDK 24.2.6603887.\n'
            'GNOME requires the sunxi-drm preferred-primary udev rule.\n'
            'firefox-gles is a Firefox Wayland-only GLES symbol lookup, not a GLX library.\n'
            'Validate presentation timestamps and physical display behavior after installation.\n')
    files = []
    external = set()
    provided = {p.name for p in (private / 'lib').glob('*') if not p.is_dir()}
    for path in sorted(stage.rglob('*')):
        rel = str(path.relative_to(stage))
        if path.is_symlink():
            if rel.startswith(str(prefix)):
                assert not path.readlink().is_absolute(), path
                assert path.resolve().is_relative_to(private.resolve()) and path.resolve().is_file(), path
            files.append({'path': rel, 'symlink': str(path.readlink()), 'source': provenance.get(rel)})
        elif path.is_file():
            item = {'path': rel, 'bytes': path.stat().st_size, 'sha256': digest(path), 'source': provenance.get(rel)}
            with path.open('rb') as f:
                elf = f.read(4) == b'\x7fELF'
            if elf and private / 'firmware' not in path.parents:
                header = run('readelf', '-h', str(path))
                assert 'AArch64' in header, path
                dyn = run('readelf', '-d', str(path))
                item['needed'] = re.findall(r'\(NEEDED\).*?\[(.*?)\]', dyn)
                external.update(set(item['needed']) - provided)
            files.append(item)
    project_inputs = ['tools/build_gpu_userspace.py', 'tools/validation/gpu_userspace_probe.c',
                      environment_file, runner_file,
                      'config/gpu-userspace-gnome.desktop', 'tools/validation/gpu_runtime_view.py']
    manifest = {'version': version, 'source_root': str(source_subdir), 'prefix': '/' + str(prefix),
                'project_inputs_sha256': {name: digest(ROOT / name) for name in project_inputs},
                'probe_compiler': run('aarch64-linux-gnu-gcc', '--version').splitlines()[0],
                'firmware_sha256': FIRMWARE, 'external_sonames': sorted(external),
                'firmware_deployed_globally': False, 'lightdm_hooks': False,
                'system_mesa_replaced': False, 'hardware_tested': False,
                'runtime_view': {'directory': 'runtime-gles', 'manifest': 'runtime-gles.json',
                                 'exclude': 'libvulkan.so*', 'vulkan_loader': 'system'},
                'files': files}
    (build / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(build / 'manifest.json', private / 'manifest.json')
    (private / 'SHA256SUMS').write_text(''.join(
        item['sha256'] + '  /' + item['path'] + '\n' for item in files if 'sha256' in item))
    # The view record binds this completed payload manifest. Keep it out of the
    # main manifest's file list to avoid a circular content hash dependency.
    print(run('python3', str(private / 'bin/gpu-runtime-view'), '--root', str(stage),
              '--prefix', '/' + str(prefix)), end='')
    print(run('python3', str(private / 'bin/gpu-runtime-view'), '--root', str(stage),
              '--prefix', '/' + str(prefix), '--verify'), end='')
    shutil.copy2(private / 'runtime-gles.json', build / 'runtime-gles.json')
    control = stage / 'DEBIAN'
    control.mkdir()
    dependencies = ('libc6 (>= 2.34), libdrm2, libexpat1, libgcc-s1, libstdc++6, libudev1, '
                    'libx11-6, libx11-xcb1, libxcb-dri2-0, libxcb-dri3-0, libxcb-glx0, '
                    'libxcb-present0, libxcb-randr0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, '
                    'libxcb1, libxext6, libxfixes3, libxshmfence1, libxxf86vm1, zlib1g, '
                    'libvulkan1, python3')
    if args.platform == 'wayland':
        dependencies += ', libwayland-client0, libwayland-server0, libwayland-egl1'
    (control / 'control').write_text(
        'Package: ' + package_name + '\nVersion: ' + version + '\nArchitecture: arm64\n'
        'Maintainer: T736 local integration\nDepends: ' + dependencies + '\n'
        'Description: Isolated T736 IMG ' + args.platform + ' EGL GLES and validation tools\n')
    package = build / (package_name + '_' + version + '_arm64.deb')
    assert not package.exists()
    print(run('dpkg-deb', '--build', '--root-owner-group', str(stage), str(package)), end='')
    (build / 'SHA256SUMS').write_text(digest(package) + '  ' + package.name + '\n' +
                                     digest(build / 'manifest.json') + '  manifest.json\n' +
                                     digest(build / 'runtime-gles.json') + '  runtime-gles.json\n')
    print(json.dumps({'package': str(package), 'sha256': digest(package),
                      'files': len(files), 'external_sonames': sorted(external)}, indent=2))


if __name__ == '__main__':
    main()
