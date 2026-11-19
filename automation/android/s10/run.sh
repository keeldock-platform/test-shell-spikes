#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || exit 2
exec python3 automation/colour/runner.py --platform android "$@"
