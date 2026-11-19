#!/usr/bin/env python3
"""Reject credentials, machine-local paths, and external renderer access."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", "target", "dist", "gen", "__pycache__"}
# Assemble common home-directory roots so this source can scan itself without
# matching the path signature embedded in its own detector.
_LOCAL_ROOTS = ("/" + "Us" + "ers" + "/", "/" + "ho" + "me" + "/")
LOCAL_PATH = re.compile("(?:" + "|".join(re.escape(root) + r"[^/]+/" for root in _LOCAL_ROOTS) + ")", re.I)
SECRET = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?i:password|secret|token)\s*[:=]\s*['\"][^'\"]{8,})"
)
REMOTE_API = re.compile(
    r"(?:\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\s*\(|\bwindow\.open\s*\(|"
    r"\blocation(?:\.href)?\s*=\s*['\"]https?://)",
    re.I,
)


def files() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return found


def main() -> int:
    failures: list[str] = []
    for path in files():
        relative = path.relative_to(ROOT).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in (("machine-local path", LOCAL_PATH), ("secret-like value", SECRET)):
            match = pattern.search(content)
            if match:
                failures.append(f"{relative}: found {label}")
        if path.suffix.lower() in {".html", ".js", ".mjs", ".ts"} and REMOTE_API.search(content):
            failures.append(f"{relative}: external navigation or network API found")

    for manifest in (ROOT / "package.json", ROOT / "package-lock.json", ROOT / "ci/environment-lock.json", ROOT / "cases/schema.json"):
        try:
            json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{manifest.relative_to(ROOT)}: invalid JSON ({error})")

    cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    for name, value in cargo.get("workspace", {}).get("dependencies", {}).items():
        version = value.get("version") if isinstance(value, dict) else value
        if not isinstance(version, str) or not version.startswith("="):
            failures.append(f"Cargo.toml: Rust dependency {name} is not exactly pinned")
    npm_manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    for dependency_group in ("dependencies", "devDependencies"):
        for name, version in npm_manifest.get(dependency_group, {}).items():
            if version.startswith(("^", "~", ">", "*")):
                failures.append(f"package.json: JavaScript dependency {name} is not exactly pinned")
            locked = package_lock.get("packages", {}).get(f"node_modules/{name}", {}).get("version")
            if locked != version:
                failures.append(f"package-lock.json: {name} does not match package.json")

    workflow = (ROOT / ".github/workflows/shell-spikes.yml").read_text(encoding="utf-8")
    for match in re.finditer(r"^\s*uses:\s+([^\s]+)$", workflow, re.MULTILINE):
        action_ref = match.group(1).rsplit("@", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{40}", action_ref):
            failures.append(f".github/workflows/shell-spikes.yml: unpinned action {match.group(1)}")
    if not (ROOT / "Cargo.lock").is_file():
        failures.append("Cargo.lock: missing; create and review it on a trusted hosted runner before dispatch")

    if failures:
        print("Public source check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Public source check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
