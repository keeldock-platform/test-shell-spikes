#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/apps/test-shell-mobile/src-tauri"
case "$target" in
  ios)
    cargo tauri ios init --ci
    ;;
  android)
    cargo tauri android init --ci
    android_project="$repo_root/apps/test-shell-mobile/src-tauri/gen/android"
    python3 "$repo_root/ci/pin-android-gradle.py" "$android_project"
    mkdir -p "$repo_root/target/gradle-home/init.d"
    cp "$android_project/shell-kotlin.init.gradle" "$repo_root/target/gradle-home/init.d/shell-kotlin.gradle"
    evidence_root="${SHELL_EVIDENCE_DIR:-$repo_root/evidence}"
    if [[ "$evidence_root" != /* ]]; then evidence_root="$repo_root/$evidence_root"; fi
    mkdir -p "$evidence_root/preflight"
    echo "::group::Android dependency-resolution probe"
    "$android_project/gradlew" --project-dir "$android_project" --no-daemon --no-configuration-cache shellDependencyProbe buildEnvironment | tee "$evidence_root/preflight/android-gradle-resolution.log"
    echo "::endgroup::"
    accent_package="$android_project/app/src/main/java/org/example/shellspikes/accent"
    mkdir -p "$accent_package"
    cp "$repo_root/apps/test-shell-mobile/plugins/accent/AndroidAccentReader.kt" "$accent_package/AndroidAccentReader.kt"
    cp "$repo_root/apps/test-shell-mobile/src-tauri/wrapper/android/S11AccentPlugin.kt" "$accent_package/S11AccentPlugin.kt"
    ;;
  *)
    echo "usage: $0 ios|android" >&2
    exit 2
    ;;
esac
