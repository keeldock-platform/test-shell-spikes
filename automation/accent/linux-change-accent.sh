#!/usr/bin/env bash
set -euo pipefail

requested=${1:?Pass a supported GNOME accent enum, such as purple or teal.}
schema=org.gnome.desktop.interface

if ! gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
  printf 'gnome-interface-schema-absent\n' >&2
  exit 3
fi
if ! gsettings list-keys "$schema" 2>/dev/null | grep -qx 'accent-color'; then
  printf 'gnome-accent-key-absent\n' >&2
  exit 4
fi

range=$(gsettings range "$schema" accent-color)
if ! printf '%s\n' "$range" | grep -Fq "'${requested}'"; then
  printf 'accent-not-in-enum:%s\n' "$requested" >&2
  exit 5
fi

# This updates the real GNOME preference; the portal listener must observe the resulting event.
gsettings set "$schema" accent-color "$requested"
gsettings get "$schema" accent-color
gdbus call --session \
  --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop \
  --method org.freedesktop.portal.Settings.Read \
  org.freedesktop.appearance accent-color
