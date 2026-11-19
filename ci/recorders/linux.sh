#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
output="${2:-}"
pid_file="${output%.*}.pid"
log_file="${output%.*}.log"
filename_file="${output%.*}.filename"
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  filename_file="$(dirname "$output")/../recorder/wayland-screencast-filename.txt"
fi

case "$action" in
  start)
    mkdir -p "$(dirname "$output")"
    if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
      command -v gdbus >/dev/null || { echo "gdbus is unavailable" >&2; exit 1; }
      gdbus introspect --session --dest org.gnome.Shell.Screencast --object-path /org/gnome/Shell/Screencast >/dev/null
      output_webm="${output%.*}.webm"
      template="${output_webm%.*}-%d.webm"
      rm -f "$filename_file"
      python3 ci/recorders/gnome-screencast.py "$template" "$filename_file" "$(dirname "$output")" >"$log_file" 2>&1 &
      recorder_pid=$!
      echo "$recorder_pid" > "$pid_file"
      for _ in {1..80}; do
        if [[ -s "$filename_file" ]]; then break; fi
        if ! kill -0 "$recorder_pid" 2>/dev/null; then cat "$log_file" >&2; exit 1; fi
        sleep 0.25
      done
      [[ -s "$filename_file" ]] || { kill -TERM "$recorder_pid" 2>/dev/null || true; cat "$log_file" >&2; exit 1; }
    else
      command -v ffmpeg >/dev/null || { echo "ffmpeg is unavailable" >&2; exit 1; }
      [[ -n "${DISPLAY:-}" ]] || { echo "X11 DISPLAY is missing" >&2; exit 1; }
      ffmpeg -copyts -nostdin -hide_banner -loglevel warning -y -f x11grab -framerate 60 -draw_mouse 1 -use_wallclock_as_timestamps 1 \
        -i "${DISPLAY}+0,0" -c:v ffv1 -pix_fmt yuv420p -f matroska "$output" >"$log_file" 2>&1 &
      recorder_pid=$!
      echo "$recorder_pid" > "$pid_file"
      sleep 2
      kill -0 "$recorder_pid"
    fi
    ;;
  stop)
    [[ -f "$pid_file" ]] || exit 0
    recorder="$(cat "$pid_file")"
    kill -INT "$recorder" 2>/dev/null || true
    for _ in {1..60}; do kill -0 "$recorder" 2>/dev/null || break; sleep 0.25; done
    kill -TERM "$recorder" 2>/dev/null || true
    for _ in {1..20}; do kill -0 "$recorder" 2>/dev/null || break; sleep 0.25; done
    kill -KILL "$recorder" 2>/dev/null || true
    rm -f "$pid_file"
    ;;
  *) echo "usage: $0 start|stop output.mkv" >&2; exit 2 ;;
esac
