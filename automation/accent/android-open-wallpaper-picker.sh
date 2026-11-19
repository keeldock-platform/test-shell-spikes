#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
api=$(adb shell getprop ro.build.version.sdk | tr -d '\r')
if [ "${api:-0}" -lt 31 ]; then
  printf 'api-below-31:%s\n' "${api:-unknown}"
  exit 3
fi

# Open the platform wallpaper picker. The runner's UiAutomator script performs a real visible
# wallpaper selection and Apply action; this helper does not write resources or emit callbacks.
adb shell am start -a android.intent.action.SET_WALLPAPER
printf 'wallpaper-picker-opened:api-%s\n' "$api"
