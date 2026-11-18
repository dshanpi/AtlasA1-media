#!/usr/bin/env python3
"""Build a private, opt-in T736 4K OMX candidate from a configured Tina tree."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tina", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New build directory")
    args = parser.parse_args()
    tina, output = args.tina.resolve(), args.output.resolve()
    buildroot = tina / "out/t736/demo_aiot/buildroot/buildroot"
    configured = buildroot / "build/libcedarc"
    decoder = Path("openmax/vdec/src/omx_vdec_aw_decoder_linux.c")
    patch = Path(__file__).resolve().parents[1] / "patches/cedar/omx-4k-broker-buffers.patch"
    if output == tina or tina in output.parents or output.exists():
        parser.error("Choose a new directory outside Tina")
    if sha256(configured / decoder) != "9e8acb893ec55a0e55cc19f1620ff7b37fcc23b2f72fbfbc40e05b507b12b661":
        parser.error("Configured decoder source differs from the T736 build")
    output.mkdir(parents=True)
    source = output / "source"
    shutil.copytree(configured, source, symlinks=True)
    # libtool's existing objects belong to other, unmodified components.
    # Recompile the changed decoder TU against its original target flags.
    subprocess.run(["patch", "--fuzz=0", "-p1", "-i", str(patch)], cwd=source, check=True)
    os.utime(source / decoder)
    vdec = source / "openmax/vdec"
    with (output / "make.log").open("wb") as log:
        subprocess.run(["make", "-j2", "V=1", "libOmxVdec.la"], cwd=vdec, check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    candidate = output / "libOmxVdec.so"
    shutil.copy2(vdec / ".libs/libOmxVdec.so", candidate)
    subprocess.run(["patchelf", "--remove-rpath", str(candidate)], check=True)
    print(f"{sha256(candidate)}  {candidate}")


if __name__ == "__main__":
    main()
