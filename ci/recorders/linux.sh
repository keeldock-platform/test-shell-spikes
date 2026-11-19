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
      start_result="$(gdbus call --session --dest org.gnome.Shell.Screencast --object-path /org/gnome/Shell/Screencast \
        --method org.gnome.Shell.Screencast.Screencast "$template" "{'framerate': <60>, 'draw-cursor': <true>}" 2>"$log_file")"
      printf '%s\n' "$start_result" >>"$log_file"
      python3 - "$start_result" "$filename_file" "$(dirname "$output")" <<'PY'
import re, sys
from pathlib import Path

result, destination, allowed_directory = sys.argv[1:]
match = re.fullmatch(r"\s*\(\s*(true|false)\s*,\s*'((?:[^'\\]|\\.)*)'\s*\)\s*", result, re.IGNORECASE)
if not match or match.group(1).lower() != "true":
    raise SystemExit("GNOME Screencast did not return a true start result and filename")
filename = match.group(2).replace("\\'", "'").replace("\\\\", "\\")
path = Path(filename)
if not path.is_absolute() or path.suffix.lower() != ".webm":
    raise SystemExit("GNOME Screencast returned a non-absolute or non-WebM filename")
try:
    path.resolve().relative_to(Path(allowed_directory).resolve())
except ValueError:
    raise SystemExit("GNOME Screencast returned a filename outside the case video directory")
Path(destination).write_text(str(path) + "\n", encoding="utf-8")
PY
      echo "gnome-shell-screencast" > "$pid_file"
    else
      command -v ffmpeg >/dev/null || { echo "ffmpeg is unavailable" >&2; exit 1; }
      [[ -n "${DISPLAY:-}" ]] || { echo "X11 DISPLAY is missing" >&2; exit 1; }
      ffmpeg -copyts -nostdin -hide_banner -loglevel warning -y -f x11grab -framerate 60 -draw_mouse 1 -use_wallclock_as_timestamps 1 \
        -i "${DISPLAY}+0,0" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -f matroska "$output" >"$log_file" 2>&1 &
      recorder_pid=$!
      echo "$recorder_pid" > "$pid_file"
      sleep 2
      kill -0 "$recorder_pid"
    fi
    ;;
  stop)
    [[ -f "$pid_file" ]] || exit 0
    recorder="$(cat "$pid_file")"
    if [[ "$recorder" == "gnome-shell-screencast" ]]; then
      gdbus call --session --dest org.gnome.Shell.Screencast --object-path /org/gnome/Shell/Screencast \
        --method org.gnome.Shell.Screencast.StopScreencast >>"$log_file" 2>&1
    else
      kill -INT "$recorder" 2>/dev/null || true
      for _ in {1..20}; do kill -0 "$recorder" 2>/dev/null || break; sleep 0.25; done
      kill -KILL "$recorder" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    ;;
  *) echo "usage: $0 start|stop output.mkv" >&2; exit 2 ;;
esac
