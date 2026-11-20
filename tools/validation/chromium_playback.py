#!/usr/bin/env python3
"""Measure an isolated, sandboxed Chromium window; never attach to user profiles.

Requires python3-websocket, ffprobe and a logged-in Wayland session. Run as the
desktop user. GPU feature support alone is not hardware-decoder acceptance.
"""
import argparse
import base64
import functools
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request

import websocket


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=10, suppress_origin=True)
        self.seq = 0
        self.events = []

    def call(self, method, params=None):
        self.seq += 1
        self.ws.send(json.dumps(dict(id=self.seq, method=method, params=params or {})))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get('id') == self.seq:
                if 'error' in reply:
                    raise RuntimeError(reply['error'])
                return reply.get('result', {})
            self.events.append(reply)

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', dict(expression=expression,
                                                   returnByValue=True, awaitPromise=True))
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result['result'].get('value')


class FixtureServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == '/player.html':
            body = b'''<!doctype html><meta charset="utf-8"><title>AtlasA1 Chromium playback test</title>
<style>body{margin:0;background:#111;color:white}video{width:100vw;height:90vh}</style>
<video id="v" muted playsinline></video><script>
window.presented=0;window.lastFrame=null;
function frame(t,m){presented++;lastFrame={mediaTime:m.mediaTime,presentedFrames:m.presentedFrames};v.requestVideoFrameCallback(frame)}
v.requestVideoFrameCallback(frame);
window.snapshot=()=>({time:performance.now(),currentTime:v.currentTime,duration:v.duration,
width:v.videoWidth,height:v.videoHeight,paused:v.paused,ended:v.ended,readyState:v.readyState,
error:v.error?{code:v.error.code,message:v.error.message}:null,
quality:{total:v.getVideoPlaybackQuality().totalVideoFrames,dropped:v.getVideoPlaybackQuality().droppedVideoFrames},
callbacks:presented,lastFrame});
</script>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=18)
    p.add_argument('--screenshot', action='store_true', help='capture only the test video page')
    p.add_argument('--flag', action='append', default=[])
    args = p.parse_args()
    if os.geteuid() == 0:
        p.error('run as the desktop user, not root')
    fixture = args.fixture.resolve(strict=True)
    if args.output.exists():
        p.error('output exists; choose a new evidence path')
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                         '-show_format', '-of', 'json', str(fixture)], text=True))
    duration = float(probe['format']['duration'])
    if args.seconds <= 0 or args.seconds + 5 > duration:
        p.error('fixture must exceed measurement duration by at least five seconds')
    forbidden = ('--no-sandbox', '--disable-gpu-sandbox', '--user-data-dir',
                 '--remote-debugging', '--disable-web-security')
    if any(flag.startswith(forbidden) for flag in args.flag):
        p.error('profile, debugging and sandbox overrides are not allowed')
    record = dict(schema=1, status='INCOMPLETE', fixture=str(fixture), probe=probe,
                  kernel=os.uname().release, flags=args.flag)
    process = server = page = browser = None
    with tempfile.TemporaryDirectory(prefix='atlasa1-chromium-') as work:
        profile = Path(work) / 'profile'
        # Expose only this fixture, never the user's files or browser profile.
        serve = Path(work) / 'http'
        serve.mkdir()
        (serve / 'fixture.mp4').symlink_to(fixture)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                    functools.partial(FixtureServer, directory=str(serve)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        logpath = args.output.with_suffix('.chromium.log')
        try:
            with logpath.open('x') as log:
                command = ['chromium', '--user-data-dir=' + str(profile),
                           '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                           '--no-first-run', '--no-default-browser-check',
                           '--autoplay-policy=no-user-gesture-required', '--ozone-platform=wayland',
                           '--window-size=1280,800', '--enable-logging=stderr',
                           *args.flag, 'about:blank']
                record['command'] = command
                process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                active = profile / 'DevToolsActivePort'
                deadline = time.monotonic() + 30
                while not active.exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Chromium did not publish its test debug endpoint')
                    time.sleep(.2)
                port, endpoint = active.read_text().splitlines()[:2]
                browser = CDP(f'ws://127.0.0.1:{port}{endpoint}')
                record['version'] = browser.call('Browser.getVersion')
                record['gpu'] = browser.call('SystemInfo.getInfo')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=10) as response:
                    targets = json.load(response)
                target = next(t for t in targets if t['type'] == 'page' and t['url'] == 'about:blank')
                page = CDP(target['webSocketDebuggerUrl'])
                page.call('Media.enable')
                page.call('Page.navigate', {'url': url + '/player.html'})
                deadline = time.monotonic() + 15
                while page.evaluate('typeof window.snapshot') != 'function':
                    if time.monotonic() > deadline:
                        raise RuntimeError('fixture page did not load')
                    time.sleep(.2)
                page.evaluate('v.src="/fixture.mp4";v.play().then(()=>true)')
                deadline = time.monotonic() + 20
                while page.evaluate('v.currentTime') < 2:
                    if time.monotonic() > deadline:
                        raise RuntimeError('video did not start: ' + str(page.evaluate('snapshot()')))
                    time.sleep(.25)
                start = page.evaluate('snapshot()')
                record['start'] = start
                if not start['width'] or not start['height']:
                    record['status'] = 'FAILED_NO_VIDEO'
                    raise RuntimeError('media clock advanced without a decoded video track')
                deadline = time.monotonic() + args.seconds
                while time.monotonic() < deadline:
                    time.sleep(.5)
                    record['last'] = page.evaluate('snapshot()')
                end = record['last']
                elapsed = (end['time'] - start['time']) / 1000
                total = end['quality']['total'] - start['quality']['total']
                dropped = end['quality']['dropped'] - start['quality']['dropped']
                record['measurement'] = dict(seconds=elapsed, total=total, dropped=dropped,
                    presented_fps=(total-dropped)/elapsed,
                    video_seconds=end['currentTime']-start['currentTime'],
                    callbacks=end['callbacks']-start['callbacks'])
                record['status'] = 'MEASURED_NOT_HARDWARE_ACCEPTANCE'
                if end['error'] or end['ended'] or total <= 0:
                    record['status'] = 'FAILED_PLAYBACK_WINDOW'
                record['gpu_after_playback'] = browser.call('SystemInfo.getInfo')
                page.evaluate('v.pause()')
                if args.screenshot:
                    screenshot = args.output.with_suffix('.frame.png')
                    with screenshot.open('xb') as stream:
                        stream.write(base64.b64decode(page.call('Page.captureScreenshot')['data']))
                    record['screenshot'] = str(screenshot)
        except Exception as exc:
            record['error'] = str(exc)
        finally:
            if page:
                record['media_events'] = [e for e in page.events if e.get('method', '').startswith('Media.')]
                page.ws.close()
            if browser:
                browser.ws.close()
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            server.shutdown()
            args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ('status', 'measurement', 'error') if k in record}))
    return 0 if record['status'].startswith('MEASURED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
