#[cfg(feature = "spike-s01")]
pub mod s01_traffic_lights;
#[cfg(feature = "spike-s02")]
pub mod s02_system_menu;
#[cfg(feature = "spike-s03")]
pub mod s03_gnome_menu;
#[cfg(feature = "spike-s08")]
pub mod s08_settings;
#[cfg(feature = "spike-s10")]
pub mod s10_colour_input;
#[cfg(feature = "spike-s11")]
pub mod s11_accent;

use tauri::{Builder, Wry};

pub fn selected_id() -> Option<&'static str> {
    match std::env::var("SHELL_SPIKE_ID").ok().as_deref() {
        Some("s01") if cfg!(feature = "spike-s01") => Some("s01"),
        Some("s02") if cfg!(feature = "spike-s02") => Some("s02"),
        Some("s03") if cfg!(feature = "spike-s03") => Some("s03"),
        Some("s08") if cfg!(feature = "spike-s08") => Some("s08"),
        Some("s10") if cfg!(feature = "spike-s10") => Some("s10"),
        Some("s11") if cfg!(feature = "spike-s11") => Some("s11"),
        _ => None,
    }
}

pub fn validate_selection() -> Result<(), String> {
    let requested = std::env::var("SHELL_SPIKE_ID").ok();
    match requested.as_deref() {
        None => Ok(()),
        Some("s01") if cfg!(feature = "spike-s01") => Ok(()),
        Some("s02") if cfg!(feature = "spike-s02") => Ok(()),
        Some("s03") if cfg!(feature = "spike-s03") => Ok(()),
        Some("s08") if cfg!(feature = "spike-s08") => Ok(()),
        Some("s10") if cfg!(feature = "spike-s10") => Ok(()),
        Some("s11") if cfg!(feature = "spike-s11") => Ok(()),
        Some(id) => Err(format!(
            "SHELL_SPIKE_ID {id:?} is not enabled in this build"
        )),
    }
}

pub fn register(mut builder: Builder<Wry>) -> Builder<Wry> {
    #[cfg(feature = "spike-s01")]
    if selected_id() == Some("s01") {
        builder = builder.plugin(s01_traffic_lights::plugin());
    }
    #[cfg(feature = "spike-s02")]
    if selected_id() == Some("s02") {
        builder = builder.plugin(s02_system_menu::plugin());
    }
    #[cfg(feature = "spike-s03")]
    if selected_id() == Some("s03") {
        builder = builder.plugin(s03_gnome_menu::plugin());
    }
    #[cfg(feature = "spike-s08")]
    if selected_id() == Some("s08") {
        builder = builder.plugin(tauri_plugin_dialog::init());
        builder = builder.plugin(s08_settings::window_state_plugin());
        builder = builder.plugin(s08_settings::plugin());
    }
    #[cfg(feature = "spike-s10")]
    if selected_id() == Some("s10") {
        builder = builder.plugin(s10_colour_input::plugin());
    }
    #[cfg(feature = "spike-s11")]
    if selected_id() == Some("s11") {
        builder = builder.plugin(s11_accent::plugin());
    }
    builder
}
