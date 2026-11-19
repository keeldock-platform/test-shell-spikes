"""Run-nine harness regressions; native observations still require hosted execution."""
import ast
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]


def driver_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), path, 'exec'), namespace)
    return namespace


class Node:
    def __init__(self, role, name='', kids=(), text=None, labels=()):
        self.role, self.name, self.kids, self.text, self.labels = role, name, list(kids), text, labels
        self.childCount = len(self.kids)

    def getChildAtIndex(self, index): return self.kids[index]
    def getRoleName(self): return self.role
    def getRelationSet(self):
        labels = self.labels
        return [SimpleNamespace(getRelationType=lambda: 3, getNTargets=lambda: len(labels),
                                getTarget=lambda i: SimpleNamespace(name=labels[i]))]
    def queryEditableText(self):
        if self.text is None: raise ValueError('not editable')
        return self
    def queryText(self):
        if self.text is None: raise ValueError('no text')
        return SimpleNamespace(characterCount=len(self.text), getText=lambda a, b: self.text)
    def getState(self): return SimpleNamespace(contains=lambda _: True)
    def queryComponent(self): return SimpleNamespace(grabFocus=lambda: True)


class RunNineProbes(unittest.TestCase):
    def test_android_wrapper_refuses_missing_generated_files_before_gradle(self):
        source = (ROOT / 'ci/generate-mobile-projects.sh').read_text()
        guard = source.split("<<'PYGUARD'\n", 1)[1].split('\nPYGUARD', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            wrapper = project / 'gradlew'
            wrapper.write_text('#!/bin/sh\necho REAL_GRADLE_CALLED\n')
            subprocess.run([sys.executable, '-c', guard, str(wrapper)], check=True)
            result = subprocess.run(['sh', str(wrapper)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 78)
            self.assertNotIn('REAL_GRADLE_CALLED', result.stdout)
            (project / 'tauri.settings.gradle').write_text("include ':tauri-android'\n")
            result = subprocess.run(['sh', str(wrapper)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 78)
            (project / 'app').mkdir()
            (project / 'app/tauri.build.gradle.kts').write_text('dependencies {}\n')
            result = subprocess.run(['sh', str(wrapper)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('REAL_GRADLE_CALLED', result.stdout)
            self.assertIn('Android pre-Gradle generated input', result.stdout)
        self.assertNotIn('shellDependencyProbe buildEnvironment', source)
        runner = (ROOT / 'ci/run-platform.py').read_text()
        self.assertLess(runner.index('["cargo", "tauri", "android", "build"'),
                        runner.index('["bash", "ci/probe-android-generated.sh"]'))

    def test_ubuntu_mirror_rotation_preserves_suites_and_vendor_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources.list.d').mkdir()
            ubuntu = root / 'sources.list.d/ubuntu.sources'
            ubuntu.write_text('URIs: http://archive.ubuntu.com/ubuntu/\nSuites: resolute resolute-updates resolute-security\nComponents: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n')
            vendor = root / 'sources.list.d/vendor.list'
            vendor.write_text('deb https://example.org/packages stable main\n')
            for index, mirror in enumerate(('archive.ubuntu.com', 'mirrors.edge.kernel.org', 'mirrors.mit.edu')):
                result = subprocess.run(['bash', str(ROOT / 'ci/apt-mirror.sh'), str(index), tmp], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('http://' + mirror + '/ubuntu/', ubuntu.read_text())
                self.assertIn('Suites: resolute resolute-updates resolute-security', ubuntu.read_text())
                self.assertIn('Signed-By:', ubuntu.read_text())
                self.assertIn('resolved Ubuntu mirror', result.stdout)
            self.assertEqual(vendor.read_text(), 'deb https://example.org/packages stable main\n')

    def test_gtk_external_dialog_relation_label_and_commit_are_used(self):
        field = Node('text', text='#336699', labels=('Color name',))
        select = Node('push button', 'Select')
        dialog = Node('dialog', 'Select a Color', (field, select))
        page_hex = Node('entry', 'HEX', text='#336699')
        page = Node('dialog', 'Appearance colour', (page_hex,))
        desktop = Node('desktop', kids=(Node('application', kids=(page,)), Node('application', kids=(dialog,))))
        with tempfile.TemporaryDirectory() as tmp:
            clock = Mock(); clock.monotonic.side_effect = range(100)
            press = Mock(return_value=True)
            ns = dict(all_desktop=desktop, pyatspi=SimpleNamespace(STATE_SHOWING=1, RELATION_LABELLED_BY=3),
                      recorder=Path(tmp), time=clock, json=__import__('json'), log=Mock(), press=press,
                      replace_focused_text=lambda value: setattr(field, 'text', value),
                      input_key=Mock(), is_wayland=True, subprocess=subprocess)
            names = {'children', 'walk', 'label', 'editable', 'native_dialogs', 'native_nodes', 'field_label', 'type_native_colour'}
            driver_functions('automation/linux/s10/drive.py', names, ns)
            self.assertTrue(ns['type_native_colour']('#7C4DFF'))
            press.assert_called_once_with(select)
            self.assertEqual(page_hex.text, '#336699')
            self.assertEqual(field.text, '#7C4DFF')
            # Removing the native dialog must never make the page HEX input count.
            desktop.kids.pop(); desktop.childCount = 1
            self.assertFalse(ns['type_native_colour']('#28A77A'))

    def test_marker_query_rejects_the_container_that_failed_run_nine(self):
        source = (ROOT / 'automation/macos/s01/TrafficLightsUITests.swift').read_text()
        pattern = re.search(r'"label MATCHES %@", "([^"]+)"', source).group(1)
        self.assertFalse(re.fullmatch(pattern, 'S01 traffic light positioning probe'))
        self.assertTrue(re.fullmatch(pattern, 'S01 000001 SETTLED'))
        self.assertTrue(re.fullmatch(pattern, 'S01 000002 APPLYING'))
        self.assertIn('sequence > afterSequence', source)

    def test_screencast_rejects_failed_and_escaping_results(self):
        ns = driver_functions('ci/recorders/gnome-screencast.py', {'validate_result'}, {'Path': Path})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(ns['validate_result'](True, str(root / 'capture.webm'), root), root / 'capture.webm')
            for success, path in ((False, root / 'capture.webm'), (True, root / '../escape.webm'),
                                  (True, Path('relative.webm')), (True, root / 'capture.mkv')):
                with self.subTest(success=success, path=path), self.assertRaises(ValueError):
                    ns['validate_result'](success, str(path), root)

    def test_screencast_start_and_stop_keep_the_same_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bus = Mock()
            bus.call_sync.return_value.unpack.return_value = (True, str(root / 'capture.webm'))
            bus.get_unique_name.return_value = ':1.42'
            loop = Mock()
            glib = SimpleNamespace(Variant=lambda *args: args, VariantType=SimpleNamespace(new=lambda value: value),
                                   MainLoop=lambda: loop, unix_signal_add=Mock(), PRIORITY_DEFAULT=0)
            gio = SimpleNamespace(bus_get_sync=Mock(return_value=bus), BusType=SimpleNamespace(SESSION=0),
                                  DBusCallFlags=SimpleNamespace(NONE=0))
            ns = driver_functions('ci/recorders/gnome-screencast.py', {'validate_result', 'main'},
                                  dict(Path=Path, Gio=gio, GLib=glib, signal=__import__('signal'),
                                       sys=SimpleNamespace(argv=['recorder', 'capture-%d.webm', str(root / 'ready'), tmp])))
            self.assertEqual(ns['main'](), 0)
            gio.bus_get_sync.assert_called_once()
            self.assertEqual([call.args[3] for call in bus.call_sync.call_args_list], ['Screencast', 'StopScreencast'])
            loop.run.assert_called_once()
            self.assertEqual((root / 'ready').read_text().strip(), str(root / 'capture.webm'))

    def test_windows_element_return_does_not_include_progress_sequence(self):
        source = (ROOT / 'automation/windows/s02/run.ps1').read_text()
        wait = source.split('function Wait-ActiveMenu', 1)[1].split('\nfunction ', 1)[0]
        self.assertIn('$null = Write-Event', wait)
        self.assertNotRegex(source, r'(?m)^\s*Write-Event ')
        self.assertNotIn('.FindAll(', source)
        self.assertIn("@('HTMAXBUTTON-hover', 'Win+Z')", source)
        self.assertIn("$trigger -ne 'HTMAXBUTTON-hover' -or $hit -ne 9", source)
        self.assertIn('Keyboard-only evidence does not satisfy the hover assertion.', source)
        helper = (ROOT / 'automation/windows/ScopedUia.cs').read_text()
        self.assertIn('done.Wait(750)', helper)
        self.assertIn('worker.IsBackground = true', helper)
        self.assertIn('nodes.Count >= maxNodes', helper)


if __name__ == '__main__':
    unittest.main()
