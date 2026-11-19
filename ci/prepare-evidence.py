#!/usr/bin/env python3
"""Create uploadable diagnostic manifests before any build or GUI step."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence"))
cell = os.environ.get("SHELL_CELL", os.environ.get("GITHUB_JOB", "unknown"))
checkout_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
frozen_sha = os.environ.get("FROZEN_SHA", "")
if not re.fullmatch(r"[0-9a-f]{40}", checkout_sha) or (frozen_sha and checkout_sha != frozen_sha):
    raise SystemExit("checked-out source SHA does not match the frozen dispatch SHA")
# Validate the same frozen-input and discovery guards before creating evidence.
subprocess.run([sys.executable, str(ROOT / "ci/check-frozen-inputs.py")], cwd=ROOT, check=True)
OUTPUT.mkdir(parents=True, exist_ok=True)
for directory in ("screens", "video", "recorder"):
    (OUTPUT / directory).mkdir(parents=True, exist_ok=True)
environment = {
    "sourceSha": checkout_sha,
    "job": os.environ.get("GITHUB_JOB", "unknown"),
    "cell": cell,
    "runnerImage": os.environ.get("ImageOS", "unavailable"),
    "runnerImageVersion": os.environ.get("ImageVersion", "unavailable"),
    "os": platform.platform(),
    "session": os.environ.get("SHELL_SESSION", "UNVERIFIED"),
    "status": "preflight",
}
(OUTPUT / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
(OUTPUT / "assertions.json").write_text(json.dumps({"sourceSha": environment["sourceSha"], "job": cell, "results": []}, indent=2) + "\n", encoding="utf-8")
(OUTPUT / "events.jsonl").write_text(json.dumps({"event": "evidence-directory-created", "cell": cell}) + "\n", encoding="utf-8")
(OUTPUT / "index.json").write_text(json.dumps({"cases": []}, indent=2) + "\n", encoding="utf-8")

hash_lines = []
for path in sorted(item for item in OUTPUT.rglob("*") if item.is_file() and item.name != "hashes.sha256"):
    hash_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(OUTPUT).as_posix()}")
(OUTPUT / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")
print(f"Evidence directory prepared for {cell}.")
