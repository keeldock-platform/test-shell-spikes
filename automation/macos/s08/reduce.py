#!/usr/bin/env python3
"""Reduce native S08 observations again after finalized media analysis."""
import hashlib, json, re, sys
from pathlib import Path
case_file, case_id, event_file, output, evidence_root = sys.argv[1:]
document = json.loads(Path(case_file).read_text(encoding="utf-8"))
case = next((item for item in document.get("cases", []) if item.get("id") == case_id), None)
if case is None:
    raise SystemExit(f"S08 case {case_id} is not in the case file")
definitions = {row["id"]: row for row in document.get("assertions", []) if isinstance(row, dict) and row.get("id")}
observed = {}
for line in Path(event_file).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("event") == "assertion" and row.get("id"):
        observed[row["id"]] = row
results = []
for reference in case.get("assertions", []):
    identifier = reference.get("id") if isinstance(reference, dict) else reference
    definition = reference if isinstance(reference, dict) else definitions.get(identifier, {})
    match = re.match(r"(S08-A\d+)", identifier or "")
    short_id = match.group(1) if match else identifier
    event = observed.get(short_id)
    expected = definition.get("expected", event.get("expected", "") if event else "")
    case_evidence = definition.get("evidence", []) if isinstance(definition.get("evidence", []), list) else []
    resolved_case_evidence = []
    for item in case_evidence:
        evidence_path = str(item).split("#", 1)[0]
        if evidence_path and (Path(evidence_root) / evidence_path).exists():
            resolved_case_evidence.append(str(item))
    if event:
        actual = str(event.get("actual", ""))
        verdict = event.get("verdict", "UNVERIFIED")
        evidence = list(event.get("evidence", []))
        evidence.extend(resolved_case_evidence)
        if short_id == "S08-A07":
            screen_result_path = Path(evidence_root) / "recorder/s08-screen-analysis.json"
            native_observation = next((json.loads(line) for line in Path(event_file).read_text(encoding="utf-8").splitlines()
                                       if line.strip() and json.loads(line).get("event") == short_id), {})
            screen_result = None
            if screen_result_path.is_file():
                screen_rows = json.loads(screen_result_path.read_text(encoding="utf-8")).get("results", [])
                screen_result = next((row for row in screen_rows if row.get("id") in {short_id, identifier}), None)
            native_ok = native_observation.get("settingsIsKey") is True and native_observation.get("mainInactiveMarker") is True
            video_path = Path(evidence_root) / "video/desktop.mp4"
            measurement_ok = False
            scrim_frames = None
            if isinstance(screen_result, dict) and video_path.is_file():
                try:
                    measured_frames = screen_result.get("framesAnalyzed")
                    classified_frames = screen_result.get("classifiedFrames")
                    scrim_frames = screen_result.get("scrimFrames")
                    unclassified_frames = screen_result.get("unclassifiedFrames")
                    video_digest = hashlib.sha256()
                    with video_path.open("rb") as capture:
                        for chunk in iter(lambda: capture.read(1024 * 1024), b""):
                            video_digest.update(chunk)
                    video_sha256 = video_digest.hexdigest()
                    measurement_ok = (
                        screen_result.get("captureScope") == "whole-desktop"
                        and screen_result.get("sourceVideo") == "video/desktop.mp4"
                        and screen_result.get("sourceSha256") == video_sha256
                        and isinstance(screen_result.get("method"), str)
                        and bool(screen_result.get("method"))
                        and type(measured_frames) is int and measured_frames > 0
                        and type(classified_frames) is int and classified_frames == measured_frames
                        and type(scrim_frames) is int and 0 <= scrim_frames <= measured_frames
                        and type(unclassified_frames) is int and unclassified_frames == 0
                    )
                except (OSError, ValueError, TypeError):
                    measurement_ok = False
            if not measurement_ok:
                verdict = "UNVERIFIED"
                actual = "UNVERIFIED: whole-desktop analysis is missing frame counts or a matching recording hash"
            elif scrim_frames > 0:
                verdict = "FAIL"
                actual = f"whole-desktop analysis measured scrim content in {scrim_frames} of {screen_result['framesAnalyzed']} frames"
            elif native_ok:
                verdict = "PASS"
                actual = f"whole-desktop analysis classified {screen_result['framesAnalyzed']} frames with no scrim; native focus and inactive state resolved"
            else:
                verdict = "UNVERIFIED"
                actual = "UNVERIFIED: native focus or inactive-window state did not resolve"
            if screen_result_path.is_file():
                evidence.append("recorder/s08-screen-analysis.json")
            if video_path.is_file():
                evidence.append("video/desktop.mp4")
            screenshot_path = Path(evidence_root) / "screens/s08-s1-12.png"
            if screenshot_path.is_file():
                evidence.append("screens/s08-s1-12.png")
        results.append({"id": identifier, "caseId": case_id, "expected": expected,
                        "actual": actual, "verdict": verdict, "evidence": list(dict.fromkeys(evidence))})
    elif short_id == "S08-A14":
        rust_results_path = Path(evidence_root) / "recorder/s08-rust-tests.json"
        required = {("settings", command) for command in [
            "s08_sentinel_tool_command", "s08_sentinel_pane_command", "s08_sentinel_tab_project_open",
            "s08_sentinel_mcp_command", "s08_sentinel_marketplace_command", "s08_sentinel_file_grant",
            "s08_open_settings", "s08_test_destroy_settings", "s08_test_lock_vault", "s08_test_unlock_vault",
        ]} | {("main", command) for command in [
            "s08_read_settings", "s08_write_setting", "s08_settings_schema", "s08_settings_search",
            "s08_update_shortcut", "s08_request_step_up", "s08_import_license", "s08_export_data",
            "s08_import_data", "s08_vault_passphrase_action", "s08_vault_recovery_action",
            "s08_project_settings", "s08_team_settings", "s08_get_view_state", "s08_set_view_state",
            "s08_window_geometry", "s08_hide_settings",
        ]}
        if rust_results_path.is_file():
            rust_rows = json.loads(rust_results_path.read_text(encoding="utf-8")).get("results", [])
            measured = {(row.get("windowLabel"), row.get("command")): row.get("allowed") for row in rust_rows if isinstance(row, dict)}
            missing = sorted(required - measured.keys())
            allowed = sorted(key for key in required if measured.get(key) is True)
            unresolved = sorted(key for key in required if measured.get(key) is not False)
            verdict = "FAIL" if allowed else "PASS" if not unresolved else "UNVERIFIED"
            actual = (f"{len(required)} host authorization pairs checked; {len(unresolved)} missing or unresolved; "
                      f"{len(allowed)} unexpected allows")
            evidence = resolved_case_evidence
            evidence.append("recorder/s08-rust-tests.json")
        else:
            verdict = "UNVERIFIED"
            actual = "UNVERIFIED: the coordinator did not provide structured Rust authorization results"
            evidence = resolved_case_evidence
        results.append({"id": identifier, "caseId": case_id, "expected": expected,
                        "actual": actual, "verdict": verdict, "evidence": evidence})
    elif short_id == "S08-A15":
        acl_path = Path(evidence_root) / "recorder/s08-acl-manifest.json"
        if acl_path.is_file():
            manifest = json.loads(acl_path.read_text(encoding="utf-8"))
            compiled_record = manifest.get("compiledAcl") if isinstance(manifest, dict) else None
            compiled_document = None
            compiled_path = None
            if isinstance(compiled_record, dict):
                relative_path = compiled_record.get("path")
                if isinstance(relative_path, str):
                    candidate = Path(relative_path)
                    artifact_root = Path(evidence_root).resolve()
                    if (not candidate.is_absolute() and ".." not in candidate.parts
                            and candidate.parts[:1] == ("recorder",)):
                        candidate = (artifact_root / candidate).resolve()
                        try:
                            if candidate.is_file() and candidate.is_relative_to(artifact_root):
                                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                            else:
                                digest = None
                            if (digest is not None
                                    and compiled_record.get("status") == "captured"
                                    and compiled_record.get("provenance") == "compiled-build"
                                    and compiled_record.get("sha256") == digest):
                                compiled_document = json.loads(candidate.read_text(encoding="utf-8"))
                                compiled_path = relative_path
                        except (OSError, ValueError, TypeError):
                            compiled_document = None
            if (isinstance(manifest, dict)
                    and manifest.get("buildStatus") == "completed"
                    and isinstance(compiled_document, dict)
                    and compiled_document.get("provenance") == "compiled-build"
                    and isinstance(compiled_document.get("windowCapabilities"), dict)
                    and isinstance(compiled_document.get("capabilities"), list)):
                assignments = compiled_document.get("windowCapabilities", {})
                capability_rows = [row for row in compiled_document.get("capabilities", []) if isinstance(row, dict)]
                settings_rows = [row for row in capability_rows
                                 if isinstance(row.get("windows"), list)
                                 and ("settings" in row.get("windows", []) or "*" in row.get("windows", []))]
                settings_capability = next((row for row in settings_rows if row.get("identifier") == "settings"), None)
                grants = compiled_document.get("resolvedCommandGrantsByWindow", {}).get("settings")
                inputs = compiled_document.get("compiledInputs", [])
                inputs_ok = (len(inputs) == 2 and {item.get("path") for item in inputs} == {
                    "recorder/s08-acl-inputs/acl-manifests.json", "recorder/s08-acl-inputs/capabilities.json"})
                for source in inputs:
                    relative = Path(source.get("path", ""))
                    candidate = (Path(evidence_root) / relative).resolve()
                    inputs_ok = inputs_ok and not relative.is_absolute() and ".." not in relative.parts
                    inputs_ok = inputs_ok and candidate.is_relative_to(Path(evidence_root).resolve())
                    inputs_ok = inputs_ok and candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == source.get("sha256")
                resolution_ok = compiled_document.get("permissionResolutionStatus") == "resolved" and isinstance(grants, dict) and inputs_ok
                allowed_settings = {
                    "s08_read_settings", "s08_write_setting", "s08_settings_schema", "s08_settings_search",
                    "s08_update_shortcut", "s08_request_step_up", "s08_import_license", "s08_export_data",
                    "s08_import_data", "s08_vault_passphrase_action", "s08_vault_recovery_action",
                    "s08_project_settings", "s08_team_settings", "s08_get_view_state", "s08_set_view_state",
                    "s08_window_geometry", "s08_hide_settings",
                }
                allowed_settings = {f"plugin:s08-settings|{command}" for command in allowed_settings}
                shared = {"selected_spike", "selected_case", "record_renderer_event", "plugin:event|listen", "plugin:event|unlisten"}
                unexpected_permissions = [command for command, allowed in (grants or {}).items()
                                          if allowed is True and command not in allowed_settings | shared]
                retained_inputs = [source["path"] for source in inputs] if inputs_ok else []
                assigned_ids = [identifier for identifier, windows in assignments.items()
                                if isinstance(windows, list) and ("settings" in windows or "*" in windows)]
                exclusive = (assignments.get("settings") == ["settings"]
                             and assigned_ids == ["settings"]
                             and len(settings_rows) == 1
                             and settings_capability is not None
                             and settings_capability.get("windows") == ["settings"])
                platform_ok = settings_capability is not None and settings_capability.get("platforms") == ["macOS"]
                required_settings_ok = isinstance(grants, dict) and all(grants.get(command) is True for command in allowed_settings)
                resolved = exclusive and platform_ok and resolution_ok and required_settings_ok
                verdict = "UNVERIFIED" if not resolution_ok else "FAIL" if unexpected_permissions or not required_settings_ok or (settings_rows and not exclusive) else "PASS" if resolved else "UNVERIFIED"
                actual = (f"compiled settings assignment exclusive={exclusive}; macOS-only={platform_ok}; "
                          f"direct filesystem/dialog grants={unexpected_permissions}")
                evidence = [*resolved_case_evidence, "recorder/s08-acl-manifest.json", compiled_path, *retained_inputs]
            else:
                verdict = "UNVERIFIED"
                actual = "UNVERIFIED: compiled ACL provenance and its hash-verified resolved manifest are unavailable"
                evidence = [*resolved_case_evidence, "recorder/s08-acl-manifest.json"]
        else:
            verdict = "UNVERIFIED"
            actual = "UNVERIFIED: the coordinator did not provide the compiled capability manifest"
            evidence = resolved_case_evidence
        results.append({"id": identifier, "caseId": case_id, "expected": expected,
                        "actual": actual, "verdict": verdict, "evidence": evidence})
    else:
        results.append({"id": identifier, "caseId": case_id, "expected": expected,
                        "actual": "UNVERIFIED: the native probe did not emit this assertion",
                        "verdict": "UNVERIFIED", "evidence": resolved_case_evidence})
Path(output).write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
