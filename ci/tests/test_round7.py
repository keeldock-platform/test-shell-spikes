"""Decision C supersedes round-seven restricted-archive installation tests.

All APK bytes and device versions below are fixtures, never measured runtimes.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ci' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

discovery = load('discovery8', 'runtime-discovery.py')
platform = load('platform8', 'run-platform.py')


class AndroidBundledTests(unittest.TestCase):
    payload = b'fixture bundled WebView APK; not a real APK'
    version = '123.0.0.1'

    def checked(self, command):
        if command == ['adb', 'shell', 'dumpsys', 'webviewupdate']:
            return f'Current WebView package (name, version): (com.android.webview, {self.version})'
        if command == ['adb', 'shell', 'pm', 'path', 'com.android.webview']:
            return 'package:/system/app/WebView/WebView.apk'
        if command[:2] == ['adb', 'pull']:
            Path(command[-1]).write_bytes(self.payload)
            return ''  # adb may emit progress on stderr, not stdout
        raise AssertionError(f'Unexpected command: {command}')

    def test_each_cell_records_bundled_version_and_payload_without_update(self):
        for api in (30, 31, 35):
            with self.subTest(api=api), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                (output / 'recorder').mkdir()
                env = {'ANDROID_API_LEVEL': str(api), 'SHELL_CELL': f'android-api-{api}'}
                with patch.dict(os.environ, env), patch.object(discovery, 'checked', side_effect=self.checked):
                    installed = discovery.discover_android(output)
                    environment = {'platform': 'android', 'cell': env['SHELL_CELL'], 'sourceSha': 'fixture', 'versions': {}}
                    record = discovery.record_runtime(output, environment)
                for value in (installed, record):
                    self.assertEqual(value['latestStableStatus'], 'UNVERIFIED')
                    self.assertEqual(value['resolvedVersion'], self.version)
                    self.assertEqual(value['artifacts'][0]['sha256'], hashlib.sha256(self.payload).hexdigest())
                    self.assertEqual(value['status'], 'recorded')
                self.assertEqual(record['verdict'], 'UNVERIFIED')
                self.assertEqual(environment['versions']['webview'], self.version)

    def test_missing_provider_or_failed_pull_never_claims_latest(self):
        for fail_at in ('webviewupdate', 'pull'):
            def checked(command):
                if fail_at in command:
                    raise subprocess.CalledProcessError(1, command)
                return self.checked(command)
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                (output / 'recorder').mkdir()
                with patch.object(discovery, 'checked', side_effect=checked):
                    self.assertEqual(discovery.discover_android(output)['status'], 'UNVERIFIED')
                    environment = {'platform': 'android', 'cell': 'android-api-30', 'sourceSha': 'fixture', 'versions': {}}
                    self.assertEqual(discovery.record_runtime(output, environment)['latestStableStatus'], 'UNVERIFIED')

    def test_android_active_returns_zero_even_when_observation_fails(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SHELL_EVIDENCE_DIR': tmp}), patch.object(sys, 'argv', ['runtime-discovery.py', 'android', '--android-active']), patch.object(discovery, 'checked', side_effect=OSError('no adb')):
            self.assertEqual(discovery.main(), 0)
            record = json.loads((Path(tmp) / 'runtime-discovery/install.json').read_text())
            self.assertEqual(record['latestStableStatus'], 'UNVERIFIED')
            self.assertIn('error', record)

    def test_platform_builds_and_runs_cases_despite_observation_failure(self):
        for api in (30, 31, 35):
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                return 78 if '--android-active' in command else 0
            with self.subTest(api=api), patch.dict(os.environ, {'ANDROID_API_LEVEL': str(api), 'SHELL_UIAUTOMATOR_APK': 'fixture.apk'}), patch.object(sys, 'argv', ['run-platform.py', 'android', '--spikes', 's10', 's11']), patch.object(platform, 'execute', side_effect=execute), patch.object(platform, 'start_android_emulator', return_value=0) as boot, patch.object(platform, 'stop_android_emulator', return_value=0), patch.object(platform, 'install_android_wrapper', return_value=0), patch.object(platform, 'build_android_uiautomator'), patch.object(platform, 'run_command', return_value='org.example.shellspikes.mobile.test/androidx.test.runner.AndroidJUnitRunner'), patch.object(platform, 'run_case', side_effect=lambda target, spike, case: execute([sys.executable, 'ci/run_case.py', target, spike, case])):
                self.assertEqual(platform.main(), 0)
                boot.assert_called_once_with(str(api))
            active = next(i for i,c in enumerate(calls) if '--android-active' in c)
            build = next(i for i,c in enumerate(calls) if c[:4] == ['cargo','tauri','android','build'])
            cases = [i for i,c in enumerate(calls) if 'ci/run_case.py' in c]
            self.assertTrue(cases)
            self.assertLess(active, build)
            self.assertTrue(all(build < i for i in cases))

    def test_preflight_reads_value_after_dumpsys_heading(self):
        import native_preflight
        with patch.object(native_preflight, 'command', return_value=self.checked(['adb','shell','dumpsys','webviewupdate'])):
            self.assertEqual(native_preflight.webview_version('android')[0], self.version)


if __name__ == '__main__':
    unittest.main()
