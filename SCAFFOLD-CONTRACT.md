# Shell spikes scaffold contract

This contract is the shared interface for S01, S02, S03, S08, S10 and S11 in the public,
synthetic test shell. It contains no product implementation. The six spikes are independently
selectable Cargo features and web modules; the single CI wave builds and exercises only the
features for each runner.

## Rust host and lane registration

The host entry point is `apps/desktop/src-tauri/src/lib.rs`:

```rust
pub fn run() -> tauri::Result<()>;
```

`run` creates the Tauri 2 builder, registers the shared mock commands and passes it through
`spikes::register(builder)`. `main.rs` calls `shell_spike_desktop_lib::run()` and contains no product
logic. `spikes/mod.rs` is coordinator-owned and declares these feature-gated modules:

| Cargo feature | Lane module file | Export |
| --- | --- | --- |
| `spike-s01` | `spikes/s01_traffic_lights.rs` | `pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry>` |
| `spike-s02` | `spikes/s02_system_menu.rs` | same |
| `spike-s03` | `spikes/s03_gnome_menu.rs` | same |
| `spike-s08` | `spikes/s08_settings.rs` | same |
| `spike-s10` | `spikes/s10_colour_input.rs` | same |
| `spike-s11` | `spikes/s11_accent.rs` | same |

Each `mod` declaration is guarded by its matching `#[cfg(feature = "spike-sNN")]`. Enabling a
feature while its module file is absent must fail compilation with Rust's missing-module error;
features disabled for another runner must not require their files. Each lane exports
`pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry>`; its plugin owns only that lane's
commands and setup and cannot reach into another lane's module. S08 initializes its mock settings
state from its plugin setup hook. It also asks the S08 module for exactly one shared
window-state-plugin instance, with visible-window persistence disabled, before registering the
S08 settings plugin. The S10 module may be an empty plugin because its subject is webview input; it
still uses the same registration contract. The coordinator registry adds only the plugin selected
by the runner's `SHELL_SPIKE_ID`; the runner also passes the same value as the renderer `?spike=`
query.

`spikes::register` has this signature:

```rust
pub fn register(builder: tauri::Builder<tauri::Wry>) -> tauri::Builder<tauri::Wry>;
```

It adds the plugin for each enabled feature and returns the builder. Shared commands are limited
to synthetic mock settings and explicit denied sentinels. Sentinel commands return a typed error
and grant no filesystem, network, tool, MCP, marketplace, vault or credential access. Public
capabilities remain minimal and window-scoped.
Inline plugin commands are declared through the Tauri build attributes and are granted by the
matching window capability. The Settings window explicitly denies direct dialog IPC; the S08 host
registers the dialog plugin once for its native picker path. The mobile capability grants only the
shared selection/event commands and the accent snapshot needed by its fixture.

## Shared renderer interface

`apps/desktop/web/index.html` loads `bootstrap.js`. The bootstrap accepts only `s01`, `s02`,
`s03`, `s08`, `s10` or `s11` from the `spike` query parameter, dynamically imports
`web/spikes/<id>.js`, creates a synthetic root, and calls:

```js
export async function registerSpike({ root, caseId, invoke, frame, record, loadAssetModule }) {}
```

- `root` is the lane's DOM mount point.
- `caseId` is the selected case identifier or `null` for a smoke page.
- `invoke(command, args)` is the Tauri invoke bridge. Every command remains subject to Rust-side
  validation; browser-only presentation cases may not call it.
- `loadAssetModule(path)` dynamically imports another same-origin module relative to the renderer
  root. It accepts only relative paths without a scheme, authority, or `..` segment.
- The loader also accepts the S01 compatibility export `mountS01(root, { invoke, emitEvent,
  frame, caseId, loadAssetModule })`; new modules use `registerSpike`.
- `frame(sequence, phase, fields = {})` updates the visible frame marker and dispatches a
  `shell-spike:frame` `CustomEvent` with `{sequence, phase, fields, monotonicTime}`. The recorder
  adapter listens for the event and writes its timestamp to `events.jsonl`.
- `record(name, fields = {})` dispatches `shell-spike:event` for structured synthetic test events.
  Do not place secrets, private paths, or user data in event fields.

The shared marker is an ordinary visible `<output id="spike-frame-marker">`, with
`data-sequence` and `data-phase` attributes. It uses synthetic sequence numbers and plain text so
the whole desktop/compositor capture can be correlated with event and presentation frames. Lanes
may add their own visible geometry markers inside `root`, but may not replace the shared marker or
use DOM automation as proof that native chrome appeared.

The shared host command `selected_case()` returns the runner's `SHELL_CASE_ID` for desktop pages;
mobile webviews pass a `case` query parameter. The mobile smoke page exposes a case-ID text field
and spike links so native automation can select the target without a devtools connection.

The mobile wrapper reports `selected_spike() = "mobile"`; the bootstrap only loads a mobile spike
after its matching `?spike=<id>&case=<case-id>` selection. For Android S11, the coordinator wrapper
registers `s11-accent` with Tauri's Android plugin loader and wraps the lane-owned
`AndroidAccentReader.kt`. It exposes `current_accent`, emits `accent-update`, and closes the reader
with the activity. The shared bootstrap subscribes to that plugin event before loading S11 and
forwards its payload as the shared `s11:accent-update` event. The reader requests no permission.

For desktop, `SHELL_SPIKE_ID` is one of `s01`, `s02`, `s03`, `s08`, `s10`, `s11`; the host registers
only that enabled lane plugin. `SHELL_CASE_ID` names the case passed to the page. The mobile wrapper
builds the requested mobile features, reports `selected_spike() = "mobile"`, and uses the smoke
page's `spike` and `case` query selection; the ready frame marker reports the resolved selection.
Runners set the desktop environment values or select the mobile query and fail preflight if the
ready marker does not match the expected spike and case.

Native automation is invoked from `automation/<platform>/<spike>/run.sh` or `run.ps1`; S10 and S11
may also use their lane folders `automation/colour/` and `automation/accent/`. The runner provides
`SHELL_APP_PATH`, `SHELL_MOBILE_BUNDLE_ID` where applicable, `SHELL_SPIKE_ID`, `SHELL_CASE_ID`,
`SHELL_CELL`, and `SHELL_EVIDENCE_DIR`. Drivers write only beneath that evidence directory and
report assertions using the result shape below.

## Case files

`cases/schema.json` is the normative JSON Schema (Draft 2020-12) for each lane-owned
`cases/sNN.json`. A case file has `schemaVersion: 1`, a lane identifier, a descriptive title, and a
non-empty `cases` array. Each case has a stable `id`; lane-specific platform/session dimensions,
setup, ordered `actions` or `steps`, and assertion references or objects remain in their authored
shape. Assertion objects have a stable `id`, `expected`, optional plain-language `requirement`, and
an `evidence` list naming required sources (for example `native-tree`, `screen`, `video`,
`frame-marker`, `os-event` or `geometry-json`). Case IDs and assertion IDs are unique within their
file. Never encode a missing runner as a passing case; the collector records it as `UNVERIFIED`.

Each uploaded `assertions.json` uses an object envelope with a stable result array:

```json
{
  "sourceSha": "<full-checkout-sha>",
  "job": "<cell-name>",
  "results": []
}
```

Each machine result in `results` has this shape:

```json
{
  "id": "S01-...",
  "expected": "...",
  "actual": "...",
  "verdict": "PASS",
  "evidence": ["video/transition.mp4#t=1.2", "events.jsonl#seq=17"]
}
```

`verdict` is exactly `PASS`, `FAIL` or `UNVERIFIED`. Evidence references are relative to the
artifact root and must resolve in the uploaded artifact. The runner records a separate assertion
for each platform/session cell and includes failure or unavailability reasons in `actual`. The
collector adds an explicit platform fallback selection to every `FAIL` or `UNVERIFIED` matrix row.

## Evidence layout and recorder output

Every job/cell uploads one artifact named
`shell-spikes-<full-sha>-<job-or-cell>-all-cases`. It includes the shared manifests below and
case-specific material in `spikes/<spike>/<case-id>/`; the explicit `all-cases` suffix identifies
serial cases grouped into one runner artifact. The collector indexes each case separately.

```text
environment.json
assertions.json
events.jsonl
index.json
hashes.sha256
screens/
video/
recorder/
```

`environment.json` records the frozen source SHA, job and case IDs, runner label/image, OS and
session, display resolution/scale/refresh, Tauri and webview versions, native SDK/runtime versions,
toolchain versions and recorder details. `events.jsonl` records monotonic timestamps, sequence IDs,
native events, renderer frame markers and the measured coordinate conversion fields required by
the lane. `index.json` maps cases/assertions to evidence paths. `hashes.sha256` covers all evidence
files except itself. Upload happens with an `always()` condition, including after timeout or test
failure. Retain public artifacts for 14 days; the coordinator downloads and hashes the one-wave
evidence into an archive before expiry.

The Linux host provisions real GNOME/Mutter X11 and nested Wayland sessions on Ubuntu 24.04; the
build, native input driver, AT-SPI observer and recorder run inside the selected session. Linux
release/session profiles without a pinned guest image are emitted as `UNVERIFIED` with their
per-case fallback selection and are not substituted with a different distribution.

## Ownership and scope

Coordinator owns this contract, shared manifests and lockfiles, the Tauri host and configuration,
`apps/desktop/web/{index.html,bootstrap.js,frame-marker.js}`, mobile wrapper and project-generation
scaffolding, `ci/`, `cases/schema.json`, and the sole workflow. Each lane owns its `sNN_*.rs`,
`web/spikes/sNN.js`, automation directory, and `cases/sNN.json` named by its brief; S10 also owns
`pages/colour/`, and S11 owns the Android accent plugin. Lanes register only through the feature,
module and renderer interfaces above. This repository contains newly written synthetic test code
only; no product kernel, private IPC, credentials, private assets or canvas content.
