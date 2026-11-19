#!/usr/bin/env python3
"""Validate runner evidence and select the documented fallback per cell."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from case_catalog import CELL_CASES, assertion_specs_for, case_ids_for, fallback_for

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CELLS = json.loads((ROOT / "ci/environment-lock.json").read_text(encoding="utf-8"))["requiredCells"]
REQUIRED_SPIKES = {cell: tuple(spikes) for cell, spikes in CELL_CASES.items()}
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}
RUNTIME_POLICY = json.loads((ROOT / "ci/environment-lock.json").read_text(encoding="utf-8")).get("runtimePolicy", {})


def sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, dict) else {}


def cell_name(environment: dict) -> str:
    return str(environment.get("cell") or environment.get("job") or "unknown")


def png_is_valid(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
        return (
            len(header) >= 24
            and header[:8] == b"\x89PNG\r\n\x1a\n"
            and header[12:16] == b"IHDR"
            and int.from_bytes(header[16:20], "big") > 0
            and int.from_bytes(header[20:24], "big") > 0
        )
    except OSError:
        return False


def capture_index_is_valid(root: Path, index_path: Path) -> tuple[bool, str]:
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False, "capture index could not be read"
    if not lines:
        return False, "capture index is empty"
    case_root = index_path.parent.parent.resolve()
    try:
        case_root.relative_to(root.resolve())
    except ValueError:
        return False, "capture index case directory escapes the artifact"
    previous_number: int | None = None
    previous_timestamp: int | None = None
    for line_number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return False, f"capture index row {line_number} is invalid JSON"
        if not isinstance(row, dict):
            return False, f"capture index row {line_number} is not an object"
        try:
            frame_number = int(row["frameNumber"])
            timestamp = int(row["timestampNanoseconds"])
        except (KeyError, TypeError, ValueError):
            return False, f"capture index row {line_number} lacks its frame number or timestamp"
        frame_reference = row.get("relativePath")
        if not isinstance(frame_reference, str) or not frame_reference:
            return False, f"capture index row {line_number} lacks a frame path"
        frame_relative = Path(frame_reference)
        if frame_relative.is_absolute() or ".." in frame_relative.parts:
            return False, f"capture index row {line_number} has an unsafe frame path"
        frame_path = (case_root / frame_relative).resolve()
        try:
            frame_path.relative_to(case_root)
        except ValueError:
            return False, f"capture index row {line_number} escapes its case directory"
        if not frame_path.is_file() or not png_is_valid(frame_path):
            return False, f"capture index frame is missing or invalid: {frame_reference}"
        if previous_number is not None and frame_number != previous_number + 1:
            return False, f"capture index frame number gap before {frame_number}"
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            return False, f"capture index timestamps are not increasing at frame {frame_number}"
        previous_number, previous_timestamp = frame_number, timestamp
    return True, ""


def assertion_path_is_valid(root: Path, reference: object) -> tuple[bool, str]:
    value = str(reference)
    relative, marker, selector = value.partition("#")
    if not relative:
        return False, "empty evidence reference"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return False, "evidence path escapes artifact"
    if not candidate.is_file():
        return False, f"evidence missing: {relative}"
    if marker and not selector:
        return False, f"empty evidence selector: {relative}#"
    if marker and selector:
        selector_found = False
        if candidate.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            if selector.startswith("case="):
                parts = Path(relative).parts
                video_index = parts.index("video") if "video" in parts else -1
                selector_found = video_index >= 2 and parts[video_index - 1] == selector.partition("=")[2]
            elif selector.startswith("t="):
                try:
                    timestamp = float(selector.partition("=")[2])
                    ffprobe = shutil.which("ffprobe")
                    probe = subprocess.run(
                        [ffprobe or "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(candidate)],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    ) if ffprobe else None
                    duration = float(probe.stdout.strip()) if probe and probe.returncode == 0 else 0.0
                    selector_found = timestamp >= 0 and duration > 0 and timestamp <= duration
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    selector_found = False
        else:
            try:
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return False, f"selected evidence could not be read: {relative}"
        if candidate.name.endswith(".jsonl"):
            for line in content.splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if selector in line:
                    selector_found = True
                    break
                if isinstance(record, dict):
                    key, separator, expected = selector.partition("=")
                    candidate_value = record.get({"case": "caseId", "seq": "sequence", "id": "id", "frame": "frameNumber"}.get(key, key))
                    if separator and str(candidate_value) == expected:
                        selector_found = True
                        break
                    if not separator and selector in {str(value) for value in record.values() if isinstance(value, (str, int))}:
                        selector_found = True
                        break
        elif candidate.suffix.lower() == ".json":
            try:
                document = json.loads(content)
            except json.JSONDecodeError:
                document = None
            if isinstance(document, dict):
                rows = document.get("results", [])
                selector_found = isinstance(rows, list) and any(
                    isinstance(row, dict) and str(row.get("id", "")) == selector
                    for row in rows
                )
        if not selector_found:
            return False, f"evidence selector not found: {relative}#{selector}"
    if ((relative.startswith("screens/") or "/screens/" in relative)
            or (relative.startswith("video/") or "/video/" in relative)) and candidate.suffix.lower() == ".png":
        if not png_is_valid(candidate):
            return False, f"unreadable PNG evidence: {relative}"
    if candidate.name == "capture-index.jsonl":
        valid, reason = capture_index_is_valid(root, candidate)
        if not valid:
            return False, reason
    if (relative.startswith("video/") or "/video/" in relative) and candidate.suffix.lower() in VIDEO_SUFFIXES:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return False, "ffprobe is unavailable for media validation"
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "json", str(candidate)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            streams = json.loads(probe.stdout).get("streams", []) if probe.returncode == 0 else []
            if not any(item.get("codec_type") == "video" for item in streams if isinstance(item, dict)):
                return False, f"video evidence has no readable video stream: {relative}"
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return False, f"video evidence could not be probed: {relative}"
    return True, ""


def required_source_satisfied(source: str, references: list[str]) -> bool:
    names = [item.split("#", 1)[0].replace("\\", "/") for item in references]
    source_path, has_selector, selector = source.partition("#")
    source_lower = source_path.lower()
    if has_selector:
        return any(
            name.endswith(source_lower)
            and any(selector in reference for reference in references)
            for name in names
        )
    if source_lower == "screen":
        return any(path.startswith("screens/") or "/screens/" in path for path in names)
    if source_lower == "video":
        return any(path.startswith("video/") or "/video/" in path for path in names)
    if source_lower == "frame-marker":
        return any(path.endswith("events.jsonl") or "frame-marker" in path for path in names) and any(path.startswith("video/") or "/video/" in path for path in names)
    if source_lower in {"events.jsonl", "os-event"}:
        return any(path.endswith("events.jsonl") or "os-event" in path for path in names)
    if source_lower == "native-tree":
        return any("native-tree" in path or "accessibility-tree" in path for path in names)
    if source_lower == "native-readback":
        return any("native-readback" in path or "readback" in path for path in names)
    if source_lower == "geometry-json":
        return any("geometry" in path and path.endswith(".json") for path in names)
    if source_lower == "environment.json":
        return any(path.endswith("environment.json") for path in names)
    if source_lower == "assertions.json":
        return any(path.endswith("assertions.json") for path in names)
    if source_lower == "webview2-accelerator":
        return any("accelerator" in path or path.endswith("events.jsonl") for path in names)
    if source_lower.endswith("/"):
        return any(path.startswith(source_lower) or f"/{source_lower}" in path for path in names)
    if source_lower.startswith(("screens/", "video/", "recorder/", "source/")):
        return any(path.endswith(source_lower) for path in names)
    return any(source_lower in path.lower() for path in names)


def expected_pairs(cell: str) -> dict[tuple[str, str], list[dict]]:
    expected: dict[tuple[str, str], list[dict]] = {}
    for spike in REQUIRED_SPIKES.get(cell, ()):
        for case_id in case_ids_for(spike, cell):
            expected[(spike, case_id)] = assertion_specs_for(spike, case_id)
    return expected


def runtime_matches_pin(cell: str, environment: dict) -> bool:
    expected = RUNTIME_POLICY.get("exactRuntimeVersionsByCell", {}).get(cell)
    if not isinstance(expected, dict) or not expected or RUNTIME_POLICY.get("passRequiresExactRuntimeMatch") is not True:
        return False
    for dotted_key, expected_value in expected.items():
        observed: object = environment
        for part in str(dotted_key).split("."):
            observed = observed.get(part) if isinstance(observed, dict) else None
        if str(observed) != str(expected_value):
            return False
    return True


def presentation_calibration_report(source):
    affected = [cell for cell in REQUIRED_CELLS if cell.startswith("android-api-") or cell.endswith("-wayland")]
    rows = []
    for cell in affected:
        cases = []
        for path in source.rglob("capture-index-status.json"):
            try:
                status = load_json(path)
                environment = load_json(path.parent.parent / "environment.json")
            except (OSError, ValueError):
                continue
            if cell_name(environment) == cell:
                cases.append({"caseId": environment.get("caseId"), "clockCalibrated": status.get("clockCalibrated") is True,
                              "evidence": str(path.relative_to(source))})
        calibrated = bool(cases) and all(row["clockCalibrated"] for row in cases)
        rows.append({"cell": cell, "status": "measured" if calibrated else "UNVERIFIED", "cases": cases,
                     "reason": "All observed capture clocks calibrated." if calibrated else "Accepted spike gap: no calibrated host-time origin for one or more Android screenrecord/GNOME Wayland captures, or cell unavailable; no presentation PASS."})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("collected"))
    parser.add_argument("--output", type=Path, default=Path("collection"))
    parser.add_argument("--expected-sha", default="")
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    cells: dict[str, dict] = {}
    cell_results: dict[str, list[dict]] = {}
    cell_artifacts: dict[str, Path] = {}
    cell_source_mismatches: dict[str, list[str]] = {}
    observed_source_shas: dict[str, set[str]] = {}
    problems: list[str] = []
    manifests = sorted(source.rglob("environment.json"))

    def is_aggregate_manifest(path: Path) -> bool:
        relative = path.parent.relative_to(source)
        if "spikes" in relative.parts:
            return True
        return len(relative.parts) == 1 and (path.parent / "cells").is_dir()

    manifests = [path for path in manifests if not is_aggregate_manifest(path)]
    for environment_path in manifests:
        manifest_dir = environment_path.parent
        artifact_root = manifest_dir.parents[1] if manifest_dir.parent.name == "cells" else manifest_dir
        try:
            environment = load_json(environment_path)
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{environment_path}: invalid environment manifest ({error})")
            continue
        cell = cell_name(environment)
        cells[cell] = {"cell": cell, "environment": environment}
        cell_artifacts[cell] = artifact_root
        environment_sha = str(environment.get("sourceSha") or "")
        if environment_sha:
            observed_source_shas.setdefault(cell, set()).add(environment_sha)
        if args.expected_sha and environment_sha != args.expected_sha:
            reason = f"environment observed source SHA {environment_sha or '<missing>'}; expected {args.expected_sha}"
            problems.append(f"{cell}: {reason}")
            cell_source_mismatches.setdefault(cell, []).append(reason)
        assertions_path = manifest_dir / "assertions.json"
        if not assertions_path.exists():
            problems.append(f"{cell}: assertions.json is missing")
            continue
        try:
            assertion_manifest = load_json(assertions_path)
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{cell}: invalid assertions.json ({error})")
            continue
        if not isinstance(assertion_manifest, dict):
            problems.append(f"{cell}: assertions.json must use a {{results: [...]}} envelope")
            continue
        assertions = assertion_manifest.get("results")
        if not isinstance(assertions, list):
            problems.append(f"{cell}: assertions.json must use a {{results: [...]}} envelope")
            continue
        assertion_sha = str(assertion_manifest.get("sourceSha") or "")
        if assertion_sha:
            observed_source_shas.setdefault(cell, set()).add(assertion_sha)
        if args.expected_sha and assertion_sha != args.expected_sha:
            reason = f"assertions observed source SHA {assertion_sha or '<missing>'}; expected {args.expected_sha}"
            problems.append(f"{cell}: {reason}")
            cell_source_mismatches.setdefault(cell, []).append(reason)
        for result in assertions:
            if not isinstance(result, dict) or result.get("verdict") not in {"PASS", "FAIL", "UNVERIFIED"}:
                problems.append(f"{cell}: malformed assertion result")
                continue
            references = result.get("evidence", [])
            if not isinstance(references, list):
                problems.append(f"{cell}/{result.get('id')}: evidence must be an array")
                references = []
            if result.get("verdict") in {"PASS", "FAIL"}:
                for reference in references:
                    ok, diagnostic = assertion_path_is_valid(artifact_root, reference)
                    if not ok:
                        result = {**result, "verdict": "UNVERIFIED", "actual": f"Required evidence could not be verified: {diagnostic}"}
                        break
            result = {**result, "observedSourceSha": assertion_sha or environment_sha or None}
            if cell_source_mismatches.get(cell):
                diagnostic = "; ".join(dict.fromkeys(cell_source_mismatches[cell]))
                result = {
                    **result,
                    "verdict": "UNVERIFIED",
                    "actual": f"UNVERIFIED: source SHA did not match the frozen checkout ({diagnostic}).",
                }
            result = {"cell": cell, **result}
            cell_results.setdefault(cell, []).append(result)

    matrix_results: list[dict] = []
    fallback_selections: list[dict] = []
    for required in REQUIRED_CELLS:
        expected = expected_pairs(required)
        actual_results = cell_results.get(required, [])
        actual_by_case: dict[tuple[str, str], list[dict]] = {}
        for result in actual_results:
            key = (str(result.get("spike", "")), str(result.get("caseId", "")))
            actual_by_case.setdefault(key, []).append(result)

        environment = cells.get(required, {}).get("environment", {})
        artifact_root = cell_artifacts.get(required)
        android_capture_has_gaps = False
        if required.startswith("android-") and artifact_root:
            segment_indexes = list(artifact_root.rglob("video/index.json"))
            android_capture_has_gaps = not segment_indexes
            for segment_index in segment_indexes:
                try:
                    capture_index = load_json(segment_index)
                    android_capture_has_gaps = android_capture_has_gaps or capture_index.get("continuousCapture") is False
                except (OSError, json.JSONDecodeError):
                    android_capture_has_gaps = True

        for (spike, case_id), specs in expected.items():
            observed = actual_by_case.get((spike, case_id), [])
            spec_by_id = {str(item.get("id")): item for item in specs if item.get("id")}
            observed_by_id: dict[str, list[dict]] = {}
            for result in observed:
                observed_by_id.setdefault(str(result.get("id", "")), []).append(result)
            for identifier, duplicates in observed_by_id.items():
                if identifier not in spec_by_id:
                    problems.append(f"{required}/{spike}/{case_id}: unexpected assertion {identifier}")
                elif len(duplicates) > 1:
                    problems.append(f"{required}/{spike}/{case_id}: duplicate assertion {identifier}")

            for identifier, spec in spec_by_id.items():
                rows = observed_by_id.get(identifier, [])
                fallback = fallback_for(required, spike, case_id)
                if len(rows) != 1:
                    verdict = "UNVERIFIED"
                    actual = "No unique assertion result was collected for this declared assertion."
                    evidence: list[str] = []
                    if len(rows) > 1:
                        actual = "Duplicate results were collected; assertion coverage is ambiguous."
                else:
                    row = dict(rows[0])
                    verdict = row.get("verdict", "UNVERIFIED")
                    actual = str(row.get("actual", ""))
                    evidence = row.get("evidence", []) if isinstance(row.get("evidence"), list) else []
                    required_evidence = spec.get("evidence", []) if isinstance(spec.get("evidence"), list) else []
                    missing_sources = [
                        str(item) for item in required_evidence
                        if not required_source_satisfied(str(item), [str(ref) for ref in evidence])
                    ]
                    if verdict in {"PASS", "FAIL"} and missing_sources:
                        verdict = "UNVERIFIED"
                        actual = "Required evidence sources are missing: " + ", ".join(missing_sources)
                    if android_capture_has_gaps and "video" in required_evidence and "frame-marker" in required_evidence:
                        verdict = "UNVERIFIED"
                        actual = "Android recording uses restarted segments; capture gaps cannot establish a one-frame assertion."
                if cell_source_mismatches.get(required):
                    verdict = "UNVERIFIED"
                    actual = "UNVERIFIED: source SHA mismatch: " + "; ".join(dict.fromkeys(cell_source_mismatches[required]))
                if verdict == "PASS" and not runtime_matches_pin(required, environment):
                    verdict = "UNVERIFIED"
                    actual = "UNVERIFIED: this cell has no reviewed exact host-runtime version pin."
                record = {
                    "cell": required,
                    "spike": spike,
                    "caseId": case_id,
                    "id": identifier,
                    "expected": spec.get("expected", "Declared case assertion"),
                    "actual": actual,
                    "verdict": verdict,
                    "evidence": evidence,
                }
                if cell_source_mismatches.get(required):
                    record["observedSourceShas"] = sorted(observed_source_shas.get(required, set()))
                    record["expectedSourceSha"] = args.expected_sha
                if verdict in {"FAIL", "UNVERIFIED"}:
                    record["fallbackSelection"] = fallback
                    record["fallbackReason"] = actual
                    fallback_selections.append({"cell": required, "spike": spike, "caseId": case_id, "assertionId": identifier, "selection": fallback})
                matrix_results.append(record)

    all_observed_shas = sorted({sha for values in observed_source_shas.values() for sha in values})
    summary = {
        "sourceSha": all_observed_shas[0] if len(all_observed_shas) == 1 else None,
        "expectedSourceSha": args.expected_sha or None,
        "observedSourceShas": all_observed_shas,
        "expectedCells": REQUIRED_CELLS,
        "observedCells": sorted(cells),
        "fallbackSelections": fallback_selections,
        "presentationCalibration": presentation_calibration_report(source),
        "runtimePolicy": RUNTIME_POLICY,
        "runtimeDiscovery": [{"cell": cell, **cells.get(cell, {}).get("environment", {}).get("runtimeDiscovery",
                                  {"status": "UNVERIFIED", "reason": "No runtime discovery evidence collected."})}
                             for cell in REQUIRED_CELLS],
        "results": matrix_results,
        "problems": problems,
    }
    (output / "result-matrix.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "index.json").write_text(json.dumps({"cells": cells, "resultMatrix": "result-matrix.json"}, indent=2) + "\n", encoding="utf-8")
    hash_lines = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "hashes.sha256"):
        hash_lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

    unverified = sum(result.get("verdict") == "UNVERIFIED" for result in matrix_results)
    failed = sum(result.get("verdict") == "FAIL" for result in matrix_results)
    print(f"Collected {len(cells)} cells, {len(matrix_results)} assertions, {unverified} unverified, {failed} failed.")
    if problems:
        print("Collection problems:")
        for problem in problems:
            print(f"- {problem}")
    return 1 if problems or unverified or failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
