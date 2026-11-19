#!/usr/bin/env bash
# Activate the real portal on the resolved session bus before native preflight.
set -euo pipefail
log="${1:?Pass the portal readiness log}"
for _ in {1..10}; do
  if timeout 5 gdbus introspect --session --dest org.freedesktop.portal.Desktop \
      --object-path /org/freedesktop/portal/desktop > "$log" 2>&1 \
      && grep -Fq org.freedesktop.portal.Settings "$log" \
      && pgrep -af xdg-desktop-portal-gnome >> "$log" 2>&1 \
      && timeout 3 busctl --user status org.freedesktop.portal.Desktop >> "$log" 2>&1; then
    exit 0
  fi
  sleep 0.25
done
cat "$log" >&2
echo 'GNOME portal did not activate with Settings interface, backend and bus owner' >&2
exit 78
