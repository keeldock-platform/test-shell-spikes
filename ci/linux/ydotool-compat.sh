#!/usr/bin/env bash
# Preserve modern input calls when Ubuntu supplies the 0.1.x client protocol.
set -euo pipefail
bin="${SHELL_YDOTOOL_REAL:?}"
if [[ "${SHELL_YDOTOOL_LEGACY:-}" != 1 ]]; then exec "$bin" "$@"; fi
action="$1"; shift
case "$action" in
  key)
    case "$*" in
      '1:1 1:0') exec "$bin" key ESC ;;
      '28:1 28:0') exec "$bin" key ENTER ;;
      '29:1 30:1 30:0 29:0') exec "$bin" key ctrl+a ;;
      *) echo "Unsupported legacy key sequence: $*" >&2; exit 2 ;;
    esac ;;
  type)
    if [[ "${1:-}" == --key-delay ]]; then shift 2; fi
    exec "$bin" type "$@" ;;
  mousemove)
    x=0; y=0
    while (($#)); do
      case "$1" in --absolute) shift ;; --x) x="$2"; shift 2 ;; --y) y="$2"; shift 2 ;; *) exit 2 ;; esac
    done
    exec "$bin" mousemove "$x" "$y" ;;
  click)
    case "$1" in 0xC0) button=1 ;; 0xC1) button=2 ;; 0xC2) button=3 ;; *) exit 2 ;; esac
    exec "$bin" click "$button" ;;
  *) exit 2 ;;
esac
