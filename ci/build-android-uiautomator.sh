#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
android_project="${repo_root}/apps/test-shell-mobile/src-tauri/gen/android"
gradle_wrapper="${android_project}/gradlew"
output_dir="${repo_root}/target/native-tests/android"
app_module="${android_project}/app"
init_script="${output_dir}/androidx-uiautomator.init.gradle"
test_apk="${output_dir}/shell-spike-uiautomator.apk"

[[ -x "$gradle_wrapper" ]] || { echo "Generated Android Gradle wrapper is unavailable" >&2; exit 78; }
[[ -d "$app_module" ]] || { echo "Generated Android app module is unavailable" >&2; exit 78; }
mkdir -p "$output_dir"
rm -f "$test_apk"

cat >"$init_script" <<EOF
allprojects {
    afterEvaluate { project ->
        if (project.path == ":app" && project.plugins.hasPlugin("com.android.application")) {
            project.android.compileSdk = 35
            project.android.buildToolsVersion = "35.0.0"
            project.android.defaultConfig.testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
            project.android.defaultConfig.testApplicationId = "org.example.shellspikes.mobile.test"
            project.android.sourceSets.getByName("androidTest").java.srcDirs += [
                "${repo_root}/automation/android/s10",
                "${repo_root}/automation/android/s11",
            ]
            project.dependencies.add("androidTestImplementation", "androidx.test:runner:1.7.0")
            project.dependencies.add("androidTestImplementation", "androidx.test.ext:junit:1.3.0")
            project.dependencies.add("androidTestImplementation", "androidx.test.uiautomator:uiautomator:2.4.0")
            project.dependencies.add("androidTestImplementation", "junit:junit:4.13.2")
        }
    }
}
EOF

"$gradle_wrapper" --project-dir "$android_project" --no-daemon --init-script "$init_script" :app:assembleDebugAndroidTest

candidates=()
while IFS= read -r candidate; do
  candidates+=("$candidate")
done < <(find "$app_module/build/outputs/apk/androidTest" -type f -name '*androidTest*.apk' -print 2>/dev/null | sort)
[[ "${#candidates[@]}" -eq 1 ]] || {
  echo "Expected one AndroidX instrumentation APK, found ${#candidates[@]}" >&2
  exit 78
}
cp "${candidates[0]}" "$test_apk"

sdk_root="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
aapt="${sdk_root}/build-tools/35.0.0/aapt"
[[ -x "$aapt" ]] || { echo "Pinned Android build-tools aapt is unavailable" >&2; exit 78; }
badging="$("$aapt" dump badging "$test_apk")"
grep -Fq "package: name='org.example.shellspikes.mobile.test'" <<<"$badging" || {
  echo "Instrumentation APK package does not match the pinned test package" >&2
  exit 78
}
grep -Fq "instrumentation: name='androidx.test.runner.AndroidJUnitRunner'" <<<"$badging" || {
  echo "AndroidX instrumentation runner was not packaged" >&2
  exit 78
}

sha256sum "$test_apk"
printf '%s\n' "$test_apk"
