"""Local regression proofs for review round five; no devices, CI or Git writes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ci'), str(ROOT / 'automation')]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded

runtime = module('native_runtime', 'automation/native_runtime.py')
case = module('run_case', 'ci/run_case.py')
index = module('capture_index', 'ci/recorders/index-video.py')
scrim = module('scrim', 'ci/analyze-s08.py')
projects = module('projects', 'ci/generate-native-test-projects.py')


def png(path, width, height, rgb):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    rows = b''.join(b'\0' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def marker(path, sequence, phase=2, scale=1):
    width, height = 400 * scale, 80 * scale
    pixels = bytearray(b'\xff\xff\xff' * width * height)
    bits = f'{sequence * 4 + phase:026b}'
    for bit in range(34):
        color = ((255, 0, 255) if bit % 2 == 0 else (0, 255, 255)) if bit < 8 else ((0, 0, 0) if bits[bit - 8] == '1' else (255, 255, 255))
        for y in range(16 * scale, 32 * scale):
            for x in range((20 + bit * 4) * scale, (24 + bit * 4) * scale):
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = bytes(color)
    png(path, width, height, pixels)


class RoundFive(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'recorder').mkdir()
    def tearDown(self):
        self.temp.cleanup()

    def test_android_instrumentation_and_private_export(self):
        apk = self.root / 'test.apk'; apk.touch()
        env = dict(SHELL_UIAUTOMATOR_APK=str(apk), SHELL_UIAUTOMATOR_RUNNER='androidx.test.runner.AndroidJUnitRunner',
                   SHELL_UIAUTOMATOR_TEST_PACKAGE='org.example.test', SHELL_MOBILE_BUNDLE_ID='org.example.mobile')
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as out:
            data = b'{"assertions":{}}'
            entry = tarfile.TarInfo('./observations.json'); entry.size = len(data)
            out.addfile(entry, io.BytesIO(data))
            entry = tarfile.TarInfo('../../escaped'); entry.size = 1
            out.addfile(entry, io.BytesIO(b'x'))
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, archive.getvalue() if 'exec-out' in command else 'OK (1 test)', '')
        for spike, method, case_id in [('s10', 'ColourUiAutomator#testNativePicker', 'S10-ANDROID'),
                                      ('s11', 'AccentUiAutomator#testWallpaperAccent', 'S11-ANDROID-API-30-NEGATIVE')]:
            with patch.object(runtime.subprocess, 'run', side_effect=run):
                runtime.run_android(spike, method, case_id, self.root, env)
            instrument = next(command for command in reversed(calls) if 'instrument' in command)
            self.assertIn('org.example.shellspikes.' + method, instrument)
            self.assertIn(case_id, instrument)
            self.assertTrue((self.root / 'recorder/observations.json').is_file())
        self.assertFalse((self.root.parent / 'escaped').exists())
        self.assertTrue(all('/sdcard' not in str(command) for command in calls))
        self.assertTrue(any('run-as' in command and 'tar' in command for command in calls))
        for lane in ['colour', 'accent']:
            driver = module(lane, f'automation/{lane}/runner.py')
            with patch.object(driver, 'run_android', return_value=subprocess.CompletedProcess([], 0)) as dispatch:
                args = ('android', self.root, 'S11-ANDROID-API-30-NEGATIVE', env) if lane == 'colour' else ('android', driver.DRIVERS['android'], 'S11-ANDROID-API-30-NEGATIVE', self.root, env)
                driver.run_native(*args)
                dispatch.assert_called_once()
            if lane == 'accent':
                with patch.object(driver, 'run_android') as dispatch:
                    driver.run_native('android', driver.DRIVERS['android'], 'S11-ANDROID-PROVIDER-UNAVAILABLE', self.root, env)
                    dispatch.assert_called_once()

    def test_android_build_paths_and_sdk_pins(self):
        build = (ROOT / 'ci/build-android-uiautomator.sh').read_text()
        lock = json.loads((ROOT / 'ci/environment-lock.json').read_text())
        self.assertIn('apps/test-shell-mobile/src-tauri/gen/android', build)
        self.assertIn('src-tauri/gen/android/gradle/wrapper', lock['android']['uiAutomator']['gradleWrapper'])
        self.assertIn('--project-dir "$android_project"', build)
        self.assertIn(':app:assembleUniversalDebugAndroidTest', build)
        self.assertIn('project.android.compileSdk = 36', build)
        self.assertNotIn('/sdcard/', ''.join((ROOT / f'automation/android/{s}/{n}UiAutomator.java').read_text() for s,n in [('s10','Colour'),('s11','Accent')]))

    def test_ios_result_bundle_arguments_and_array_manifest(self):
        bundle = self.root / 'result.xcresult'; bundle.mkdir()
        export = self.root / 'recorder/ios-xctest-attachments'; export.mkdir()
        records = []
        for number, name in enumerate(['screens/picker.png', 'recorder/observations.json', '../escape', '/tmp/escape']):
            exported = f'{number}.data'; (export / exported).write_bytes(b'evidence')
            records.append({'attachments': [{'suggestedHumanReadableName': name, 'exportedFileName': exported}]})
        (export / 'manifest.json').write_text(json.dumps(records))
        env = dict(SHELL_IOS_XCRESULT_PATH=str(bundle), SHELL_IOS_PROJECT='tests.xcodeproj', SHELL_IOS_TEST_SCHEME='tests', SHELL_IOS_DESTINATION='platform=iOS Simulator')
        with patch.dict(os.environ, env), patch.object(case.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            case.collect_ios_xctest_evidence('s10', self.root)
        self.assertEqual((self.root / 'screens/picker.png').read_bytes(), b'evidence')
        self.assertEqual((self.root / 'recorder/observations.json').read_bytes(), b'evidence')
        self.assertTrue(bundle.is_dir())
        status = json.loads((self.root / 'recorder/ios-xctest-evidence-transport.json').read_text())
        self.assertEqual(len(status['attachments']), 2)
        for lane in ['colour', 'accent']:
            driver = module(lane, f'automation/{lane}/runner.py')
            with patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([],0)) as run:
                args = ('ios', self.root, 'S11-POLICY-IPHONE', env) if lane == 'colour' else ('ios', driver.DRIVERS['ios'], 'S11-POLICY-IPHONE', self.root, env)
                driver.run_native(*args)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index('-resultBundlePath') + 1], str(bundle))

    def test_process_cleanup_and_escalation(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        runtime.stop_desktop(process)
        self.assertIsNotNone(process.poll())
        hung = Mock(); hung.poll.return_value = None
        hung.wait.side_effect = [subprocess.TimeoutExpired('shell',10), 0]
        runtime.stop_desktop(hung)
        hung.terminate.assert_called_once(); hung.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in hung.wait.call_args_list], [10,5])

    def test_bundle_identifier_derived_and_mismatch_rejected(self):
        app = self.root / 'Test.app'; (app / 'Contents').mkdir(parents=True)
        with (app / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleIdentifier': 'org.example.actual'}, stream)
        with patch.dict(os.environ, {'SHELL_APP_PATH':str(app), 'S01_APP_BUNDLE_ID':'org.example.actual'}), patch.object(projects, 'ROOT', self.root):
            project = projects.project_for('macos','s01')
            self.assertIn('PRODUCT_BUNDLE_IDENTIFIER = "org.example.actual"', (project / 'project.pbxproj').read_text())
            self.assertIn('actual_id', (project / 'project.pbxproj').read_text())
            with patch.dict(os.environ, {'S01_APP_BUNDLE_ID':'org.example.wrong'}):
                with self.assertRaises(ValueError): projects.project_for('macos','s01')

    def test_marker_decoder_scales_and_compressed_video(self):
        for scale in [1,2,3]:
            image = self.root / f'code-{scale}.png'; marker(image, 0x13579b, scale=scale)
            self.assertEqual(index.decode_presentation_marker(image), (0x13579b,2))
        source = self.root / 'code-1.png'; video = self.root / 'code.mkv'; decoded = self.root / 'decoded.png'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-frames:v','1','-pix_fmt','rgb24',str(decoded)],check=True)
        self.assertEqual(index.decode_presentation_marker(decoded), (0x13579b,2))

    def test_scrim_clear_dim_and_unknown(self):
        width=height=320
        baseline = (width,height,b'\xc8\xc8\xc8' * width * height)
        dark = (width,height,b'\x78\x78\x78' * width * height)
        white = (width,height,b'\xff\xff\xff' * width * height)
        args=([0,0,320,320],[500,500,50,50],[0,0,320,320])
        self.assertEqual(scrim.classify(baseline,baseline,baseline,*args),'clear')
        self.assertEqual(scrim.classify(baseline,baseline,dark,*args),'scrim')
        self.assertEqual(scrim.classify(baseline,baseline,white,*args),'unclassified')
        self.assertEqual(scrim.classify(baseline,dark,baseline,*args),'unclassified')

    def test_android_builder_dry_run(self):
        import shutil
        repo = self.root / 'build-repo'
        (repo / 'ci').mkdir(parents=True)
        shutil.copy(ROOT / 'ci/build-android-uiautomator.sh', repo / 'ci')
        project = repo / 'apps/test-shell-mobile/src-tauri/gen/android'
        (project / 'app').mkdir(parents=True)
        wrapper = project / 'gradlew'
        wrapper.write_text("#!/bin/bash\nset -eu\n[[ \"$1\" == --project-dir ]]\ncd \"$2\"\n[[ \"${@: -1}\" == :app:assembleUniversalDebugAndroidTest ]]\nmkdir -p app/build/outputs/apk/androidTest/universal/debug\nprintf apk > app/build/outputs/apk/androidTest/universal/debug/app-debug-androidTest.apk\n")
        wrapper.chmod(0o755)
        aapt = repo / 'sdk/build-tools/36.0.0/aapt'; aapt.parent.mkdir(parents=True)
        aapt.write_text('''#!/bin/sh
if [ "$2" = xmltree ]; then
cat <<'MANIFEST'
    E: instrumentation (line=1)
      A: android:name(0x01010003)="androidx.test.runner.AndroidJUnitRunner"
      A: android:targetPackage(0x01010021)="org.example.shellspikes.mobile"
MANIFEST
else
  echo "package: name='org.example.shellspikes.mobile.test'"
fi
''')
        aapt.chmod(0o755)
        subprocess.run(['bash',str(repo / 'ci/build-android-uiautomator.sh')],
                       env={**os.environ,'ANDROID_SDK_ROOT':str(repo / 'sdk')}, check=True, capture_output=True)
        self.assertEqual((repo / 'target/native-tests/android/shell-spike-uiautomator.apk').read_bytes(),b'apk')

    def test_runtime_freeze_does_not_invent_pins(self):
        lock = case.environment_lock()
        self.assertTrue(lock['runtimePolicy']['passRequiresExactRuntimeMatch'])
        self.assertFalse(case.runtime_matches_pin('mac-desktop', {'image':'mutable'}))
        with patch.object(case,'environment_lock',return_value={'runtimePolicy': {'passRequiresExactRuntimeMatch':True,'exactRuntimeVersionsByCell':{'cell':{'webview.version':'123'}}}}):
            self.assertTrue(case.runtime_matches_pin('cell',{'webview':{'version':'123'}}))
            self.assertFalse(case.runtime_matches_pin('cell',{'webview':{'version':'124'}}))

    def test_presentation_join_and_fail_closed_calibration(self):
        (self.root / 'video').mkdir()
        video = self.root / 'video/capture.mkv'; video.write_bytes(b'recorded')
        (self.root / 'environment.json').write_text(json.dumps({'spike':'s11','platform':'windows','display':{'refreshHz':60}}))
        clock={'status':'measured','samples':[{'phase':'start','monotonicNanoseconds':1000000000},{'phase':'stop','monotonicNanoseconds':2000000000}],
               'calibrationUncertaintyNanoseconds':1000,'wallToMonotonicOffsetNanoseconds':1000000000-1700000000000000000}
        (self.root / 'recorder/capture-clock.json').write_text(json.dumps(clock))
        frame_event={'type':'shell-spike:frame','hostReceiptMonotonicNanoseconds':1001000000,
                     'hostUpdateMonotonicNanoseconds':1002000000,'detail':{'sequence':7,'phase':'tokens-mutated'}}
        event_path=self.root / 'recorder/renderer-events.jsonl'
        def run_variant(timestamp_mode='epoch'):
            def command(arguments):
                if '-show_frames' in arguments:
                    times=['1700000000.000','1700000000.010','1700000000.020'] if timestamp_mode=='epoch' else ['0','.010','.020']
                    return subprocess.CompletedProcess(arguments,0,json.dumps({'frames':[{'best_effort_timestamp_time':t} for t in times]}),'')
                frames=self.root / 'screens/video-frames'
                for number,seq in [(1,0),(2,7),(3,7)]: marker(frames / f'frame-{number:06d}.png',seq)
                return subprocess.CompletedProcess(arguments,0,'','')
            event_path.write_text(json.dumps(frame_event)+'\n'+json.dumps({'detail':{'name':'s11.native-event','fields':{'sequence':7}}})+'\n')
            with patch.object(index,'command',side_effect=command), patch.object(sys,'argv',['index','--evidence-dir',str(self.root),'--video',str(video)]):
                self.assertEqual(index.main(),0)
            return json.loads((self.root / 'recorder/presentation-links.jsonl').read_text().splitlines()[0])
        self.assertEqual(run_variant()['status'],'correlated')
        finalizer=module('finalizer','ci/finalize-s11.py')
        observed=self.root / 'recorder/observations.json'
        observed.write_text(json.dumps({'assertions':{'S11-WINDOWS-FRAME':{'verdict':'UNVERIFIED'}}}))
        finalizer.finalize(self.root)
        self.assertEqual(json.loads(observed.read_text())['assertions']['S11-WINDOWS-FRAME']['verdict'],'PASS')
        self.assertEqual(run_variant('relative')['status'],'UNVERIFIED')
        frame_event['hostUpdateMonotonicNanoseconds']=1009000000
        frame_event['hostReceiptMonotonicNanoseconds']=1008000000
        self.assertEqual(run_variant()['status'],'correlated')
        frame_event['hostReceiptMonotonicNanoseconds']=980000000
        self.assertEqual(run_variant()['status'],'measured-late')
        finalizer.finalize(self.root)
        self.assertEqual(json.loads(observed.read_text())['assertions']['S11-WINDOWS-FRAME']['verdict'],'FAIL')
        frame_event['hostReceiptMonotonicNanoseconds']=800000000
        frame_event['hostUpdateMonotonicNanoseconds']=900000000
        self.assertEqual(run_variant()['status'],'measured-late')
        frame_event.pop('hostUpdateMonotonicNanoseconds')
        self.assertEqual(run_variant()['status'],'UNVERIFIED')
        finalizer.finalize(self.root)
        self.assertEqual(json.loads(observed.read_text())['assertions']['S11-WINDOWS-FRAME']['verdict'],'UNVERIFIED')

    def test_s08_finalized_analysis_and_rereduction(self):
        import hashlib
        (self.root / 'video').mkdir(); (self.root / 'screens').mkdir()
        video=self.root / 'video/desktop.mp4'; video.write_bytes(b'finalized recording fixture')
        digest=hashlib.sha256(video.read_bytes()).hexdigest()
        for name in ['a.png','b.png','frame.png']:
            png(self.root / 'screens' / name,320,320,b'\xc8\xc8\xc8'*320*320)
        events=[{'event':'scrim-baseline','windowID':42,'mainBounds':[0,0,320,320], 'displayBounds':[0,0,320,320],
                 'displayCount':1,'screens':['screens/a.png','screens/b.png']},
                {'event':'scrim-interval-start','windowID':42,'mainBounds':[0,0,320,320],'excludeBounds':[500,500,100,100],'monotonicSeconds':1},
                {'event':'scrim-interval-stop','monotonicSeconds':2},
                {'event':'S08-A07','settingsIsKey':True,'mainInactiveMarker':True},
                {'event':'assertion','id':'S08-A07','verdict':'UNVERIFIED','actual':'requires finalized capture'}]
        event_file=self.root / 'recorder/s08-case-events.jsonl'; event_file.write_text(''.join(json.dumps(row)+'\n' for row in events))
        (self.root / 'recorder/capture-index-status.json').write_text(json.dumps({'videoSha256':digest}))
        (self.root / 'video/capture-index.jsonl').write_text(json.dumps({'clockMapping':'paired-realtime-monotonic','timestampNanoseconds':1500000000,'relativePath':'screens/frame.png'})+'\n')
        result=scrim.analyze(self.root)
        self.assertEqual(result['verdict'],'PASS'); self.assertEqual(result['classifiedFrames'],1)
        (self.root / 'recorder/s08-screen-analysis.json').write_text(json.dumps({'results':[result]}))
        output=self.root / 'assertions.json'
        subprocess.run([sys.executable,str(ROOT / 'automation/macos/s08/reduce.py'),str(ROOT / 'cases/s08.json'),
                        'S08-MAC-03-parented-sheet-and-inactive-main',str(event_file),str(output),str(self.root)],check=True)
        a07=next(row for row in json.loads(output.read_text())['results'] if row['id'].startswith('S08-A07'))
        self.assertEqual(a07['verdict'],'PASS')
        png(self.root / 'screens/frame.png',320,320,b'\x78\x78\x78'*320*320)
        result=scrim.analyze(self.root); self.assertEqual(result['verdict'],'FAIL'); self.assertEqual(result['scrimFrames'],1)
        (self.root / 'recorder/capture-index-status.json').write_text(json.dumps({'videoSha256':'wrong'}))
        self.assertEqual(scrim.analyze(self.root)['verdict'],'UNVERIFIED')

    def test_s08_effective_grants_and_retained_input_hashes(self):
        import hashlib, tomllib
        permissions=tomllib.loads((ROOT / 'apps/desktop/src-tauri/permissions/s08.toml').read_text())
        allowed=['plugin:s08-settings|'+command for command in permissions['permission'][0]['commands']['allow']]
        compiled={'provenance':'compiled-build','windowCapabilities':{'settings':['settings']},
                  'capabilities':[{'identifier':'settings','windows':['settings'],'platforms':['macOS']}],
                  'permissionResolutionStatus':'resolved', 'compiledInputs':[],
                  'resolvedCommandGrantsByWindow':{'settings':{command:True for command in allowed}}}
        (self.root / 'recorder/s08-acl-inputs').mkdir()
        for name in ['acl-manifests.json','capabilities.json']:
            relative='recorder/s08-acl-inputs/'+name; (self.root / relative).write_bytes(b'compiled input')
            compiled['compiledInputs'].append({'path':relative,'sha256':hashlib.sha256(b'compiled input').hexdigest()})
        path=self.root / 'recorder/s08-compiled-acl.json'; manifest=self.root / 'recorder/s08-acl-manifest.json'
        event_file=self.root / 'recorder/events'; event_file.touch()
        doc=json.loads((ROOT / 'cases/s08.json').read_text())
        case_id=next(row['id'] for row in doc['cases'] if any(ref['id'].startswith('S08-A15') for ref in row['assertions']))
        def reduce():
            path.write_text(json.dumps(compiled))
            manifest.write_text(json.dumps({'buildStatus':'completed','compiledAcl':{'path':'recorder/s08-compiled-acl.json','status':'captured','provenance':'compiled-build','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}))
            output=self.root / 'assertions.json'
            subprocess.run([sys.executable,str(ROOT / 'automation/macos/s08/reduce.py'),str(ROOT / 'cases/s08.json'),case_id,str(event_file),str(output),str(self.root)],check=True)
            return next(row for row in json.loads(output.read_text())['results'] if row['id'].startswith('S08-A15'))['verdict']
        self.assertEqual(reduce(),'PASS')
        for forbidden in ['plugin:dialog|open','plugin:dialog|save','plugin:fs|read_file','plugin:s08-settings|s08_sentinel_tool_command','plugin:s08-settings|s08_open_settings','plugin:fs|s08_read_settings']:
            compiled['resolvedCommandGrantsByWindow']['settings'][forbidden]=True
            self.assertEqual(reduce(),'FAIL')
            del compiled['resolvedCommandGrantsByWindow']['settings'][forbidden]
        compiled['permissionResolutionStatus']='UNVERIFIED'; self.assertEqual(reduce(),'UNVERIFIED')
        compiled['permissionResolutionStatus']='resolved'
        (self.root / 'recorder/s08-acl-inputs/acl-manifests.json').write_bytes(b'tampered')
        self.assertEqual(reduce(),'UNVERIFIED')

    def test_android_installer_exports_instrumentation_contract(self):
        platform = module('run_platform', 'ci/run-platform.py')
        apk = self.root / 'target/native-tests/android/shell-spike-uiautomator.apk'
        apk.parent.mkdir(parents=True); apk.write_bytes(b'APK fixture')
        with patch.object(platform,'ROOT',self.root), patch.dict(os.environ,{'SHELL_EVIDENCE_DIR':str(self.root)},clear=False), \
             patch.object(platform.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'installed','')) as run:
            platform.build_android_uiautomator()
            self.assertTrue(any(call.args[0][:3] == ['adb','install','-r'] for call in run.call_args_list))
            self.assertEqual(os.environ['SHELL_UIAUTOMATOR_APK'],str(apk))
            self.assertEqual(os.environ['SHELL_UIAUTOMATOR_RUNNER'],'androidx.test.runner.AndroidJUnitRunner')
            self.assertEqual(os.environ['SHELL_UIAUTOMATOR_TEST_PACKAGE'],'org.example.shellspikes.mobile.test')

    def test_lane_finally_retains_handle_on_driver_failure(self):
        for lane in ['colour','accent']:
            driver = module(lane, f'automation/{lane}/runner.py')
            process = Mock(pid=43210)
            with patch.dict(os.environ,{'SHELL_CASE_ID':'fixture','SHELL_EVIDENCE_DIR':str(self.root),'SHELL_APP_PATH':'/fixture/app'}), \
                 patch.object(sys,'argv',['runner','--platform','linux']), \
                 patch.object(driver,'launch_desktop',return_value=process), \
                 patch.object(driver,'run_native',side_effect=RuntimeError('native timeout')), \
                 patch.object(driver,'wait_desktop_ready',return_value=True), \
                 patch.object(driver,'write_status'), patch.object(driver.time,'sleep'), \
                 patch.object(driver.subprocess,'run',return_value=subprocess.CompletedProcess([],0)), \
                 patch.object(driver,'stop_desktop') as stop:
                self.assertEqual(driver.main(),0)
                stop.assert_called_once_with(process,self.root)
                self.assertEqual(json.loads((self.root / 'recorder/desktop-process.json').read_text())['pid'],43210)

    def test_acl_namespace_denials_do_not_mask_other_plugins(self):
        acl=module('prepare_s08','ci/prepare-s08-evidence.py')
        manifests={'dialog':{'permissions':{'deny-open':{'commands':{'allow':[],'deny':['open']}}}},
                   'fs':{'permissions':{'allow-open':{'commands':{'allow':['open'],'deny':[]}}}}}
        _, grants, unresolved=acl.resolve_capability_grants(manifests,{'permissions':['dialog:deny-open','fs:allow-open']})
        self.assertFalse(unresolved)
        self.assertFalse(grants['plugin:dialog|open']['allowed'])
        self.assertTrue(grants['plugin:fs|open']['allowed'])

    def test_exact_branch_guards_every_job(self):
        workflow=(ROOT / '.github/workflows/shell-spikes.yml').read_text()
        self.assertEqual(workflow.count('name: Guard dispatch ref and frozen SHA'),8)
        self.assertEqual(workflow.count('id: dispatch-guard'),8)
        self.assertIn("if: always() && steps.dispatch-guard.outcome == 'success'",workflow)
        self.assertEqual(workflow.count('refs/heads/shell-spikes/integration-1118'),16)
        # Execute every Bash guard using a read-only fake git identity.
        fake=self.root / 'git'; fake.write_text('#!/bin/sh\nprintf "%s\\n" "$FROZEN_SHA"\n'); fake.chmod(0o755)
        sections=workflow.split('name: Guard dispatch ref and frozen SHA')[1:]
        for section in sections:
            if 'shell: pwsh' in section.split('run: |')[0]: continue
            lines=section.split('run: |\n',1)[1].splitlines()
            guard_lines=[]
            for line in lines:
                if not line.startswith('          '): break
                guard_lines.append(line[10:])
            script='\n'.join(guard_lines)
            for branch,code in [('refs/heads/shell-spikes/integration-1118',0),('refs/heads/other',1)]:
                env={**os.environ,'PATH':str(self.root)+':'+os.environ['PATH'],'GITHUB_REF':branch,'GITHUB_REF_TYPE':'branch','FROZEN_SHA':'a'*40}
                completed=subprocess.run(['bash','-e','-c',script],env=env,capture_output=True)
                self.assertEqual(completed.returncode,code)

if __name__=='__main__': unittest.main(verbosity=2)
