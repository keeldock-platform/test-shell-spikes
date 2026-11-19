#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
shift || true
ydotool_bin="${YDOTOOL_BIN:-ydotool}"

case "$action" in
  move)
    x=""
    y=""
    while (($#)); do
      case "$1" in
        --x) x="${2:-}"; shift 2 ;;
        --y) y="${2:-}"; shift 2 ;;
        *) echo "unknown move option: $1" >&2; exit 2 ;;
      esac
    done
    [[ "$x" =~ ^[0-9]+$ && "$y" =~ ^[0-9]+$ ]] || { echo "move requires nonnegative --x and --y coordinates" >&2; exit 2; }
    exec "$ydotool_bin" mousemove --absolute --x "$x" --y "$y"
    ;;
  click)
    button=""
    while (($#)); do
      case "$1" in
        --button) button="${2:-}"; shift 2 ;;
        *) echo "unknown click option: $1" >&2; exit 2 ;;
      esac
    done
    case "$button" in
      1) exec "$ydotool_bin" click 0xC0 ;;
      2) exec "$ydotool_bin" click 0xC2 ;;
      3) exec "$ydotool_bin" click 0xC1 ;;
      *) echo "unsupported mouse button: $button" >&2; exit 2 ;;
    esac
    ;;
  key)
    case "${1:-}" in
      Escape) exec "$ydotool_bin" key 1:1 1:0 ;;
      *) echo "unsupported key: ${1:-}" >&2; exit 2 ;;
    esac
    ;;
  *)
    echo "usage: $0 move --x N --y N | click --button N | key Escape" >&2
    exit 2
    ;;
esac
