#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EVIDENCE="${SHELL_EVIDENCE_DIR:-${SHELL_SPIKES_ARTIFACT_DIR:-}}"
CASE_ID="${SHELL_CASE_ID:-S01-CAPTURE}"
APP_PATH="${SHELL_APP_PATH:-}"
SPIKE_ID="${SHELL_SPIKE_ID:-s01}"
STATUS=0
REASON=""

if [[ -z "$EVIDENCE" ]]; then
  echo "SHELL_EVIDENCE_DIR is required" >&2
  exit 2
fi
mkdir -p "$EVIDENCE/recorder" "$EVIDENCE/video" "$EVIDENCE/screens"
EVENTS="$EVIDENCE/events.jsonl"
UI_EVENTS="$EVIDENCE/ui-events.jsonl"
ANALYSIS="$EVIDENCE/recorder/s01-analysis.json"
RESULTS="$EVIDENCE/assertions.json"
touch "$EVENTS" "$UI_EVENTS"

write_unverified() {
  local reason="$1"
  python3 - "$ROOT/cases/s01.json" "$CASE_ID" "$RESULTS" "$reason" <<'PY'
import json, sys
from pathlib import Path
case_file, case_id, output, reason = sys.argv[1:]
document = json.loads(Path(case_file).read_text(encoding="utf-8"))
definitions = {row["id"]: row for row in document.get("assertions", []) if isinstance(row, dict) and row.get("id")}
selected = {}
for case in document.get("cases", []):
    if case_id not in {"all", ""} and case.get("id") != case_id:
        continue
    for reference in case.get("assertions", []):
        identifier = reference.get("id") if isinstance(reference, dict) else reference
        if identifier in definitions:
            selected.setdefault(identifier, definitions[identifier].get("expected", ""))
if not selected:
    selected = {identifier: row.get("expected", "") for identifier, row in definitions.items()}
results = [{"id": identifier, "caseId": "S01-CAPTURE", "expected": expected,
            "actual": f"UNVERIFIED: {reason}", "verdict": "UNVERIFIED", "evidence": []}
           for identifier, expected in selected.items()]
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

if [[ "$SPIKE_ID" != "s01" ]]; then
  STATUS=2
  REASON="SHELL_SPIKE_ID must be s01"
elif [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  STATUS=2
  REASON="SHELL_APP_PATH must name the built macOS app bundle"
elif [[ "${S01_PERMISSION_PROMPT_PREFLIGHT:-}" != "passed" ]]; then
  STATUS=2
  REASON="the no-permission-prompt preflight was not recorded as passed"
elif [[ -z "${S01_XCODE_PROJECT:-}" || -z "${S01_XCODE_SCHEME:-}" ]]; then
  STATUS=2
  REASON="the coordinator must provide S01_XCODE_PROJECT and S01_XCODE_SCHEME"
else
  PLIST="$APP_PATH/Contents/Info.plist"
  if [[ ! -f "$PLIST" ]]; then
    STATUS=2
    REASON="the built app bundle has no Info.plist"
  else
    APP_BUNDLE_ID="${S01_APP_BUNDLE_ID:-$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$PLIST" 2>/dev/null || true)}"
    BUILT_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$PLIST" 2>/dev/null || true)"
    if [[ "$APP_BUNDLE_ID" != "$BUILT_BUNDLE_ID" ]]; then
      STATUS=2
      REASON="S01_APP_BUNDLE_ID disagrees with packaged CFBundleIdentifier"
    elif [[ -z "$APP_BUNDLE_ID" ]]; then
      STATUS=2
      REASON="the app bundle identifier could not be read"
    elif ! command -v xcodebuild >/dev/null 2>&1 || ! command -v swift >/dev/null 2>&1; then
      STATUS=2
      REASON="xcodebuild or swift is unavailable on the runner"
    else
      export SHELL_SPIKE_ID=s01 SHELL_CASE_ID="$CASE_ID" SHELL_EVIDENCE_DIR="$EVIDENCE"
      export S01_APP_BUNDLE_ID="$APP_BUNDLE_ID" S01_ARTIFACT_DIR="$EVIDENCE"
      export S01_PERMISSION_PROMPT_PREFLIGHT=passed
      RESULT_BUNDLE="$EVIDENCE/recorder/s01-ui-tests.xcresult"
      rm -rf "$RESULT_BUNDLE"
      set +e
      xcodebuild test \
        -project "$S01_XCODE_PROJECT" \
        -scheme "$S01_XCODE_SCHEME" \
        -destination "${S01_XCODE_DESTINATION:-platform=macOS}" \
        -resultBundlePath "$RESULT_BUNDLE" \
        "-only-testing:${S01_ONLY_TESTING_TARGET:-TrafficLightsUITests/TrafficLightsUITests/testS01TrafficLightsMatrix}" \
        "S01_APP_BUNDLE_ID=$S01_APP_BUNDLE_ID" \
        "S01_ARTIFACT_DIR=$S01_ARTIFACT_DIR" \
        "S01_PERMISSION_PROMPT_PREFLIGHT=$S01_PERMISSION_PROMPT_PREFLIGHT" \
        "SHELL_CASE_ID=$CASE_ID" \
        CODE_SIGNING_ALLOWED=NO \
        >"$EVIDENCE/recorder/s01-xcodebuild.log" 2>&1
      STATUS=$?
      if [[ $STATUS -ne 0 ]]; then
        REASON="the native UI test did not complete successfully; see recorder/s01-xcodebuild.log"
      elif [[ ! -s "$UI_EVENTS" ]] || ! python3 - "$UI_EVENTS" <<'PY'
import json, sys
from pathlib import Path
rows = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
if not any(row.get("kind") == "app-ready" and row.get("caseId") == "S01-PREFLIGHT" for row in rows):
    raise SystemExit(1)
PY
      then
        STATUS=1
        REASON="the UI test did not verify the ready marker and foreground no-prompt preflight"
      else
        # The coordinator recorder exports normalized shell-spike events from
        # the live WebView bridge into this lane-owned input path.
        NATIVE_EVENTS="${S01_NATIVE_EVENTS_SOURCE:-$EVIDENCE/recorder/s01-events.jsonl}"
        if [[ ! -s "$NATIVE_EVENTS" ]]; then
          STATUS=1
          REASON="the recorder did not provide normalized native events at recorder/s01-events.jsonl"
        else
          if ! python3 - "$NATIVE_EVENTS" "$EVENTS" <<'PY'
import json, sys
from pathlib import Path
source, destination = map(Path, sys.argv[1:])
rows = []
for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    value = json.loads(line)
    if not isinstance(value, dict):
        raise SystemExit(f"native event row {number} is not an object")
    rows.append(json.dumps(value, separators=(",", ":")))
with destination.open("a", encoding="utf-8") as stream:
    for row in rows:
        stream.write(row + "\n")
PY
          then
            STATUS=1
            REASON="the normalized S01 native event stream could not be extracted"
          elif [[ ! -s "$EVIDENCE/video/capture-index.jsonl" ]]; then
            STATUS=1
            REASON="the full-desktop recorder did not provide video/capture-index.jsonl"
          elif swift "$ROOT/automation/macos/s01/analyze_capture.swift" "$EVIDENCE" "$ROOT/cases/s01.json" >"$EVIDENCE/recorder/s01-analysis.log" 2>&1; then
            if [[ -s "$RESULTS" ]]; then mv "$RESULTS" "$ANALYSIS"; fi
          python3 - "$ROOT/cases/s01.json" "$ANALYSIS" "$RESULTS" <<'PY'
import json, sys
from pathlib import Path
case_file, source, output = map(Path, sys.argv[1:])
manifest = json.loads(case_file.read_text(encoding="utf-8"))
value = json.loads(source.read_text(encoding="utf-8"))
rows = value.get("results", value.get("assertions", [])) if isinstance(value, dict) else []
if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
    raise SystemExit("S01 analyzer output has no assertion list")
definitions = [row for row in manifest.get("assertions", []) if isinstance(row, dict) and row.get("id")]
grouped = {}
for row in rows:
    grouped.setdefault(row.get("id"), []).append(row)
declared = {row["id"] for row in definitions}
unexpected = sorted(set(grouped) - declared)
results = []
for definition in definitions:
    identifier = definition["id"]
    observations = grouped.get(identifier, [])
    if any(row.get("verdict") == "FAIL" for row in observations):
        verdict = "FAIL"
    elif not observations or any(row.get("verdict") != "PASS" for row in observations) or unexpected:
        verdict = "UNVERIFIED"
    else:
        verdict = "PASS"
    actual = " | ".join(
        f"{row.get('caseId', 'unknown-case')}: {row.get('verdict', 'UNVERIFIED')} — {row.get('actual', '')}"
        for row in observations
    ) or f"UNVERIFIED: analyzer produced no observation for {identifier}"
    if unexpected:
        actual += f"; undeclared analyzer IDs: {', '.join(unexpected)}"
    evidence = sorted({item for row in observations for item in row.get("evidence", []) if isinstance(item, str)})
    results.append({"id": identifier, "caseId": "S01-CAPTURE", "expected": definition.get("expected", ""),
                    "actual": actual, "verdict": verdict, "evidence": evidence})
Path(output).write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
PY
          else
            STATUS=1
            REASON="S01 analysis failed; see recorder/s01-analysis.log"
          fi
        fi
      fi
    fi
  fi
fi

if [[ -n "$REASON" || ! -s "$RESULTS" ]]; then
  [[ -n "$REASON" ]] || REASON="the S01 adapter did not produce analyzer results"
  write_unverified "$REASON"
  set_status "UNVERIFIED" "$REASON"
else
  set_status "complete" "S01 UI interaction, event extraction, frame analysis, and result serialization finished"
fi
exit "$STATUS"
