#!/usr/bin/env bash
# Re-resolve transient Maven misses without retrying compilation/assertion failures.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${SHELL_EVIDENCE_DIR:-$repo_root/evidence}"
if [[ "$out" != /* ]]; then out="$repo_root/$out"; fi
mkdir -p "$out/preflight"
for attempt in 1 2 3; do
  log="$out/preflight/android-build-attempt-$attempt.log"
  echo "Android build attempt=$attempt/3 refreshDependencies=${SHELL_ANDROID_REFRESH_DEPENDENCIES:-0}"
  set +e
  "$@" 2>&1 | tee "$log"
  statuses=("${PIPESTATUS[@]}")
  set -e
  status="${statuses[0]}"
  if [[ "${statuses[1]}" != 0 ]]; then exit "${statuses[1]}"; fi
  if [[ "$status" == 0 ]]; then exit 0; fi
  if [[ "$attempt" == 3 ]] || ! grep -Eq 'Could not (find|resolve)' "$log" || ! grep -q 'https://repo.maven.apache.org/maven2/' "$log"; then
    exit "$status"
  fi
  # Gradle caches negative module lookups. The generated init script reads this
  # flag; changing versions or deleting unrelated caches would hide the cause.
  export SHELL_ANDROID_REFRESH_DEPENDENCIES=1
  sleep "$attempt"
done
