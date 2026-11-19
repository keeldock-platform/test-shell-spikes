//! S10 has no native host command; the picker is exercised in the webview.

/// Registers the empty S10 host plugin required by the shared feature contract.
///
/// It exposes no commands and does not panic.
pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri::plugin::Builder::new("s10-colour-input").build()
}
