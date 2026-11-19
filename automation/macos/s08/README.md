# S08 macOS native probe

`probe.swift` is a source artifact for the hosted macOS desktop job. Do not compile or run it on the authoring workstation. The runner invokes `bash automation/macos/s08/run.sh`; the adapter launches the built app, checks the visible ready marker without requesting permissions, then invokes the native probe once for readiness and once for the selected case:

```sh
bash automation/macos/s08/run.sh
```

PowerShell Core can use `pwsh -File automation/macos/s08/run.ps1` as a forwarding
entry point; it invokes the same macOS adapter and artifact contract.

Supported scenarios are `entry`, `tool-settings`, `sheet`, `geometry`, `mock-lock`, and `permissions`, with `ready` reserved for the ready-marker check. Each probe attaches to the running app by bundle identifier and writes timestamped native events and per-assertion observations to JSONL. The adapter extracts those records into `events.jsonl` and serializes a stable `{ "results": [...] }` assertion document; evidence that is not supplied by the native probe remains `UNVERIFIED`.

The helper reads the macOS Accessibility tree and on-screen CoreGraphics window list, maps the Settings and main windows to native window identifiers, and sends native Command+Comma, Option+Command+Comma, Command+W, clicks, wheel, and window geometry changes. It records both native outer bounds and the Tauri-reported logical content size. It does not use DOM automation as proof of native chrome, dialog, or sheet behavior.

Accessibility preflight uses `AXIsProcessTrusted()` without requesting consent. If trust is unavailable, the app bundle cannot be found, a required native tree is missing, or a case cannot resolve its evidence, the scenario must be recorded as `UNVERIFIED`; the runner must not show or bypass a macOS permission prompt. The helper never reads or records picker paths. Picker tests cancel each parented native panel.

## Required runner and recorder behavior

- Run only on the `macos-15` desktop session with the S08 feature and `SHELL_SPIKE_ID=s08`; report the bundle ID, display resolution, backing scale, refresh rate, Tauri/WebKit versions, and exact source SHA.
- Record the whole desktop, including both native windows and attached AppKit sheets, at the shared 60 fps target. Preserve capture timestamps and upload video, screenshots, native events, assertion pointers, recorder metadata, and hashes even on failure or timeout.
- Verify S08-A07's inactive main window from the visible native state and whole-desktop frames. The Swift helper records the active native window IDs; video analysis must decide whether any scrim or overlay appeared. If the recorder cannot resolve this, mark it `UNVERIFIED`.
- Verify the Accessibility `AXSheets` parent relationship and `AXSheet` role for the step-up and each host picker. A child window or WebView layer does not count.
- Produce the compiled ACL manifest for the exact app configuration. Verify the settings capability assignment is exclusive to the `settings` label on macOS and contains no direct fs/dialog plugin grant. Include the S08 Rust host-authorization test output; a successful frontend mock IPC alone is not evidence of production capability enforcement.
- Keep all fixture text and picker selections synthetic. Do not collect real account, vault, project, team, license, or filesystem data.

The adapter accepts S08-A07 only when `recorder/s08-screen-analysis.json` identifies the finalized canonical recording `video/desktop.mp4`, carries that file's SHA-256, reports `captureScope: "whole-desktop"`, a nonempty method, positive `framesAnalyzed`, matching `classifiedFrames`, zero `unclassifiedFrames`, and a measured `scrimFrames` count. A positive scrim count is `FAIL`; missing or inconsistent measurements remain `UNVERIFIED`.

For S08-A15, `recorder/s08-acl-manifest.json` must point to a hash-matching `compiledAcl` artifact with `status: "captured"` and `provenance: "compiled-build"`. The referenced JSON must also identify compiled-build provenance and contain the resolved `windowCapabilities` and `capabilities`. Source capability files and generated permission schemas are attached as context but cannot establish a pass.
