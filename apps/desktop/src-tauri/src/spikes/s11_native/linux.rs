use std::sync::atomic::{AtomicU64, Ordering};

use ashpd::desktop::settings::Settings;
use futures_util::StreamExt;

use super::{EventSender, Snapshot, send_update};

const NAMESPACE: &str = "org.freedesktop.appearance";
const KEY: &str = "accent-color";

pub(super) async fn subscribe(sender: EventSender) -> Snapshot {
    let settings = match Settings::new().await {
        Ok(settings) => settings,
        Err(_) => return Snapshot::unavailable("portal-service-unavailable"),
    };
    let interface_version = settings.version();

    // Subscribe first so a change between Read and listener setup cannot be lost.
    let mut changes = match settings
        .receive_setting_changed_with_args::<(f64, f64, f64)>(NAMESPACE, KEY)
        .await
    {
        Ok(changes) => changes,
        Err(_) => {
            return Snapshot::unavailable_with_portal_version(
                "portal-subscription-failed",
                interface_version,
            );
        }
    };

    let raw = match settings.read::<(f64, f64, f64)>(NAMESPACE, KEY).await {
        Ok(value) => value,
        Err(_) => {
            return Snapshot::unavailable_with_portal_version(
                "portal-read-failed",
                interface_version,
            );
        }
    };
    let initial = match Snapshot::from_portal(raw, interface_version) {
        Ok(snapshot) => snapshot,
        Err(reason) => Snapshot::unavailable_with_portal_version(reason, interface_version),
    };

    tauri::async_runtime::spawn(async move {
        static SEQUENCE: AtomicU64 = AtomicU64::new(0);
        while let Some(change) = changes.next().await {
            let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed).saturating_add(1);
            let snapshot = match change {
                Ok(value) => {
                    Snapshot::from_portal(value, interface_version).unwrap_or_else(|reason| {
                        Snapshot::unavailable_with_portal_version(reason, interface_version)
                    })
                }
                Err(_) => Snapshot::unavailable_with_portal_version(
                    "malformed-portal-colour",
                    interface_version,
                ),
            };
            send_update(&sender, sequence, snapshot, true, "portal-setting-changed");
        }

        let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed).saturating_add(1);
        send_update(
            &sender,
            sequence,
            Snapshot::unavailable("portal-subscription-ended"),
            false,
            "portal-subscription-ended",
        );
    });

    initial
}
