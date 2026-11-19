#!/usr/bin/env bash
set -euo pipefail
mirrors=(https://archive.ubuntu.com/ubuntu/ https://mirrors.edge.kernel.org/ubuntu/ https://mirrors.mit.edu/ubuntu/)
mirror=""
if [[ "$1" != current ]]; then mirror="${mirrors[$1]}"; fi
source_root="${2:-/etc/apt}"
for path in "$source_root/sources.list" "$source_root"/sources.list.d/*.sources "$source_root"/sources.list.d/*.list; do
  [[ -f "$path" ]] || continue
  if [[ -n "$mirror" ]]; then
  sed -E "s@https?://[^[:space:]]+/ubuntu/?@$mirror@g; s@mirror\+file:/etc/apt/apt-(security-)?mirrors.txt@$mirror@g" "$path" > "$path.shell-mirror-tmp"
  mv "$path.shell-mirror-tmp" "$path"
  fi
  sed -n '\@https://.*/ubuntu/@p; /^Suites:/p; /^Components:/p' "$path"
done
printf 'Provisioning resolved Ubuntu mirror: %s\n' "${mirror:-retained from successful metadata update}"
