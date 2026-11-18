#!/usr/bin/env python3
"""Measure clocked native FFplay playback through Cedar without opening an HDMI window."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile
import time


def journal(*args):
    return subprocess.check_output(['journalctl', '-b', '--no-pager', '-o', 'cat', *args],
                                   text=True, timeout=15)


def irq():
    for line in Path('/proc/interrupts').read_text().splitlines():
        if 't736-cedar-wc' in line:
            counters = re.match(r'\s*((?:\d+\s+)+)', line.split(':', 1)[1])
            if counters:
                return sum(map(int, counters[1].split()))
    raise ValueError('missing Cedar interrupt counter')


def play(args, record):
    clip = args.clip.resolve(strict=True)
    metadata = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,duration,nb_frames', '-of', 'json', str(clip)],
        text=True, timeout=15)
    stream = json.loads(metadata)['streams'][0]
    codec = stream['codec_name']
    frames, duration = int(stream['nb_frames']), float(stream['duration'])
    if codec not in ('hevc', 'h264') or not 2 <= duration <= 90 or frames < 2:
        raise ValueError('expected a 2–90 second H.264 or HEVC fixture with a declared frame count')
    total_frames = frames * args.loops
    total_duration = duration * args.loops
    if args.present_trace and total_frames > 16384:
        raise ValueError('the SDL presentation tracer can record at most 16384 frames')
    with clip.open('rb') as src:
        stream['sha256'] = hashlib.file_digest(src, 'sha256').hexdigest()
    record['fixture'] = stream
    if args.audio:
        audio = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name,sample_rate,channels', '-of', 'json', str(clip)],
            text=True, timeout=15)
        tracks = json.loads(audio)['streams']
        if not tracks:
            raise ValueError('A/V clock test requires an audio track')
        record['audio_track'] = tracks[0]
    user = pwd.getpwnam(args.user)
    if not user.pw_uid or os.geteuid() != 0:
        raise ValueError('run as root and select an unprivileged FFplay user')
    env = dict(PATH='/usr/bin:/bin', LANG='C', HOME=user.pw_dir, SDL_VIDEODRIVER='dummy',
               SDL_AUDIODRIVER='dummy', SDL_RENDER_DRIVER='software', AV_LOG_FORCE_NOCOLOR='1')
    if args.renderer == 'powervr':
        prefix = '/opt/t736-img-ddk-24.2-x11'
        env.update(SDL_VIDEODRIVER='offscreen', SDL_RENDER_DRIVER='opengles2',
                   LD_LIBRARY_PATH=prefix+'/runtime-gles', LIBGL_DRIVERS_PATH=prefix+'/lib/dri')
        for sock in Path('/tmp/.X11-unix').glob('X[0-9]*'):
            if sock.stat().st_uid == user.pw_uid:
                env.update(DISPLAY=':'+sock.name[1:], XAUTHORITY=f'/run/user/{user.pw_uid}/gdm/Xauthority')
                break
    if args.mode == 'cedar':
        libs = [args.client_lib, args.ffmpeg_lib/'libavutil.so.59', args.ffmpeg_lib/'libavcodec.so.61']
        for lib in libs:
            lib.resolve(strict=True)
        env.update(T736_CEDAR_ENABLE='1', T736_CEDAR_TEST_CLIENT='1', T736_CEDAR_TRACE='1',
                   LD_PRELOAD=':'.join(map(str, libs)))
        if args.native_fit or args.omx_fit:
            del env['T736_CEDAR_TEST_CLIENT']
            env.update(T736_CEDAR_NATIVE_PLAYER='1', T736_CEDAR_PANEL='1920x1080')
    if args.present_trace:
        tracer = str(args.present_trace.resolve(strict=True))
        env['LD_PRELOAD'] = ':'.join(filter(None, [tracer, env.get('LD_PRELOAD')]))
    decoder = codec + ('_cedar' if args.mode == 'cedar' else '')
    video_filter = 'showinfo=checksum=0'
    if args.scale_to_window:
        video_filter += (",scale=w='min(iw,1920)':h='min(ih,1080)':force_original_aspect_ratio=decrease:"
                         "force_divisible_by=2:flags=fast_bilinear,showinfo@panel=checksum=0")
    cmd = [str(args.player), '-hide_banner', '-loglevel', 'info', '-stats', '-autoexit',
           '-sn', '-sync', 'audio' if args.audio else 'ext', '-noframedrop' if args.keep_frames else '-framedrop', '-vcodec', decoder,
           '-vf', video_filter, '-x', '1920', '-y', '1080', '-i', str(clip)]
    if not args.audio:
        cmd.insert(1, '-an')
    if args.scale_to_window:
        cmd[1:1] = ['-filter_threads', '2']
    if args.loops > 1:
        cmd[1:1] = ['-loop', str(args.loops)]
    if args.wait_video_start:
        cmd.insert(1, '-wait_video_start')
    cursor = re.search(r'^-- cursor: (.+)$', journal('-n', '1', '--show-cursor'), re.M)
    if not cursor:
        raise ValueError('missing starting journal cursor')
    irq_start = irq()
    start = time.monotonic()
    pvr_libs = set()
    with tempfile.TemporaryFile() as logfile, subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=logfile, user=user.pw_uid, group=user.pw_gid,
            extra_groups=os.getgrouplist(user.pw_name, user.pw_gid)) as proc:
        try:
            if args.renderer == 'powervr':
                while proc.poll() is None and time.monotonic()-start < 10 and not pvr_libs:
                    try:
                        maps = Path(f'/proc/{proc.pid}/maps').read_text().splitlines()
                        pvr_libs = {Path(s.split()[-1]).name for s in maps if '/pvr_dri.so' in s}
                    except FileNotFoundError:
                        break
                    if not pvr_libs:
                        time.sleep(.2)
            proc.wait(timeout=max(1, 2*total_duration+20-(time.monotonic()-start)))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        logfile.seek(0)
        log = logfile.read().decode('utf-8', 'replace')
    elapsed, interrupts = time.monotonic() - start, irq() - irq_start
    broker = journal('--after-cursor', cursor[1], '-u', 't736-cedar.service')
    sessions = re.findall(r'CEDAR_BROKER: open session=(\d+) codec=(\d+) (\d+)x(\d+)', broker)
    hw = re.findall(r'CEDAR_BROKER: hardware frames=\d+ session=(\d+) visible=(\d+)x(\d+)', broker)
    shape = (str(stream['width']), str(stream['height']))
    # FFplay can open and close a probe decoder before it opens the playing decoder.
    # Tie the pixels returned to this process to the service's matching lease.
    pulls = set(re.findall(r'CEDAR_TRACE pull=\d+ session=(\d+) ', log))
    expected = (str({'hevc':2,'h264':1}[codec]), *shape)
    visible_shape = ('1920', '1080') if args.omx_fit else shape
    matching_sessions = {s for s, c, w, h in sessions
                         if s in pulls and (c, w, h) == expected and (s, *visible_shape) in hw}
    match = bool(matching_sessions)
    shown = re.findall(r'\[Parsed_showinfo_\d+ @ [^\]]+\] n:\s*\d+\s+pts:.*? s:(\d+)x(\d+)\b', log)
    clock_label = 'A-V' if args.audio else 'M-V'
    stats = re.findall(r'([-+]?\d+\.\d+)\s+' + clock_label + r':\s*([-+\d.]+)\s+fd=\s*(\d+)', log)
    drops = max((int(row[2]) for row in stats), default=None)
    clock_end = float(stats[-1][0]) if stats else None
    errors = [line.strip() for line in log.splitlines() if re.search(
        'undefined symbol|symbol lookup error|failed|unknown decoder|cannot open|native fallback=', line, re.I)]
    checks = dict(exited_cleanly=proc.returncode == 0, all_frames=len(shown) == total_frames,
                  full_dimensions=bool(shown) and set(shown) == {shape}, zero_player_drops=drops == 0,
                  clock_reached_end=clock_end is not None and abs(clock_end-duration) < .25,
                  realtime_wall=.97*total_duration <= elapsed <= 1.03*total_duration+1,
                  decoder_path=(match and 'T736_CEDAR_CLIENT: preconnected' in log and
                                'native fallback=' not in log and interrupts >= .97*total_frames)
                               if args.mode == 'cedar' else not sessions and interrupts == 0)
    if args.renderer == 'powervr':
        checks['pvr_loaded'] = bool(pvr_libs)
        record['pvr_libraries'] = sorted(pvr_libs)
    record['player_filter_sizes'] = sorted({f'{w}x{h}' for w,h in shown})
    if args.native_fit or args.omx_fit:
        del checks['full_dimensions']
        checks['full_source_session'] = shape == ('3840', '2160') and match
        marker = ('T736_CEDAR_PROXY: input=3840x2160 display=1920x1080 omx-scale=1'
                  if args.omx_fit else 'T736_CEDAR_PROXY: decoded=3840x2160 display=1920x1080 i420-box2x2')
        mode = 'omx-scale' if args.omx_fit else 'shm-box'
        shared = 'x'.join(visible_shape)
        negotiated = any(f'T736_CEDAR_PANEL: session={s} mode={mode} input=3840x2160 '
                         f'shared={shared} display=1920x1080' in log for s in matching_sessions)
        checks['omx_fit_geometry' if args.omx_fit else 'native_fit_geometry'] = (
            set(shown) == {('1920', '1080')} and (negotiated or marker in log))
    if args.audio:
        skew = sorted(abs(float(offset)) for t, offset, _ in stats if 1 <= float(t) < duration-.5)
        record['av_offset_p95_seconds'] = skew[(95*len(skew)-1)//100] if skew else None
        checks['audio_video_sync'] = bool(skew) and record['av_offset_p95_seconds'] <= .08
    if args.scale_to_window:
        panel = re.findall(r'\[showinfo@panel @ [^\]]+\] n:\s*\d+\s+pts:.*? s:(\d+)x(\d+)\b', log)
        record['panel_sizes'] = sorted({f'{w}x{h}' for w,h in panel})
        checks['scaled_output'] = (len(panel) == len(shown) and bool(panel) and
                                   all(int(w) <= 1920 and int(h) <= 1080 for w,h in panel))
    if args.present_trace:
        summary = re.search(r'T736_FFPLAY_PRESENT frames=(\d+) span_ms=([\d.]+) '
                            r'gap_p95_ms=([\d.]+) gap_max_ms=([\d.]+)', log)
        checks['presented_every_frame'] = bool(summary) and int(summary[1]) == total_frames
        if summary:
            record['sdl_present'] = dict(frames=int(summary[1]), span_ms=float(summary[2]),
                                         gap_p95_ms=float(summary[3]), gap_max_ms=float(summary[4]))
            checks['p95_presentation_gap'] = float(summary[3]) <= 1.5*1000*duration/frames
        upload = re.search(r'T736_FFPLAY_UPLOAD mean_upload_ms=([\d.]+) '
                           r'mean_upload_to_present_ms=([\d.]+)', log)
        if upload:
            record['texture_upload'] = dict(mean_ms=float(upload[1]), through_present_mean_ms=float(upload[2]))
    record.update(exit_status=proc.returncode, wall_seconds=round(elapsed, 3), irq_delta=interrupts,
                  frames_at_player_filter=len(shown), player_drops=drops, final_clock=clock_end,
                  broker=[s for s in broker.splitlines() if 'CEDAR_BROKER:' in s][-20:],
                  diagnostics=errors[-8:], checks=checks, status='passed' if all(checks.values()) else 'not_verified')
    if not shown:
        record['player_tail'] = log.splitlines()[-6:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('clip', type=Path)
    parser.add_argument('--mode', choices=['cedar','software'], default='cedar')
    parser.add_argument('--renderer', choices=['software','powervr'], default='software')
    parser.add_argument('--present-trace', type=Path, help='ARM64 shared library built from ffplay_present_trace.c')
    parser.add_argument('--keep-frames', action='store_true', help='Retain late frames with the same external master clock')
    parser.add_argument('--loops', type=int, default=1,
                        help='Number of playback passes with a seek to the beginning between passes')
    parser.add_argument('--wait-video-start', action='store_true',
                        help='Enable the bounded audio start option of the AtlasA1 0.1-4 FFplay')
    scaling = parser.add_mutually_exclusive_group()
    scaling.add_argument('--scale-to-window', action='store_true',
                        help='Fit the fully decoded picture inside 1920×1080 before uploading its SDL texture')
    scaling.add_argument('--native-fit', action='store_true',
                        help='Require full UHD broker output and native-client 1920×1080 box-filtered images')
    scaling.add_argument('--omx-fit', action='store_true',
                        help='Require a UHD input session and half-size images from the OMX decoder')
    parser.add_argument('--user', default='t736')
    parser.add_argument('--player', type=Path, default=Path('/usr/bin/ffplay'))
    parser.add_argument('--audio', action='store_true', help='Decode audio to the dummy device and use its clock')
    parser.add_argument('--ffmpeg-lib', type=Path, default=Path('/opt/t736-browser-ffmpeg-v7/lib'))
    parser.add_argument('--client-lib', type=Path,
                        default=Path('/opt/t736-cedar-transport-v2/lib/libt736_cedar_client.so'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.loops < 1 or (args.loops > 1 and not (args.keep_frames and args.present_trace)):
        parser.error('multiple playback passes require --keep-frames and --present-trace, and loops must be positive')
    if args.wait_video_start and not args.audio:
        parser.error('--wait-video-start requires --audio')
    if args.keep_frames and not args.present_trace:
        parser.error('--keep-frames requires --present-trace to measure actual output pacing')
    if (args.native_fit or args.omx_fit) and args.mode != 'cedar':
        parser.error('--native-fit and --omx-fit require Cedar')
    record = dict(player='FFplay', kernel=os.uname().release, mode=args.mode,
                  probe_cpu_affinity=sorted(os.sched_getaffinity(0)),
                  loops=args.loops, wait_video_start=args.wait_video_start,
                  display='SDL dummy software renderer' if args.renderer == 'software' else 'SDL offscreen GLES2',
                  window=[1920,1080], audio=args.audio, keep_late_frames=args.keep_frames)
    with args.output.open('x', encoding='utf-8') as out:
        try:
            play(args, record)
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
            record.update(status='incomplete', error=str(exc))
        json.dump(record, out, indent=2)
        out.write('\n')
    print(json.dumps(record))
    return 0 if record['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
