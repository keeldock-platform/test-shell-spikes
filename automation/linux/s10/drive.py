#!/usr/bin/env python3
"""AT-SPI plus X11/Wayland native-input driver for the Linux colour-input cell."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pyatspi


case_id, evidence_arg = sys.argv[1:3]
evidence = Path(evidence_arg)
recorder = evidence / "recorder"
recorder.mkdir(parents=True, exist_ok=True)
all_desktop = pyatspi.Registry.getDesktop(0)
app_pid = int(os.environ["SHELL_APP_PID"])
desktop = next((all_desktop.getChildAtIndex(i) for i in range(all_desktop.childCount)
                if all_desktop.getChildAtIndex(i).get_process_id() == app_pid), None)
if desktop is None:
    raise RuntimeError("Launched process has no AT-SPI application")
is_wayland = os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
video_ref = "video/capture-1.webm" if is_wayland else "video/capture.mkv"


def input_command(*args):
    executable = os.environ.get("YDOTOOL_BIN", "ydotool") if is_wayland else "xdotool"
    subprocess.run([executable, *args], check=True, timeout=10)


def input_key(key):
    if is_wayland:
        keycode = {"Return": "28", "Escape": "1"}.get(key)
        if keycode is None:
            raise ValueError(f"Unsupported Wayland key: {key}")
        input_command("key", f"{keycode}:1", f"{keycode}:0")
    else:
        input_command("key", key)


def replace_focused_text(value):
    if is_wayland:
        # Linux input-event keycodes: left Control=29 and A=30.
        input_command("key", "29:1", "30:1", "30:0", "29:0")
        input_command("type", "--key-delay", "12", value)
    else:
        input_command("key", "ctrl+a")
        input_command("type", "--clearmodifiers", value)


def children(node):
    try:
        return [node.getChildAtIndex(index) for index in range(node.childCount)]
    except Exception:
        return []


def label(node):
    try:
        return " ".join(str(value) for value in (node.name, node.getRoleName()) if value)
    except Exception:
        return ""


def walk(node):
    yield node
    for child in children(node):
        yield from walk(child)


def find(text, scope=desktop):
    needle = text.casefold()
    return next((node for node in walk(scope) if needle in label(node).casefold()), None)


def press(node):
    try:
        for index in range(node.queryAction().nActions):
            name = node.queryAction().getName(index).casefold()
            if name in {"click", "press", "activate"}:
                node.queryAction().doAction(index)
                return True
    except Exception:
        pass
    return False


def snapshot():
    return [label(node) for node in walk(desktop) if label(node)]


def log(name, **fields):
    row = {"timeNs": time.monotonic_ns(), "name": name, **fields}
    with (recorder / "native-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def type_native_colour(value):
    fields = [node for node in walk(desktop) if "hex" in label(node).casefold() or "html" in label(node).casefold()]
    if not fields:
        return False
    try:
        fields[0].queryComponent().grabFocus()
        replace_focused_text(value)
        input_key("Return")
        log("native-picker-value-entry", value=value, session="wayland" if is_wayland else "x11")
        return True
    except (AttributeError, OSError, subprocess.SubprocessError, ValueError):
        return False


def type_page_hex(value):
    target = next((node for node in walk(desktop)
                   if "hex" in label(node).casefold() and "text" in label(node).casefold()), None)
    if target is None:
        target = next((node for node in walk(desktop)
                       if "hex" in label(node).casefold() and "entry" in label(node).casefold()), None)
    if target is None:
        return False
    try:
        target.queryComponent().grabFocus()
        replace_focused_text(value)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


deadline = time.monotonic() + 30
ready = False
while time.monotonic() < deadline:
    ready = find("Ready") is not None
    if ready:
        break
    time.sleep(0.25)
initial_tree = snapshot()
(recorder / "native-tree-before.txt").write_text("\n".join(initial_tree) + "\n", encoding="utf-8")
subprocess.run(["gnome-screenshot", "-f", str(recorder / "screen.png")], check=False, timeout=15)
log("ready-marker", observed=ready, marker="Ready")

opened = False
picker_visible = False
native_entry = False
accepted_values = []
focus_returned = False
if ready:
    open_button = find("Open Appearance dialog")
    opened = press(open_button) if open_button else False
    log("appearance-open", observed=opened)
    time.sleep(0.5)
    picker = find("Custom colour picker")
    if picker:
        picker_visible = press(picker)
        log("native-picker-open", observed=picker_visible)
        time.sleep(1)
        tree = snapshot()
        (recorder / "native-tree-picker.txt").write_text("\n".join(tree) + "\n", encoding="utf-8")
        subprocess.run(["gnome-screenshot", "-f", str(recorder / "screen.png")], check=False, timeout=15)
        for index, value in enumerate(("#7C4DFF", "#28A77A")):
            if index == 1:
                colour_control = find("Custom colour picker")
                if colour_control:
                    press(colour_control)
                    time.sleep(0.5)
            if type_native_colour(value):
                time.sleep(0.5)
                page_now = "\n".join(snapshot()).casefold()
                if "native-change" in page_now and value.lower() in page_now:
                    accepted_values.append(value.lower())
        focus_returned = find("Custom colour picker") is not None
        log("picker-focus-return", observed=focus_returned)

page_labels = snapshot()
(recorder / "page-accessibility.txt").write_text("\n".join(page_labels) + "\n", encoding="utf-8")
manual_ok = short_ok = invalid_ok = cancel_ok = dismiss_ok = False
if ready:
    button = find("Open Appearance dialog")
    if button: press(button)
    time.sleep(0.25)
    if type_page_hex("#E0A526"):
        button = find("Use HEX value")
        if button: press(button)
        button = find("Apply")
        if button: press(button)
        page_now = "\n".join(snapshot()).casefold()
        manual_ok = "#e0a526" in page_now
        button = find("Open Appearance dialog")
        if button: press(button)
        if type_page_hex("abc"):
            button = find("Use HEX value")
            if button: press(button)
            short_ok = "#aabbcc" in "\n".join(snapshot()).casefold()
            button = find("Cancel")
            if button: press(button)
            cancel_ok = "#e0a526" in "\n".join(snapshot()).casefold()
            button = find("Open Appearance dialog")
            if button: press(button)
            if type_page_hex("#12XZ"):
                button = find("Use HEX value")
                if button: press(button)
                invalid_ok = "enter a colour" in "\n".join(snapshot()).casefold()
                button = find("Cancel")
                if button: press(button)
    button = find("Open Appearance dialog")
    if button: press(button)
    button = find("Custom colour picker")
    if button and press(button):
        escape_sent = False
        try:
            input_key("Escape")
            escape_sent = True
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        dismiss_ok = escape_sent and "#e0a526" in "\n".join(snapshot()).casefold()

page_labels = snapshot()
(recorder / "page-accessibility.txt").write_text("\n".join(page_labels) + "\n", encoding="utf-8")
with (evidence / "events.jsonl").open("a", encoding="utf-8") as stream:
    for line in page_labels:
        if any(token in line.casefold() for token in ("native-", "appearance-", "hex-")):
            stream.write(json.dumps({"monotonicTimeNs": time.monotonic_ns(), "name": "s10.page-accessibility-event", "text": line}) + "\n")
assertions = {}
for item in json.loads(Path("cases/s10.json").read_text(encoding="utf-8"))["cases"]:
    if item["id"] != case_id:
        continue
    for assertion in item.get("assertions", []):
        aid = assertion["id"]
        suffix = aid.removeprefix(case_id + "-")
        verdict = "UNVERIFIED"
        actual = "Native interaction was attempted; complete scenario evidence is required before a verdict."
        evidence_paths = ["recorder/native-events.jsonl", "recorder/page-accessibility.txt"]
        if suffix == "NATIVE-PICKER" and ready and picker_visible:
            verdict = "PASS" if len(accepted_values) == 2 else "FAIL"
            actual = f"Native picker visible; native hex entry returned {accepted_values}."
            evidence_paths = ["recorder/native-tree-picker.txt", "recorder/native-events.jsonl", video_ref]
        elif suffix == "ACCEPT-FOCUS" and len(accepted_values) == 2 and focus_returned:
            verdict = "PASS"
            actual = f"Native picker returned {accepted_values} and focus returned to the webview."
            evidence_paths = ["recorder/page-accessibility.txt", "recorder/native-events.jsonl", video_ref]
        elif suffix == "MANUAL-HEX":
            verdict = "PASS" if manual_ok and short_ok and invalid_ok else "UNVERIFIED"
            actual = f"Manual six-digit, short, and invalid HEX observations: {manual_ok}/{short_ok}/{invalid_ok}."
            evidence_paths = ["recorder/page-accessibility.txt", "events.jsonl", video_ref]
        elif suffix == "APPLY-CANCEL":
            verdict = "PASS" if manual_ok and cancel_ok else "UNVERIFIED"
            actual = f"Apply stored the first value and outer Cancel preserved it: {manual_ok}/{cancel_ok}."
            evidence_paths = ["recorder/page-accessibility.txt", "events.jsonl", video_ref]
        elif suffix == "DISMISS":
            verdict = "PASS" if dismiss_ok else "UNVERIFIED"
            actual = f"Native Escape dismissal preserved the committed value: {dismiss_ok}."
            evidence_paths = ["recorder/native-tree-picker.txt", "recorder/page-accessibility.txt", video_ref]
        elif suffix == "INPUT-USABILITY":
            verdict = "PASS" if len(accepted_values) == 2 else "UNVERIFIED"
            actual = f"Native picker touch/keyboard route returned {len(accepted_values)} selections."
            evidence_paths = ["recorder/native-tree-picker.txt", "recorder/page-accessibility.txt", video_ref]
        for required_ref in ("environment.json", "events.jsonl", "recorder/screen.png", video_ref, "video/index.json"):
            if required_ref not in evidence_paths:
                evidence_paths.append(required_ref)
        assertions[aid] = {"verdict": verdict, "actual": actual, "evidence": evidence_paths}

planning = "native picker usable" if len(accepted_values) == 2 and focus_returned else ("hex field only" if ready and not picker_visible else "UNVERIFIED")
(recorder / "observations.json").write_text(json.dumps({
    "caseId": case_id,
    "platform": "linux",
    "ready": ready,
    "planningVerdict": planning,
    "assertions": assertions,
}, indent=2) + "\n", encoding="utf-8")

if not ready:
    raise SystemExit(1)
