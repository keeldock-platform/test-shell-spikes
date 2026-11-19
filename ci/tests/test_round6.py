"""Round-six local fixture proofs: no installers, devices, CI, or Git writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_round5 import module, ROOT, case

accent = module('accent6', 'automation/accent/runner.py')
discovery = module('discovery6', 'ci/runtime-discovery.py')
collector = module('collector6', 'ci/collect.py')
finalizer = module('finalizer6', 'ci/finalize-s11.py')


class RoundSix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'recorder').mkdir()
        self.case_id = 'S11-ANDROID-API-31'

    def tearDown(self):
        self.temp.cleanup()

    def observation(self):
        return {'assertions': {self.case_id + '-' + suffix: {'verdict': 'UNVERIFIED'}
                              for suffix in ['WALLPAPER', 'RECREATE', 'FRAME', 'IDENTITY']}}

    def reduce(self, events, observation=None, case_id=None):
        path = self.root / 'recorder/observations.json'
        path.write_text(json.dumps(observation or self.observation()))
        (self.root / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
        accent.analyze_android_events(self.root, case_id or self.case_id)
        return json.loads(path.read_text())['assertions']

    def events(self):
        def row(name, seq, generation, wallpaper, color, **kwargs):
            return {'name': name, 'fields': dict(sequence=seq, activityGeneration=generation,
                    wallpaperId=wallpaper, resourceArgb=color, **kwargs)}
        return [row('s11.initial-reader-snapshot', 1, 0, 10, '#FF111111'),
                row('s11.native-event', 2, 0, 11, '#FF222222', cause='wallpaper-callback'),
                row('s11.host-and-token-update', 2, 0, 11, '#FF222222', appliedHex='#405066', identityHex='#6B5B45'),
                row('s11.reader-status', 3, 1, 11, '#FF222222', cause='activity-recreated-read', nativeEvent=False),
                row('s11.native-event', 4, 1, 12, '#FF333333', cause='configuration-changed'),
                row('s11.host-and-token-update', 4, 1, 12, '#FF333333', appliedHex='#405066', identityHex='#6B5B45')]

    def test_finding3_api30_observations_and_missing_facts(self):
        facts = dict(apiLevel=30, reason='api-below-31', systemHidden=True, storedAccent='system',
                     resolvedSource='brand', appliedHex='#405066', dynamicResourceRead=False,
                     promptSamples=10, promptObserved=False)
        obs = dict(ready=True, api30Facts=facts, assertions={})
        def check(value):
            return self.reduce([], value, 'S11-ANDROID-API-30-NEGATIVE')
        results = check(obs)
        self.assertEqual(results['S11-ANDROID-API-30-HIDDEN']['verdict'], 'PASS')
        self.assertEqual(results['S11-ANDROID-API-30-PROMPT']['verdict'], 'PASS')
        for key, wrong in [('reason', 'unsupported'), ('appliedHex', '#FFFFFF'), ('dynamicResourceRead', True),
                           ('storedAccent', 'brand'), ('systemHidden', False), ('resolvedSource', 'system')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(obs); changed['api30Facts'][key] = wrong
                self.assertEqual(check(changed)['S11-ANDROID-API-30-HIDDEN']['verdict'], 'UNVERIFIED')
        for key, wrong in [('promptObserved', True), ('promptSamples', 0)]:
            changed = copy.deepcopy(obs); changed['api30Facts'][key] = wrong
            self.assertEqual(check(changed)['S11-ANDROID-API-30-PROMPT']['verdict'], 'UNVERIFIED')
        self.assertTrue(all(row['verdict'] == 'UNVERIFIED' for row in check({'ready': True}).values()))
        driver = (ROOT / 'automation/android/s11/AccentUiAutomator.java').read_text()
        for text in ['api-below-31', 'appliedHex', 'prompt-window-', 'packageNameMatches', 'api30Facts']:
            self.assertIn(text, driver)

    def test_finding4_fresh_mobile_retrieval_before_reduction(self):
        # Start with no host events, then exercise the same transport used after collection.
        obs = self.root / 'recorder/observations.json'; obs.write_text(json.dumps(self.observation()))
        accent.analyze_android_events(self.root, self.case_id)
        self.assertEqual(json.loads(obs.read_text())['assertions'][self.case_id + '-RECREATE']['verdict'], 'UNVERIFIED')
        records = [{'type': 'shell-spike:event', 'detail': {'name': row['name'], 'fields': row['fields']}}
                   for row in self.events()]
        renderer = self.root / 'recorder/renderer-events.jsonl'
        payload = ''.join(json.dumps(row) + '\n' for row in records).encode()
        with patch.object(case, 'run', side_effect=["files/renderer.jsonl", None]), patch.object(
                case.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, payload, b'')):
            case.collect_mobile_renderer_events('android', self.root, self.case_id)
        self.assertEqual(renderer.read_bytes(), payload)
        accent.analyze_android_events(self.root, self.case_id)
        results = json.loads(obs.read_text())['assertions']
        self.assertEqual(results[self.case_id + '-RECREATE']['verdict'], 'PASS')
        self.assertEqual(results[self.case_id + '-IDENTITY']['verdict'], 'PASS')
        source = (ROOT / 'ci/run_case.py').read_text()
        self.assertLess(source.index('collect_mobile_renderer_events(platform_name, scenario, case_id)'), source.index('"--reduce-android", str(scenario)'))
        self.assertLess(source.index('"--reduce-android", str(scenario)'), source.index('refresh_lane_envelope(spike, scenario, case_file)', source.index('"--reduce-android"')))

    def test_finding5_complete_and_incomplete_callback_sequences(self):
        complete = self.events()
        results = self.reduce(complete)
        for suffix in ['WALLPAPER', 'RECREATE', 'IDENTITY']:
            self.assertEqual(results[self.case_id + '-' + suffix]['verdict'], 'PASS')
        self.assertEqual(results[self.case_id + '-FRAME']['verdict'], 'UNVERIFIED')
        mutations = {
            'positive-generation-only': [complete[0], complete[3]],
            'missing-second-change': complete[:4],
            'missing-second-host': complete[:5],
            'missing-first-host': complete[:2] + complete[3:],
            'duplicate-second-host': complete + [copy.deepcopy(complete[-1])],
            'duplicate-second-callback': complete + [copy.deepcopy(complete[-2])],
            'out-of-order-delivery': complete[:4] + [complete[5], complete[4]],
        }
        for title, rows in mutations.items():
            with self.subTest(title=title):
                self.assertEqual(self.reduce(rows)[self.case_id + '-RECREATE']['verdict'], 'UNVERIFIED')
        changed = copy.deepcopy(complete); changed[3]['fields']['activityGeneration'] = 0
        self.assertEqual(self.reduce(changed)[self.case_id + '-RECREATE']['verdict'], 'UNVERIFIED')
        self.assertEqual(self.reduce([complete[0]])[self.case_id + '-WALLPAPER']['verdict'], 'UNVERIFIED')
        driver = (ROOT / 'automation/android/s11/AccentUiAutomator.java').read_text()
        self.assertIn('base, "second", 1', driver)
        self.assertNotIn('verdict = changed ? "PASS"', driver)

    def test_finding6_static_clamp_helper_resolution(self):
        import re
        source = (ROOT / 'automation/windows/s11/drive.ps1').read_text()
        branch = source.split("elseif ($suffix -match 'CLAMP') {", 1)[1].split("} elseif", 1)[0]
        functions = set(re.findall(r'function\s+(Get-[\w-]+)', source))
        calls = set(re.findall(r'\((Get-[\w-]+)\s+\$_\)', branch))
        self.assertEqual(calls, {'Get-EventName', 'Get-Fields'})
        self.assertTrue(calls <= functions)
        self.assertNotIn('Get-EventFields', source)
        self.assertIn('(Get-Fields $_).clamped -eq $true', branch)

    def test_finding6_powershell_actual_clamp_expression(self):
        source = (ROOT / 'automation/windows/s11/drive.ps1').read_text()
        self.assertNotIn('Get-EventFields', source)
        # Parse the actual driver and extract its real helpers and clamp assignment.
        driver = str(ROOT / 'automation/windows/s11/drive.ps1').replace("'", "''")
        script = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__DRIVER__',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw $errors[0] }
foreach ($name in @('Get-Fields','Get-EventName')) {
  $fn=$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true) | Where-Object Name -eq $name
  Invoke-Expression $fn.Extent.Text
}
$assignment=$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst]},$true) | Where-Object { $_.Extent.Text -like '*$rows | Where-Object*host-and-token-update*clamped*' }
if (@($assignment).Count -ne 1) { throw 'Expected one actual clamp assignment' }
foreach ($expected in @($false,$true)) {
  $rows=@([pscustomobject]@{name='s11.host-and-token-update'; fields=[pscustomobject]@{clamped=$expected}})
  Invoke-Expression $assignment.Extent.Text
  if ($clamped -ne $expected) { throw "clamp mismatch" }
}
'actual Windows clamp branch: false and true passed'
'''.replace('__DRIVER__', driver)
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], capture_output=True, text=True)
        if result.returncode != 0 and 'Stack overflow.' in result.stderr + result.stdout:
            self.skipTest('Installed pwsh crashes even at startup on this host; static helper-resolution proof runs separately.')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_discovery_authorization_dry_run_and_payload_hash(self):
        policy = json.loads((ROOT / 'ci/environment-lock.json').read_text())['runtimePolicy']
        env = dict(GITHUB_RUN_NUMBER='3', GITHUB_RUN_ATTEMPT='1', GITHUB_RUN_ID='123',
                   GITHUB_REF='refs/heads/shell-spikes/integration-1118', GITHUB_REF_TYPE='branch')
        for number in ['1', '2', '3', '4', '5', '6']:
            self.assertTrue(discovery.authorized(policy, {**env, 'GITHUB_RUN_NUMBER': number}))
        for key, wrong in [('GITHUB_RUN_NUMBER','7'), ('GITHUB_RUN_ATTEMPT','2'), ('GITHUB_RUN_ID',''),
                           ('GITHUB_REF','refs/heads/other'), ('GITHUB_REF_TYPE','tag')]:
            self.assertFalse(discovery.authorized(policy, {**env, key: wrong}))
        with patch.dict(os.environ, {'ANDROID_API_LEVEL':'30'}):
            for target in ['macos','ios','android','linux','windows']:
                commands = discovery.plan(target, self.root)
                run = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, 'fixture install log', '')
                self.assertTrue(all(row['exitCode'] == 0 for row in discovery.execute_plan(commands, self.root, run)))
            self.assertIn('--channel=0', discovery.plan('android', self.root)[0])
        runtime = self.root / 'libwebkit.so'; runtime.write_bytes(b'actual fixture runtime payload')
        environment = dict(platform='linux', cell='linux-ubuntu-24.04-x11', sourceSha='a'*40,
                           versions={'webview':'fixture-1'}, runnerImage='ubuntu24',runnerImageVersion='fixture',os='fixture')
        fake = subprocess.CompletedProcess([], 0, str(runtime), '')
        with patch.object(discovery.subprocess,'run',return_value=fake), patch.dict(os.environ,env):
            record = discovery.record_runtime(self.root, environment)
        self.assertEqual(record['artifacts'][0]['sha256'],hashlib.sha256(runtime.read_bytes()).hexdigest())
        self.assertEqual(record['resolvedVersion'],'fixture-1')
        self.assertEqual(record['verdict'],'UNVERIFIED')
        self.assertIn('runtimeDiscovery.runtimePayloadSha256', record['candidatePins'])
        self.assertFalse(case.runtime_matches_pin(environment['cell'],environment))

    def test_discovery_failed_install_does_not_continue_or_invent_payload(self):
        calls = []
        def fail(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, '', 'fixture installer failure')
        rows = discovery.execute_plan([['first'], ['second']], self.root, fail)
        self.assertEqual(calls, [['first']])
        self.assertEqual(rows[0]['exitCode'], 1)
        environment = dict(platform='linux', cell='fixture', sourceSha='a'*40, versions={'webview':None})
        with patch.object(discovery.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            record = discovery.record_runtime(self.root, environment)
        self.assertEqual(record['status'], 'UNVERIFIED')
        self.assertEqual(record['artifacts'], [])
        self.assertIsNone(record['runtimePayloadSha256'])

    def test_uncalibrated_cells_explicit_and_never_frame_pass(self):
        rows = collector.presentation_calibration_report(self.root)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['status'] == 'UNVERIFIED' for row in rows))
        (self.root / 'environment.json').write_text(json.dumps({'cell':'android-api-31','caseId':self.case_id}))
        (self.root / 'recorder/capture-index-status.json').write_text(json.dumps({'clockCalibrated':False}))
        (self.root / 'recorder/renderer-events.jsonl').write_text(json.dumps({'detail':{'name':'s11.native-event','fields':{'sequence':2}}})+'\n')
        (self.root / 'recorder/presentation-links.jsonl').write_text(json.dumps({'sequence':2,'status':'correlated'})+'\n')
        (self.root / 'recorder/observations.json').write_text(json.dumps(self.observation()))
        finalizer.finalize(self.root)
        result = json.loads((self.root / 'recorder/observations.json').read_text())
        self.assertEqual(result['assertions'][self.case_id + '-FRAME']['verdict'],'UNVERIFIED')
        rows = collector.presentation_calibration_report(self.root)
        self.assertEqual(next(row for row in rows if row['cell']=='android-api-31')['status'],'UNVERIFIED')

if __name__ == '__main__':
    unittest.main()
