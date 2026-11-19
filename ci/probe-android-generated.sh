#!/usr/bin/env bash
set -euo pipefail
project="$(pwd)/apps/test-shell-mobile/src-tauri/gen/android"
out="${SHELL_EVIDENCE_DIR:-evidence}/preflight"
mkdir -p "$out"
for generated in tauri.settings.gradle app/tauri.build.gradle.kts; do
  [[ -s "$project/$generated" ]] || { echo "Missing generated Android input: $generated" >&2; exit 78; }
done
echo "::group::Android generated-input and dependency-resolution probe"
cat "$project/tauri.settings.gradle"
"$project/gradlew" --project-dir "$project" --no-daemon --no-configuration-cache shellDependencyProbe buildEnvironment | tee "$out/android-gradle-resolution.log"
echo "::endgroup::"
