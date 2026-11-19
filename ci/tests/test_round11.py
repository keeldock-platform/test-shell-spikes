"""Run-five provisioning regressions; mocked tools never start a GUI or emulator."""
import contextlib
import importlib.util
import io
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
spec = importlib.util.spec_from_file_location('platform11', ROOT / 'ci/run-platform.py')
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)
from discovery_authorization import discovery_authorization_errors


class ProvisioningTests(unittest.TestCase):
    def test_discovery_boundary_and_attempt(self):
        policy = json.loads((ROOT / 'ci/environment-lock.json').read_text())['runtimePolicy']
        env = dict(GITHUB_ACTIONS='true', GITHUB_REF='refs/heads/shell-spikes/integration-1118',
                   GITHUB_REF_TYPE='branch', GITHUB_RUN_NUMBER='7', GITHUB_RUN_ATTEMPT='1')
        self.assertEqual(discovery_authorization_errors(policy, env), [])
        for override in ({'GITHUB_RUN_NUMBER': str(max(json.loads((ROOT / 'ci/discovery-authorization.json').read_text())['runNumbers']) + 1)}, {'GITHUB_RUN_ATTEMPT': '2'}):
            self.assertTrue(discovery_authorization_errors(policy, {**env, **override}))

    def test_avd_created_noninteractively_before_boot_for_every_api(self):
        for api in ('30', '31', '35'):
            for created in (True, False):
                with self.subTest(api=api, created=created), tempfile.TemporaryDirectory() as tmp:
                    home = Path(tmp)
                    lock = platform.environment_lock()['android']
                    ndk = home / 'ndk' / lock['ndk']['version']
                    ndk.mkdir(parents=True)
                    (ndk / 'source.properties').write_text('Pkg.Revision = ' + lock['ndk']['version'])
                    image = lock['systemImages'][api]['package']
                    name = f'shell-spike-api-{api}'
                    calls = []
                    def run(command, **kwargs):
                        calls.append(command)
                        if 'create' in command:
                            self.assertEqual(kwargs['input'], 'no\n')
                            self.assertEqual(command[command.index('--name')+1], name)
                            self.assertEqual(command[command.index('--package')+1], image)
                            avd_home = Path(kwargs['env']['ANDROID_AVD_HOME'])
                            if created:
                                (avd_home / f'{name}.ini').write_text('fixture')
                        return subprocess.CompletedProcess(command, 0)
                    def output(command):
                        if '--list_installed' in command:
                            return image + ' | 1 | fixture'
                        if '-list-avds' in command:
                            return name if created else ''
                        if 'getprop' in command:
                            return '1'
                        return 'fixture version'
                    env = dict(ANDROID_HOME=tmp, RUNNER_TEMP=tmp, SHELL_EVIDENCE_DIR=tmp)
                    with patch.dict(os.environ, env), patch.object(platform.shutil, 'which', side_effect=lambda n:n), patch.object(platform, 'execute', return_value=0), patch.object(platform, 'run_command', side_effect=output), patch.object(platform.subprocess, 'run', side_effect=run), patch.object(platform.subprocess, 'Popen') as boot:
                        boot.return_value.pid = 123
                        self.assertEqual(platform.start_android_emulator(api), 0 if created else 78)
                        self.assertEqual(boot.call_count, int(created))
                        if created:
                            self.assertIn(name, boot.call_args.args[0])
                            self.assertEqual(boot.call_args.kwargs['env']['ANDROID_AVD_HOME'], str((home / 'shell-spike-avd').resolve()))

    def test_linux_fallback_only_for_unavailable_session(self):
        import shutil
        real_bash = shutil.which('bash')
        for status in (78, 1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                shim = base / 'bash'
                shim.write_text('#!/bin/bash\nif [[ "$2" == provision ]]; then exit 0; fi\nexit "$SESSION_STATUS"\n')
                shim.chmod(0o755)
                emitter = base / 'python3'
                emitter.write_text('#!/bin/bash\n[[ "$1" == ci/emit-unverified-linux.py ]] || exit 99\n[[ -n "$SHELL_LINUX_FALLBACK_REASON" ]] || exit 98\necho fallback\n')
                emitter.chmod(0o755)
                env = {**os.environ, 'PATH': str(base)+':'+os.environ['PATH'],
                       'LINUX_DISTRO': 'Ubuntu 24.04', 'SESSION_STATUS': str(status)}
                result = subprocess.run([real_bash, str(ROOT / 'ci/run-linux.sh')],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 78 if status == 78 else 1)
                self.assertEqual('fallback' in result.stdout, status == 78)

    def test_apt_rewrites_hosted_mirror_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'sources.list.d').mkdir()
            sources = base / 'sources.list.d/ubuntu.sources'
            sources.write_text('URIs: mirror+file:/etc/apt/apt-mirrors.txt\nURIs: mirror+file:/etc/apt/apt-security-mirrors.txt\nURIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu\n')
            result = subprocess.run(['bash', str(ROOT / 'ci/apt-mirror.sh'), '0', str(base)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = sources.read_text()
            self.assertNotIn('mirror+file:', updated)
            self.assertNotIn('ec2.archive', updated)
            self.assertIn('http://archive.ubuntu.com/ubuntu/', updated)
            self.assertEqual(updated.count('http://archive.ubuntu.com/ubuntu/'), 3)

    def test_apt_retries_are_bounded_and_preserve_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sudo = base / 'sudo'
            sudo.write_text('#!/bin/bash\nif [[ "$1" == bash ]]; then exit 0; fi\necho attempt >> "$ATTEMPT_LOG"\nexit 124\n')
            sudo.chmod(0o755)
            attempts = base / 'attempts'
            env = {**os.environ, 'PATH': str(base)+':'+os.environ['PATH'], 'ATTEMPT_LOG': str(attempts), 'SHELL_APT_ATTEMPTS': '2'}
            result = subprocess.run(['bash', str(ROOT / 'ci/apt-host.sh'), 'update'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 124)
            self.assertEqual(attempts.read_text().splitlines(), ['attempt', 'attempt'])


if __name__ == '__main__':
    unittest.main()
