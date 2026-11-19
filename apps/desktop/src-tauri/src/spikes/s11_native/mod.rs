//! Isolated platform adapters for the S11 accent host door.

use tauri::{AppHandle, Wry};

pub(crate) type EventSender = tokio::sync::mpsc::Sender<NativeUpdate>;

#[derive(Clone, Debug)]
pub(crate) struct Snapshot {
    pub available: bool,
    pub reason: Option<String>,
    pub rgb: Option<[f64; 3]>,
    pub portal_interface_version: Option<u32>,
}

impl Snapshot {
    pub(crate) fn available(rgb: [f64; 3], portal_interface_version: Option<u32>) -> Self {
        Self {
            available: true,
            reason: None,
            rgb: Some(rgb),
            portal_interface_version,
        }
    }

    pub(crate) fn unavailable(reason: &'static str) -> Self {
        Self {
            available: false,
            reason: Some(reason.to_owned()),
            rgb: None,
            portal_interface_version: None,
        }
    }

    pub(crate) fn unavailable_with_portal_version(
        reason: &'static str,
        portal_interface_version: u32,
    ) -> Self {
        Self {
            available: false,
            reason: Some(reason.to_owned()),
            rgb: None,
            portal_interface_version: Some(portal_interface_version),
        }
    }

    pub(crate) fn from_portal(
        value: (f64, f64, f64),
        portal_interface_version: u32,
    ) -> Result<Self, &'static str> {
        let rgb = [value.0, value.1, value.2];
        if rgb.iter().any(|channel| !channel.is_finite()) {
            return Err("malformed-portal-colour");
        }
        if rgb.iter().any(|channel| !(0.0..=1.0).contains(channel)) {
            return Err("portal-colour-out-of-range");
        }
        Ok(Self::available(rgb, Some(portal_interface_version)))
    }
}

#[derive(Clone, Debug)]
pub(crate) struct NativeUpdate {
    pub sequence: u64,
    pub native_event_ns: u64,
    pub native_event: bool,
    pub cause: &'static str,
    pub snapshot: Snapshot,
}

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "windows")]
mod windows;

pub(crate) async fn subscribe(sender: EventSender, app_handle: AppHandle<Wry>) -> Snapshot {
    #[cfg(target_os = "macos")]
    {
        return macos::subscribe(sender, app_handle).await;
    }
    #[cfg(target_os = "windows")]
    {
        return windows::subscribe(sender, app_handle).await;
    }
    #[cfg(target_os = "linux")]
    {
        let _ = app_handle;
        return linux::subscribe(sender).await;
    }
    #[allow(unreachable_code)]
    Snapshot::unavailable("unsupported-platform")
}

pub(crate) fn monotonic_ns() -> u64 {
    crate::monotonic_nanoseconds().unwrap_or(0)
}

pub(crate) fn send_update(
    sender: &EventSender,
    sequence: u64,
    snapshot: Snapshot,
    native_event: bool,
    cause: &'static str,
) {
    let update = NativeUpdate {
        sequence,
        native_event_ns: if native_event { monotonic_ns() } else { 0 },
        native_event,
        cause,
        snapshot,
    };
    // Accent changes are human-paced; try_send avoids blocking or panicking when the OS invokes
    // this callback from an AppKit/WinRT dispatcher. A saturated queue is visible as a missing
    // sequence in the runner evidence and cannot be counted as a pass.
    let _ = sender.try_send(update);
}

pub(crate) fn publish_update(sender: &EventSender, update: NativeUpdate) {
    // Native callbacks are low-frequency. Do not block a platform dispatcher; if the bounded
    // queue fills, the missing sequence makes the CI evidence fail closed.
    let _ = sender.try_send(update);
}
