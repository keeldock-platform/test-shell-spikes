#!/usr/bin/env bash
set -euo pipefail

if [[ "${LINUX_DISTRO:-}" == "Ubuntu 24.04" ]]; then
  bash ci/linux/session.sh provision
  bash ci/linux/session.sh run python3 ci/run-platform.py linux --spikes s03 s10 s11
else
  python3 ci/emit-unverified-linux.py
fi
