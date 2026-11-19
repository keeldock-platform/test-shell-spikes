#!/usr/bin/env python3
"""Write a public, path-free status record for a native accent run."""

import argparse
import json
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--platform", required=True)
parser.add_argument("--case", required=True)
parser.add_argument("--cell", required=True)
parser.add_argument("--reason", required=True)
parser.add_argument("--evidence-dir", required=True, type=Path)
args = parser.parse_args()

destination = args.evidence_dir / "recorder" / "driver-status.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps({
    "platform": args.platform,
    "caseId": args.case,
    "cell": args.cell,
    "verdict": "UNVERIFIED",
    "fallback": "System hidden; stored System resolves to the test brand colour.",
    "reason": args.reason,
}, indent=2) + "\n", encoding="utf-8")
