//! S02 Windows system-menu spike.
//!
//! The title-bar subclass preserves the existing `HTMAXBUTTON` result for Snap
//! Layouts and routes `HTCAPTION` right-button releases through
//! `on_non_client_right_button_up`. The plugin registers a host WebView2
//! `AcceleratorKeyPressed` handler that calls `on_webview2_accelerator` without
//! inspecting DOM focus.
//!
//! This is synthetic spike code. The scaffold registers this narrow Win32 FFI
//! module with its static policy before the CI build.

use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};

use tauri::{
    Emitter, Manager, RunEvent, WindowEvent, Wry,
    plugin::{Builder as PluginBuilder, TauriPlugin},
};

const PLUGIN_NAME: &str = "s02-system-menu";

use std::fmt;

const SC_SIZE: u32 = 0xF000;
const SC_MOVE: u32 = 0xF010;
const SC_MINIMIZE: u32 = 0xF020;
const SC_MAXIMIZE: u32 = 0xF030;
const SC_CLOSE: u32 = 0xF060;
const SC_RESTORE: u32 = 0xF120;

const VK_SPACE: u32 = 0x20;
const HTCAPTION: isize = 2;
const HTMAXBUTTON: isize = 9;

#[derive(Clone, Default)]
struct S02State {
    regions: Arc<Mutex<Option<HitTestRegions>>>,
    kit_mode: Arc<AtomicBool>,
}

#[derive(Clone, Copy, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct HitTestRegions {
    empty_chrome: HitTestRect,
    maximize_button: HitTestRect,
    scale: f64,
}

#[derive(Clone, Copy, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct HitTestRect {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl HitTestRect {
    fn is_valid(self) -> bool {
        [self.x, self.y, self.width, self.height]
            .into_iter()
            .all(f64::is_finite)
            && self.x >= 0.0
            && self.y >= 0.0
            && self.width > 0.0
            && self.height > 0.0
    }

    fn contains(self, x: f64, y: f64) -> bool {
        x >= self.x && y >= self.y && x < self.x + self.width && y < self.y + self.height
    }
}

/// Registers S02 commands, the close guard, and the Windows title-bar shim.
pub fn plugin() -> TauriPlugin<Wry> {
    PluginBuilder::new(PLUGIN_NAME)
        .invoke_handler(tauri::generate_handler![
            s02_open_system_menu_at_origin,
            s02_set_hit_test_regions,
            s02_set_menu_mode,
            s02_dispatch_system_command,
            s02_set_window_state,
            s02_close_after_guard,
            s02_get_window_menu_state
        ])
        .setup(|app, _api| {
            let state = S02State::default();
            app.manage(state.clone());

            #[cfg(windows)]
            {
                let window = app
                    .get_webview_window("main")
                    .ok_or_else(|| std::io::Error::other("S02 main window is unavailable"))?;
                window
                    .set_decorations(false)
                    .map_err(|error| std::io::Error::other(error.to_string()))?;
                window
                    .set_resizable(true)
                    .map_err(|error| std::io::Error::other(error.to_string()))?;
                window
                    .set_title("S02 System Menu Spike")
                    .map_err(|error| std::io::Error::other(error.to_string()))?;
                let hwnd = hwnd_for(&window).map_err(std::io::Error::other)?;
                native::install_window_subclass(hwnd, state).map_err(std::io::Error::other)?;
                install_accelerator_hook(app, &window).map_err(std::io::Error::other)?;
            }
            Ok(())
        })
        .on_event(|app, event| {
            if let RunEvent::WindowEvent { label, event, .. } = event {
                if label == "main" {
                    if let Some(window) = app.get_webview_window(label) {
                        if let WindowEvent::CloseRequested { api, .. } = event {
                            api.prevent_close();
                            let _ = window.emit("s02-close-guard", ());
                        }
                    }
                }
            }
        })
        .build()
}

/// Register WebView2's browser-level accelerator hook once for the main view.
/// It receives Alt+Space regardless of whether focus is in an input or on
/// empty chrome, marks the event handled before entering TrackPopupMenu, and
/// emits a renderer receipt for native UI Automation.
#[cfg(windows)]
fn install_accelerator_hook(
    app: &tauri::AppHandle<Wry>,
    window: &tauri::WebviewWindow<Wry>,
) -> Result<(), String> {
    use webview2_com::{
        AcceleratorKeyPressedEventHandler,
        Microsoft::Web::WebView2::Win32::{
            COREWEBVIEW2_KEY_EVENT_KIND_SYSTEM_KEY_DOWN, ICoreWebView2Controller,
        },
    };
    let hwnd = hwnd_for(window)?;
    let app_handle = app.clone();
    let (sender, receiver) = std::sync::mpsc::channel();
    window
        .with_webview(move |platform_webview| {
            let registration = unsafe {
                let controller: ICoreWebView2Controller = platform_webview.controller();
                let callback_app = app_handle.clone();
                let handler = AcceleratorKeyPressedEventHandler::create(Box::new(
                    move |_sender, event_args| {
                        let Some(event_args) = event_args else {
                            return Ok(());
                        };

                        let mut virtual_key = 0;
                        let mut event_kind = Default::default();
                        let mut key_lparam = 0_i32;
                        unsafe {
                            event_args.VirtualKey(&mut virtual_key)?;
                            event_args.KeyEventKind(&mut event_kind)?;
                            event_args.KeyEventLParam(&mut key_lparam)?;
                        }
                        let key_state = key_lparam as u32;

                        let mut mark_handled_error = None;
                        let _ = on_webview2_accelerator(
                            hwnd,
                            virtual_key,
                            event_kind == COREWEBVIEW2_KEY_EVENT_KIND_SYSTEM_KEY_DOWN,
                            key_state & (1 << 29) != 0,
                            key_state & (1 << 30) != 0,
                            || {
                                mark_handled_error = unsafe { event_args.SetHandled(true).err() };
                            },
                            || {
                                let _ = callback_app.emit_to(
                                    "main",
                                    "s02-webview2-accelerator",
                                    "Alt+Space",
                                );
                            },
                        );

                        if let Some(error) = mark_handled_error {
                            return Err(error);
                        }
                        Ok(())
                    },
                ));
                let mut token = 0_i64;
                controller.add_AcceleratorKeyPressed(&handler, &mut token)
            };
            let _ = sender.send(registration.map_err(|error| error.to_string()));
        })
        .map_err(|error| error.to_string())?;

    receiver
        .recv()
        .map_err(|_| "WebView2 accelerator registration did not complete".to_owned())?
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MenuAnchor {
    Pointer { screen_x: i32, screen_y: i32 },
    WindowTopLeft,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SystemCommand {
    Restore,
    Move,
    Size,
    Minimize,
    Maximize,
    Close,
}

impl SystemCommand {
    fn win32_id(self) -> u32 {
        match self {
            Self::Restore => SC_RESTORE,
            Self::Move => SC_MOVE,
            Self::Size => SC_SIZE,
            Self::Minimize => SC_MINIMIZE,
            Self::Maximize => SC_MAXIMIZE,
            Self::Close => SC_CLOSE,
        }
    }

    fn from_win32_id(id: u32) -> Option<Self> {
        match id & 0xFFF0 {
            SC_RESTORE => Some(Self::Restore),
            SC_MOVE => Some(Self::Move),
            SC_SIZE => Some(Self::Size),
            SC_MINIMIZE => Some(Self::Minimize),
            SC_MAXIMIZE => Some(Self::Maximize),
            SC_CLOSE => Some(Self::Close),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SystemMenuError {
    UnsupportedPlatform,
    InvalidWindow,
    MenuUnavailable,
    WindowBoundsUnavailable,
    MenuStateUnavailable,
    CommandDispatchFailed,
}

impl fmt::Display for SystemMenuError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::UnsupportedPlatform => "S02 system menus are available on Windows only",
            Self::InvalidWindow => "the S02 native window handle is invalid",
            Self::MenuUnavailable => "GetSystemMenu did not return a window menu",
            Self::WindowBoundsUnavailable => "the S02 window bounds could not be read",
            Self::MenuStateUnavailable => "the S02 window menu state could not be updated",
            Self::CommandDispatchFailed => "the S02 system command could not be dispatched",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for SystemMenuError {}

/// Opens the operating-system system menu and dispatches its selected command.
/// Pointer coordinates are physical screen coordinates; keyboard and app-icon
/// entry use the top-left of the native window.
pub fn show_system_menu(
    hwnd: isize,
    anchor: MenuAnchor,
) -> Result<Option<SystemCommand>, SystemMenuError> {
    #[cfg(windows)]
    {
        native::show_system_menu(hwnd, anchor)
    }
    #[cfg(not(windows))]
    {
        let _ = (hwnd, anchor);
        Err(SystemMenuError::UnsupportedPlatform)
    }
}

/// Dispatches one allow-listed system command, used by the kit-menu fallback.
pub fn dispatch_system_command(hwnd: isize, command: SystemCommand) -> Result<(), SystemMenuError> {
    #[cfg(windows)]
    {
        native::dispatch_system_command(hwnd, command)
    }
    #[cfg(not(windows))]
    {
        let _ = (hwnd, command);
        Err(SystemMenuError::UnsupportedPlatform)
    }
}

/// Handles a non-client right-button release only for empty title-bar space.
/// Other hit-test results, including `HTMAXBUTTON`, remain owned by the shim.
pub fn on_non_client_right_button_up(
    hwnd: isize,
    hit_test: isize,
    packed_screen_point: isize,
) -> Result<bool, SystemMenuError> {
    if hit_test == HTMAXBUTTON {
        return Ok(false);
    }
    if hit_test != HTCAPTION {
        return Ok(false);
    }

    let packed = packed_screen_point as u32;
    let screen_x = i32::from(packed as u16 as i16);
    let screen_y = i32::from((packed >> 16) as u16 as i16);
    show_system_menu(hwnd, MenuAnchor::Pointer { screen_x, screen_y })?;
    Ok(true)
}

/// Entry point for the composition root's WebView2 `AcceleratorKeyPressed`
/// handler. `mark_handled` must call `SetHandled(true)` on the event args; it is
/// called before TrackPopupMenu enters its modal message loop. `record_intercept`
/// emits `s02-webview2-accelerator`, which the renderer records for UIA evidence.
/// Focus is not filtered, so an input cannot consume Alt+Space as text.
pub fn on_webview2_accelerator<F, R>(
    hwnd: isize,
    virtual_key: u32,
    key_down: bool,
    alt_down: bool,
    repeated: bool,
    mark_handled: F,
    record_intercept: R,
) -> Result<bool, SystemMenuError>
where
    F: FnOnce(),
    R: FnOnce(),
{
    if virtual_key != VK_SPACE || !key_down || !alt_down || repeated {
        return Ok(false);
    }

    mark_handled();
    record_intercept();
    show_system_menu(hwnd, MenuAnchor::WindowTopLeft)?;
    Ok(true)
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WindowMenuState {
    maximized: bool,
    minimized: bool,
    resizable: bool,
}

#[tauri::command]
pub fn s02_open_system_menu_at_origin(window: tauri::WebviewWindow) -> Result<(), String> {
    let hwnd = hwnd_for(&window)?;
    window
        .run_on_main_thread(move || {
            let _ = show_system_menu(hwnd, MenuAnchor::WindowTopLeft);
        })
        .map_err(|_| "could not schedule the S02 system menu on the UI thread".to_owned())
}

#[tauri::command]
fn s02_set_hit_test_regions(
    state: tauri::State<'_, S02State>,
    empty_chrome: HitTestRect,
    maximize_button: HitTestRect,
    scale: f64,
) -> Result<(), String> {
    if !empty_chrome.is_valid()
        || !maximize_button.is_valid()
        || !scale.is_finite()
        || !(0.5..=4.0).contains(&scale)
    {
        return Err(
            "S02 hit-test geometry must be finite, non-empty, and within the supported scale"
                .into(),
        );
    }
    let regions = HitTestRegions {
        empty_chrome,
        maximize_button,
        scale,
    };
    *state
        .regions
        .lock()
        .map_err(|_| "S02 hit-test geometry lock is unavailable".to_owned())? = Some(regions);
    Ok(())
}

#[tauri::command]
fn s02_set_menu_mode(state: tauri::State<'_, S02State>, mode: String) -> Result<(), String> {
    match mode.as_str() {
        "native" => state.kit_mode.store(false, Ordering::Release),
        "kit" => state.kit_mode.store(true, Ordering::Release),
        _ => return Err("S02 menu mode must be 'native' or 'kit'".into()),
    }
    Ok(())
}

#[tauri::command]
pub fn s02_open_system_menu_at_pointer(
    window: tauri::WebviewWindow,
    screen_x: i32,
    screen_y: i32,
) -> Result<(), String> {
    let hwnd = hwnd_for(&window)?;
    window
        .run_on_main_thread(move || {
            let _ = show_system_menu(hwnd, MenuAnchor::Pointer { screen_x, screen_y });
        })
        .map_err(|_| "could not schedule the S02 system menu on the UI thread".to_owned())
}

#[tauri::command]
pub fn s02_dispatch_system_command(
    window: tauri::WebviewWindow,
    command: String,
) -> Result<(), String> {
    let command = match command.as_str() {
        "restore" => SystemCommand::Restore,
        "move" => SystemCommand::Move,
        "size" => SystemCommand::Size,
        "minimize" => SystemCommand::Minimize,
        "maximize" => SystemCommand::Maximize,
        "close" => SystemCommand::Close,
        _ => return Err("unknown S02 system command".to_owned()),
    };
    dispatch_system_command(hwnd_for(&window)?, command).map_err(|error| error.to_string())
}

#[tauri::command]
pub fn s02_set_window_state(window: tauri::WebviewWindow, state: String) -> Result<(), String> {
    let command = match state.as_str() {
        "normal" => SystemCommand::Restore,
        "maximized" => SystemCommand::Maximize,
        "minimized" => SystemCommand::Minimize,
        _ => return Err("unknown S02 window state".to_owned()),
    };
    dispatch_system_command(hwnd_for(&window)?, command).map_err(|error| error.to_string())
}

#[tauri::command]
pub fn s02_close_after_guard(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .destroy()
        .map_err(|_| "the S02 mock close guard could not close the window".to_owned())
}

#[tauri::command]
pub fn s02_get_window_menu_state(window: tauri::WebviewWindow) -> Result<WindowMenuState, String> {
    #[cfg(windows)]
    {
        native::window_menu_state(hwnd_for(&window)?).map_err(|error| error.to_string())
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Err(SystemMenuError::UnsupportedPlatform.to_string())
    }
}

#[cfg(windows)]
fn hwnd_for(window: &tauri::WebviewWindow) -> Result<isize, String> {
    window
        .hwnd()
        .map(|hwnd| hwnd.0 as isize)
        .map_err(|_| SystemMenuError::InvalidWindow.to_string())
}

#[cfg(not(windows))]
fn hwnd_for(_window: &tauri::WebviewWindow) -> Result<isize, String> {
    Err(SystemMenuError::UnsupportedPlatform.to_string())
}

#[cfg(windows)]
#[allow(unsafe_code)]
mod native {
    use super::{
        HTCAPTION, HTMAXBUTTON, HitTestRegions, MenuAnchor, S02State, SC_CLOSE, SC_MAXIMIZE,
        SC_MINIMIZE, SC_MOVE, SC_RESTORE, SC_SIZE, SystemCommand, SystemMenuError, WindowMenuState,
    };
    use std::ffi::c_void;
    use std::sync::atomic::Ordering;

    type Hwnd = *mut c_void;
    type Hmenu = *mut c_void;

    const WM_NULL: u32 = 0x0000;
    const WM_SYSCOMMAND: u32 = 0x0112;
    const TPM_RIGHTBUTTON: u32 = 0x0002;
    const TPM_RETURNCMD: u32 = 0x0100;
    const MF_BYCOMMAND: u32 = 0x0000;
    const MF_GRAYED: u32 = 0x0001;
    const MF_ENABLED: u32 = 0x0000;
    const GWL_STYLE: i32 = -16;
    const WS_THICKFRAME: usize = 0x0004_0000;
    const WM_NCHITTEST: u32 = 0x0084;
    const WM_NCRBUTTONUP: u32 = 0x00A5;
    const WM_NCDESTROY: u32 = 0x0082;
    const WM_SYSKEYDOWN: u32 = 0x0104;
    const VK_MENU: i32 = 0x12;
    const VK_SPACE: usize = 0x20;
    const HTCLIENT: isize = 1;
    const SUBCLASS_ID: usize = 0x5330_3201;

    struct HookContext {
        state: S02State,
    }

    type SubclassProc =
        Option<unsafe extern "system" fn(Hwnd, u32, usize, isize, usize, usize) -> isize>;

    #[repr(C)]
    struct Rect {
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    }

    #[repr(C)]
    struct Point {
        x: i32,
        y: i32,
    }

    // SAFETY: This narrow module validates each HWND, keeps the system-menu
    // handle owned by its window, and uses only documented User32 operations.
    #[link(name = "user32")]
    unsafe extern "system" {
        fn IsWindow(hwnd: Hwnd) -> i32;
        fn GetWindowRect(hwnd: Hwnd, rect: *mut Rect) -> i32;
        fn ClientToScreen(hwnd: Hwnd, point: *mut Point) -> i32;
        fn GetSystemMenu(hwnd: Hwnd, revert: i32) -> Hmenu;
        fn EnableMenuItem(menu: Hmenu, item: u32, flags: u32) -> u32;
        fn TrackPopupMenu(
            menu: Hmenu,
            flags: u32,
            x: i32,
            y: i32,
            reserved: i32,
            hwnd: Hwnd,
            rect: *const Rect,
        ) -> u32;
        fn PostMessageW(hwnd: Hwnd, message: u32, wparam: usize, lparam: isize) -> i32;
        fn SetForegroundWindow(hwnd: Hwnd) -> i32;
        fn IsZoomed(hwnd: Hwnd) -> i32;
        fn IsIconic(hwnd: Hwnd) -> i32;
        fn GetWindowLongPtrW(hwnd: Hwnd, index: i32) -> isize;
        fn GetKeyState(virtual_key: i32) -> i16;
    }

    #[link(name = "comctl32")]
    unsafe extern "system" {
        fn SetWindowSubclass(
            hwnd: Hwnd,
            callback: SubclassProc,
            subclass_id: usize,
            reference_data: usize,
        ) -> i32;
        fn RemoveWindowSubclass(hwnd: Hwnd, callback: SubclassProc, subclass_id: usize) -> i32;
        fn DefSubclassProc(hwnd: Hwnd, message: u32, wparam: usize, lparam: isize) -> isize;
    }

    pub(super) fn install_window_subclass(
        raw_hwnd: isize,
        state: S02State,
    ) -> Result<(), SystemMenuError> {
        let hwnd = as_hwnd(raw_hwnd)?;
        let context = Box::new(HookContext { state });
        let reference_data = Box::into_raw(context) as usize;
        // SAFETY: The context is reclaimed on WM_NCDESTROY. The callback only
        // handles this live main window and otherwise delegates to its chain.
        let installed = unsafe {
            SetWindowSubclass(
                hwnd,
                Some(system_menu_subclass_proc),
                SUBCLASS_ID,
                reference_data,
            )
        };
        if installed == 0 {
            // SAFETY: SetWindowSubclass failed, so ownership was not transferred.
            unsafe { drop(Box::from_raw(reference_data as *mut HookContext)) };
            return Err(SystemMenuError::InvalidWindow);
        }
        Ok(())
    }

    unsafe extern "system" fn system_menu_subclass_proc(
        hwnd: Hwnd,
        message: u32,
        wparam: usize,
        lparam: isize,
        subclass_id: usize,
        reference_data: usize,
    ) -> isize {
        if message == WM_NCHITTEST {
            // Preserve any existing shim result, including HTMAXBUTTON. Only
            // classify the two explicitly registered synthetic regions when
            // the current result is ordinary client space.
            let native = unsafe { DefSubclassProc(hwnd, message, wparam, lparam) };
            if native == HTMAXBUTTON {
                return native;
            }
            let context = unsafe { &*(reference_data as *const HookContext) };
            if let Some(regions) = read_regions(&context.state) {
                if let Some((x, y)) = client_point(hwnd, lparam) {
                    if regions
                        .maximize_button
                        .contains(x / regions.scale, y / regions.scale)
                    {
                        return HTMAXBUTTON;
                    }
                    if regions
                        .empty_chrome
                        .contains(x / regions.scale, y / regions.scale)
                    {
                        if context.state.kit_mode.load(Ordering::Acquire) {
                            return HTCLIENT;
                        }
                        return HTCAPTION;
                    }
                }
            }
            if native == HTCAPTION {
                return native;
            }
            return native;
        }

        let context = unsafe { &*(reference_data as *const HookContext) };
        if message == WM_NCRBUTTONUP
            && !context.state.kit_mode.load(Ordering::Acquire)
            && super::on_non_client_right_button_up(hwnd as isize, wparam as isize, lparam)
                .unwrap_or(false)
        {
            return 0;
        }

        if message == WM_NCRBUTTONUP && wparam as isize == HTMAXBUTTON {
            // Snap's maximize hit target stays with the OS window procedure.
            return unsafe { DefSubclassProc(hwnd, message, wparam, lparam) };
        }

        let is_repeat = (lparam as u32 & (1 << 30)) != 0;
        if message == WM_SYSKEYDOWN
            && wparam == VK_SPACE
            && !is_repeat
            && !context.state.kit_mode.load(Ordering::Acquire)
        {
            // The HWND path covers environments where WebView2 does not expose
            // its AcceleratorKeyPressed hook; the dedicated callback remains
            // available to an exact WebView2 event adapter.
            if unsafe { GetKeyState(VK_MENU) } < 0
                && show_system_menu(hwnd as isize, MenuAnchor::WindowTopLeft).is_ok()
            {
                return 0;
            }
        }

        let result = unsafe { DefSubclassProc(hwnd, message, wparam, lparam) };
        if message == WM_NCDESTROY {
            // SAFETY: This hook owns the context and WM_NCDESTROY runs once.
            unsafe {
                let _ = RemoveWindowSubclass(hwnd, Some(system_menu_subclass_proc), subclass_id);
                drop(Box::from_raw(reference_data as *mut HookContext));
            }
        }
        result
    }

    fn read_regions(state: &S02State) -> Option<HitTestRegions> {
        state.regions.lock().ok().and_then(|regions| *regions)
    }

    fn client_point(hwnd: Hwnd, packed: isize) -> Option<(f64, f64)> {
        let mut origin = Point { x: 0, y: 0 };
        // SAFETY: `hwnd` is live and `origin` is a writable POINT in client coordinates.
        if unsafe { ClientToScreen(hwnd, &mut origin) } == 0 {
            return None;
        }
        let (screen_x, screen_y) = signed_screen_point(packed)?;
        Some(((screen_x - origin.x) as f64, (screen_y - origin.y) as f64))
    }

    fn signed_screen_point(packed: isize) -> Option<(i32, i32)> {
        let value = packed as u32;
        let x = i32::from(value as u16 as i16);
        let y = i32::from((value >> 16) as u16 as i16);
        Some((x, y))
    }

    pub(super) fn show_system_menu(
        raw_hwnd: isize,
        anchor: MenuAnchor,
    ) -> Result<Option<SystemCommand>, SystemMenuError> {
        let hwnd = as_hwnd(raw_hwnd)?;
        // SAFETY: `as_hwnd` rejects a null or non-window handle. The menu is
        // borrowed from this live window and is not retained after TrackPopupMenu.
        let menu = unsafe { GetSystemMenu(hwnd, 0) };
        if menu.is_null() {
            return Err(SystemMenuError::MenuUnavailable);
        }

        update_enabled_items(hwnd, menu)?;
        let (screen_x, screen_y) = match anchor {
            MenuAnchor::Pointer { screen_x, screen_y } => (screen_x, screen_y),
            MenuAnchor::WindowTopLeft => window_top_left(hwnd)?,
        };

        // SAFETY: The owner HWND and menu handle remain valid for this
        // synchronous call. Coordinates are physical screen coordinates. The
        // return-command flag returns an item id for explicit WM_SYSCOMMAND
        // dispatch below, preserving the normal window procedure path.
        unsafe {
            let _ = SetForegroundWindow(hwnd);
            let selected = TrackPopupMenu(
                menu,
                TPM_RETURNCMD | TPM_RIGHTBUTTON,
                screen_x,
                screen_y,
                0,
                hwnd,
                std::ptr::null(),
            );
            let command = SystemCommand::from_win32_id(selected);
            if let Some(command) = command {
                post_system_command(hwnd, command)?;
            }
            let _ = PostMessageW(hwnd, WM_NULL, 0, 0);
            Ok(command)
        }
    }

    pub(super) fn dispatch_system_command(
        raw_hwnd: isize,
        command: SystemCommand,
    ) -> Result<(), SystemMenuError> {
        let hwnd = as_hwnd(raw_hwnd)?;
        post_system_command(hwnd, command)
    }

    pub(super) fn window_menu_state(raw_hwnd: isize) -> Result<WindowMenuState, SystemMenuError> {
        let hwnd = as_hwnd(raw_hwnd)?;
        // SAFETY: `hwnd` was checked by `as_hwnd`; these functions only query
        // state owned by the window manager.
        let (maximized, minimized, style) = unsafe {
            (
                IsZoomed(hwnd) != 0,
                IsIconic(hwnd) != 0,
                GetWindowLongPtrW(hwnd, GWL_STYLE) as usize,
            )
        };
        Ok(WindowMenuState {
            maximized,
            minimized,
            resizable: style & WS_THICKFRAME != 0,
        })
    }

    fn update_enabled_items(hwnd: Hwnd, menu: Hmenu) -> Result<(), SystemMenuError> {
        let state = window_menu_state(hwnd as isize)?;
        set_enabled(menu, SC_RESTORE, state.maximized || state.minimized)?;
        set_enabled(menu, SC_MOVE, !state.maximized && !state.minimized)?;
        set_enabled(
            menu,
            SC_SIZE,
            state.resizable && !state.maximized && !state.minimized,
        )?;
        set_enabled(menu, SC_MINIMIZE, !state.minimized)?;
        set_enabled(
            menu,
            SC_MAXIMIZE,
            state.resizable && !state.maximized && !state.minimized,
        )?;
        set_enabled(menu, SC_CLOSE, true)?;
        Ok(())
    }

    fn set_enabled(menu: Hmenu, command: u32, enabled: bool) -> Result<(), SystemMenuError> {
        let state = if enabled { MF_ENABLED } else { MF_GRAYED };
        // SAFETY: The menu is a live handle returned by GetSystemMenu for the
        // validated owner window. Command ids are the documented SC_* ids.
        let previous = unsafe { EnableMenuItem(menu, command, MF_BYCOMMAND | state) };
        if previous == u32::MAX {
            return Err(SystemMenuError::MenuStateUnavailable);
        }
        Ok(())
    }

    fn window_top_left(hwnd: Hwnd) -> Result<(i32, i32), SystemMenuError> {
        let mut rect = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        // SAFETY: `rect` is a writable RECT and `hwnd` is valid for this call.
        let ok = unsafe { GetWindowRect(hwnd, &mut rect) };
        if ok == 0 {
            return Err(SystemMenuError::WindowBoundsUnavailable);
        }
        Ok((rect.left, rect.top))
    }

    fn post_system_command(hwnd: Hwnd, command: SystemCommand) -> Result<(), SystemMenuError> {
        // SAFETY: The HWND was validated, and the command value is selected
        // from the closed SystemCommand enum. WM_SYSCOMMAND reaches the normal
        // host close guard for SC_CLOSE.
        let ok = unsafe {
            PostMessageW(
                hwnd,
                WM_SYSCOMMAND,
                (command.win32_id() & 0xFFF0) as usize,
                0,
            )
        };
        if ok == 0 {
            return Err(SystemMenuError::CommandDispatchFailed);
        }
        Ok(())
    }

    fn as_hwnd(raw_hwnd: isize) -> Result<Hwnd, SystemMenuError> {
        let hwnd = raw_hwnd as Hwnd;
        if hwnd.is_null() {
            return Err(SystemMenuError::InvalidWindow);
        }
        // SAFETY: IsWindow accepts an opaque HWND and does not dereference the
        // caller's memory. It is used only to reject stale handles.
        let valid = unsafe { IsWindow(hwnd) };
        if valid == 0 {
            return Err(SystemMenuError::InvalidWindow);
        }
        Ok(hwnd)
    }
}
