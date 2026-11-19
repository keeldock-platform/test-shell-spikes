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
