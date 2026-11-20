#!/usr/bin/env python3
"""Select the validated panel mode from GNOME's current physical output."""
import os


def panel_mode(state):
    _, monitors, logical, _ = state
    if len(logical) != 1 or len(logical[0][5]) != 1:
        return None
    active = [mode for spec, modes, _ in monitors
              if tuple(spec) == tuple(logical[0][5][0])
              for mode in modes if mode[-1].get('is-current', False)]
    if len(active) != 1:
        return None
    _, width, height, refresh, *_ = active[0]
    return '1920x1080' if (width, height) == (1920, 1080) and 59 <= refresh <= 61 else None


def main():
    if (os.environ.get('XDG_SESSION_TYPE') != 'wayland'
            or 'GNOME' not in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':')):
        return
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync('org.gnome.Mutter.DisplayConfig',
                              '/org/gnome/Mutter/DisplayConfig',
                              'org.gnome.Mutter.DisplayConfig', 'GetCurrentState',
                              None, None, Gio.DBusCallFlags.NONE, 1500, None)
        mode = panel_mode(reply.unpack())
        if mode:
            print(mode)
    except (ImportError, ValueError, TypeError, IndexError, KeyError, RuntimeError):
        return
    except Exception:
        # D-Bus/GI errors disable scaling. They must not prevent browser startup.
        return


if __name__ == '__main__':
    main()
