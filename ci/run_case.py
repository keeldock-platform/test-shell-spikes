#!/usr/bin/env python3
"""Run one lane adapter and preserve UNVERIFIED evidence on missing capability."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

from case_catalog import assertion_specs_for
from native_preflight import collect as collect_native_preflight

ROOT = Path(__file__).resolve().parents[1]
SPIKES = {"s01", "s02", "s03", "s08", "s10", "s11"}


def run(command: list[str], *, timeout: int = 12) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    return (completed.stdout + completed.stderr).strip()[:1000]


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def record_capture_clock_sample(path: Path, phase: str) -> None:
    """Bracket recorder execution with host realtime/monotonic clock pairs."""
    mono_before = time.monotonic_ns()
    wall = time.time_ns()
    mono_after = time.monotonic_ns()
    mono = (mono_before + mono_after) // 2
    uncertainty = (mono_after - mono_before + 1) // 2
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    samples = current.get("samples", []) if isinstance(current, dict) else []
    samples = [item for item in samples if isinstance(item, dict) and item.get("phase") != phase]
    samples.append({
        "phase": phase,
        "wallClockNanoseconds": wall,
        "monotonicNanoseconds": mono,
        "monotonicReadUncertaintyNanoseconds": uncertainty,
    })
    offsets = [int(item["monotonicNanoseconds"]) - int(item["wallClockNanoseconds"])
               for item in samples if isinstance(item.get("wallClockNanoseconds"), int)
               and isinstance(item.get("monotonicNanoseconds"), int)]
    complete = {item.get("phase") for item in samples} >= {"start", "stop"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": "measured" if complete else "sampling",
        "samples": samples,
        "wallToMonotonicOffsetNanoseconds": int(statistics.median(offsets)) if offsets else None,
        "calibrationUncertaintyNanoseconds": max(
            [max(offsets) - min(offsets) if len(offsets) > 1 else 0,
             *(int(item.get("monotonicReadUncertaintyNanoseconds", 0)) for item in samples)]
        ),
        "source": "paired host realtime and monotonic samples bracketing recorder lifetime",
    }, indent=2) + "\n", encoding="utf-8")


def environment_lock() -> dict:
    return json.loads((ROOT / "ci/environment-lock.json").read_text(encoding="utf-8"))


def runtime_matches_pin(cell: str, environment: dict) -> bool:
    policy = environment_lock().get("runtimePolicy", {})
    expected = policy.get("exactRuntimeVersionsByCell", {}).get(cell)
    if not isinstance(expected, dict) or not expected or policy.get("passRequiresExactRuntimeMatch") is not True:
        return False
    for dotted_key, expected_value in expected.items():
        observed: object = environment
        for part in str(dotted_key).split("."):
            observed = observed.get(part) if isinstance(observed, dict) else None
        if str(observed) != str(expected_value):
            return False
    return True


def linux_release() -> dict[str, str]:
    values: dict[str, str] = {}
    release_file = Path("/etc/os-release")
    if not release_file.is_file():
        return values
    for line in release_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ID", "NAME", "VERSION_ID", "PRETTY_NAME"}:
            values[key] = value.strip().strip('"')
    return values


def assertion_ids(case_file: Path, case_id: str) -> list[str]:
    return [str(item["id"]) for item in assertion_specs_for(case_file.stem, case_id) if item.get("id")]


def spike_label(spike: str) -> str:
    return f"S{spike[1:].upper()}" if spike.startswith("s") else spike.upper()


def recorder_commands(platform_name: str, action: str, output: Path) -> tuple[list[str], Path]:
    scripts = {
        "macos": ROOT / "ci/recorders/macos.sh",
        "linux": ROOT / "ci/recorders/linux.sh",
        "ios": ROOT / "ci/recorders/ios.sh",
        "android": ROOT / "ci/recorders/android.sh",
    }
    if platform_name == "windows":
        if action == "start":
            return ([sys.executable, str(ROOT / "ci/recorders/windows-start.py"), str(output)], output.with_suffix(".pid"))
        return (["pwsh", "-NoProfile", "-File", str(ROOT / "ci/recorders/windows.ps1"), action, str(output)], output.with_suffix(".pid"))
    return (["bash", str(scripts[platform_name]), action, str(output)], output.with_suffix(".pid"))


def verify_recorder_version(platform_name: str) -> tuple[bool, str]:
    if platform_name in {"macos", "windows"} or (platform_name == "linux" and os.environ.get("XDG_SESSION_TYPE") != "wayland"):
        actual = run(["ffmpeg", "-version"])
        if not actual or not actual.startswith("ffmpeg version "):
            return False, "ffmpeg version could not be measured or the recorder is unavailable"
        return True, actual.splitlines()[0]
    if platform_name == "android":
        actual = run(["adb", "--version"])
        if not actual:
            return False, "Android platform-tools version could not be measured"
        return True, actual.splitlines()[0]
    if platform_name == "linux":
        actual = os.environ.get("SHELL_GNOME_VERSION")
        return bool(actual), actual or "Mutter/GNOME version is unavailable in this session"
    if platform_name == "ios":
        actual = run(["xcodebuild", "-version"])
        return bool(actual), "simctl recorder through " + (actual.replace("\n", "; ") if actual else "Xcode version could not be measured")
    return False, "recorder runtime could not be identified"


def find_adapter(platform_name: str, spike: str, case_id: str) -> list[str] | None:
    candidates = [
        ROOT / "automation" / platform_name / spike / "run.sh",
        ROOT / "automation" / platform_name / spike / "run.ps1",
        ROOT / "automation" / "colour" / f"run-{platform_name}.sh" if spike == "s10" else ROOT / "__none__",
        ROOT / "automation" / "accent" / f"run-{platform_name}.sh" if spike == "s11" else ROOT / "__none__",
    ]
    for candidate in candidates:
        if candidate.is_file():
            if candidate.suffix == ".ps1":
                return ["pwsh", "-NoProfile", "-File", str(candidate), "-CaseId", case_id]
            return ["bash", str(candidate)]
    return None


def write_hashes(evidence: Path) -> None:
    lines = []
    for path in sorted(item for item in evidence.rglob("*") if item.is_file() and item.name != "hashes.sha256"):
        lines.append(f"{sha256(path)}  {path.relative_to(evidence).as_posix()}")
    (evidence / "hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_lane_results(lane_file: Path) -> list[dict]:
    if not lane_file.exists():
        return []
    try:
        value = json.loads(lane_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        results = value.get("results", value.get("assertions"))
        return results if isinstance(results, list) else []
    return value if isinstance(value, list) else []


def root_relative_results(results: list[dict], scenario: Path, evidence: Path) -> list[dict]:
    """Lift lane-local evidence references to paths rooted at the uploaded artifact."""
    prefix = scenario.relative_to(evidence).as_posix()
    lifted: list[dict] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = dict(result)
        references = item.get("evidence", [])
        if isinstance(references, list):
            normalized = []
            for reference in references:
                value = str(reference)
                path, marker, suffix = value.partition("#")
                path = path.replace("\\", "/")
                if path and not path.startswith(prefix + "/"):
                    path = posixpath.normpath(posixpath.join(prefix, path))
                normalized.append(path + (marker + suffix if marker else ""))
            item["evidence"] = normalized
        lifted.append(item)
    return lifted


def materialize_case_evidence_aliases(spike: str, scenario: Path) -> None:
    """Expose native captures under the case contract's stable evidence folders."""
    if spike not in {"s10", "s11"}:
        return
    aliases: list[dict[str, str]] = []
    screens = scenario / "screens"
    recorder = scenario / "recorder"
    screens.mkdir(parents=True, exist_ok=True)
    for source in sorted(recorder.rglob("*.png")):
        target = screens / f"native-{source.name}"
        if source.is_file() and not target.exists():
            try:
                shutil.copyfile(source, target)
                aliases.append({"source": source.relative_to(scenario).as_posix(), "alias": target.relative_to(scenario).as_posix()})
            except OSError:
                pass
    tree_candidates = [path for path in sorted(recorder.rglob("*")) if path.is_file()
                       and ("native-tree" in path.name.lower() or "accessibility" in path.name.lower())]
    if tree_candidates and not any("native-tree" in path.name.lower() or "accessibility-tree" in path.name.lower()
                                   for path in recorder.rglob("*")):
        source = tree_candidates[0]
        target = recorder / f"native-tree-accessibility{source.suffix or '.txt'}"
        if not target.exists():
            try:
                shutil.copyfile(source, target)
                aliases.append({"source": source.relative_to(scenario).as_posix(), "alias": target.relative_to(scenario).as_posix()})
            except OSError:
                pass
    if aliases:
        (recorder / "case-evidence-aliases.json").write_text(json.dumps(aliases, indent=2) + "\n", encoding="utf-8")


def materialize_s02_geometry(scenario: Path) -> None:
    """Expose measured UIA rectangles already retained in native S02 events."""
    import math
    observations = []
    events = scenario / "events.jsonl"
    if not events.is_file():
        return
    for number, line in enumerate(events.read_text(encoding="utf-8-sig").splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            continue
        for key in ("bounds", "targetBounds", "buttonBounds", "windowBounds", "menuBounds", "before", "after"):
            bounds = event["data"].get(key)
            if not isinstance(bounds, dict) or any(
                type(bounds.get(axis)) not in (int, float) or not math.isfinite(bounds[axis])
                for axis in ("x", "y", "width", "height")
            ):
                continue
            observations.append({"source": "events.jsonl", "sourceLine": number,
                                 "event": event.get("name"), "field": key, "bounds": bounds})
    if observations:
        (scenario / "recorder/geometry.json").write_text(json.dumps({"observations": observations}, indent=2) + "\n")


def attach_case_evidence(results: list[dict], specs: list[dict], scenario: Path, evidence: Path) -> list[dict]:
    """Attach only existing case-local files required by each assertion."""
    specs_by_id = {str(spec.get("id")): spec for spec in specs if spec.get("id")}
    prefix = scenario.relative_to(evidence).as_posix()
    enriched: list[dict] = []
    for source_row in results:
        row = dict(source_row)
        references = row.get("evidence", [])
        references = list(references) if isinstance(references, list) else []
        spec = specs_by_id.get(str(row.get("id")), {})
        for required in spec.get("evidence", []) if isinstance(spec.get("evidence"), list) else []:
            source, marker, selector = str(required).partition("#")
            candidates: list[Path] = []
            if source == "events.jsonl" or source == "os-event":
                candidates = [scenario / "events.jsonl"] if marker else [scenario / "events.jsonl", *sorted((scenario / "recorder").glob("*events.jsonl"))]
            elif source == "frame-marker":
                candidates = [scenario / "events.jsonl", *sorted((scenario / "video").glob("*")), scenario / "recorder" / "presentation-links.jsonl"]
            elif source == "video":
                candidates = sorted((scenario / "video").glob("*"))
            elif source == "screen":
                candidates = [*sorted((scenario / "screens").glob("*")), *sorted((scenario / "recorder").glob("*.png"))]
            elif source == "native-tree":
                candidates = sorted((scenario / "native-tree").glob("*.json"))
                candidates += [path for path in sorted((scenario / "recorder").glob("*"))
                               if "native-tree" in path.name.lower() or "accessibility-tree" in path.name.lower()]
            elif source == "geometry-json":
                candidates = [scenario / "recorder/geometry.json"]
            elif source == "native-readback":
                candidates = [path for path in sorted((scenario / "recorder").glob("*"))
                              if "readback" in path.name.lower() or "native-readback" in path.name.lower() or "portal-probe" in path.name.lower()]
            elif source == "environment.json":
                candidates = [scenario / "environment.json"]
            elif source.startswith(("screens/", "video/", "recorder/")):
                candidates = [scenario / source]
            else:
                candidates = [scenario / source]
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                reference = f"{prefix}/{candidate.relative_to(scenario).as_posix()}"
                if marker:
                    reference += f"#{selector}"
                if reference not in references:
                    references.append(reference)
            if marker and not any(reference.startswith(f"{prefix}/{source}#") for reference in references):
                exact = scenario / source
                if exact.is_file():
                    references.append(f"{prefix}/{source}#{selector}")
        row["evidence"] = references
        enriched.append(row)
    return enriched


def normalize_results(
    spike: str,
    case_id: str,
    specs: list[dict],
    lane_results: list[dict],
    *,
    recorder_ok: bool,
    webview_ok: bool,
    display_ok: bool,
    android_capture_has_gaps: bool,
    runtime_pinned: bool,
    capture_index_ok: bool,
) -> tuple[list[dict], list[dict]]:
    """Reject duplicate, missing, unexpected, or capture-incomplete rows."""
    by_id: dict[str, list[dict]] = {}
    expected_ids = {str(spec.get("id")) for spec in specs if spec.get("id")}
    malformed = [item for item in lane_results if not isinstance(item, dict)]
    for item in lane_results:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id", ""))
        by_id.setdefault(identifier, []).append(item)
    unexpected = [item for identifier, rows in by_id.items() if identifier not in expected_ids for item in rows]
    unexpected.extend({"id": "<malformed-result>", "actual": "A lane result was not an object."} for _ in malformed)
    output: list[dict] = []
    for spec in specs:
        identifier = str(spec.get("id", ""))
        rows = by_id.get(identifier, [])
        if len(rows) != 1:
            reason = "No unique lane result was supplied for this declared assertion."
            if len(rows) > 1:
                reason = "Duplicate lane results were supplied for this assertion."
            output.append({
                "id": identifier,
                "expected": spec.get("expected", "Declared case assertion"),
                "actual": f"UNVERIFIED: {reason}",
                "verdict": "UNVERIFIED",
                "evidence": [],
                "requiredEvidence": spec.get("evidence", []),
            })
            continue
        item = dict(rows[0])
        item["laneVerdict"] = item.get("verdict")
        item["laneActual"] = item.get("actual")
        item["expected"] = spec.get("expected", item.get("expected", "Declared case assertion"))
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(reference, str) for reference in evidence):
            evidence = []
            item["evidence"] = evidence
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: lane evidence references were malformed."
        verdict = item.get("verdict")
        if verdict not in {"PASS", "FAIL", "UNVERIFIED"}:
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: lane result used an unsupported verdict."
        requirements = [str(value).lower() for value in spec.get("evidence", []) if isinstance(value, str)]
        if item.get("verdict") in {"PASS", "FAIL"} and not recorder_ok and any("video" in value or "frame-marker" in value for value in requirements):
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: whole-session recording did not complete cleanly."
        if item.get("verdict") in {"PASS", "FAIL"} and not display_ok and any("video" in value or "frame-marker" in value or "geometry" in value for value in requirements):
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: native display resolution, scale, or refresh could not be measured."
        if item.get("verdict") in {"PASS", "FAIL"} and spike in {"s10", "s11"} and not webview_ok:
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: installed webview version could not be measured."
        if item.get("verdict") in {"PASS", "FAIL"} and android_capture_has_gaps and "video" in requirements and "frame-marker" in requirements:
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: Android segment gaps cannot establish a one-frame assertion."
        if item.get("verdict") == "PASS" and "frame-marker" in requirements and not capture_index_ok:
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: timestamped capture frames could not be joined to renderer presentation markers."
        if item.get("verdict") == "PASS" and not runtime_pinned:
            item["verdict"] = "UNVERIFIED"
            item["actual"] = "UNVERIFIED: no reviewed exact runtime pin matches this hosted cell."
        item["requiredEvidence"] = spec.get("evidence", [])
        output.append(item)
    for item in unexpected:
        output.append({
            **item,
            "verdict": "UNVERIFIED",
            "actual": "UNVERIFIED: unexpected assertion ID was rejected by the case contract.",
        })
    return output, unexpected


def append_renderer_events(scenario: Path) -> None:
    """Copy native-received renderer records into the case event stream."""
    source = scenario / "recorder" / "renderer-events.jsonl"
    if not source.is_file():
        return
    destination = scenario / "events.jsonl"
    normalized_s01: list[str] = []
    try:
        records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        (scenario / "recorder" / "renderer-event-transport.json").write_text(
            json.dumps({"status": "UNVERIFIED", "reason": "renderer event stream was not valid JSONL"}, indent=2) + "\n",
            encoding="utf-8",
        )
        return
    try:
        existing_rows = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        existing_rows = []
    existing_renderer = {
        json.dumps(row, separators=(",", ":"), sort_keys=True)
        for row in existing_rows if isinstance(row, dict)
    }
    existing_s01 = {
        (row.get("sequenceId"), row.get("kind"), row.get("monotonicNanoseconds"))
        for row in existing_rows if isinstance(row, dict) and row.get("kind")
    }
    with destination.open("a", encoding="utf-8") as stream:
        for record in records:
            if not isinstance(record, dict):
                continue
            renderer_key = json.dumps(record, separators=(",", ":"), sort_keys=True)
            if renderer_key not in existing_renderer:
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
                existing_renderer.add(renderer_key)
            detail = record.get("detail") if isinstance(record.get("detail"), dict) else record
            fields = detail.get("fields", {}) if isinstance(detail.get("fields"), dict) else {}
            if record.get("type") != "shell-spike:event" and detail.get("type") != "shell-spike:event":
                continue
            normalized = {
                **fields,
                "sequenceId": fields.get("sequenceId", fields.get("sequence")),
                "kind": detail.get("name", fields.get("name", "renderer-event")),
                "name": detail.get("name", fields.get("name", "renderer-event")),
                "hostPid": record.get("hostPid"),
                "utc": record.get("utc", ""),
                "rendererMonotonicTime": detail.get("monotonicTime"),
                "monotonicNanoseconds": record.get("hostMonotonicNanoseconds"),
                "fields": fields,
            }
            event_key = (normalized.get("sequenceId"), normalized.get("kind"), normalized.get("monotonicNanoseconds"))
            if event_key not in existing_s01:
                normalized_s01.append(json.dumps(normalized, separators=(",", ":")))
                stream.write(json.dumps(normalized, separators=(",", ":")) + "\n")
                existing_s01.add(event_key)
    if normalized_s01:
        s01_path = scenario / "recorder" / "s01-events.jsonl"
        prior = s01_path.read_text(encoding="utf-8").rstrip() + "\n" if s01_path.is_file() else ""
        s01_path.write_text(prior + "\n".join(normalized_s01) + "\n", encoding="utf-8")


def collect_mobile_renderer_events(platform_name: str, scenario: Path, case_id: str) -> None:
    """Pull app-sandbox telemetry from the active simulator/emulator."""
    bundle_id = os.environ.get("SHELL_MOBILE_BUNDLE_ID", "org.example.shellspikes.mobile")
    destination = scenario / "recorder" / "renderer-events.jsonl"
    event_name = f"renderer-events-{case_id}.jsonl"
    s01_name = f"s01-events-{case_id}.jsonl"
    payload: bytes | None = None
    if platform_name == "ios":
        udid = os.environ.get("SHELL_IOS_SIMULATOR_UDID")
        container = run(["xcrun", "simctl", "get_app_container", udid, bundle_id, "data"]) if udid else None
        if container:
            candidates = sorted(Path(container).rglob(event_name))
            if candidates:
                try:
                    payload = candidates[0].read_bytes()
                except OSError:
                    payload = None
    elif platform_name == "android":
        remote = run(["adb", "shell", "run-as", bundle_id, "sh", "-c", f"find files -type f -name '{event_name}' -print -quit"])
        if remote:
            try:
                copied = subprocess.run(
                    ["adb", "exec-out", "run-as", bundle_id, "cat", remote.splitlines()[0]],
                    capture_output=True, timeout=15, check=False,
                )
                if copied.returncode == 0:
                    payload = copied.stdout
            except (OSError, subprocess.TimeoutExpired):
                payload = None
    if payload:
        destination.write_bytes(payload)
        append_renderer_events(scenario)
    else:
        (scenario / "recorder" / "renderer-event-transport.json").write_text(
            json.dumps({"status": "UNVERIFIED", "reason": "the mobile app sandbox contained no renderer event stream"}, indent=2) + "\n",
            encoding="utf-8",
        )
    if platform_name == "ios":
        udid = os.environ.get("SHELL_IOS_SIMULATOR_UDID")
        container = run(["xcrun", "simctl", "get_app_container", udid, bundle_id, "data"]) if udid else None
        candidates = sorted(Path(container).rglob(s01_name)) if container else []
        if candidates:
            try:
                shutil.copyfile(candidates[0], scenario / "recorder" / "s01-events.jsonl")
            except OSError:
                pass
    elif platform_name == "android":
        remote_s01 = run(["adb", "shell", "run-as", bundle_id, "sh", "-c", f"find files -type f -name '{s01_name}' -print -quit"])
        if remote_s01:
            try:
                copied_s01 = subprocess.run(
                    ["adb", "exec-out", "run-as", bundle_id, "cat", remote_s01.splitlines()[0]],
                    capture_output=True, timeout=15, check=False,
                )
                if copied_s01.returncode == 0:
                    (scenario / "recorder" / "s01-events.jsonl").write_bytes(copied_s01.stdout)
            except (OSError, subprocess.TimeoutExpired):
                pass


def ios_attachment_relative_name(suggested: str) -> Path | None:
    # xcresulttool removes slashes/extensions and appends repetition + UUID.
    # Map only the explicitly named test attachments back to canonical paths.
    known = ["recorder/observations.json", "recorder/native-tree.txt", "recorder/ios-display.json",
             "recorder/native-tree-picker.txt", "recorder/page-accessibility.txt",
             "recorder/manual-input-failure.txt", "events.jsonl",
             "screens/ios-policy.png", "screens/ios-initial.png",
             "screens/ios-picker-1.png", "screens/ios-picker-2.png",
             "screens/ios-picker-dismiss.png"]
    uuid = r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}"
    for reference in known:
        path = Path(reference)
        stem = path.with_suffix("").as_posix().replace("/", "")
        extension = r"(?:txt|jsonl)" if path.suffix == ".jsonl" else re.escape(path.suffix[1:])
        if re.fullmatch(re.escape(stem) + r"_[0-9]+_" + uuid + r"\." + extension, suggested):
            return path
    path = Path(suggested)
    if not path.is_absolute() and ".." not in path.parts and (
        path.parts[:1] in (("screens",), ("recorder",)) or path.as_posix() == "events.jsonl"
    ):
        return path
    return None


def collect_ios_xctest_evidence(spike: str, scenario: Path) -> None:
    """Export named XCTest attachments from the case's retained result bundle."""
    if spike not in {"s10", "s11"}:
        return
    destination = scenario / "recorder"
    result_bundle_value = os.environ.get("SHELL_IOS_XCRESULT_PATH", "")
    result_bundle = Path(result_bundle_value) if result_bundle_value else None
    if result_bundle is not None and result_bundle.is_dir():
        export_dir = destination / "ios-xctest-attachments"
        export_dir.mkdir(parents=True, exist_ok=True)
        try:
            exported = subprocess.run(
                ["xcrun", "xcresulttool", "export", "attachments", "--path", str(result_bundle), "--output-path", str(export_dir)],
                cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
            )
            manifest_path = export_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            attachments = [attachment for test in manifest if isinstance(test, dict)
                           for attachment in test.get("attachments", [])] if isinstance(manifest, list) else []
            copied: list[str] = []
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                suggested = attachment.get("suggestedHumanReadableName")
                exported_name = attachment.get("exportedFileName")
                if not isinstance(suggested, str) or not isinstance(exported_name, str):
                    continue
                relative = ios_attachment_relative_name(suggested)
                if relative is None:
                    continue
                if relative.as_posix() in copied:
                    raise ValueError("Duplicate XCTest attachment for " + relative.as_posix())
                source = (export_dir / exported_name).resolve()
                try:
                    source.relative_to(export_dir.resolve())
                except ValueError:
                    continue
                if not source.is_file():
                    continue
                target = (scenario / relative).resolve()
                try:
                    target.relative_to(scenario.resolve())
                except ValueError:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied.append(relative.as_posix())
            status = "captured" if exported.returncode == 0 and copied else "UNVERIFIED"
            (destination / "ios-xctest-evidence-transport.json").write_text(
                json.dumps({
                    "status": status,
                    "source": "case-xcresult-attachment-export",
                    "resultBundle": result_bundle.name,
                    "exportExitCode": exported.returncode,
                    "attachments": sorted(set(copied)),
                    "diagnostic": (exported.stdout + exported.stderr)[-2000:],
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            return
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            pass
    (destination / "ios-xctest-evidence-transport.json").write_text(
        json.dumps({"status": "UNVERIFIED", "reason": "case XCTest result bundle or its attachment manifest was unavailable"}, indent=2) + "\n",
        encoding="utf-8",
    )


def refresh_lane_envelope(spike: str, scenario: Path, case_file: Path) -> None:
    """Recheck lane evidence after the recorder has finalized its media paths."""
    scripts = {
        "s10": ROOT / "automation/colour/result-envelope.py",
        "s11": ROOT / "automation/accent/result-envelope.py",
    }
    script = scripts.get(spike)
    if script is None or not script.is_file():
        return
    result = subprocess.run(
        [
            sys.executable, str(script), "--case-file", str(case_file),
            "--case-id", os.environ.get("SHELL_CASE_ID", scenario.name),
            "--evidence-dir", str(scenario), "--output", str(scenario / "assertions.json"),
        ],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        (scenario / "recorder" / "result-envelope-refresh.json").write_text(
            json.dumps({"status": "UNVERIFIED", "exitCode": result.returncode}, indent=2) + "\n",
            encoding="utf-8",
        )


def finalize_s01_analysis(scenario: Path, case_file: Path) -> None:
    """Run S01 analysis after the recorder has closed and indexed the capture."""
    index = scenario / "video/capture-index.jsonl"
    if not index.is_file() or not (scenario / "ui-events.jsonl").is_file():
        (scenario / "recorder/s01-analysis-status.json").write_text(
            json.dumps({"status": "UNVERIFIED", "reason": "finalized video index or UI event stream is unavailable"}, indent=2) + "\n",
            encoding="utf-8",
        )
        return
    log_path = scenario / "recorder/s01-analysis.log"
    try:
        result = subprocess.run(
            ["swift", str(ROOT / "automation/macos/s01/analyze_capture.swift"), str(scenario), str(case_file)],
            cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log_path.write_text(f"UNVERIFIED: {type(error).__name__}\n", encoding="utf-8")
        result_code = 78
        output = ""
    else:
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        result_code = result.returncode
        output = result.stdout.strip()
    (scenario / "recorder/s01-analysis-status.json").write_text(
        json.dumps({"status": "complete" if result_code == 0 else "UNVERIFIED", "exitCode": result_code, "summary": output}, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_s08_case_evidence(scenario: Path) -> None:
    destination = scenario / "recorder"
    destination.mkdir(parents=True, exist_ok=True)
    shared = Path(os.environ.get("SHELL_S08_EVIDENCE_DIR", ""))
    for filename in ("s08-rust-tests.log", "s08-rust-tests.json", "s08-acl-manifest.json", "s08-compiled-acl.json", "s08-generated-permission-schema.json"):
        source = shared / "recorder" / filename
        target = destination / filename
        if source.is_file():
            shutil.copyfile(source, target)
    acl_inputs = shared / "recorder" / "s08-acl-inputs"
    if acl_inputs.is_dir():
        shutil.copytree(acl_inputs, destination / "s08-acl-inputs", dirs_exist_ok=True)
    if not (destination / "s08-rust-tests.log").is_file():
        (destination / "s08-rust-tests.log").write_text(
            "UNVERIFIED: coordinator Rust authorization tests were not supplied.\n", encoding="utf-8"
        )
    if not (destination / "s08-rust-tests.json").is_file():
        (destination / "s08-rust-tests.json").write_text(
            json.dumps({"status": "UNVERIFIED", "results": []}, indent=2) + "\n", encoding="utf-8"
        )
    if not (destination / "s08-acl-manifest.json").is_file():
        (destination / "s08-acl-manifest.json").write_text(
            json.dumps({"buildStatus": "UNVERIFIED", "windowCapabilities": {}, "capabilities": []}, indent=2) + "\n",
            encoding="utf-8",
        )



def ios_display_measurement(scenario, preflight, case_id, simulator_udid):
    """Qualify UIKit display samples exported by the same simulator case."""
    import math
    import statistics
    try:
        probe = json.loads((scenario / "recorder/ios-display.json").read_text())
        timestamps = probe["displayLinkTimestamps"]
        scale = probe["scale"]
        if (probe.get("caseId") != case_id or not simulator_udid
                or probe.get("simulatorUdid") != simulator_udid
                or not isinstance(probe.get("resolution"), str)
                or not re.fullmatch(r"[1-9]\d*x[1-9]\d*", probe["resolution"])
                or probe.get("resolution") != preflight.get("display", {}).get("resolution")
                or type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0
                or not isinstance(timestamps, list) or len(timestamps) < 6
                or any(type(t) not in (int, float) or not math.isfinite(t) for t in timestamps)):
            return None
        intervals = [b - a for a, b in zip(timestamps, timestamps[1:])]
        if any(interval <= 0 for interval in intervals):
            return None
        return {"resolution": probe["resolution"], "scale": scale,
                "refreshHz": 1 / statistics.median(intervals)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: run_case.py <platform> <spike-id> <case-id>", file=sys.stderr)
        return 2
    platform_name, spike, case_id = sys.argv[1:]
    if spike not in SPIKES:
        print(f"unknown spike id: {spike}", file=sys.stderr)
        return 2

    evidence = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence")).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    for directory in ("screens", "video", "recorder"):
        (evidence / directory).mkdir(parents=True, exist_ok=True)
    scenario = evidence / "spikes" / spike / case_id
    for subdirectory in ("screens", "video", "recorder"):
        (scenario / subdirectory).mkdir(parents=True, exist_ok=True)
    if spike == "s08":
        prepare_s08_case_evidence(scenario)
    os.environ["SHELL_RUN_EVIDENCE_DIR"] = str(evidence)
    os.environ["SHELL_EVIDENCE_DIR"] = str(scenario)
    os.environ["SHELL_SPIKE_ID"] = spike
    os.environ["SHELL_CASE_ID"] = case_id
    os.environ["SHELL_MOBILE_EVIDENCE_SUBPATH"] = f"shell-evidence/{spike}/{case_id}/recorder"
    if platform_name == "macos" and spike == "s01":
        import plistlib
        with (Path(os.environ["SHELL_APP_PATH"]) / "Contents/Info.plist").open("rb") as stream:
            bundle_id = plistlib.load(stream)["CFBundleIdentifier"]
        if os.environ.get("S01_APP_BUNDLE_ID", bundle_id) != bundle_id:
            raise ValueError("S01_APP_BUNDLE_ID disagrees with packaged CFBundleIdentifier")
        os.environ["S01_APP_BUNDLE_ID"] = bundle_id
        os.environ["S01_ARTIFACT_DIR"] = str(scenario)
        os.environ.setdefault("S01_PERMISSION_PROMPT_PREFLIGHT", "unverified")
    if platform_name == "ios":
        os.environ["SHELL_MOBILE_TEST_RUNNER_BUNDLE_ID"] = f"org.example.shellspikes.tests.{spike}"
        os.environ["SHELL_IOS_XCRESULT_PATH"] = str(scenario / "recorder" / f"{spike}-{case_id}.xcresult")
    # Compatibility names used by lane-owned adapters already in the shared tree.
    os.environ["SHELL_SPIKES_ARTIFACT_DIR"] = str(scenario)
    os.environ["S03_CASE_ID"] = case_id
    os.environ["S03_CAPTURE_VIDEO_REF"] = "video/desktop.mp4"
    os.environ["S03_DISPLAY_SCALE"] = os.environ.get("SHELL_DISPLAY_SCALE", "1")
    os.environ["S02_APP_PATH"] = os.environ.get("SHELL_APP_PATH", "")
    os.environ["S02_EVIDENCE_ROOT"] = str(scenario)
    os.environ["S02_JOB_ID"] = os.environ.get("SHELL_CELL", os.environ.get("GITHUB_JOB", "unknown"))
    os.environ["S02_DISTRIBUTION"] = "windows-11-arm" if os.environ.get("SHELL_CELL") == "win-client" else "windows-2025"
    os.environ["S02_TAURI_VERSION"] = "2.12.6"
    os.environ["S03_FEDORA_VERSION_ID"] = os.environ.get("SHELL_FEDORA_VERSION_ID", "unavailable")

    case_file = ROOT / "cases" / f"{spike}.json"
    assertion_specs = assertion_specs_for(spike, case_id)
    results = [{
        "id": str(spec.get("id")),
        "expected": spec.get("expected", "The lane assertion is measured with its required native evidence."),
        "actual": "UNVERIFIED: no lane automation adapter has supplied a result.",
        "verdict": "UNVERIFIED",
        "evidence": [],
    } for spec in assertion_specs if spec.get("id")]

    checkout = run(["git", "rev-parse", "HEAD"])
    source_sha = checkout.splitlines()[0] if checkout else ""
    frozen_sha = os.environ.get("FROZEN_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or (frozen_sha and source_sha != frozen_sha):
        raise SystemExit("checked-out source SHA does not match the supplied frozen dispatch SHA")

    cell = os.environ.get("SHELL_CELL", os.environ.get("GITHUB_JOB", "unknown"))
    if platform_name == "macos" and os.environ.get("SHELL_MAC_DISPLAY_PROBE"):
        # Recheck after XCTest and other hosted UI tooling have run.
        # Configure and read back again before each case and its recorder start.
        configured = subprocess.run([os.environ["SHELL_MAC_DISPLAY_PROBE"], "--configure"],
                                    capture_output=True, text=True, timeout=30, check=False)
        (scenario / "recorder/display-configuration.json").write_text(json.dumps({
            "exitCode": configured.returncode, "stdout": configured.stdout,
            "stderr": configured.stderr,
        }, indent=2) + "\n")
    print(f"PHASE {case_id} native-preflight", flush=True)
    native_preflight = collect_native_preflight(platform_name, scenario)
    s01_displays: list[dict] = []
    if platform_name == "macos" and spike == "s01" and os.environ.get("SHELL_S01_DISPLAYS_JSON"):
        try:
            display_value = json.loads(os.environ["SHELL_S01_DISPLAYS_JSON"])
            s01_displays = [row for row in display_value if isinstance(row, dict)] if isinstance(display_value, list) else []
        except json.JSONDecodeError:
            s01_displays = []
    release = linux_release() if platform_name == "linux" else {}
    measured_display = native_preflight.get("display", {})
    for field, variable in (("resolution", "SHELL_DISPLAY_RESOLUTION"), ("scale", "SHELL_DISPLAY_SCALE"), ("refreshHz", "SHELL_DISPLAY_REFRESH_HZ")):
        if measured_display.get(field) is not None:
            os.environ[variable] = str(measured_display[field])
    if platform_name == "windows" and native_preflight.get("webview"):
        os.environ["S02_WEBVIEW2_VERSION"] = str(native_preflight["webview"])
    environment = {
        "sourceSha": source_sha,
        "job": cell,
        "cell": cell,
        "caseId": case_id,
        "spike": spike,
        "runnerLabel": os.environ.get("RUNNER_NAME", "unknown"),
        "runnerImage": os.environ.get("ImageOS", "unavailable"),
        "runnerImageVersion": os.environ.get("ImageVersion", "unavailable"),
        "platform": platform_name,
        "linuxCompositor": os.environ.get("SHELL_LINUX_COMPOSITOR"),
        "os": platform.platform(),
        "distribution": os.environ.get("LINUX_DISTRO") or os.environ.get("S02_DISTRIBUTION") or release.get("PRETTY_NAME"),
        "distributionId": release.get("ID"),
        "distributionVersion": release.get("VERSION_ID"),
        "session": os.environ.get("SHELL_SESSION", "UNVERIFIED"),
        "display": native_preflight.get("display", {}),
        "displayStatus": native_preflight.get("displayStatus", "UNVERIFIED"),
        "s01Displays": s01_displays,
        "preflight": native_preflight,
        "versions": {
            "rustc": run(["rustc", "--version"]),
            "cargo": run(["cargo", "--version"]),
            "node": run(["node", "--version"]),
            "npm": run([shutil.which("npm") or "npm", "--version"]),
            "python": platform.python_version(),
            "pythonToolchain": os.environ.get("SHELL_TOOLCHAIN_PYTHON", platform.python_version()),
            "tauri": "2.12.6",
            "tauriCli": "2.12.5" if platform_name in {"ios", "android"} else None,
            "xcode": run(["xcodebuild", "-version"]) if platform_name in {"macos", "ios"} else None,
            "androidApiLevel": os.environ.get("ANDROID_API_LEVEL"),
            "webview": native_preflight.get("webview"),
            "webviewStatus": native_preflight.get("webviewStatus", "UNVERIFIED"),
            "androidSystemImage": os.environ.get("SHELL_ANDROID_SYSTEM_IMAGE"),
            "androidSdkManager": os.environ.get("SHELL_ANDROID_SDKMANAGER_VERSION"),
            "androidPlatformTools": os.environ.get("SHELL_ANDROID_ADB_VERSION"),
            "androidEmulator": os.environ.get("SHELL_ANDROID_EMULATOR_VERSION"),
            "androidNdk": os.environ.get("SHELL_ANDROID_NDK_VERSION"),
            "androidSdkPackages": os.environ.get("SHELL_ANDROID_SDK_PACKAGES"),
            "androidUiAutomator": os.environ.get("SHELL_UIAUTOMATOR_VERSION"),
            "androidUiAutomatorSha256": os.environ.get("SHELL_UIAUTOMATOR_SHA256"),
        },
        "simulator": {
            "name": os.environ.get("SHELL_IOS_SIMULATOR_NAME"),
            "runtime": os.environ.get("SHELL_IOS_SIMULATOR_RUNTIME"),
        } if platform_name == "ios" else None,
        "recorder": {"adapter": f"ci/recorders/{platform_name}", "status": "starting"},
    }
    if "runtimeDiscovery" not in environment:
        import importlib.util
        spec = importlib.util.spec_from_file_location("runtime_discovery", ROOT / "ci/runtime-discovery.py")
        discovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(discovery)
        discovery.record_runtime(scenario, environment)
    (evidence / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    assertions_path = evidence / "assertions.json"
    if assertions_path.exists():
        try:
            aggregate = json.loads(assertions_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            aggregate = {"sourceSha": environment["sourceSha"], "job": cell, "results": []}
    else:
        aggregate = {"sourceSha": environment["sourceSha"], "job": cell, "results": []}
    if not isinstance(aggregate, dict) or not isinstance(aggregate.get("results"), list):
        aggregate = {"sourceSha": environment["sourceSha"], "job": cell, "results": []}

    event_path = evidence / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as events:
        events.write(json.dumps({"monotonicTime": time.monotonic_ns(), "event": "scenario-start", "spike": spike, "caseId": case_id}) + "\n")

    extension = ".mp4" if platform_name in {"ios", "android"} else ".webm" if platform_name == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland" else ".mkv"
    recorder_output = scenario / "video" / f"capture{extension}"
    recorded_reference = recorder_output.relative_to(scenario).as_posix()
    os.environ["SHELL_CAPTURE_VIDEO"] = str(recorder_output)
    os.environ["SHELL_CAPTURE_VIDEO_RELATIVE"] = recorded_reference
    os.environ["SHELL_CAPTURE_INDEX"] = str(scenario / "video" / "capture-index.jsonl")
    os.environ["SHELL_CAPTURE_SEGMENT_INDEX"] = str(scenario / "video" / "index.json")
    os.environ["SHELL_CAPTURE_CLOCK_FILE"] = str(scenario / "recorder" / "capture-clock.json")
    if platform_name == "macos" and spike == "s01":
        os.environ["S01_NATIVE_EVENTS_SOURCE"] = str(scenario / "recorder" / "s01-events.jsonl")
    print(f"PHASE {case_id} recorder-start", flush=True)
    start_command, pid_file = recorder_commands(platform_name, "start", recorder_output)
    recorder_started = False
    capture_clock_path = scenario / "recorder" / "capture-clock.json"
    capture_clock_started = False
    version_ok, version_diagnostic = verify_recorder_version(platform_name)
    recorder_binary = (
        "adb" if platform_name == "android"
        else "gnome-shell" if platform_name == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland"
        else "xcrun" if platform_name == "ios"
        else "ffmpeg"
    )
    recorder_executable = shutil.which(recorder_binary)
    recorder_hash = sha256(Path(recorder_executable)) if recorder_executable and Path(recorder_executable).is_file() else None
    started = None
    if version_ok:
        try:
            record_capture_clock_sample(capture_clock_path, "start")
            capture_clock_started = True
            started = subprocess.run(start_command, capture_output=True, text=True, timeout=15, check=False)
            recorder_started = started.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            started = None
    else:
        version_diagnostic = f"Recorder preflight failed: {version_diagnostic}."
    environment["recorder"] = {
        "adapter": f"ci/recorders/{platform_name}",
        "status": "recording" if recorder_started else "UNVERIFIED",
        "runtime": version_diagnostic,
        "executableSha256": recorder_hash,
        "diagnostic": "" if recorder_started else version_diagnostic or "Recorder preflight failed or the required capture tool is unavailable.",
        "startExitCode": started.returncode if started else None,
        "startOutput": (started.stdout + started.stderr)[-4000:] if started else None,
    }
    environment["recording"] = {
        "video": recorded_reference,
        "index": "video/index.json" if platform_name == "android" else "video/capture-index.jsonl",
        "continuous": platform_name != "android",
    }
    (scenario / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")

    def make_video_alias(source: Path, alias: Path) -> None:
        if not source.is_file() or alias.exists():
            return
        alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, alias)
        except OSError:
            # This snapshot is only a path-compatibility alias. The canonical
            # recorder path remains in SHELL_CAPTURE_VIDEO and environment.json.
            shutil.copyfile(source, alias)

    lane_video_name = "android.mp4" if platform_name == "android" else "desktop.mp4"
    if platform_name != "android":
        make_video_alias(recorder_output, scenario / "video" / lane_video_name)

    launched_app: subprocess.Popen | None = None
    app_path = os.environ.get("SHELL_APP_PATH")
    adapter = find_adapter(platform_name, spike, case_id)
    adapter_status = 127
    recorder_stop_ok = recorder_started
    try:
        if platform_name == "linux" and spike == "s03" and app_path:
            with (scenario / "recorder/s03-app.log").open("w") as app_log:
                launched_app = subprocess.Popen([app_path], cwd=ROOT, env=os.environ.copy(),
                                               stdout=app_log, stderr=subprocess.STDOUT)
            os.environ["S03_APP_PID"] = str(launched_app.pid)
            time.sleep(1)
        if adapter is None:
            (scenario / "recorder" / "adapter-status.json").write_text(json.dumps({"status": "UNVERIFIED", "reason": "native automation adapter missing"}, indent=2) + "\n", encoding="utf-8")
        else:
            try:
                from process_watch import watched
                budget = 600 if platform_name == "ios" else {"s01": 900, "s02": 120, "s08": 600}.get(spike, 240)
                adapter_status = watched(adapter, label=f"{case_id}/native-adapter",
                                         timeout=int(os.environ.get("SHELL_CASE_TIMEOUT_SECONDS", str(budget))),
                                         cwd=ROOT, env=os.environ.copy())
            except (OSError, subprocess.TimeoutExpired) as error:
                (scenario / "recorder" / "adapter-status.json").write_text(json.dumps({"status": "UNVERIFIED", "reason": f"{type(error).__name__}"}, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        environment["recorder"]["appLaunch"] = f"UNVERIFIED: {type(error).__name__}"
    finally:
        # Android startup can time out after spawning its segment loop. Always
        # signal it to stop, even when its start command did not return cleanly.
        if recorder_started or platform_name == "android":
            stop_command, _ = recorder_commands(platform_name, "stop", recorder_output)
            try:
                stopped = subprocess.run(stop_command, capture_output=True, text=True, timeout=180, check=False)
                recorder_stop_ok = stopped.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                recorder_stop_ok = False
            if not recorder_stop_ok:
                environment["recorder"]["status"] = "UNVERIFIED"
                environment["recorder"]["diagnostic"] = "Recorder cleanup did not complete, including after startup failure."
        if capture_clock_started:
            record_capture_clock_sample(capture_clock_path, "stop")
        if launched_app is not None and launched_app.poll() is None:
            launched_app.terminate()
            try:
                launched_app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                launched_app.kill()
                launched_app.wait(timeout=5)
    media_source = recorder_output if recorder_output.is_file() else None
    if platform_name == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        filename_file = scenario / "recorder/wayland-screencast-filename.txt"
        try:
            returned_path = Path(filename_file.read_text(encoding="utf-8").strip()).resolve()
            returned_path.relative_to((scenario / "video").resolve())
            if returned_path.suffix.lower() == ".webm" and returned_path.is_file():
                media_source = returned_path
                environment["recording"]["segments"] = [returned_path.relative_to(scenario).as_posix()]
                environment["recording"]["continuous"] = True
            else:
                media_source = None
        except (OSError, ValueError):
            media_source = None
    if platform_name == "android":
        try:
            segment_index = json.loads((scenario / "video" / "index.json").read_text(encoding="utf-8"))
            segments = segment_index.get("segments", [])
            first_segment = scenario / "video" / str(segments[0]) if segments else None
            if first_segment is not None:
                media_source = first_segment
                make_video_alias(first_segment, scenario / "video" / lane_video_name)
                environment["recording"]["video"] = first_segment.relative_to(scenario).as_posix()
                environment["recording"]["segments"] = [str(item) for item in segments]
                environment["recording"]["continuous"] = segment_index.get("continuousCapture") is not False
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    elif media_source and media_source.is_file():
        if media_source != recorder_output:
            recorded_reference = media_source.relative_to(scenario).as_posix()
            environment["recording"]["video"] = recorded_reference
        make_video_alias(media_source, scenario / "video" / lane_video_name)
    if spike == "s08":
        # Keep the descriptive path used by older evidence consumers while
        # desktop.mp4 remains the current S08 adapter's canonical input.
        make_video_alias(scenario / "video" / "desktop.mp4", scenario / "video" / "s08-macos.mp4")

    if platform_name == "ios":
        collect_ios_xctest_evidence(spike, scenario)
        display = ios_display_measurement(scenario, native_preflight, case_id,
                                         os.environ.get("SHELL_IOS_SIMULATOR_UDID", ""))
        if display:
            native_preflight["display"] = display
            native_preflight["displayStatus"] = "measured"
            native_preflight.setdefault("evidence", {})["displayLinkProbe"] = "recorder/ios-display.json"
            environment["display"] = display
            environment["displayStatus"] = "measured"
            (scenario / "recorder/native-preflight.json").write_text(json.dumps(native_preflight, indent=2) + "\n")

    if platform_name in {"ios", "android"}:
        collect_mobile_renderer_events(platform_name, scenario, case_id)
    elif (scenario / "recorder" / "renderer-events.jsonl").is_file():
        append_renderer_events(scenario)

    if platform_name == "android" and spike == "s11":
        subprocess.run([sys.executable, str(ROOT / "automation/accent/runner.py"),
                        "--reduce-android", str(scenario), "--case-id", case_id], check=True, timeout=60)

    capture_index_ok = False
    if media_source and media_source.is_file():
        index_result = subprocess.run(
            [sys.executable, str(ROOT / "ci/recorders/index-video.py"), "--evidence-dir", str(scenario), "--video", str(media_source)],
            cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
        )
        (scenario / "recorder/capture-index-run.json").write_text(
            json.dumps({"status": "indexed" if index_result.returncode == 0 else "UNVERIFIED", "exitCode": index_result.returncode, "diagnostic": (index_result.stdout + index_result.stderr)[-2000:]}, indent=2) + "\n",
            encoding="utf-8",
        )
        environment["recording"]["index"] = "video/capture-index.jsonl" if index_result.returncode == 0 else None
        try:
            index_status = json.loads((scenario / "recorder/capture-index-status.json").read_text(encoding="utf-8"))
            capture_index_ok = (
                index_result.returncode == 0
                and index_status.get("status") == "indexed"
                and index_status.get("sequenceCorrelationStatus") == "measured"
                and environment["recording"].get("continuous") is True
            )
        except (OSError, json.JSONDecodeError):
            capture_index_ok = False
    elif platform_name != "android":
        (scenario / "recorder/capture-index-run.json").write_text(
            json.dumps({"status": "UNVERIFIED", "reason": "recorder produced no usable video file"}, indent=2) + "\n",
            encoding="utf-8",
        )

    if platform_name == "macos" and spike == "s01":
        finalize_s01_analysis(scenario, case_file)

    if spike == "s08":
        subprocess.run([sys.executable, str(ROOT / "ci/analyze-s08.py"), str(scenario)], check=True, timeout=600)
        case_events = scenario / "recorder/s08-case-events.jsonl"
        if case_events.is_file():
            subprocess.run([sys.executable, str(ROOT / "automation/macos/s08/reduce.py"), str(case_file),
                            case_id, str(case_events), str(scenario / "assertions.json"), str(scenario)], check=True, timeout=60)

    materialize_case_evidence_aliases(spike, scenario)
    if spike == "s02":
        materialize_s02_geometry(scenario)
    if spike == "s11":
        subprocess.run([sys.executable, str(ROOT / "ci/finalize-s11.py"), str(scenario)], check=True, timeout=60)
    refresh_lane_envelope(spike, scenario, case_file)
    (evidence / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    (scenario / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")

    lane_file = scenario / "assertions.json"
    if not lane_file.exists() and spike == "s03":
        lane_file = scenario / "s03-assertions.json"
    lane_results = root_relative_results(merge_lane_results(lane_file), scenario, evidence)
    lane_results = attach_case_evidence(lane_results, assertion_specs, scenario, evidence)
    android_index = scenario / "video" / "index.json"
    try:
        android_capture_has_gaps = platform_name == "android" and json.loads(android_index.read_text(encoding="utf-8")).get("continuousCapture") is False
    except (OSError, json.JSONDecodeError):
        android_capture_has_gaps = platform_name == "android"
    results, unexpected_results = normalize_results(
        spike,
        case_id,
        assertion_specs,
        lane_results,
        recorder_ok=recorder_started and recorder_stop_ok,
        webview_ok=bool(native_preflight.get("webview")),
        display_ok=native_preflight.get("displayStatus") == "measured",
        android_capture_has_gaps=android_capture_has_gaps,
        runtime_pinned=runtime_matches_pin(cell, environment),
        capture_index_ok=capture_index_ok,
    )
    if unexpected_results:
        (scenario / "recorder" / "result-integrity.json").write_text(json.dumps({"status": "UNVERIFIED", "unexpectedAssertionIds": [item.get("id") for item in unexpected_results]}, indent=2) + "\n", encoding="utf-8")

    aggregate.setdefault("results", []).extend({"cell": cell, "spike": spike, "caseId": case_id, **item} for item in results)
    assertions_path.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    cell_dir = evidence / "cells" / cell
    cell_dir.mkdir(parents=True, exist_ok=True)
    cell_environment_path = cell_dir / "environment.json"
    cell_environment_path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    cell_assertions_path = cell_dir / "assertions.json"
    try:
        cell_aggregate = json.loads(cell_assertions_path.read_text(encoding="utf-8")) if cell_assertions_path.exists() else {"sourceSha": environment["sourceSha"], "job": cell, "results": []}
    except (OSError, json.JSONDecodeError):
        cell_aggregate = {"sourceSha": environment["sourceSha"], "job": cell, "results": []}
    if not isinstance(cell_aggregate, dict) or not isinstance(cell_aggregate.get("results"), list):
        cell_aggregate = {"sourceSha": environment["sourceSha"], "job": cell, "results": []}
    cell_aggregate["results"].extend({"spike": spike, "caseId": case_id, **item} for item in results)
    cell_assertions_path.write_text(json.dumps(cell_aggregate, indent=2) + "\n", encoding="utf-8")
    scenario_events = scenario / "events.jsonl"
    if scenario_events.is_file():
        with event_path.open("a", encoding="utf-8") as root_events:
            for line in scenario_events.read_text(encoding="utf-8").splitlines():
                root_events.write(json.dumps({"source": scenario.relative_to(evidence).as_posix(), "record": line}) + "\n")
    with event_path.open("a", encoding="utf-8") as events:
        events.write(json.dumps({"monotonicTime": time.monotonic_ns(), "event": "scenario-finished", "spike": spike, "caseId": case_id, "automationExit": adapter_status}) + "\n")

    index_path = evidence / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"cases": []}
    index["cases"].append({"cell": cell, "spike": spike, "caseId": case_id, "assertions": [item.get("id") for item in results], "evidenceRoot": scenario.relative_to(evidence).as_posix()})
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    probe = {"platform": platform_name, "spike": spike, "caseId": case_id,
             "automationExit": adapter_status, "recorderStarted": recorder_started,
             "recorderStopped": recorder_stop_ok, "recorder": environment["recorder"],
             "assertions": [{"id": row.get("id"), "verdict": row.get("verdict"),
                             "laneVerdict": row.get("laneVerdict"), "actual": row.get("actual")}
                            for row in results]}
    probe["diagnosticLogs"] = {
        str(path.relative_to(scenario)): path.read_text(encoding="utf-8-sig", errors="replace")[-4000:]
        for path in (scenario / "video/capture.log", scenario / "recorder/s03-app.log",
                     scenario / "recorder/s01-xcodebuild.log", scenario / "recorder/desktop-readiness.json",
                     scenario / "recorder/driver-status.json", scenario / "recorder/ios-xctest-evidence-transport.json",
                     scenario / "recorder/s08-probe.log", scenario / "recorder/s08-ready.log",
                     scenario / "recorder/s02-startup-window-probe.json", scenario / "recorder/s02-app.stderr.log",
                     scenario / "recorder/accent-selection.txt", scenario / "recorder/native-readback.json",
                     scenario / "recorder/native-picker-fields.json", scenario / "recorder/s02-error.json",
                     scenario / "recorder/ios-display.json", scenario / "recorder/capture-index-status.json",
                     scenario / "recorder/xctest-resolved-environment.json")
        if path.is_file()
    }
    (scenario / "recorder/case-diagnostics.json").write_text(json.dumps(probe, indent=2) + "\n")
    print("Native case probe: " + json.dumps(probe), flush=True)
    incomplete = any(not item.get("laneVerdict") for item in results) or not results
    # Several native adapters use exit 1 for an emitted assertion FAIL. Keep that
    # verdict in the manifest; only execution/setup errors fail this step. The
    # independent execution guard and collector still reject fallback-only runs.
    assertion_exit = adapter_status == 1 and not incomplete and any(
        item.get("laneVerdict") == "FAIL" for item in results)
    execution_error = bool(adapter_status) and not assertion_exit
    return 1 if execution_error or incomplete or not recorder_started or not recorder_stop_ok else 0


if __name__ == "__main__":
    sys.exit(main())
