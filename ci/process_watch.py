"""Bound a native process tree and report progress without pipe-drain deadlocks."""
import os
import signal
import subprocess
import time


def stop_tree(process, cleanup_grace=0):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)
    else:
        try:
            if cleanup_grace:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=cleanup_grace)
                    return
                except subprocess.TimeoutExpired:
                    pass
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=20)


def watched(command, *, label, timeout, cwd, env=None, heartbeat=30, cleanup_grace=0):
    started = time.monotonic()
    print(f'BEGIN {label} deadline={timeout}s', flush=True)
    process = subprocess.Popen(command, cwd=cwd, env=env,
                               start_new_session=os.name != 'nt')
    previous_handler = None
    if os.name != 'nt':
        def terminate(signum, frame):
            raise SystemExit(128 + signum)
        previous_handler = signal.signal(signal.SIGTERM, terminate)
    status = 124
    try:
        while True:
            elapsed = time.monotonic() - started
            remaining = timeout - elapsed
            if remaining <= 0:
                print(f'TIMEOUT {label} elapsed={elapsed:.1f}s pid={process.pid}', flush=True)
                stop_tree(process, cleanup_grace)
                break
            try:
                status = process.wait(timeout=min(heartbeat, remaining))
                break
            except subprocess.TimeoutExpired:
                print(f'PROGRESS {label} elapsed={time.monotonic() - started:.1f}s pid={process.pid}', flush=True)
    finally:
        if process.poll() is None:
            stop_tree(process, cleanup_grace)
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
    print(f'END {label} exit={status} elapsed={time.monotonic() - started:.1f}s', flush=True)
    return status
