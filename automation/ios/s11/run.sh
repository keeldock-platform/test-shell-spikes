#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || exit 2
exec python3 automation/accent/runner.py --platform ios "$@"
