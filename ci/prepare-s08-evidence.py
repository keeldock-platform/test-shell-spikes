#!/usr/bin/env python3
"""Produce the structured S08 authorization and capability inputs on the runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "apps/desktop/src-tauri"

SETTINGS_DENIALS = [
    "s08_sentinel_tool_command", "s08_sentinel_pane_command", "s08_sentinel_tab_project_open",
    "s08_sentinel_mcp_command", "s08_sentinel_marketplace_command", "s08_sentinel_file_grant",
    "s08_open_settings", "s08_test_destroy_settings", "s08_test_lock_vault", "s08_test_unlock_vault",
]
MAIN_DENIALS = [
    "s08_read_settings", "s08_write_setting", "s08_settings_schema", "s08_settings_search",
    "s08_update_shortcut", "s08_request_step_up", "s08_import_license", "s08_export_data",
    "s08_import_data", "s08_vault_passphrase_action", "s08_vault_recovery_action",
    "s08_project_settings", "s08_team_settings", "s08_get_view_state", "s08_set_view_state",
    "s08_window_geometry", "s08_hide_settings",
]


def qualified_command(namespace: str, command: str) -> str:
    if namespace == "__app-acl__" or command.startswith("plugin:"):
        return command
    plugin = namespace.removeprefix("core:")
    return f"plugin:{plugin}|{command}"


def resolve_permission(manifests: dict, reference: str, *, seen: set[str] | None = None) -> tuple[set[str], set[str], bool]:
    """Resolve one compiled Tauri permission or permission set to commands."""
    seen = set() if seen is None else seen
    if reference in seen:
        return set(), set(), False
    seen.add(reference)
    if ":" in reference:
        namespace, identifier = reference.rsplit(":", 1)
    else:
        namespace, identifier = "__app-acl__", reference
    manifest = manifests.get(namespace)
    if not isinstance(manifest, dict):
        return set(), set(), False
    permission = manifest.get("permissions", {}).get(identifier) if isinstance(manifest.get("permissions"), dict) else None
    if isinstance(permission, dict):
        commands = permission.get("commands", {})
        if not isinstance(commands, dict):
            return set(), set(), False
        allow = commands.get("allow", [])
        deny = commands.get("deny", [])
        if not isinstance(allow, list) or not isinstance(deny, list):
            return set(), set(), False
        return {qualified_command(namespace, str(value)) for value in allow}, {qualified_command(namespace, str(value)) for value in deny}, True
    permission_set = manifest.get("permission_sets", {}).get(identifier) if isinstance(manifest.get("permission_sets"), dict) else None
    if isinstance(permission_set, dict):
        nested = permission_set.get("permissions", [])
        if not isinstance(nested, list):
            return set(), set(), False
        allow: set[str] = set()
        deny: set[str] = set()
        complete = True
        for nested_reference in nested:
            if not isinstance(nested_reference, str):
                complete = False
                continue
            if ":" not in nested_reference and namespace != "__app-acl__":
                nested_reference = f"{namespace}:{nested_reference}"
            nested_allow, nested_deny, resolved = resolve_permission(manifests, nested_reference, seen=seen.copy())
            allow.update(nested_allow)
            deny.update(nested_deny)
            complete = complete and resolved
        return allow, deny, complete
    command_names = manifest.get("commands", [])
    if isinstance(command_names, list):
        for prefix, enabled in (("allow-", True), ("deny-", False)):
            if identifier.startswith(prefix):
                slug = identifier[len(prefix):]
                matching = {str(value) for value in command_names if str(value).replace("_", "-") == slug}
                if matching:
                    qualified = {qualified_command(namespace, value) for value in matching}
                    return (qualified, set(), True) if enabled else (set(), qualified, True)
    return set(), set(), False


def resolve_capability_grants(manifests: dict, capability: dict) -> tuple[list[dict], dict[str, object], list[str]]:
    references = capability.get("permissions", [])
    if not isinstance(references, list):
        return [], {}, ["capability permissions are not a list"]
    allow: set[str] = set()
    deny: set[str] = set()
    rows: list[dict] = []
    unresolved: list[str] = []
    for raw_reference in references:
        reference = raw_reference if isinstance(raw_reference, str) else (
            raw_reference.get("identifier") if isinstance(raw_reference, dict) else None
        )
        if not isinstance(reference, str):
            unresolved.append(str(raw_reference))
            continue
        grants, denials, resolved = resolve_permission(manifests, reference)
        rows.append({"identifier": reference, "status": "resolved" if resolved else "UNVERIFIED",
                     "allowedCommands": sorted(grants), "deniedCommands": sorted(denials)})
        if not resolved:
            unresolved.append(reference)
        allow.update(grants)
        deny.update(denials)
    effective = {
        command: {"allowed": command in allow and command not in deny}
        for command in sorted(allow | deny)
    }
    return rows, effective, unresolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    recorder = args.output_dir / "recorder"
    recorder.mkdir(parents=True, exist_ok=True)

    log_path = recorder / "s08-rust-tests.log"
    command = [
        "cargo", "test", "--locked", "--manifest-path", str(DESKTOP / "Cargo.toml"),
        "--features", "spike-s08", "--lib", "--", "--nocapture",
    ]
    try:
        test = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900, check=False)
        log = "$ " + " ".join(command) + "\n" + test.stdout + test.stderr
        test_status = test.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        log = f"UNVERIFIED: Rust authorization checks could not complete ({type(error).__name__}).\n"
        test_status = 78
    log_path.write_text(log, encoding="utf-8")
    results = []
    if test_status == 0:
        results = [
            {"windowLabel": "settings", "command": command_name, "allowed": False,
             "test": "host_allowlist_matches_only_settings_window_commands"}
            for command_name in SETTINGS_DENIALS
        ] + [
            {"windowLabel": "main", "command": command_name, "allowed": False,
             "test": "host_allowlist_matches_only_settings_window_commands"}
            for command_name in MAIN_DENIALS
        ]
    (recorder / "s08-rust-tests.json").write_text(
        json.dumps({"status": "passed" if test_status == 0 else "UNVERIFIED", "results": results}, indent=2) + "\n",
        encoding="utf-8",
    )

    capabilities = []
    window_capabilities: dict[str, list[str]] = {}
    for capability_file in sorted((DESKTOP / "capabilities").glob("*.json")):
        capability = json.loads(capability_file.read_text(encoding="utf-8"))
        windows = capability.get("windows", [])
        identifier = str(capability.get("identifier", capability_file.stem))
        window_capabilities[identifier] = windows
        capabilities.append({
            "identifier": identifier,
            "windows": windows,
            "platforms": capability.get("platforms", ["macOS", "windows", "linux"]),
            "permissions": capability.get("permissions", []),
            "buildInput": capability_file.relative_to(ROOT).as_posix(),
        })
    generated_schema_path = DESKTOP / "gen/schemas/desktop-schema.json"
    generated_schema_copy = recorder / "s08-generated-permission-schema.json"
    generated_schema_status = "UNVERIFIED"
    generated_schema_sha256 = None
    if generated_schema_path.is_file():
        try:
            generated_schema = json.loads(generated_schema_path.read_text(encoding="utf-8"))
            generated_schema_copy.write_text(json.dumps(generated_schema, indent=2) + "\n", encoding="utf-8")
            generated_schema_sha256 = hashlib.sha256(generated_schema_path.read_bytes()).hexdigest()
            generated_schema_status = "captured"
        except (OSError, json.JSONDecodeError):
            generated_schema_status = "UNVERIFIED"

    # Tauri writes the permission manifests and parsed capabilities into the
    # build script OUT_DIR. Use those exact build outputs as the ACL evidence
    # source; the checked-in capability files above are context only.
    compiled_acl = None
    compiled_acl_status = "UNVERIFIED"
    out_root = ROOT / "target" / "release" / "build"
    candidates = sorted(
        (path for path in out_root.glob("shell-spike-desktop-*/out")
         if (path / "acl-manifests.json").is_file() and (path / "capabilities.json").is_file()),
        key=lambda path: min((path / "acl-manifests.json").stat().st_mtime_ns,
                             (path / "capabilities.json").stat().st_mtime_ns),
        reverse=True,
    ) if out_root.is_dir() else []
    for out_dir in candidates:
        try:
            acl_path = out_dir / "acl-manifests.json"
            capabilities_path = out_dir / "capabilities.json"
            acl_manifests = json.loads(acl_path.read_text(encoding="utf-8"))
            build_capabilities = json.loads(capabilities_path.read_text(encoding="utf-8"))
            config = json.loads((DESKTOP / "tauri.conf.json").read_text(encoding="utf-8"))
            selected = config.get("app", {}).get("security", {}).get("capabilities", [])
            if not isinstance(acl_manifests, dict) or not isinstance(build_capabilities, dict):
                continue
            if not isinstance(selected, list) or not selected:
                continue
            capability_rows = []
            window_capabilities: dict[str, list[str]] = {}
            window_allowed: dict[str, set[str]] = {}
            window_denied: dict[str, set[str]] = {}
            unresolved_references: list[dict[str, str]] = []
            for identifier in selected:
                capability = build_capabilities.get(identifier)
                if not isinstance(capability, dict):
                    unresolved_references.append({"capability": str(identifier), "permission": "compiled capability is missing"})
                    continue
                windows = capability.get("windows", [])
                if not isinstance(windows, list):
                    continue
                window_capabilities[str(identifier)] = [str(window) for window in windows]
                resolved_permissions, effective_grants, unresolved = resolve_capability_grants(acl_manifests, capability)
                for reference in unresolved:
                    unresolved_references.append({"capability": str(identifier), "permission": reference})
                capability_rows.append({
                    "identifier": str(identifier),
                    "windows": windows,
                    "platforms": capability.get("platforms", ["macOS", "windows", "linux"]),
                    "permissions": capability.get("permissions", []),
                    "resolvedPermissions": resolved_permissions,
                    "resolvedCommandGrants": effective_grants,
                    "buildInput": "tauri-build OUT_DIR/capabilities.json",
                })
                for window in windows:
                    window_name = str(window)
                    window_allowed.setdefault(window_name, set()).update(
                        command for command, grant in effective_grants.items() if grant.get("allowed") is True
                    )
                    window_denied.setdefault(window_name, set()).update(
                        command for command, grant in effective_grants.items() if grant.get("allowed") is False
                    )
            if not capability_rows or "s08-settings" not in acl_manifests:
                continue
            all_commands = set()
            for namespace, manifest in acl_manifests.items():
                if not isinstance(manifest, dict):
                    continue
                all_commands.update(qualified_command(namespace, value) for value in manifest.get("commands", []) if isinstance(value, str))
                for permission in manifest.get("permissions", {}).values() if isinstance(manifest.get("permissions"), dict) else []:
                    if isinstance(permission, dict) and isinstance(permission.get("commands"), dict):
                        all_commands.update(qualified_command(namespace, value) for value in permission["commands"].get("allow", []) if isinstance(value, str))
                        all_commands.update(qualified_command(namespace, value) for value in permission["commands"].get("deny", []) if isinstance(value, str))
            resolved_by_window = {}
            all_windows = sorted({str(window) for capability in capability_rows for window in capability.get("windows", [])})
            for window in all_windows:
                allowed = window_allowed.get(window, set())
                denied = window_denied.get(window, set())
                resolved_by_window[window] = {
                    command: command in allowed and command not in denied
                    for command in sorted(all_commands | allowed | denied)
                }
            inputs_dir = recorder / "s08-acl-inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            acl_copy = inputs_dir / "acl-manifests.json"
            capabilities_copy = inputs_dir / "capabilities.json"
            shutil.copyfile(acl_path, acl_copy)
            shutil.copyfile(capabilities_path, capabilities_copy)
            compiled_document = {
                "provenance": "compiled-build",
                "buildProfile": "release",
                "sourceSha": subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT,
                    capture_output=True, text=True, check=True,
                ).stdout.strip(),
                "windowCapabilities": window_capabilities,
                "capabilities": capability_rows,
                "resolvedCommandGrantsByWindow": resolved_by_window,
                "permissionResolutionStatus": "resolved" if not unresolved_references else "UNVERIFIED",
                "unresolvedPermissionReferences": unresolved_references,
                "compiledInputs": [
                    {"path": "recorder/s08-acl-inputs/acl-manifests.json", "sha256": hashlib.sha256(acl_copy.read_bytes()).hexdigest()},
                    {"path": "recorder/s08-acl-inputs/capabilities.json", "sha256": hashlib.sha256(capabilities_copy.read_bytes()).hexdigest()},
                ],
            }
            compiled_path = recorder / "s08-compiled-acl.json"
            compiled_path.write_text(json.dumps(compiled_document, indent=2) + "\n", encoding="utf-8")
            compiled_acl = {
                "status": "captured" if not unresolved_references else "UNVERIFIED",
                "provenance": "compiled-build",
                "path": "recorder/s08-compiled-acl.json",
                "sha256": hashlib.sha256(compiled_path.read_bytes()).hexdigest(),
            }
            compiled_acl_status = "resolved" if not unresolved_references else "UNVERIFIED"
            break
        except (OSError, json.JSONDecodeError, KeyError, TypeError, subprocess.CalledProcessError):
            continue

    (recorder / "s08-acl-manifest.json").write_text(
        json.dumps({
            "buildStatus": "completed" if compiled_acl else "UNVERIFIED",
            "compiledAcl": compiled_acl,
            "compiledAclStatus": compiled_acl_status,
            "generatedPermissionSchema": {
                "status": generated_schema_status,
                "path": "recorder/s08-generated-permission-schema.json" if generated_schema_status == "captured" else None,
                "sha256": generated_schema_sha256,
            },
            "windowCapabilities": window_capabilities,
            "capabilities": capabilities,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
