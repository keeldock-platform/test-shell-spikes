#!/usr/bin/env python3
"""Launch the real shell, run the platform's native picker driver, and serialize results."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation"))
from native_runtime import run_android, stop_desktop

DRIVERS = {
    "macos": ROOT / "automation/macos/s10/drive.swift",
    "windows": ROOT / "automation/windows/s10/drive.ps1",
    "linux": ROOT / "automation/linux/s10/drive.py",
    "ios": ROOT / "automation/ios/s10/ColourUITests.swift",
    "android": ROOT / "automation/android/s10/ColourUiAutomator.java",
}


def write_status(evidence: Path, platform: str, case_id: str, cell: str, reason: str):
    subprocess.run([
        sys.executable, str(ROOT / "automation/colour/driver-status.py"),
        "--platform", platform, "--case", case_id, "--cell", cell,
        "--reason", reason, "--evidence-dir", str(evidence),
    ], check=True)


def launch_desktop(platform: str, app: Path, env: dict[str, str]):
    if platform == "macos" and app.suffix == ".app":
        plist = app / "Contents/Info.plist"
        executable_name = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print CFBundleExecutable", str(plist)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        env["SHELL_APP_BUNDLE_ID"] = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print CFBundleIdentifier", str(plist)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        executable = app / "Contents/MacOS" / executable_name
        return subprocess.Popen([str(executable)], env=env, start_new_session=True)
    return subprocess.Popen([str(app)], env=env, start_new_session=True)


def run_native(platform: str, evidence: Path, case_id: str, env: dict[str, str]):
    driver = DRIVERS[platform]
    if not driver.is_file():
        raise FileNotFoundError(f"Native driver source is missing for {platform}.")
    if platform == "macos":
        return subprocess.run(["swift", str(driver), case_id, str(evidence)], env=env, timeout=240)
    if platform == "windows":
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver), case_id, str(evidence)], env=env, timeout=240)
    if platform == "linux":
        return subprocess.run([sys.executable, str(driver), case_id, str(evidence)], env=env, timeout=240)
    if platform == "ios":
        project = env.get("SHELL_IOS_PROJECT")
        scheme = env.get("SHELL_IOS_TEST_SCHEME")
        destination = env.get("SHELL_IOS_DESTINATION")
        result_bundle = env.get("SHELL_IOS_XCRESULT_PATH")
        if not (project and scheme and destination and result_bundle):
            raise RuntimeError("The coordinator must provide the unsigned simulator test project, scheme, and destination.")
        return subprocess.run([
            "xcodebuild", "test", "-project", project, "-scheme", scheme,
            "-destination", destination, "-resultBundlePath", result_bundle, "CODE_SIGNING_ALLOWED=NO",
            *[f"{key}={value}" for key, value in {**env, "SHELL_CASE_ID": case_id, "SHELL_EVIDENCE_DIR": str(evidence)}.items()
              if key in {"SHELL_SPIKE_ID", "SHELL_CASE_ID", "SHELL_EVIDENCE_DIR",
                         "SHELL_MOBILE_EVIDENCE_SUBPATH", "SHELL_MOBILE_BUNDLE_ID", "SHELL_IOS_XCRESULT_PATH"}],
            "-only-testing:ColourUITests/ColourUITests/testNativeColourInput",
        ], env={**env, "SHELL_CASE_ID": case_id, "SHELL_EVIDENCE_DIR": str(evidence)}, timeout=900)
    return run_android("s10", "ColourUiAutomator#testNativePicker", case_id, evidence, env)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=DRIVERS)
    parser.add_argument("--case-id", default=os.environ.get("SHELL_CASE_ID"))
    args = parser.parse_args()
    evidence_arg = os.environ.get("SHELL_EVIDENCE_DIR")
    case_id = args.case_id
    cell = os.environ.get("SHELL_CELL", "unspecified")
    if not case_id or not evidence_arg:
        parser.error("SHELL_CASE_ID and SHELL_EVIDENCE_DIR are required.")
    evidence = Path(evidence_arg)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "recorder").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"SHELL_SPIKE_ID": "s10", "SHELL_CASE_ID": case_id,
                "SHELL_CELL": cell, "SHELL_EVIDENCE_DIR": str(evidence)})

    for marker in ("shutdown-request", "shutdown-flushed"):
        (evidence / "recorder" / marker).unlink(missing_ok=True)
    desktop_process = None
    try:
        if args.platform in {"macos", "windows", "linux"}:
            app_path = env.get("SHELL_APP_PATH")
            if not app_path:
                raise RuntimeError("SHELL_APP_PATH is required to launch the test shell.")
            desktop_process = launch_desktop(args.platform, Path(app_path), env)
            env["SHELL_APP_PID"] = str(desktop_process.pid)
            (evidence / "recorder/desktop-process.json").write_text(json.dumps({"pid": desktop_process.pid}))
            time.sleep(2)
        result = run_native(args.platform, evidence, case_id, env)
        if result.returncode != 0:
            write_status(evidence, args.platform, case_id, cell,
                         f"Native driver exited with status {result.returncode}; picker outcome is unverified.")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        write_status(evidence, args.platform, case_id, cell,
                     f"Native driver unavailable: {type(error).__name__}: {error}")
    finally:
        stop_desktop(desktop_process, evidence)
        subprocess.run([
            sys.executable, str(ROOT / "automation/colour/result-envelope.py"),
            "--case-file", str(ROOT / "cases/s10.json"), "--case-id", case_id,
            "--evidence-dir", str(evidence), "--output", str(evidence / "assertions.json"),
        ], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
