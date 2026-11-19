#!/usr/bin/env bash
set -euo pipefail
if [[ "${SHELL_PACKAGE_ROOT:-}" == 1 && "$EUID" == 0 ]]; then sudo() { "$@"; }; fi
attempts="${SHELL_APT_ATTEMPTS:-3}"
[[ "$attempts" =~ ^[1-3]$ ]] || { echo "apt attempts must be 1..3" >&2; exit 2; }
options=(-o Acquire::Retries=1 -o Acquire::ForceIPv4=true -o Acquire::http::Timeout=20
  -o Acquire::https::Timeout=20 -o Acquire::Languages=none -o DPkg::Lock::Timeout=120)
for ((attempt=1; attempt<=attempts; attempt++)); do
  if ((attempt > 1)) || [[ "${1:-}" == update ]]; then
    sudo bash ci/apt-mirror.sh "$((attempt-1))"
    if sudo timeout --kill-after=10 180 apt-get "${options[@]}" update --error-on=any; then
      :
    else
      status=$?
      echo "Mirror metadata failed on attempt $attempt/$attempts" >&2
      continue
    fi
    if [[ "${1:-}" == update ]]; then exit 0; fi
  else
    sudo bash ci/apt-mirror.sh current
  fi
  echo "Provisioning apt attempt=$attempt/$attempts packages=$*"
  if sudo env DEBIAN_FRONTEND=noninteractive timeout --kill-after=10 "${SHELL_APT_TIMEOUT_SECONDS:-600}" apt-get "${options[@]}" "$@"; then
    exit 0
  else
    status=$?
  fi
  echo "apt attempt $attempt/$attempts failed with status $status" >&2
done
exit "${status:-100}"
