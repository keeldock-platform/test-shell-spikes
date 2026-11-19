#!/usr/bin/env python3
"""Keep the Screencast D-Bus sender alive until the recorder is stopped."""
import signal
import sys
from pathlib import Path

from gi.repository import Gio, GLib


def validate_result(success, filename, directory):
    path = Path(filename)
    if not success or not path.is_absolute() or path.suffix != '.webm':
        raise ValueError('GNOME Screencast did not return a successful absolute WebM path')
    path.resolve().relative_to(Path(directory).resolve())
    return path


def main():
    template, filename_file, directory = sys.argv[1:]
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    destination = 'org.gnome.Shell.Screencast'
    object_path = '/org/gnome/Shell/Screencast'
    interface = destination
    result = bus.call_sync(destination, object_path, interface, 'Screencast',
                           GLib.Variant('(sa{sv})', (template, {
                               'framerate': GLib.Variant('i', 60),
                               'draw-cursor': GLib.Variant('b', True)})),
                           GLib.VariantType.new('(bs)'), Gio.DBusCallFlags.NONE, 15000, None)
    success, filename = result.unpack()
    path = validate_result(success, filename, directory)
    loop = GLib.MainLoop()
    def stop():
        loop.quit()
        return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    Path(filename_file).write_text(str(path) + '\n')
    print(f'Screencast sender={bus.get_unique_name()} file={path.name}', flush=True)
    try:
        loop.run()
    finally:
        bus.call_sync(destination, object_path, interface, 'StopScreencast', None,
                      None, Gio.DBusCallFlags.NONE, 10000, None)
        print('Screencast stopped on original sender', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
