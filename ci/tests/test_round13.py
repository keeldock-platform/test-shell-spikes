"""Run-seven execution and ingestion regressions; no synthetic GUI claims."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
sys.path.insert(0, str(ROOT / 'automation'))


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


verify = module('execution13', 'ci/verify-execution.py')
collector = module('collector13', 'ci/collect.py')
finalizer = module('finalizer13', 'ci/finalize-s11.py')
import native_runtime


class RunSevenTests(unittest.TestCase):
    def test_execution_guard_rejects_emitter_only_and_all_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cell = root / 'cells/linux-ubuntu-24.04-x11'
            cell.mkdir(parents=True)
            (cell / 'assertions.json').write_text(json.dumps({'results': [{'verdict': 'UNVERIFIED'}]}))
            self.assertEqual(len(verify.execution_summary(root)['errors']), 2)
            (root / 'events.jsonl').write_text(json.dumps({'event': 'scenario-finished', 'automationExit': 0}) + '\n')
            self.assertEqual(len(verify.execution_summary(root)['errors']), 1)
            (cell / 'assertions.json').write_text(json.dumps({'results': [{'verdict': 'UNVERIFIED', 'laneVerdict': 'PASS'}]}))
            self.assertEqual(verify.execution_summary(root)['errors'], [])

    def test_native_startup_distinguishes_dead_process_and_ready_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'recorder').mkdir()
            process = Mock(pid=42)
            process.poll.return_value = 1
            self.assertFalse(native_runtime.wait_desktop_ready(process, root, 'case'))
            self.assertEqual(json.loads((root / 'recorder/desktop-readiness.json').read_text())['status'], 'process-exited')
            process.poll.return_value = None
            (root / 'recorder/renderer-events.jsonl').write_text(json.dumps({'caseId': 'case', 'detail': {'phase': 'scenario-ready'}}) + '\n')
            self.assertTrue(native_runtime.wait_desktop_ready(process, root, 'case'))

    def test_native_hooks_wait_for_configured_windows(self):
        for lane in ('s02_system_menu', 's03_gnome_menu'):
            source = (ROOT / f'apps/desktop/src-tauri/src/spikes/{lane}.rs').read_text()
            setup = source.split('.setup(|app, _api| {', 1)[1].split('.on_event(', 1)[0]
            self.assertNotIn('get_webview_window', setup)
            self.assertNotIn('install_native_event_hook', setup)
            self.assertIn('RunEvent::Ready', source)

    def test_legacy_ydotool_translates_native_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'ydotool'
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS"\n')
            binary.chmod(0o755)
            env = {**os.environ, 'SHELL_YDOTOOL_REAL': str(binary), 'SHELL_YDOTOOL_LEGACY': '1', 'ARGS': str(root / 'args')}
            for args, expected in [(['key', '1:1', '1:0'], ['key', 'ESC']),
                                   (['key', '28:1', '28:0'], ['key', 'ENTER']),
                                   (['click', '0xC1'], ['click', '2']),
                                   (['mousemove', '--absolute', '--x', '100', '--y', '200'], ['mousemove', '100', '200'])]:
                subprocess.run(['bash', str(ROOT / 'ci/linux/ydotool-compat.sh'), *args], env=env, check=True)
                self.assertEqual((root / 'args').read_text().splitlines(), expected)

    def test_xcresult_sanitized_attachment_names_map_only_known_paths(self):
        case = module('case13', 'ci/run_case.py')
        uuid = '09E66C2C-6024-4796-B520-C88150849B36'
        self.assertEqual(case.ios_attachment_relative_name('recorderobservations_0_' + uuid + '.json'), Path('recorder/observations.json'))
        self.assertEqual(case.ios_attachment_relative_name('screensios-policy_0_' + uuid + '.png'), Path('screens/ios-policy.png'))
        self.assertEqual(case.ios_attachment_relative_name('events_0_' + uuid + '.txt'), Path('events.jsonl'))
        for name in ('../escape', '/tmp/escape', 'unknown_0_' + uuid + '.json'):
            self.assertIsNone(case.ios_attachment_relative_name(name))

    def test_xctest_environment_resolves_case_values_without_build_macros(self):
        configure = module('xctest13', 'ci/configure-xctest-environment.py')
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'fixture.xcodeproj'
            directory = project / 'xcshareddata/xcschemes'
            directory.mkdir(parents=True)
            path = directory / 'fixture.xcscheme'
            path.write_text('<Scheme><TestAction><EnvironmentVariables>'
                            '<EnvironmentVariable key="S01_PERMISSION_PROMPT_PREFLIGHT" value="$(S01_PERMISSION_PROMPT_PREFLIGHT)"/>'
                            '<EnvironmentVariable key="SHELL_CASE_ID" value="$(SHELL_CASE_ID)"/>'
                            '</EnvironmentVariables></TestAction></Scheme>')
            for case_id in ('first & case', 'second case'):
                configure.configure(project, 'fixture', {'S01_PERMISSION_PROMPT_PREFLIGHT': 'passed', 'SHELL_CASE_ID': case_id})
                values = {row.get('key'): row.get('value') for row in ET.parse(path).getroot().findall('.//EnvironmentVariable')}
                self.assertEqual(values['S01_PERMISSION_PROMPT_PREFLIGHT'], 'passed')
                self.assertEqual(values['SHELL_CASE_ID'], case_id)

    def test_windows_probe_keeps_json_separate_from_stderr(self):
        native = module('native13', 'ci/native_preflight.py')
        payload = {'width': 1920, 'height': 1080, 'scale': 1, 'refreshHz': 60, 'webview': '123.0.0.1'}
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), 'diagnostic warning')
        with patch.object(native.subprocess, 'run', return_value=completed):
            display, evidence = native.display_windows()
        self.assertEqual(display['resolution'], '1920x1080')
        self.assertEqual(evidence['windowsNative']['webview'], '123.0.0.1')
        self.assertEqual(evidence['windowsProbe']['stderr'], 'diagnostic warning')

    def test_bom_observation_survives_s11_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'recorder').mkdir()
            path = root / 'recorder/observations.json'
            path.write_text(json.dumps({'assertions': {'fixture-FRAME': {}}}), encoding='utf-8-sig')
            finalizer.finalize(root)
            self.assertEqual(json.loads(path.read_text())['assertions']['fixture-FRAME']['verdict'], 'UNVERIFIED')

    def test_hash_audit_rejects_unsealed_extra_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'one').write_bytes(b'one')
            import hashlib
            (root / 'hashes.sha256').write_text(hashlib.sha256(b'one').hexdigest() + '  one\n')
            self.assertEqual(collector.audit_hashes(root)['errors'], [])
            (root / 'two').write_bytes(b'two')
            self.assertIn('file missing from hash manifest', collector.audit_hashes(root)['errors'][0])


if __name__ == '__main__':
    unittest.main()
