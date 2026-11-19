"""Run-six regression probes; fixtures do not claim hosted GUI observations."""
import importlib.util
import json
import os
import plistlib
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ci"))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


collector = module("collector12", "ci/collect.py")
case = module("case12", "ci/run_case.py")
platform = module("platform12", "ci/run-platform.py")
linux = module("linux12", "automation/linux/s03/probe.py")


class RunSixProbes(unittest.TestCase):
    @unittest.skipUnless(shutil.which("swift"), "Swift is unavailable on this host")
    def test_macos_description_text_wins_over_empty_value(self):
        source = (ROOT / "automation/macos/s08/probe.swift").read_text()
        helper = source[source.index("func matchingAccessibilityText("):source.index("func attribute(")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.swift"
            path.write_text(helper + '''
precondition(matchingAccessibilityText(["", nil, "Pose: S08-MAIN"], containing: "Pose:") == "Pose: S08-MAIN")
precondition(matchingAccessibilityText(["", "unrelated", nil], containing: "Pose:") == nil)
precondition(matchingAccessibilityText(["", "Native geometry: settings 1040×660 logical points"], containing: "Native geometry: settings ") != nil)
''')
            subprocess.run(["swift", "-module-cache-path", str(Path(tmp) / "cache"), str(path)], check=True, capture_output=True, timeout=120)

    def test_macos_virtual_display_does_not_require_system_profiler_adapter(self):
        native = module("native12", "ci/native_preflight.py")
        measurement = {"resolution": "1280x800", "scale": 1, "refreshHz": 60}
        def command(args, **kwargs):
            return json.dumps(measurement) if args[0] == "fixture-probe" else '{"SPDisplaysDataType": []}'
        with patch.dict(os.environ, {"SHELL_MAC_DISPLAY_PROBE": "fixture-probe"}), patch.object(native, "command", side_effect=command):
            display, raw = native.display_macos()
            self.assertEqual(display, measurement)
            self.assertEqual(raw["nativeDisplay"], measurement)

    def test_windows_call_contract_has_no_automatic_pid_parameter(self):
        # PowerShell parameter binding is case-insensitive: $Pid is read-only.
        source = (ROOT / "automation/windows/s02/run.ps1").read_text()
        self.assertIsNone(re.search(r"\$pid\b", source, re.I))
        for lane in ("s10", "s11"):
            source = (ROOT / f"automation/windows/{lane}/run.ps1").read_text()
            self.assertRegex(source, r"param\(\[string\]\$CaseId")
            self.assertIn("--case-id $CaseId", source)

    def test_xctest_scheme_uses_its_declared_environment(self):
        projects = module("projects12", "ci/generate-native-test-projects.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Fixture.app"
            (app / "Contents").mkdir(parents=True)
            for path in (app / "Info.plist", app / "Contents/Info.plist"):
                path.write_bytes(plistlib.dumps({"CFBundleIdentifier": "org.example.fixture"}))
            with patch.object(projects, "ROOT", root), patch.dict(os.environ, {"SHELL_APP_PATH": str(app), "S01_APP_BUNDLE_ID": "org.example.fixture"}):
                for target, suite in (("macos", "s01"), ("ios", "s10"), ("ios", "s11")):
                    projects.project_for(target, suite)
            for path in root.rglob("*.xcscheme"):
                action = ET.parse(path).getroot().find("TestAction")
                self.assertEqual(action.get("shouldUseLaunchSchemeArgsEnv"), "NO")
                entries = {row.get("key"): row.get("value") for row in action.findall("EnvironmentVariables/EnvironmentVariable")}
                self.assertEqual(entries["SHELL_CASE_ID"], "$(SHELL_CASE_ID)")

    def test_collector_ingests_cell_once_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "download" / "shell-spikes-sha-linux-all-cases"
            cell_dir = artifact / "cells" / "linux-ubuntu-24.04-x11"
            cell_dir.mkdir(parents=True)
            env = {"cell": "linux-ubuntu-24.04-x11", "sourceSha": "a" * 40}
            row = {"spike": "s03", "caseId": "S03-UBUNTU-24.04-X11",
                   "id": "fixture", "verdict": "UNVERIFIED", "evidence": []}
            for directory in (artifact, cell_dir):
                (directory / "environment.json").write_text(json.dumps(env))
                (directory / "assertions.json").write_text(json.dumps({"sourceSha": "a" * 40, "results": [row]}))
            case.write_hashes(artifact)
            self.assertEqual(collector.audit_hashes(artifact)["errors"], [])
            with patch.object(sys, "argv", ["collect.py", "--input", str(root / "download"), "--output", str(root / "out"), "--expected-sha", "a" * 40]):
                collector.main()
            summary = json.loads((root / "out/result-matrix.json").read_text())
            self.assertEqual(len(summary["ingestion"]), 1)
            self.assertEqual(summary["ingestion"][0]["parsedResults"], 1)
            (cell_dir / "assertions.json").write_text('{}')
            self.assertIn("hash mismatch", collector.audit_hashes(artifact)["errors"][0])
            # The upload boundary must seal after the final process/log write.
            env_file = root / "github-env"
            subprocess.run([sys.executable, str(ROOT / "ci/hash-evidence.py")],
                           env={**os.environ, "SHELL_EVIDENCE_DIR": str(artifact),
                                "GITHUB_ENV": str(env_file), "RUNNER_TEMP": str(root)},
                           check=True, capture_output=True)
            snapshot = Path(env_file.read_text().strip().split("=", 1)[1])
            self.assertEqual(collector.audit_hashes(snapshot)["errors"], [])
            (cell_dir / "assertions.json").write_text('{"late":true}')
            self.assertEqual(collector.audit_hashes(snapshot)["errors"], [])

    def test_linux_probe_envelope_survives_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s03-assertions.json"
            row = {"id": "s03-fixture", "verdict": "FAIL", "actual": "measured failure"}
            path.write_text(json.dumps({"assertions": [row]}))
            self.assertEqual(case.merge_lane_results(path), [row])

    def test_linux_waits_for_header_without_assuming_atspi_region_role(self):
        # First lookup is empty while the webview starts, then a landmark appears.
        header = object()
        rect = {"x": 1, "y": 2, "width": 30, "height": 40}
        with patch.object(linux, "find_named", side_effect=[(None, None), (header, rect)]) as find, patch.object(linux.time, "sleep"), patch.object(linux, "target_point", side_effect=linux.ProbeUnavailable("reached header")):
            with self.assertRaisesRegex(linux.ProbeUnavailable, "reached header"):
                linux.run_required_cell({"id": "fixture"}, Path("unused"), object(), object())
            self.assertEqual(find.call_count, 2)
            self.assertEqual(len(find.call_args.args), 3)

    def test_ios_passes_resolved_case_as_xcode_build_setting(self):
        for lane in ("colour", "accent"):
            runner = module("runner12_" + lane, f"automation/{lane}/runner.py")
            env = dict(SHELL_IOS_PROJECT="test.xcodeproj", SHELL_IOS_TEST_SCHEME="fixture",
                       SHELL_IOS_DESTINATION="platform=iOS Simulator,id=fixture",
                       SHELL_IOS_XCRESULT_PATH="case.xcresult", SHELL_SPIKE_ID="s11")
            with patch.object(runner.subprocess, "run") as run:
                if lane == "colour":
                    runner.run_native("ios", Path("/tmp/evidence"), "S10-IOS-IPHONE-WKWEBVIEW", env)
                    expected = "S10-IOS-IPHONE-WKWEBVIEW"
                else:
                    runner.run_native("ios", Path("fixture.swift"), "S11-POLICY-IPHONE", Path("/tmp/evidence"), env)
                    expected = "S11-POLICY-IPHONE"
                self.assertIn("SHELL_CASE_ID=" + expected, run.call_args.args[0])

    def test_android_licenses_precede_install_and_failure_stops(self):
        with patch.dict(os.environ, {"ANDROID_HOME": "/tmp/sdk"}), patch.object(platform.shutil, "which", return_value="sdkmanager"), patch.object(platform.subprocess, "run", return_value=subprocess.CompletedProcess([], 9)) as run, patch.object(platform, "execute") as install:
            self.assertEqual(platform.start_android_emulator("31"), 9)
            self.assertEqual(run.call_args.args[0], ["sdkmanager", "--licenses"])
            self.assertIn("y\n", run.call_args.kwargs["input"])
            install.assert_not_called()

    def test_android_shutdown_waits_for_final_log_writes(self):
        from unittest.mock import Mock
        process = Mock()
        with patch.dict(os.environ, {"SHELL_ANDROID_EMULATOR_PID": "123"}), patch.object(platform, "ANDROID_EMULATOR_PROCESS", process), patch.object(platform, "execute", return_value=0):
            self.assertEqual(platform.stop_android_emulator(), 0)
            process.wait.assert_called_once_with(timeout=30)
            self.assertIsNone(platform.ANDROID_EMULATOR_PROCESS)


if __name__ == "__main__":
    unittest.main()
