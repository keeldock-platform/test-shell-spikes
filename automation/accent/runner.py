#!/usr/bin/env python3
"""Launch the shell, exercise a platform accent source, and serialize every case row."""

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
from native_runtime import run_android, stop_desktop, wait_desktop_ready

DRIVERS = {
    "macos": ROOT / "automation/macos/s11/drive.swift",
    "windows": ROOT / "automation/windows/s11/drive.ps1",
    "linux": ROOT / "automation/linux/s11/drive.py",
    "ios": ROOT / "automation/ios/s11/AccentUITests.swift",
    "android": ROOT / "automation/android/s11/AccentUiAutomator.java",
}


def write_status(evidence: Path, platform: str, case_id: str, cell: str, reason: str):
    subprocess.run([
        sys.executable, str(ROOT / "automation/accent/driver-status.py"),
        "--platform", platform, "--case", case_id, "--cell", cell,
        "--reason", reason, "--evidence-dir", str(evidence),
    ], check=True)


def analyze_android_events(evidence: Path, case_id: str):
    event_file = evidence / "events.jsonl"
    observations_file = evidence / "recorder" / "observations.json"
    if not observations_file.is_file():
        return
    try:
        events = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines() if line.strip()] if event_file.is_file() else []
        observations = json.loads(observations_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if case_id == "S11-ANDROID-API-30-NEGATIVE":
        facts = observations.get("api30Facts", {})
        ready = observations.get("ready") is True and facts.get("apiLevel") == 30
        hidden = (ready and facts.get("systemHidden") is True and facts.get("reason") == "api-below-31"
                  and facts.get("storedAccent") == "system" and facts.get("resolvedSource") == "brand"
                  and facts.get("appliedHex", "").upper() == "#405066" and facts.get("dynamicResourceRead") is False)
        prompt = ready and facts.get("promptSamples", 0) >= 10 and facts.get("promptObserved") is False
        for suffix, passed in [("HIDDEN", hidden), ("PROMPT", prompt)]:
            key = "S11-ANDROID-API-30-" + suffix
            observations.setdefault("assertions", {})[key] = {
                "verdict": "PASS" if passed else "UNVERIFIED", "actual": f"API 30 observed {suffix.lower()}={passed}; facts={facts}",
                "evidence": ["recorder/observations.json", "recorder/native-tree-before.xml"]
                    + ([f"recorder/prompt-window-{sample}.xml" for sample in range(10)] if suffix == "PROMPT" else []),
            }
        observations_file.write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
        return

    def name(row):
        return row.get("name") or row.get("event") or (row.get("fields") or {}).get("name", "")
    def fields(row):
        return row.get("fields") if isinstance(row.get("fields"), dict) else row
    # Preserve event order; a sequence alone is insufficient proof of a delivery.
    native = [fields(row) for row in events if name(row) == "s11.native-event"]
    updates = [fields(row) for row in events if name(row) == "s11.host-and-token-update"]
    status = [fields(row) for row in events if name(row) == "s11.reader-status"]
    assertions = observations.setdefault("assertions", {})
    initial = next((fields(row) for row in events if name(row) == "s11.initial-reader-snapshot"), None)
    recreate = next((row for row in status if row.get("cause") == "activity-recreated-read"), None)
    def fingerprint(row):
        return (row.get("wallpaperId"), row.get("resourceArgb"))
    def delivered(row):
        sequence = row.get("sequence")
        hosts = [host for host in updates if host.get("sequence") == sequence]
        callbacks = [event for event in native if event.get("sequence") == sequence]
        return (isinstance(sequence, int) and sequence > 0 and len(callbacks) == len(hosts) == 1
                and row.get("cause") in {"wallpaper-callback", "configuration-changed"}
                and row.get("wallpaperId") is not None and row.get("resourceArgb") is not None
                and fingerprint(hosts[0]) == fingerprint(row)
                and hosts[0].get("activityGeneration") == row.get("activityGeneration")
                and bool(hosts[0].get("appliedHex"))
                and events.index(next(event for event in events if fields(event) is row))
                    < events.index(next(event for event in events if fields(event) is hosts[0])))
    matched_native = [row for row in native if delivered(row)]
    matched = [host for host in updates if any(host.get("sequence") == row.get("sequence") for row in matched_native)]
    first = next((row for row in matched_native if initial
                  and row.get("sequence", 0) > initial.get("sequence", 0)
                  and fingerprint(row) != fingerprint(initial)
                  and row.get("activityGeneration") == initial.get("activityGeneration")), None)
    wallpaper = case_id + "-WALLPAPER"
    if wallpaper in assertions:
        assertions[wallpaper] = {
            "verdict": "PASS" if first else "UNVERIFIED",
            "actual": "Changed wallpaper/resource callback and exactly one matching host token delivery observed." if first else "Changed wallpaper readback alone is insufficient; complete callback and host delivery are absent.",
            "evidence": ["events.jsonl", "recorder/wallpaper-readback.txt"],
        }
    second = next((row for row in matched_native if recreate and first
                   and recreate.get("sequence", 0) > first.get("sequence", 0)
                   and row.get("sequence", 0) > recreate.get("sequence", 0)
                   and row.get("activityGeneration") == recreate.get("activityGeneration")
                   and fingerprint(recreate) == fingerprint(first)
                   and fingerprint(row) != fingerprint(recreate)), None)
    target = case_id + "-RECREATE"
    if target in assertions:
        complete = bool(initial and recreate and second
                        and recreate.get("nativeEvent") is False
                        and isinstance(initial.get("activityGeneration"), int)
                        and isinstance(recreate.get("activityGeneration"), int)
                        and recreate["activityGeneration"] > initial["activityGeneration"])
        assertions[target] = {
            "verdict": "PASS" if complete else "UNVERIFIED",
            "actual": "Generation advanced, recreation reread the current resource, and a second changed wallpaper callback reached the host exactly once." if complete else "Generation advance, non-native reread and second post-recreation callback/host delivery are not all verified.",
            "evidence": ["events.jsonl", "recorder/native-tree-after-recreation.xml", "recorder/wallpaper-readback.txt"],
        }
    target = case_id + "-FRAME"
    if target in assertions:
        assertions[target] = {
            "verdict": "UNVERIFIED",
            "actual": f"Native events={len(native)}; sequence-matched host updates={len(matched)}; no visible first-frame index was joined.",
            "evidence": ["events.jsonl", "video/android.mp4"],
        }
    target = case_id + "-IDENTITY"
    if target in assertions:
        matching_identity = any(row.get("identityHex") == "#6B5B45" for row in matched)
        assertions[target] = {
            "verdict": "PASS" if matching_identity else "UNVERIFIED",
            "actual": "Independent identity sample #6B5B45 observed in a callback-correlated host update." if matching_identity else "No callback-correlated identity update was observed.",
            "evidence": ["events.jsonl", "recorder/native-tree-before.xml", "video/android.mp4"],
        }
    observations_file.write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")


def launch_desktop(platform: str, app: Path, env: dict[str, str]):
    if platform == "macos" and app.suffix == ".app":
        executable_name = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print CFBundleExecutable", str(app / "Contents/Info.plist")],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        with (Path(env["SHELL_EVIDENCE_DIR"]) / "recorder/desktop-launch.log").open("w") as log:
            return subprocess.Popen([str(app / "Contents/MacOS" / executable_name)], env=env, start_new_session=True, stdout=log, stderr=subprocess.STDOUT)
    with (Path(env["SHELL_EVIDENCE_DIR"]) / "recorder/desktop-launch.log").open("w") as log:
        return subprocess.Popen([str(app)], env=env, start_new_session=True, stdout=log, stderr=subprocess.STDOUT)


def run_native(platform: str, driver: Path, case_id: str, evidence: Path, env: dict[str, str]):
    if platform == "macos":
        return subprocess.run(["swift", str(driver), case_id, str(evidence)], env=env, timeout=360)
    if platform == "windows":
        return subprocess.run(["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver), case_id, str(evidence)], env=env, timeout=360)
    if platform == "linux":
        return subprocess.run([sys.executable, str(driver), case_id, str(evidence)], env=env, timeout=360)
    if platform == "ios":
        if "POLICY" not in case_id:
            raise RuntimeError("Mobile accent reading is deliberately unavailable on iOS; System is hidden and stored values resolve to the test brand colour.")
        project, scheme, destination = (env.get("SHELL_IOS_PROJECT"), env.get("SHELL_IOS_TEST_SCHEME"), env.get("SHELL_IOS_DESTINATION"))
        result_bundle = env.get("SHELL_IOS_XCRESULT_PATH")
        if not (project and scheme and destination and result_bundle):
            raise RuntimeError("The coordinator must provide the unsigned simulator test project, scheme, and destination.")
        subprocess.run([sys.executable, str(ROOT / "ci/configure-xctest-environment.py"), project, scheme],
                       env={**env, "SHELL_CASE_ID": case_id, "SHELL_EVIDENCE_DIR": str(evidence)},
                       check=True, timeout=30)
        return subprocess.run([
            "xcodebuild", "test", "-project", project, "-scheme", scheme,
            "-destination", destination, "-resultBundlePath", result_bundle, "CODE_SIGNING_ALLOWED=NO",
            *[f"{key}={value}" for key, value in {**env, "SHELL_CASE_ID": case_id, "SHELL_EVIDENCE_DIR": str(evidence)}.items()
              if key in {"SHELL_SPIKE_ID", "SHELL_CASE_ID", "SHELL_EVIDENCE_DIR",
                         "SHELL_MOBILE_EVIDENCE_SUBPATH", "SHELL_MOBILE_BUNDLE_ID", "SHELL_IOS_XCRESULT_PATH"}],
            "-only-testing:AccentUITests/AccentUITests/testPolicyFixture",
        ], env={**env, "SHELL_CASE_ID": case_id, "SHELL_EVIDENCE_DIR": str(evidence)}, timeout=900)
    return run_android("s11", "AccentUiAutomator#testWallpaperAccent", case_id, evidence, env)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=DRIVERS)
    parser.add_argument("--reduce-android", type=Path)
    parser.add_argument("--case-id", default=os.environ.get("SHELL_CASE_ID"))
    args = parser.parse_args()
    case_id = args.case_id
    if args.reduce_android:
        analyze_android_events(args.reduce_android, case_id)
        return 0
    if not args.platform:
        parser.error("--platform is required when driving a case")
    evidence_arg = os.environ.get("SHELL_EVIDENCE_DIR")
    cell = os.environ.get("SHELL_CELL", "unspecified")
    if not case_id or not evidence_arg:
        parser.error("SHELL_CASE_ID and SHELL_EVIDENCE_DIR are required.")
    evidence = Path(evidence_arg)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "recorder").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"SHELL_SPIKE_ID": "s11", "SHELL_CASE_ID": case_id,
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
            if not wait_desktop_ready(desktop_process, evidence, case_id):
                raise RuntimeError("Desktop startup failed; see desktop-readiness.json and desktop-launch.log")
        result = run_native(args.platform, DRIVERS[args.platform], case_id, evidence, env)
        if result.returncode != 0:
            write_status(evidence, args.platform, case_id, cell,
                         f"Native driver exited with status {result.returncode}; accent delivery is unverified.")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        write_status(evidence, args.platform, case_id, cell,
                     f"Native driver unavailable: {type(error).__name__}: {error}")
    finally:
        stop_desktop(desktop_process, evidence)
        subprocess.run([
            sys.executable, str(ROOT / "automation/accent/result-envelope.py"),
            "--case-file", str(ROOT / "cases/s11.json"), "--case-id", case_id,
            "--evidence-dir", str(evidence), "--output", str(evidence / "assertions.json"),
        ], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
