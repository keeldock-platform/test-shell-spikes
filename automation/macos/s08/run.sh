#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EVIDENCE="${SHELL_EVIDENCE_DIR:-${SHELL_SPIKES_ARTIFACT_DIR:-}}"
CASE_ID="${SHELL_CASE_ID:-}"
APP_PATH="${SHELL_APP_PATH:-}"
SPIKE_ID="${SHELL_SPIKE_ID:-s08}"
APP_PID=""
STATUS=0
REASON=""

if [[ -z "$EVIDENCE" ]]; then
  echo "SHELL_EVIDENCE_DIR is required" >&2
  exit 2
fi
mkdir -p "$EVIDENCE/recorder" "$EVIDENCE/screens" "$EVIDENCE/video"
EVENTS="$EVIDENCE/events.jsonl"
RESULTS="$EVIDENCE/assertions.json"
READY_EVENTS="$EVIDENCE/recorder/s08-ready-events.jsonl"
CASE_EVENTS="$EVIDENCE/recorder/s08-case-events.jsonl"
rm -f "$EVIDENCE/recorder/shutdown-request" "$EVIDENCE/recorder/shutdown-flushed"
touch "$EVENTS"

stop_app() {
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    touch "$EVIDENCE/recorder/shutdown-request"
    for _ in {1..50}; do
      [[ -f "$EVIDENCE/recorder/shutdown-flushed" ]] && break
      sleep 0.1
    done
    kill -TERM "$APP_PID" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$APP_PID" 2>/dev/null || break
      sleep 0.25
    done
    kill -KILL "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap stop_app EXIT

write_unverified() {
  local reason="$1"
  python3 - "$ROOT/cases/s08.json" "$CASE_ID" "$RESULTS" "$reason" <<'PY'
import json, sys
from pathlib import Path
case_file, case_id, output, reason = sys.argv[1:]
document = json.loads(Path(case_file).read_text(encoding="utf-8"))
definitions = {row["id"]: row for row in document.get("assertions", []) if isinstance(row, dict) and row.get("id")}
selected = []
for case in document.get("cases", []):
    if case_id not in {"all", ""} and case.get("id") != case_id:
        continue
    for reference in case.get("assertions", []):
        identifier = reference.get("id") if isinstance(reference, dict) else reference
        if isinstance(reference, dict):
            selected.append((identifier, reference.get("expected", ""), case.get("id", case_id)))
        elif identifier in definitions:
            selected.append((identifier, definitions[identifier].get("expected", ""), case.get("id", case_id)))
if not selected:
    selected = [(identifier, row.get("expected", ""), case_id) for identifier, row in definitions.items()]
results = [{"id": identifier, "caseId": case, "expected": expected,
            "actual": f"UNVERIFIED: {reason}", "verdict": "UNVERIFIED", "evidence": []}
           for identifier, expected, case in selected]
Path(output).write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
PY
}

set_status() {
  local status="$1" reason="$2"
  python3 - "$EVIDENCE/recorder/adapter-status.json" "$status" "$reason" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"status": sys.argv[2], "reason": sys.argv[3]}, indent=2) + "\n", encoding="utf-8")
PY
}

case "$CASE_ID" in
  S08-MAC-01-entry-instance) SCENARIO=entry ;;
  S08-MAC-02-tool-settings-entry) SCENARIO=tool-settings ;;
  S08-MAC-03-parented-sheet-and-inactive-main) SCENARIO=sheet ;;
  S08-MAC-04-window-state-and-view-restore) SCENARIO=geometry ;;
  S08-MAC-05-mock-lock-destroys-settings) SCENARIO=mock-lock ;;
  S08-MAC-06-capability-and-host-allowlist) SCENARIO=permissions ;;
  *) SCENARIO="" ;;
esac

if [[ "$SPIKE_ID" != "s08" ]]; then
  STATUS=2
  REASON="SHELL_SPIKE_ID must be s08"
elif [[ -z "$SCENARIO" ]]; then
  STATUS=2
  REASON="SHELL_CASE_ID does not name an S08 native case"
elif [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  STATUS=2
  REASON="SHELL_APP_PATH must name the built macOS app bundle"
elif [[ ! -f "$APP_PATH/Contents/Info.plist" ]]; then
  STATUS=2
  REASON="the built app bundle has no Info.plist"
elif ! command -v swift >/dev/null 2>&1; then
  STATUS=2
  REASON="swift is unavailable on the runner"
else
  APP_BUNDLE_ID="${S08_APP_BUNDLE_ID:-$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)}"
  EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c 'Print CFBundleExecutable' "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
  EXECUTABLE="$APP_PATH/Contents/MacOS/$EXECUTABLE_NAME"
  if [[ -z "$APP_BUNDLE_ID" || -z "$EXECUTABLE_NAME" || ! -x "$EXECUTABLE" ]]; then
    STATUS=2
    REASON="the app bundle identifier or executable could not be resolved"
  else
    export SHELL_SPIKE_ID=s08 SHELL_CASE_ID="$CASE_ID" SHELL_EVIDENCE_DIR="$EVIDENCE" SHELL_APP_BUNDLE_ID="$APP_BUNDLE_ID"
    "$EXECUTABLE" >"$EVIDENCE/recorder/s08-app.log" 2>&1 &
    APP_PID=$!
    if swift "$ROOT/automation/macos/s08/probe.swift" --scenario ready --bundle-id "$APP_BUNDLE_ID" --events "$READY_EVENTS" >"$EVIDENCE/recorder/s08-ready.log" 2>&1; then
      if swift "$ROOT/automation/macos/s08/probe.swift" --scenario "$SCENARIO" --bundle-id "$APP_BUNDLE_ID" --events "$CASE_EVENTS" >"$EVIDENCE/recorder/s08-probe.log" 2>&1; then
        python3 - "$READY_EVENTS" "$CASE_EVENTS" "$EVENTS" <<'PY'
import json, sys
from pathlib import Path
ready, case, destination = map(Path, sys.argv[1:])
with destination.open("a", encoding="utf-8") as stream:
    for source in (ready, case):
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SystemExit(f"S08 event row {number} is not an object")
            stream.write(json.dumps(value, separators=(",", ":")) + "\n")
PY
        python3 "$ROOT/automation/macos/s08/reduce.py" "$ROOT/cases/s08.json" "$CASE_ID" "$CASE_EVENTS" "$RESULTS" "$EVIDENCE"
      else
        STATUS=1
        REASON="the native S08 interaction failed; see recorder/s08-probe.log"
      fi
    else
      STATUS=1
      REASON="the S08 ready marker or Accessibility preflight failed; see recorder/s08-ready.log"
    fi
  fi
fi

if [[ -n "$REASON" || ! -s "$RESULTS" ]]; then
  [[ -n "$REASON" ]] || REASON="the S08 adapter did not produce result rows"
  write_unverified "$REASON"
  set_status "UNVERIFIED" "$REASON"
else
  set_status "complete" "S08 app launch, ready check, native interaction, event extraction, and result serialization finished"
fi
exit "$STATUS"
