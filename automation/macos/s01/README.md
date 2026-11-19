# S01 macOS runner contract

This folder is runner code only. The coordinator supplies the generated XCTest
UI-test target, app bundle id, shared Tauri build, ScreenCaptureKit/AVFoundation
recorder, and artifact collector. No local build or test is part of authoring.

## Required run order

1. On the `macos-15` runner, record OS build, Tauri/Rust/WebKit versions,
   display bounds, backing scale, accessibility readiness, app bundle id and
   recorder configuration in `environment.json`.
   Run a separate complete capture/UI pass for every backing scale the runner
   can provide; record the observed scale cells and do not invent unavailable
   display modes.
2. Start a **full desktop** 60 fps recording before launching the app. Capture
   the native title bar and native AppKit controls; a webview-only capture is
   insufficient. Use a fresh disposable session. Fail the no-prompt preflight
   if accessibility or capture prompts appear; never dismiss or bypass one.
3. Invoke `bash automation/macos/s01/run.sh` (or the PowerShell forwarding entry
   `pwsh -File automation/macos/s01/run.ps1`) with the built app in
   `SHELL_APP_PATH`, generated UI-test project and scheme in
   `S01_XCODE_PROJECT` and `S01_XCODE_SCHEME`, and a passed
   `S01_PERMISSION_PROMPT_PREFLIGHT`. The adapter runs `TrafficLightsUITests.swift`
   through XCTest; XCTest launches the app, waits for its visible settled
   marker, and drives accessible controls in the synthetic screen. The test
   writes `ui-events.jsonl`.
4. The bootstrap-provided `emitEvent` bridge dispatches structured app events;
   the coordinator recorder exports normalized rows to
   `recorder/s01-events.jsonl` (or the path supplied in
   `S01_NATIVE_EVENTS_SOURCE`). The adapter appends those rows to `events.jsonl`.
   Each normalized row stores the `shell-spike:event` detail with
   `sequenceId` from `fields.sequenceId`, `kind` from `name`, other
   `fields` at the event top level, the native snapshot from `fields.native`,
   UTC time, renderer monotonic time, and recorder `monotonicNanoseconds`.
   That nanosecond clock must use the same monotonic timebase as the capture
   index. Shared `frame()` events retain `sequence`, `phase`, fields and
   presentation time.
5. The recorder writes timestamped PNG frames under `screens/` or
   `video/frames/`, the complete recording under `video/`, and
   `video/capture-index.jsonl`. Every index row has:

   ```json
   {
     "frameNumber": 120,
     "timestampNanoseconds": 2000000000,
     "relativePath": "video/frames/frame-000120.png",
     "displayFrameAppkit": [0, 0, 1440, 900],
     "displayPixelSize": [2880, 1800],
     "windowContentRectAppkit": [100, 80, 1240, 760],
     "backingScaleFactor": 2
   }
   ```

   AppKit and display rectangles use logical points with a bottom-left origin;
   PNG coordinates use a top-left origin. The analyzer maps between them with
   display pixel dimensions and checks the mapping against the recorded
   backing scale. Do not write
   guessed bounds or interpolate missing frames.
6. On the macOS runner, run
   `swift automation/macos/s01/analyze_capture.swift "$S01_ARTIFACT_DIR" cases/s01.json`.
   It reads `events.jsonl`, `ui-events.jsonl` and the capture index, decodes
   the visible 24-bit sequence plus 2-bit phase marker, inspects all indexed
   frames, then writes `assertions.json`. The renderer records native state
   polls during full-screen transitions. A transition frame without a native
   poll within 50ms is `UNVERIFIED`. Keep the raw recording, frame series,
   event files and hashes with the artifact even when analysis fails.

## Verdict handling

- The event snapshot checks all three native AppKit button centres against the
  row-1 centre and records x positions, diameter and gaps. A successful UI
  marker or a settled screenshot alone cannot pass the transition assertion.
- The frame analyzer checks the visible native-light pixels after each marker
  change, detects stale/overlapping old-position pixels, checks for zero
  traffic-light-classified pixels in the calibrated 78 px titlebar region
  whenever native full-screen state is active (`S1-13`), and verifies
  timestamp cadence.
- If native pixels, marker cells, capture timestamps, display mapping,
  backing scale, session focus or native button frames cannot be resolved, the
  affected assertion is `UNVERIFIED`; select the named fallback. A transition
  animation that cannot be resolved remains unverified.
- Report every backing scale actually available. The runner must not claim a
  scale that was not observed. Keep native and screenshot coordinates in
  logical points and pixels respectively in the assertion evidence.

