#!/usr/bin/env python3
"""Validate manifests, schema files, assertion references, and CI routing."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from case_catalog import CELL_CASES

ROOT = Path(__file__).resolve().parents[1]
SPIKES = ("s01", "s02", "s03", "s08", "s10", "s11")


def assertion_id(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and isinstance(item.get("id"), str):
        return item["id"]
    return None


def main() -> int:
    problems: list[str] = []
    root_manifest = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    tauri_version = root_manifest.get("workspace", {}).get("dependencies", {}).get("tauri", "")
    if tauri_version != "=2.12.6":
        problems.append("workspace Tauri pin must remain exactly =2.12.6")
    dependencies = root_manifest.get("workspace", {}).get("dependencies", {})
    for name, value in dependencies.items():
        version = value.get("version") if isinstance(value, dict) else value
        if not isinstance(version, str) or not version.startswith("="):
            problems.append(f"workspace dependency {name} is not exact-pinned")

    desktop_manifest = tomllib.loads((ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    features = desktop_manifest.get("features", {})
    registry = (ROOT / "apps/desktop/src-tauri/src/spikes/mod.rs").read_text(encoding="utf-8")
    renderer = (ROOT / "apps/desktop/web/bootstrap.js").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "cases/schema.json").read_text(encoding="utf-8"))
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        problems.append("case schema must declare Draft 2020-12")

    case_data: dict[str, dict] = {}
    for spike in SPIKES:
        feature = f"spike-{spike}"
        module = {
            "s01": "s01_traffic_lights.rs", "s02": "s02_system_menu.rs", "s03": "s03_gnome_menu.rs",
            "s08": "s08_settings.rs", "s10": "s10_colour_input.rs", "s11": "s11_accent.rs",
        }[spike]
        for path in (
            ROOT / "apps/desktop/src-tauri/src/spikes" / module,
            ROOT / "apps/desktop/web/spikes" / f"{spike}.js",
            ROOT / "cases" / f"{spike}.json",
        ):
            if not path.is_file():
                problems.append(f"required lane input is missing: {path.relative_to(ROOT)}")
        if feature not in features:
            problems.append(f"Cargo feature is missing: {feature}")
        if not re.search(rf'feature\s*=\s*"{re.escape(feature)}"', registry):
            problems.append(f"Rust registry is missing cfg for {feature}")
        if f'"{spike}"' not in renderer:
            problems.append(f"renderer bootstrap does not allow {spike}")

        case_file = ROOT / "cases" / f"{spike}.json"
        if not case_file.is_file():
            continue
        data = json.loads(case_file.read_text(encoding="utf-8"))
        case_data[spike] = data
        if data.get("schemaVersion") != 1 or data.get("spike") not in {spike, f"SHELL-SPIKE-{spike[1:]}"}:
            problems.append(f"case metadata does not match {spike}")
        cases = data.get("cases", [])
        case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
        if len(case_ids) != len(set(case_ids)):
            problems.append(f"case IDs are not unique in cases/{spike}.json")

        top_level = [item for item in data.get("assertions", []) if isinstance(item, dict)]
        definitions = {item["id"]: item for item in top_level if isinstance(item.get("id"), str)}
        if len(definitions) != len(top_level):
            problems.append(f"top-level assertion IDs are missing or duplicated in cases/{spike}.json")
        seen_assertions = set(definitions)
        for case in cases:
            if not isinstance(case, dict):
                continue
            for assertion in case.get("assertions", []):
                identifier = assertion_id(assertion)
                if identifier is None:
                    continue
                if isinstance(assertion, str):
                    if identifier not in definitions:
                        problems.append(f"unresolved assertion reference {identifier} in cases/{spike}.json")
                elif identifier in seen_assertions:
                    problems.append(f"duplicate assertion ID {identifier} in cases/{spike}.json")
                else:
                    seen_assertions.add(identifier)

    for cell, spikes in CELL_CASES.items():
        for spike, mapped_ids in spikes.items():
            available = {case.get("id") for case in case_data.get(spike, {}).get("cases", []) if isinstance(case, dict)}
            for case_id in mapped_ids:
                if case_id not in available:
                    problems.append(f"cell mapping references missing case {spike}/{case_id} in {cell}")

    lock = json.loads((ROOT / "ci/environment-lock.json").read_text(encoding="utf-8"))
    if set(lock.get("requiredCells", [])) != set(CELL_CASES):
        problems.append("required cell list and explicit case routing map differ")
    if not (ROOT / "Cargo.lock").is_file():
        problems.append("Cargo.lock is missing")

    mobile_capability = json.loads((ROOT / "apps/test-shell-mobile/src-tauri/capabilities/mobile.json").read_text(encoding="utf-8"))
    if "s11-accent:allow-current-accent" in mobile_capability.get("permissions", []):
        problems.append("Android-only S11 snapshot permission must not be granted to iOS")
    android_capability = json.loads((ROOT / "apps/test-shell-mobile/src-tauri/capabilities/android.json").read_text(encoding="utf-8"))
    android_permissions = android_capability.get("permissions", [])
    required_android_permissions = {
        "s11-accent:allow-accent-listeners",
        "core:event:allow-emit", "s11-accent:allow-current-accent",
    }
    if not required_android_permissions.issubset(set(android_permissions)):
        problems.append("Android event bridge or S11 snapshot permissions are incomplete")
    if android_capability.get("platforms") != ["android"]:
        problems.append("Android event bridge permissions must remain Android-only")
    if "allow-record-renderer-event" not in mobile_capability.get("permissions", []):
        problems.append("mobile renderer event recorder permission is missing")

    settings_capability = json.loads((ROOT / "apps/desktop/src-tauri/capabilities/settings.json").read_text(encoding="utf-8"))
    settings_permissions = settings_capability.get("permissions", [])
    if not all(item in settings_permissions for item in ("dialog:deny-open", "dialog:deny-save", "dialog:deny-message")):
        problems.append("Settings capability must explicitly deny direct dialog IPC")
    if not all(item in settings_permissions for item in ("allow-selected-spike", "allow-selected-case")):
        problems.append("Settings capability must allow shared selection reads during bootstrap")
    if any(item.startswith("dialog:allow-") or item == "dialog:default" for item in settings_permissions):
        problems.append("Settings capability must not grant direct dialog IPC")

    schema_check = subprocess.run(
        ["node", str(ROOT / "ci/validate-cases.mjs")],
        cwd=ROOT,
        check=False,
    )
    if schema_check.returncode:
        problems.append("Draft 2020-12 validation rejected one or more lane case files")

    if problems:
        print("Scaffold validation failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Scaffold manifests, case schema, assertion references, and CI routing are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
