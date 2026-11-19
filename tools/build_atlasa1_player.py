#!/usr/bin/env python3
"""Package the optional AtlasA1 desktop player (Debian arm64)."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffplay', type=Path, required=True, help='FFplay with refresh and first-picture audio patches')
    p.add_argument('--avcodec', type=Path, required=True, help='Cedar libavcodec.so.61 including ELBG')
    p.add_argument('--avutil', type=Path, required=True, help='matching private libavutil.so.59')
    p.add_argument('--cc', default='aarch64-linux-gnu-gcc')
    p.add_argument('--client', type=Path, help='prebuilt matching native panel client')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--private-runtime', type=Path,
                   help='Bundle matching FFmpeg 7 runtime libraries on systems with FFmpeg 8')
    args = p.parse_args()
    if args.output.exists():
        p.error('output already exists')
    option_table = subprocess.check_output(['readelf', '--string-dump=.rodata', args.ffplay])
    if not any(line.partition(b']')[2].strip() == b'wait_video_start' for line in option_table.splitlines()):
        p.error('--ffplay must implement -wait_video_start; use ffplay-start-sync')
    tools = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp)
        app = stage/'opt/atlasa1-player'
        def install(source, dest, mode):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            dest.chmod(mode)
        for src, dest, mode in [(args.ffplay, app/'bin/ffplay', 0o755),
                                (args.avcodec, app/'lib/libavcodec.so.61', 0o644),
                                (args.avutil, app/'lib/libavutil.so.59', 0o644)]:
            if 'AArch64' not in subprocess.check_output(['readelf','-h',src], text=True):
                p.error('expected an AArch64 binary: ' + str(src))
            if dest.suffix != '' and ('[' + dest.name + ']') not in subprocess.check_output(['readelf','-d',src],text=True):
                p.error('unexpected library SONAME: ' + str(src))
            install(src, dest, mode)
        symbols = subprocess.check_output(['nm','-D','--defined-only',args.avcodec], text=True)
        if not all(s+'@@LIBAVCODEC_61' in symbols for s in ('avpriv_elbg_free','avpriv_elbg_do')):
            p.error('the Cedar codec must include Debian libavfilter ELBG compatibility')
        codec_bytes = args.avcodec.read_bytes()
        if not all(s in codec_bytes for s in (b'hevc_cedar\0', b'h264_cedar\0',
                                              b't736_client_open_preferred_panel\0', b't736_client_pull_fit1080\0')):
            p.error('native Cedar panel decoder build required for --avcodec')
        client = app/'lib/libt736_cedar_client.so'
        if args.client:
            install(args.client, client, 0o644)
        else:
            with tempfile.TemporaryDirectory() as private:
                subprocess.run(['sh', tools/'player/prepare_panel_sources.sh', private], check=True)
                subprocess.run([args.cc,'-std=gnu11','-O3','-Wall','-Wextra','-Werror','-fPIC','-shared',
                                '-pthread','-Wl,-z,relro,-z,now','-Wl,-soname,libt736_cedar_client.so',
                                '-o',client,'cedar_client.c'],cwd=Path(private)/'shm_v2',check=True)
        if 'AArch64' not in subprocess.check_output(['readelf', '-h', client], text=True):
            p.error('native client must be AArch64')
        exports = subprocess.check_output(['nm', '-D', '--defined-only', client], text=True).splitlines()
        if not {'t736_client_pull_fit1080', 't736_client_panel_requested',
                't736_client_open_preferred_panel'} <= {s.split()[-1] for s in exports}:
            p.error('native client lacks panel output support')
        client.chmod(0o644)
        install(tools/'player/atlasa1-player', stage/'usr/bin/atlasa1-player', 0o755)
        install(tools/'player/atlasa1-player.desktop', stage/'usr/share/applications/atlasa1-player.desktop', 0o644)
        for name in ('README.md','copyright'):
            install(tools/'player'/name, stage/'usr/share/doc/atlasa1-player'/name, 0o644)
        ffmpeg_deps = 'libavdevice61, libavfilter10, libavformat61, libavcodec61, libavutil59, libswscale8, libswresample5, '
        version = '0.1-6'
        if args.private_runtime:
            for soname in ('libavdevice.so.61', 'libavfilter.so.10', 'libavformat.so.61', 'libswscale.so.8',
                           'libswresample.so.5'):
                library = args.private_runtime / soname
                if ('['+soname+']' not in subprocess.check_output(['readelf','-d',library],text=True)
                        or 'AArch64' not in subprocess.check_output(['readelf','-h',library],text=True)):
                    p.error('unexpected private runtime library: ' + soname)
                install(library, app/'lib'/soname, 0o644)
            ffmpeg_deps = ''
            version = '0.1-6~resolute1'
        control = stage/'DEBIAN'
        control.mkdir()
        control.joinpath('control').write_text(
            f'Package: atlasa1-player\nVersion: {version}\nArchitecture: arm64\n'
            'Maintainer: AtlasA1 Project <noreply@github.com>\n'
            f'Depends: ffmpeg (>= 7:7.1), {ffmpeg_deps}libsdl2-2.0-0, python3, python3-gi, gir1.2-gtk-3.0\n'
            'Recommends: x11-xserver-utils\nSection: video\nPriority: optional\n'
            'Description: AtlasA1 FFplay with Cedar decoding and SDL GLES2 playback\n'
            ' Opens local video files in a desktop session with the board media runtime.\n')
        sums = []
        for f in sorted(stage.rglob('*')):
            if f.is_file() and control not in f.parents:
                sums.append(hashlib.md5(f.read_bytes(),usedforsecurity=False).hexdigest()+'  '+str(f.relative_to(stage)))
        (control/'md5sums').write_text('\n'.join(sums)+'\n')
        # Host group umasks vary; the archive also contains shared /usr trees.
        for directory in (stage, *stage.rglob('*')):
            if directory.is_dir():
                directory.chmod(0o755)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['dpkg-deb','--root-owner-group','--build',stage,args.output],check=True)
        print('client',hashlib.sha256(client.read_bytes()).hexdigest())
    print('package',hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
