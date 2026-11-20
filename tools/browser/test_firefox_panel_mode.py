#!/usr/bin/env python3
"""Guard against silently scaling video on a 4K or multi-monitor desktop."""
import unittest
from firefox_panel_mode import panel_mode

SPEC = ('HDMI-1', 'vendor', 'monitor', 'serial')


def state(width=1920, height=1080, refresh=60, scale=1):
    mode = ('id', width, height, refresh, 1, [1, 2], {'is-current': True})
    return (1, [(SPEC, [mode], {})], [(0, 0, scale, 0, True, [SPEC], {})], {})


class PanelTests(unittest.TestCase):
    def test_physical_mode(self):
        self.assertEqual(panel_mode(state()), '1920x1080')
        self.assertEqual(panel_mode(state(refresh=59.94)), '1920x1080')
        self.assertIsNone(panel_mode(state(3840, 2160, scale=2)))
        self.assertIsNone(panel_mode(state(refresh=30)))
        self.assertIsNone(panel_mode(state(1080, 1920)))

    def test_multi_monitor_or_no_current_mode(self):
        s = state()
        s[2].append(s[2][0])
        self.assertIsNone(panel_mode(s))
        s = state()
        s[2][0][5].append(SPEC)
        self.assertIsNone(panel_mode(s))
        s = state()
        s[1][0][1][0][-1]['is-current'] = False
        self.assertIsNone(panel_mode(s))


if __name__ == '__main__':
    unittest.main()
