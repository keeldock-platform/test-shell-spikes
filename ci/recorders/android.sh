#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
output="${2:-}"
base="${output%.*}"
pid_file="${base}.pid"
device_file="${base}.segments"
stop_file="${base}.stop"
loop_log="${base}.log"
case "$action" in
  start)
    command -v adb >/dev/null || { echo "adb is unavailable" >&2; exit 1; }
    command -v setsid >/dev/null || { echo "setsid is unavailable for Android recorder process-group control" >&2; exit 78; }
    adb wait-for-device
    rm -f "$device_file" "$stop_file"
    setsid bash -c '
      set -u
      stop_file="$1"
      device_file="$2"
      loop_log="$3"
      segment=0
      while [[ ! -f "$stop_file" ]]; do
        segment=$((segment + 1))
        device_path="/sdcard/shell-spike-$(date +%s)-${segment}.mp4"
        echo "$device_path" >> "$device_file"
        adb shell screenrecord --bit-rate 12000000 --time-limit 170 "$device_path" >>"$loop_log" 2>&1 || true
      done
    ' android-screenrecord-loop "$stop_file" "$device_file" "$loop_log" </dev/null >/dev/null 2>&1 &
    recorder_pid=$!
    echo "$recorder_pid" > "$pid_file"
    started=0
    for _ in {1..24}; do
      if adb shell pidof screenrecord >/dev/null 2>&1; then started=1; break; fi
      sleep 0.5
    done
    [[ "$started" == "1" ]] || { echo "Android screen recorder did not report a started capture" >&2; exit 1; }
    ;;
  stop)
    touch "$stop_file"
    adb shell pkill -INT screenrecord 2>/dev/null || true
    if [[ -f "$pid_file" ]]; then
      recorder_pid="$(cat "$pid_file")"
      kill -TERM -- "-$recorder_pid" 2>/dev/null || true
      for _ in {1..30}; do kill -0 -- "-$recorder_pid" 2>/dev/null || break; sleep 0.25; done
      kill -KILL -- "-$recorder_pid" 2>/dev/null || true
      for _ in {1..20}; do kill -0 -- "-$recorder_pid" 2>/dev/null || break; sleep 0.25; done
      rm -f "$pid_file"
    fi
    if [[ -f "$device_file" ]]; then
      segment=0
      while IFS= read -r device_path; do
        [[ -n "$device_path" ]] || continue
        segment=$((segment + 1))
        local_path="${base}-segment-$(printf '%03d' "$segment").mp4"
        adb pull "$device_path" "$local_path" >/dev/null || true
        adb shell rm -f "$device_path" >/dev/null 2>&1 || true
      done < "$device_file"
    fi
    python3 - "$device_file" <<'PY'
import json, sys
from pathlib import Path
source = Path(sys.argv[1])
paths = source.read_text(encoding="utf-8").splitlines() if source.exists() else []
segments = [f"{source.stem}-segment-{index:03d}.mp4" for index, _ in enumerate(paths, 1)]
index = source.parent / "index.json"
index.write_text(json.dumps({"segments": segments, "remoteSegments": paths, "continuousCapture": False, "cadenceDependentAssertions": "UNVERIFIED", "note": "screenrecord restarts between its 170-second segment limit; the restart gap cannot establish a one-frame assertion"}, indent=2) + "\n", encoding="utf-8")
PY
    rm -f "$device_file" "$stop_file" "$pid_file"
    ;;
  *) echo "usage: $0 start|stop output.mp4" >&2; exit 2 ;;
esac
