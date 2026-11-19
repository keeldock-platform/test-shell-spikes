use std::cell::RefCell;
use std::ptr::NonNull;
use std::sync::atomic::{AtomicU64, Ordering};

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::ProtocolObject;
use objc2_app_kit::{NSColor, NSColorSpace, NSSystemColorsDidChangeNotification};
use objc2_core_foundation::CGFloat;
use objc2_foundation::{
    NSNotification, NSNotificationCenter, NSOperationQueue, NSObjectProtocol,
};
use tauri::{AppHandle, Wry};

use super::{monotonic_ns, publish_update, EventSender, NativeUpdate, Snapshot};

thread_local! {
    static OBSERVER: RefCell<Option<Retained<ProtocolObject<dyn NSObjectProtocol>>>> = const {
        RefCell::new(None)
    };
}

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
    let center = NSNotificationCenter::defaultCenter();
    let callback_sender = sender.clone();
    let callback = RcBlock::new(move |_notification: NonNull<NSNotification>| {
        static SEQUENCE: AtomicU64 = AtomicU64::new(0);
        let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed).saturating_add(1);
        let snapshot = read_srgb();
        let update = NativeUpdate {
            sequence,
            native_event_ns: monotonic_ns(),
            native_event: true,
            cause: "system-colours-notification",
            snapshot,
        };
        publish_update(&callback_sender, update);
    });

    let main_queue = NSOperationQueue::mainQueue();
    // SAFETY: the observer name is AppKit's documented system-colour notification; object is
    // absent because the notification has no object, and the callback is scheduled on the main
    // operation queue. The captured sender is thread-safe and the centre owns the copied block.
    let observer = unsafe {
        center.addObserverForName_object_queue_usingBlock(
            Some(NSSystemColorsDidChangeNotification),
            None,
            Some(&main_queue),
            &callback,
        )
    };
    OBSERVER.with(|slot| {
        if let Ok(mut slot) = slot.try_borrow_mut() {
            *slot = Some(observer);
        }
    });

    // Reading after registration closes the first-read/listener race.
    read_srgb()
}

fn read_srgb() -> Snapshot {
    let accent = NSColor::controlAccentColor();
    let srgb_space = NSColorSpace::sRGBColorSpace();
    let Some(colour) = accent.colorUsingColorSpace(&srgb_space) else {
        return Snapshot::unavailable("srgb-conversion-failed");
    };

    let mut red: CGFloat = 0.0;
    let mut green: CGFloat = 0.0;
    let mut blue: CGFloat = 0.0;
    let mut alpha: CGFloat = 0.0;
    // SAFETY: all four pointers refer to live CGFloat values and NSColor writes one component to
    // each pointer. The colour was converted to sRGB immediately above.
    unsafe {
        colour.getRed_green_blue_alpha(&mut red, &mut green, &mut blue, &mut alpha);
    }
    let _ = alpha;
    let channels = [red as f64, green as f64, blue as f64];
    if channels
        .iter()
        .any(|channel| !channel.is_finite() || !(0.0..=1.0).contains(channel))
    {
        return Snapshot::unavailable("invalid-srgb-component");
    }
    Snapshot::available(channels, None)
}
