#!/usr/bin/env python3
"""Measure sandboxed Firefox video frames and Cedar IRQs offscreen or on Wayland."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import select
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KNOWN_HEVC = '37f109312141defa1e1afcd38e9cfe92527fa4ab1103a554bdfbe6ba689fcd20'


def run_virtual_display(xvfb, width, height, command):
    """Run the test client as its normal user on a private local X server."""
    auth = Path(os.environ['T736_CEDAR_PROFILE']) / 'x-test-authority'
    # FamilyWild with empty address/display fields matches the display chosen by Xvfb.
    with auth.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(struct.pack('>H', 65535))
        for field in (b'', b'', b'MIT-MAGIC-COOKIE-1', secrets.token_bytes(16)):
            stream.write(struct.pack('>H', len(field)) + field)
    server = subprocess.Popen([xvfb, '-displayfd', '1', '-screen', '0', f'{width}x{height}x24',
                               '-nolisten', 'tcp', '-auth', str(auth)], stdout=subprocess.PIPE)
    try:
        if not select.select([server.stdout], [], [], 12)[0]:
            raise TimeoutError('Virtual X server did not start')
        number = int(server.stdout.readline().strip())
        env = dict(os.environ, DISPLAY=f':{number}', XAUTHORITY=str(auth), GDK_BACKEND='x11')
        return subprocess.call(command, env=env)
    finally:
        server.terminate()
        server.wait(timeout=8)

PAGE = b'''<!doctype html><meta charset="utf-8"><style>*{margin:0}video{width:100vw;height:100vh}</style>
<video muted playsinline preload="auto" src="clip.mp4"></video>
<script>
const v = document.querySelector('video');
let done = false;
async function sample(phase, reason) {
  const q = v.getVideoPlaybackQuality();
  await fetch('stats', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phase, reason, wallMs:performance.now(), mediaTime:v.currentTime,
      width:v.videoWidth, height:v.videoHeight, paused:v.paused, rate:v.playbackRate,
      total:q.totalVideoFrames, dropped:q.droppedVideoFrames,
      parsed:v.mozParsedFrames, decoded:v.mozDecodedFrames, presented:v.mozPresentedFrames,
      painted:v.mozPaintedFrames, frameDelaySeconds:v.mozFrameDelay, visible:document.visibilityState,
      viewport:[innerWidth,innerHeight], videoBox:[v.clientWidth,v.clientHeight], dpr:devicePixelRatio})});
}
async function end(reason) {
  if (done) return;
  done = true;
  await sample('end',reason);
}
v.addEventListener('error', () => end('media error ' + v.error?.code));
v.addEventListener('ended', () => end('eos'));
async function watch() {
  if (done) return;
  try {
    await sample('tick','');
    if(v.currentTime >= WINDOW + 2) { await end('window'); v.pause(); }
  } finally { if (!done) setTimeout(watch,500); }
}
watch();
setTimeout(() => v.play().catch(err => end(String(err))), WARMUP_MS);
</script>'''


def irq_count():
    for line in Path('/proc/interrupts').read_text().splitlines():
        if 't736-cedar-wc' in line:
            return sum(map(int, re.match(r'\s*((?:\d+\s+)+)', line.split(':', 1)[1])[1].split()))
    return None


def fixture_info(path):
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest == KNOWN_HEVC:
        return {'codec_name':'hevc', 'width':1920, 'height':1080, 'avg_frame_rate':'60/1',
                'duration':'30.000000', 'sha256':digest}
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
           'stream=codec_name,width,height,avg_frame_rate,duration', '-of', 'json', str(path)]
    info = json.loads(subprocess.check_output(cmd, timeout=30))['streams'][0]
    info['sha256'] = digest
    return info


class Player(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == self.server.prefix:
            data = PAGE.replace(b'WINDOW', str(self.server.seconds).encode()).replace(
                b'WARMUP_MS', str(self.server.warmup * 1000).encode())
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path != self.server.prefix + 'clip.mp4':
            self.send_error(404)
            return
        path = self.server.clip
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(end, int(match[2])) if match[2] else end
            if start > end:
                self.send_error(416)
                return
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if requested:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as src:
                src.seek(start)
                while start <= end:
                    block = src.read(min(256 * 1024, end - start + 1))
                    if not block:
                        break
                    self.wfile.write(block)
                    start += len(block)
        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_POST(self):
        if self.path != self.server.prefix + 'stats':
            self.send_error(404)
            return
        if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
            self.send_error(403)
            return
        try:
            n = int(self.headers['Content-Length'])
            if not 1 <= n <= 4096:
                raise ValueError('length')
            data = json.loads(self.rfile.read(n))
            if data['phase'] not in ('tick', 'end'):
                raise ValueError('phase')
        except (ValueError, TypeError, KeyError):
            self.send_error(400)
            return
        data['irq'] = irq_count()
        self.server.samples.append(data)
        self.send_response(204)
        self.end_headers()
        if data['phase'] == 'end':
            self.server.done.set()


def journal(*args):
    p = subprocess.run(['journalctl', '--no-pager', '-b', '-o', 'cat', *args],
                       capture_output=True, text=True, timeout=12)
    return p.stdout if p.returncode == 0 else ''


def classify(samples, seconds, journal_lines, firefox_lines, info, rdd=(), decoded_size=None):
    window = [p for p in samples if p['mediaTime'] >= 2]
    if len(window) < 2:
        return {'status':'incomplete', 'reason':'video did not reach the measurement window'}
    a, b = window[0], window[-1]
    wall = (b['wallMs'] - a['wallMs']) / 1000
    media = b['mediaTime'] - a['mediaTime']
    total = b['total'] - a['total']
    dropped = b['dropped'] - a['dropped']
    presented = (b['presented'] - a['presented']
                 if all(isinstance(x.get('presented'), int) for x in (a, b)) else None)
    irq = b['irq'] - a['irq'] if a['irq'] is not None and b['irq'] is not None else None
    codec = {'h264':1, 'hevc':2}.get(info['codec_name'], 0)
    width, height = info['width'], info['height']
    decoded_width, decoded_height = decoded_size or (width, height)
    target_fps = rational(info['avg_frame_rate'])
    opens = re.findall(r'CEDAR_BROKER: open session=(\d+) codec=(\d+) (\d+)x(\d+)', journal_lines)
    markers = re.findall(r'CEDAR_BROKER: hardware frames=(\d+) session=(\d+) visible=(\d+)x(\d+)', journal_lines)
    matched = [s for s,c,w,h in opens if (int(c),int(w),int(h)) == (codec,width,height)]
    hw_marker = len(opens) == len(matched) == 1 and any(
        s in matched and (int(w),int(h)) == (decoded_width,decoded_height) for _,s,w,h in markers)
    rate = (total - dropped)/wall if wall > 0 else 0
    checks = {'window_completed': b['phase']=='end' and b['reason'] in ('window','eos')
              and wall >= seconds-1 and media >= seconds-1,
              'dimensions': (b['width'],b['height']) == (width,height),
              'normal_speed': all(p['rate']==1 for p in window) and wall > 0 and .97 <= media/wall <= 1.03,
              'browser_frame_rate': rate >= .98*target_fps and dropped == 0 and total >= 1
              and presented is not None and presented >= .98*wall*target_fps,
              'hardware_irq_rate': irq is not None and irq >= .95*target_fps*media,
              'matching_hardware_session': hw_marker,
              'rdd_seccomp_filter': any('Seccomp:\t2' in process['sandbox']
                                        and 'NoNewPrivs:\t1' in process['sandbox'] for process in rdd),
              'rdd_hardware_output': bool(re.search(
                  r'T736_CEDAR_CLIENT: preconnected .* rdd=1', firefox_lines))
              and 'T736_CEDAR_PROXY: bounded_batch' in firefox_lines,
              'no_fallback_logged': 'native fallback=' not in firefox_lines}
    if decoded_size:
        checks['explicit_hardware_scale'] = (
            'T736_CEDAR_PROXY: browser_panel input=3840x2160 output=1920x1080 hardware_scale=1' in firefox_lines
            and 'image_allocator output=1920x1080' in firefox_lines)
    return {'status':'passed' if all(checks.values()) else 'not_verified', 'checks':checks,
            'decoded_size':[decoded_width,decoded_height],
            'output_mode':'hardware-scaled-to-1080p' if decoded_size else 'original-size',
            'wall_seconds':wall, 'media_seconds':media, 'total_delta':total,
            'dropped_delta':dropped, 'presented_delta':presented, 'browser_retained_fps':rate,
            'irq_delta':irq, 'broker_sessions':opens, 'broker_frame_markers':markers}


def rational(value):
    numerator, denominator = map(int, value.split('/'))
    return numerator / denominator


def rdd_snapshot(group, cpus=None):
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if os.getpgid(int(proc.name)) != group or 'RDD' not in (proc/'comm').read_text():
                continue
            entry = {'pid': int(proc.name)}
            entry['cpu_affinity_before'] = sorted(os.sched_getaffinity(int(proc.name)))
            if cpus:
                changed = 0
                for task in (proc/'task').glob('[0-9]*'):
                    try:
                        os.sched_setaffinity(int(task.name), cpus)
                        changed += 1
                    except ProcessLookupError:
                        pass
                entry['affinity_threads_changed'] = changed
                entry['cpu_affinity_after'] = sorted(os.sched_getaffinity(int(proc.name)))
            status = (proc/'status').read_text().splitlines()
            entry['sandbox'] = [line for line in status if line.startswith(('NoNewPrivs:', 'Seccomp:'))]
            try:
                entry['media_libraries'] = sorted({line.split()[-1] for line in (proc/'maps').read_text().splitlines()
                    if any(lib in line for lib in ('libavcodec.so.', 'libt736_cedar_client.so', 'libavutil.so.'))})
            except OSError as exc:
                entry['maps_error'] = str(exc)
            found.append(entry)
        except (OSError, ValueError):
            continue
    return found


def collect(args, record):
    import pwd
    uid = os.geteuid()
    user = pwd.getpwnam(args.user) if uid == 0 else pwd.getpwuid(uid)
    if user.pw_uid == 0:
        raise ValueError('Firefox requires a non-root desktop account')
    info = fixture_info(args.clip)
    if info['codec_name'] not in ('h264','hevc') or rational(info['avg_frame_rate']) <= 0:
        raise ValueError(f'unsupported fixture {info}')
    record['fixture'] = info
    if args.decoded_size and (info['codec_name'],info['width'],info['height'],args.decoded_size) != ('hevc',3840,2160,[1920,1080]):
        raise ValueError('Only the explicit HEVC 3840x2160 to 1920x1080 candidate is supported')
    record['requested_decoded_size'] = args.decoded_size
    record['launcher'] = str(args.launcher)
    record['launcher_sha256'] = hashlib.sha256(args.launcher.read_bytes()).hexdigest()
    record['kernel'] = os.uname().release
    record['desktop_uid'] = user.pw_uid
    record['warmup_seconds'] = args.warmup
    width, height = args.screen or (info['width'], info['height'])
    record['headless_screen'] = [width, height]
    before = journal('-n','1','--show-cursor')
    cursor = re.search(r'^-- cursor: (.+)$', before, re.M)
    with tempfile.TemporaryDirectory(prefix='t736-firefox-') as profile, \
         tempfile.TemporaryFile(mode='w+b') as log, ThreadingHTTPServer(('127.0.0.1',0),Player) as srv:
        if uid == 0:
            os.chown(profile, user.pw_uid, user.pw_gid)
        debug_connection = None
        debug_client = None
        debug_next = 0
        if args.debug_media:
            from firefox_renderer_probe import Marionette
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                debug_port = listener.getsockname()[1]
            prefs = Path(profile) / 'user.js'
            prefs.write_text(f'user_pref("marionette.port", {debug_port});\n', encoding='utf-8')
            if uid == 0:
                os.chown(prefs, user.pw_uid, user.pw_gid)
            record['debug_media'] = []
        env = dict(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name,
                   PATH='/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8', MOZ_HEADLESS='1',
                   MOZ_HEADLESS_WIDTH=str(width), MOZ_HEADLESS_HEIGHT=str(height),
                   T736_CEDAR_PROFILE=profile, MOZ_LOG='PlatformDecoderModule:4')
        if args.debug_media:
            env['MOZ_REMOTE_ALLOW_SYSTEM_ACCESS'] = '1'
        runtime_dir = Path(f'/run/user/{user.pw_uid}')
        if runtime_dir.is_dir():
            env['XDG_RUNTIME_DIR'] = str(runtime_dir)
        if args.wayland:
            if not (runtime_dir/'wayland-0').is_socket():
                raise ValueError('Expected the active GNOME wayland-0 socket')
            env.pop('MOZ_HEADLESS')
            env.update(WAYLAND_DISPLAY='wayland-0', XDG_SESSION_TYPE='wayland',
                       GDK_BACKEND='wayland', DBUS_SESSION_BUS_ADDRESS='unix:path='+str(runtime_dir/'bus'))
        srv.prefix = '/' + secrets.token_urlsafe(16) + '/'
        srv.warmup = args.warmup
        srv.clip, srv.seconds, srv.samples, srv.done = args.clip, args.seconds, [], threading.Event()
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        identity = (dict(user=user.pw_uid,group=user.pw_gid,
                         extra_groups=os.getgrouplist(user.pw_name,user.pw_gid)) if uid == 0 else {})
        geometry = ['--kiosk', '--width', str(width), '--height', str(height)] if args.screen else []
        # The Cedar launcher consumes T736_CEDAR_PROFILE. A stock Firefox
        # needs the same isolated profile and its own process explicitly.
        isolated = ['--no-remote', '--profile', profile] if args.launcher.name == 'firefox' else []
        command = [args.launcher, *isolated, *geometry, f'http://127.0.0.1:{srv.server_port}{srv.prefix}']
        if args.debug_media:
            command[1:1] = ['--marionette', '--remote-allow-system-access']
            command[-1] = 'about:blank'
        if args.xvfb:
            record['display_backend'] = 'Xvfb'
            env.pop('MOZ_HEADLESS')
            command = [sys.executable, str(Path(__file__).resolve()), '_xvfb', args.xvfb.resolve(),
                       str(width), str(height), *command]
        elif not args.wayland:
            command.insert(1, '--headless')
        else:
            record['display_backend'] = 'GNOME Wayland'
        proc = subprocess.Popen(command,
                                stdout=log, stderr=subprocess.STDOUT, env=env, cwd=profile,
                                start_new_session=True, **identity)
        try:
            deadline = time.monotonic()+args.seconds+args.warmup+90
            snapshot_time = time.monotonic()
            while not srv.done.wait(.25) and proc.poll() is None and time.monotonic()<deadline:
                if args.debug_media and debug_client is None and time.monotonic() >= debug_next:
                    try:
                        debug_connection = socket.create_connection(('127.0.0.1', debug_port), timeout=1)
                        debug_client = Marionette(debug_connection, 60)
                        debug_client.command('WebDriver:NewSession', {})
                        debug_client.command('WebDriver:SetTimeouts', {'script': 2000})
                        debug_client.command('Marionette:SetContext', {'value': 'chrome'})
                        graphics = debug_client.command('WebDriver:ExecuteScript', {'args': [], 'script': '''
                            const gfx = Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo);
                            const prefs = Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefBranch);
                            return {features: gfx.getFeatures(), renderer: gfx.adapterDescription,
                                waylandVsync: prefs.getBoolPref("widget.wayland.vsync.enabled"),
                                layoutFrameRate: prefs.getIntPref("layout.frame_rate")};
                        '''})
                        record['graphics'] = graphics.get('value', graphics)
                        debug_client.command('Marionette:SetContext', {'value': 'content'})
                        debug_client.command('WebDriver:Navigate', {
                            'url': f'http://127.0.0.1:{srv.server_port}{srv.prefix}'})
                        debug_connection.settimeout(3)
                    except ConnectionRefusedError:
                        if debug_connection:
                            debug_connection.close()
                        debug_client = None
                        debug_next = time.monotonic() + 1
                if (srv.samples and srv.samples[-1]['mediaTime'] >= 2
                        and time.monotonic() >= snapshot_time
                        and not any('Seccomp:\t2' in p['sandbox'] for p in record.get('rdd', []))):
                    record['rdd'] = rdd_snapshot(proc.pid, args.rdd_cpus)
                    snapshot_time = time.monotonic() + 2
                if (args.debug_media and debug_client is not None and srv.samples and srv.samples[-1]['mediaTime'] >= 3
                        and time.monotonic() >= debug_next):
                    debug_next = time.monotonic() + 5
                    try:
                        script = Path(__file__).with_name('firefox_media_debug_snapshot.js').read_text(encoding='utf-8')
                        response = debug_client.command('WebDriver:ExecuteAsyncScript', {
                            'script': script, 'args': [], 'newSandbox': True, 'sandbox': 'system'})
                        record['debug_media'].append(response.get('value', response))
                    except (OSError, ValueError, RuntimeError, EOFError) as exc:
                        record['debug_media'].append({'error': str(exc)})
                        debug_next = float('inf')
            record['firefox_exit_before_cleanup'] = proc.poll()
            record['samples'] = list(srv.samples)
        finally:
            if debug_connection:
                debug_connection.close()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            srv.shutdown()
            thread.join()
        log.seek(0)
        lines = [l.decode('utf-8','replace').strip() for l in log
                 if any(key in l for key in (b'T736_', b'CEDAR_STAGE', b'error', b'failed', b'ERROR', b'cannot be preloaded'))]
        record['firefox_diagnostics'] = lines[-80:]
        raw = journal('--after-cursor', cursor[1], '-u', args.unit) if cursor else ''
        record['broker_log'] = [s for s in raw.splitlines() if 'CEDAR_BROKER:' in s][-80:]
        record['result'] = classify(record['samples'], args.seconds, raw, '\n'.join(lines), info,
                                    record.get('rdd', []), args.decoded_size)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('clip',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--xvfb',type=Path,help='Use a private virtual X server executable instead of Firefox headless mode')
    ap.add_argument('--wayland',action='store_true',help='Play visibly in the current GNOME Wayland session')
    ap.add_argument('--debug-media', action='store_true',
                    help='Read internal drop counters via loopback Marionette in the isolated test profile')
    ap.add_argument('--rdd-cpus',type=int,nargs='+',help='Diagnostic affinity for this temporary Firefox RDD only')
    ap.add_argument('--seconds',type=int,default=20)
    ap.add_argument('--decoded-size', nargs=2, type=int, metavar=('WIDTH','HEIGHT'),
                    help='Explicitly validate the HEVC 4K-to-1080p candidate; never count it as original-size output')
    ap.add_argument('--warmup', type=int, default=0,
                    help='Wait on the test page before playback to separate browser startup load')
    ap.add_argument('--screen', nargs=2, type=int, metavar=('WIDTH', 'HEIGHT'),
                    help='set headless screen and kiosk window size; report the actual CSS video box separately')
    ap.add_argument('--user',default='t736')
    ap.add_argument('--launcher',type=Path,default=Path('/usr/local/bin/t736-firefox-cedar'))
    ap.add_argument('--unit',default='t736-cedar.service')
    args = ap.parse_args()
    if args.rdd_cpus and not set(args.rdd_cpus) <= os.sched_getaffinity(0):
        ap.error('--rdd-cpus must be a subset of the CPUs available to this test')
    if args.wayland and args.xvfb:
        ap.error('--wayland and --xvfb are mutually exclusive')
    if not 2 <= args.seconds <= 3600:
        ap.error('measurement window must be 2..3600 seconds')
    if not 0 <= args.warmup <= 120:
        ap.error('warmup must be 0..120 seconds')
    if args.screen and not all(64 <= n <= 8192 for n in args.screen):
        ap.error('screen dimensions must be 64..8192')
    record = {'schema':1,'kind':'t736-sandboxed-firefox-headless-playback'}
    if args.wayland:
        record['kind'] = 'atlasa1-sandboxed-firefox-wayland-playback'
    with args.output.open('x',encoding='utf-8') as out:
        try:
            collect(args,record)
        except (OSError, ValueError, KeyError, RuntimeError, EOFError, subprocess.SubprocessError) as exc:
            record['result'] = {'status':'incomplete','reason':str(exc)}
        json.dump(record,out,indent=2)
        out.write('\n')
    print(json.dumps(record['result']))
    return 0 if record['result']['status']=='passed' else 2


if __name__ == '__main__':
    if sys.argv[1:2] == ['_xvfb']:
        raise SystemExit(run_virtual_display(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:]))
    raise SystemExit(main())
