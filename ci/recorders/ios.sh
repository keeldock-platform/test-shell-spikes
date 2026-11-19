#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
output="${2:-}"
pid_file="${output%.*}.pid"
log_file="${output%.*}.log"
case "$action" in
  start)
    command -v xcrun >/dev/null || { echo "xcrun is unavailable" >&2; exit 1; }
    simulator="${SHELL_IOS_SIMULATOR_UDID:-booted}"
    mkdir -p "$(dirname "$output")"
    xcrun simctl io "$simulator" recordVideo --codec=h264 "$output" >"$log_file" 2>&1 &
    recorder_pid=$!
    echo "$recorder_pid" > "$pid_file"
    sleep 2
    kill -0 "$recorder_pid"
    ;;
  stop)
    [[ -f "$pid_file" ]] || exit 0
    recorder_pid="$(cat "$pid_file")"
    kill -INT "$recorder_pid" 2>/dev/null || true
    for _ in {1..20}; do kill -0 "$recorder_pid" 2>/dev/null || break; sleep 0.25; done
    kill -KILL "$recorder_pid" 2>/dev/null || true
    rm -f "$pid_file"
    ;;
  *) echo "usage: $0 start|stop output.mp4" >&2; exit 2 ;;
esac
