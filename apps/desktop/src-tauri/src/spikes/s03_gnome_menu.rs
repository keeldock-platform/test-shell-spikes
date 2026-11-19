//! S03 adapter for the GNOME/Mutter window menu.
//!
//! The GTK callback receives the original GDK button event. On Wayland that
//! event carries the compositor-owned input serial through GDK; on X11 GDK
//! routes the request through the GTK window-menu path. This module never
//! synthesizes an event or opens a separate Wayland connection.

use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};

use tauri::{
    AppHandle, Manager, State, Wry,
    plugin::{Builder as PluginBuilder, TauriPlugin},
    webview::WebviewWindow,
};

const PLUGIN_NAME: &str = "s03-gnome-menu";

#[derive(Clone, Default)]
struct S03State(Arc<S03StateInner>);

#[derive(Default)]
struct S03StateInner {
    regions: Mutex<Option<HeaderRegions>>,
    kit_menu: AtomicBool,
    fallback_all_workspaces: AtomicBool,
}

#[derive(Clone, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct HeaderRegions {
    header: Rect,
    blockers: Vec<Rect>,
    css_to_gdk_scale: f64,
}

#[derive(Clone, Copy, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct Rect {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl Rect {
    fn is_valid(self) -> bool {
        self.x.is_finite()
            && self.y.is_finite()
            && self.width.is_finite()
            && self.height.is_finite()
            && self.width > 0.0
            && self.height > 0.0
            && self.x.abs() <= 16_384.0
            && self.y.abs() <= 16_384.0
            && self.width <= 16_384.0
            && self.height <= 16_384.0
            && (self.x + self.width).is_finite()
            && (self.y + self.height).is_finite()
    }

    fn contains(self, x: f64, y: f64) -> bool {
        x >= self.x && y >= self.y && x < self.x + self.width && y < self.y + self.height
    }

    fn contains_rect(self, other: Self) -> bool {
        other.x >= self.x
            && other.y >= self.y
            && other.x + other.width <= self.x + self.width
            && other.y + other.height <= self.y + self.height
    }
}

impl HeaderRegions {
    fn validate(&self) -> Result<(), String> {
        if !self.header.is_valid() {
            return Err("header bounds must be finite and non-empty".into());
        }
        if self.blockers.len() > 16 || self.blockers.iter().any(|rect| !rect.is_valid()) {
            return Err(
                "header blockers must contain at most 16 finite, non-empty rectangles".into(),
            );
        }
        if self
            .blockers
            .iter()
            .any(|rect| !self.header.contains_rect(*rect))
        {
            return Err("header blockers must be inside the header bounds".into());
        }
        // GDK event coordinates and WebKit CSS pixels are expected to be
        // logical coordinates in the pinned 100% scale test session.
        if !self.css_to_gdk_scale.is_finite() || (self.css_to_gdk_scale - 1.0).abs() > 0.001 {
            return Err("S03 requires a 1:1 CSS-to-GDK coordinate scale".into());
        }
        Ok(())
    }

    fn is_empty_header_point(&self, x: f64, y: f64) -> bool {
        self.header.contains(x, y) && !self.blockers.iter().any(|rect| rect.contains(x, y))
    }
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct FallbackWindowState {
    maximized: bool,
    always_on_top: bool,
    all_workspaces: bool,
    resize_supported: bool,
}

/// Registers S03's native event adapter and its synthetic kit-menu fallback.
pub fn plugin() -> TauriPlugin<Wry> {
    PluginBuilder::new(PLUGIN_NAME)
        .invoke_handler(tauri::generate_handler![
            set_header_regions,
            set_menu_mode,
            set_test_maximized,
            fallback_window_state,
            perform_fallback_action
        ])
        .setup(|app, _api| {
            let state = S03State::default();
            app.manage(state.clone());

            #[cfg(target_os = "linux")]
            install_native_event_hook(app.handle(), state)?;

            Ok(())
        })
        .build()
}

#[tauri::command]
fn set_header_regions(state: State<'_, S03State>, regions: HeaderRegions) -> Result<(), String> {
    regions.validate()?;
    let mut current = state
        .0
        .regions
        .lock()
        .map_err(|_| "S03 header-region lock is unavailable".to_string())?;
    *current = Some(regions);
    Ok(())
}

#[tauri::command]
fn set_menu_mode(state: State<'_, S03State>, mode: String) -> Result<(), String> {
    match mode.as_str() {
        "native" => state.0.kit_menu.store(false, Ordering::Relaxed),
        "kit" => state.0.kit_menu.store(true, Ordering::Relaxed),
        _ => return Err("S03 menu mode must be 'native' or 'kit'".into()),
    }
    Ok(())
}

#[tauri::command]
fn set_test_maximized(app: AppHandle<Wry>, maximized: bool) -> Result<(), String> {
    let window = main_window(&app)?;
    if maximized {
        window.maximize()
    } else {
        window.unmaximize()
    }
    .map_err(|error| error.to_string())
}

#[tauri::command]
fn fallback_window_state(
    app: AppHandle<Wry>,
    state: State<'_, S03State>,
) -> Result<FallbackWindowState, String> {
    let window = main_window(&app)?;
    Ok(FallbackWindowState {
        maximized: window.is_maximized().map_err(|error| error.to_string())?,
        always_on_top: window
            .is_always_on_top()
            .map_err(|error| error.to_string())?,
        all_workspaces: state.0.fallback_all_workspaces.load(Ordering::Relaxed),
        // Tauri has no Linux resize-drag operation that can preserve this
        // menu click's GDK event and its Wayland serial.
        resize_supported: false,
    })
}

#[tauri::command]
fn perform_fallback_action(
    app: AppHandle<Wry>,
    state: State<'_, S03State>,
    action: String,
) -> Result<(), String> {
    let window = main_window(&app)?;
    match action.as_str() {
        "minimize" => window.minimize(),
        "maximizeOrRestore" => {
            if window.is_maximized().map_err(|error| error.to_string())? {
                window.unmaximize()
            } else {
                window.maximize()
            }
        }
        "move" => window.start_dragging(),
        "resize" => {
            return Err("Resize is unavailable in the S03 kit-menu fallback.".into());
        }
        "alwaysOnTop" => {
            let next = !window
                .is_always_on_top()
                .map_err(|error| error.to_string())?;
            window.set_always_on_top(next)
        }
        "allWorkspaces" => {
            let next = !state.0.fallback_all_workspaces.load(Ordering::Relaxed);
            window
                .set_visible_on_all_workspaces(next)
                .map_err(|error| error.to_string())?;
            state
                .0
                .fallback_all_workspaces
                .store(next, Ordering::Relaxed);
            Ok(())
        }
        "close" => window.close(),
        _ => return Err("Unknown S03 fallback action".into()),
    }
    .map_err(|error| error.to_string())
}

fn main_window(app: &AppHandle<Wry>) -> Result<WebviewWindow<Wry>, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "S03 main webview window is unavailable".into())
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::ffi::{CStr, c_char, c_int, c_ulong, c_void};

    #[repr(C)]
    struct GtkWidget {
        _opaque: [u8; 0],
    }

    #[repr(C)]
    struct GdkWindow {
        _opaque: [u8; 0],
    }

    #[repr(C)]
    struct GdkEvent {
        _opaque: [u8; 0],
    }

    #[repr(C)]
    struct GObject {
        _opaque: [u8; 0],
    }

    #[repr(C)]
    struct GClosure {
        _opaque: [u8; 0],
    }

    type GCallback = unsafe extern "C" fn();
    type GClosureNotify = unsafe extern "C" fn(*mut c_void, *mut GClosure);

    const GDK_BUTTON_PRESS: c_int = 4;
    const GDK_BUTTON_PRESS_MASK: c_int = 1 << 8;
    const SECONDARY_BUTTON: u32 = 3;

    #[link(name = "gtk-3")]
    unsafe extern "C" {
        fn gtk_widget_add_events(widget: *mut GtkWidget, events: c_int);
        fn gtk_widget_get_toplevel(widget: *mut GtkWidget) -> *mut GtkWidget;
        fn gtk_widget_get_window(widget: *mut GtkWidget) -> *mut GdkWindow;
    }

    #[link(name = "gdk-3")]
    unsafe extern "C" {
        fn gdk_event_get_event_type(event: *const GdkEvent) -> c_int;
        fn gdk_event_get_button(event: *const GdkEvent, button: *mut u32) -> c_int;
        fn gdk_event_get_coords(event: *const GdkEvent, x: *mut f64, y: *mut f64) -> c_int;
        fn gdk_window_show_window_menu(window: *mut GdkWindow, event: *mut GdkEvent) -> c_int;
    }

    #[link(name = "gobject-2.0")]
    unsafe extern "C" {
        fn g_signal_connect_data(
            instance: *mut GObject,
            detailed_signal: *const c_char,
            c_handler: Option<GCallback>,
            data: *mut c_void,
            destroy_data: Option<GClosureNotify>,
            connect_flags: c_int,
        ) -> c_ulong;
    }

    struct HookContext {
        state: S03State,
        window: WebviewWindow<Wry>,
    }

    pub(super) fn install_native_event_hook(
        app: &AppHandle<Wry>,
        state: S03State,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let webview = app
            .get_webview("main")
            .ok_or("S03 requires the main webview")?;
        let window = main_window(app).map_err(std::io::Error::other)?;
        let connected = Arc::new(AtomicBool::new(false));
        let error = Arc::new(Mutex::new(None::<String>));
        let connected_in_callback = Arc::clone(&connected);
        let error_in_callback = Arc::clone(&error);

        webview.with_webview(move |platform_webview| {
            // Tauri guarantees this closure runs on the GTK main thread. The
            // returned WebKitWebView is a GtkWidget owned by the webview.
            // `inner()` returns webkit2gtk's owned WebView wrapper. Use the
            // gtk-rs ObjectType pointer accessor to borrow its GObject handle;
            // do not cast the Rust wrapper object itself.
            let webview = platform_webview.inner();
            let widget = gtk::glib::object::ObjectType::as_ptr(&webview).cast::<GtkWidget>();
            if widget.is_null() {
                *error_in_callback.lock().expect("S03 setup error lock") =
                    Some("Tauri returned a null WebKitGTK widget".into());
                return;
            }

            let context = Box::new(HookContext { state, window });
            let context_ptr = Box::into_raw(context).cast::<c_void>();
            let signal = unsafe { CStr::from_bytes_with_nul_unchecked(b"button-press-event\0") };
            let callback = unsafe {
                std::mem::transmute::<
                    unsafe extern "C" fn(*mut GtkWidget, *mut GdkEvent, *mut c_void) -> c_int,
                    GCallback,
                >(on_button_press)
            };

            unsafe {
                gtk_widget_add_events(widget, GDK_BUTTON_PRESS_MASK);
                let handler_id = g_signal_connect_data(
                    widget.cast::<GObject>(),
                    signal.as_ptr(),
                    Some(callback),
                    context_ptr,
                    Some(destroy_hook_context),
                    0,
                );
                if handler_id != 0 {
                    connected_in_callback.store(true, Ordering::Release);
                } else {
                    drop(Box::from_raw(context_ptr.cast::<HookContext>()));
                    *error_in_callback.lock().expect("S03 setup error lock") =
                        Some("GTK did not attach the S03 button-press handler".into());
                }
            }
        })?;

        if !connected.load(Ordering::Acquire) {
            let message = error
                .lock()
                .map_err(|_| std::io::Error::other("S03 setup error lock poisoned"))?
                .clone()
                .unwrap_or_else(|| "GTK did not attach the S03 button-press handler".into());
            return Err(std::io::Error::other(message).into());
        }
        Ok(())
    }

    unsafe extern "C" fn destroy_hook_context(data: *mut c_void, _closure: *mut GClosure) {
        if !data.is_null() {
            // GTK calls the closure notifier once when the webview is destroyed.
            unsafe { drop(Box::from_raw(data.cast::<HookContext>())) };
        }
    }

    unsafe extern "C" fn on_button_press(
        widget: *mut GtkWidget,
        event: *mut GdkEvent,
        data: *mut c_void,
    ) -> c_int {
        if widget.is_null() || event.is_null() || data.is_null() {
            return 0;
        }

        let event_type = unsafe { gdk_event_get_event_type(event) };
        let mut button = 0;
        let has_button = unsafe { gdk_event_get_button(event, &mut button) } != 0;
        if event_type != GDK_BUTTON_PRESS || !has_button || button != SECONDARY_BUTTON {
            return 0;
        }

        let mut x = 0.0;
        let mut y = 0.0;
        if unsafe { gdk_event_get_coords(event, &mut x, &mut y) } == 0
            || !x.is_finite()
            || !y.is_finite()
        {
            return 0;
        }

        let context = unsafe { &*(data.cast::<HookContext>()) };
        let regions = match context.state.0.regions.lock() {
            Ok(regions) => regions.clone(),
            Err(_) => return 0,
        };
        let Some(regions) = regions else {
            // Fail closed until the renderer has published its real geometry.
            return 0;
        };
        if !regions.is_empty_header_point(x, y) {
            return 0;
        }

        if context.state.0.kit_menu.load(Ordering::Relaxed) {
            open_kit_menu(&context.window, x, y, "forced-kit-fallback");
            return 1;
        }

        let top_level = unsafe { gtk_widget_get_toplevel(widget) };
        if top_level.is_null() {
            open_kit_menu(&context.window, x, y, "missing-gtk-toplevel");
            return 1;
        }
        let gdk_window = unsafe { gtk_widget_get_window(top_level) };
        if gdk_window.is_null() {
            open_kit_menu(&context.window, x, y, "missing-gdk-window");
            return 1;
        }

        // This is the original GDK button-press event, passed synchronously
        // from the GTK signal while its Wayland serial remains valid.
        let shown = unsafe { gdk_window_show_window_menu(gdk_window, event) } != 0;
        record_native_request(&context.window, x, y, shown);
        if !shown {
            open_kit_menu(&context.window, x, y, "gdk-request-declined");
        }
        1
    }

    fn open_kit_menu(window: &WebviewWindow<Wry>, x: f64, y: f64, reason: &str) {
        if !x.is_finite() || !y.is_finite() {
            return;
        }
        let script = format!(
            "window.s03?.openFallbackAt({:.3}, {:.3}, {:?})",
            x.max(0.0),
            y.max(0.0),
            reason
        );
        let _ = window.eval(script);
    }

    fn record_native_request(window: &WebviewWindow<Wry>, x: f64, y: f64, accepted: bool) {
        let script = format!(
            "window.s03?.recordNativeRequest({{x:{:.3},y:{:.3},apiAccepted:{}}})",
            x, y, accepted
        );
        let _ = window.eval(script);
    }
}

#[cfg(target_os = "linux")]
use linux::install_native_event_hook;
