//! S11's synthetic host door for the OS accent preference.
//!
//! The module exposes only the accent snapshot and native change events. It does not touch the
//! account setting; persistence and the `system`-to-brand resolver belong to the product host.

use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::{Emitter, Manager, State, Wry};

#[path = "s11_native/mod.rs"]
mod s11_native;

use self::s11_native::{NativeUpdate, Snapshot};

const EVENT_NAME: &str = "s11:accent-update";

#[derive(Clone)]
struct DoorState(Arc<Mutex<DoorSnapshot>>);

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DoorSnapshot {
    available: bool,
    reason: Option<String>,
    rgb: Option<[f64; 3]>,
    sequence: u64,
    source: &'static str,
    portal_interface_version: Option<u32>,
}

impl Default for DoorState {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(DoorSnapshot {
            available: false,
            reason: Some("reader-starting".to_owned()),
            rgb: None,
            sequence: 0,
            source: "system",
            portal_interface_version: None,
        })))
    }
}

impl DoorState {
    fn replace(&self, snapshot: Snapshot, sequence: u64) {
        if let Ok(mut current) = self.0.lock() {
            *current = DoorSnapshot::from_native(snapshot, sequence);
        }
    }

    fn current(&self) -> Result<DoorSnapshot, String> {
        self.0
            .lock()
            .map(|value| value.clone())
            .map_err(|_| "accent-state-unavailable".to_owned())
    }

    fn accept(&self, update: &NativeUpdate) -> Result<bool, String> {
        let mut current = self
            .0
            .lock()
            .map_err(|_| "accent-state-unavailable".to_owned())?;
        if update.sequence <= current.sequence {
            return Ok(false);
        }
        *current = DoorSnapshot::from_native(update.snapshot.clone(), update.sequence);
        Ok(true)
    }
}

impl DoorSnapshot {
    fn from_native(snapshot: Snapshot, sequence: u64) -> Self {
        Self {
            available: snapshot.available,
            reason: snapshot.reason,
            rgb: snapshot.rgb,
            sequence,
            source: "system",
            portal_interface_version: snapshot.portal_interface_version,
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeEvent {
    sequence: u64,
    native_event_ns: u64,
    host_update_ns: u64,
    native_event: bool,
    cause: &'static str,
    available: bool,
    reason: Option<String>,
    rgb: Option<[f64; 3]>,
    source: &'static str,
    portal_interface_version: Option<u32>,
}

#[tauri::command]
async fn current_accent(state: State<'_, DoorState>) -> Result<DoorSnapshot, String> {
    state.current()
}

/// Registers the S11 host plugin required by `spikes::register`.
pub fn plugin() -> tauri::plugin::TauriPlugin<Wry> {
    tauri::plugin::Builder::new("s11-accent")
        .invoke_handler(tauri::generate_handler![current_accent])
        .setup(|app, _api| {
            let state = DoorState::default();
            app.manage(state.clone());

            let app_handle = app.clone();
            tauri::async_runtime::spawn(async move {
                let (sender, mut updates) = tokio::sync::mpsc::channel::<NativeUpdate>(8);
                let initial = s11_native::subscribe(sender, app_handle.clone()).await;
                state.replace(initial, 0);

                let initial_event = match state.current() {
                    Ok(snapshot) => NativeEvent {
                        sequence: 0,
                        native_event_ns: 0,
                        host_update_ns: s11_native::monotonic_ns(),
                        native_event: false,
                        cause: "reader-ready",
                        available: snapshot.available,
                        reason: snapshot.reason,
                        rgb: snapshot.rgb,
                        source: snapshot.source,
                        portal_interface_version: snapshot.portal_interface_version,
                    },
                    Err(_) => return,
                };
                let ready_handle = app_handle.clone();
                let _ = app_handle.run_on_main_thread(move || {
                    let _ = ready_handle.emit(EVENT_NAME, initial_event);
                });

                while let Some(update) = updates.recv().await {
                    let accepted = match state.accept(&update) {
                        Ok(accepted) => accepted,
                        Err(_) => break,
                    };
                    if !accepted {
                        continue;
                    }

                    let event = NativeEvent {
                        sequence: update.sequence,
                        native_event_ns: update.native_event_ns,
                        host_update_ns: s11_native::monotonic_ns(),
                        native_event: update.native_event,
                        cause: update.cause,
                        available: update.snapshot.available,
                        reason: update.snapshot.reason,
                        rgb: update.snapshot.rgb,
                        source: "system",
                        portal_interface_version: update.snapshot.portal_interface_version,
                    };
                    let event_handle = app_handle.clone();
                    let _ = app_handle.run_on_main_thread(move || {
                        let _ = event_handle.emit(EVENT_NAME, event);
                    });
                }
            });
            Ok(())
        })
        .build()
}
