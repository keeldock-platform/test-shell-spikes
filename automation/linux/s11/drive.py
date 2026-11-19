#!/usr/bin/env python3
"""Probe GNOME's real accent portal, change it when supported, and correlate host events."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


case_id, evidence_arg = sys.argv[1:3]
evidence = Path(evidence_arg)
recorder = evidence / "recorder"
recorder.mkdir(parents=True, exist_ok=True)
video_ref = "video/capture-1.webm" if os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland" else "video/capture.mkv"
probe_path = recorder / "linux-probe.txt"
change_path = recorder / "linux-change.txt"
fixture_only = case_id in {
    "S11-POLICY-WEB", "S11-MACOS-DEFAULT-BRAND-IDENTITY", "S11-CONTRAST-BOUNDARY-INJECTION",
    "S11-HIGH-CONTRAST-IGNORES-SYSTEM", "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND",
    "S11-LINUX-ABSENT-KEY", "S11-LINUX-FAULT-FALLBACKS",
}
probe = subprocess.run(["bash", "automation/accent/linux-probe.sh"], capture_output=True, text=True, timeout=90)
probe_path.write_text(probe.stdout + probe.stderr, encoding="utf-8")
key_present = "gnome_accent_key=present" in probe.stdout
def portal_rgb_from_output(output):
    triples = re.findall(r'^\s*\(<<\(\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)>>,\)\s*$', output, re.M)
    if not triples:
        return None
    values = tuple(float(value) for value in triples[-1])
    return values if all(0 <= value <= 1 for value in values) else None


probe_rgb = portal_rgb_from_output(probe.stdout)
read_present = probe.returncode == 0 and probe_rgb is not None
changed = False
if fixture_only:
    change_path.write_text("No OS setting change is required for this page fixture.\n", encoding="utf-8")
elif key_present:
    change = subprocess.run(["bash", "automation/accent/linux-change-accent.sh", "purple"],
                            capture_output=True, text=True, timeout=90)
    change_path.write_text(change.stdout + change.stderr, encoding="utf-8")
    changed = change.returncode == 0
else:
    change_path.write_text("Accent key is absent in this GNOME session; live delivery is unverified and System fallback applies.\n", encoding="utf-8")
subprocess.run(["gnome-screenshot", "-f", str(recorder / "screen.png")], check=False, timeout=15)

events_file = evidence / "events.jsonl"
event_lines = []
if events_file.is_file():
    for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            if row.get("hostPid") == int(os.environ["SHELL_APP_PID"]):
                event_lines.append(row)
        except json.JSONDecodeError:
            continue
def event_name(row):
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    return row.get("name") or row.get("event") or detail.get("name") or (row.get("fields") or {}).get("name", "")


def event_fields(row):
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    if isinstance(detail.get("fields"), dict):
        return detail["fields"]
    return row.get("fields") if isinstance(row.get("fields"), dict) else row


native = [row for row in event_lines if event_name(row) == "s11.native-event"]
updates = [row for row in event_lines if event_name(row) == "s11.host-and-token-update"]
native_sequences = {event_fields(row).get("sequence") for row in native}
matched_updates = [row for row in updates if event_fields(row).get("sequence") in native_sequences]
frame_events = [row for row in event_lines if event_fields(row).get("phase") == "tokens-mutated" or event_name(row) == "shell-spike:frame"]
ready_events = {
    "s11.listener-ready", "s11.platform-policy", "s11.clamp-result",
    "s11.high-contrast-ignored-system",
}
ready = any(event_name(row) in ready_events for row in event_lines)
reader_ready = any(event_name(row) == "s11.reader-ready" and event_fields(row).get("available") is True for row in event_lines)
initial_snapshot = next((event_fields(row) for row in event_lines if event_name(row) == "s11.initial-reader-snapshot"), {})
readback_text = change_path.read_text(encoding="utf-8", errors="replace")
portal_rgb = portal_rgb_from_output(readback_text) or probe_rgb
if portal_rgb is not None:
    (recorder / "native-readback.json").write_text(json.dumps({
        "source": "org.freedesktop.portal.Settings.Read org.freedesktop.appearance accent-color",
        "rgb": portal_rgb, "probeRgb": probe_rgb, "changed": changed,
    }, indent=2) + "\n")
current_host = event_fields(native[-1]) if native and matched_updates else initial_snapshot
host_rgb = current_host.get("rgb")
readback_matches = bool(portal_rgb and isinstance(host_rgb, list) and len(host_rgb) == 3 and
                        max(abs(portal_rgb[index] - float(host_rgb[index])) for index in range(3)) <= 1.0 / 255.0)

case_file = json.loads(Path("cases/s11.json").read_text(encoding="utf-8"))
selected = next(item for item in case_file["cases"] if item["id"] == case_id)
assertions = {}
for item in selected.get("assertions", []):
    aid = item["id"]
    suffix = aid
    verdict = "UNVERIFIED"
    actual = "Portal, host event, or presentation evidence is incomplete."
    refs = ["recorder/linux-probe.txt"]
    if suffix.endswith("-PROBE"):
        probe_valid = probe.returncode == 0 and read_present
        not_applicable = case_id == "S11-LINUX-ABSENT-KEY" and key_present
        verdict = "UNVERIFIED" if not_applicable or not probe_valid else "PASS"
        actual = f"Portal Read diagnostics recorded={probe_valid}; accent key present={key_present}; a present key is not a missing-key pass."
    elif "FALLBACK" in suffix or suffix.endswith("-BRAND"):
        fallback_case = not key_present or case_id in {
            "S11-LINUX-ABSENT-KEY", "S11-LINUX-FAULT-FALLBACKS",
            "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND", "S11-MACOS-DEFAULT-BRAND-IDENTITY",
        }
        verdict = "UNVERIFIED"
        actual = "Unavailable-reader fallback is required for this cell; the host failure mode cannot be injected by this driver." if fallback_case else "A live reader is present; fallback behavior is not established by this cell."
        refs = ["recorder/linux-probe.txt", "events.jsonl", "screens/desktop.png"]
    elif "READBACK" in suffix:
        verdict = "PASS" if read_present and changed and reader_ready and readback_matches else "UNVERIFIED"
        actual = f"Portal and host sRGB readback agree within 1/255={readback_matches}; reader ready={reader_ready}."
        refs = ["recorder/linux-probe.txt", "recorder/linux-change.txt", "events.jsonl"]
    elif "EVENT" in suffix:
        verdict = "PASS" if changed and native and matched_updates else "UNVERIFIED"
        actual = f"Real preference change observed={changed}; native events={len(native)}; sequence-matched host updates={len(matched_updates)}."
        refs = ["recorder/linux-change.txt", "events.jsonl", video_ref]
    elif "FRAME" in suffix:
        verdict = "UNVERIFIED"
        actual = f"Native-to-host sequence matches={len(matched_updates)}; renderer markers={len(frame_events)}; no frame-index correlation was produced."
        refs = ["events.jsonl", video_ref]
    elif "UPDATE" in suffix:
        verdict = "PASS" if len(native) == 1 and len(matched_updates) == 1 and event_fields(matched_updates[0]).get("reload") is False else "UNVERIFIED"
        actual = f"Native changes={len(native)}; sequence-matched host updates={len(matched_updates)}; reload=false required."
        refs = ["events.jsonl", video_ref]
    elif "PROMPT" in suffix:
        verdict = "UNVERIFIED"
        actual = "No reader permission API is used; full-screen prompt inspection requires the hosted capture."
        refs = ["recorder/linux-probe.txt", video_ref]
    elif case_id == "S11-LINUX-FAULT-FALLBACKS":
        verdict = "UNVERIFIED"
        actual = "Portal service, key, malformed-response, and subscription failure injection is unavailable in this host driver; System fallback remains selected for the result."
        refs = ["recorder/linux-probe.txt", "events.jsonl", "recorder/screen.png", video_ref]
    elif case_id == "S11-CONTRAST-BOUNDARY-INJECTION" and aid == "S11-CONTRAST-CLAMP":
        clamp = next((event_fields(row) for row in event_lines if event_name(row) == "s11.clamp-result"), {})
        clamped = bool(clamp.get("clamped") or (clamp.get("clampTarget") not in (None, "none")))
        verdict = "PASS" if clamped else "UNVERIFIED"
        actual = f"Synthetic boundary injection clamp outcome observed={clamped}; it does not prove native delivery."
        refs = ["events.jsonl"]
    elif case_id == "S11-CONTRAST-BOUNDARY-INJECTION" and aid == "S11-CONTRAST-NATIVE":
        boundary = next((event_fields(row) for row in event_lines if event_name(row) == "s11.boundary-injection"), {})
        non_native = boundary.get("nativeEvent") is False
        verdict = "PASS" if non_native else "UNVERIFIED"
        actual = f"Boundary sample is explicitly non-native={non_native}."
        refs = ["events.jsonl"]
    elif case_id == "S11-HIGH-CONTRAST-IGNORES-SYSTEM" and aid == "S11-HIGH-CONTRAST-IGNORED":
        sample = next((event_fields(row) for row in event_lines if event_name(row) == "s11.high-contrast-ignored-system"), {})
        ignored = sample.get("resolvedSource") == "high-contrast-theme"
        verdict = "PASS" if ignored else "UNVERIFIED"
        actual = f"High-contrast preview resolved independently of System={ignored}."
        refs = ["events.jsonl", video_ref]
    elif case_id == "S11-POLICY-WEB" and aid == "S11-POLICY-WEB-HIDDEN":
        policy = next((event_fields(row) for row in event_lines if event_name(row) == "s11.platform-policy"), {})
        hidden = policy.get("platform") == "web" and policy.get("systemVisible") is False
        verdict = "PASS" if hidden else "UNVERIFIED"
        actual = f"Web policy fixture hid System without a native read={hidden}."
        refs = ["events.jsonl", video_ref]
    elif case_id == "S11-SYSTEM-UNAVAILABLE-RESOLVES-BRAND" and aid == "S11-SYSTEM-UNAVAILABLE-BRAND":
        verdict = "UNVERIFIED"
        actual = "System hidden/brand fallback selected; visible page evidence is required to confirm it."
        refs = ["events.jsonl", video_ref]
    elif "CLAMP" in suffix:
        clamped = any(event_name(row) == "s11.host-and-token-update" and event_fields(row).get("clamped") is True for row in event_lines)
        verdict = "PASS" if clamped else "UNVERIFIED"
        actual = f"Observed native updates with an applied contrast clamp={clamped}."
        refs = ["recorder/linux-probe.txt", "events.jsonl", "recorder/screen.png", video_ref]
    for required_ref in ("environment.json", "events.jsonl", "recorder/screen.png", video_ref, "video/index.json"):
        if required_ref not in refs:
            refs.append(required_ref)
    assertions[aid] = {"verdict": verdict, "actual": actual, "evidence": refs}

fallback = "System hidden; stored System resolves to the test brand colour."
planning = "native accent reader available" if changed and native else "UNVERIFIED"
(recorder / "observations.json").write_text(json.dumps({
    "caseId": case_id, "platform": "linux", "ready": ready,
    "planningVerdict": planning, "fallback": fallback, "assertions": assertions,
}, indent=2) + "\n", encoding="utf-8")
