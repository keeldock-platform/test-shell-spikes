#!/usr/bin/env python3
"""Build a target once, then run all assigned spike adapters serially."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from process_watch import watched
from case_catalog import case_ids_for
from discovery_authorization import discovery_authorization_errors

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "apps/desktop/src-tauri"
MOBILE = ROOT / "apps/test-shell-mobile/src-tauri"
LOCK = ROOT / "ci/environment-lock.json"
ANDROID_EMULATOR_PROCESS: subprocess.Popen | None = None


def environment_lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def execute(command: list[str], *, cwd: Path = ROOT) -> int:
    print("+ " + " ".join(command), flush=True)
    if command[:4] == ["cargo", "tauri", "android", "build"]:
        command = ["bash", str(ROOT / "ci/android-build-retry.sh"), *command]
    return subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=False).returncode


def run_case(platform, spike, case_id):
    defaults = {'s01': 1200, 's02': 300, 's03': 600, 's08': 1200, 's10': 600, 's11': 600}
    timeout = 900 if platform == 'ios' else defaults[spike]
    status = watched([sys.executable, 'ci/run_case.py', platform, spike, case_id],
                     label=f'{platform}/{spike}/{case_id}', timeout=timeout, cwd=ROOT,
                     env=os.environ.copy(), cleanup_grace=20)
    root = Path(os.environ.get('SHELL_EVIDENCE_DIR', 'evidence'))
    if platform == 'windows':
        from run_case import recorder_commands
        output = root / 'spikes' / spike / case_id / 'video/capture.mkv'
        command, pid_file = recorder_commands(platform, 'stop', output)
        if pid_file.is_file():
            print(f'Cleanup orphan capture after {case_id}', flush=True)
            try:
                stopped = subprocess.run(command, timeout=30, check=False)
                if stopped.returncode:
                    status = status or stopped.returncode
            except subprocess.TimeoutExpired:
                status = status or 124
    path = root / 'spikes' / spike / case_id / 'recorder/case-process.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'caseId': case_id, 'exitCode': status,
                               'timeoutSeconds': timeout, 'timedOut': status == 124}, indent=2) + '\n')
    return status


def start_android_emulator(api: str) -> int:
    global ANDROID_EMULATOR_PROCESS
    android_lock = environment_lock()["android"]
    image_entry = android_lock["systemImages"].get(api, {})
    image = image_entry.get("package")
    if not isinstance(image, str) or not image:
        print(f"Android API {api} system image package is not declared.", file=sys.stderr)
        return 78
    sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk_root:
        os.environ["ANDROID_HOME"] = sdk_root
        os.environ["ANDROID_SDK_ROOT"] = sdk_root
        os.environ["PATH"] = os.pathsep.join([
            str(Path(sdk_root) / "cmdline-tools/latest/bin"),
            str(Path(sdk_root) / "platform-tools"),
            str(Path(sdk_root) / "emulator"), os.environ.get("PATH", ""),
        ])
    sdkmanager = shutil.which("sdkmanager")
    if not sdkmanager:
        print("sdkmanager is unavailable", file=sys.stderr)
        return 127
    packages = [
        str(android_lock.get("platform", {}).get("package", "")),
        str(android_lock.get("buildTools", {}).get("package", "")),
        str(android_lock.get("ndk", {}).get("package", "")),
        "platform-tools",
        "emulator",
        image,
    ]
    if any(not package for package in packages):
        print("Android SDK package set is incomplete.", file=sys.stderr)
        return 78
    # sdkmanager otherwise silently skips API 31 on EOF at its license prompt.
    try:
        licenses = subprocess.run([sdkmanager, "--licenses"], input="y\n" * 100,
                                  text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Android SDK license preflight failed: {type(error).__name__}", file=sys.stderr)
        return 78
    if licenses.returncode:
        print("Android SDK license acceptance failed.", file=sys.stderr)
        return licenses.returncode
    install_status = execute([sdkmanager, "--channel=0", "--install", *packages])
    if install_status:
        return install_status
    installed = run_command([sdkmanager, "--list_installed"])
    installed_row = next((line.strip() for line in (installed or "").splitlines() if line.strip().startswith(f"{image} |")), None)
    if installed_row is None:
        print(f"Installed Android system image revision could not be identified for {image}.", file=sys.stderr)
        return 78
    os.environ["SHELL_ANDROID_SYSTEM_IMAGE"] = installed_row
    package_rows = [
        line.strip()
        for line in (installed or "").splitlines()
        if any(line.strip().startswith(f"{package} |") for package in packages)
    ]
    os.environ["SHELL_ANDROID_SDK_PACKAGES"] = "\n".join(package_rows)
    os.environ["SHELL_ANDROID_SDKMANAGER_VERSION"] = run_command([sdkmanager, "--version"]) or "unavailable"
    os.environ["SHELL_ANDROID_ADB_VERSION"] = run_command(["adb", "--version"]) or "unavailable"
    emulator_version = run_command(["emulator", "-version"])
    os.environ["SHELL_ANDROID_EMULATOR_VERSION"] = (emulator_version or "unavailable").splitlines()[0]
    sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    ndk_version = str(android_lock.get("ndk", {}).get("version", ""))
    ndk_root = Path(sdk_root) / "ndk" / ndk_version if sdk_root else None
    properties_path = ndk_root / "source.properties" if ndk_root else None
    if not properties_path or not properties_path.is_file():
        print("The locked Android NDK package was not installed.", file=sys.stderr)
        return 78
    properties = properties_path.read_text(encoding="utf-8", errors="replace")
    revision = next((line.partition("=")[2].strip() for line in properties.splitlines() if line.startswith("Pkg.Revision")), "")
    if revision != ndk_version:
        print("Installed Android NDK revision does not match the lock.", file=sys.stderr)
        return 78
    os.environ["ANDROID_NDK_HOME"] = str(ndk_root)
    os.environ["NDK_HOME"] = str(ndk_root)
    os.environ["SHELL_ANDROID_NDK_VERSION"] = revision
    avd = f"shell-spike-api-{api}"
    device = str(environment_lock()["android"].get("deviceProfile", ""))
    if not device:
        print("Android AVD device profile is not frozen.", file=sys.stderr)
        return 78
    # avdmanager can exit successfully on EOF without writing an AVD. Supply
    # its hardware-profile answer and share one explicit home with the emulator.
    avd_home = Path(os.environ.get("RUNNER_TEMP", str(ROOT / "target"))) / "shell-spike-avd"
    avd_home.mkdir(parents=True, exist_ok=True)
    os.environ["ANDROID_AVD_HOME"] = str(avd_home.resolve())
    avdmanager = shutil.which("avdmanager")
    if not avdmanager:
        print("avdmanager is unavailable", file=sys.stderr)
        return 127
    command = [avdmanager, "create", "avd", "--force", "--name", avd,
               "--package", image, "--device", device]
    print("+ " + " ".join(command), flush=True)
    try:
        create = subprocess.run(command, cwd=ROOT, env=os.environ.copy(),
                                input="no\n", text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        print("avdmanager timed out before creating the AVD", file=sys.stderr)
        return 78
    if create.returncode:
        return create.returncode
    available = run_command(["emulator", "-list-avds"]) or ""
    if not (avd_home / f"{avd}.ini").is_file() or avd not in available.splitlines():
        print(f"avdmanager did not create the expected AVD: {avd}", file=sys.stderr)
        return 78
    emulator_log = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence")) / "recorder/android-emulator.log"
    emulator_log.parent.mkdir(parents=True, exist_ok=True)
    with emulator_log.open("w") as log:
        process = subprocess.Popen(
            ["emulator", "-avd", avd, "-accel", "on", "-wipe-data", "-no-snapshot", "-no-audio", "-no-window", "-no-boot-anim"],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    os.environ["SHELL_ANDROID_EMULATOR_PID"] = str(process.pid)
    ANDROID_EMULATOR_PROCESS = process
    try:
        wait_status = subprocess.run(["adb", "wait-for-device"], timeout=180, check=False).returncode
    except subprocess.TimeoutExpired:
        print("adb wait-for-device timed out; inspect recorder/android-emulator.log", file=sys.stderr)
        return 78
    if wait_status:
        return wait_status
    for _ in range(120):
        if (run_command(["adb", "shell", "getprop", "sys.boot_completed"]) or "").strip() == "1":
            return 0
        time.sleep(1)
    print("Android emulator did not finish booting.", file=sys.stderr)
    return 78


def stop_android_emulator() -> int:
    global ANDROID_EMULATOR_PROCESS
    if not os.environ.get("SHELL_ANDROID_EMULATOR_PID"):
        return 0
    status = execute(["adb", "emu", "kill"])
    if ANDROID_EMULATOR_PROCESS is not None:
        try:
            ANDROID_EMULATOR_PROCESS.wait(timeout=30)
        except subprocess.TimeoutExpired:
            ANDROID_EMULATOR_PROCESS.terminate()
            ANDROID_EMULATOR_PROCESS.wait(timeout=10)
        ANDROID_EMULATOR_PROCESS = None
    os.environ.pop("SHELL_ANDROID_EMULATOR_PID", None)
    return status


def boot_ios_simulator(device_key: str) -> str | None:
    device = environment_lock()["apple"]["simulatorDevices"].get(device_key, {})
    name = str(device.get("name", ""))
    runtime = str(device.get("runtime", ""))
    if not name or not runtime:
        print(f"The locked {device_key} simulator model/runtime is unresolved.", file=sys.stderr)
        return None
    if environment_lock()["runtimePolicy"].get("mode") == "first-ci-run-discovery":
        runtimes = json.loads(run_command(["xcrun", "simctl", "list", "runtimes", "--json"]) or "{}").get("runtimes", [])
        stable = [r for r in runtimes if r.get("isAvailable") and "iOS" in r.get("identifier", "")
                  and not any(label in r.get("name", "").lower() for label in ("beta", "rc", "preview"))]
        if not stable:
            return None
        runtime = max(stable, key=lambda r: tuple(int(n) for n in r["version"].split(".")))["identifier"]
    listing = run_command(["xcrun", "simctl", "list", "devices", "--json"])
    if listing is None:
        return None
    try:
        devices = json.loads(listing).get("devices", {})
    except json.JSONDecodeError:
        return None
    udid = None
    for runtime_name, entries in devices.items():
        if runtime_name == runtime:
            for entry in entries:
                if entry.get("name") == name:
                    udid = entry.get("udid")
                    break
    if not udid and environment_lock()["runtimePolicy"].get("mode") == "first-ci-run-discovery":
        model = "com.apple.CoreSimulator.SimDeviceType." + name.replace(" ", "-").replace("(", "").replace(")", "")
        udid = (run_command(["xcrun", "simctl", "create", name, model, runtime]) or "").strip() or None
    if not udid:
        print(f"Simulator {name} for {runtime} is not installed.", file=sys.stderr)
        return None
    state = next((entry.get("state") for entries in devices.values() for entry in entries if entry.get("udid") == udid), None)
    if (state != "Booted" and execute(["xcrun", "simctl", "boot", udid])) or execute(["xcrun", "simctl", "bootstatus", udid, "-b"]):
        return None
    os.environ["SHELL_IOS_SIMULATOR_UDID"] = str(udid)
    os.environ["SHELL_IOS_SIMULATOR_NAME"] = name
    os.environ["SHELL_IOS_SIMULATOR_RUNTIME"] = runtime
    os.environ["SHELL_MOBILE_BUNDLE_ID"] = "org.example.shellspikes.mobile"
    os.environ["SHELL_IOS_DESTINATION"] = f"platform=iOS Simulator,id={udid}"
    return str(udid)


def run_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def install_ios_wrapper(udid: str) -> int:
    candidates = sorted((MOBILE / "gen/apple").rglob("*.app")) if (MOBILE / "gen/apple").exists() else []
    wrapper = next((path for path in candidates if path.name.lower().startswith("test shell mobile")), None)
    if wrapper is None:
        print("No generated iOS simulator app was found.", file=sys.stderr)
        return 78
    status = execute(["xcrun", "simctl", "install", udid, str(wrapper)])
    if status == 0:
        os.environ["SHELL_APP_PATH"] = str(wrapper)
        os.environ["SHELL_MOBILE_BUNDLE_ID"] = "org.example.shellspikes.mobile"
    return status


def install_android_wrapper() -> int:
    candidates = sorted((MOBILE / "gen/android").rglob("*.apk")) if (MOBILE / "gen/android").exists() else []
    wrapper = next((path for path in candidates if "debug" in path.parts and "androidTest" not in path.parts), None)
    if wrapper is None:
        print("No debuggable Android APK was found.", file=sys.stderr)
        return 78
    sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    aapt = Path(sdk_root) / "build-tools" / environment_lock()["android"]["buildTools"]["package"].split(";", 1)[1] / "aapt" if sdk_root else None
    if not aapt or not aapt.is_file():
        print("The pinned Android build-tools aapt is unavailable.", file=sys.stderr)
        return 78
    badging = run_command([str(aapt), "dump", "badging", str(wrapper)])
    if not badging or "application-debuggable" not in badging:
        print("The selected Android APK is not explicitly debuggable for case-isolated evidence export.", file=sys.stderr)
        return 78
    status = execute(["adb", "install", "-r", str(wrapper)])
    if status == 0:
        os.environ["SHELL_APP_PATH"] = str(wrapper)
        os.environ["SHELL_MOBILE_BUNDLE_ID"] = "org.example.shellspikes.mobile"
        os.environ["SHELL_ANDROID_DEBUGGABLE"] = "1"
    return status


def package_macos_app(executable: Path) -> Path | None:
    if not executable.is_file():
        print("The macOS desktop executable was not produced.", file=sys.stderr)
        return None
    config = json.loads((DESKTOP / "tauri.conf.json").read_text(encoding="utf-8"))
    bundle = ROOT / "target/release" / "Test Shell.app"
    contents = bundle / "Contents"
    binary_directory = contents / "MacOS"
    if bundle.exists():
        shutil.rmtree(bundle)
    binary_directory.mkdir(parents=True)
    shutil.copy2(executable, binary_directory / executable.name)
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": executable.name,
        "CFBundleIdentifier": config["identifier"],
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": config["productName"],
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": config["version"],
        "CFBundleVersion": config["version"],
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream, sort_keys=True)
    return bundle


def configure_xctest_project(platform_name: str, spike: str) -> bool:
    suite = "s01" if platform_name == "macos" else spike
    output = run_command([sys.executable, "ci/generate-native-test-projects.py", platform_name, suite])
    project = Path(output.strip()) if output else None
    if not project or not project.is_dir():
        print(f"Could not generate the unsigned {platform_name}/{suite} XCTest project.", file=sys.stderr)
        return False
    scheme = f"ShellSpikeNativeTests-{suite}"
    if platform_name == "macos":
        os.environ["S01_XCODE_PROJECT"] = str(project)
        os.environ["S01_XCODE_SCHEME"] = scheme
        os.environ["S01_XCODE_DESTINATION"] = "platform=macOS"
        os.environ["S01_ONLY_TESTING_TARGET"] = "TrafficLightsUITests/TrafficLightsUITests/testS01TrafficLightsMatrix"
        preflight = subprocess.run(["swift", "ci/preflight-s01-permissions.swift"], cwd=ROOT, capture_output=True, text=True, check=False)
        preflight_dir = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence")) / "recorder"
        preflight_dir.mkdir(parents=True, exist_ok=True)
        (preflight_dir / "s01-permission-preflight.log").write_text(
            preflight.stdout + preflight.stderr, encoding="utf-8"
        )
        os.environ["S01_PERMISSION_PROMPT_PREFLIGHT"] = "passed" if preflight.returncode == 0 else "unverified"
        try:
            preflight_report = json.loads(preflight.stdout)
            screens = preflight_report.get("screens", [])
            if preflight_report.get("status") == "passed" and isinstance(screens, list):
                os.environ["SHELL_S01_DISPLAYS_JSON"] = json.dumps(screens, separators=(",", ":"))
            else:
                os.environ.pop("SHELL_S01_DISPLAYS_JSON", None)
        except json.JSONDecodeError:
            os.environ.pop("SHELL_S01_DISPLAYS_JSON", None)
    else:
        os.environ["SHELL_IOS_PROJECT"] = str(project)
        os.environ["SHELL_IOS_TEST_SCHEME"] = scheme
        os.environ["SHELL_IOS_DESTINATION"] = os.environ.get("SHELL_IOS_DESTINATION", "")
    return True


def build_android_uiautomator() -> None:
    evidence = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence"))
    log = evidence / "recorder" / "android-uiautomator-build.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    apk = ROOT / "target/native-tests/android/shell-spike-uiautomator.apk"
    try:
        result = subprocess.run(
            ["bash", "ci/build-android-uiautomator.sh"],
            cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.write_text(f"UNVERIFIED: {type(error).__name__}\n", encoding="utf-8")
        for key in ("SHELL_UIAUTOMATOR_APK", "SHELL_UIAUTOMATOR_RUNNER", "SHELL_UIAUTOMATOR_TEST_PACKAGE"):
            os.environ.pop(key, None)
        return
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    print("Android instrumentation build probe:\n" + (result.stdout + result.stderr)[-12000:], flush=True)
    if result.returncode == 0 and apk.is_file():
        try:
            install = subprocess.run(
                ["adb", "install", "-r", str(apk)], cwd=ROOT,
                capture_output=True, text=True, timeout=90, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            with log.open("a", encoding="utf-8") as stream:
                stream.write(f"\nUNVERIFIED: instrumentation APK install failed ({type(error).__name__}).\n")
            for key in ("SHELL_UIAUTOMATOR_APK", "SHELL_UIAUTOMATOR_RUNNER", "SHELL_UIAUTOMATOR_TEST_PACKAGE", "SHELL_UIAUTOMATOR_VERSION", "SHELL_UIAUTOMATOR_SHA256"):
                os.environ.pop(key, None)
            return
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n$ adb install -r " + str(apk) + "\n" + install.stdout + install.stderr)
        if install.returncode:
            for key in ("SHELL_UIAUTOMATOR_APK", "SHELL_UIAUTOMATOR_RUNNER", "SHELL_UIAUTOMATOR_TEST_PACKAGE"):
                os.environ.pop(key, None)
            os.environ.pop("SHELL_UIAUTOMATOR_VERSION", None)
            os.environ.pop("SHELL_UIAUTOMATOR_SHA256", None)
            return
        uiautomator = environment_lock()["android"]["uiAutomator"]
        wrapper_properties = ROOT / str(uiautomator["gradleWrapper"])
        wrapper_url = "unavailable"
        if wrapper_properties.is_file():
            for line in wrapper_properties.read_text(encoding="utf-8").splitlines():
                if line.startswith("distributionUrl="):
                    wrapper_url = line.partition("=")[2]
                    break
        os.environ["SHELL_UIAUTOMATOR_APK"] = str(apk)
        os.environ["SHELL_UIAUTOMATOR_RUNNER"] = str(uiautomator["instrumentationRunner"])
        os.environ["SHELL_UIAUTOMATOR_TEST_PACKAGE"] = str(uiautomator["instrumentationPackage"])
        os.environ["SHELL_UIAUTOMATOR_VERSION"] = (
            f"gradle-wrapper={wrapper_url};runner={uiautomator['androidxRunner']};"
            f"junit-extension={uiautomator['androidxJunitExtension']};"
            f"uiautomator={uiautomator['androidxUiAutomator']};junit={uiautomator['junit']}"
        )
        os.environ["SHELL_UIAUTOMATOR_SHA256"] = hashlib.sha256(apk.read_bytes()).hexdigest()
    else:
        for key in ("SHELL_UIAUTOMATOR_APK", "SHELL_UIAUTOMATOR_RUNNER", "SHELL_UIAUTOMATOR_TEST_PACKAGE", "SHELL_UIAUTOMATOR_VERSION", "SHELL_UIAUTOMATOR_SHA256"):
            os.environ.pop(key, None)


def build_windows_readback() -> None:
    evidence = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence"))
    log = evidence / "recorder" / "windows-readback-build.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    output = Path(os.environ.get("RUNNER_TEMP", str(ROOT / "target"))) / "windows-accent-readback.exe"
    try:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise FileNotFoundError("PowerShell is unavailable")
        result = subprocess.run(
            [shell, "-NoProfile", "-File", str(ROOT / "ci/build-windows-readback.ps1"), "-OutputPath", str(output)],
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.write_text(f"UNVERIFIED: {type(error).__name__}\n", encoding="utf-8")
        os.environ.pop("SHELL_WINDOWS_READBACK_EXE", None)
        return
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode == 0 and output.is_file():
        os.environ["SHELL_WINDOWS_READBACK_EXE"] = str(output)
    else:
        os.environ.pop("SHELL_WINDOWS_READBACK_EXE", None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["macos", "windows", "linux", "ios", "android"])
    parser.add_argument("--spikes", nargs="+", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Describe Android preflight without provisioning or builds")
    args = parser.parse_args()
    if any(spike not in {"s01", "s02", "s03", "s08", "s10", "s11"} for spike in args.spikes):
        parser.error("--spikes contains an unknown id")

    if args.dry_run:
        if args.platform != "android":
            parser.error("--dry-run currently supports Android preflight")
        return execute([sys.executable, "ci/runtime-discovery.py", "android", "--dry-run"])

    policy = environment_lock()["runtimePolicy"]
    if args.platform == "ios" and policy.get("mode") == "first-ci-run-discovery":
        errors = discovery_authorization_errors(policy, os.environ, require_ci=True)
        if errors or not os.environ.get("GITHUB_RUN_ID"):
            print("iOS bootstrap requires coordinator-authorized discovery.", file=sys.stderr)
            return 78

    # Start CoreSimulator and wait for a usable device before Xcode runtime updates.
    if args.platform == "ios" and not boot_ios_simulator("iphone"):
        print("iOS simulator bootstrap failed before runtime discovery.", file=sys.stderr)
        return 78

    discovery_status = execute([sys.executable, "ci/runtime-discovery.py", args.platform])
    if discovery_status:
        return discovery_status

    if args.platform == "macos":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            listed = subprocess.run(
                [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True,
                text=True,
                check=False,
            )
            output = listed.stdout + listed.stderr
            import re
            match = re.search(r"\[(\d+)\]\s+Capture screen", output, re.IGNORECASE)
            if match:
                os.environ["SHELL_CAPTURE_DEVICE"] = f"{match.group(1)}:none"
                os.environ["SHELL_CAPTURE_DEVICE_SOURCE"] = "ffmpeg AVFoundation screen-device enumeration"
            else:
                os.environ["SHELL_CAPTURE_DEVICE"] = "UNVERIFIED"

    if args.platform == "linux":
        backend = os.environ.get("SHELL_LINUX_COMPOSITOR")
        if os.environ.get("SHELL_LINUX_SESSION_READY") != "1" or backend not in {"gnome-shell-x11", "gnome-shell-wayland", "metacity-x11"}:
            print("Declared Linux GUI session was not provisioned; refusing to build or run on the Ubuntu host.", file=sys.stderr)
            return 78
    if args.platform == "android":
        api = os.environ.get("ANDROID_API_LEVEL", "")
        os.environ["SHELL_CELL"] = f"android-api-{api}"
        emulator_status = start_android_emulator(api)
        if emulator_status:
            print("Android emulator could not be provisioned from the frozen SDK image.", file=sys.stderr)
            stop_android_emulator()
            return emulator_status

    if args.platform == "android":
        active_status = execute([sys.executable, "ci/runtime-discovery.py", "android", "--android-active"])
        if active_status:
            print("Bundled WebView discovery unavailable: UNVERIFIED; continuing Android build and cases.", file=sys.stderr)

    renderer_status = execute([shutil.which("npm") or "npm", "run", "build:renderer"])
    if renderer_status:
        if args.platform == "android":
            stop_android_emulator()
        return renderer_status

    mobile = args.platform in {"ios", "android"}
    mobile_app_built = False
    if mobile:
        target = "ios" if args.platform == "ios" else "android"
        if target == "android":
            os.environ["GRADLE_USER_HOME"] = str(ROOT / "target/gradle-home")
        generation = execute(["bash", "ci/generate-mobile-projects.sh", target])
        if generation:
            if args.platform == "android":
                stop_android_emulator()
            return generation
        feature_args = ",".join(f"spike-{spike}" for spike in args.spikes)
        if args.platform == "ios":
            build = execute(["cargo", "tauri", "ios", "build", "--ci", "--target", "aarch64-sim", "--features", feature_args], cwd=MOBILE)
        else:
            build = execute(["cargo", "tauri", "android", "build", "--ci", "--debug", "--target", "x86_64", "--apk", "--features", feature_args], cwd=MOBILE)
        if target == "android" and build == 0:
            build = execute(["bash", "ci/probe-android-generated.sh"])
        mobile_app_built = build == 0
    else:
        features = ",".join(f"spike-{spike}" for spike in args.spikes)
        build = execute(["cargo", "build", "--locked", "--release", "--features", features, "--manifest-path", str(DESKTOP / "Cargo.toml")])
    if build:
        if args.platform == "android":
            stop_android_emulator()
        return build
    if not mobile:
        executable = ROOT / "target/release" / ("shell-spike-desktop.exe" if os.name == "nt" else "shell-spike-desktop")
        if args.platform == "macos":
            bundle = package_macos_app(executable)
            if bundle is None:
                return 78
            os.environ["SHELL_APP_PATH"] = str(bundle)
        else:
            os.environ["SHELL_APP_PATH"] = str(executable)

    failures = []
    if args.platform == "android" and mobile_app_built:
        if install_android_wrapper():
            failures.append("android-install")
    if args.platform == "android":
        build_android_uiautomator()
        instrumentation = run_command(["adb", "shell", "pm", "list", "instrumentation"])
        expected = "org.example.shellspikes.mobile.test/androidx.test.runner.AndroidJUnitRunner"
        print("Android installed instrumentation probe: " + (instrumentation or "unavailable"), flush=True)
        if failures or not os.environ.get("SHELL_UIAUTOMATOR_APK") or expected not in (instrumentation or ""):
            stop_android_emulator()
            return 78
    if args.platform == "windows" and "s11" in args.spikes:
        build_windows_readback()

    if args.platform == "macos" and "s08" in args.spikes:
        shared_s08 = Path(os.environ.get("RUNNER_TEMP", str(ROOT / "target"))) / "s08-shared-evidence"
        try:
            prepared = subprocess.run(
                [sys.executable, "ci/prepare-s08-evidence.py", "--output-dir", str(shared_s08)],
                cwd=ROOT, capture_output=True, text=True, timeout=1000, check=False,
            )
            os.environ["SHELL_S08_EVIDENCE_DIR"] = str(shared_s08)
            (Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence")) / "recorder" / "s08-evidence-preparation.log").write_text(
                prepared.stdout + prepared.stderr, encoding="utf-8"
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            os.environ["SHELL_S08_EVIDENCE_DIR"] = str(shared_s08)
            print(f"S08 evidence preflight unavailable: {type(error).__name__}", file=sys.stderr)

    if args.platform == "macos" and "s01" in args.spikes:
        if not configure_xctest_project("macos", "s01"):
            failures.append("s01-xctest-project")

    if args.platform == "ios":
        for device_key in ("iphone", "ipad"):
            cell = f"ios-colour-{device_key}"
            os.environ["SHELL_CELL"] = cell
            os.environ.pop("SHELL_APP_PATH", None)
            os.environ.pop("SHELL_IOS_SIMULATOR_UDID", None)
            os.environ.pop("SHELL_IOS_DESTINATION", None)
            udid = boot_ios_simulator(device_key)
            if udid:
                install_status = install_ios_wrapper(udid)
                if install_status:
                    failures.append(f"ios-install-{device_key}")
            else:
                failures.append(f"ios-simulator-{device_key}")
            for spike in args.spikes:
                if not configure_xctest_project("ios", spike):
                    failures.append(f"{spike}-xctest-project-{device_key}")
                for case_id in case_ids_for(spike, cell):
                    status = run_case(args.platform, spike, case_id)
                    if status:
                        failures.append(f"{spike}/{case_id}")
            if udid:
                execute(["xcrun", "simctl", "shutdown", udid])
                os.environ.pop("SHELL_IOS_SIMULATOR_UDID", None)
                os.environ.pop("SHELL_IOS_DESTINATION", None)
    else:
        cell = os.environ.get("SHELL_CELL", os.environ.get("GITHUB_JOB", "unknown"))
        if args.platform == "android":
            cell = f"android-api-{os.environ.get('ANDROID_API_LEVEL', 'unknown')}"
            os.environ["SHELL_CELL"] = cell
        for spike in args.spikes:
            for case_id in case_ids_for(spike, cell):
                status = run_case(args.platform, spike, case_id)
                if status:
                    failures.append(f"{spike}/{case_id}")

    if args.platform == "android" and os.environ.get("SHELL_ANDROID_EMULATOR_PID"):
        process_status = stop_android_emulator()
        if process_status:
            failures.append("android-emulator-shutdown")

    print(f"Finished {args.platform}; incomplete cells: {', '.join(failures) if failures else 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
