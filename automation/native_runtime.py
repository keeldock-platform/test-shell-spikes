"""Shared native transport and bounded ownership of a launched desktop process."""
import io
from pathlib import Path
import re
import time
import subprocess
import tarfile


def stop_desktop(process, evidence=None):
    if process is None:
        return
    if process.poll() is None:
        if evidence is not None:
            (evidence / 'recorder/shutdown-flushed').unlink(missing_ok=True)
            (evidence / 'recorder/shutdown-request').touch()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                if (evidence / 'recorder/shutdown-flushed').is_file():
                    break
                time.sleep(0.05)
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def run_android(spike, method, case_id, evidence, env):
    required = ('SHELL_UIAUTOMATOR_APK', 'SHELL_UIAUTOMATOR_RUNNER',
                'SHELL_UIAUTOMATOR_TEST_PACKAGE', 'SHELL_MOBILE_BUNDLE_ID')
    if any(not env.get(key) for key in required):
        raise RuntimeError('Coordinator must supply installed instrumentation APK, runner, test package and target package.')
    if not Path(env[required[0]]).is_file():
        raise RuntimeError('Instrumentation APK is missing.')
    package = env['SHELL_MOBILE_BUNDLE_ID']
    if not re.fullmatch(r'[A-Za-z0-9_.]+', package) or not re.fullmatch(r'[A-Za-z0-9_-]+', case_id):
        raise ValueError('Unsafe Android package or case id')
    relative = f'files/shell-evidence/{spike}/{case_id}/recorder'
    # run-as both verifies debuggability and removes stale observations for this case.
    subprocess.run(['adb', 'shell', 'run-as', package, 'rm', '-rf', relative], check=True, timeout=30)
    try:
        result = subprocess.run([
            'adb', 'shell', 'am', 'instrument', '-w', '-r',
            '-e', 'class', f'org.example.shellspikes.{method}',
            '-e', 'caseId', case_id, '-e', 'bundleId', package,
            f"{env['SHELL_UIAUTOMATOR_TEST_PACKAGE']}/{env['SHELL_UIAUTOMATOR_RUNNER']}",
        ], env=env, capture_output=True, text=True, timeout=600, check=True)
        (evidence / 'recorder/instrumentation.log').write_text(result.stdout + result.stderr)
        if 'FAILURES!!!' in result.stdout or 'INSTRUMENTATION_FAILED' in result.stdout:
            raise RuntimeError('Instrumentation reported test failure; see instrumentation.log')
        return result
    finally:
        archive = subprocess.run(['adb', 'exec-out', 'run-as', package, 'tar', '-C', relative, '-cf', '-', '.'],
                                 capture_output=True, check=True, timeout=60)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            # Copy regular files only; never trust archive paths or links from a device.
            for member in bundle.getmembers():
                path = Path(member.name)
                if not member.isfile() or path.is_absolute() or '..' in path.parts:
                    continue
                target = (evidence / 'recorder' / path).resolve()
                target.relative_to((evidence / 'recorder').resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.extractfile(member).read())
