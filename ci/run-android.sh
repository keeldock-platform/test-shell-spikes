#!/usr/bin/env bash
set -euo pipefail
[[ -n "${JAVA_HOME_17_X64:-}" && -x "$JAVA_HOME_17_X64/bin/java" ]] || { echo 'Hosted JDK 17 is required' >&2; exit 78; }
export JAVA_HOME="$JAVA_HOME_17_X64"
export PATH="$JAVA_HOME/bin:$PATH"
java -version
[[ "$(java -version 2>&1)" == *'version "17.'* ]] || exit 78
if [[ "${ANDROID_API_LEVEL:-}" == "30" ]]; then
  python3 ci/run-platform.py android --spikes s11
else
  python3 ci/run-platform.py android --spikes s10 s11
fi
