"""Run-17 failures replayed with fake platform tools; no native PASS claims."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import urllib.error

ROOT = Path(os.environ.get('SHELL_REPLAY_SOURCE', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'ci'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class RunSeventeenReplays(unittest.TestCase):
    def test_fake_lazy_portal_is_activated_and_backend_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, body in [('timeout', 'shift; exec "$@"'), ('sleep', ':'),
                               ('gdbus', 'touch "$REPLAY_ROOT/active"; echo "interface org.freedesktop.portal.Settings"'),
                               ('pgrep', '[[ "$REPLAY_MODE" != no-backend ]]'),
                               ('busctl', '[[ -f "$REPLAY_ROOT/active" ]]')]:
                path = root / name
                path.write_text('#!/bin/bash\n' + body + '\n')
                path.chmod(0o755)
            for mode, expected in [('native', 0), ('no-backend', 78)]:
                (root / 'active').unlink(missing_ok=True)
                result = subprocess.run(['bash', str(ROOT / 'ci/linux/portal-ready.sh'), str(root / 'log')], env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'REPLAY_ROOT': tmp, 'REPLAY_MODE': mode}, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            session = (ROOT / 'ci/linux/session.sh').read_text()
            self.assertGreater(session.index('bash ci/linux/portal-ready.sh'), session.index('dbus-update-activation-environment'))

    def test_fake_gnome_overview_must_settle_before_case_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, body in [('timeout', 'shift; exec "$@"'), ('sleep', ':'),
                               ('gdbus', '''[[ "$*" == *'Main.overview.hide(); !Main.overview.visible && !Main.overview.animationInProgress'* ]] || exit 91
if [[ "$REPLAY_MODE" == settled ]]; then echo "(true, 'true')"; else echo "(true, 'false')"; fi''')]:
                path = root / name
                path.write_text('#!/bin/bash\n' + body + '\n')
                path.chmod(0o755)
            for mode, expected in [('settled', 0), ('overview', 78)]:
                result = subprocess.run(['bash', str(ROOT / 'ci/linux/gnome-normal-mode.sh'), str(root / 'log')],
                                        env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'REPLAY_MODE': mode}, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            session = (ROOT / 'ci/linux/session.sh').read_text()
            self.assertLess(session.index('bash ci/linux/gnome-normal-mode.sh'), session.index('export SHELL_LINUX_SESSION_READY=1'))
            self.assertIn('gnome-shell --x11 --replace --sm-disable --unsafe-mode', session)

    def test_fake_fedora_package_tool_requires_process_observer(self):
        source = (ROOT / 'ci/linux/session.sh').read_text()
        body = source.split('provision_host() {', 1)[1].split('\nrun_in_session()', 1)[0]
        script = '''set -euo pipefail
profile="$REPLAY_PROFILE"; session=wayland; session_slug=wayland
SHELL_LINUX_GUEST=1; diagnostics="$REPLAY_ROOT/provision.json"
record_status() { :; }
bash() { case "$*" in *'install -y'*) [[ " $* " == *" $REPLAY_PACKAGE "* ]] ;; *) : ;; esac; }
python3() { cat >/dev/null; }
gnome-shell() { echo 'GNOME Shell fixture'; }
pkg-config() { echo fixture; }
ffmpeg() { echo fixture; }
rpm() { :; }
dpkg-query() { :; }
apt-cache() { :; }
sudo() { :; }
''' + 'provision_host() {' + body + '\nprovision_host\n'
        with tempfile.TemporaryDirectory() as tmp:
            for profile, package in [('Fedora current', 'procps-ng'), ('Ubuntu 24.04', 'procps')]:
                result = subprocess.run(['bash', '-c', script], env={**os.environ, 'REPLAY_ROOT': tmp, 'REPLAY_PROFILE': profile, 'REPLAY_PACKAGE': package}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_fake_gradle_requires_androidx_and_preserves_properties(self):
        pin = module('pin20', 'ci/pin-android-gradle.py')
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for folder in ('buildSrc', 'app', 'gradle/wrapper'):
                (project / folder).mkdir(parents=True)
            (project / 'build.gradle.kts').write_text('classpath("com.android.tools.build:gradle:9.3.1")\nclasspath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.2.21")')
            (project / 'buildSrc/build.gradle.kts').write_text('implementation("com.android.tools.build:gradle:9.3.1")')
            (project / 'gradle/wrapper/gradle-wrapper.properties').write_text('distributionUrl=old\n')
            properties = project / 'gradle.properties'
            properties.write_text('org.gradle.configuration-cache=true\nandroid.useAndroidX=false\n')
            pin.pin(project, '2.2.21')
            pin.pin(project, '2.2.21')
            fake = project / 'fake-gradle.py'
            fake.write_text('from pathlib import Path\ns=Path("gradle.properties").read_text()\nassert s.count("android.useAndroidX=true")==1, "AndroidX property is not enabled"\nassert "android.useAndroidX=false" not in s\nassert "org.gradle.configuration-cache=true" in s\n')
            result = subprocess.run([sys.executable, str(fake)], cwd=project, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_fake_maven_negative_cache_recovers_same_coordinate(self):
        probe = module('probe20', 'ci/probe-android-dependencies.py')
        url = 'https://repo.maven.apache.org/maven2/fixed/version.pom'
        requests = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'coordinate'
        def open_url(request, **kwargs):
            requested = request.full_url if hasattr(request, 'full_url') else request
            requests.append(requested)
            if '?' not in requested:
                raise urllib.error.HTTPError(requested, 404, 'cached Not Found', {}, None)
            self.assertEqual(requested.split('?')[0], url)
            return Response()
        with patch.object(probe.urllib.request, 'urlopen', open_url), patch.object(probe.time, 'sleep'):
            self.assertEqual(probe.fetch(url, 1024), b'coordinate')
        self.assertEqual(len(requests), 2)
        with patch.object(probe.urllib.request, 'urlopen', side_effect=OSError('unavailable')) as request, patch.object(probe.time, 'sleep'):
            with self.assertRaises(ValueError): probe.fetch(url, 1024)
            self.assertEqual(request.call_count, 3)

    def test_fake_uploader_retains_all_hashed_bytes(self):
        seal = module('seal20', 'ci/hash-evidence.py')
        workflow = (ROOT / '.github/workflows/shell-spikes.yml').read_text()
        uploads = re.findall(r'path: \$\{\{ env.SHELL_UPLOAD_DIR \}\}([^\n]*(?:\n          [^\n]+)*)', workflow)
        self.assertTrue(uploads)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source / '.goutputstream-VFT0Y3').write_text('unfinished atomic save')
            (source / '.native-observation.json').write_text('{"observed":true}')
            (source / 'screen.png').write_bytes(b'capture')
            sealed = seal.seal(source, root / 'sealed')
            self.assertFalse((sealed / '.goutputstream-VFT0Y3').exists())
            self.assertTrue((sealed / '.native-observation.json').exists())
            for upload in uploads:
                include_hidden = 'include-hidden-files: true' in upload
                uploaded = {p.relative_to(sealed).as_posix() for p in sealed.rglob('*')
                            if p.is_file() and (include_hidden or not p.name.startswith('.'))}
                for line in (sealed / 'hashes.sha256').read_text().splitlines():
                    self.assertIn(line.partition('  ')[2], uploaded)

    def test_stubborn_session_children_are_killed_and_reaped(self):
        source = (ROOT / 'ci/linux/session.sh').read_text()
        body = source.split('    stop_capture_services() {', 1)[1].split('\n    trap stop_capture_services EXIT', 1)[0]
        helper = ROOT / 'ci/linux/stop-owned.sh'
        prefix = ('source ' + str(helper) + '\n') if helper.exists() else ''
        script = '''set -euo pipefail
declare -a stopped=()
kill() { case "$1" in -KILL) stopped[$2]=1;; -0) [[ "${stopped[$2]:-}" != 1 ]];; *) :;; esac; }
wait() { [[ "${stopped[$1]:-}" == 1 ]]; }
sleep() { :; }
timeout() { shift; "$@"; }
sudo() { :; }
shell_pid=11; input_daemon_pid=12; screencast_pid=13; wireplumber_pid=14; pipewire_pid=15
''' + prefix + 'stop_capture_services() {' + body + '\nstop_capture_services\nfor pid in 11 12 13 14 15; do [[ "${stopped[$pid]:-}" == 1 ]]; done\n'
        result = subprocess.run(['bash', '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fake_uia_provider_is_scoped_to_owned_hwnd(self):
        # Model the observed unrelated desktop provider that never answers.
        # Structural replay only: C#/Win32 execution remains a hosted check.
        source = (ROOT / 'automation/windows/ScopedUia.cs').read_text()
        body = source.split('WindowForPid(int processId)', 1)[1].split('public static AutomationElement.AutomationElementInformation', 1)[0]
        calls = []
        def provider(target):
            calls.append(target)
            if target == 'desktop': raise TimeoutError('top-level-window')
            return {'hwnd': 123, 'pid': 42}
        if 'RootElement.FindFirst' in body:
            value = provider('desktop')
        else:
            self.assertIn('process.MainWindowHandle', body)
            self.assertIn('AutomationElement.FromHandle(handle)', body)
            value = provider('owned-hwnd')
        self.assertEqual(value['pid'], 42)
        self.assertEqual(calls, ['owned-hwnd'])
        self.assertIn('done.Wait(750)', source)
        driver = (ROOT / 'automation/windows/s02/run.ps1').read_text()
        menu = driver.split('function Find-ActiveMenu', 1)[1].split('function Get-MenuItems', 1)[0]
        self.assertNotIn('RootElement', menu)
        self.assertIn('NativeMenus()', menu)

    def test_real_case_tree_and_window_geometry_are_attached(self):
        case = module('case20', 'ci/run_case.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = root / 'spikes/s02/case'
            (scenario / 'native-tree').mkdir(parents=True)
            (scenario / 'recorder').mkdir()
            tree = scenario / 'native-tree/case-menu.json'
            tree.write_text('{"name":"System","items":["Close"]}')
            (scenario / 'events.jsonl').write_text(json.dumps({'name': 'menu-opened', 'data': {'menuBounds': {'x': 1, 'y': 2, 'width': 3, 'height': 4}}}) + '\n')
            case.materialize_s02_geometry(scenario)
            rows = case.attach_case_evidence([{'id':'observed','verdict':'FAIL'}], [{'id':'observed','evidence':['native-tree','geometry-json']}], scenario, root)
            self.assertIn('spikes/s02/case/native-tree/case-menu.json', rows[0]['evidence'])
            self.assertIn('spikes/s02/case/recorder/geometry.json', rows[0]['evidence'])
            self.assertEqual(rows[0]['verdict'], 'FAIL')

    def test_ios_main_queue_and_s01_stable_queries(self):
        ios = (ROOT / 'automation/ios/DisplayProbe.swift').read_text()
        self.assertIn('DispatchQueue.main.sync', ios)
        self.assertIn('screenshot.image.cgImage', ios)
        self.assertIn('"resolution": "\\(pixels.width)x\\(pixels.height)"', ios)
        self.assertNotIn('guard Thread.isMainThread else { return }', ios)
        mac = (ROOT / 'automation/macos/s01/TrafficLightsUITests.swift').read_text()
        body = mac.split('private func stateLabel()', 1)[1].split('private func ', 1)[0]
        self.assertNotIn('allElementsBoundByIndex', body)
        self.assertIn('label BEGINSWITH', body)
        self.assertIn('as? String', body)

    def test_fake_portal_and_raw_renderer_events_produce_native_verdicts(self):
        case_id = 'S11-LINUX-FEDORA-CURRENT'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for name, fields in [('s11.reader-ready', {'available': True}),
                                 ('s11.initial-reader-snapshot', {'rgb': [0.1, 0.2, 0.3]}),
                                 ('s11.native-event', {'sequence': 1, 'rgb': [0.5, 0.25, 0.75]}),
                                 ('s11.host-and-token-update', {'sequence': 1, 'reload': False})]:
                rows.append({'hostPid': 42, 'caseId': case_id, 'detail': {'name': name, 'fields': fields}})
            (root / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            def fake_tool(command, **kwargs):
                if 'linux-probe.sh' in ' '.join(command):
                    return SimpleNamespace(returncode=0, stdout='gnome_accent_key=present\n.Read method ss v deprecated\n(<<(0.1, 0.2, 0.3)>>,)\n', stderr='')
                return SimpleNamespace(returncode=0, stdout='(<<(0.5, 0.25, 0.75)>>,)\n', stderr='')
            previous = Path.cwd()
            try:
                os.chdir(ROOT)
                with patch.object(sys, 'argv', ['drive.py', case_id, str(root)]), patch.dict(os.environ, {'SHELL_APP_PID': '42'}), patch('subprocess.run', fake_tool):
                    runpy.run_path(str(ROOT / 'automation/linux/s11/drive.py'))
            finally:
                os.chdir(previous)
            observed = json.loads((root / 'recorder/observations.json').read_text())['assertions']
            for suffix in ('PROBE', 'LIVE-READBACK', 'LIVE-EVENT', 'LIVE-UPDATE'):
                self.assertEqual(observed['S11-LINUX-FEDORA-CURRENT-' + suffix]['verdict'], 'PASS')
            self.assertEqual(observed['S11-LINUX-FEDORA-CURRENT-LIVE-FRAME']['verdict'], 'UNVERIFIED')
            self.assertEqual(observed['S11-LINUX-FEDORA-CURRENT-FALLBACK']['verdict'], 'UNVERIFIED')
            self.assertEqual(json.loads((root / 'recorder/native-readback.json').read_text())['rgb'], [0.5, 0.25, 0.75])

    def test_portal_parser_rejects_errors_and_invalid_triples(self):
        path = ROOT / 'automation/linux/s11/drive.py'
        function = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'portal_rgb_from_output')
        ns = {'re': re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), ns)
        for text in ('Error: key not found', '(<<(2.0, 0.2, 0.3)>>,)', '(<<"(0.1, 0.2, 0.3)">>,)', 'error (0.1, 0.2, 0.3)'):
            self.assertIsNone(ns['portal_rgb_from_output'](text))


if __name__ == '__main__':
    unittest.main()
