#!/usr/bin/env python3
"""Check the installed AtlasA1 launcher in a disposable native Wayland profile.

Run as the desktop user. The compositor check is read-only, and Marionette's
system access is enabled only for this short-lived loopback test instance.
Animation callbacks measure browser scheduling, not physical HDMI scanout.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from urllib.parse import quote
from firefox_renderer_probe import Marionette


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--launcher', type=Path, default=Path('/usr/bin/atlasa1-firefox'))
    args = ap.parse_args()
    if args.output.exists() or args.output.with_suffix('.log').exists():
        ap.error('Output exists; preserve previous evidence')
    pid = subprocess.check_output(['pgrep', '-u', str(os.getuid()), '-x', 'gnome-shell'], text=True).split()[-1]
    source = dict(item.decode().split('=', 1) for item in Path('/proc', pid, 'environ').read_bytes().split(b'\0') if b'=' in item)
    env = os.environ.copy()
    for key in ('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_SESSION_TYPE'):
        if key in source:
            env[key] = source[key]
    if env.get('XDG_SESSION_TYPE') != 'wayland':
        ap.error('The active GNOME session must use Wayland')
    env['WAYLAND_DISPLAY'] = 'wayland-0'
    env['GDK_BACKEND'] = 'wayland'
    env['MOZ_REMOTE_ALLOW_SYSTEM_ACCESS'] = '1'
    record = {'session_type': 'wayland', 'complete': False,
              'graphics_pass': False, 'animation_metric': 'requestAnimationFrame callbacks, not HDMI frames'}
    with tempfile.TemporaryDirectory(prefix='atlas-wayland-firefox-') as directory:
        env['T736_CEDAR_PROFILE'] = directory
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        preferences = {'marionette.port': port, 'browser.shell.checkDefaultBrowser': False,
                       'browser.aboutwelcome.enabled': False, 'browser.startup.firstrunSkipsHomepage': True}
        Path(directory, 'user.js').write_text(''.join(f'user_pref({json.dumps(k)}, {json.dumps(v)});\n' for k, v in preferences.items()))
        log = args.output.with_suffix('.log').open('w')
        process = subprocess.Popen([str(args.launcher), '--marionette', 'about:blank'],
                                   env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        connection = None
        try:
            while time.monotonic() - started < 60:
                if process.poll() is not None:
                    raise RuntimeError(f'Firefox exited: {process.returncode}')
                try:
                    connection = socket.create_connection(('127.0.0.1', port), timeout=1)
                    break
                except OSError:
                    time.sleep(.25)
            if connection is None:
                raise RuntimeError('Marionette startup timed out')
            client = Marionette(connection, 30)
            record['startup_seconds'] = time.monotonic() - started
            record['session'] = client.command('WebDriver:NewSession', {'acceptInsecureCerts': False})
            client.command('WebDriver:SetTimeouts', {'pageLoad': 20000, 'script': 15000})
            client.command('Marionette:SetContext', {'value': 'chrome'})
            result = client.command('WebDriver:ExecuteScript', {'args': [], 'script': '''
                const gfx = Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo);
                return {features: gfx.getFeatures(), renderer: gfx.adapterDescription};
            '''})
            record['graphics'] = result.get('value', result)
            record['graphics_pass'] = (record['graphics']['features']['compositor'] == 'webrender'
                                       and 'PowerVR' in record['graphics']['renderer'])
            client.command('Marionette:SetContext', {'value': 'content'})
            page = '''<!doctype html><style>body{background:#223;color:white}div{width:100px;height:200px;background:#28a}</style>
                <p>AtlasA1 browser animation test</p><div></div><script>
                window.samples=[];const box=document.querySelector('div');
                function step(t){samples.push(t);box.style.transform=`translateX(${(t/4)%600}px)`;
                    if(samples.length<2000)requestAnimationFrame(step)}requestAnimationFrame(step);
                </script>'''
            client.command('WebDriver:Navigate', {'url': 'data:text/html,' + quote(page)})
            time.sleep(10)
            result = client.command('WebDriver:ExecuteScript', {'args': [], 'script': '''
                const a=window.samples||[],g=a.slice(1).map((v,i)=>v-a[i]);
                return {callbacks:a.length,visible:document.visibilityState,
                    fps:a.length>1?1000*(a.length-1)/(a.at(-1)-a[0]):0,
                    maxGapMs:g.length?Math.max(...g):null,gapsOver25ms:g.filter(v=>v>25).length};
            '''})
            record['animation'] = result.get('value', result)
            record['complete'] = True
            client.command('WebDriver:DeleteSession')
        except Exception as error:
            record['error'] = str(error)
        finally:
            if connection:
                connection.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            log.close()
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return 0 if record['complete'] and record['graphics_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
