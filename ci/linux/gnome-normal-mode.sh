#!/usr/bin/env bash
# CI nested GNOME starts in overview on some releases. Do not send case input
# until the compositor itself confirms the normal desktop, after its animation.
set -euo pipefail
log="${1:?Pass the session probe log}"
for _ in {1..20}; do
  result="$(timeout 3 gdbus call --session --dest org.gnome.Shell \
    --object-path /org/gnome/Shell --method org.gnome.Shell.Eval \
    'Main.overview.hide(); !Main.overview.visible && !Main.overview.animationInProgress' 2>&1)" || result="Eval failed: $result"
  printf '%s\n' "$result" >> "$log"
  if [[ "$result" == "(true, 'true')" ]]; then exit 0; fi
  sleep 0.25
done
echo 'GNOME did not confirm normal desktop mode; case input is unsafe to interpret' >&2
exit 78
