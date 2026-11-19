# Spike fix round 6 — implementation and local proof

Date: 2026-11-19. Read the round-six review final-message.md in full. Implemented in `.`.

## Finding → change → proof

| Finding / coordinator decision | Change | Local proof |
| --- | --- | --- |
| P1 #3: API 30 HIDDEN omitted reason/token; PROMPT never evaluated | Android driver reads the visible S11 JSON values and requires API 30, `api-below-31`, hidden System, stored System, brand source, applied `#405066`, unavailable/raw-null state. The visible applied token now comes from computed CSS. Ten native permission-window samples are saved; readiness and no observed permission-controller window are required. `api30Facts` feeds a post-collection reducer that independently checks reason, token, no dynamic-resource read and prompt samples. | `test_finding3_api30_observations_and_missing_facts` passes: valid facts pass HIDDEN/PROMPT; wrong reason/token/source/stored enum, visible control, attempted resource read, observed prompt, insufficient samples and missing facts remain UNVERIFIED. No Android device execution was performed. |
| P1 #4: reduction ran before telemetry retrieval | Removed Android reduction from the live driver invocation. `ci/run_case.py` now invokes `--reduce-android` after `collect_mobile_renderer_events`, before capture finalization and envelope regeneration. | `test_finding4_fresh_mobile_retrieval_before_reduction` passes: begins without host events, supplies sandbox telemetry through the real mocked Android retrieval/append path, then obtains RECREATE/IDENTITY reductions. Source ordering verifies collection → reduction → refreshed envelope. |
| P1 #5: WALLPAPER accepted changed readback alone; RECREATE accepted any positive generation and no second wallpaper | Java leaves WALLPAPER pending host reduction and attempts a second distinct picker candidate after recreation, recording second readback. Python requires a recognized changed-fingerprint callback, unique sequence, exactly one matching later host/token update, matching resource/wallpaper/generation and an applied token. RECREATE additionally requires generation advancement from the initial snapshot, a non-native reread of the current fingerprint, and a second changed-fingerprint callback/host delivery after recreation. Initial snapshot now records its sequence; reader status explicitly records `nativeEvent=false`. | `test_finding5_complete_and_incomplete_callback_sequences` passes. Complete two-change fixture passes; positive generation alone, missing first host, missing second change/host, duplicate callback/host, reversed delivery and non-advancing generation stay UNVERIFIED. Readback alone cannot pass WALLPAPER. FRAME stays UNVERIFIED without presentation proof. Picker attempts that do not produce a distinct change cannot pass. |
| P1 #6: undefined Windows clamp helper | Replaced `Get-EventFields` with the defined `Get-Fields` in the actual token-update clamp branch. | `test_finding6_static_clamp_helper_resolution` passes: every Get-helper called by the clamp branch resolves to a defined function and the branch uses `(Get-Fields $_).clamped`. An additional test extracts and executes the real PowerShell AST against false/true fixtures when PowerShell works. That execution test is skipped here: installed `pwsh` exits with `Stack overflow.` even for `Write-Output ok`. This is a static dry-run proof, not a claimed Windows execution pass. |
| A / prior #7: authorized discovery and recording path | Empty pins now explicitly mean `runtimePolicy.mode=first-ci-run-discovery`, with dated authorization, scope and coordinator freeze ownership. Static/runtime guards restrict discovery to workflow run number 1, attempt 1. Each provisioned platform requests updates through its official stable channel before build. Per-case `recorder/runtime-discovery.json` records exact observed runtime versions, SDK/image identities, source/run identity, install logs, SHA-256 of actual installed runtime payloads and candidate dotted-key pins, including a payload digest. The coordinator must populate the map and switch to locked mode after the run. No script edits the lock automatically. Missing versions/payloads and unprovisioned cells remain explicit UNVERIFIED. | Discovery authorization, first-vs-second-run rejection, all five platform command plans, successful/failed mocked installers, actual fixture payload hashing and missing-payload handling pass. `runtime-discovery-dry-run.json` contains actual CLI `--dry-run` output for all five platforms. Runtime matching still rejects empty pins. No runtime was installed locally. |
| B / prior #4: accepted capture-clock gap | Collection emits `presentationCalibration` rows per Android/Wayland cell, with case-level calibration evidence. S11 FRAME finalization discards presentation links unless the capture index explicitly says `clockCalibrated=true`. Existing index/normalization gates continue to reject uncalibrated joins. | `test_uncalibrated_cells_explicit_and_never_frame_pass` passes: all six affected cells appear as UNVERIFIED in a no-capture fixture; a correlated-looking link with a false calibration flag cannot pass FRAME. Existing relative-PTS calibration regression also passes. |

## Explicit accepted presentation gaps per cell

No native captures were taken in this fix round. The following cells must retain UNVERIFIED presentation joins whenever no calibrated host-time origin exists; none has a local presentation PASS:

| Cell | Capture / availability | Presentation status |
| --- | --- | --- |
| android-api-30 | Android screenrecord; API 30 negative-policy cases may have no presentation assertion | UNVERIFIED for any uncalibrated join |
| android-api-31 | Android screenrecord | UNVERIFIED for uncalibrated joins |
| android-api-35 | Android screenrecord | UNVERIFIED for uncalibrated joins |
| linux-ubuntu-24.04-wayland | GNOME Wayland screencast | UNVERIFIED for uncalibrated joins |
| linux-ubuntu-26.04-wayland | Profile remains not provisioned | UNVERIFIED; no substitute capture |
| linux-fedora-current-wayland | Profile remains not provisioned | UNVERIFIED; no substitute capture |

These are the coordinator's accepted measured gaps for the spike, not blockers and not PASS results. `presentation-calibration-dry-run.json` demonstrates the per-cell report shape.

## Validation

- `python3 -m unittest discover -s ci/tests -p 'test_round*.py' -v`: 24 tests, 23 passed, 1 skipped (broken local PowerShell startup). Full output: `local-proof.log`.
- Python AST parsing: 29 files passed.
- Frozen-input checker, scaffold/schema/routing validation, case schema validation, public-source check and renderer transport regression: passed.
- Runtime CLI dry runs: macOS, iOS, Android, Windows and Linux passed; a second-run fixture was rejected.

## Limits that the evidence preserves

Official stable-channel update requests do not themselves prove the active embedded webview is the independently newest release. In particular, Android installs the latest stable revision of the declared Google APIs image; its bundled WebView may lag independent stable WebView releases. Apple updates may require reboot, and iOS platform availability is bounded by the selected Xcode. `latestStableStatus` explicitly remains UNVERIFIED. The first CI run must supply the actual resolved versions and payload hashes for coordinator review; this local work does not claim that global latest-stable installation has been proven. Unavailable Linux profiles remain unavailable. The recording path is implemented; actual first-run resolution and subsequent coordinator freeze remain future actions by instruction.

No native builds, app launches, runtime installations, git writes, pushes or CI runs were performed. Git inspection was read-only. No existing user changes were staged or committed.
