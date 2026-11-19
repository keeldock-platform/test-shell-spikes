"""Run-ten provisioning, toolchain and evidence transport regressions."""
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


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


pin = module('pin16', 'ci/pin-android-gradle.py')
probe = module('probe16', 'ci/probe-android-dependencies.py')
case = module('case16', 'ci/run_case.py')
collector = module('collector16', 'ci/collect.py')


class RunTenProbes(unittest.TestCase):
    def test_fedora_retries_without_assuming_repo_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = {
                'sudo': '#!/bin/sh\nexec "$@"\n',
                'timeout': '#!/bin/sh\nshift\nshift\nexec "$@"\n',
                'dnf': '''#!/bin/sh
echo "$*" >> "$PROBE_LOG"
case "$*" in
  *"repo info"*) exit 1 ;;
  *"clean metadata"*) exit 0 ;;
  *"--setopt=fedora.baseurl="*) exit 0 ;;
  *) exit 100 ;;
esac
''',
            }
            for name, source in scripts.items():
                path = root / name
                path.write_text(source)
                path.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'ci/dnf-retry.sh'), 'install', '-y', 'gnome-shell'],
                                    env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                                         'PROBE_LOG': str(root / 'calls')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = (root / 'calls').read_text()
            self.assertEqual(calls.count('install -y gnome-shell'), 3)
            self.assertIn('--setopt=fedora.baseurl=https://mirrors.kernel.org/', calls)

    def test_vendor_ubuntu_path_is_never_rewritten_as_an_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources.list.d').mkdir()
            vendor = root / 'sources.list.d/microsoft-prod.list'
            original = 'deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main\n'
            vendor.write_text(original)
            archive = root / 'sources.list'
            archive.write_text('deb http://us-east-2.ec2.archive.ubuntu.com/ubuntu noble main\n')
            for index in range(3):
                result = subprocess.run(['bash', str(ROOT / 'ci/apt-mirror.sh'), str(index), tmp],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(vendor.read_text(), original)
                self.assertNotIn('/24.04/prod', archive.read_text())
                self.assertNotIn('ec2.archive', archive.read_text())

    def test_buildsrc_agp_cannot_override_root_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'buildSrc').mkdir()
            (root / 'gradle/wrapper').mkdir(parents=True)
            (root / 'build.gradle.kts').write_text('classpath("com.android.tools.build:gradle:9.3.1")\nclasspath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.2.10")')
            src = root / 'buildSrc/build.gradle.kts'
            src.write_text('dependencies { implementation("com.android.tools.build:gradle:9.3.1") }')
            (root / 'gradle/wrapper/gradle-wrapper.properties').write_text('distributionUrl=old\n')
            pin.pin(root, '2.2.21')
            self.assertIn('com.android.tools.build:gradle:8.11.1', src.read_text())
            self.assertNotIn('9.3.1', src.read_text())

    def test_failed_coordinate_names_url_and_never_counts_as_resolved(self):
        url = 'https://example.invalid/exact.pom'
        with patch.object(probe.urllib.request, 'urlopen', side_effect=OSError('HTTP 404')), \
                patch.object(probe.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()) as log:
            with self.assertRaisesRegex(ValueError, 'exact.pom'):
                probe.fetch(url, 100)
        self.assertEqual(log.getvalue().count('failure url='), 3)
        self.assertIn(url, log.getvalue())

    def test_failed_case_survives_hashing_and_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / 'download/mac'
            cell_dir = artifact / 'cells/mac-desktop'
            cell_dir.mkdir(parents=True)
            environment = {'cell': 'mac-desktop', 'sourceSha': 'a' * 40}
            # This assertion needs native event/environment evidence, not fabricated media.
            refs = ['cells/mac-desktop/environment.json', 'events.jsonl']
            row = {'spike': 's01', 'caseId': 'S01-CAPTURE', 'id': 'S01-CREATION-POSITION',
                   'verdict': 'FAIL', 'laneVerdict': 'FAIL', 'actual': 'Measured native frames differed',
                   'evidence': refs}
            (artifact / 'events.jsonl').write_text('{"event":"scenario-finished","automationExit":1}\n')
            (cell_dir / 'environment.json').write_text(json.dumps(environment))
            (cell_dir / 'assertions.json').write_text(json.dumps({'sourceSha': 'a' * 40, 'results': [row]}))
            case.write_hashes(artifact)
            with patch.object(sys, 'argv', ['collect.py', '--input', str(root / 'download'),
                                           '--output', str(root / 'out'), '--expected-sha', 'a' * 40]):
                self.assertEqual(collector.main(), 1)
            summary = json.loads((root / 'out/result-matrix.json').read_text())
            observed = next(item for item in summary['results'] if item['id'] == row['id'])
            self.assertEqual(observed['verdict'], 'FAIL')
            self.assertEqual(summary['executionObservations']['byCell']['mac-desktop']['FAIL'], 1)
            # Tampered bytes still invalidate the assertion, including a native FAIL.
            (artifact / 'events.jsonl').write_text('tampered')
            self.assertTrue(collector.audit_hashes(artifact)['errors'])

    def test_s08_attaches_only_a_real_accessibility_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = root / 'spikes/s08/case'
            (scenario / 'recorder').mkdir(parents=True)
            spec = {'id': 'native', 'evidence': ['recorder/accessibility-tree.jsonl']}
            row = {'id': 'native', 'verdict': 'FAIL', 'evidence': []}
            before = case.attach_case_evidence([row], [spec], scenario, root)[0]
            self.assertEqual(before['evidence'], [])
            snapshot = scenario / 'recorder/accessibility-tree.jsonl'
            snapshot.write_text('{"observation":"S08-A01","nodes":[{"AXRole":"AXWindow"}]}\n')
            after = case.attach_case_evidence([row], [spec], scenario, root)[0]
            self.assertEqual(after['verdict'], 'FAIL')
            self.assertEqual(after['evidence'], ['spikes/s08/case/recorder/accessibility-tree.jsonl'])
            self.assertTrue(collector.required_source_satisfied(spec['evidence'][0], after['evidence']))
            source = (ROOT / 'automation/macos/s08/probe.swift').read_text()
            self.assertIn('captureAccessibilityTree(name)', source)
            self.assertIn('recorder/accessibility-tree.jsonl', source)

    def test_native_targets_and_upload_failure_paths_remain_explicit(self):
        workflow = (ROOT / '.github/workflows/shell-spikes.yml').read_text()
        for block in workflow.split('uses: actions/upload-artifact@')[:-1]:
            self.assertIn('if: always()', block.split('- name:')[-1])
        self.assertIn('ci/install-media-validator.sh', workflow)
        media = (ROOT / 'ci/install-media-validator.sh').read_text()
        self.assertIn('Dir::Etc::sourceparts=-', media)
        self.assertIn('signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg', media)
        self.assertNotIn('ci/apt-host.sh', media)
        dnf = (ROOT / 'ci/dnf-retry.sh').read_text()
        self.assertNotIn('/etc/yum.repos.d/fedora.repo', dnf)
        for driver in ('s02/run.ps1', 's10/drive.ps1'):
            source = (ROOT / 'automation/windows' / driver).read_text()
            self.assertLess(source.index('Add-Type -AssemblyName WindowsBase'), source.index('[System.Windows.Rect]'))
        for driver in ('s10/ColourUITests.swift', 's11/AccentUITests.swift'):
            source = (ROOT / 'automation/ios' / driver).read_text()
            self.assertIn('caseField.value as? String == caseId', source)
            self.assertIn('XCTWaiter.wait(for: [retainedValue], timeout: 5)', source)
            self.assertIn('scenario-entered-value', source)
            self.assertIn('Ready: \\(spike): \\(caseId)', source)
        display = (ROOT / 'ci/macos-display.swift').read_text()
        self.assertIn('CGCompleteDisplayConfiguration(configuration, .forSession)', display)


if __name__ == '__main__':
    unittest.main()
