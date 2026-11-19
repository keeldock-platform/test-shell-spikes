#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(cd -- "$script_dir/../../.." && pwd)"

: "${S03_CASE_ID:?Set S03_CASE_ID to a case id from cases/s03.json}"
: "${SHELL_SPIKES_ARTIFACT_DIR:?Set SHELL_SPIKES_ARTIFACT_DIR to this case artifact directory}"

exec python3 "$script_dir/probe.py" \
  --cases "$repo_root/cases/s03.json" \
  --case-id "$S03_CASE_ID" \
  --artifact-dir "$SHELL_SPIKES_ARTIFACT_DIR"
