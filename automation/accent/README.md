# Accent runner helpers

These helpers are for disposable hosted runner sessions only. They are never preparation
commands for a local workstation. They change an actual OS preference through the native Settings UI or
GNOME setting, then read the resulting preference independently of the S11 web renderer.

| File | Runner use |
|---|---|
| `macos-select-accent.applescript` | Accessibility driven selection in System Settings. The runner must grant the automation helper its setup-only Accessibility access and record that grant separately from accent-reader permissions. |
| `macos-readback.swift` | Read `NSColor.controlAccentColor`, convert to sRGB, and emit a machine-readable value. |
| `windows-select-accent.ps1` | Open the Colors settings page and invoke the named accent swatch through UI Automation. Do not set the registry directly. |
| `windows-readback.cpp` | Read `UISettings.GetColorValue(UIColorType::Accent)` in a separate process. |
| `linux-probe.sh` | Record GNOME/session, portal service introspection, interface version, and key support before a live case. |
| `linux-change-accent.sh` | Change the actual GNOME `accent-color` setting only when that setting exists, then independently read the portal value. |
| `android-open-wallpaper-picker.sh` | Open Android's real wallpaper UI; the UiAutomator case selects and applies the wallpaper. |

The lane entry points launch the selected shell and collect the shared ready/event marker before
running these helpers. Invoke from the repository root with `SHELL_CASE_ID`, `SHELL_CELL`, and
`SHELL_EVIDENCE_DIR`; every run writes `assertions.json` as `{ "results": [...] }`.

- macOS desktop: `bash automation/macos/s11/run.sh`
- Windows desktop: `powershell -File automation/windows/s11/run.ps1`
- Linux GNOME: `bash automation/linux/s11/run.sh`
- iPhone/iPad policy fixture: `bash automation/ios/s11/run.sh`; System remains hidden by policy and no accent reader is launched.
- Android API 31/35: `bash automation/android/s11/run.sh`; Android API 30 and provider-unavailable cases produce UNVERIFIED plus the hidden-System/brand fallback.

The coordinator supplies the unsigned iOS XCUITest project, Android UiAutomator test jar, whole-session recorder, and event/frame correlation. Native event rows are joined to host updates by sequence. A renderer marker without a capture-index match remains UNVERIFIED. If a live cell, OS setting surface, or recorder is unavailable, the analyzer records UNVERIFIED and the selected fallback explicitly.

The portal fault cases use a separately labelled test D-Bus service or a safely disabled portal; those cases prove adapter fallback only and never count as real GNOME live delivery. Do not replace any real OS event with a renderer-dispatched event.

The S11 authoring lane did not execute these helpers. CI must invoke them only on disposable
hosted sessions. Linux fault coverage requires a coordinator-provided isolated D-Bus service or
equivalent adapter fixture for absent service/key, malformed/out-of-range values and subscription
failure; the GNOME change helper does not fabricate those faults. The portal interface version is
also recorded from the host reader's `reader-ready` event, alongside the independent `Read` output.
