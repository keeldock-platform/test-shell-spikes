//! Synthetic Settings-window spike. The coordinator registers its plugin and
//! one shared window-state/dialog plugin instance through the host scaffold.

use std::sync::Mutex;

use serde::Serialize;
use tauri::{
    AppHandle, Emitter, Manager, Runtime, WebviewUrl, WebviewWindow, WindowEvent, Wry,
    plugin::{Builder as PluginBuilder, TauriPlugin},
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_window_state::{
    AppHandleExt as WindowStateAppHandleExt, Builder as WindowStateBuilder, StateFlags,
};

pub const SETTINGS_LABEL: &str = "settings";
pub const MAIN_LABEL: &str = "main";
const SETTINGS_TITLE: &str = "Settings";
const INITIAL_WIDTH: f64 = 1040.0;
const INITIAL_HEIGHT: f64 = 660.0;
const MIN_WIDTH_PROPOSAL: f64 = 760.0;
const MIN_HEIGHT_PROPOSAL: f64 = 500.0;

const SETTINGS_COMMANDS: &[&str] = &[
    "s08_read_settings",
    "s08_write_setting",
    "s08_settings_schema",
    "s08_settings_search",
    "s08_update_shortcut",
    "s08_request_step_up",
    "s08_import_license",
    "s08_export_data",
    "s08_import_data",
    "s08_vault_passphrase_action",
    "s08_vault_recovery_action",
    "s08_project_settings",
    "s08_team_settings",
    "s08_get_view_state",
    "s08_set_view_state",
    "s08_window_geometry",
    "s08_hide_settings",
];

const MAIN_COMMANDS: &[&str] = &[
    "s08_open_settings",
    "s08_test_destroy_settings",
    "s08_test_lock_vault",
    "s08_test_unlock_vault",
];

const DENIED_SENTINELS: &[&str] = &[
    "s08_sentinel_tool_command",
    "s08_sentinel_pane_command",
    "s08_sentinel_tab_project_open",
    "s08_sentinel_mcp_command",
    "s08_sentinel_marketplace_command",
    "s08_sentinel_file_grant",
];

/// Use this exact flag set for the one app-wide window-state plugin instance.
/// The settings window's label is kept as its independent persistence key.
pub fn window_state_flags() -> StateFlags {
    StateFlags::all().difference(StateFlags::VISIBLE)
}

/// The coordinator registers this once because shared `lib.rs` is scaffold owned.
pub fn window_state_plugin<R: Runtime>() -> tauri::plugin::TauriPlugin<R> {
    WindowStateBuilder::new()
        .with_state_flags(window_state_flags())
        .build()
}

#[derive(Debug, Serialize, thiserror::Error)]
#[serde(tag = "code", rename_all = "snake_case")]
pub enum S08Error {
    #[error("request is not in the caller window's S08 capability")]
    Forbidden,
    #[error("settings window is locked by the mock vault state")]
    Locked,
    #[error("input is outside the mock contract")]
    InvalidInput,
    #[error("mock settings state is unavailable")]
    StateUnavailable,
    #[error("native window operation failed")]
    NativeWindow,
    #[error("window-state plugin operation failed")]
    WindowState,
    #[error("the S08 state was already registered")]
    AlreadyInitialized,
}

#[derive(Default)]
pub struct S08HostState {
    open_gate: Mutex<()>,
    mock: Mutex<MockSettings>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MockSettings {
    theme: String,
    density: String,
    mock_counter: u32,
    locked: bool,
    view: MockViewState,
}

impl Default for MockSettings {
    fn default() -> Self {
        Self {
            theme: "system".to_owned(),
            density: "comfortable".to_owned(),
            mock_counter: 0,
            locked: false,
            view: MockViewState::default(),
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MockViewState {
    page: String,
    scroll_top: u32,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MockWindowGeometry {
    label: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    scale_factor: f64,
}

impl Default for MockViewState {
    fn default() -> Self {
        Self {
            page: "General".to_owned(),
            scroll_top: 0,
        }
    }
}

pub fn init<R: Runtime>(app: &AppHandle<R>) -> Result<(), S08Error> {
    if app.manage(S08HostState::default()) {
        Ok(())
    } else {
        Err(S08Error::AlreadyInitialized)
    }
}

/// Register this lane as an isolated Tauri plugin. All S08 invoke commands are
/// namespaced as `plugin:s08-settings|<command>` and remain capability-gated.
pub fn plugin() -> TauriPlugin<Wry> {
    PluginBuilder::new("s08-settings")
        .invoke_handler(tauri::generate_handler![
            s08_open_settings,
            s08_read_settings,
            s08_write_setting,
            s08_settings_schema,
            s08_settings_search,
            s08_update_shortcut,
            s08_request_step_up,
            s08_import_license,
            s08_export_data,
            s08_import_data,
            s08_vault_passphrase_action,
            s08_vault_recovery_action,
            s08_project_settings,
            s08_team_settings,
            s08_get_view_state,
            s08_set_view_state,
            s08_window_geometry,
            s08_hide_settings,
            s08_sentinel_tool_command,
            s08_sentinel_pane_command,
            s08_sentinel_tab_project_open,
            s08_sentinel_mcp_command,
            s08_sentinel_marketplace_command,
            s08_sentinel_file_grant,
            s08_test_destroy_settings,
            s08_test_lock_vault,
            s08_test_unlock_vault
        ])
        .setup(|app, _api| {
            init(app)?;
            Ok(())
        })
        .on_event(|app, event| {
            if let tauri::RunEvent::WindowEvent { label, event, .. } = event {
                if let Some(window) = app.get_webview_window(label) {
                    on_window_event(&window, event);
                }
            }
        })
        .build()
}

fn host_allows(window_label: &str, command: &str) -> bool {
    match window_label {
        SETTINGS_LABEL => {
            SETTINGS_COMMANDS.contains(&command) && !DENIED_SENTINELS.contains(&command)
        }
        MAIN_LABEL => MAIN_COMMANDS.contains(&command),
        _ => false,
    }
}

fn require_command(window: &WebviewWindow, command: &str) -> Result<(), S08Error> {
    if host_allows(window.label(), command) {
        Ok(())
    } else {
        Err(S08Error::Forbidden)
    }
}

fn reject_sentinel(window: &WebviewWindow, command: &str) -> Result<(), S08Error> {
    require_command(window, command)?;
    Err(S08Error::Forbidden)
}

fn mock_lock(state: &S08HostState) -> Result<std::sync::MutexGuard<'_, MockSettings>, S08Error> {
    state.mock.lock().map_err(|_| S08Error::StateUnavailable)
}

fn open_lock(state: &S08HostState) -> Result<std::sync::MutexGuard<'_, ()>, S08Error> {
    state
        .open_gate
        .lock()
        .map_err(|_| S08Error::StateUnavailable)
}

/// Open once from the main window. The caller's label is checked in Rust even
/// when the Tauri ACL has already rejected an out-of-capability invocation.
#[tauri::command]
pub async fn s08_open_settings(
    app: AppHandle,
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
) -> Result<(), S08Error> {
    require_command(&window, "s08_open_settings")?;
    if cfg!(not(target_os = "macos")) {
        return Err(S08Error::Forbidden);
    }
    if mock_lock(&state)?.locked {
        return Err(S08Error::Locked);
    }

    let _open_guard = open_lock(&state)?;
    if let Some(settings) = app.get_webview_window(SETTINGS_LABEL) {
        settings.show().map_err(|_| S08Error::NativeWindow)?;
        settings.set_focus().map_err(|_| S08Error::NativeWindow)?;
        return Ok(());
    }

    let settings = tauri::WebviewWindowBuilder::new(
        &app,
        SETTINGS_LABEL,
        WebviewUrl::App("index.html?spike=s08&window=settings".into()),
    )
    .title(SETTINGS_TITLE)
    .inner_size(INITIAL_WIDTH, INITIAL_HEIGHT)
    .min_inner_size(MIN_WIDTH_PROPOSAL, MIN_HEIGHT_PROPOSAL)
    .resizable(true)
    .decorations(true)
    .build()
    .map_err(|_| S08Error::NativeWindow)?;

    settings.set_focus().map_err(|_| S08Error::NativeWindow)
}

#[tauri::command]
pub async fn s08_read_settings(
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
) -> Result<MockSettings, S08Error> {
    require_command(&window, "s08_read_settings")?;
    let mock = mock_lock(&state)?;
    if mock.locked {
        return Err(S08Error::Locked);
    }
    Ok(mock.clone())
}

#[tauri::command]
pub async fn s08_write_setting(
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
    key: String,
    value: String,
) -> Result<(), S08Error> {
    require_command(&window, "s08_write_setting")?;
    if value.len() > 80 {
        return Err(S08Error::InvalidInput);
    }
    let mut mock = mock_lock(&state)?;
    if mock.locked {
        return Err(S08Error::Locked);
    }
    match (key.as_str(), value.as_str()) {
        ("theme", "system" | "light" | "dark") => mock.theme = value,
        ("density", "comfortable" | "compact") => mock.density = value,
        _ => return Err(S08Error::InvalidInput),
    }
    mock.mock_counter = mock.mock_counter.saturating_add(1);
    Ok(())
}

#[tauri::command]
pub async fn s08_settings_schema(window: WebviewWindow) -> Result<Vec<&'static str>, S08Error> {
    require_command(&window, "s08_settings_schema")?;
    Ok(vec![
        "theme:system|light|dark",
        "density:comfortable|compact",
    ])
}

#[tauri::command]
pub async fn s08_settings_search(
    window: WebviewWindow,
    query: String,
) -> Result<Vec<&'static str>, S08Error> {
    require_command(&window, "s08_settings_search")?;
    if query.len() > 80 {
        return Err(S08Error::InvalidInput);
    }
    let query = query.to_lowercase();
    Ok([
        "General",
        "Appearance",
        "Security",
        "Data and storage",
        "Team",
    ]
    .into_iter()
    .filter(|page| page.to_lowercase().contains(&query))
    .collect())
}

#[tauri::command]
pub async fn s08_update_shortcut(
    window: WebviewWindow,
    command_id: String,
    chord: String,
) -> Result<(), S08Error> {
    require_command(&window, "s08_update_shortcut")?;
    if command_id != "settings.open" || chord.len() > 40 || chord.is_empty() {
        return Err(S08Error::InvalidInput);
    }
    Ok(())
}

#[tauri::command]
pub async fn s08_request_step_up(app: AppHandle, window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_request_step_up")?;
    let result_app = app.clone();
    app.dialog()
        .message("This is a synthetic step-up request for the S08 window test.")
        .title("Mock confirmation")
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Continue (mock)".to_owned(),
            "Cancel".to_owned(),
        ))
        .parent(&window)
        .show(move |accepted| {
            let _ = result_app.emit_to(SETTINGS_LABEL, "s08:step-up-result", accepted);
        });
    Ok(())
}

fn open_native_import_picker(
    app: &AppHandle,
    window: &WebviewWindow,
    event: &'static str,
    label: &'static str,
) {
    let result_app = app.clone();
    app.dialog()
        .file()
        .add_filter(label, &["json"])
        .set_parent(window)
        .pick_file(move |selection| {
            let _ = result_app.emit_to(SETTINGS_LABEL, event, selection.is_some());
        });
}

#[tauri::command]
pub async fn s08_import_license(app: AppHandle, window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_import_license")?;
    open_native_import_picker(
        &app,
        &window,
        "s08:license-picker-result",
        "Synthetic licence",
    );
    Ok(())
}

#[tauri::command]
pub async fn s08_export_data(app: AppHandle, window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_export_data")?;
    let result_app = app.clone();
    app.dialog()
        .file()
        .set_file_name("s08-sample-export.json")
        .set_parent(&window)
        .save_file(move |selection| {
            let _ = result_app.emit_to(
                SETTINGS_LABEL,
                "s08:export-picker-result",
                selection.is_some(),
            );
        });
    Ok(())
}

#[tauri::command]
pub async fn s08_import_data(app: AppHandle, window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_import_data")?;
    open_native_import_picker(&app, &window, "s08:import-picker-result", "Synthetic data");
    Ok(())
}

#[tauri::command]
pub async fn s08_vault_passphrase_action(window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_vault_passphrase_action")?;
    Ok(())
}

#[tauri::command]
pub async fn s08_vault_recovery_action(window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_vault_recovery_action")?;
    Ok(())
}

#[tauri::command]
pub async fn s08_project_settings(window: WebviewWindow) -> Result<&'static str, S08Error> {
    require_command(&window, "s08_project_settings")?;
    Ok("Synthetic project settings")
}

#[tauri::command]
pub async fn s08_team_settings(window: WebviewWindow) -> Result<&'static str, S08Error> {
    require_command(&window, "s08_team_settings")?;
    Ok("Synthetic team settings")
}

#[tauri::command]
pub async fn s08_get_view_state(
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
) -> Result<MockViewState, S08Error> {
    require_command(&window, "s08_get_view_state")?;
    Ok(mock_lock(&state)?.view.clone())
}

#[tauri::command]
pub async fn s08_set_view_state(
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
    page: String,
    scroll_top: u32,
) -> Result<(), S08Error> {
    require_command(&window, "s08_set_view_state")?;
    const PAGES: &[&str] = &[
        "General",
        "Appearance",
        "Security",
        "Data and storage",
        "Team",
    ];
    if !PAGES.contains(&page.as_str()) || scroll_top > 100_000 {
        return Err(S08Error::InvalidInput);
    }
    mock_lock(&state)?.view = MockViewState { page, scroll_top };
    Ok(())
}

#[tauri::command]
pub async fn s08_window_geometry(window: WebviewWindow) -> Result<MockWindowGeometry, S08Error> {
    require_command(&window, "s08_window_geometry")?;
    let scale_factor = window.scale_factor().map_err(|_| S08Error::NativeWindow)?;
    let inner = window
        .inner_size()
        .map_err(|_| S08Error::NativeWindow)?
        .to_logical::<f64>(scale_factor);
    let origin = window
        .outer_position()
        .map_err(|_| S08Error::NativeWindow)?
        .to_logical::<f64>(scale_factor);
    Ok(MockWindowGeometry {
        label: window.label().to_owned(),
        x: origin.x,
        y: origin.y,
        width: inner.width,
        height: inner.height,
        scale_factor,
    })
}

#[tauri::command]
pub async fn s08_hide_settings(window: WebviewWindow) -> Result<(), S08Error> {
    require_command(&window, "s08_hide_settings")?;
    window.hide().map_err(|_| S08Error::NativeWindow)
}

#[tauri::command]
pub async fn s08_sentinel_tool_command(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_tool_command")
}

#[tauri::command]
pub async fn s08_sentinel_pane_command(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_pane_command")
}

#[tauri::command]
pub async fn s08_sentinel_tab_project_open(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_tab_project_open")
}

#[tauri::command]
pub async fn s08_sentinel_mcp_command(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_mcp_command")
}

#[tauri::command]
pub async fn s08_sentinel_marketplace_command(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_marketplace_command")
}

#[tauri::command]
pub async fn s08_sentinel_file_grant(window: WebviewWindow) -> Result<(), S08Error> {
    reject_sentinel(&window, "s08_sentinel_file_grant")
}

/// Test-only main-window command used by the native harness to exercise plugin
/// restoration after destroying and recreating the lazy Settings webview.
#[tauri::command]
pub async fn s08_test_destroy_settings(
    app: AppHandle,
    window: WebviewWindow,
) -> Result<(), S08Error> {
    require_command(&window, "s08_test_destroy_settings")?;
    destroy_settings(&app)
}

/// Synthetic lock signal only: it makes no assertion about a real vault.
#[tauri::command]
pub async fn s08_test_lock_vault(
    app: AppHandle,
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
) -> Result<(), S08Error> {
    require_command(&window, "s08_test_lock_vault")?;
    mock_lock(&state)?.locked = true;
    destroy_settings(&app)
}

#[tauri::command]
pub async fn s08_test_unlock_vault(
    window: WebviewWindow,
    state: tauri::State<'_, S08HostState>,
) -> Result<(), S08Error> {
    require_command(&window, "s08_test_unlock_vault")?;
    mock_lock(&state)?.locked = false;
    Ok(())
}

fn destroy_settings(app: &AppHandle) -> Result<(), S08Error> {
    if let Some(settings) = app.get_webview_window(SETTINGS_LABEL) {
        app.save_window_state(window_state_flags())
            .map_err(|_| S08Error::WindowState)?;
        settings.destroy().map_err(|_| S08Error::NativeWindow)?;
    }
    Ok(())
}

/// Handles close-to-hide and main inactive-state tracking for this plugin.
pub fn on_window_event(window: &WebviewWindow, event: &WindowEvent) {
    match event {
        WindowEvent::CloseRequested { api, .. } if window.label() == SETTINGS_LABEL => {
            api.prevent_close();
            let _ = window.hide();
        }
        WindowEvent::Focused(true) if window.label() == SETTINGS_LABEL => {
            let _ = window
                .app_handle()
                .emit_to(MAIN_LABEL, "s08:window-activity", false);
        }
        WindowEvent::Focused(true) if window.label() == MAIN_LABEL => {
            let _ = window
                .app_handle()
                .emit_to(MAIN_LABEL, "s08:window-activity", true);
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::{
        DENIED_SENTINELS, MAIN_COMMANDS, MAIN_LABEL, SETTINGS_COMMANDS, SETTINGS_LABEL, host_allows,
    };

    #[test]
    fn host_allowlist_matches_only_settings_window_commands() {
        for command in SETTINGS_COMMANDS {
            assert!(host_allows(SETTINGS_LABEL, command));
        }
        for command in DENIED_SENTINELS {
            assert!(!host_allows(SETTINGS_LABEL, command));
        }
        for command in MAIN_COMMANDS {
            assert!(!host_allows(SETTINGS_LABEL, command));
        }
        for command in SETTINGS_COMMANDS {
            assert!(!host_allows(MAIN_LABEL, command));
        }
        assert!(!host_allows("unrecognized-window", "s08_read_settings"));
    }

    #[test]
    fn window_state_persistence_never_restores_visibility() {
        assert!(!super::window_state_flags().contains(super::StateFlags::VISIBLE));
        assert!(super::window_state_flags().contains(super::StateFlags::SIZE));
        assert!(super::window_state_flags().contains(super::StateFlags::POSITION));
    }
}
