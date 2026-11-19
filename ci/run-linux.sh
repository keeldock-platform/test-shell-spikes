#!/usr/bin/env bash
set -euo pipefail

if [[ "${LINUX_DISTRO:-}" == "Ubuntu 24.04" ]]; then
  status=0
  bash ci/linux/session.sh provision || status=$?
  if [[ "$status" == 0 ]]; then
    bash ci/linux/session.sh run python3 ci/run-platform.py linux --spikes s03 s10 s11 || status=$?
  fi
  if [[ "$status" == 78 ]]; then
    export SHELL_LINUX_FALLBACK_REASON="Required GNOME session or input adapter unavailable; see preflight session diagnostics."
    python3 ci/emit-unverified-linux.py
  else
    exit "$status"
  fi
else
  python3 ci/emit-unverified-linux.py
fi
