#!/usr/bin/env python3
"""Write honest case-level fallbacks for Linux profiles not provisioned here."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from case_catalog import CELL_CASES, assertion_specs_for, fallback_for

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence")).resolve()


def checked_out_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    value = result.stdout.strip()
    expected = os.environ.get("FROZEN_SHA", "")
    if len(value) != 40 or (expected and value != expected):
        raise RuntimeError("checkout does not match the supplied frozen source SHA")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_hashes() -> None:
    lines = []
    for path in sorted(item for item in EVIDENCE.rglob("*") if item.is_file() and item.name != "hashes.sha256"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(EVIDENCE).as_posix()}")
    (EVIDENCE / "hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    cell = os.environ.get("SHELL_CELL", "")
    if not cell.startswith("linux-") or cell not in CELL_CASES:
        raise RuntimeError(f"no explicit Linux routing is defined for {cell!r}")
    source_sha = checked_out_sha()
    distribution = os.environ.get("LINUX_DISTRO", "Unavailable Linux profile")
    session = os.environ.get("LINUX_SESSION", "unverified")
    reason = os.environ.get("SHELL_LINUX_FALLBACK_REASON", "No pinned guest or release/session profile is provisioned for this Linux cell.")
    environment = {
        "sourceSha": source_sha,
        "job": os.environ.get("GITHUB_JOB", "linux-gui"),
        "cell": cell,
        "runnerLabel": os.environ.get("RUNNER_NAME", "unknown"),
        "runnerImage": os.environ.get("ImageOS", "unavailable"),
        "runnerImageVersion": os.environ.get("ImageVersion", "unavailable"),
        "platform": "linux",
        "os": platform.platform(),
        "distribution": distribution,
        "session": session,
        "status": "UNVERIFIED",
        "execution": "not-started",
        "runtimeDiscovery": {"status": "UNVERIFIED", "resolvedVersion": None, "artifacts": [],
                             "reason": "Cell is not provisioned; no substitute host runtime is installed or frozen."},
        "reason": reason,
        "versions": {"tauri": "2.12.6", "webview": None},
    }
    results = []
    cases_index = []
    for spike, case_ids in CELL_CASES[cell].items():
        for case_id in case_ids:
            scenario_root = EVIDENCE / "spikes" / spike / case_id
            specs = assertion_specs_for(spike, case_id)
            case_results = []
            selection = fallback_for(cell, spike, case_id)
            for spec in specs:
                row = {
                    "spike": spike,
                    "caseId": case_id,
                    "id": spec.get("id"),
                    "expected": spec.get("expected", "Native evidence from the selected Linux profile"),
                    "actual": "UNVERIFIED: " + reason,
                    "verdict": "UNVERIFIED",
                    "evidence": [],
                    "fallbackSelection": selection,
                }
                results.append(row)
                case_results.append(row)
            write_json(scenario_root / "environment.json", {**environment, "spike": spike, "caseId": case_id})
            write_json(scenario_root / "assertions.json", {"sourceSha": source_sha, "results": case_results})
            cases_index.append({"cell": cell, "spike": spike, "caseId": case_id, "assertions": [row["id"] for row in case_results], "fallbackSelection": selection})

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for name in ("screens", "video", "recorder"):
        (EVIDENCE / name).mkdir(exist_ok=True)
    cell_environment = {**environment, "status": "UNVERIFIED"}
    write_json(EVIDENCE / "environment.json", cell_environment)
    write_json(EVIDENCE / "assertions.json", {"sourceSha": source_sha, "job": cell, "results": results})
    write_json(EVIDENCE / "index.json", {"cases": cases_index})
    cell_dir = EVIDENCE / "cells" / cell
    write_json(cell_dir / "environment.json", cell_environment)
    write_json(cell_dir / "assertions.json", {"sourceSha": source_sha, "job": cell, "results": results})
    (EVIDENCE / "events.jsonl").write_text(json.dumps({"event": "profile-not-provisioned", "cell": cell, "fallbacksRecorded": len(results)}) + "\n", encoding="utf-8")
    write_hashes()
    print(f"Recorded {len(results)} UNVERIFIED Linux assertions and per-case fallback selections for {cell}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
