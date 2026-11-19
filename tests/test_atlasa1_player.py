"""Verify user-visible launcher arguments without opening a desktop window."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


class AtlasPlayer(unittest.TestCase):
    def setUp(self):
        self.script = runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools/player/atlasa1-player'))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.movie = Path(self.temp.name)/'测试 clip with space.mp4'
        self.movie.touch()

    def launch(self, stream):
        probe_json = json.dumps({'streams':[stream]})
        with patch('subprocess.check_output', return_value=probe_json) as probe, \
             patch('os.execve') as execute, \
             patch.dict(os.environ, {'T736_CEDAR_TEST_CLIENT':'1', 'SDL_AUDIODRIVER':'dummy',
                                     'T736_CEDAR_PANEL':'1920x1080'}):
            self.script['main']([str(self.movie)])
        self.assertEqual(probe.call_args.args[0][-1], str(self.movie))
        executable, args, env = execute.call_args.args
        self.assertEqual(executable, '/opt/atlasa1-player/bin/ffplay')
        self.assertEqual(args[-2:], ['-i', str(self.movie)])
        self.assertIn('-noframedrop', args)
        self.assertNotIn('-an', args)
        self.assertNotIn('T736_CEDAR_TEST_CLIENT', env)
        self.assertEqual(env['SDL_RENDER_DRIVER'],'opengles2')
        self.assertEqual(env['SDL_AUDIODRIVER'],'dummy')
        return args, env

    def test_supported(self):
        args, env = self.launch(dict(codec_name='hevc', pix_fmt='yuv420p', width=1920, height=1080, field_order='progressive'))
        self.assertEqual(args[args.index('-vcodec')+1],'hevc_cedar')
        self.assertEqual(args.count('-wait_video_start'), 1)
        self.assertEqual(env['T736_CEDAR_NATIVE_PLAYER'],'1')
        self.assertNotIn('T736_CEDAR_PANEL', env)

    def test_match_panel_and_affinity(self):
        stream = dict(codec_name='hevc', pix_fmt='yuv420p', width=3840, height=2160)
        for compatible, panel, allowed, should_fit, should_pin in (
            (b'allwinner,t736\0', (1920, 1080), {4, 5, 6, 7}, True, True),
            (b'allwinner,t736\0', (1920, 1080), {4, 5}, True, False),
            (b'allwinner,t736\0', (3840, 2160), {6, 7}, False, False),
            (b'allwinner,t736\0', None, {6, 7}, False, False),
            (b'other\0', (1920, 1080), {6, 7}, False, False),
        ):
            with self.subTest(compatible=compatible, panel=panel, allowed=allowed), \
                 patch.object(Path, 'read_bytes', return_value=compatible), \
                 patch.dict(self.script['main'].__globals__, {'desktop_panel': lambda: panel}), \
                 patch('os.sched_getaffinity', return_value=allowed, create=True), \
                 patch('os.sched_setaffinity', create=True) as pin:
                _, env = self.launch(stream)
                self.assertEqual(env.get('T736_CEDAR_PANEL'), '1920x1080' if should_fit else None)
                if should_pin:
                    pin.assert_called_once_with(0, {6, 7})
                else:
                    pin.assert_not_called()

    def test_tenbit(self):
        args, env = self.launch(dict(codec_name='hevc', pix_fmt='yuv420p10le', width=3840, height=2160))
        self.assertNotIn('-vcodec',args)
        self.assertNotIn('-wait_video_start', args)
        self.assertNotIn('T736_CEDAR_NATIVE_PLAYER',env)
        self.assertNotIn('LD_PRELOAD',env)

    def test_audio_only(self):
        args, env = self.launch(dict(codec_name='aac'))
        self.assertNotIn('-wait_video_start', args)
        self.assertNotIn('T736_CEDAR_ENABLE', env)

    def test_wayland_runtime_and_single_clock(self):
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}, clear=True), \
             patch('os.path.isdir', return_value=True):
            _, env = self.launch(dict(codec_name='h264', pix_fmt='yuv420p', width=1920, height=1080))
        self.assertEqual(env['SDL_VIDEODRIVER'], 'wayland')
        self.assertEqual(env['SDL_RENDER_VSYNC'], '0')
        self.assertIn('/opt/atlasa1-img-wayland/runtime-gles', env['LD_LIBRARY_PATH'])
        self.assertEqual(env['LIBGL_DRIVERS_PATH'], '/opt/atlasa1-img-wayland/lib/dri')

    def test_x11_runtime(self):
        with patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True), \
             patch('os.path.isdir', return_value=True):
            _, env = self.launch(dict(codec_name='h264', pix_fmt='yuv420p', width=1920, height=1080))
        self.assertIn('/opt/t736-img-ddk-24.2-x11/runtime-gles', env['LD_LIBRARY_PATH'])
        self.assertNotIn('SDL_RENDER_VSYNC', env)


if __name__ == '__main__':
    unittest.main()
