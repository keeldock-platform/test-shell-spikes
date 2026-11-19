"""Run-16 control-flow replays; simulated tools never establish native PASS."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class RunSixteenReplays(unittest.TestCase):
    def test_case_exit_separates_verdict_from_execution(self):
        # Execute the actual final status expression, including against old revisions.
        source = (ROOT / 'ci/run_case.py').read_text()
        tail = source[source.index('    incomplete = any('):source.index('\n\nif __name__')]
        ns = {}
        exec('def status(results, adapter_status, recorder_started, recorder_stop_ok):\n' + tail, ns)
        status = ns['status']
        for verdict in ['FAIL', 'PASS', 'UNVERIFIED']:
            row = {'id': 'observed', 'verdict': verdict, 'laneVerdict': verdict}
            self.assertEqual(status([row], 0, True, True), 0)
        failed = [{'id': 'observed', 'verdict': 'FAIL', 'laneVerdict': 'FAIL'}]
        self.assertEqual(status(failed, 1, True, True), 0)
        self.assertEqual(status(failed, 2, True, True), 1)
        self.assertEqual(status(failed, 124, True, True), 1)
        self.assertEqual(status(failed, 1, False, True), 1)
        self.assertEqual(status(failed, 1, True, False), 1)
        self.assertEqual(status([], 1, True, True), 1)
        self.assertEqual(status([{'verdict': 'UNVERIFIED'}], 1, True, True), 1)

    def test_guard_still_rejects_fallback_and_accepts_real_fail(self):
        guard = module('guard19', 'ci/verify-execution.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cell = root / 'cells/fixture'
            cell.mkdir(parents=True)
            (root / 'events.jsonl').write_text(json.dumps({'event': 'scenario-finished', 'automationExit': 0}) + '\n')
            for verdict in ['UNVERIFIED', 'FAIL']:
                (cell / 'assertions.json').write_text(json.dumps({'results': [{'verdict': verdict}]}))
                self.assertEqual(bool(guard.execution_summary(root)['errors']), verdict == 'UNVERIFIED')

    def test_android_generated_agp8_dsl_replays_before_gradle(self):
        pin = module('pin19', 'ci/pin-android-gradle.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'buildSrc').mkdir()
            (root / 'app').mkdir()
            (root / 'gradle/wrapper').mkdir(parents=True)
            (root / 'build.gradle.kts').write_text('classpath("com.android.tools.build:gradle:9.3.1")\nclasspath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.2.10")')
            (root / 'buildSrc/build.gradle.kts').write_text('implementation("com.android.tools.build:gradle:9.3.1")')
            (root / 'gradle/wrapper/gradle-wrapper.properties').write_text('distributionUrl=old\n')
            app = root / 'app/build.gradle.kts'
            app.write_text('android { buildTypes { getByName("release") {\n optimization {\n enable = true\n }\n proguardFiles("rules.pro")\n} } }')
            pin.pin(root, '2.2.21')
            # Fake Gradle models the exact compile error, and verifies optimisation stays enabled.
            gradle = root / 'gradlew'
            gradle.write_text('#!' + sys.executable + '\nfrom pathlib import Path\ns=Path("app/build.gradle.kts").read_text()\nassert "enable = true" not in s, "Unresolved reference: enable"\nassert "isMinifyEnabled = true" in s\nassert "proguardFiles" in s\n')
            result = subprocess.run([sys.executable, str(gradle)], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_fedora_provisioning_installs_pipewire_cli(self):
        source = (ROOT / 'ci/linux/session.sh').read_text()
        body = source.split('provision_host() {', 1)[1].split('\nrun_in_session()', 1)[0]
        # Actual package selection and install control flow; host mutations are fake functions.
        script = '''set -euo pipefail
profile='Fedora current'; session=wayland; session_slug=wayland
SHELL_LINUX_GUEST=1; diagnostics="$REPLAY_ROOT/provision.json"
record_status() { :; }
bash() { case "$*" in *'install -y'*) [[ " $* " == *' pipewire-utils '* ]] ;; *) : ;; esac; }
python3() { cat >/dev/null; }
gnome-shell() { echo 'GNOME Shell fixture'; }
pkg-config() { echo fixture; }
ffmpeg() { echo fixture; }
rpm() { :; }
sudo() { :; }
''' + 'provision_host() {' + body + '\nprovision_host\n'
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['bash', '-c', script], env={**os.environ, 'REPLAY_ROOT': tmp}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_fedora_x11_recorder_uses_available_lossless_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ffmpeg = root / 'ffmpeg'
            ffmpeg.write_text('#!/bin/bash\n[[ " $* " == *" -c:v ffv1 "* ]] || exit 91\n[[ " $* " != *" -preset "* ]] || exit 92\nsleep 4\n')
            ffmpeg.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'ci/recorders/linux.sh'), 'start', str(root / 'capture.mkv')],
                                    env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'DISPLAY': ':97', 'XDG_SESSION_TYPE': 'x11'}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run(['bash', str(ROOT / 'ci/recorders/linux.sh'), 'stop', str(root / 'capture.mkv')], capture_output=True, timeout=25)

    def test_ios_display_measurement_retains_real_fail_without_guessing(self):
        case = module('case19', 'ci/run_case.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'recorder').mkdir()
            probe = root / 'recorder/ios-display.json'
            native = {'display': {'resolution': '1200x1800', 'scale': None, 'refreshHz': None},
                      'displayStatus': 'UNVERIFIED'}
            payload = {'caseId': 'fixture', 'simulatorUdid': 'device', 'resolution': '1200x1800',
                       'scale': 2, 'displayLinkTimestamps': [i / 60 for i in range(10)]}
            for mutation in [None, 'caseId', 'simulatorUdid', 'resolution', 'scale', 'displayLinkTimestamps']:
                row = dict(payload)
                if mutation:
                    row[mutation] = [] if mutation == 'displayLinkTimestamps' else -1
                probe.write_text(json.dumps(row))
                measured = case.ios_display_measurement(root, native, 'fixture', 'device')
                self.assertEqual(measured is not None, mutation is None)
                if measured:
                    self.assertAlmostEqual(measured['refreshHz'], 60)

    def test_guest_stale_seat_directory_uses_native_non_systemd_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = (ROOT / 'ci/linux/guest.sh').read_text()
            # Fake tools model a package-created empty seat dir in a bash-PID1 guest.
            block = source.split('  # A private system bus', 1)[1].split('\n', 1)[1].split('  bash ci/linux/session.sh run', 1)[0]
            script = """set -euo pipefail
mkdir() { :; }
bash() { :; }
dbus-uuidgen() { :; }
dbus-daemon() { :; }
busctl() { :; }
cat() { if [[ "$1" == /proc/1/comm ]]; then echo bash; else command cat "$@"; fi; }
[[ -d "$REPLAY_ROOT/seats" ]] || command mkdir "$REPLAY_ROOT/seats"
rmdir() { [[ "$1" == /run/systemd/seats ]]; command rmdir "$REPLAY_ROOT/seats"; }
""" + block.replace(' -d /run/systemd/seats ', ' -d "$REPLAY_ROOT/seats" ') + '\n[[ ! -d "$REPLAY_ROOT/seats" ]]\n'
            result = subprocess.run(['bash', '-c', script], env={**os.environ, 'REPLAY_ROOT': tmp}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_resolved_wayland_socket_reaches_activated_services(self):
        source = (ROOT / 'ci/linux/session.sh').read_text()
        block = source.split('      export WAYLAND_DISPLAY="${wayland_socket##*/}"', 1)[1].split('      export PATH=', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for status in [0, 93]:
                script = """set -euo pipefail
DISPLAY=:97; WAYLAND_DISPLAY=wayland-3; XDG_RUNTIME_DIR=/fixture
GDK_BACKEND=wayland; XDG_SESSION_TYPE=wayland; XDG_CURRENT_DESKTOP=GNOME
log="$REPLAY_ROOT/log"
dbus-update-activation-environment() {
  [[ "$*" == 'DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR GDK_BACKEND XDG_SESSION_TYPE XDG_CURRENT_DESKTOP' ]]
  [[ "$WAYLAND_DISPLAY" == wayland-3 && "$GDK_BACKEND" == wayland ]]
  echo "$WAYLAND_DISPLAY" > "$REPLAY_ROOT/activation"
  return "$FAKE_STATUS"
}
""" + block + '\n[[ -s "$REPLAY_ROOT/activation" ]]\n'
                result = subprocess.run(['bash', '-c', script], env={**os.environ, 'REPLAY_ROOT': tmp, 'FAKE_STATUS': str(status)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)

    def test_display_attachment_and_simulator_identity_are_transported(self):
        case = module('transport19', 'ci/run_case.py')
        suggested = 'recorderios-display_1_12345678-1234-1234-1234-123456789ABC.json'
        self.assertEqual(case.ios_attachment_relative_name(suggested), Path('recorder/ios-display.json'))
        generator = (ROOT / 'ci/generate-native-test-projects.py').read_text()
        self.assertIn('automation/ios/DisplayProbe.swift', generator)
        self.assertIn('key="SHELL_IOS_SIMULATOR_UDID"', generator)

    def test_s02_geometry_comes_only_from_native_event_rectangles(self):
        case = module('geometry19', 'ci/run_case.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'recorder').mkdir()
            path = root / 'recorder/geometry.json'
            events = root / 'events.jsonl'
            events.write_text(json.dumps({'name': 'window-state-requested', 'data': {'state': 'normal'}}) + '\n')
            case.materialize_s02_geometry(root)
            self.assertFalse(path.exists())
            rectangle = {'x': 12, 'y': 23, 'width': 1040, 'height': 660}
            events.write_text(json.dumps({'name': 'window-state-requested', 'data': {'bounds': rectangle}}) + '\n')
            case.materialize_s02_geometry(root)
            data = json.loads(path.read_text())
            self.assertEqual(data['observations'][0]['bounds'], rectangle)
            self.assertEqual(data['observations'][0]['sourceLine'], 1)

    def test_readback_fake_linker_requires_winrt_and_com_import_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compiler = root / 'cl.exe'
            compiler.write_text('#!' + sys.executable + '\nimport re,sys\nfrom pathlib import Path\ns=Path(sys.argv[1]).read_text()\nlibs=set(re.findall(r\'pragma comment\\(lib, "([^" ]+)"\\)\',s))\nassert {"windowsapp.lib", "ole32.lib", "oleaut32.lib"} <= libs, "LNK2019: WINRT_IMPL_RoGetActivationFactory / CoInitializeEx / SysFreeString"\n')
            result = subprocess.run([sys.executable, str(compiler), str(ROOT / 'automation/accent/windows-readback.cpp')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_accent_selector_uses_powershell7_reference_assemblies(self):
        source = (ROOT / 'automation/windows/s11/drive.ps1').read_text()
        import re
        executable = re.search(r'& (\w+) -NoProfile .*windows-select-accent', source).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, code in [('pwsh', 0), ('powershell', 91)]:
                p = root / name
                p.write_text('#!/bin/sh\nexit ' + str(code) + '\n')
                p.chmod(0o755)
            result = subprocess.run([str(root / executable), '-NoProfile'], capture_output=True)
            self.assertEqual(result.returncode, 0)

    def test_linux_colour_control_wins_over_its_static_label(self):
        import ast
        from types import SimpleNamespace
        path = ROOT / 'automation/linux/s10/drive.py'
        function = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'find')
        label = SimpleNamespace(getRoleName=lambda: 'static text', name='Custom colour picker')
        well = SimpleNamespace(getRoleName=lambda: 'color chooser', name='Custom colour picker')
        ns = dict(desktop=object(), walk=lambda _: [label, well], label=lambda n: n.name)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), ns)
        self.assertIs(ns['find']('Custom colour picker'), well)

    def test_android_transient_maven_failure_retries_without_masking_build_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fake=root/'cargo'
            fake.write_text('#!' + sys.executable + '\nimport os,sys\nfrom pathlib import Path\np=Path(os.environ["REPLAY_COUNT"])\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nmode=os.environ["REPLAY_MODE"]\nif mode=="compile": print("Unresolved reference: enable");sys.exit(7)\nif n==1 or mode=="exhaust": print("Could not find kotlin-compiler-runner-2.0.21.jar\\nhttps://repo.maven.apache.org/maven2/");sys.exit(8)\nassert os.environ.get("SHELL_ANDROID_REFRESH_DEPENDENCIES")=="1"\n')
            for mode, expected, attempts in [('transient',0,2),('compile',7,1),('exhaust',8,3)]:
                count=root/'count'
                count.unlink(missing_ok=True)
                result=subprocess.run(['bash',str(ROOT/'ci/android-build-retry.sh'),sys.executable,str(fake)],env={**os.environ,'REPLAY_MODE':mode,'REPLAY_COUNT':str(count),'SHELL_EVIDENCE_DIR':str(root/'evidence')},capture_output=True,text=True,timeout=25)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertEqual(int(count.read_text()),attempts)

    def test_numeric_xctest_values_do_not_receive_contains(self):
        source = (ROOT / 'automation/macos/s01/TrafficLightsUITests.swift').read_text()
        body = source.split('    private func stateLabel()', 1)[1].split('    private func ', 1)[0]
        self.assertNotIn('value CONTAINS', body)
        self.assertIn('as? String', body)


if __name__ == '__main__':
    unittest.main()
