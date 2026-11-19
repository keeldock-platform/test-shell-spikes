#!/usr/bin/env python3
"""Seal upload contents after recorders, emulators and compositor cleanup exit."""
import os
from pathlib import Path

from run_case import write_hashes

root = Path(os.environ.get("SHELL_EVIDENCE_DIR", "evidence"))
if root.is_dir():
    write_hashes(root)
    print(f"Finalized evidence hashes in {root}.")
