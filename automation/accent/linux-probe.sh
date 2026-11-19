#!/usr/bin/env bash
set -euo pipefail

printf '{"session_type":"%s","desktop":"%s","gnome_shell":"%s"}\n' \
  "${XDG_SESSION_TYPE:-unknown}" \
  "${XDG_CURRENT_DESKTOP:-unknown}" \
  "$(gnome-shell --version 2>/dev/null || printf unknown)"

if command -v xdg-desktop-portal >/dev/null 2>&1; then
  xdg-desktop-portal --version 2>&1 || true
else
  printf 'xdg-desktop-portal executable: absent\n'
fi

if command -v dpkg-query >/dev/null 2>&1; then
  for package in xdg-desktop-portal xdg-desktop-portal-gnome; do
    dpkg-query -W -f='${Package}=${Version}\n' "$package" 2>/dev/null || true
  done
elif command -v rpm >/dev/null 2>&1; then
  for package in xdg-desktop-portal xdg-desktop-portal-gnome; do
    rpm -q "$package" 2>&1 || true
  done
fi

ps -eo args 2>/dev/null | grep '[x]dg-desktop-portal' || true

if command -v busctl >/dev/null 2>&1; then
  busctl --user introspect org.freedesktop.portal.Desktop \
    /org/freedesktop/portal/desktop org.freedesktop.portal.Settings 2>&1 || true
fi

if gsettings list-schemas 2>/dev/null | grep -qx 'org\.gnome\.desktop\.interface'; then
  if gsettings list-keys org.gnome.desktop.interface 2>/dev/null | grep -qx 'accent-color'; then
    printf 'gnome_accent_key=present\n'
    gsettings get org.gnome.desktop.interface accent-color
  else
    printf 'gnome_accent_key=absent\n'
  fi
else
  printf 'gnome_interface_schema=absent\n'
fi

gdbus call --session \
  --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop \
  --method org.freedesktop.portal.Settings.Read \
  org.freedesktop.appearance accent-color 2>&1 || true
