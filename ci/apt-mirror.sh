#!/usr/bin/env bash
set -euo pipefail
# Match archive origins exactly: vendor URLs can also contain /ubuntu/.
mirrors=(http://archive.ubuntu.com/ubuntu/ http://mirrors.edge.kernel.org/ubuntu/ http://mirrors.mit.edu/ubuntu/)
selection="${1:-current}"
source_root="${2:-/etc/apt}"
mirror=""
if [[ "$selection" != current ]]; then
  [[ "$selection" =~ ^[0-2]$ ]] || exit 2
  mirror="${mirrors[$selection]}"
fi
for path in "$source_root/sources.list" "$source_root"/sources.list.d/*.sources "$source_root"/sources.list.d/*.list; do
  [[ -f "$path" ]] || continue
  if [[ -n "$mirror" ]]; then
    # Keep distro suites, components and archive signing keys intact.
    sed -E "s@https?://(([a-z0-9.-]+\.)?archive\.ubuntu\.com|security\.ubuntu\.com|mirrors\.edge\.kernel\.org|mirrors\.mit\.edu)/ubuntu/?([[:space:]]|$)@$mirror\\3@g; s@mirror\+file:/etc/apt/apt-(security-)?mirrors.txt@$mirror@g" "$path" > "$path.shell-mirror-tmp"
    mv "$path.shell-mirror-tmp" "$path"
  fi
  cat "$path"
done
printf 'Provisioning resolved Ubuntu mirror: %s\n' "${mirror:-retained from successful metadata update}"
