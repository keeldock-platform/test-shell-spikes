"""Replay provisioning shell logic without installing packages or using sudo.

Only OS identity and executable-location reads are adapted for the host. The
installer itself runs unmodified; fake tools model apt's epoch naming, payload
integrity, permissions, dpkg readback and the encoder/decoder smoke sequence.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIN = '1a23baace5f2688a47e28119aedae6993cd638e6279a7227dfc52d9a337a1c17'
ARCHIVE = 'ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb'

# This is a simulated payload, never an executable or a substitute package pin.
TOOL = r'''
import hashlib, json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['REPLAY_ROOT'])
def record(**values):
    with (root / 'calls').open('a') as stream:
        stream.write(json.dumps(dict(tool=name, args=args, **values)) + '\n')
def require(ok):
    if not ok:
        sys.exit(91)
record()
if name == 'sudo':
    os.execvp(args[0], args)
elif name == 'timeout':
    require(args[0] == '--kill-after=10' and args[1] == '180')
    os.execvp(args[2], args[2:])
elif name == 'chown':
    require(args[0] == '_apt:root')
    (pathlib.Path(args[1]) / '.apt-owner').touch()
elif name == 'dpkg':
    if args == ['--print-architecture']:
        print('amd64')
    else:
        require(args == ['--verify', 'ffmpeg'])
elif name == 'dpkg-query':
    require(args == ['-W', "-f=${Version}", 'ffmpeg'])
    print('7:6.1.1-3ubuntu5')
elif name == 'apt-cache':
    # The current installer uses authenticated apt-get metadata directly.
    sys.exit('unexpected apt-cache call: add an explicit replay contract')
elif name == 'apt-get':
    require('Dir::Etc::sourceparts=-' in args)
    require('Acquire::Retries=3' in args)
    sources = next(a.split('=', 1)[1] for a in args if a.startswith('Dir::Etc::sourcelist='))
    require('signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg' in pathlib.Path(sources).read_text())
    if 'update' in args:
        require('--error-on=any' in args)
    elif 'download' in args:
        require(args[-1] == 'ffmpeg=7:6.1.1-3ubuntu5')
        mode = os.environ.get('REPLAY_MODE', '')
        cwd = pathlib.Path.cwd()
        sandboxed = (cwd / '.apt-owner').exists() and cwd.stat().st_mode & 0o777 == 0o755
        # The enclosing metadata dir must also be traversable by _apt.
        sandboxed = sandboxed and cwd.parent.stat().st_mode & 0o005 == 0o005
        record(sandboxed=sandboxed)
        names = {
            'missing': [], 'wrong': ['not-ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb'],
            'wrong-arch': ['ffmpeg_7%3a6.1.1-3ubuntu5_arm64.deb'],
            'multiple': ['ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb', 'ffmpeg_other_amd64.deb'],
            'wrong-version': ['ffmpeg_other_amd64.deb'],
        }.get(mode, ['ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb'])
        for filename in names:
            (cwd / filename).write_bytes(b'corrupt' if mode == 'hash' else b'run13 simulated archive')
        transcript = pathlib.Path(os.environ['REPLAY_TRANSCRIPT']).read_text()
        for line in transcript.splitlines():
            if line.startswith('W:'):
                if not sandboxed or os.environ.get('REPLAY_WARNING') == '1': print(line, file=sys.stderr)
            else: print(line)
    elif 'install' in args:
        require(all(a in args for a in ['--yes', '--no-install-recommends', '--reinstall', '--allow-downgrades']))
        archive = pathlib.Path(args[-1])
        require(archive.is_file() and archive.name == 'ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb')
        require((root / 'hashed').read_text() == str(archive))
    else: sys.exit(92)
elif name == 'sha256sum':
    require(args == ['--check', '--strict'])
    digest, filename = sys.stdin.read().strip().split('  ', 1)
    archive = pathlib.Path(filename).absolute()
    payload = archive.read_bytes()
    record(file=str(archive), payload_sha256=hashlib.sha256(payload).hexdigest(), pin=digest)
    # Model the pinned archive's digest using deterministic inert fixture bytes.
    require(digest == '1a23baace5f2688a47e28119aedae6993cd638e6279a7227dfc52d9a337a1c17')
    require(payload == b'run13 simulated archive' and archive.name == 'ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb')
    (root / 'hashed').write_text(str(archive))
elif name in ('ffmpeg', 'ffprobe'):
    require((root / 'hashed').is_file())
    if args == ['-version']: pass
    elif name == 'ffprobe': require(pathlib.Path(args[-1]).is_file())
    else:
        if os.environ.get('REPLAY_MODE') == 'smoke': sys.exit(93)
        if '-i' in args and 'lavfi' not in args: require(pathlib.Path(args[args.index('-i')+1]).is_file())
        pathlib.Path(args[-1]).touch()
elif name == 'npm':
    require(args == ['ci', '--ignore-scripts'])
    if os.environ.get('REPLAY_MODE') == 'npm': sys.exit(94)
elif name == 'rustup':
    require(args == ['toolchain', 'install', '1.99.1', '--profile', 'minimal', '--component', 'rustfmt', '--component', 'clippy'])
    if os.environ.get('REPLAY_MODE') == 'rustup': sys.exit(95)
elif name == 'cargo':
    require(args in [['+1.99.1', 'fmt', '--all', '--', '--check'], ['+1.99.1', 'metadata', '--locked', '--format-version', '1']])
    if 'metadata' in args: print('{}')
else: sys.exit('unmodelled tool ' + name)
'''


def steps(job):
    """Read actual run blocks, preserving their commands and ordering."""
    workflow = (ROOT / '.github/workflows/shell-spikes.yml').read_text()
    block = workflow.split(f'\n  {job}:\n', 1)[1]
    block = re.split(r'\n  [a-z][a-z-]*:\n', block, maxsplit=1)[0]
    result = []
    for step in re.split(r'\n      - ', block)[1:]:
        match = re.search(r'^        run: (.+)$', step, re.M)
        if match:
            command = match.group(1)
            if command == '|':
                command = textwrap.dedent(step[match.end()+1:].split('\n      - ', 1)[0])
            result.append((step.splitlines()[0], command.strip()))
    return result


class ProvisioningReplay(unittest.TestCase):
    def replay(self, commands=None, mode='', warning=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = root / 'bin'
            binaries.mkdir()
            for name in ['sudo', 'timeout', 'chown', 'apt-get', 'apt-cache', 'dpkg', 'dpkg-query',
                         'sha256sum', 'ffmpeg', 'ffprobe', 'npm', 'rustup', 'cargo']:
                path = binaries / name
                path.write_text('#!' + sys.executable + '\n' + TOOL)
                path.chmod(0o755)
            env_file = root / 'bash-env'
            env_file.write_text('''
source() {
  if [[ "$1" == /etc/os-release ]]; then
    ID=ubuntu; VERSION_CODENAME=noble
  else builtin source "$@"; fi
}
command() {
  if [[ "$1" == -v && ( "$2" == ffmpeg || "$2" == ffprobe ) ]]; then
    printf '/usr/bin/%s\\n' "$2"
  else builtin command "$@"; fi
}
''')
            (root / 'evidence').mkdir()
            env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                   'BASH_ENV': str(env_file), 'REPLAY_ROOT': str(root), 'REPLAY_MODE': mode,
                   'REPLAY_WARNING': str(int(warning)),
                   'REPLAY_TRANSCRIPT': str(ROOT / 'ci/tests/fixtures/run13-apt-download.txt')}
            script = commands or 'bash ' + shlex.quote(str(ROOT / 'ci/install-media-validator.sh'))
            # Run from a disposable cwd; all host-mutating tools above are fakes.
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=root,
                                    env=env, text=True, capture_output=True, timeout=30)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
            return result, calls

    def test_epoch_archive_with_exact_run13_output_including_warning(self):
        result, calls = self.replay(warning=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        transcript = (ROOT / 'ci/tests/fixtures/run13-apt-download.txt').read_text()
        for line in transcript.splitlines():
            self.assertIn(line, result.stderr if line.startswith('W:') else result.stdout)
        hashed = next(c for c in calls if c['tool'] == 'sha256sum' and 'file' in c)
        self.assertEqual(Path(hashed['file']).name, ARCHIVE)
        self.assertEqual(hashed['pin'], PIN)
        install = next(c for c in calls if c['tool'] == 'apt-get' and 'install' in c['args'])
        self.assertEqual(install['args'][-1], hashed['file'])
        self.assertEqual(len([c for c in calls if c['tool'] in ('ffmpeg', 'ffprobe')]), 5)

    def test_download_is_writable_and_traversable_for_apt(self):
        result, calls = self.replay()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(next(c['sandboxed'] for c in calls if 'sandboxed' in c))
        self.assertNotIn('unsandboxed', result.stderr)

    def test_refuses_missing_wrong_multiple_and_corrupt_archives(self):
        for mode in ['missing', 'wrong', 'wrong-arch', 'wrong-version', 'multiple', 'hash']:
            with self.subTest(mode=mode):
                result, calls = self.replay(mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c['tool'] == 'apt-get' and 'install' in c['args'] for c in calls))
                if mode in ['missing', 'wrong', 'wrong-arch', 'multiple']:
                    self.assertFalse(any(c['tool'] == 'sha256sum' for c in calls))
                    self.assertIn('Expected exactly one downloaded', result.stderr)
                if mode == 'hash':
                    self.assertEqual(result.returncode, 91)
                    self.assertTrue(any(c['tool'] == 'sha256sum' and 'file' in c for c in calls))

    def test_smoke_failure_is_fatal(self):
        result, _ = self.replay(mode='smoke')
        self.assertNotEqual(result.returncode, 0)

    def test_replay_precedes_real_provisioning(self):
        for job in ['public-static', 'collect']:
            commands = [command for _, command in steps(job)]
            replay = commands.index('python ci/tests/test_round18.py')
            for index, command in enumerate(commands):
                if 'npm ci' in command or 'rustup toolchain install' in command or 'bash ci/install-media-validator.sh' in command:
                    self.assertLess(replay, index, job)

    def test_every_pre_gate_installer_step_replays(self):
        expected = {
            'public-static': ['npm ci --ignore-scripts',
                              'rustup toolchain install 1.99.1 --profile minimal --component rustfmt --component clippy',
                              'bash ci/install-media-validator.sh'],
            'collect': ['bash ci/install-media-validator.sh'],
        }
        for job, inventory in expected.items():
            with self.subTest(job=job):
                commands = []
                for name, command in steps(job):
                    if 'Check case deadlines' in name or 'Produce result matrix' in name: break
                    if re.search(r'\b(?:install|npm ci)\b', command) and 'test_round18.py' not in command:
                        commands.append(command)
                self.assertEqual([c.splitlines()[0] for c in commands], inventory)
                for command in commands:
                    command = command.replace('bash ci/install-media-validator.sh',
                                              'bash ' + shlex.quote(str(ROOT / 'ci/install-media-validator.sh')))
                    result, calls = self.replay(commands=command)
                    self.assertEqual(result.returncode, 0, (job, command, result.stderr))
                    if command.startswith('npm') or command.startswith('rustup'):
                        mode = command.split()[0]
                        failed, _ = self.replay(commands=command, mode=mode)
                        self.assertNotEqual(failed.returncode, 0)
                        self.assertTrue(any(c['tool'] == mode for c in calls))


if __name__ == '__main__':
    unittest.main()
