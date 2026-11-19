# Pinned versions

Direct dependencies use exact versions. `Cargo.lock` and `package-lock.json` are generated from
their exact manifests. Hosted runner images, operating-system webviews, and simulator runtimes
remain measured per cell because the workflow does not provision immutable images for them.
`ci/environment-lock.json` requires an exact runtime match before it accepts `PASS`; without a
reviewed per-cell runtime pin, the runner and collector downgrade `PASS` to `UNVERIFIED`.

## Toolchains and runtime

| Component | Pin | Reason and source |
|---|---:|---|
| Rust | `1.99.1` | Current approved toolchain floor; [official release](https://github.com/rust-lang/rust/releases/tag/1.99.1). |
| Tauri | `2.12.6` | Meets the current supply-chain floor; [official release](https://github.com/tauri-apps/tauri/releases/tag/tauri-v2.12.6). |
| tauri-build | `2.7.5` | Build crate paired in the Tauri 2.12.6 release; [docs.rs](https://docs.rs/crate/tauri-build/2.7.5). |
| tauri-cli | `2.12.5` | Exact version for mobile project generation and simulator builds; [docs.rs](https://docs.rs/crate/tauri-cli/2.12.5). |
| Node.js | `24.11.1` | Node 24 LTS; [official archive](https://nodejs.org/en/download/archive/v24.11.1). |
| npm | `11.6.2` | Version shipped with Node 24.11.1; recorded in the [official Node archive](https://nodejs.org/en/download/archive/v24.11.1). |
| Python | `3.14.10` | Current stable runtime used by the standard-library CI tools; [official release](https://www.python.org/downloads/release/python-31410/). |
| `@tauri-apps/api` | `2.12.4` | Exact JavaScript bridge compatible with the Tauri 2 host; [npm package metadata](https://www.npmjs.com/package/@tauri-apps/api/v/2.12.4). |

## Rust dependencies

| Crate | Exact version | Reason and source |
|---|---:|---|
| `tauri-plugin-window-state` | `2.5.0` | Required by the S08 settings-window probe; [docs.rs](https://docs.rs/crate/tauri-plugin-window-state/2.5.0). |
| `tauri-plugin-dialog` | `2.8.4` | S08 synthetic native dialog probe; [crates.io](https://crates.io/crates/tauri-plugin-dialog/2.8.4). |
| `serde` | `1.0.229` | Serializes synthetic native measurements and event values; [crates.io](https://crates.io/crates/serde/1.0.229). |
| `thiserror` | `2.0.21` | Typed errors for S08's synthetic host state; [crates.io](https://crates.io/crates/thiserror/2.0.21). |
| `tokio` | `1.54.1` | Bounded async event channel for S11 native updates; [crates.io](https://crates.io/crates/tokio/1.54.1). |
| `ashpd` | `0.14.0` | S11 XDG Settings portal adapter; [crates.io](https://crates.io/crates/ashpd/0.14.0). |
| `futures-util` | `0.3.34` | Stream handling for portal change notifications; [crates.io](https://crates.io/crates/futures-util/0.3.34). |
| `objc2` | `0.6.5` | Narrow AppKit system-colour observer adapter; [crates.io](https://crates.io/crates/objc2/0.6.5). |
| `objc2-app-kit` | `0.3.2` | AppKit window and system-colour interfaces; [crates.io](https://crates.io/crates/objc2-app-kit/0.3.2). |
| `objc2-foundation` | `0.3.2` | Foundation notification and geometry interfaces; [crates.io](https://crates.io/crates/objc2-foundation/0.3.2). |
| `objc2-core-foundation` | `0.3.2` | Core Foundation scalar type used by the colour reader; [crates.io](https://crates.io/crates/objc2-core-foundation/0.3.2). |
| `block2` | `0.6.2` | Objective-C callback block for system-colour notifications; [crates.io](https://crates.io/crates/block2/0.6.2). |
| `windows` | `0.62.2` | Windows UISettings accent event API; [crates.io](https://crates.io/crates/windows/0.62.2). |
| AndroidX instrumentation runner | `androidx.test:runner:1.7.0` | Installed as an Android test APK and launched with `AndroidJUnitRunner`; [AndroidX Test release notes](https://developer.android.com/jetpack/androidx/releases/test). |
| AndroidX JUnit extension | `androidx.test.ext:junit:1.3.0` | JUnit 4 runner integration for the instrumented native drivers; [AndroidX Test release notes](https://developer.android.com/jetpack/androidx/releases/test). |
| AndroidX UiAutomator | `androidx.test.uiautomator:uiautomator:2.4.0` | Native cross-app UI automation library for the instrumented APK; [AndroidX UiAutomator release notes](https://developer.android.com/jetpack/androidx/releases/test-uiautomator). |
| JUnit | `junit:junit:4.13.2` | Test annotations and runner API used by AndroidX instrumentation. |
| Android test compile SDK / Build Tools | API `35` / `35.0.0` | Uses the same pinned Android SDK platform and Build Tools as the mobile wrapper. |

## GitHub Actions

All actions are fixed to reviewed full commit SHAs. Sources point to the official release/tag commit.

| Action | Version | Commit SHA | Source |
|---|---:|---|---|
| `actions/checkout` | `v6.0.1` | `8e8c483db84b4bee98b60c0593521ed34d9990e8` | [official release](https://github.com/actions/checkout/releases/tag/v6.0.1) |
| `actions/upload-artifact` | `v7.0.0` | `bbbca2ddaa5d8feaa63e36b76fdaad77386f024f` | [official release](https://github.com/actions/upload-artifact/releases/tag/v7.0.0) |
| `actions/download-artifact` | `v8.0.0` | `70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3` | [official release](https://github.com/actions/download-artifact/releases/tag/v8.0.0) |
| `actions/setup-node` | `v7.1.0` | `949feb2413d6458794dcd2491c4babbbce0c15c1` | [official release](https://github.com/actions/setup-node/releases/tag/v7.1.0) |
| `actions/setup-python` | `v7.1.0` | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | [official release](https://github.com/actions/setup-python/releases/tag/v7.1.0) |

## Recorder APIs

| Component | Pin | Reason and source |
|---|---:|---|
| GNOME Shell recorder | D-Bus `org.gnome.Shell.Screencast`, 60 fps request | GNOME Shell's own whole-screen screencast API; [GNOME interface introduction](https://mail.gnome.org/archives/commits-list/2013-May/msg02787.html). The active session's Mutter/GNOME build is captured as observed evidence; without a reviewed per-cell runtime pin it cannot support `PASS`. |

## Host-managed runtime policy

The environment lock records runner image identity, webview builds, Apple simulator runtimes,
Android SDK packages, AndroidX instrumentation dependencies, GNOME/Mutter versions, and recorder versions as observed values. These values
are not dependency pins. The current `exactRuntimeVersionsByCell` map is empty, so no hosted cell
can produce an accepted `PASS` until reviewed expected values are added. Missing or mismatched
values stay `UNVERIFIED`, and unavailable Linux distributions use the explicit fallbacks in the
environment lock. GitHub Actions themselves are fixed to full commit SHAs.


## Coordinator revision, 2026-11-19

The empty per-cell runtime pin map explicitly selects `first-ci-run-discovery`.
Coordinator decision A2 authorizes workflow run numbers 1–3, attempt 1 only, on
`refs/heads/shell-spikes/integration-1118` through the source-controlled
`ci/discovery-authorization.json` referenced by `runtimePolicy.discoveryAuthorization`.
Earlier runs stopped before discovery; this remains one discovery wave. After that
wave the coordinator must populate `exactRuntimeVersionsByCell`, switch
`runtimePolicy.mode` to `locked`, remove `runtimePolicy.discoveryAuthorization`,
and delete the authorization file. No script renews this authorization. Discovery
continues to downgrade runtime-dependent PASS to UNVERIFIED until that freeze.

`ci/runtime-discovery.py` runs before builds in each provisioned cell. It uses
Microsoft's [Evergreen bootstrapper](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution),
Ubuntu's configured stable apt repository, Apple's `softwareupdate` for embedded
macOS WebKit and [iOS platform download](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components),
and Android [sdkmanager channel 0](https://developer.android.com/tools/sdkmanager)
for the declared API image. Android uses its bundled active WebView, with exact
version and pulled APK checksums recorded per cell. Coordinator decision C
(2026-11-19) removes separate WebView downloads and installation. Every Android
cell reports `latestStableStatus=UNVERIFIED` (bundled, not latest); discovery
failures do not stop Android builds or cases. The API/OS profiles remain those in the spike matrix.
The latest image revision is not proof that its bundled Android WebView matches
the independently released newest stable WebView; likewise pending Apple updates
may need a reboot. Those limits must be reviewed from the resolved runtime evidence,
and no latest-version or runtime-dependent PASS is inferred from installer exit status.

Each case writes `recorder/runtime-discovery.json`, including the exact observed
webview version, SDK/runtime identities, run/source identity, install logs, actual
installed payload SHA-256 values, and candidate dotted-key pins. Android hashes
pulled provider APKs; Linux hashes installed WebKit shared libraries; Windows hashes
WebView2 EXE/DLL payloads; Apple hashes WebKit or simulator dyld payloads. Missing
payloads or versions stay UNVERIFIED. The coordinator copies reviewed candidate pins
(including `runtimeDiscovery.runtimePayloadSha256`) into the lock after the run;
no script silently edits the lock or invents pins. OS-managed payloads may be large.

Android screenrecord and GNOME Wayland presentation joins without a calibrated
host-time origin remain UNVERIFIED, an accepted measured spike gap. Collection
lists the calibration state per Android and Wayland cell in `presentationCalibration`.
The S11 FRAME finalizer also rejects links unless the capture index explicitly
reports `clockCalibrated: true`.
