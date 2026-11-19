#!/usr/bin/env python3
"""Turn native accent-driver observations into the stable collector envelope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


VERDICTS = {"PASS", "FAIL", "UNVERIFIED"}


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def safe_evidence(root: Path, references):
    safe = []
    for reference in references if isinstance(references, list) else []:
        if not isinstance(reference, str):
            continue
        candidate = Path(reference)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        if (root / candidate).is_file():
            safe.append(candidate.as_posix())
    return safe


def has_source(root: Path, source: str) -> bool:
    files = [path for path in root.rglob("*") if path.is_file()]
    names = [path.relative_to(root).as_posix().lower() for path in files]
    source = source.lower()
    if source in {"events.jsonl", "os-event"}:
        return any(name.endswith("events.jsonl") or name.endswith("os-event.jsonl") for name in names)
    if source == "frame-marker":
        return has_source(root, "events.jsonl") and has_source(root, "video")
    if source == "video":
        return any(name.startswith("video/") and Path(name).suffix in {".mp4", ".mov", ".mkv"} for name in names)
    if source == "screen":
        return any((name.startswith("screens/") and Path(name).suffix in {".png", ".jpg", ".jpeg"})
                   or (name.startswith("recorder/") and Path(name).suffix in {".png", ".jpg", ".jpeg"}) for name in names)
    if source == "native-tree":
        return any(name.startswith("recorder/") and ("tree" in name or "accessibility" in name) for name in names)
    if source == "native-readback":
        return any(any(token in name for token in ("native-readback", "readback", "portal-probe")) for name in names)
    if source == "environment.json":
        return (root / "environment.json").is_file()
    if source == "geometry-json":
        return any("geometry" in name and name.endswith(".json") for name in names)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    evidence_root = args.evidence_dir.resolve()
    case_file = read_json(args.case_file, {})
    case = next((item for item in case_file.get("cases", []) if item.get("id") == args.case_id), None)
    if case is None:
        print(f"case not found: {args.case_id}", file=sys.stderr)
        return 2

    observations = read_json(evidence_root / "recorder" / "observations.json", {})
    driver_status = read_json(evidence_root / "recorder" / "driver-status.json", {})
    observed = observations.get("assertions", {}) if isinstance(observations, dict) else {}
    fallback = observations.get("fallback") if isinstance(observations, dict) else None
    fallback = fallback or "System hidden; a stored System selection resolves to the test brand colour."
    results = []

    for assertion in case.get("assertions", []):
        assertion_id = assertion if isinstance(assertion, str) else assertion.get("id")
        expected = "Recorded by the native accent driver." if isinstance(assertion, str) else assertion.get("expected")
        supplied = observed.get(assertion_id, {}) if isinstance(observed, dict) else {}
        verdict = supplied.get("verdict") if isinstance(supplied, dict) else None
        references = safe_evidence(evidence_root, supplied.get("evidence", []) if isinstance(supplied, dict) else [])
        actual = supplied.get("actual") if isinstance(supplied, dict) else None
        if verdict not in VERDICTS:
            verdict = "UNVERIFIED"
            actual = actual or driver_status.get("reason") or "Native event, ready marker, or complete presentation evidence is unavailable."
            if (evidence_root / "recorder" / "driver-status.json").is_file():
                references = ["recorder/driver-status.json"]
        elif verdict in {"PASS", "FAIL"} and not references:
            verdict = "UNVERIFIED"
            actual = "Required native evidence did not resolve inside the evidence directory."
        required = assertion.get("evidence", []) if isinstance(assertion, dict) else []
        missing_sources = [source for source in required if isinstance(source, str) and not has_source(evidence_root, source)]
        if verdict in {"PASS", "FAIL"} and missing_sources:
            verdict = "UNVERIFIED"
            actual = f"Required evidence sources are missing: {', '.join(missing_sources)}."

        actual_text = str(actual or "No assertion-specific observation was produced.")
        actual_text += f" Selected fallback: {fallback}"
        results.append({
            "id": assertion_id,
            "expected": expected,
            "actual": actual_text,
            "verdict": verdict,
            "evidence": references,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
