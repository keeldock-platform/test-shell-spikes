"""Deadline, generated dependency and immutable-upload regression probes."""
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


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


seal = module('seal14', 'ci/hash-evidence.py')
collector = module('collect14', 'ci/collect.py')
pin = module('pin14', 'ci/pin-android-gradle.py')
discovery = module('discovery14', 'ci/runtime-discovery.py')
finalizer = module('finalize14', 'ci/finalize-s11.py')
case_runner = module('case14', 'ci/run_case.py')
from process_watch import watched


class RunEightProbes(unittest.TestCase):
    def test_upload_snapshot_survives_late_log_video_and_inode_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source / 'stdout.log').write_bytes(b'final log\r\n')
            (source / 'capture.mkv').write_bytes(b'video bytes')
            os.link(source / 'capture.mkv', source / 'alias.mp4')
            snapshot = seal.seal(source, root / 'sealed')
            with (source / 'stdout.log').open('ab') as stream:
                stream.write(b'late producer output')
            (source / 'capture.mkv').write_bytes(b'late video trailer')
            self.assertEqual(collector.audit_hashes(snapshot)['errors'], [])
            self.assertEqual((snapshot / 'stdout.log').read_bytes(), b'final log\r\n')
            self.assertEqual((snapshot / 'alias.mp4').read_bytes(), b'video bytes')
            (snapshot / 'stdout.log').write_bytes(b'corrupt upload')
            self.assertTrue(collector.audit_hashes(snapshot)['errors'])

    def test_case_deadline_reports_timeout_and_reaps_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / 'child.py'
            child.write_text('import time\ntime.sleep(1)\nopen("late", "w").write("still running")\n')
            command = [sys.executable, '-c',
                       'import subprocess,sys,time; subprocess.Popen([sys.executable,"child.py"]); time.sleep(60)']
            status = watched(command, label='hung-native-case', timeout=0.2,
                             heartbeat=0.1, cwd=root)
            self.assertEqual(status, 124)
            # A second bounded process gives a surviving descendant time to expose itself.
            subprocess.run([sys.executable, '-c', 'import time; time.sleep(1.2)'], check=True, timeout=3)
            self.assertFalse((root / 'late').exists())

    def test_success_keeps_child_exit_code(self):
        self.assertEqual(watched([sys.executable, '-c', 'raise SystemExit(7)'],
                                 label='failed-native-case', timeout=3, cwd=ROOT), 7)

    def test_kotlin_pin_rewrites_generated_version_and_probes_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / 'build.gradle.kts'
            build.write_text('classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.3.21")\nclasspath("com.android.tools.build:gradle:9.3.1")')
            build_src = root / 'buildSrc/build.gradle.kts'
            build_src.parent.mkdir()
            build_src.write_text('implementation("com.android.tools.build:gradle:9.3.1")')
            wrapper = root / 'gradle/wrapper/gradle-wrapper.properties'
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text('distributionUrl=https://services.gradle.org/distributions/gradle-9.6.1-bin.zip\n')
            init = pin.pin(root, '2.2.21')
            self.assertIn('kotlin-gradle-plugin:2.2.21', build.read_text())
            self.assertIn('gradle-8.14.3-bin.zip', wrapper.read_text())
            self.assertIn('distributionSha256Sum=', wrapper.read_text())
            self.assertIn('com.android.tools.build:gradle:8.11.1', build.read_text())
            self.assertIn('rethrowFailure()', init.read_text())
            build.write_text('unknown generated layout')
            with self.assertRaises(ValueError):
                pin.pin(root, '2.2.21')

    def test_truncated_renderer_event_is_preserved_and_cannot_pass_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'recorder').mkdir()
            observation = root / 'recorder/observations.json'
            observation.write_text(json.dumps({'assertions': {'native-FRAME': {}}}))
            events = root / 'recorder/renderer-events.jsonl'
            original = '{"caseId":"fixture","detail":{},"spike":"s11",\n'
            events.write_text(original)
            finalizer.finalize(root)
            self.assertEqual(events.read_text(), original)
            self.assertEqual(json.loads(observation.read_text())['assertions']['native-FRAME']['verdict'], 'UNVERIFIED')
            diagnostic = json.loads((root / 'recorder/s11-json-integrity.json').read_text())
            self.assertFalse(diagnostic['valid'])
            self.assertEqual(diagnostic['errors'][0]['line'], 1)

    def test_windows_recorder_start_uses_detached_launcher_and_bounded_stop(self):
        start, pid = case_runner.recorder_commands('windows', 'start', Path('capture.mkv'))
        stop, _ = case_runner.recorder_commands('windows', 'stop', Path('capture.mkv'))
        self.assertTrue(start[1].endswith('windows-start.py'))
        self.assertTrue(any(arg.endswith('windows.ps1') for arg in stop))
        self.assertEqual(pid, Path('capture.pid'))

    def test_apple_discovery_performs_no_system_or_runtime_install(self):
        for target in ('macos', 'ios'):
            commands = discovery.plan(target, Path('/unused'))
            self.assertEqual(commands, [])
            with patch.object(discovery.subprocess, 'run') as run:
                self.assertEqual(discovery.execute_plan(commands, Path('/unused')), [])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
