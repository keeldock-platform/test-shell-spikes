use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};

use tauri::{AppHandle, Wry};
use windows::Foundation::TypedEventHandler;
use windows::UI::ViewManagement::{UIColorType, UISettings};
use windows::core::IInspectable;

use super::{EventSender, NativeUpdate, Snapshot, monotonic_ns, publish_update};

static REGISTRATION: OnceLock<(UISettings, i64)> = OnceLock::new();
static SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub(super) async fn subscribe(sender: EventSender, app_handle: AppHandle<Wry>) -> Snapshot {
    let (reply, response) = tokio::sync::oneshot::channel();
    if app_handle
        .run_on_main_thread(move || {
            let snapshot = subscribe_on_main(sender);
            let _ = reply.send(snapshot);
        })
        .is_err()
    {
        return Snapshot::unavailable("main-thread-dispatch-failed");
    }
    match response.await {
        Ok(snapshot) => snapshot,
        Err(_) => Snapshot::unavailable("main-thread-reader-unavailable"),
    }
}

fn subscribe_on_main(sender: EventSender) -> Snapshot {
    let settings = match UISettings::new() {
        Ok(settings) => settings,
        Err(_) => return Snapshot::unavailable("ui-settings-unavailable"),
    };

    let callback_settings = settings.clone();
    let callback_sender = sender.clone();
    let handler = TypedEventHandler::<UISettings, IInspectable>::new(move |_, _| {
        let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed).saturating_add(1);
        let snapshot = read_accent(&callback_settings);
        let update = NativeUpdate {
            sequence,
            native_event_ns: monotonic_ns(),
            native_event: true,
            cause: "ui-settings-color-values-changed",
            snapshot,
        };
        publish_update(&callback_sender, update);
        Ok(())
    });

    let token = match settings.ColorValuesChanged(&handler) {
        Ok(token) => token,
        Err(_) => return Snapshot::unavailable("change-subscription-failed"),
    };
    if REGISTRATION.set((settings.clone(), token)).is_err() {
        return Snapshot::unavailable("change-subscription-already-active");
    }

    // Windows delivers ColorValuesChanged callbacks on its WinRT event dispatcher. The shared
    // host forwards each accepted update through AppHandle::run_on_main_thread before rendering.
    read_accent(&settings)
}

fn read_accent(settings: &UISettings) -> Snapshot {
    let color = match settings.GetColorValue(UIColorType::Accent) {
        Ok(color) => color,
        Err(_) => return Snapshot::unavailable("accent-read-failed"),
    };
    Snapshot::available(
        [
            f64::from(color.R) / 255.0,
            f64::from(color.G) / 255.0,
            f64::from(color.B) / 255.0,
        ],
        None,
    )
}
