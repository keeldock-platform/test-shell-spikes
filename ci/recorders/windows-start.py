#!/usr/bin/env python3
"""Launch capture with file handles so PowerShell redirection cannot hold startup open."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def start(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg is unavailable')
    command = [ffmpeg, '-copyts', '-nostdin', '-hide_banner', '-loglevel', 'warning',
               '-y', '-f', 'gdigrab', '-framerate', '60', '-draw_mouse', '1',
               '-use_wallclock_as_timestamps', '1', '-i', 'desktop', '-c:v', 'libx264',
               '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-f', 'matroska', str(output)]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    with output.with_suffix('.log').open('wb') as log, output.with_suffix('.log.out').open('wb') as stdout:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=log,
                                   close_fds=True, creationflags=flags)
    output.with_suffix('.pid').write_text(str(process.pid))
    time.sleep(2)
    if process.poll() is not None:
        raise RuntimeError('ffmpeg exited during capture preflight')
    print(f'Capture started pid={process.pid}', flush=True)
    return process.pid


if __name__ == '__main__':
    start(Path(sys.argv[1]))
