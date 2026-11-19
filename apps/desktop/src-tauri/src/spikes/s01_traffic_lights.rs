//! SHELL-SPIKE-01 native traffic-light positioning probe.
//!
//! The scaffold registers this lane plugin and sets the main window to
//! `titleBarStyle: "Overlay"`, `decorations: true`, and creation-time
//! `trafficLightPosition`. The initial config and runtime path deliberately
//! leave native window decorations enabled.

use serde::Serialize;
use std::sync::mpsc;
use std::time::Duration;
use tauri::WebviewWindow;

/// Registers only the S01 traffic-light commands with the selected lane.
pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri::plugin::Builder::new("s01-traffic-lights")
        .invoke_handler(tauri::generate_handler![
            s01_reposition_traffic_lights,
            s01_inspect_traffic_lights,
            s01_set_fullscreen
        ])
        .build()
}

const COMFORTABLE_ROW1: f64 = 34.0;
const COMPACT_ROW1: f64 = 30.0;
const MAIN_THREAD_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeFrame {
    pub name: &'static str,
    /// Native frame in the AppKit button parent's logical-point coordinates.
    pub appkit_frame: [f64; 4],
    /// Native frame converted to the content view's logical-point coordinates.
    pub content_frame: [f64; 4],
    /// Vertical centre measured down from the content view's top edge.
    pub center_y_from_content_top: f64,
    pub diameter_x: f64,
    pub diameter_y: f64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSnapshot {
    pub sequence_id: u64,
    pub native_event_ns: u64,
    pub host_update_ns: u64,
    pub density: &'static str,
    pub tab_layout: &'static str,
    pub row1_height: f64,
    pub row2_height: f64,
    pub bar_height: f64,
    pub expected_center_y_from_content_top: f64,
    pub backing_scale_factor: f64,
    pub is_fullscreen: bool,
    /// AppKit screen coordinates use a bottom-left origin. Keep this field so
    /// the CI analyzer can map native points to full-desktop capture pixels.
    pub content_rect_on_screen_appkit: [f64; 4],
    pub window_frame_on_screen_appkit: [f64; 4],
    pub lights: Vec<NativeFrame>,
}

#[tauri::command]
pub async fn s01_reposition_traffic_lights(
    window: WebviewWindow,
    sequence_id: u64,
    compact: bool,
    capsules: bool,
) -> Result<NativeSnapshot, String> {
    if sequence_id == 0 {
        return Err("S01 sequence id must be nonzero".into());
    }

    let row1_height = if compact {
        COMPACT_ROW1
    } else {
        COMFORTABLE_ROW1
    };
    let row2_height = if capsules {
        0.0
    } else if compact {
        28.0
    } else {
        30.0
    };

    #[cfg(target_os = "macos")]
    {
        run_on_appkit_main_thread(
            &window,
            sequence_id,
            compact,
            capsules,
            row1_height,
            row2_height,
            true,
        )
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = (window, capsules, row1_height, row2_height);
        Err("S01 AppKit repositioning is macOS-only".into())
    }
}

#[tauri::command]
pub async fn s01_inspect_traffic_lights(
    window: WebviewWindow,
    sequence_id: u64,
    compact: bool,
    capsules: bool,
) -> Result<NativeSnapshot, String> {
    if sequence_id == 0 {
        return Err("S01 sequence id must be nonzero".into());
    }

    let row1_height = if compact {
        COMPACT_ROW1
    } else {
        COMFORTABLE_ROW1
    };
    let row2_height = if capsules {
        0.0
    } else if compact {
        28.0
    } else {
        30.0
    };

    #[cfg(target_os = "macos")]
    {
        run_on_appkit_main_thread(
            &window,
            sequence_id,
            compact,
            capsules,
            row1_height,
            row2_height,
            false,
        )
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = (window, capsules, row1_height, row2_height);
        Err("S01 AppKit inspection is macOS-only".into())
    }
}

#[tauri::command]
pub async fn s01_set_fullscreen(window: WebviewWindow, fullscreen: bool) -> Result<(), String> {
    window
        .set_fullscreen(fullscreen)
        .map_err(|error| format!("failed to request native full-screen state: {error}"))
}

#[cfg(target_os = "macos")]
fn run_on_appkit_main_thread(
    window: &WebviewWindow,
    sequence_id: u64,
    compact: bool,
    capsules: bool,
    row1_height: f64,
    row2_height: f64,
    reposition: bool,
) -> Result<NativeSnapshot, String> {
    let receipt_ns = crate::monotonic_nanoseconds().ok_or("native receipt clock unavailable")?;
    let (sender, receiver) = mpsc::channel();
    window
        .with_webview(move |platform_webview| {
            let result = unsafe {
                let native_window = platform_webview.ns_window();
                if native_window.is_null() {
                    Err("Tauri returned a null NSWindow".to_owned())
                } else {
                    let native_window = &*native_window.cast::<objc2_app_kit::NSWindow>();
                    let content_view = native_window
                        .contentView()
                        .ok_or_else(|| "NSWindow has no content view".to_owned());
                    content_view.and_then(|content_view| {
                        if reposition {
                            place_lights(native_window, &content_view, row1_height)?;
                        }
                        snapshot(
                            native_window,
                            &content_view,
                            sequence_id,
                            compact,
                            capsules,
                            row1_height,
                            row2_height,
                        )
                    })
                }
            };
            let result = result.map(|mut measured| {
                measured.native_event_ns = receipt_ns;
                measured.host_update_ns = crate::monotonic_nanoseconds().unwrap_or(0);
                measured
            });
            let _ = sender.send(result);
        })
        .map_err(|error| format!("failed to enter AppKit main thread: {error}"))?;

    receiver
        .recv_timeout(MAIN_THREAD_TIMEOUT)
        .map_err(|_| "timed out waiting for AppKit main-thread measurement".to_owned())?
}

#[cfg(target_os = "macos")]
unsafe fn place_lights(
    native_window: &objc2_app_kit::NSWindow,
    content_view: &objc2_app_kit::NSView,
    row1_height: f64,
) -> Result<(), String> {
    use objc2_app_kit::NSWindowButton;
    use objc2_foundation::NSPoint;

    let content_bounds = content_view.bounds();
    let from_content_bottom = if content_view.isFlipped() {
        content_bounds.origin.y + row1_height / 2.0
    } else {
        content_bounds.origin.y + content_bounds.size.height - row1_height / 2.0
    };
    let content_center = NSPoint::new(content_bounds.origin.x, from_content_bottom);

    for button_kind in [
        NSWindowButton::CloseButton,
        NSWindowButton::MiniaturizeButton,
        NSWindowButton::ZoomButton,
    ] {
        let button = native_window
            .standardWindowButton(button_kind)
            .ok_or_else(|| "AppKit did not provide all three standard window buttons".to_owned())?;
        let parent = button
            .superview()
            .ok_or_else(|| "a standard window button has no parent view".to_owned())?;
        let center_in_parent = content_view.convertPoint_toView(content_center, Some(&parent));
        let mut frame = button.frame();
        // Preserve AppKit's native horizontal spacing and button size. Only
        // the vertical origin changes; x/gap/diameter are reported as checks.
        frame.origin.y = center_in_parent.y - frame.size.height / 2.0;
        button.setFrame(frame);
    }

    Ok(())
}

#[cfg(target_os = "macos")]
unsafe fn snapshot(
    native_window: &objc2_app_kit::NSWindow,
    content_view: &objc2_app_kit::NSView,
    sequence_id: u64,
    compact: bool,
    capsules: bool,
    row1_height: f64,
    row2_height: f64,
) -> Result<NativeSnapshot, String> {
    use objc2_app_kit::NSWindowButton;
    use objc2_foundation::NSPoint;

    let content_bounds = content_view.bounds();
    let expected_center = row1_height / 2.0;
    let mut lights = Vec::with_capacity(3);

    for (name, button_kind) in [
        ("close", NSWindowButton::CloseButton),
        ("minimize", NSWindowButton::MiniaturizeButton),
        ("zoom", NSWindowButton::ZoomButton),
    ] {
        let button = native_window
            .standardWindowButton(button_kind)
            .ok_or_else(|| format!("AppKit did not provide the {name} button"))?;
        let parent = button
            .superview()
            .ok_or_else(|| format!("the {name} button has no parent view"))?;
        let button_frame = button.frame();
        let content_frame = parent.convertRect_toView(button_frame, Some(content_view));
        let center_in_content = parent.convertPoint_toView(
            NSPoint::new(
                button_frame.origin.x + button_frame.size.width / 2.0,
                button_frame.origin.y + button_frame.size.height / 2.0,
            ),
            Some(content_view),
        );
        let center_y_from_top = if content_view.isFlipped() {
            center_in_content.y - content_bounds.origin.y
        } else {
            content_bounds.origin.y + content_bounds.size.height - center_in_content.y
        };

        lights.push(NativeFrame {
            name,
            appkit_frame: [
                button_frame.origin.x,
                button_frame.origin.y,
                button_frame.size.width,
                button_frame.size.height,
            ],
            content_frame: [
                content_frame.origin.x,
                content_frame.origin.y,
                content_frame.size.width,
                content_frame.size.height,
            ],
            center_y_from_content_top: center_y_from_top,
            diameter_x: button_frame.size.width,
            diameter_y: button_frame.size.height,
        });
    }

    let content_frame_in_window = content_view.convertRect_toView(content_bounds, None);
    let content_rect_on_screen = native_window.convertRectToScreen(content_frame_in_window);
    let window_frame = native_window.frame();
    let compact_name = if compact { "compact" } else { "comfortable" };
    let layout_name = if capsules { "capsules" } else { "rows" };

    Ok(NativeSnapshot {
        sequence_id,
        native_event_ns: 0,
        host_update_ns: 0,
        density: compact_name,
        tab_layout: layout_name,
        row1_height,
        row2_height,
        bar_height: row1_height + row2_height,
        expected_center_y_from_content_top: expected_center,
        backing_scale_factor: native_window.backingScaleFactor(),
        is_fullscreen: native_window
            .styleMask()
            .contains(objc2_app_kit::NSWindowStyleMask::FullScreen),
        content_rect_on_screen_appkit: [
            content_rect_on_screen.origin.x,
            content_rect_on_screen.origin.y,
            content_rect_on_screen.size.width,
            content_rect_on_screen.size.height,
        ],
        window_frame_on_screen_appkit: [
            window_frame.origin.x,
            window_frame.origin.y,
            window_frame.size.width,
            window_frame.size.height,
        ],
        lights,
    })
}
