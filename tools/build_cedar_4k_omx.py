#!/usr/bin/env python3
"""Compile every OMX decoder translation unit from source, without old objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tina", required=True, type=Path, help="SDK or automatically prepared minimal input tree")
    parser.add_argument("--output", required=True, type=Path, help="New build directory")
    args = parser.parse_args()
    tina, output = args.tina.resolve(), args.output.resolve()
    buildroot = tina / "out/t736/demo_aiot/buildroot/buildroot"
    original = tina / "platform/allwinner/multimedia/libcedarc_v2.0"
    sdk = buildroot / 'host'
    compiler = sdk / 'bin/aarch64-none-linux-gnu-gcc'
    sysroot = sdk / 'aarch64-buildroot-linux-gnu/sysroot'
    decoder = Path("openmax/vdec/src/omx_vdec_aw_decoder_linux.c")
    patch = Path(__file__).resolve().parents[1] / "patches/cedar/omx-4k-broker-buffers.patch"
    if output == tina or tina in output.parents or output.exists():
        parser.error("Choose a new directory outside Tina")
    if sha256(original / decoder) != "9e8acb893ec55a0e55cc19f1620ff7b37fcc23b2f72fbfbc40e05b507b12b661":
        parser.error("Decoder source differs from the T736 build")
    output.mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    input_hashes = {}
    # Copy source/header files only. No Makefile/config.status, .libs, .lo or .o
    # can carry configured paths or objects from the developer's old build.
    for path in sorted(original.rglob('*')):
        if path.is_file() and path.suffix in ('.c', '.h'):
            relative = path.relative_to(original)
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            input_hashes[relative.as_posix()] = sha256(destination)
    subprocess.run(["patch", "--fuzz=0", "-p1", "-i", str(patch)], cwd=source, check=True)
    vdec = source / "openmax/vdec"
    sources = ['src/omx_vdec.c', 'src/omx_vdec_port.c', 'src/omx_vdec_aw_decoder_linux.c',
               'looper/omx_thread.c', 'looper/omx_mutex.c', 'looper/omx_sem.c']
    includes = [source / rel for rel in ('openmax/include', 'openmax/vdec/inc',
                'openmax/vdec/looper', 'include', 'openmax/omxcore/include',
                'base/include', 've/include', 'openmax/omxcore/tablelist/linux')]
    flags = ['-g', '-O0', '-Wall', '-Werror', '-D_GNU_SOURCE', '-fPIC',
             '-D__LINUX__', '-DCONF_KERNEL_VERSION_6_6', '-DCONF_USE_IOMMU',
             '-DCONF_AUTO_SCALE_OVER_4K', '-DCONF_AW_AFBC_MODE=0',
             '-DCONF_VE_MULTIPLE_OUTPUT', '-DCONF_OMX_USE_ZERO_COPY']
    flags += ['-Wno-' + name for name in ('unused-variable', 'array-bounds',
              'unused-but-set-variable', 'unused-result', 'unused-function', 'unused-value',
              'pointer-to-int-cast', 'int-to-pointer-cast', 'unused-label', 'strict-aliasing', 'format')]
    flags += ['-I' + str(path) for path in includes]
    objects = output / 'objects'
    objects.mkdir()
    commands = []
    candidate = output / "libOmxVdec.so"
    with (output / "make.log").open("wb") as log:
        for name in sources:
            obj = objects / (Path(name).stem + '.o')
            command = [str(compiler), *flags, '-c', str(vdec / name), '-o', str(obj)]
            commands.append(command)
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        command = [str(compiler), '-shared', '-Wl,--no-undefined', '-Wl,-soname,libOmxVdec.so',
                   '-o', str(candidate), *[str(objects / (Path(n).stem + '.o')) for n in sources],
                   '-L' + str(sysroot / 'usr/lib'), '-Wl,-rpath-link,' + str(sysroot / 'usr/lib'),
                   '-lcdc_base', '-lvdecoder', '-lMemAdapter', '-lVE', '-lvideoengine',
                   '-ldl', '-lrt', '-lpthread', '-lm']
        commands.append(command)
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    dynamic = subprocess.check_output(['aarch64-linux-gnu-readelf', '-d', candidate], text=True)
    if '(RPATH)' in dynamic or '(RUNPATH)' in dynamic:
        raise ValueError('Unexpected build-host runtime library path')
    (output / 'source-build.json').write_text(json.dumps({
        'reused_objects': False, 'translation_units': sources, 'input_sha256': input_hashes,
        'commands': commands, 'dynamic_section': dynamic, 'output_sha256': sha256(candidate)
    }, indent=2) + '\n')
    print(f"{sha256(candidate)}  {candidate}")


if __name__ == "__main__":
    main()
