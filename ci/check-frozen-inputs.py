#!/usr/bin/env python3
"""Check exact package pins and require conservative host-runtime fallbacks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def markers(value, path="$files"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from markers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from markers(item, f"{path}[{index}]")
    elif isinstance(value, str) and "UNRESOLVED" in value:
        yield path, value


def main() -> int:
    lock = json.loads((ROOT / "ci/environment-lock.json").read_text(encoding="utf-8"))
    unresolved = list(markers(lock))
    if lock.get("freezeStatus") != "dependency-versions-pinned; host-managed-runtime-values-observed-per-cell; unsupported-linux-profiles-explicit":
        unresolved.append(("ci/environment-lock.json.freezeStatus", "the environment policy does not match the reviewed dependency/runtime status"))
    runtime_policy = lock.get("runtimePolicy", {})
    if runtime_policy.get("passRequiresExactRuntimeMatch") is not True or runtime_policy.get("unmatchedOrUnpinnedVerdict") != "UNVERIFIED":
        unresolved.append(("ci/environment-lock.json.runtimePolicy", "host-runtime discovery must never support PASS without a reviewed exact match"))
    if not isinstance(runtime_policy.get("exactRuntimeVersionsByCell"), dict):
        unresolved.append(("ci/environment-lock.json.runtimePolicy.exactRuntimeVersionsByCell", "exact runtime expectations must use a per-cell mapping"))
    pins = runtime_policy.get("exactRuntimeVersionsByCell", {})
    mode = runtime_policy.get("mode")
    if (not pins and (mode != "first-ci-run-discovery" or not runtime_policy.get("discoveryAuthorization"))) or (pins and mode != "locked"):
        unresolved.append(("ci/environment-lock.json.runtimePolicy.mode", "empty pins require explicit first-run discovery authorization; populated pins require locked mode"))
    if mode == "first-ci-run-discovery" and os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_RUN_NUMBER") != "1" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            unresolved.append(("runtimePolicy.discoveryAuthorization", "discovery is limited to the first CI run and first attempt; coordinator freeze is required"))
    for cell, profile in ((item.get("distribution"), item) for item in lock.get("linuxProfiles", [])):
        if profile.get("availability") == "not-provisioned" and not profile.get("fallbacks"):
            unresolved.append((f"ci/environment-lock.json.linuxProfiles.{cell}", "an unavailable profile has no explicit platform fallback"))
    screenshot_version = lock.get("linuxHostPackages", {}).get("ubuntu-24.04", {}).get("gnomeScreenshot")
    if screenshot_version != "41.0-2build2":
        unresolved.append(("ci/environment-lock.json.linuxHostPackages.ubuntu-24.04.gnomeScreenshot", "the screenshot utility must use the pinned Ubuntu 24.04 package revision"))
    if not lock.get("waylandInput", {}).get("versionSource"):
        unresolved.append(("ci/environment-lock.json.waylandInput.versionSource", "the installed Wayland input package version must be captured in session diagnostics"))
    android = lock.get("android", {})
    if android.get("ndk", {}).get("package") != f"ndk;{android.get('ndk', {}).get('version', '')}":
        unresolved.append(("ci/environment-lock.json.android.ndk", "the Android NDK package and version do not agree"))
    for key in ("platform", "buildTools"):
        if not android.get(key, {}).get("package"):
            unresolved.append((f"ci/environment-lock.json.android.{key}", "an exact Android SDK package is missing"))
    uiautomator = android.get("uiAutomator", {})
    expected_uiautomator = {
        "runnerModel": "androidx-instrumentation-apk",
        "instrumentationRunner": "androidx.test.runner.AndroidJUnitRunner",
        "instrumentationPackage": "org.example.shellspikes.mobile.test",
        "androidxRunner": "1.7.0",
        "androidxJunitExtension": "1.3.0",
        "androidxUiAutomator": "2.4.0",
        "junit": "4.13.2",
        "compileSdk": 35,
        "buildTools": "35.0.0",
    }
    if any(uiautomator.get(key) != value for key, value in expected_uiautomator.items()):
        unresolved.append(("ci/environment-lock.json.android.uiAutomator", "AndroidX instrumentation APK and direct test dependencies must match the reviewed exact pins"))
    if not (ROOT / "Cargo.lock").is_file():
        unresolved.append(("Cargo.lock", "generated dependency graph is missing"))
    if unresolved:
        print("Frozen environment is incomplete:")
        for path, value in unresolved:
            print(f"- {path}: {value}")
        return 1
    print("Exact dependency versions and conservative host-runtime verdict rules are configured; mutable host runtimes remain observed values.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
