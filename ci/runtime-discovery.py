#!/usr/bin/env python3
"""One-wave official stable-channel update and installed-runtime evidence.

No implicit discovery: the coordinator file scopes run numbers, branch and attempt 1.
The coordinator reviews runtime-discovery.json and freezes its candidate pins.
Android uses the WebView bundled in the official sdkmanager system image.
Active discovery is read-only and non-blocking; latest-stable is UNVERIFIED.
--dry-run describes commands without installs or lookups.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from discovery_authorization import discovery_authorization_errors

ROOT = Path(__file__).resolve().parents[1]


def authorized(policy, env):
    return (policy.get('mode') == 'first-ci-run-discovery'
            and not policy.get('exactRuntimeVersionsByCell')
            and not discovery_authorization_errors(policy, env, require_ci=True)
            and bool(env.get('GITHUB_RUN_ID')))


def plan(target, output):
    # Embedded WKWebView updates with its OS. Never substitute a browser binary.
    if target == 'macos':
        return [['sudo', 'softwareupdate', '--install', '--all']]
    if target == 'ios':
        return [['xcodebuild', '-downloadPlatform', 'iOS']]
    if target == 'android':
        api = os.environ['ANDROID_API_LEVEL']
        android = json.loads((ROOT / 'ci/environment-lock.json').read_text())['android']
        return [['sdkmanager', '--channel=0', '--install', android['platform']['package'],
                 android['buildTools']['package'], android['ndk']['package'],
                 'platform-tools', 'emulator', android['systemImages'][api]['package']]]
    if target == 'linux':
        return [['bash', 'ci/apt-host.sh', 'update'], ['bash', 'ci/apt-host.sh', 'install', '--only-upgrade', '-y', 'libwebkit2gtk-4.1-0']]
    if target == 'windows':
        installer = output / 'MicrosoftEdgeWebview2Setup.exe'
        script = ("$ErrorActionPreference='Stop'; Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile '"
                  + str(installer).replace("'", "''") + "'; $p=Start-Process '" + str(installer).replace("'", "''")
                  + "' -ArgumentList '/silent','/install' -Wait -PassThru; exit $p.ExitCode")
        return [['pwsh', '-NoProfile', '-Command', script]]
    raise ValueError(target)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def execute_plan(commands, output, run=subprocess.run):
    records = []
    for number, command in enumerate(commands):
        try:
            result = run(command, capture_output=True, text=True, timeout=1800, check=False)
            log = output / f'install-{number}.log'
            log.write_text(result.stdout + result.stderr)
            print('$ ' + ' '.join(command), flush=True)
            print(result.stdout + result.stderr, flush=True)
            records.append({'command': command, 'exitCode': result.returncode, 'log': log.name})
            if result.returncode:
                break
        except (OSError, subprocess.SubprocessError) as error:
            records.append({'command': command, 'error': str(error)})
            break
    return records


ANDROID_BUNDLED_REASON = 'Bundled in the official emulator system image; not latest stable (coordinator decision C, 2026-11-19).'


def checked(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=True)
    return result.stdout.strip()


def active_android():
    dump = checked(['adb', 'shell', 'dumpsys', 'webviewupdate'])
    match = re.search(r'Current WebView package(?: \(name, version\))?:\s*\(([^,\s]+),\s*([^)]+)\)', dump)
    if not match or 'WebView package dirty: true' in dump or 'Any WebView package installed: false' in dump:
        raise ValueError('Active Android WebView is missing or not ready')
    return match.group(1), match.group(2).strip(), dump


def pull_android_payloads(output, package):
    remotes = checked(['adb', 'shell', 'pm', 'path', package]).splitlines()
    if not remotes or any(not line.startswith('package:') for line in remotes):
        raise ValueError('Active WebView APK paths missing')
    payloads = []
    for number, line in enumerate(remotes):
        local = output / f'active-webview-{number}.apk'
        checked(['adb', 'pull', line[8:], str(local)])
        payloads.append({'path': local.name, 'devicePath': line[8:], 'sha256': sha256(local), 'bytes': local.stat().st_size})
    return payloads


def discover_android(output):
    """Observe the bundled active provider; evidence failures must not stop cases."""
    record = {'platform': 'android', 'cell': os.environ.get('SHELL_CELL'),
              'api': os.environ.get('ANDROID_API_LEVEL'), 'runId': os.environ.get('GITHUB_RUN_ID'),
              'source': 'official-sdkmanager-system-image-bundled',
              'systemImage': os.environ.get('SHELL_ANDROID_SYSTEM_IMAGE'),
              'status': 'UNVERIFIED', 'latestStableStatus': 'UNVERIFIED',
              'latestStableReason': ANDROID_BUNDLED_REASON}
    try:
        package, version, dump = active_android()
        record.update(activePackage=package, resolvedVersion=version, activeDump=dump)
        record['artifacts'] = pull_android_payloads(output, package)
        record['status'] = 'recorded'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record['error'] = str(error)
    (output / 'install.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def record_runtime(scenario, environment):
    """Hash actual installed runtime payloads, not a version string or metadata digest."""
    target = environment['platform']
    paths = []
    android_observation = {}
    def command(args):
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        return result.stdout.strip() if result.returncode == 0 else ''
    if target == 'linux':
        paths = [Path(p) for p in command(['dpkg-query', '-L', 'libwebkit2gtk-4.1-0']).splitlines()
                 if '.so' in p and Path(p).is_file()]
    elif target == 'macos':
        binary = Path('/System/Library/Frameworks/WebKit.framework/Versions/A/WebKit')
        paths = [binary] if binary.is_file() else list(Path('/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld').glob('dyld_shared_cache_*'))
        if not paths:
            paths = list(Path('/System/Library/dyld').glob('dyld_shared_cache_*'))
    elif target == 'ios':
        runtimes = json.loads(command(['xcrun', 'simctl', 'list', 'runtimes', '--json']) or '{}').get('runtimes', [])
        selected = next((r for r in runtimes if r.get('identifier') == (environment.get('simulator') or {}).get('runtime')), {})
        if selected.get('bundlePath'):
            base = Path(selected['bundlePath']) / 'Contents/Resources/RuntimeRoot'
            paths = list(base.glob('System/Library/dyld/dyld_shared_cache_arm64*'))
            paths += list(base.glob('System/Library/Frameworks/WebKit.framework/WebKit'))
    elif target == 'windows':
        for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            base = Path(os.environ.get(variable, 'missing')) / 'Microsoft/EdgeWebView/Application'
            version = environment.get('versions', {}).get('webview')
            if version:
                paths += list((base / str(version)).glob('msedgewebview2.exe'))
                paths += list((base / str(version)).glob('msedge.dll'))
    elif target == 'android':
        try:
            package, version, dump = active_android()
            android_observation.update(activePackage=package, activeDump=dump)
            environment.setdefault('versions', {})['webview'] = version
            output = scenario / 'recorder'
            output.mkdir(parents=True, exist_ok=True)
            payloads = pull_android_payloads(output, package)
            paths = [output / payload['path'] for payload in payloads]
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            android_observation['error'] = str(error)
    artifacts = []
    for path in sorted(set(paths)):
        try:
            if path.is_file():
                artifacts.append({'path': str(path), 'sha256': sha256(path), 'bytes': path.stat().st_size})
        except OSError:
            continue
    versions = environment.get('versions', {})
    pins = {f'versions.{key}': value for key, value in versions.items()
            if value is not None and key in {'webview', 'xcode', 'androidSystemImage', 'androidEmulator', 'androidSdkPackages'}}
    pins.update({key: environment.get(key) for key in ('runnerImage', 'runnerImageVersion', 'os')})
    evidence_root = Path(os.environ.get('SHELL_RUN_EVIDENCE_DIR', os.environ.get('SHELL_EVIDENCE_DIR', 'evidence')))
    install_path = evidence_root / 'runtime-discovery/install.json'
    try:
        install = json.loads(install_path.read_text()) if install_path.is_file() else {'status': 'UNVERIFIED'}
    except (OSError, ValueError) as error:
        install = {'status': 'UNVERIFIED', 'error': str(error)}
    mode = json.loads((ROOT / 'ci/environment-lock.json').read_text())['runtimePolicy']['mode']
    record = {'mode': mode, 'cell': environment['cell'],
              'sourceSha': environment['sourceSha'], 'runId': os.environ.get('GITHUB_RUN_ID'),
              'runNumber': os.environ.get('GITHUB_RUN_NUMBER'), 'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'install': install, 'resolvedVersion': versions.get('webview'), 'artifacts': artifacts,
              'status': 'recorded' if artifacts and versions.get('webview') else 'UNVERIFIED',
              'candidatePins': pins, 'freezeOwner': 'coordinator',
              'latestStableStatus': 'UNVERIFIED',
              'latestStableReason': 'Official stable update requested for the profile; installer exit status alone does not establish that the active embedded webview is the independently newest release.',
              'verdict': 'UNVERIFIED', 'reason': 'Discovery observations require coordinator review and freeze before runtime-dependent PASS.'}
    record['runtimePayloadSha256'] = hashlib.sha256(json.dumps(sorted((a['sha256'], a['bytes']) for a in artifacts)).encode()).hexdigest() if artifacts else None
    record['candidatePins']['runtimeDiscovery.runtimePayloadSha256'] = record['runtimePayloadSha256']
    if target == 'android':
        record.update(android_observation)
        record['source'] = 'official-sdkmanager-system-image-bundled'
        record['latestStableReason'] = ANDROID_BUNDLED_REASON
    environment['runtimeDiscovery'] = record
    (scenario / 'recorder/runtime-discovery.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=['macos', 'ios', 'android', 'windows', 'linux'])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--android-active', action='store_true', help='Record bundled provider after emulator boot; never install a WebView')
    args = parser.parse_args()
    policy = json.loads((ROOT / 'ci/environment-lock.json').read_text())['runtimePolicy']
    output = Path(os.environ.get('SHELL_EVIDENCE_DIR', 'evidence')) / 'runtime-discovery'
    if args.android_active and args.platform != 'android':
        parser.error('--android-active requires android')
    if args.dry_run:
        if args.platform == 'android':
            print(json.dumps({'sdkBeforeBoot': plan('android', output),
                'activeAfterBoot': [['adb', 'shell', 'dumpsys', 'webviewupdate'],
                    ['adb', 'shell', 'pm', 'path', '<active-package>'],
                    ['adb', 'pull', '<active-apk-path>', '<evidence-apk>']],
                'emulatorPolicy': 'wipe data, disable snapshots; use bundled provider',
                'source': 'official-sdkmanager-system-image-bundled',
                'latestStableStatus': 'UNVERIFIED', 'latestStableReason': ANDROID_BUNDLED_REASON,
                'onDiscoveryFailure': 'record UNVERIFIED and continue build and cases'}, indent=2))
        else:
            print(json.dumps(plan(args.platform, output), indent=2))
        return 0
    if args.android_active:
        output.mkdir(parents=True, exist_ok=True)
        discover_android(output)
        return 0
    if policy.get('mode') == 'locked':
        return 0
    if not authorized(policy, os.environ):
        raise SystemExit('Discovery requires the coordinator-authorized run number, branch and first attempt; coordinator must freeze after the discovery wave.')
    if args.platform == 'android':
        # run-platform provisions the official SDK packages once before boot.
        return 0
    commands = plan(args.platform, output)
    output.mkdir(parents=True, exist_ok=True)
    records = execute_plan(commands, output)
    (output / 'install.json').write_text(json.dumps({'platform': args.platform, 'channel': 'official-stable',
        'scope': 'latest offered by the official channel for the declared OS/API profile',
        'status': 'installed' if len(records) == len(commands) and all(r.get('exitCode') == 0 for r in records) else 'UNVERIFIED',
        'commands': records}, indent=2) + '\n')
    # Failure never falls back to a silent preinstalled runtime.
    return 0 if all(r.get('exitCode') == 0 for r in records) else 78

if __name__ == '__main__':
    sys.exit(main())
