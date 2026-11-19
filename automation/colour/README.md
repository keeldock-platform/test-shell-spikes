# S10 native colour automation

This folder defines the native interaction and evidence contract for cases/s10.json. The public app is a synthetic webview probe, not a Safari or Chromium proxy. The runner must load the same pages/colour/ page in the desktop and test-shell-mobile wrappers.

## Required native drivers

- macOS desktop: XCTest or Accessibility automation against the WKWebView in the hosted macOS app.
- iOS simulator: XCUITest against the newly authored test-shell-mobile wrapper, once in the iPhone presentation and once in the iPad presentation.
- Windows: UI Automation against the WebView2 app and the native picker surface.
- Linux: AT-SPI and real pointer/keyboard input against WebKitGTK under each required X11 and Wayland session.
- Android: UiAutomator/ADB against the System WebView app on API 31 and API 35.

A DOM driver may read page outputs and the event log as supporting evidence. It must not open the picker, set the color input value, choose a color, dismiss the native picker, or stand in for the native accessibility tree. Open the Appearance dialog by activating its visible button. Open the picker by activating the visible, labelled input type=color through the OS input path.

## Scenario order

For every case, capture the whole desktop/compositor/simulator/emulator output before interaction, then:

1. Open the Appearance dialog with a real mouse click, keyboard activation, or touch tap.
2. Activate the labelled Custom colour picker with a real click/tap and save a native accessibility-tree snapshot and full-screen capture while its native surface is open. On desktop, exercise keyboard navigation and acceptance in the native picker where the controls expose it. On iOS and Android, operate the picker by touch and enter HEX with the on-screen keyboard.
3. Choose a non-default colour through controls exposed by that native picker and accept. Record the exact returned page value and the input/change event order. Return must match ^#[0-9a-fA-F]{6}$; the app boundary normalizes it to lowercase.
4. Apply the Appearance draft and record the committed value. Reopen the dialog, choose and accept a second non-default colour through native controls, then cancel the Appearance dialog. The committed Appearance value must remain the first accepted value.
5. Reopen and enter #E0A526 in the HEX field using real keyboard/touch entry. Commit it with Enter or the visible Use HEX value button, Apply, and verify the stored sample remains exactly #e0a526. The page must show the below-3:1 warning without changing the selected value.
6. Reopen and enter abc in HEX. Commit it and verify that the draft becomes #aabbcc, then cancel and verify that the committed sample stays #e0a526.
7. Reopen and enter the invalid value #12XZ. Verify the accessible error and unchanged draft/committed state, then cancel.
8. Reopen the Appearance dialog, open the native picker once more, exercise every dismissal route exposed by that platform (Escape and native close/cancel on desktop; native cancel/back on mobile; outside tap only if supported), and verify focus returns to the webview and the sample value is unchanged.

The runner must read each native picker's actual accessibility tree to choose and accept colours. If a platform offers a native hex/RGB editor, it may use that editor; otherwise use visible native picker controls and compare the returned value with the value displayed by the picker when available. Never use an injected script or direct property assignment to simulate a native choice.

## Native entry points

Invoke from the repository root after the coordinator recorder has created the case evidence folder. Every entry point requires `SHELL_CASE_ID`, `SHELL_CELL`, `SHELL_EVIDENCE_DIR`, and the app location or mobile app id described by the shared scaffold contract. The runner writes `assertions.json` as `{ "results": [...] }` even when the host, UI tree, or capture is unavailable.

- macOS desktop: `bash automation/macos/s10/run.sh`
- Windows desktop: `powershell -File automation/windows/s10/run.ps1`
- Linux X11 or Wayland: `bash automation/linux/s10/run.sh`
- iPhone/iPad simulator: `bash automation/ios/s10/run.sh`; the coordinator supplies the unsigned XCUITest project, scheme, destination, and case launch environment.
- Android API 31/35: `bash automation/android/s10/run.sh`; the coordinator supplies the UiAutomator test jar and mobile app id.

The platform adapters capture an accessibility tree, use native clicks and keyboard/touch entry, and extract the visible event log. The result analyzer keeps the per-cell planning outcome separate from PASS/FAIL/UNVERIFIED assertions. An unavailable tree, unsupported native editor, missing event stream, or incomplete whole-screen capture cannot produce a native-picker PASS; the row remains UNVERIFIED with the conservative hex-field-only route.

## Result handling

For each platform/session row, record exactly one planning verdict: native picker usable, hex field only, or UNVERIFIED. Use native picker usable only when the native surface is visible, operable by the declared pointer/keyboard/touch route, returns two valid six-digit values, and returns focus to the webview. If the picker opens but cannot satisfy these conditions, record the limitation and select hex field only. If the runner, session, native tree or complete capture is unavailable, record UNVERIFIED and select hex field only conservatively; do not claim the engine's picker is broken.

Keep the three verdict layers separate in assertions.json: assertion verdict PASS/FAIL/UNVERIFIED, per-cell planning verdict, and fallback route. A successful hex-only result is still a valid planning result. Record webview and native runtime versions from the job, never infer them from the OS label.

## Evidence

Use the artifact layout in SCAFFOLD-CONTRACT.md and COMMON.md:

- environment.json: full source SHA; case/job; hosted runner, OS/session, SDK/runtime and exact webview versions; display resolution, scale, refresh; automation and recorder versions.
- assertions.json: each assertion's expected and actual value, PASS/FAIL/UNVERIFIED, and relative evidence references.
- events.jsonl: monotonic sequence for native input, native acceptance/dismissal, page input/change, focus return, Apply, Cancel and committed value. Include session and coordinate conversion where the runner provides it.
- screens/ and video/: whole desktop/compositor/simulator/emulator captures, including native picker chrome.
- recorder/: accessibility-tree snapshots, input route used and recorder metadata.
- index.json and hashes.sha256: complete case-to-evidence map and integrity hashes.

A screenshot of the webview or a DOM assertion alone cannot establish that the native picker appeared or worked.

