#!/usr/bin/env bash
set -euo pipefail
if [[ "${ANDROID_API_LEVEL:-}" == "30" ]]; then
  python3 ci/run-platform.py android --spikes s11
else
  python3 ci/run-platform.py android --spikes s10 s11
fi
