#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
output="${2:-}"
pid_file="${output%.*}.pid"
log_file="${output%.*}.log"
case "$action" in
  start)
    command -v ffmpeg >/dev/null || { echo "ffmpeg is unavailable" >&2; exit 1; }
    [[ "${SHELL_CAPTURE_DEVICE:-}" =~ ^[0-9]+:none$ ]] || { echo "No enumerated AVFoundation screen-capture device is available" >&2; exit 1; }
    mkdir -p "$(dirname "$output")"
    ffmpeg -copyts -nostdin -hide_banner -loglevel warning -y -f avfoundation -capture_cursor 1 -framerate 60 -use_wallclock_as_timestamps 1 \
      -i "$SHELL_CAPTURE_DEVICE" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -f matroska "$output" >"$log_file" 2>&1 &
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
  *) echo "usage: $0 start|stop output.mkv" >&2; exit 2 ;;
esac
