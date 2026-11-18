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
    with clip.open('rb') as src:
        stream['sha256'] = hashlib.file_digest(src, 'sha256').hexdigest()
    record['fixture'] = stream
    user = pwd.getpwnam(args.user)
    if not user.pw_uid or os.geteuid() != 0:
        raise ValueError('run as root and select an unprivileged FFplay user')
    env = dict(PATH='/usr/bin:/bin', LANG='C', HOME=user.pw_dir, SDL_VIDEODRIVER='dummy',
               SDL_AUDIODRIVER='dummy', SDL_RENDER_DRIVER='software', AV_LOG_FORCE_NOCOLOR='1')
    if args.mode == 'cedar':
        libs = [args.client_lib, args.ffmpeg_lib/'libavutil.so.59', args.ffmpeg_lib/'libavcodec.so.61']
        for lib in libs:
            lib.resolve(strict=True)
        env.update(T736_CEDAR_ENABLE='1', T736_CEDAR_TEST_CLIENT='1', T736_CEDAR_TRACE='1',
                   LD_PRELOAD=':'.join(map(str, libs)))
    decoder = codec + ('_cedar' if args.mode == 'cedar' else '')
    cmd = ['/usr/bin/ffplay', '-hide_banner', '-loglevel', 'info', '-stats', '-autoexit',
           '-an', '-sn', '-sync', 'ext', '-framedrop', '-vcodec', decoder,
           '-vf', 'showinfo=checksum=0', '-x', '1920', '-y', '1080', '-i', str(clip)]
    cursor = re.search(r'^-- cursor: (.+)$', journal('-n', '1', '--show-cursor'), re.M)
    if not cursor:
        raise ValueError('missing starting journal cursor')
    irq_start = irq()
    start = time.monotonic()
    proc = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, timeout=2*duration + 20,
                          user=user.pw_uid, group=user.pw_gid,
                          extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
    elapsed, interrupts = time.monotonic() - start, irq() - irq_start
    log = proc.stderr.decode('utf-8', 'replace')
    broker = journal('--after-cursor', cursor[1], '-u', 't736-cedar.service')
    sessions = re.findall(r'CEDAR_BROKER: open session=(\d+) codec=(\d+) (\d+)x(\d+)', broker)
    hw = re.findall(r'CEDAR_BROKER: hardware frames=\d+ session=(\d+) visible=(\d+)x(\d+)', broker)
    shape = (str(stream['width']), str(stream['height']))
    # FFplay can open and close a probe decoder before it opens the playing decoder.
    # Tie the pixels returned to this process to the service's matching lease.
    pulls = set(re.findall(r'CEDAR_TRACE pull=\d+ session=(\d+) ', log))
    expected = (str({'hevc':2,'h264':1}[codec]), *shape)
    match = any(s in pulls and (c, w, h) == expected and (s, w, h) in hw
                for s, c, w, h in sessions)
    shown = re.findall(r'\[Parsed_showinfo_\d+ @ [^\]]+\] n:\s*\d+\s+pts:.*? s:(\d+)x(\d+)\b', log)
    stats = re.findall(r'([-+]?\d+\.\d+)\s+M-V:\s*[-+\d.]+\s+fd=\s*(\d+)', log)
    drops = max((int(row[1]) for row in stats), default=None)
    clock_end = float(stats[-1][0]) if stats else None
    errors = [line.strip() for line in log.splitlines() if re.search(
        'undefined symbol|symbol lookup error|failed|unknown decoder|cannot open|native fallback=', line, re.I)]
    checks = dict(exited_cleanly=proc.returncode == 0, all_frames=len(shown) == frames,
                  full_dimensions=bool(shown) and set(shown) == {shape}, zero_player_drops=drops == 0,
                  clock_reached_end=clock_end is not None and abs(clock_end-duration) < .25,
                  realtime_wall=.97*duration <= elapsed <= 1.03*duration+1,
                  decoder_path=(match and 'T736_CEDAR_CLIENT: preconnected' in log and
                                'native fallback=' not in log and interrupts >= .97*frames)
                               if args.mode == 'cedar' else not sessions and interrupts == 0)
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
    parser.add_argument('--user', default='t736')
    parser.add_argument('--ffmpeg-lib', type=Path, default=Path('/opt/t736-browser-ffmpeg-v7/lib'))
    parser.add_argument('--client-lib', type=Path,
                        default=Path('/opt/t736-cedar-transport-v2/lib/libt736_cedar_client.so'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = dict(player='FFplay', kernel=os.uname().release, mode=args.mode,
                  display='SDL dummy video, 1920x1080 window, software renderer', audio=False)
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
