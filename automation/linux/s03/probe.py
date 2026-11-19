#!/usr/bin/env python3
"""S03 native menu probe; run only inside the one hosted Linux GUI wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath


WINDOW_MENU_ITEMS = {
    "Minimize",
    "Move",
    "Resize",
    "Always on Top",
    "Always on Visible Workspace",
    "Close",
}
POLL_SECONDS = 0.04
MENU_TIMEOUT_SECONDS = 1.5
NEGATIVE_OBSERVATION_SECONDS = 0.7
EVENT_SEQUENCE = 300_000


class ProbeUnavailable(RuntimeError):
    """Required evidence or runner capability is unavailable."""


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_event(artifact_dir: Path, case_id: str, event_name: str, fields: dict) -> int:
    global EVENT_SEQUENCE
    EVENT_SEQUENCE += 1
    event = {
        "seq": EVENT_SEQUENCE,
        "monotonicNs": time.monotonic_ns(),
        "caseId": case_id,
        "event": event_name,
        **fields,
    }
    path = artifact_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return EVENT_SEQUENCE


def read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line or raw_line.startswith("#"):
            continue
        key, value = raw_line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def command_output(argv: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def process_present(pattern: str) -> bool:
    code, output = command_output(["pgrep", "-af", pattern])
    print("S03 process probe: " + json.dumps({"pattern": pattern, "exit": code, "output": output}), flush=True)
    if code != 0:
        return False
    return any(pattern not in line or "pgrep -af" not in line for line in output.splitlines())


def check_session(case: dict, artifact_dir: Path) -> tuple[dict, list[str], object]:
    errors: list[str] = []
    environment: dict[str, object] = {
        "caseId": case["id"],
        "platform": case["platform"],
        "distributionExpected": case["distribution"],
        "distributionActual": read_os_release(),
        "distributionVersionExpected": os.environ.get("S03_FEDORA_VERSION_ID", "") if case["distribution"] == "fedora-current" else "24.04",
        "sessionExpected": case["session"],
        "sessionActual": os.environ.get("XDG_SESSION_TYPE", ""),
        "displayScale": os.environ.get("S03_DISPLAY_SCALE", ""),
        "display": os.environ.get("DISPLAY", "") if case["session"] == "x11" else "",
        "waylandDisplayPresent": bool(os.environ.get("WAYLAND_DISPLAY")),
        "sessionBusPresent": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
        "gnomeShellPresent": process_present("gnome-shell"),
        "portalBackendPresent": process_present("xdg-desktop-portal-gnome"),
        "portalService": command_output(["busctl", "--user", "status", "org.freedesktop.portal.Desktop"])[0] == 0,
        "inputBackend": "XTest" if case["session"] == "x11" else os.environ.get("S03_WAYLAND_INPUT_BACKEND", ""),
        "sourceOsReleaseRecorded": case["distribution"] != "fedora-current" or Path("/etc/os-release").exists(),
    }
    os_release = environment["distributionActual"]
    if not environment["gnomeShellPresent"]:
        errors.append("GNOME Shell/Mutter process is not present")
    if not environment["sessionBusPresent"]:
        errors.append("session D-Bus is unavailable")
    if not environment["portalBackendPresent"] or not environment["portalService"]:
        errors.append("GNOME XDG portal backend/service is unavailable")
    if environment["sessionActual"] != case["session"]:
        errors.append(f"expected {case['session']} session, got {environment['sessionActual']!r}")
    if case["distribution"] == "ubuntu-24.04":
        if os_release.get("ID", "").lower() != "ubuntu" or os_release.get("VERSION_ID") != "24.04":
            errors.append("the active guest is not Ubuntu 24.04")
    elif case["distribution"] == "fedora-current":
        if os_release.get("ID", "").lower() != "fedora":
            errors.append("the active guest is not Fedora")
        frozen_version = os.environ.get("S03_FEDORA_VERSION_ID", "")
        if not frozen_version or os_release.get("VERSION_ID") != frozen_version:
            errors.append("Fedora VERSION_ID does not match the release frozen in the CI environment lock")
    if environment["displayScale"] != "1":
        errors.append("S03_DISPLAY_SCALE must be set to 1 for the 1:1 coordinate evidence")

    if case["session"] == "x11":
        if not environment["display"]:
            errors.append("X11 DISPLAY is unset")
        if shutil.which("xdotool") is None:
            errors.append("xdotool is unavailable for XTest input")
        code, extensions = command_output(["xdpyinfo", "-queryExtensions"])
        environment["xtestExtension"] = code == 0 and "XTEST" in extensions
        if not environment["xtestExtension"]:
            errors.append("the X server does not report the XTEST extension")
    else:
        if not environment["waylandDisplayPresent"]:
            errors.append("WAYLAND_DISPLAY is unset")
        helper = os.environ.get("S03_WAYLAND_INPUT", "")
        backend = environment["inputBackend"]
        if not helper or not Path(helper).is_file() or backend not in {"libei", "uinput"}:
            errors.append("runner virtual input helper with libei or uinput backend is unavailable")

    if not environment["sourceOsReleaseRecorded"]:
        errors.append("Fedora /etc/os-release is unavailable")

    try:
        import pyatspi  # type: ignore[import-not-found]

        desktop = pyatspi.Registry.getDesktop(0)
        _ = desktop.childCount
        environment["atSpiAvailable"] = True
    except Exception as error:  # AT-SPI errors vary by distro and session bus state.
        pyatspi = None
        desktop = None
        environment["atSpiAvailable"] = False
        errors.append(f"AT-SPI desktop discovery unavailable: {type(error).__name__}")

    video_ref = safe_artifact_ref(os.environ.get("S03_CAPTURE_VIDEO_REF", "video/desktop.mp4"))
    environment["videoEvidenceRef"] = video_ref
    if not video_ref:
        errors.append("the whole-compositor recorder did not provide a safe video evidence reference")
    write_json(artifact_dir / "automation" / "s03" / "session-preflight.json", environment)
    return environment, errors, (pyatspi, desktop)


def safe_artifact_ref(value: str) -> str | None:
    if not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    if path.parts[0] not in {"screens", "video", "recorder"}:
        return None
    return path.as_posix()


def accessible_children(node):
    try:
        count = node.childCount
    except Exception:
        return
    for index in range(count):
        try:
            child = node.getChildAtIndex(index)
        except Exception:
            continue
        if child is not None:
            yield child


def walk_accessible(root, max_depth: int = 24):
    stack = [(root, 0)]
    visited = 0
    while stack and visited < 30_000:
        current, depth = stack.pop()
        visited += 1
        yield current
        if depth < max_depth:
            stack.extend((child, depth + 1) for child in accessible_children(current))


def accessible_name(node) -> str:
    try:
        return (node.name or "").strip()
    except Exception:
        return ""


def accessible_role(node) -> str:
    try:
        return (node.getRoleName() or "").strip().lower()
    except Exception:
        return ""


def accessible_rect(node, pyatspi):
    try:
        rect = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
        result = {"x": int(rect.x), "y": int(rect.y), "width": int(rect.width), "height": int(rect.height)}
        if result["width"] > 0 and result["height"] > 0:
            return result
    except Exception:
        return None
    return None


def accessible_description(node) -> str:
    try:
        return (node.description or "").strip()
    except Exception:
        return ""


def accessible_window_rect(node, pyatspi):
    parent = node
    for _ in range(24):
        if accessible_role(parent) in {"frame", "window"}:
            rect = accessible_rect(parent, pyatspi)
            if rect:
                return rect
        try:
            parent = parent.parent
        except Exception:
            break
    return None


def accessible_snapshot(node, pyatspi) -> dict:
    entries = []
    for descendant in walk_accessible(node, max_depth=12):
        name = accessible_name(descendant)
        role = accessible_role(descendant)
        if name or role:
            entries.append({"role": role, "name": name, "bounds": accessible_rect(descendant, pyatspi)})
    return {
        "role": accessible_role(node),
        "name": accessible_name(node),
        "description": accessible_description(node),
        "bounds": accessible_rect(node, pyatspi),
        "descendants": entries,
    }


def find_named(desktop, pyatspi, name: str, role_hint: str | None = None):
    for node in walk_accessible(desktop):
        if accessible_name(node) == name and (role_hint is None or role_hint in accessible_role(node)):
            rect = accessible_rect(node, pyatspi)
            if rect:
                return node, rect
    return None, None


def has_named_node(desktop, name: str, role_hint: str | None = None) -> bool:
    for node in walk_accessible(desktop):
        if accessible_name(node) == name and (role_hint is None or role_hint in accessible_role(node)):
            return True
    return False


def descendants_by_name(node):
    result = {}
    for descendant in walk_accessible(node, max_depth=12):
        name = accessible_name(descendant)
        if name:
            result.setdefault(name, []).append(descendant)
    return result


def is_showing(node, pyatspi) -> bool:
    try:
        state = node.getState()
        return state.contains(pyatspi.STATE_VISIBLE) or state.contains(pyatspi.STATE_SHOWING)
    except Exception:
        return False


def find_menu(desktop, pyatspi, fallback: bool = False):
    for node in walk_accessible(desktop):
        if "menu" not in accessible_role(node) or not is_showing(node, pyatspi):
            continue
        name = accessible_name(node)
        if fallback != (name == "Window actions"):
            continue
        named = descendants_by_name(node)
        labels = set(named)
        if fallback and {"Minimize", "Close"}.issubset(labels):
            bounds = accessible_rect(node, pyatspi)
            if bounds:
                return node, bounds, named
        if not fallback and labels.intersection(WINDOW_MENU_ITEMS | {"Maximize", "Restore"}):
            bounds = accessible_rect(node, pyatspi)
            if bounds:
                return node, bounds, named
    return None


def visible_menu_candidates(desktop, pyatspi) -> list[dict]:
    candidates = []
    for node in walk_accessible(desktop):
        if "menu" not in accessible_role(node) or not is_showing(node, pyatspi):
            continue
        snapshot = accessible_snapshot(node, pyatspi)
        labels = {entry["name"] for entry in snapshot["descendants"] if entry["name"]}
        if snapshot["name"] == "Window actions" or labels.intersection(WINDOW_MENU_ITEMS | {"Maximize", "Restore"}):
            candidates.append(snapshot)
    return candidates


def wait_until(predicate, timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(POLL_SECONDS)
    return last_value


def inject_input(session: str, action: str, *, x: int | None = None, y: int | None = None, button: int = 3, key: str | None = None) -> None:
    if session == "x11":
        if action == "click":
            subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], check=True, timeout=5)
            subprocess.run(["xdotool", "click", "--clearmodifiers", str(button)], check=True, timeout=5)
        elif action == "key":
            subprocess.run(["xdotool", "key", "--clearmodifiers", key or "Escape"], check=True, timeout=5)
        return

    helper = os.environ["S03_WAYLAND_INPUT"]
    if action == "click":
        subprocess.run([helper, "move", "--x", str(x), "--y", str(y)], check=True, timeout=5)
        subprocess.run([helper, "click", "--button", str(button)], check=True, timeout=5)
    elif action == "key":
        subprocess.run([helper, "key", key or "Escape"], check=True, timeout=5)


def point_in_rect(point: dict, rect: dict) -> bool:
    return (
        rect["x"] <= point["x"] < rect["x"] + rect["width"]
        and rect["y"] <= point["y"] < rect["y"] + rect["height"]
    )


def target_point(node, rect: dict, pyatspi, artifact_dir: Path, case_id: str, target_name: str) -> tuple[dict, int, dict | None]:
    point = {"x": rect["x"] + rect["width"] // 2, "y": rect["y"] + rect["height"] // 2}
    description = accessible_description(node)
    scale_ok = "devicePixelRatio=1" in description and "cssToGdkScale=1" in description
    if target_name == "Empty header area":
        scale_probe = {"description": description, "scaleConfirmed": scale_ok,
                       "target": accessible_snapshot(node, pyatspi)}
        write_json(artifact_dir / "recorder/s03-scale-probe.json", scale_probe)
        print("S03 accessibility scale probe: " + json.dumps(scale_probe), flush=True)
        if not scale_ok:
            raise ProbeUnavailable("AT-SPI did not expose the 1:1 CSS/GDK scale description")

    window_rect = accessible_window_rect(node, pyatspi)

    geometry = {
        "caseId": case_id,
        "target": target_name,
        "targetBoundsDesktop": rect,
        "pointerDesktop": point,
        "windowBoundsDesktop": window_rect,
        "coordinateMapping": {
            "displayScale": 1,
            "devicePixelRatio": 1,
            "cssToGdkScale": 1,
            "desktopToWebview": "subtract windowBoundsDesktop.x/y; then apply 1:1 scale",
            "pointerWebviewLogicalEstimate": None if window_rect is None else {
                "x": point["x"] - window_rect["x"],
                "y": point["y"] - window_rect["y"],
            },
        },
    }
    seq = append_event(artifact_dir, case_id, "s03-input-target", {
        "target": target_name,
        "button": 3,
        "pointerDesktop": point,
        "targetBoundsDesktop": rect,
        "windowBoundsDesktop": window_rect,
        "cssToGdkScale": 1,
        "devicePixelRatio": 1,
    })
    geometry_path = artifact_dir / "geometry" / f"{case_id}-target-{seq}.json"
    write_json(geometry_path, geometry)
    return point, seq, window_rect


def native_tree_and_geometry(artifact_dir: Path, case_id: str, label: str, seq: int, node, bounds: dict, named: dict, pyatspi, point: dict, target_rect: dict, window_rect: dict | None) -> tuple[str, str]:
    tree_relative = f"native-tree/{case_id}-{label}-{seq}.json"
    geometry_relative = f"geometry/{case_id}-{label}-{seq}.json"
    write_json(artifact_dir / tree_relative, accessible_snapshot(node, pyatspi))
    geometry = {
        "caseId": case_id,
        "checkpoint": label,
        "pointerDesktop": point,
        "popupBoundsDesktop": bounds,
        "pointerInsidePopup": point_in_rect(point, bounds),
        "targetBoundsDesktop": target_rect,
        "windowBoundsDesktop": window_rect,
        "coordinateMapping": {
            "displayScale": 1,
            "devicePixelRatio": 1,
            "cssToGdkScale": 1,
            "desktopToWebview": "subtract windowBoundsDesktop.x/y; then apply 1:1 scale",
        },
        "accessibleMenuLabels": sorted(named),
    }
    write_json(artifact_dir / geometry_relative, geometry)
    return tree_relative, geometry_relative


def result_record(definition: dict, verdict: str, actual: str, evidence: list[str]) -> dict:
    return {
        "id": definition["id"],
        "expected": definition["expected"],
        "actual": actual,
        "verdict": verdict,
        "evidence": evidence,
    }


def artifact_evidence(artifact_dir: Path, case_id: str, checkpoint: str, seq: int, sources: list[str], local_refs: list[str]) -> list[str]:
    evidence = list(local_refs)
    if "screen" in sources:
        screen_ref = f"screens/{case_id}-{checkpoint}.png"
        screen_path = artifact_dir / screen_ref
        try:
            image = screen_path.read_bytes()
        except OSError as error:
            raise ProbeUnavailable(f"required whole-compositor screenshot is missing: {screen_ref}") from error
        if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n":
            raise ProbeUnavailable(f"required whole-compositor screenshot is not a valid PNG: {screen_ref}")
        width, height = struct.unpack(">II", image[16:24])
        if width <= 0 or height <= 0:
            raise ProbeUnavailable(f"required whole-compositor screenshot has invalid dimensions: {screen_ref}")
        evidence.append(screen_ref)
    if "video" in sources:
        evidence.append(safe_artifact_ref(os.environ.get("S03_CAPTURE_VIDEO_REF", "video/desktop.mp4")) or "video/desktop.mp4")
    if "events.jsonl" in sources:
        evidence.append(f"events.jsonl#seq={seq}")
    return evidence


def case_assertion(case: dict, suffix: str) -> dict:
    for assertion in case["assertions"]:
        if assertion["id"].endswith(suffix):
            return assertion
    raise ProbeUnavailable(f"case has no assertion ending in {suffix!r}")


def emit_capture_point(artifact_dir: Path, case_id: str, checkpoint: str, point: dict, target: str) -> int:
    screen_ref = f"screens/{case_id}-{checkpoint}.png"
    screenshot_tool = os.environ.get("S03_SCREENSHOT_TOOL", "gnome-screenshot")
    screenshot_path = artifact_dir / screen_ref
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [screenshot_tool, f"--file={screenshot_path}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProbeUnavailable(f"whole-desktop screenshot failed at {checkpoint}: {type(error).__name__}") from error
    if completed.returncode != 0 or not screenshot_path.is_file():
        detail = (completed.stderr or completed.stdout).strip()[:240]
        raise ProbeUnavailable(f"whole-desktop screenshot failed at {checkpoint}: {detail or 'no PNG was written'}")
    image = screenshot_path.read_bytes()
    if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n":
        raise ProbeUnavailable(f"whole-desktop screenshot at {checkpoint} is not a PNG")
    width, height = struct.unpack(">II", image[16:24])
    if width <= 0 or height <= 0:
        raise ProbeUnavailable(f"whole-desktop screenshot at {checkpoint} has invalid dimensions")
    return append_event(artifact_dir, case_id, "s03-capture-point", {
        "checkpoint": checkpoint,
        "screenRef": screen_ref,
        "screenCapture": "gnome-screenshot whole desktop",
        "captureScope": "whole-compositor",
        "pixelSize": [width, height],
        "sha256": hashlib.sha256(image).hexdigest(),
        "pointerDesktop": point,
        "target": target,
    })


def click_accessible(desktop, pyatspi, case: dict, artifact_dir: Path, session: str, name: str, button: int) -> tuple[dict, int, dict, object, dict | None]:
    node, rect = find_named(desktop, pyatspi, name)
    if node is None or rect is None:
        raise ProbeUnavailable(f"AT-SPI target {name!r} is unavailable")
    point, seq, window_rect = target_point(node, rect, pyatspi, artifact_dir, case["id"], name)
    inject_input(session, "click", x=point["x"], y=point["y"], button=button)
    append_event(artifact_dir, case["id"], "s03-input-sent", {
        "target": name,
        "button": button,
        "pointerDesktop": point,
        "targetEventSeq": seq,
    })
    return point, seq, rect, node, window_rect


def make_unverified(case: dict, reason: str) -> list[dict]:
    return [result_record(assertion, "UNVERIFIED", reason, []) for assertion in case["assertions"]]


def run_required_cell(case: dict, artifact_dir: Path, pyatspi, desktop) -> list[dict]:
    case_id = case["id"]
    results: dict[str, dict] = {}
    # WebKit exposes ARIA regions as AT-SPI landmarks on some releases.
    # Qualify by the exact accessible name and measured bounds, after startup.
    found = wait_until(lambda: (lambda pair: pair if pair[0] is not None else None)(
        find_named(desktop, pyatspi, "Empty header area")), 20.0)
    header, header_rect = found or (None, None)
    if header is None or header_rect is None:
        write_json(artifact_dir / "recorder/s03-startup-tree.json", accessible_snapshot(desktop, pyatspi))
        raise ProbeUnavailable("AT-SPI could not discover the empty header region after 20 seconds; see recorder/s03-startup-tree.json")

    # Positive click: GDK receives the real button event and the recorder captures
    # the entire compositor output, not only the app webview.
    point, target_seq, window_rect = target_point(header, header_rect, pyatspi, artifact_dir, case_id, "Empty header area")
    inject_input(case["session"], "click", x=point["x"], y=point["y"], button=3)
    click_seq = append_event(artifact_dir, case_id, "s03-secondary-click", {
        "target": "empty-header",
        "button": 3,
        "inputBackend": "XTest" if case["session"] == "x11" else os.environ.get("S03_WAYLAND_INPUT_BACKEND", ""),
        "pointerDesktop": point,
        "targetBoundsDesktop": header_rect,
        "coordinateTargetSeq": target_seq,
    })
    emit_capture_point(artifact_dir, case_id, "restored-popup", point, "empty-header")
    menu = wait_until(lambda: find_menu(desktop, pyatspi, fallback=False), MENU_TIMEOUT_SECONDS)
    visible_def = case_assertion(case, "S1-16")
    anchor_def = case_assertion(case, "O-21")
    restored_def = case_assertion(case, "RESTORED-MODEL")

    if menu is None:
        reason = "No native popup was discoverable through AT-SPI; the compositor recording remains for manual review."
        tree_ref = f"native-tree/{case_id}-restored-popup-{click_seq}.json"
        write_json(artifact_dir / tree_ref, {
            "caseId": case_id,
            "checkpoint": "restored-popup",
            "nativeMenuDiscovered": False,
            "headerBoundsDesktop": header_rect,
            "windowBoundsDesktop": window_rect,
            "visibleMenuCandidates": visible_menu_candidates(desktop, pyatspi),
        })
        refs = artifact_evidence(artifact_dir, case_id, "restored-popup", click_seq, visible_def["evidence"], [tree_ref])
        results[visible_def["id"]] = result_record(visible_def, "UNVERIFIED", reason, refs)
        results[anchor_def["id"]] = result_record(anchor_def, "UNVERIFIED", reason, refs)
        results[restored_def["id"]] = result_record(restored_def, "UNVERIFIED", reason, refs)
    else:
        popup, popup_bounds, named = menu
        tree_ref, geometry_ref = native_tree_and_geometry(artifact_dir, case_id, "restored-popup", click_seq, popup, popup_bounds, named, pyatspi, point, header_rect, window_rect)
        visible_refs = artifact_evidence(artifact_dir, case_id, "restored-popup", click_seq, visible_def["evidence"], [tree_ref])
        results[visible_def["id"]] = result_record(visible_def, "PASS", "A visible non-kit Mutter window menu is present in the native accessibility tree.", visible_refs)
        inside = point_in_rect(point, popup_bounds)
        results[anchor_def["id"]] = result_record(anchor_def, "PASS" if inside else "FAIL",
            f"Pointer {point} is {'inside' if inside else 'outside'} native popup bounds {popup_bounds}; CSS/GDK scale is 1:1.",
            artifact_evidence(artifact_dir, case_id, "restored-popup", click_seq, anchor_def["evidence"], [geometry_ref]))
        restored_labels = WINDOW_MENU_ITEMS | {"Maximize"}
        missing = sorted(restored_labels - set(named))
        restored_refs = artifact_evidence(artifact_dir, case_id, "restored-popup", click_seq, restored_def["evidence"], [tree_ref])
        results[restored_def["id"]] = result_record(restored_def, "PASS" if not missing else "FAIL",
            "All expected restored-window menu items are accessible." if not missing else f"Missing native menu labels: {missing}", restored_refs)

    try:
        inject_input(case["session"], "key", key="Escape")
    except Exception as error:
        raise ProbeUnavailable(f"could not dismiss the compositor menu: {type(error).__name__}") from error
    menu_dismissed = wait_until(lambda: find_menu(desktop, pyatspi, fallback=False) is None, NEGATIVE_OBSERVATION_SECONDS)
    if not menu_dismissed:
        reason = "Escape did not dismiss the compositor menu; later input targets cannot be observed reliably."
        for suffix in ("CONTROL-NEGATIVE", "TAB-NEGATIVE", "MAXIMIZED-RESTORE"):
            definition = case_assertion(case, suffix)
            results[definition["id"]] = result_record(definition, "UNVERIFIED", reason, [
                f"native-tree/{case_id}-restored-popup-{click_seq}.json",
                f"events.jsonl#seq={click_seq}",
                os.environ.get("S03_CAPTURE_VIDEO_REF", "video/desktop.mp4"),
            ])
        return [results.get(assertion["id"], result_record(assertion, "UNVERIFIED", reason, [])) for assertion in case["assertions"]]

    # Negative control and tab probes are real secondary-clicks. The native
    # handler's registered blocker rectangles must let both events propagate.
    for label, suffix in (("Minimize window", "CONTROL-NEGATIVE"), ("Overview tab", "TAB-NEGATIVE")):
        point, target_seq, target_rect, target_node, window_rect = click_accessible(
            desktop, pyatspi, case, artifact_dir, case["session"], label, 3
        )
        checkpoint = "control-negative" if suffix.startswith("CONTROL") else "tab-negative"
        seq = append_event(artifact_dir, case_id, "s03-secondary-click", {
            "target": "control" if suffix.startswith("CONTROL") else "tab",
            "targetName": label,
            "button": 3,
            "pointerDesktop": point,
            "targetBoundsDesktop": target_rect,
        })
        emit_capture_point(artifact_dir, case_id, checkpoint, point, label)
        popup_after = wait_until(lambda: find_menu(desktop, pyatspi, fallback=False), NEGATIVE_OBSERVATION_SECONDS)
        definition = case_assertion(case, suffix)
        local_path = f"native-tree/{case_id}-{checkpoint}-{seq}.json"
        write_json(artifact_dir / local_path, {
            "caseId": case_id,
            "checkpoint": checkpoint,
            "clickedTarget": accessible_snapshot(target_node, pyatspi),
            "visibleMenuCandidates": visible_menu_candidates(desktop, pyatspi),
            "observationSeconds": NEGATIVE_OBSERVATION_SECONDS,
        })
        refs = artifact_evidence(artifact_dir, case_id, checkpoint, seq, definition["evidence"], [local_path])
        if popup_after:
            results[definition["id"]] = result_record(definition, "FAIL", f"A compositor window menu opened after secondary-click on {label}.", refs)
            inject_input(case["session"], "key", key="Escape")
            menu_dismissed = wait_until(lambda: find_menu(desktop, pyatspi, fallback=False) is None, NEGATIVE_OBSERVATION_SECONDS)
            if not menu_dismissed:
                reason = "Escape did not dismiss the menu opened by the negative control; later checks were skipped."
                for later_label, later_suffix in (("Overview tab", "TAB-NEGATIVE"), ("Maximize for menu state check", "MAXIMIZED-RESTORE")):
                    later = case_assertion(case, later_suffix)
                    results[later["id"]] = result_record(later, "UNVERIFIED", reason, [local_path, f"events.jsonl#seq={seq}"])
                return [results.get(assertion["id"], result_record(assertion, "UNVERIFIED", reason, [])) for assertion in case["assertions"]]
        elif results.get(visible_def["id"], {}).get("verdict") == "PASS":
            results[definition["id"]] = result_record(definition, "PASS", f"No compositor window menu appeared after secondary-click on {label}.", refs)
        else:
            results[definition["id"]] = result_record(definition, "UNVERIFIED", "The native-menu accessibility observer was not qualified by a visible positive popup.", refs)

    # Maximize via a real primary-click, then inspect a second native popup.
    maximize_point, maximize_seq, maximize_rect, maximize_node, _maximize_window_rect = click_accessible(
        desktop, pyatspi, case, artifact_dir, case["session"], "Maximize for menu state check", 1
    )
    maximize_ready = wait_until(lambda: has_named_node(desktop, "Test window maximized", "status"), 3.0)
    append_event(artifact_dir, case_id, "s03-maximize-test-window", {
        "pointerDesktop": maximize_point,
        "targetBoundsDesktop": maximize_rect,
        "operationConfirmed": bool(maximize_ready),
    })
    maximize_def = case_assertion(case, "MAXIMIZED-RESTORE")
    if not maximize_ready:
        results[maximize_def["id"]] = result_record(maximize_def, "UNVERIFIED", "The app did not confirm the maximize request through its accessible status.", [
            f"events.jsonl#seq={maximize_seq}",
            safe_artifact_ref(os.environ.get("S03_CAPTURE_VIDEO_REF", "video/desktop.mp4")) or "video/desktop.mp4",
        ])
        reason = "The maximize request was not confirmed; menu-state check skipped."
        return [results.get(assertion["id"], result_record(assertion, "UNVERIFIED", reason, [])) for assertion in case["assertions"]]
    time.sleep(0.25)
    point, target_seq, window_rect = target_point(header, header_rect, pyatspi, artifact_dir, case_id, "Empty header area")
    inject_input(case["session"], "click", x=point["x"], y=point["y"], button=3)
    max_seq = append_event(artifact_dir, case_id, "s03-secondary-click", {
        "target": "empty-header-maximized",
        "button": 3,
        "pointerDesktop": point,
    })
    emit_capture_point(artifact_dir, case_id, "maximized-popup", point, "empty-header-maximized")
    maximized_menu = wait_until(lambda: find_menu(desktop, pyatspi, fallback=False), MENU_TIMEOUT_SECONDS)
    if maximized_menu is None:
        results[maximize_def["id"]] = result_record(maximize_def, "UNVERIFIED", "No native popup was discoverable after maximizing; the compositor recording remains for manual review.",
            artifact_evidence(artifact_dir, case_id, "maximized-popup", max_seq, maximize_def["evidence"], []))
    else:
        popup, popup_bounds, named = maximized_menu
        tree_ref, geometry_ref = native_tree_and_geometry(artifact_dir, case_id, "maximized-popup", max_seq, popup, popup_bounds, named, pyatspi, point, header_rect, window_rect)
        restore_ok = "Restore" in named and "Maximize" not in named
        results[maximize_def["id"]] = result_record(maximize_def, "PASS" if restore_ok else "FAIL",
            "Restore is present and Maximize is absent." if restore_ok else f"Maximized menu labels do not show Restore-only state: {sorted(named)}",
            artifact_evidence(artifact_dir, case_id, "maximized-popup", max_seq, maximize_def["evidence"], [tree_ref, geometry_ref]))
    try:
        inject_input(case["session"], "key", key="Escape")
    except Exception:
        pass

    # Keep assertion order identical to the case declaration.
    return [results.get(assertion["id"], result_record(assertion, "UNVERIFIED", "The probe did not produce this assertion.", [])) for assertion in case["assertions"]]


def run_fallback_case(case: dict, artifact_dir: Path, pyatspi, desktop) -> list[dict]:
    case_id = case["id"]
    _mode_point, _, _, _, _ = click_accessible(desktop, pyatspi, case, artifact_dir, case["session"], "Select kit fallback mode", 1)
    if not wait_until(lambda: has_named_node(desktop, "Kit fallback mode selected", "status"), 3.0):
        write_json(artifact_dir / "recorder/s03-fallback-status-tree.json", accessible_snapshot(desktop, pyatspi))
        emit_capture_point(artifact_dir, case_id, "fallback-status-missing", _mode_point, "Select kit fallback mode")
        raise ProbeUnavailable("the app did not confirm kit fallback mode through its accessible status")
    # WebKit exposes ARIA regions as AT-SPI landmarks on some releases.
    # Qualify by the exact accessible name and measured bounds, after startup.
    found = wait_until(lambda: (lambda pair: pair if pair[0] is not None else None)(
        find_named(desktop, pyatspi, "Empty header area")), 20.0)
    header, header_rect = found or (None, None)
    if header is None or header_rect is None:
        write_json(artifact_dir / "recorder/s03-startup-tree.json", accessible_snapshot(desktop, pyatspi))
        raise ProbeUnavailable("AT-SPI could not discover the empty header region after 20 seconds; see recorder/s03-startup-tree.json")
    point, target_seq, window_rect = target_point(header, header_rect, pyatspi, artifact_dir, case_id, "Empty header area")
    inject_input(case["session"], "click", x=point["x"], y=point["y"], button=3)
    seq = append_event(artifact_dir, case_id, "s03-secondary-click", {
        "target": "empty-header-kit-fallback",
        "button": 3,
        "pointerDesktop": point,
        "coordinateTargetSeq": target_seq,
    })
    emit_capture_point(artifact_dir, case_id, "kit-fallback-popup", point, "empty-header-kit-fallback")
    menu = wait_until(lambda: find_menu(desktop, pyatspi, fallback=True), MENU_TIMEOUT_SECONDS)
    visible_def = case_assertion(case, "FALLBACK-VISIBLE")
    items_def = case_assertion(case, "FALLBACK-SAME-ITEMS")
    resize_def = case_assertion(case, "FALLBACK-UNSUPPORTED-RESIZE")
    if menu is None:
        reason = "The app's accessible kit fallback menu did not appear."
        refs = artifact_evidence(artifact_dir, case_id, "kit-fallback-popup", seq, visible_def["evidence"], [])
        return [result_record(definition, "FAIL", reason, refs) for definition in case["assertions"]]

    popup, bounds, named = menu
    tree_ref, geometry_ref = native_tree_and_geometry(artifact_dir, case_id, "kit-fallback-popup", seq, popup, bounds, named, pyatspi, point, header_rect, window_rect)
    refs = artifact_evidence(artifact_dir, case_id, "kit-fallback-popup", seq, visible_def["evidence"], [tree_ref, geometry_ref])
    inside = point_in_rect(point, bounds)
    results = {
        visible_def["id"]: result_record(visible_def, "PASS" if inside else "FAIL",
            f"Kit menu bounds {bounds} {'contain' if inside else 'do not contain'} pointer {point}.", refs),
    }
    expected_items = WINDOW_MENU_ITEMS | {"Maximize"}
    missing = sorted(expected_items - set(named))
    results[items_def["id"]] = result_record(items_def, "PASS" if not missing else "FAIL",
        "The seven GNOME menu actions are present." if not missing else f"Missing fallback items: {missing}", refs)
    resize_nodes = named.get("Resize", [])
    resize_disabled = bool(resize_nodes) and all(
        not node.getState().contains(pyatspi.STATE_ENABLED) for node in resize_nodes
    )
    resize_text = any("Resize is unavailable" in name for name in named)
    results[resize_def["id"]] = result_record(resize_def, "PASS" if resize_disabled and resize_text else "FAIL",
        "Resize is disabled and its limitation is accessible." if resize_disabled and resize_text else "Resize was not both disabled and explained.", refs)
    try:
        inject_input(case["session"], "key", key="Escape")
    except Exception:
        pass
    return [results[assertion["id"]] for assertion in case["assertions"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args()
    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cases_doc = json.loads(args.cases.read_text(encoding="utf-8"))
    case = next((item for item in cases_doc["cases"] if item["id"] == args.case_id), None)
    if case is None:
        raise SystemExit(f"Unknown S03 case id: {args.case_id}")

    environment, errors, atspi = check_session(case, artifact_dir)
    pyatspi, desktop = atspi
    if errors:
        results = make_unverified(case, "; ".join(errors))
    else:
        try:
            if case["id"].endswith("KIT-FALLBACK"):
                results = run_fallback_case(case, artifact_dir, pyatspi, desktop)
            else:
                results = run_required_cell(case, artifact_dir, pyatspi, desktop)
        except ProbeUnavailable as error:
            results = make_unverified(case, str(error))
        except (OSError, subprocess.SubprocessError) as error:
            results = make_unverified(case, f"Runner input/capture command failed: {type(error).__name__}")
        except Exception as error:
            results = make_unverified(case, f"AT-SPI/probe failure: {type(error).__name__}")

    result_doc = {"caseId": case["id"], "assertions": results}
    write_json(artifact_dir / "s03-assertions.json", result_doc)
    print(json.dumps({"caseId": case["id"], "verdicts": {item["id"]: item["verdict"] for item in results}}, sort_keys=True))
    return 0 if all(item["verdict"] == "PASS" for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
